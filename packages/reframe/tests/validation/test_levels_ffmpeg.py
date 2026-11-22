"""``encoder.level_too_low`` agrees with what the real x265 accepts, and
``encoder.level_bitrate_too_high`` with what NVENC accepts."""

from __future__ import annotations

import subprocess
from fractions import Fraction

import pytest

from reframe.models import FitWithin
from reframe.validation.levels import (
    NVENC_H264_LEVEL_KBPS,
    NVENC_HEVC_LEVEL_KBPS,
    h264_level_fits,
    x265_level_fits,
)

from . import scenario as sc

pytestmark = pytest.mark.needs_ffmpeg


def x265_accepts(
    level: str, width: int, height: int, rate: str, preset: str, min_cu: int | None = None
) -> bool:
    from reframe_testing import media

    ffmpeg = media.find_ffmpeg()
    assert ffmpeg is not None
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostdin", "-y", "-f", "lavfi", "-i",
         f"testsrc2=size={width}x{height}:rate={rate}:duration=0.05", "-frames:v", "1",
         "-c:v", "libx265", "-preset", preset, "-x265-params",
         f"level-idc={level}" + (f":min-cu-size={min_cu}" if min_cu is not None else ""),
         "-f", "null", "-"],
        capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip
    refused = "out of range for specified level" in result.stderr
    assert result.returncode == 0 or refused, result.stderr[-2000:]
    return result.returncode == 0


@pytest.mark.parametrize(
    ("level", "width", "height", "rate", "preset"),
    [
        ("3.1", 1280, 720, "24", "medium"),
        ("3.1", 1920, 1080, "24", "medium"),
        ("4.0", 1920, 1080, "32", "medium"),
        ("4.0", 1920, 1080, "33", "medium"),
        ("4.1", 1920, 1080, "60", "medium"),
        ("4.1", 1920, 1080, "65", "medium"),
        ("4.0", 2560, 1440, "24", "medium"),
        ("5.0", 3840, 2160, "30", "medium"),
        ("5.0", 3840, 2160, "60", "medium"),
        ("4.0", 1920, 1160, "24", "medium"),
        ("4.0", 1920, 1160, "24", "ultrafast"),
        ("3.1", 2800, 64, "24", "medium"),
        ("3.1", 2816, 64, "24", "medium"),
        ("4.0", 4216, 64, "24", "medium"),
        ("4.0", 4216, 64, "24", "ultrafast"),
    ],
)  # fmt: skip
def test_level_limits_match_x265(
    level: str, width: int, height: int, rate: str, preset: str
) -> None:
    fits = x265_level_fits(level, width, height, Fraction(rate), preset) is None
    assert fits is x265_accepts(level, width, height, rate, preset)


@pytest.mark.parametrize(
    ("preset", "min_cu", "accepted"),
    [
        ("medium", 16, False),
        ("medium", 32, False),
        ("medium", 8, True),
        ("ultrafast", 8, True),
        ("ultrafast", 16, False),
    ],
)
def test_the_padding_follows_min_cu_size(preset: str, min_cu: int, accepted: bool) -> None:
    """Level 4 at 1920x1160: 1920x1160 itself fits; padded to 16 or 32 lines it does not."""
    assert x265_accepts("4.0", 1920, 1160, "24", preset, min_cu) is accepted
    fits = x265_level_fits("4.0", 1920, 1160, Fraction(24), preset, min_cu=min_cu) is None
    assert fits is accepted
    s = sc.base()
    s.source.video[0].height = 1160
    s.job.dimensions.size = FitWithin(width=1920, height=1160)
    s.job.video.encoder = "libx265"
    s.job.video.level = "4.0"
    s.job.video.preset = preset
    s.job.video.advanced = {"min-cu-size": str(min_cu)}
    found = sc.found(s.validate(), "encoder.level_too_low", "video.level")
    assert found is not accepted


def _nvenc_takes(encoder: str, level: str, kbps: int, *extra: str) -> bool:
    from reframe_testing import media

    ffmpeg = media.find_ffmpeg()
    assert ffmpeg is not None
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostdin", "-f", "lavfi", "-i", "testsrc2=size=160x96:rate=15",
         "-frames:v", "2", "-pix_fmt", "yuv420p", "-c:v", encoder, *extra, "-level", level,
         "-rc", "vbr", "-b:v", f"{kbps}k", "-f", "null", "-"],
        capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip
    refused = "Invalid Level" in result.stderr
    assert result.returncode == 0 or refused, result.stderr[-2000:]
    return result.returncode == 0


def _nvenc_limits() -> list[tuple[str, str, int, tuple[str, ...]]]:
    cases: list[tuple[str, str, int, tuple[str, ...]]] = []
    for level, (main, high) in NVENC_H264_LEVEL_KBPS.items():
        cases.append(("h264_nvenc", level, main, ("-profile", "main")))
        cases.append(("h264_nvenc", level, high, ("-profile", "high")))
    for level, (main_tier, high_tier) in NVENC_HEVC_LEVEL_KBPS.items():
        cases.append(("hevc_nvenc", level, main_tier, ("-tier", "main")))
        if high_tier is not None:
            cases.append(("hevc_nvenc", level, high_tier, ("-tier", "high")))
    return cases


@pytest.mark.needs_gpu
def test_the_nvenc_level_bitrates_match_the_gpu() -> None:
    from reframe_testing import media

    ffmpeg = media.find_ffmpeg()
    assert ffmpeg is not None
    probe = [ffmpeg, "-hide_banner", "-nostdin", "-f", "lavfi", "-i", "testsrc2=size=160x96",
             "-frames:v", "1", "-c:v", "hevc_nvenc", "-f", "null", "-"]  # fmt: skip
    if subprocess.run(probe, capture_output=True, timeout=60, check=False).returncode:
        pytest.skip("NVENC does not work on this machine")
    wrong = [
        f"{encoder} {level} {' '.join(extra)}: {kbps}"
        for encoder, level, kbps, extra in _nvenc_limits()  # one at a time: sessions are limited
        if not _nvenc_takes(encoder, level, kbps, *extra)
        or _nvenc_takes(encoder, level, kbps + 1, *extra)
    ]
    assert wrong == []


@pytest.mark.needs_gpu
@pytest.mark.parametrize(
    ("encoder", "level", "size", "rate"),
    [
        ("h264_nvenc", "4.1", "1920x1080", 60),
        ("h264_nvenc", "4.2", "1920x1080", 60),
        ("h264_nvenc", "3.2", "1920x1080", 30),
        ("h264_nvenc", "4.0", "1920x1080", 30),
        ("h264_nvenc", "3.1", "1280x720", 60),
        ("h264_nvenc", "3.2", "1280x720", 60),
        ("hevc_nvenc", "4.0", "1920x1080", 60),
        ("hevc_nvenc", "4.1", "1920x1080", 60),
        ("hevc_nvenc", "3.1", "1920x1080", 30),
        ("hevc_nvenc", "4.0", "1920x1080", 30),
        ("hevc_nvenc", "5.0", "3840x2160", 60),
        ("hevc_nvenc", "5.1", "3840x2160", 60),
    ],
)
def test_nvenc_level_picture_limits_match_the_rule(
    encoder: str, level: str, size: str, rate: int
) -> None:
    from reframe_testing import media

    ffmpeg = media.find_ffmpeg()
    assert ffmpeg is not None
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostdin", "-f", "lavfi", "-i",
         f"testsrc2=size={size}:rate={rate}", "-frames:v", "2", "-pix_fmt", "yuv420p",
         "-c:v", encoder, "-rc", "vbr", "-cq", "27", "-b:v", "0", "-level", level,
         "-f", "null", "-"],
        capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip
    if result.returncode and "Invalid Level" not in result.stderr:
        pytest.skip(f"{encoder} does not work on this machine")
    width, height = (int(v) for v in size.split("x"))
    if encoder == "h264_nvenc":
        fits = h264_level_fits(level, width, height, Fraction(rate)) is None
    else:
        fits = x265_level_fits(level, width, height, Fraction(rate), None, min_cu=8) is None
    assert (result.returncode == 0) == fits, result.stderr[-1000:]
