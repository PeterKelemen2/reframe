"""Every value of every enum and bool option of the software encoders reaches the encoder
without an error."""

from __future__ import annotations

import re

import pytest

from reframe.definitions import EncoderOption, load_definitions
from reframe_testing.encoders import encode_args, mapping_args, parallel, run_ffmpeg_capture

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


def _values(option: EncoderOption) -> list[str]:
    if option.type == "bool":
        return ["1", "0"]
    if option.type == "enum":
        return [c.written for c in option.choices or []]
    return []


@pytest.mark.parametrize("encoder_id", SOFTWARE)
def test_every_enum_and_bool_value_encodes(encoder_id: str) -> None:
    encoder = DEFS.video_encoders[encoder_id]
    jobs = [
        (option, value) for option in encoder.options for value in _values(option)
    ]  # fmt: skip
    assert jobs, encoder_id
    depth = 10 if "10" in encoder.pix_fmts else 8

    def run(job: tuple[EncoderOption, str]) -> str | None:
        option, value = job
        args, params = mapping_args(option.mapping, value)
        if option.mapping.kind == "x26x_param":
            params |= _COMPANIONS.get((encoder_id, option.key, value), {})
        if encoder_id == "libsvtav1":
            args = ["-preset", "10", *args]
        result = run_ffmpeg_capture(
            [*encode_args(encoder, args, params, depth=depth, frames=2), "-f", "null", "-"]
        )
        refused = [ln for ln in result.stderr.splitlines() if _REFUSED.search(ln)]
        if result.returncode or refused:
            return f"{option.key}={value}: rc {result.returncode} {refused[:2]}"
        return None

    assert parallel(jobs, run) == []
