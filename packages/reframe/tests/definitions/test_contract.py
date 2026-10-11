"""The M2 definitions contract stub: the loader validates the data and C-4/C-16 fields exist."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from reframe.definitions import VideoEncoderDef, load_definitions


def test_loader_reads_the_packaged_encoders() -> None:
    defs = load_definitions()
    x265 = defs.video_encoders["libx265"]
    assert x265.id == "libx265"
    assert x265.codec == "hevc"
    assert x265.codec_label == "H.265"
    assert x265.handbrake_key == "x265"
    assert not x265.hardware
    assert x265.pix_fmts["10"] == "yuv420p10le"


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        VideoEncoderDef.model_validate(
            {
                "id": "x",
                "label": "x",
                "codec": "h264",
                "codec_label": "H.264",
                "handbrake_key": "x",
                "family": "software",
                "hardware": False,
                "typo_field": 1,
            }
        )
