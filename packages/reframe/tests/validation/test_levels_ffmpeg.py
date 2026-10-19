"""``encoder.level_too_low`` agrees with what the real x265 accepts."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from types import ModuleType

import pytest

from reframe.models import FitWithin
from reframe.validation.levels import x265_level_fits

pytestmark = pytest.mark.needs_ffmpeg


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"_reframe_validation_{name}", Path(__file__).with_name(f"{name}.py")
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sc = _load("scenario")


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
