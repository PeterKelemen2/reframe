"""Every value of every enum and bool option of the software encoders reaches the encoder
without an error."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor

import pytest

from reframe.definitions import EncoderOption, VideoEncoderDef, load_definitions

pytestmark = pytest.mark.needs_ffmpeg

DEFS = load_definitions()
SOFTWARE = sorted(e for e, d in DEFS.video_encoders.items() if not d.hardware)
#: What an encoder prints for a value it does not take (x264, SVT-AV1, x265, FFmpeg, libvpx).
_REFUSED = re.compile(
    r"Error parsing option|Unknown option|Invalid value|Error setting option"
    r"|Failed to set|out of range|Svt\[error\]|x26[45] \[error\]"
)
#: Values that need another value to be accepted (they are tested together).
_COMPANIONS: dict[tuple[str, str, str], dict[str, str]] = {
    ("libx265", "hdr10-opt", "1"): {
        "colorprim": "bt2020",
        "transfer": "smpte2084",
        "colormatrix": "bt2020nc",
    },
}


def _ffmpeg() -> str:
    from reframe_testing import media

    found = media.find_ffmpeg()
    assert found is not None
    return found


def _written(value: object) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def _values(option: EncoderOption) -> list[str]:
    if option.type == "bool":
        return ["1", "0"]
    if option.type == "enum":
        return [c.written for c in option.choices or []]
    return []


def _args(encoder: VideoEncoderDef, option: EncoderOption, value: str) -> list[str]:
    mapping = option.mapping
    if mapping.kind == "x26x_param":
        assert encoder.params_arg is not None
        extra = _COMPANIONS.get((encoder.id, option.key, value), {})
        params = [f"{mapping.name}={value}", *(f"{k}={v}" for k, v in extra.items())]
        return [encoder.params_arg, ":".join(params)]
    if mapping.kind == "private_opt":
        return [f"-{mapping.name}", value]
    return [mapping.arg, value]


def _run(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_ffmpeg(), "-hide_banner", "-nostdin", "-y", *argv],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@pytest.mark.parametrize("encoder_id", SOFTWARE)
def test_every_enum_and_bool_value_encodes(encoder_id: str) -> None:
    encoder = DEFS.video_encoders[encoder_id]
    jobs = [
        (option, value) for option in encoder.options for value in _values(option)
    ]  # fmt: skip
    assert jobs, encoder_id
    depth = "yuv420p10le" if "10" in encoder.pix_fmts else "yuv420p"

    def run(job: tuple[EncoderOption, str]) -> str | None:
        option, value = job
        extra = ["-preset", "10"] if encoder_id == "libsvtav1" else []
        result = _run(
            [
                *("-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25", "-frames:v", "2"),
                *("-pix_fmt", depth, "-c:v", encoder.id, *encoder.extra_args, *extra),
                *_args(encoder, option, value),
                *("-f", "null", "-"),
            ]
        )
        refused = [ln for ln in result.stderr.splitlines() if _REFUSED.search(ln)]
        if result.returncode or refused:
            return f"{option.key}={value}: rc {result.returncode} {refused[:2]}"
        return None

    with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 2)) as pool:
        problems = [p for p in pool.map(run, jobs) if p]
    assert problems == []


def test_every_software_encoder_has_options_in_each_main_category() -> None:
    """VP9 has no colour options of its own (FFmpeg's colour tags apply)."""
    for encoder_id in ("libx264", "libx265", "libsvtav1"):
        categories = {o.category for o in DEFS.video_encoders[encoder_id].options}
        assert {
            "Rate control",
            "Frame types / GOP",
            "Psycho-visual",
            "Loop filters",
            "HDR / colour",
            "Performance",
        } <= categories, encoder_id
    assert "Motion / analysis" in {o.category for o in DEFS.video_encoders["libx265"].options}
