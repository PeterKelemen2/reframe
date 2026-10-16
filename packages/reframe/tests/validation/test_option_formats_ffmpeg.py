"""The VBV rule (R5-7) and the HDR text formats (R5-8) agree with the real encoders
(core-complete review; decision 0035 "Follow-up (core-complete review, 2026-10-16)";
testdata/README.md "Advanced encoder options (C-6, complete option sets)").

Each row encodes with the parameters written directly and reads what the encoder did (x264's
settings SEI, x265's log, the HDR side data of the output); validation must warn exactly when
the encoder drops the value, and refuse exactly the texts the encoder cannot use.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from reframe.definitions import load_definitions
from reframe.models import (
    AverageBitrate,
    CapabilitySnapshot,
    ConstantQuality,
    OptionValue,
    VideoSettings,
)
from reframe.validation.video import video_option_issues, video_option_rule_issues

pytestmark = pytest.mark.needs_ffmpeg

DEFS = load_definitions()


def _tools() -> tuple[str, str]:
    from reframe_testing import media

    ffmpeg, ffprobe = media.find_ffmpeg(), media.find_ffprobe()
    assert ffmpeg is not None
    assert ffprobe is not None
    return ffmpeg, ffprobe


def _run(argv: list[str], timeout: float = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)


# --------------------------------------------------------------------------- R5-7


@pytest.mark.parametrize("encoder", ["libx264", "libx265"])
@pytest.mark.parametrize("abr", [False, True], ids=["crf", "abr"])
@pytest.mark.parametrize(
    "advanced",
    [{"vbv-maxrate": 5000}, {"vbv-bufsize": 5000}, {"vbv-maxrate": 5000, "vbv-bufsize": 6000}],
    ids=["maxrate", "bufsize", "both"],
)
def test_r5_7_vbv_with_the_encoders(
    tmp_path: Path, encoder: str, abr: bool, advanced: dict[str, int]
) -> None:
    ffmpeg, _ = _tools()
    out = tmp_path / ("o.h264" if encoder == "libx264" else "o.hevc")
    params = ":".join(f"{k}={v}" for k, v in advanced.items())
    rc = ["-b:v", "2000k"] if abr else ["-crf", "22"]
    result = _run(
        [ffmpeg, "-hide_banner", "-nostdin", "-y", "-f", "lavfi", "-i",
         "testsrc2=size=192x108:rate=25", "-frames:v", "3", "-c:v", encoder, "-preset",
         "ultrafast", *rc, f"-{encoder.removeprefix('lib')}-params", params, str(out)]
    )  # fmt: skip
    assert result.returncode == 0, result.stderr[-1500:]
    if encoder == "libx264":  # the settings SEI: "vbv_maxrate=… vbv_bufsize=…" when VBV is on
        sei = re.search(rb"options: ([ -~]+)", out.read_bytes())
        assert sei is not None
        used = b"vbv_maxrate=" in sei.group(1)
    else:
        used = "VBV/HRD buffer / max-rate" in result.stderr
    rate_control = AverageBitrate(kbps=2000) if abr else ConstantQuality(value=22)
    video = VideoSettings(encoder=encoder, rate_control=rate_control, advanced=dict(advanced))
    warned = {
        i.path
        for i in video_option_rule_issues(video, CapabilitySnapshot(), DEFS)
        if i.code == "encoder.option_inactive"
    }
    assert bool(warned) is not used, (result.stderr[-800:], warned)


# --------------------------------------------------------------------------- R5-8

X265_MD = "G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(10000000,1)"
SVT_MD = "G(0.265,0.69)B(0.15,0.06)R(0.68,0.32)WP(0.3127,0.329)L(1000,0.0001)"


def _hdr_side_data(ffprobe: str, path: Path) -> dict[str, dict[str, object]]:
    probe = _run(
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-read_intervals", "%+#1",
         "-show_frames", "-show_entries", "frame=side_data_list", "-of", "json", str(path)]
    )  # fmt: skip
    found: dict[str, dict[str, object]] = {}
    for frame in json.loads(probe.stdout or "{}").get("frames", []):
        for side in frame.get("side_data_list", []):
            found[side.get("side_data_type", "")] = side
    return found


def _invalid(encoder: str, key: str, value: OptionValue) -> bool:
    video = VideoSettings(encoder=encoder, bit_depth=10, advanced={key: value})
    issues = video_option_issues(video, CapabilitySnapshot(), DEFS)
    return any(i.code == "encoder.option_invalid" for i in issues)


@pytest.mark.parametrize(
    ("encoder", "key", "value", "expected"),
    [
        # (the side data the encoder writes, or None when it writes none)
        ("libx265", "master-display", X265_MD, {"red_x": "34000/50000", "green_x": "13250/50000"}),
        ("libx265", "master-display", "garbage", None),
        ("libx265", "master-display", SVT_MD, None),
        ("libx265", "master-display", X265_MD.replace("13250", "70000"), {"green_x": "4464/50000"}),
        ("libx265", "max-cll", "1000,400", {"max_content": 1000, "max_average": 400}),
        ("libx265", "max-cll", "1000", {"max_content": 1000, "max_average": 0}),
        ("libx265", "max-cll", "70000,400", {"max_content": 4464, "max_average": 400}),
        ("libsvtav1", "mastering-display", SVT_MD, {"red_x": "44564/65536"}),
        ("libsvtav1", "mastering-display", "garbage", None),
        ("libsvtav1", "mastering-display", SVT_MD.removesuffix("L(1000,0.0001)"), None),
        ("libsvtav1", "mastering-display", X265_MD, {"red_x": "65535/65536"}),  # clipped
        ("libsvtav1", "content-light", "1000,400", {"max_content": 1000, "max_average": 400}),
        ("libsvtav1", "content-light", "1000", None),
        ("libsvtav1", "content-light", "70000,400", {"max_content": 65535, "max_average": 400}),
    ],
)  # fmt: skip
def test_r5_8_what_the_encoders_write(
    tmp_path: Path, encoder: str, key: str, value: str, expected: dict[str, object] | None
) -> None:
    """Validation accepts a text exactly when the encoder writes it as given."""
    ffmpeg, ffprobe = _tools()
    out = tmp_path / "o.mkv"
    escaped = value.replace(":", "\\:").replace(",", "\\,")
    preset = ["-preset", "12"] if encoder == "libsvtav1" else ["-preset", "ultrafast"]
    params_arg = DEFS.video_encoders[encoder].params_arg
    assert params_arg is not None
    result = _run(
        [ffmpeg, "-hide_banner", "-nostdin", "-y", "-f", "lavfi", "-i",
         "testsrc2=size=192x108:rate=25", "-frames:v", "2", "-pix_fmt", "yuv420p10le",
         "-c:v", encoder, *preset, params_arg, f"{key}={escaped}", str(out)]
    )  # fmt: skip
    assert result.returncode == 0, result.stderr[-1500:]
    kind = "Mastering display metadata" if "display" in key else "Content light level metadata"
    side = _hdr_side_data(ffprobe, out).get(kind)
    if expected is None:
        assert side is None, side
    else:
        assert side is not None
        assert {k: side.get(k) for k in expected} == expected
    as_given = value == "1000,400" or (encoder, value) in {
        ("libx265", X265_MD),
        ("libsvtav1", SVT_MD),
    }
    assert _invalid(encoder, key, value) is not as_given


def test_r5_8_svt_av1_never_ends_with_text_after_the_tags(tmp_path: Path) -> None:
    """SVT-AV1 v4.2.0: ``mastering-display`` with any other text (``…L(1000,0.0001)junk``)
    keeps FFmpeg busy until it is killed (one frame normally takes 0.1 s); validation refuses
    such a text."""
    ffmpeg, _ = _tools()
    value = SVT_MD + "junk"
    try:
        _run(
            [ffmpeg, "-hide_banner", "-nostdin", "-f", "lavfi", "-i",
             "testsrc2=size=192x108:rate=25", "-frames:v", "1", "-pix_fmt", "yuv420p10le",
             "-c:v", "libsvtav1", "-preset", "12", "-svtav1-params",
             f"mastering-display={value.replace(',', chr(92) + ',')}", "-f", "null", "-"],
            timeout=5,
        )  # fmt: skip
        ended = True
    except subprocess.TimeoutExpired:
        ended = False
    assert not ended
    assert _invalid("libsvtav1", "mastering-display", value)
