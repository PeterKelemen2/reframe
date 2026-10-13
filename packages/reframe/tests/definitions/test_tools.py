"""The definitions checked against the real FFmpeg build (``needs_ffmpeg``; ``needs_gpu`` for
the AMF / VAAPI encodes).

These tests are the record of where the data comes from: every private option name, preset,
tune, profile and level against ``ffmpeg -h encoder=<id>``; the x264 / x265 per-preset
defaults against what the libraries write into the stream; every rate-control argument,
audio bitrate and sample rate against a real encode; what each muxer accepts and which
flags it writes; and every filter chain against a real run. testdata/README.md
("Encoder definitions (C-6)") has the results as tables.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from functools import cache
from pathlib import Path
from typing import Any, cast

import pytest

from reframe.definitions import (
    ChoiceSetting,
    CodecSupport,
    ContainerDef,
    EncoderOption,
    VideoEncoderDef,
    load_definitions,
)
from reframe.definitions.models import TRACK_FLAGS, OptionMapping
from reframe.models.job import Container, OptionValue

pytestmark = pytest.mark.needs_ffmpeg

DEFS = load_definitions()
VIDEO = DEFS.video_encoders
SOFTWARE = [e for e in VIDEO if not VIDEO[e].hardware]
_LAVFI_VIDEO = ["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25"]
#: Small enough for every level (H.265 level 1 allows 36 864 luma samples per picture).
_LAVFI_SMALL = ["-f", "lavfi", "-i", "testsrc2=size=160x96:rate=15"]
_GENERIC_ARGS = frozenset(
    {
        "-b:v",
        "-global_quality",
        "-pass",
        "-passlogfile",
        "-g",
        "-bf",
        "-refs",
        "-profile",
        "-level",
        "-compression_level",
        "-q:a",
        "-crf",
    }
)


# =========================================================================== helpers


def _tools() -> tuple[str, str]:
    from reframe_testing import media

    ffmpeg, ffprobe = media.find_ffmpeg(), media.find_ffprobe()
    assert ffmpeg is not None
    assert ffprobe is not None
    return ffmpeg, ffprobe


def _ffmpeg(args: Sequence[str], timeout: float = 120) -> subprocess.CompletedProcess[str]:
    ffmpeg, _ = _tools()
    return subprocess.run(
        [ffmpeg, "-hide_banner", "-nostdin", "-y", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _probe(path: Path, *entries: str) -> dict[str, Any]:
    _, ffprobe = _tools()
    out = subprocess.run(
        [ffprobe, "-v", "error", "-of", "json", *entries, str(path)],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    result: dict[str, Any] = json.loads(out.stdout)
    return result


def _parallel[T](jobs: Iterable[T], run: Callable[[T], str | None]) -> list[str]:
    """Run ``run`` for every job in a thread pool; the problems it returns, in order."""
    with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 2)) as pool:
        return [p for p in pool.map(run, list(jobs)) if p]


#: libx264, libx265 and libsvtav1 do not fail on a bad params entry: they log one of these
#: and encode on (exit 0).
_PARAM_ERRORS = re.compile(r"Error parsing option|Unknown option|Invalid value|bad parameter")


def _param_error(result: subprocess.CompletedProcess[str]) -> str | None:
    found = [ln for ln in result.stderr.splitlines() if _PARAM_ERRORS.search(ln)]
    return " | ".join(found) if found else None


def _fail_text(result: subprocess.CompletedProcess[str]) -> str:
    lines = [ln for ln in result.stderr.splitlines() if ln.strip()]
    return " | ".join(lines[-3:])


@cache
def _encoders_in_build() -> frozenset[str]:
    names = set()
    for line in _ffmpeg(["-encoders"]).stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and re.fullmatch(r"[VAS][F.][S.][X.][B.][D.]", parts[0]):
            names.add(parts[1])
    return frozenset(names)


@cache
def _help(encoder: str) -> dict[str, set[str]]:
    """``ffmpeg -h encoder=<id>``: private option name → its named constants."""
    options: dict[str, set[str]] = {}
    current: set[str] | None = None
    for line in _ffmpeg(["-h", f"encoder={encoder}"]).stdout.splitlines():
        opt = re.match(r"^  -(\S+)\s+<", line)
        if opt:
            current = options.setdefault(opt.group(1), set())
            continue
        const = re.match(r"^     (\S+)\s", line)
        if const and current is not None:
            current.add(const.group(1))
    return options


def _need_encoder(encoder: str) -> None:
    if encoder not in _encoders_in_build():
        pytest.skip(f"{encoder} is not in this FFmpeg build")


def _mapping_args(mapping: OptionMapping, value: str) -> tuple[list[str], dict[str, str]]:
    if mapping.kind == "x26x_param":
        return [], {mapping.name: value}
    if mapping.kind == "ffmpeg_arg":
        return [mapping.arg, value], {}
    return [f"-{mapping.name}", value], {}


def _written(value: OptionValue) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _encode_args(
    encoder: VideoEncoderDef,
    args: Sequence[str] = (),
    params: dict[str, str] | None = None,
    depth: int = 8,
    frames: int = 3,
    small: bool = False,
) -> list[str]:
    params_args: list[str] = []
    source = _LAVFI_SMALL if small else _LAVFI_VIDEO
    if params:
        assert encoder.params_arg is not None
        params_args = [encoder.params_arg, ":".join(f"{k}={v}" for k, v in params.items())]
    return [
        *source,
        "-frames:v",
        str(frames),
        "-pix_fmt",
        encoder.pix_fmts[str(depth)],  # type: ignore[index]
        "-c:v",
        encoder.id,
        *encoder.extra_args,
        *args,
        *params_args,
    ]


# =========================================================================== help output


@pytest.mark.parametrize("encoder_id", sorted(VIDEO))
def test_private_options_and_choices_exist_in_the_build(encoder_id: str) -> None:
    """Every private option the definitions write is listed by ``ffmpeg -h encoder=<id>``,
    and every choice of an option with named constants is one of them."""
    _need_encoder(encoder_id)
    enc = VIDEO[encoder_id]
    known = _help(encoder_id)
    problems: list[str] = []
    if enc.params_arg is not None and enc.params_arg.lstrip("-") not in known:
        problems.append(f"params argument {enc.params_arg}")
    settings: list[tuple[str, ChoiceSetting]] = [
        (name, s)
        for name in ("presets", "tunes", "profiles", "levels")
        if (s := getattr(enc, name)) is not None
    ]
    for name, setting in settings:
        if setting.mapping.kind != "private_opt":
            continue
        opt = setting.mapping.name
        if opt not in known:
            problems.append(f"{name}: -{opt}")
        elif known[opt]:  # named constants: every choice must be one
            missing = [c.written for c in setting.choices if c.written not in known[opt]]
            if missing:
                problems.append(f"{name}: {missing} not constants of -{opt}")
    for option in enc.options:
        if option.mapping.kind == "private_opt":
            if option.mapping.name not in known:
                problems.append(f"option {option.key}: -{option.mapping.name}")
            elif option.type == "enum" and known[option.mapping.name]:
                missing = [
                    c.value
                    for c in option.choices or []
                    if c.value not in known[option.mapping.name]
                ]
                if missing:
                    problems.append(f"option {option.key}: {missing}")
    rc_args: list[str] = []
    if enc.rate_control.quality is not None:
        rc_args += enc.rate_control.quality.args
    if enc.rate_control.bitrate is not None:
        b = enc.rate_control.bitrate
        rc_args += b.args
        if b.two_pass is not None:
            rc_args += [*b.two_pass.args, *b.two_pass.turbo_args, *b.two_pass.full_args]
    rc_args += enc.extra_args
    for i, arg in enumerate(rc_args):
        if not arg.startswith("-") or arg in _GENERIC_ARGS:
            continue
        name = arg[1:]
        if name not in known:
            problems.append(f"rate control / extra argument {arg}")
            continue
        value = rc_args[i + 1] if i + 1 < len(rc_args) else ""
        if (
            known[name]
            and "{" not in value
            and not value.lstrip("-").isdigit()
            and value not in known[name]
        ):
            problems.append(f"{arg} {value}: not a constant")
    assert problems == []


@pytest.mark.parametrize("encoder_id", ["libx264", "libx265"])
def test_x26x_lists_match_the_library(encoder_id: str) -> None:
    """x264 / x265 take free text; the library prints its own lists for a bad value."""
    enc = VIDEO[encoder_id]
    out = _ffmpeg([*_encode_args(enc, ["-preset", "bogus"]), "-f", "null", "-"]).stderr
    presets = re.search(r"Possible presets: (.+)", out)
    tunes = re.search(r"Possible tunes: (.+)", out)
    assert presets is not None
    assert tunes is not None
    assert enc.presets is not None
    assert enc.tunes is not None
    assert enc.presets.values() == presets.group(1).split()
    library_tunes = set(tunes.group(1).split())
    assert set(enc.tunes.values()) | {"fastdecode"} <= library_tunes
    out = _ffmpeg([*_encode_args(enc, ["-profile", "bogus"]), "-f", "null", "-"]).stderr
    profiles = re.search(r"Possible profiles: (.+)", out)
    assert profiles is not None
    assert enc.profiles is not None
    assert set(enc.profiles.values()) <= set(profiles.group(1).split())


# =========================================================================== x264 / x265 SEI


def _sei_options(path: Path) -> dict[str, str]:
    match = re.search(rb"options: ([ -~]+)", path.read_bytes())
    assert match is not None, "no encoder settings SEI"
    out: dict[str, str] = {}
    for token in match.group(1).decode().split():
        if "=" in token:
            key, value = token.split("=", 1)
            out[key] = value
        elif token.startswith("no-"):
            out[token[3:]] = "0"
        else:
            out[token] = "1"
    return out


def _part(value: str, index: int, sep: str = ":") -> str:
    return value.split(sep)[index]


#: Option key → (SEI key, value as the definitions store it) for x264 and x265.
_SEI: dict[str, dict[str, tuple[str, Callable[[str], OptionValue | None]]]] = {
    "libx264": {
        "bframes": ("bframes", int),
        "b-adapt": ("b_adapt", str),
        "b-pyramid": ("b_pyramid", lambda v: {"0": "none", "1": "strict", "2": "normal"}[v]),
        "ref": ("ref", int),
        "keyint": ("keyint", int),
        "min-keyint": ("keyint_min", int),
        "scenecut": ("scenecut", int),
        "rc-lookahead": ("rc_lookahead", int),
        "weightp": ("weightp", str),
        "aq-mode": ("aq", lambda v: _part(v, 0)),
        "aq-strength": ("aq", lambda v: float(_part(v, 1)) if ":" in v else None),
        "mbtree": ("mbtree", lambda v: v == "1"),
        "qcomp": ("qcomp", float),
        "vbv-maxrate": ("vbv_maxrate", int),
        "vbv-bufsize": ("vbv_bufsize", int),
        "psy-rd": ("psy_rd", lambda v: float(_part(v, 0))),
        "psy-trellis": ("psy_rd", lambda v: float(_part(v, 1))),
        "deblock-alpha": ("deblock", lambda v: int(_part(v, 1))),
        "deblock-beta": ("deblock", lambda v: int(_part(v, 2))),
        "me": ("me", str),
        "subme": ("subme", int),
        "merange": ("me_range", int),
        "trellis": ("trellis", str),
        "direct": (
            "direct",
            lambda v: {"0": "none", "1": "spatial", "2": "temporal", "3": "auto"}[v],
        ),
    },
    "libx265": {
        "bframes": ("bframes", int),
        "b-adapt": ("b-adapt", str),
        "ref": ("ref", int),
        "keyint": ("keyint", int),
        "min-keyint": ("min-keyint", int),
        "scenecut": ("scenecut", int),
        "rc-lookahead": ("rc-lookahead", int),
        "aq-mode": ("aq-mode", str),
        "aq-strength": ("aq-strength", float),
        "cutree": ("cutree", lambda v: v == "1"),
        "psy-rd": ("psy-rd", float),
        "psy-rdoq": ("psy-rdoq", float),
        "rdoq-level": ("rdoq-level", str),
        "rd": ("rd", int),
        "me": ("me", str),
        "subme": ("subme", int),
        "merange": ("merange", int),
        "ctu": ("ctu", str),
        "deblock-tc": ("deblock", lambda v: int(_part(v, 0)) if ":" in v else None),
        "deblock-beta": ("deblock", lambda v: int(_part(v, 1)) if ":" in v else None),
        "sao": ("sao", lambda v: v == "1"),
        "limit-sao": ("limit-sao", lambda v: v == "1"),
        "selective-sao": ("selective-sao", int),
        "strong-intra-smoothing": ("strong-intra-smoothing", lambda v: v == "1"),
        "hdr10": ("hdr10", lambda v: v == "1"),
        "hdr10-opt": ("hdr10-opt", lambda v: v == "1"),
        "master-display": ("master-display", str),
        "max-cll": ("cll", str),
        "repeat-headers": ("repeat-headers", lambda v: v == "1"),
    },
}

_EXT = {"libx264": "h264", "libx265": "hevc"}


@pytest.mark.parametrize("encoder_id", ["libx264", "libx265"])
def test_per_preset_defaults_match_the_library(encoder_id: str, tmp_path: Path) -> None:
    """Every per-preset default table equals what the library writes for that preset."""
    enc = VIDEO[encoder_id]
    assert enc.presets is not None
    sei = _SEI[encoder_id]

    def check(preset: str) -> str | None:
        out = tmp_path / f"{preset}.{_EXT[encoder_id]}"
        result = _ffmpeg([*_encode_args(enc, ["-preset", preset]), str(out)])
        if result.returncode:
            return f"{preset}: {_fail_text(result)}"
        options = _sei_options(out)
        wrong = []
        for option in enc.options:
            if option.default.kind == "fixed" and option.key in sei:
                key, convert = sei[option.key]
                if key in options and convert(options[key]) != option.default.value:
                    wrong.append(f"{option.key}={options[key]} (fixed {option.default.value})")
            if option.default.kind != "preset":
                continue
            key, convert = sei[option.key]
            actual = convert(options[key]) if key in options else None
            expected = option.default.values.get(preset)
            if actual != expected:
                wrong.append(f"{option.key}: library {actual!r}, table {expected!r}")
        return f"{preset}: {wrong}" if wrong else None

    assert _parallel(enc.presets.values(), check) == []


def _build_params(
    enc: VideoEncoderDef, values: dict[str, OptionValue], preset: str
) -> dict[str, str]:
    """The params a builder writes for ``values`` (composite parts joined with ``,``)."""
    params: dict[str, str] = {}
    composite: dict[str, dict[int, str]] = {}
    for option in enc.options:
        if option.mapping.kind != "x26x_param":
            continue
        name, part = option.mapping.name, option.mapping.part
        if option.key in values:
            value = _written(values[option.key])
        elif part is not None and option.default.kind == "preset":
            value = _written(option.default.values[preset])
        else:
            continue
        if part is None:
            params[name] = value
        else:
            composite.setdefault(name, {})[part] = value
    for name, parts in composite.items():
        if any(
            o.key in values
            for o in enc.options
            if o.mapping.kind == "x26x_param" and o.mapping.name == name
        ):
            params[name] = ",".join(parts[i] for i in sorted(parts))
    return params


#: A non-default value for every option, to see that the parameter reaches the library.
_TEST_VALUES: dict[str, dict[str, OptionValue]] = {
    "libx264": {
        "bframes": 5,
        "b-adapt": "2",
        "b-pyramid": "strict",
        "ref": 4,
        "keyint": 120,
        "min-keyint": 12,
        "scenecut": 30,
        "rc-lookahead": 25,
        "weightp": "1",
        "aq-mode": "2",
        "aq-strength": 0.8,
        "mbtree": False,
        "qcomp": 0.7,
        "vbv-maxrate": 5000,
        "vbv-bufsize": 10000,
        "psy-rd": 1.1,
        "psy-trellis": 0.2,
        "deblock-alpha": -1,
        "deblock-beta": -2,
        "me": "umh",
        "subme": 9,
        "merange": 20,
        "trellis": "2",
        "direct": "auto",
    },
    "libx265": {
        "bframes": 6,
        "b-adapt": "1",
        "ref": 2,
        "keyint": 120,
        "min-keyint": 12,
        "scenecut": 30,
        "rc-lookahead": 30,
        "aq-mode": "3",
        "aq-strength": 0.8,
        "cutree": False,
        "psy-rd": 1.5,
        "psy-rdoq": 2.0,
        "rdoq-level": "1",
        "rd": 4,
        "me": "2",
        "subme": 3,
        "merange": 48,
        "ctu": "32",
        "deblock-tc": -1,
        "deblock-beta": -2,
        "sao": False,
        "limit-sao": True,
        "selective-sao": 2,
        "strong-intra-smoothing": False,
        "hdr10": True,
        "hdr10-opt": True,
        "master-display": "G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(10000000,1)",
        "max-cll": "1000,400",
        "repeat-headers": True,
    },
}


@pytest.mark.parametrize("encoder_id", ["libx264", "libx265"])
def test_every_x26x_option_reaches_the_library(encoder_id: str, tmp_path: Path) -> None:
    enc = VIDEO[encoder_id]
    values = _TEST_VALUES[encoder_id]
    assert set(values) == {o.key for o in enc.options}
    sei = _SEI[encoder_id]
    # limit-sao and selective-sao need SAO on (x265 turns SAO back on for selective-sao, even
    # with sao=0): check them in a second encode.
    later = {"limit-sao", "selective-sao"}
    first = {k: v for k, v in values.items() if k not in later}
    sets = [first]
    if encoder_id == "libx265":
        sets.append({"sao": True, **{k: values[k] for k in later}})
    for values_set in sets:
        out = tmp_path / f"o.{_EXT[encoder_id]}"
        params = _build_params(enc, values_set, "medium")
        if encoder_id == "libx265":
            # hdr10-opt needs BT.2020 colour ("Recommended Settings for HDR10-opt: colour
            # primaries should be BT.2020, Disabling hdr10-opt."); C-7 writes these tags.
            params |= {"colorprim": "bt2020", "transfer": "smpte2084", "colormatrix": "bt2020nc"}
        result = _ffmpeg([*_encode_args(enc, ["-preset", "medium"], params, depth=10), str(out)])
        assert result.returncode == 0, _fail_text(result)
        assert _param_error(result) is None
        options = _sei_options(out)
        for key, value in values_set.items():
            sei_key, convert = sei[key]
            assert sei_key in options, key
            got = convert(options[sei_key])
            if isinstance(value, float):
                assert got == pytest.approx(value), key
            else:
                assert got == value, key


def test_x265_level_idc_reaches_the_library(tmp_path: Path) -> None:
    enc = VIDEO["libx265"]
    assert enc.levels is not None
    out = tmp_path / "o.hevc"
    result = _ffmpeg([*_encode_args(enc, [], {"level-idc": "4.1"}), str(out)])
    assert result.returncode == 0, _fail_text(result)
    assert _sei_options(out)["level-idc"] == "41"


# =========================================================================== software choices


def _choice_jobs(enc: VideoEncoderDef) -> list[tuple[str, list[str], dict[str, str], int]]:
    jobs: list[tuple[str, list[str], dict[str, str], int]] = []
    for name in ("presets", "tunes", "profiles", "levels"):
        setting: ChoiceSetting | None = getattr(enc, name)
        if setting is None:
            continue
        for choice in setting.choices:
            depths = choice.bit_depths or [int(d) for d in enc.pix_fmts]
            for depth in depths:
                if str(depth) not in enc.pix_fmts:
                    continue
                args, params = _mapping_args(setting.mapping, choice.written)
                jobs.append((f"{name}={choice.value}@{depth}", args, params, depth))
    if enc.fast_decode is not None:
        fd = enc.fast_decode
        args = ["-tune", fd.tune] if fd.tune else list(fd.args)
        jobs.append(("fast_decode", args, dict(fd.params), 8))
    return jobs


@pytest.mark.parametrize("encoder_id", SOFTWARE)
def test_every_software_choice_encodes(encoder_id: str) -> None:
    """Every preset, tune, profile and level (at each bit depth it is valid for) encodes."""
    enc = VIDEO[encoder_id]

    def run(job: tuple[str, list[str], dict[str, str], int]) -> str | None:
        label, args, params, depth = job
        result = _ffmpeg(
            [*_encode_args(enc, args, params, depth=depth, frames=2, small=True), "-f", "null", "-"]
        )
        if result.returncode:
            return f"{label}: {_fail_text(result)}"
        error = _param_error(result)
        return f"{label}: {error}" if error else None

    assert _parallel(_choice_jobs(enc), run) == []


def test_svtav1_options_parse() -> None:
    """libsvtav1 only logs a bad parameter and encodes on: check its log."""
    enc = VIDEO["libsvtav1"]
    values: dict[str, OptionValue] = {
        "film-grain": 8,
        "film-grain-denoise": False,
        "keyint": 240,
        "scd": True,
        "lookahead": 60,
        "enable-overlays": True,
        "enable-tf": "0",
        "enable-qm": True,
        "qm-min": 2,
        "qm-max": 12,
        "enable-variance-boost": True,
        "sharpness": 2,
    }
    assert set(values) == {o.key for o in enc.options}
    params = {
        o.mapping.name: _written(values[o.key])
        for o in enc.options
        if o.mapping.kind == "x26x_param"
    }
    result = _ffmpeg([*_encode_args(enc, ["-preset", "10"], params), "-f", "null", "-"])
    assert result.returncode == 0, _fail_text(result)
    assert _param_error(result) is None
    assert re.search(r"gop size / mini-gop size / key-frame type\s*:\s*240 /", result.stderr)
    assert re.search(r"film grain synth / denoising / level .*: 1 / 0 / 8", result.stderr)


@pytest.mark.parametrize("encoder_id", SOFTWARE)
def test_software_rate_control_encodes(encoder_id: str, tmp_path: Path) -> None:
    """Constant quality at min / default / max, average bitrate, and 2-pass with a turbo and
    a full first pass."""
    enc = VIDEO[encoder_id]
    q = enc.rate_control.quality
    b = enc.rate_control.bitrate
    assert q is not None
    assert b is not None
    runs: list[tuple[str, list[str], dict[str, str]]] = []
    for value in (q.min, q.default, q.max):
        text = _written(value)
        runs.append(
            (
                f"quality {text}",
                [a.replace("{value}", text) for a in q.args],
                {k: v.replace("{value}", text) for k, v in q.params.items()},
            )
        )
    runs.append(("bitrate", [a.replace("{kbps}", "500") for a in b.args], dict(b.params)))

    def run(job: tuple[str, list[str], dict[str, str]]) -> str | None:
        label, args, params = job
        result = _ffmpeg([*_encode_args(enc, args, params, frames=5), "-f", "null", "-"])
        if result.returncode:
            return f"{label}: {_fail_text(result)}"
        error = _param_error(result)
        return f"{label}: {error}" if error else None

    assert _parallel(runs, run) == []
    tp = b.two_pass
    assert tp is not None
    assert tp.mode == "two_runs"
    for turbo in (True, False):
        passlog = str(tmp_path / f"log{turbo}")
        out = tmp_path / f"two_pass_{turbo}.mkv"
        for number in ("1", "2"):

            def fill(text: str, number: str = number, passlog: str = passlog) -> str:
                return text.replace("{pass}", number).replace("{passlog}", passlog)

            args = [fill(a) for a in [*b.args, *tp.args]]
            params = {k: fill(v) for k, v in {**b.params, **tp.params}.items()}
            if number == "1":
                args += tp.turbo_args if turbo else tp.full_args
                params |= tp.turbo_params if turbo else tp.full_params
            args = [a.replace("{kbps}", "500") for a in args]
            target = ["-f", "null", "-"] if number == "1" else [str(out)]
            result = _ffmpeg([*_encode_args(enc, args, params, frames=10), *target])
            assert result.returncode == 0, f"pass {number}: {_fail_text(result)}"
            assert _param_error(result) is None
        assert out.stat().st_size > 0


# =========================================================================== audio


_MIXDOWN_LAYOUT = {"mono": "mono", "stereo": "stereo", "dpl2": "stereo", "5.1": "5.1", "7.1": "7.1"}


def _audio_encode(
    encoder: str, layout: str, args: Sequence[str], rate: int = 48000
) -> subprocess.CompletedProcess[str]:
    """Encode noise; ``-ar`` forces the output rate (without it FFmpeg would negotiate a rate
    the encoder supports)."""
    return _ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"anoisesrc=sample_rate={rate}:duration=0.3:amplitude=0.3,"
            f"aformat=channel_layouts={layout}",
            "-c:a",
            encoder,
            "-ar",
            str(rate),
            *args,
            "-f",
            "null",
            "-",
        ]
    )


@pytest.mark.parametrize("encoder_id", sorted(DEFS.audio_encoders))
def test_audio_bitrates_and_sample_rates_encode(encoder_id: str) -> None:
    """Every mixdown at its minimum, default and maximum (and every allowed value for the
    fixed-step encoders), every sample rate, and the VBR quality ends."""
    _need_encoder(encoder_id)
    enc = DEFS.audio_encoders[encoder_id]
    jobs: list[tuple[str, str, list[str], int]] = []
    for mixdown in enc.mixdowns:
        layout = _MIXDOWN_LAYOUT[mixdown]
        if enc.bitrate is None:
            jobs.append((mixdown, layout, [], 48000))
            continue
        limits = enc.bitrate.by_mixdown[mixdown]
        values = enc.bitrate.values(mixdown) or [limits.min, limits.default, limits.max]
        jobs += [(f"{mixdown} {v}k", layout, ["-b:a", f"{v}k"], 48000) for v in values]
    jobs += [(f"{rate} Hz", "stereo", [], rate) for rate in enc.samplerates]
    if enc.quality is not None:
        q = enc.quality
        jobs += [
            (f"quality {v}", "stereo", [q.arg, _written(v)], 48000)
            for v in (q.min, q.default, q.max)
        ]

    def run(job: tuple[str, str, list[str], int]) -> str | None:
        label, layout, args, rate = job
        result = _audio_encode(encoder_id, layout, args, rate)
        return f"{label}: {_fail_text(result)}" if result.returncode else None

    assert _parallel(jobs, run) == []


def test_recorded_audio_encoder_behaviour(tmp_path: Path) -> None:
    """testdata/README.md: AC-3 snaps silently, Opus and AC-3 reject unlisted rates, 7.1 is
    negotiated down for AC-3."""
    out = tmp_path / "a.ac3"
    ffmpeg_args = [
        "-f",
        "lavfi",
        "-i",
        "sine=duration=0.3",
        "-c:a",
        "ac3",
        "-b:a",
        "150k",
        str(out),
    ]
    assert _ffmpeg(ffmpeg_args).returncode == 0
    assert _probe(out, "-show_streams")["streams"][0]["bit_rate"] == "160000"
    assert _audio_encode("libopus", "stereo", [], 44100).returncode != 0
    assert _audio_encode("ac3", "stereo", [], 96000).returncode != 0
    assert _audio_encode("libopus", "stereo", ["-b:a", "600k"]).returncode != 0
    out71 = tmp_path / "b.ac3"
    assert (
        _ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                "sine=duration=0.3,aformat=channel_layouts=7.1",
                "-c:a",
                "ac3",
                str(out71),
            ]
        ).returncode
        == 0
    )
    assert _probe(out71, "-show_streams")["streams"][0]["channels"] == 6


# =========================================================================== containers


_VIDEO_SOURCES: dict[str, list[str]] = {
    "h264": ["-c:v", "libx264"],
    "hevc": ["-c:v", "libx265"],
    "av1": ["-c:v", "libsvtav1"],
    "vp9": ["-c:v", "libvpx-vp9", "-deadline", "realtime"],
    "vp8": ["-c:v", "libvpx"],
    "mpeg1video": ["-c:v", "mpeg1video"],
    "mpeg2video": ["-c:v", "mpeg2video"],
    "mpeg4": ["-c:v", "mpeg4"],
    "mjpeg": ["-c:v", "mjpeg"],
}
_AUDIO_SOURCES: dict[str, list[str]] = {
    "aac": ["-c:a", "aac"],
    "ac3": ["-c:a", "ac3"],
    "eac3": ["-c:a", "eac3"],
    "opus": ["-c:a", "libopus"],
    "flac": ["-c:a", "flac"],
    "mp3": ["-c:a", "libmp3lame"],
    "truehd": ["-c:a", "truehd", "-strict", "-2"],
    "dts": ["-c:a", "dca", "-strict", "-2"],
    "alac": ["-c:a", "alac"],
    "vorbis": ["-c:a", "libvorbis"],
    "pcm_s16le": ["-c:a", "pcm_s16le"],
    "pcm_s24le": ["-c:a", "pcm_s24le"],
    "pcm_s32le": ["-c:a", "pcm_s32le"],
}


@pytest.fixture(scope="module")
def stream_sources(
    tmp_path_factory: pytest.TempPathFactory, fixture_media_module: Callable[[str], Path]
) -> dict[str, Path]:
    """One short Matroska file per codec (``-c copy`` sources)."""
    folder = tmp_path_factory.mktemp("sources")
    jobs = [
        (n, ["-f", "lavfi", "-i", "testsrc2=size=160x120:rate=25:duration=0.4", *a])
        for n, a in _VIDEO_SOURCES.items()
    ]
    jobs += [
        (n, ["-f", "lavfi", "-i", "sine=duration=0.4:sample_rate=48000", *a])
        for n, a in _AUDIO_SOURCES.items()
    ]
    srt = fixture_media_module("text-subs").with_name("text-subs.en.srt")
    ass = srt.with_name("text-subs.en.ass")
    jobs += [
        ("subrip", ["-i", str(srt), "-c:s", "srt"]),
        ("ass", ["-i", str(ass), "-c:s", "ass"]),
        ("webvtt", ["-i", str(srt), "-c:s", "webvtt"]),
    ]
    vobsub = fixture_media_module("vobsub")
    jobs.append(("dvd_subtitle", ["-i", str(vobsub), "-map", "0:s:0", "-c:s", "copy"]))
    jobs.append(("dvb_subtitle", ["-i", str(vobsub), "-map", "0:s:0", "-c:s", "dvbsub"]))
    sources: dict[str, Path] = {}

    def make(job: tuple[str, list[str]]) -> str | None:
        name, args = job
        out = folder / f"{name}.mkv"
        result = _ffmpeg([*args, str(out)])
        if result.returncode:
            return f"{name}: {_fail_text(result)}"
        sources[name] = out
        return None

    assert _parallel(jobs, make) == []
    mov_text = folder / "mov_text.mp4"
    assert _ffmpeg(["-i", str(srt), "-c:s", "mov_text", str(mov_text)]).returncode == 0
    sources["mov_text"] = mov_text
    return sources


@pytest.fixture(scope="module")
def fixture_media_module() -> Callable[[str], Path]:
    from reframe_testing.pytest_plugin import fixture_media_path

    return fixture_media_path


def _container(name: str) -> ContainerDef:
    return DEFS.containers[cast(Container, name)]


def _copy_into(
    source: Path, container: str, out: Path, extra: Sequence[str] = ()
) -> subprocess.CompletedProcess[str]:
    return _ffmpeg(
        [
            "-i",
            str(source),
            "-map",
            "0",
            "-c",
            "copy",
            *extra,
            "-f",
            _container(container).muxer,
            str(out),
        ]
    )


@pytest.mark.parametrize("container", ["mkv", "mp4", "webm"])
def test_listed_codecs_can_be_copied_in(
    container: str, stream_sources: dict[str, Path], tmp_path: Path
) -> None:
    cont = _container(container)
    jobs: list[tuple[str, list[str]]] = []
    kinds: tuple[tuple[CodecSupport, list[str]], ...] = (
        (cont.video, list(_VIDEO_SOURCES)),
        (cont.audio, list(_AUDIO_SOURCES)),
        (cont.subtitles, []),
    )
    for support, all_of_kind in kinds:
        names = all_of_kind if "*" in support.copy_codecs else support.copy_codecs
        for name in names:
            if name not in stream_sources:
                continue  # hdmv_pgs_subtitle: FFmpeg has no PGS encoder to make a source
            jobs.append((name, support.copy_args.get(name, [])))

    def run(job: tuple[str, list[str]]) -> str | None:
        name, extra = job
        out = tmp_path / f"{name}{cont.extensions[0]}"
        result = _copy_into(stream_sources[name], container, out, extra)
        if result.returncode:
            return f"{name}: {_fail_text(result)}"
        got = _probe(out, "-show_streams")["streams"][0]["codec_name"]
        return None if got == name else f"{name}: read back as {got}"

    assert _parallel(jobs, run) == []


@pytest.mark.parametrize(
    ("container", "codec"),
    [
        ("mp4", "subrip"),
        ("mp4", "ass"),
        ("mp4", "webvtt"),
        ("mp4", "vp8"),
        ("webm", "h264"),
        ("webm", "hevc"),
        ("webm", "aac"),
        ("webm", "ac3"),
        ("webm", "flac"),
        ("webm", "subrip"),
        ("webm", "dvd_subtitle"),
        ("mkv", "mov_text"),
    ],
)
def test_unlisted_codecs_are_rejected(
    container: str, codec: str, stream_sources: dict[str, Path], tmp_path: Path
) -> None:
    cont = _container(container)
    assert not any(
        s.can_copy(codec)
        for s in (cont.video, cont.audio, cont.subtitles)
        if "*" not in s.copy_codecs
    )
    result = _copy_into(stream_sources[codec], container, tmp_path / f"x{cont.extensions[0]}")
    assert result.returncode != 0


def test_truehd_in_mp4_needs_strict(stream_sources: dict[str, Path], tmp_path: Path) -> None:
    result = _copy_into(stream_sources["truehd"], "mp4", tmp_path / "t.mp4")
    assert result.returncode != 0
    assert "-strict -2" in result.stderr


@pytest.mark.parametrize("container", ["mkv", "mp4", "webm"])
def test_subtitle_encode_targets(
    container: str, fixture_media: Callable[[str], Path], tmp_path: Path
) -> None:
    cont = _container(container)
    srt = fixture_media("text-subs").with_name("text-subs.en.srt")
    for target in ("srt", "ass", "webvtt", "mov_text"):
        out = tmp_path / f"{target}{cont.extensions[0]}"
        result = _ffmpeg(["-i", str(srt), "-c:s", target, "-f", cont.muxer, str(out)])
        assert (result.returncode == 0) == (target in cont.subtitles.encode), (
            target,
            _fail_text(result),
        )


@pytest.mark.parametrize("container", ["mkv", "mp4", "webm"])
def test_flags_the_muxer_writes(container: str, tmp_path: Path) -> None:
    cont = _container(container)
    codec = {"mkv": "aac", "mp4": "aac", "webm": "libopus"}[container]
    for flag in TRACK_FLAGS:
        disposition = DEFS.track_flags[flag].disposition
        out = tmp_path / f"{flag}{cont.extensions[0]}"
        result = _ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                "sine=duration=0.2",
                "-f",
                "lavfi",
                "-i",
                "sine=duration=0.2",
                "-map",
                "0",
                "-map",
                "1",
                "-c:a",
                codec,
                "-disposition:a:0",
                disposition,
                "-disposition:a:1",
                "0",
                str(out),
            ]
        )
        assert result.returncode == 0, _fail_text(result)
        got = _probe(out, "-show_streams")["streams"][0]["disposition"][disposition]
        assert bool(got) == (flag in cont.flags), flag


@pytest.mark.parametrize("container", ["mkv", "mp4", "webm"])
def test_default_flag_without_a_default_track(container: str, tmp_path: Path) -> None:
    cont = _container(container)
    codec = {"mkv": "aac", "mp4": "aac", "webm": "libopus"}[container]
    out = tmp_path / f"d{cont.extensions[0]}"
    result = _ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "sine=duration=0.2",
            "-f",
            "lavfi",
            "-i",
            "sine=duration=0.2",
            "-map",
            "0",
            "-map",
            "1",
            "-c:a",
            codec,
            "-disposition:a:0",
            "0",
            "-disposition:a:1",
            "0",
            str(out),
        ]
    )
    assert result.returncode == 0
    first = _probe(out, "-show_streams")["streams"][0]["disposition"]["default"]
    assert bool(first) == cont.default_always_set


@pytest.mark.parametrize("container", ["mkv", "mp4", "webm"])
def test_chapters_and_attachments(
    container: str, fixture_media: Callable[[str], Path], tmp_path: Path
) -> None:
    cont = _container(container)
    video = (
        ["-c:v", "libvpx-vp9", "-deadline", "realtime"]
        if container == "webm"
        else ["-c:v", "libx264"]
    )
    out = tmp_path / f"c{cont.extensions[0]}"
    result = _ffmpeg(
        ["-i", str(fixture_media("chapters")), "-map", "0:v", *video, "-frames:v", "5", str(out)]
    )
    assert result.returncode == 0, _fail_text(result)
    assert (len(_probe(out, "-show_chapters")["chapters"]) == 4) == cont.chapters
    out = tmp_path / f"a{cont.extensions[0]}"
    result = _ffmpeg(
        [
            "-i",
            str(fixture_media("text-subs")),
            "-map",
            "0:v",
            "-map",
            "0:t",
            *video,
            "-frames:v",
            "5",
            str(out),
        ]
    )
    attachments = 0
    if result.returncode == 0:
        streams = _probe(out, "-show_streams")["streams"]
        attachments = sum(1 for s in streams if s["codec_type"] == "attachment")
    assert (attachments == 1) == cont.attachments  # WebM drops it silently, MP4 fails


def test_mp4_codec_tags_and_format_flags(tmp_path: Path) -> None:
    mp4 = DEFS.containers["mp4"]
    out = tmp_path / "h.mp4"
    args = ["-tag:v", mp4.codec_tags["hevc"], *mp4.format_flags["web_optimized"]]
    result = _ffmpeg([*_LAVFI_VIDEO, "-frames:v", "3", "-c:v", "libx265", *args, str(out)])
    assert result.returncode == 0, _fail_text(result)
    assert _probe(out, "-show_streams")["streams"][0]["codec_tag_string"] == "hvc1"
    data = out.read_bytes()
    assert data.index(b"moov") < data.index(b"mdat")  # +faststart moved the index forward


# =========================================================================== filters

_CUSTOM: dict[str, str] = {
    "detelecine": "order=auto",
    "interlace_detection": "intl_thres=1.2",
    "deinterlace": "mode=send_frame",
    "denoise": "s=2",
    "deblock": "filter=weak",
    "custom": "hflip",
    "colorspace": "p=bt709:t=bt709:m=bt709",
    "sharpen": "la=0.5",
    "chroma_smooth": "ca=-1",
}
_CUSTOM_BY_IMPL = {"hqdn3d": "luma_spatial=3", "yadif": "mode=send_field", "cas": "strength=0.4"}
_COLOUR_FILTERS = frozenset({"tonemap", "colorspace"})


@cache
def _filters_in_build() -> frozenset[str]:
    names = set()
    for line in _ffmpeg(["-filters"]).stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and re.fullmatch(r"[T.][S.][C.]", parts[0]):
            names.add(parts[1])
    return frozenset(names)


def _filter_jobs() -> list[tuple[str, str, str]]:
    jobs: list[tuple[str, str, str]] = []
    for filter_id, f in DEFS.filters.items():
        for preset in f.presets:
            chains = [(f"{preset.id}/{impl}", impl, chain) for impl, chain in preset.chains.items()]
            chains += [
                (f"{preset.id}+{tune}/{impl}", impl, chain)
                for tune, by_impl in preset.tune_chains.items()
                for impl, chain in by_impl.items()
            ]
            for label, impl_id, chain in chains:
                custom = _CUSTOM_BY_IMPL.get(impl_id, _CUSTOM.get(filter_id, ""))
                text = chain.replace("{custom}", custom)
                impl = next(i for i in f.implementations if i.id == impl_id)
                if impl.combed_only:
                    jobs.append(
                        (
                            f"{filter_id} {label} combed only",
                            impl_id,
                            f"idet,{text}:{impl.combed_only}",
                        )
                    )
                jobs.append((f"{filter_id} {label}", impl_id, text))
    return jobs


def test_every_filter_chain_runs(fixture_media: Callable[[str], Path]) -> None:
    hdr = fixture_media("hdr10")
    available = _filters_in_build()
    impls = {i.id: i for f in DEFS.filters.values() for i in f.implementations}

    def run(job: tuple[str, str, str]) -> str | None:
        label, impl_id, chain = job
        if not set(impls[impl_id].filters) <= available:
            return None
        colour = label.split()[0] in _COLOUR_FILTERS
        source = (
            ["-i", str(hdr)] if colour else ["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25"]
        )
        tail = ",format=yuv420p" if colour else ""
        result = _ffmpeg([*source, "-vf", chain + tail, "-frames:v", "2", "-f", "null", "-"])
        if result.returncode == 0:
            return None
        if impls[impl_id].needs_vulkan and "Generic error in an external library" in result.stderr:
            return None  # no Vulkan driver on this machine: libplacebo cannot run here
        return f"{label}: {chain}: {_fail_text(result)}"

    assert _parallel(_filter_jobs(), run) == []


def test_zscale_needs_tagged_input() -> None:
    """Why ``requires_tagged_input``: zscale fails on an untagged source."""
    chain = "zscale=p=bt709:t=bt709:m=bt709,format=yuv420p"
    untagged = _ffmpeg([*_LAVFI_VIDEO, "-vf", chain, "-frames:v", "2", "-f", "null", "-"])
    tagged = _ffmpeg(
        [
            *_LAVFI_VIDEO,
            "-vf",
            "setparams=color_primaries=bt470bg:color_trc=smpte170m:colorspace=bt470bg," + chain,
            "-frames:v",
            "2",
            "-f",
            "null",
            "-",
        ]
    )
    assert untagged.returncode != 0
    assert tagged.returncode == 0


def test_idet_flags_interlaced_frames(fixture_media: Callable[[str], Path]) -> None:
    """Interlace detection works because idet sets the frames' interlaced flag, which
    bwdif / yadif ``deint=interlaced`` reads. setfield=prog clears the source flag first."""
    src = fixture_media("interlaced")
    result = _ffmpeg(
        ["-i", str(src), "-vf", "setfield=prog,idet,showinfo", "-frames:v", "12", "-f", "null", "-"]
    )
    assert result.returncode == 0
    flags = re.findall(r" i:(\S)", result.stderr)
    assert flags, result.stderr
    assert flags[-1] in ("T", "B"), flags


@pytest.mark.parametrize("encoder_id", ["libx264", "libx265", "libsvtav1"])
def test_a_bad_params_entry_does_not_fail_the_encode(encoder_id: str) -> None:
    """Recorded for C-8's custom-parameter dry run: the exit code is 0, only the log says it
    ("Error parsing option 'bogus = 1'." / "Unknown option: bogus." / "Error parsing option
    bogus: 1.")."""
    enc = VIDEO[encoder_id]
    result = _ffmpeg([*_encode_args(enc, [], {"bogus": "1"}, small=True), "-f", "null", "-"])
    assert result.returncode == 0
    assert _param_error(result) is not None


# =========================================================================== hardware


_HW_SETUP = {
    "vaapi": ["-init_hw_device", "vaapi=va:/dev/dri/renderD128", "-filter_hw_device", "va"],
}


def _hw_args(enc: VideoEncoderDef, depth: int) -> list[str]:
    pix = enc.pix_fmts[str(depth)]  # type: ignore[index]
    if enc.family == "vaapi":
        return [
            *_HW_SETUP["vaapi"],
            *_LAVFI_VIDEO,
            "-frames:v",
            "5",
            "-vf",
            f"format={pix},hwupload",
            "-c:v",
            enc.id,
        ]
    return [*_LAVFI_VIDEO, "-frames:v", "5", "-pix_fmt", pix, "-c:v", enc.id]


def _hw_usable(enc: VideoEncoderDef) -> bool:
    if enc.id not in _encoders_in_build():
        return False
    return _ffmpeg([*_hw_args(enc, 8), "-f", "null", "-"], timeout=30).returncode == 0


def _option_test_value(option: EncoderOption) -> str:
    if option.type == "bool":
        return "1"
    if option.type == "enum":
        return (option.choices or [])[-1].value
    assert option.min is not None
    assert option.max is not None
    return _written(min(option.max, max(option.min, 2)))


@pytest.mark.needs_gpu
@pytest.mark.parametrize(
    "encoder_id", sorted(e for e, d in VIDEO.items() if d.family in ("amf", "vaapi"))
)
def test_hardware_choices_rate_control_and_options_encode(encoder_id: str) -> None:
    """AMF and VAAPI on a real GPU (AMD RX 7600 when recorded): every preset, profile and
    level, constant quality at min / default / max, average bitrate, and every option."""
    enc = VIDEO[encoder_id]
    if not _hw_usable(enc):
        pytest.skip(f"{encoder_id} does not work on this machine")
    jobs: list[tuple[str, list[str], int]] = []
    for label, args, _params, depth in _choice_jobs(enc):
        if enc.family == "amf" and enc.codec == "h264" and depth == 10:
            continue
        jobs.append((label, args, depth))
    q, b = enc.rate_control.quality, enc.rate_control.bitrate
    assert q is not None
    assert b is not None
    for value in (q.min, q.default, q.max):
        args = []
        for arg in q.args:
            text = arg.replace("{value}", _written(value))
            for name, derived in q.derived.items():
                text = text.replace("{" + name + "}", _written(derived.compute(value)))
            args.append(text)
        jobs.append((f"quality {value}", args, 8))
    jobs.append(("bitrate", [a.replace("{kbps}", "2000") for a in b.args], 8))
    for option in enc.options:
        args, _ = _mapping_args(option.mapping, _option_test_value(option))
        jobs.append((f"option {option.key}", args, 8))

    def run(job: tuple[str, list[str], int]) -> str | None:
        label, args, depth = job
        result = _ffmpeg([*_hw_args(enc, depth), *args, "-f", "null", "-"], timeout=60)
        return f"{label}: {_fail_text(result)}" if result.returncode else None

    problems: list[str] = []
    for job in jobs:  # one at a time: the GPU sessions are limited
        problem = run(job)
        if problem:
            problems.append(problem)
    assert problems == []
