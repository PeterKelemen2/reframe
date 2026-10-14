"""``encoder.level_too_low``: the x265 level limits of validation agree with the real x265
(testdata/README.md "Validation (C-8)").

x265 refuses a level whose limits the picture exceeds ("picture dimensions are out of range
for specified level", "frame rate is out of range for specified level"), measured on the
picture padded to the minimum coding unit (16 for ``ultrafast``, 8 otherwise).
"""

from __future__ import annotations

import subprocess
from fractions import Fraction

import pytest

from reframe.validation.levels import x265_level_fits

pytestmark = pytest.mark.needs_ffmpeg


def x265_accepts(level: str, width: int, height: int, rate: str, preset: str) -> bool:
    from reframe_testing import media

    ffmpeg = media.find_ffmpeg()
    assert ffmpeg is not None
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostdin", "-y", "-f", "lavfi", "-i",
         f"testsrc2=size={width}x{height}:rate={rate}:duration=0.05", "-frames:v", "1",
         "-c:v", "libx265", "-preset", preset, "-x265-params", f"level-idc={level}",
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
