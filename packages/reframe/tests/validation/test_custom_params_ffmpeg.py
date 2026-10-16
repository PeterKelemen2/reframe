"""Custom encoder parameters that read or write files, checked with the real encoders
(core-complete review R5-1; decision 0035 "Follow-up (core-complete review, 2026-10-16)";
testdata/README.md "Advanced encoder options (C-6, complete option sets)").

Each run encodes a few frames with FFmpeg directly (the parameter written as the command
builder writes it), with a target path in ``tmp_path`` and ``tmp_path / "cwd"`` as the working
folder, and checks what the encoder did with the file; then validation must refuse the
parameter. The allow-list of the encoders without a params argument is checked against this
build's ``ffmpeg -h full`` and ``ffmpeg -h encoder=<id>``.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from reframe.capabilities.parse import parse_encoder_help
from reframe.definitions import load_definitions
from reframe.definitions.custom_params import custom_param_rules
from reframe.models import CapabilitySnapshot, ConstantQuality, VideoSettings
from reframe.validation.video import video_custom_param_issues

pytestmark = pytest.mark.needs_ffmpeg

DEFS = load_definitions()
_REFUSED = re.compile(r"Unknown option|Error parsing option|Unrecognized option")


def _ffmpeg() -> str:
    from reframe_testing import media

    found = media.find_ffmpeg()
    assert found is not None
    return found


def _encode(
    encoder: str, params: str, cwd: Path, frames: int = 3
) -> subprocess.CompletedProcess[str]:
    """``params`` the way the builder writes custom parameters: the params argument, or
    ``-<name>:v:0 <value>`` for an encoder without one."""
    definition = DEFS.video_encoders[encoder]
    argv = [_ffmpeg(), "-hide_banner", "-nostdin", "-f", "lavfi", "-i",
            "testsrc2=size=192x108:rate=25", "-frames:v", str(frames), "-c:v", encoder]  # fmt: skip
    if encoder == "libvpx-vp9":
        argv += ["-crf", "30", "-b:v", "0"]
    if definition.params_arg is not None:
        argv += [definition.params_arg, params]
    else:
        for entry in params.split(":"):
            name, _, value = entry.partition("=")
            argv += [f"-{name}:v:0", value]
    argv += ["-f", "null", "-"]
    return subprocess.run(argv, capture_output=True, text=True, timeout=120, cwd=cwd, check=False)


def _refused_by_validation(encoder: str, params: str) -> bool:
    video = VideoSettings(encoder=encoder, custom_params=params)
    if encoder == "libvpx-vp9":
        video.rate_control = ConstantQuality(value=30)
    codes = {i.code for i in video_custom_param_issues(video, CapabilitySnapshot(), DEFS)}
    return codes == {"encoder.custom_param_file"}


@pytest.mark.parametrize(
    ("encoder", "params", "written"),
    [
        # The file named by the key is written.
        ("libx265", "csv={target}", "target"),
        ("libx265", "analysis-save={target}", "target"),
        ("libx265", "analysis_save={target}", "target"),
        ("libx265", "--csv={target}", "target"),
        ("libx265", "stats={target}:pass=1", "target"),
        ("libx264", "dump-yuv={target}", "target"),
        ("libx264", "stats={target}:pass=1", "target"),
        ("libvpx-vp9", "vstats_file={target}", "target"),
        ("libvpx-vp9", "progress={target}", "target"),
        ("libvpx-vp9", "stats_enc_post={target}", "target"),
        ("libvpx-vp9", "print_graphs_file={target}", "target"),
        # A file in the working folder.
        ("libx265", "pass=1", "x265_2pass.log"),
        ("libx265", "no-csv={target}", "true"),  # read as csv=true
        ("libx264", "pass=1", "x264_2pass.log"),
        ("libx264", "nostats={target}:pass=1", "true"),  # read as stats=true
        ("libvpx-vp9", "pass=1", "ffmpeg2pass-0.log"),
    ],
)
def test_a_parameter_that_writes_a_file(
    tmp_path: Path, encoder: str, params: str, written: str
) -> None:
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    target = tmp_path / "target.bin"
    text = params.format(target=target)
    result = _encode(encoder, text, cwd)
    assert result.returncode == 0, result.stderr[-1500:]
    if written == "target":
        assert target.is_file()
        assert target.stat().st_size > 0
    else:
        assert written in [p.name for p in cwd.iterdir()]
    assert _refused_by_validation(encoder, text)


@pytest.mark.parametrize(
    ("encoder", "key", "message"),
    [
        ("libx264", "cqmfile", "can't open file"),
        ("libx265", "scaling-list", "can't read matrix"),
        ("libx265", "lambda-file", "lambda file is incomplete"),
        ("libx265", "analysis-load", "Error reading analysis data"),
        ("libx265", "aom-film-grain", "Error reading Aom FilmGrain characteristics"),
    ],
)
def test_a_parameter_that_reads_a_file(
    tmp_path: Path, encoder: str, key: str, message: str
) -> None:
    junk = tmp_path / "junk.txt"
    junk.write_text("junk\n")
    path = junk if key != "cqmfile" else tmp_path / "missing.txt"
    result = _encode(encoder, f"{key}={path}", tmp_path)
    assert message in result.stderr, result.stderr[-1500:]
    assert _refused_by_validation(encoder, f"{key}={path}")


#: The file keys the library takes today; the others of ``custom_params.toml`` are refused by
#: the library ("Unknown option" / "Error parsing option": file options of the encoders' own
#: programs, refused by Reframe in case a later library takes them).
ACCEPTED = {
    "libx264": {"stats", "dump-yuv", "pass", "cqmfile", "opencl-clbin"},
    "libx265": {
        "csv",
        "analysis-save",
        "analysis-reuse-file",
        "stats",
        "pass",
        "analysis-load",
        "scaling-list",
        "lambda-file",
        "dhdr10-info",
        "nalu-file",
        "film-grain",
        "aom-film-grain",
        "fovea-gaze-file",
    },
    "libsvtav1": set(),
}


@pytest.mark.parametrize("encoder", sorted(ACCEPTED))
def test_which_file_keys_the_library_takes(tmp_path: Path, encoder: str) -> None:
    missing = tmp_path / "no-such-folder" / "file"
    taken: set[str] = set()
    for key in custom_param_rules().file_keys[encoder]:
        value = "1" if key == "pass" else str(missing)
        result = _encode(encoder, f"{key}={value}", tmp_path, frames=1)
        if not any(_REFUSED.search(line) for line in result.stderr.splitlines()):
            taken.add(key)
    assert taken == ACCEPTED[encoder]


# --------------------------------------------------------------------------- the allow-list


def _help(*args: str) -> str:
    result = subprocess.run(
        [_ffmpeg(), "-hide_banner", "-h", *args], capture_output=True, text=True, timeout=60
    )
    return result.stdout


def test_the_generic_options_and_ffmpegs_own_options() -> None:
    """The recorded AVCodecContext options are this build's (flags ``E..V``), and no name of
    the allow-list is one of FFmpeg's own options (which FFmpeg reads first), except three that
    set the codec option of the same name."""
    text = _help("full")
    own_part, _, rest = text.partition("AVCodecContext AVOptions:")
    codec_part = rest.split("\n\n", 1)[0]
    generic = {
        m.group(1) for m in re.finditer(r"^  -(\S+)\s+<\w+>\s+E..V", codec_part, re.MULTILINE)
    }
    own = set(re.findall(r"^-([A-Za-z0-9_?-]+)", own_part, re.MULTILINE))
    rules = custom_param_rules()
    assert rules.codec_options <= generic
    allowed = rules.codec_options.union(*rules.private_options.values())
    assert allowed & own == {"aspect", "b", "profile"}
    for name in ("vstats_file", "progress", "passlogfile", "pass", "stats_enc_post", "sdp_file"):
        assert name in own
        assert name in rules.file_options


@pytest.mark.parametrize("encoder", sorted(custom_param_rules().private_options))
def test_the_recorded_private_options_cover_this_build(encoder: str) -> None:
    parsed = parse_encoder_help(_help(f"encoder={encoder}"))
    if parsed is None:
        pytest.skip(f"{encoder} is not in this FFmpeg build")
    assert set(parsed.private_options) <= custom_param_rules().private_options[encoder]
