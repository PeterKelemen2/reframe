"""The definitions loader: packaged encoders, strict fields and the encoder contract."""

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


def test_exactly_the_supported_video_encoders_are_defined() -> None:
    expected = {
        "libx264",
        "libx265",
        "libsvtav1",
        "libvpx-vp9",
        *(
            f"{codec}_{family}"
            for codec in ("h264", "hevc", "av1")
            for family in ("nvenc", "qsv", "amf", "vaapi")
        ),
    }
    assert set(load_definitions().video_encoders) == expected


def test_fallback_chains_name_known_encoders_and_end_in_software() -> None:
    encoders = load_definitions().video_encoders
    for encoder in encoders.values():
        assert encoder.hardware == (encoder.family != "software"), encoder.id
        if not encoder.hardware:
            assert encoder.fallback == [], encoder.id
            continue
        assert encoder.fallback, encoder.id
        assert all(step in encoders for step in encoder.fallback), encoder.id
        assert encoder.id not in encoder.fallback, encoder.id
        assert not encoders[encoder.fallback[-1]].hardware, encoder.id
        assert all(encoders[step].codec == encoder.codec for step in encoder.fallback), encoder.id


def test_vaapi_is_linux_only_and_uploads_frames() -> None:
    for encoder in load_definitions().video_encoders.values():
        if encoder.family != "vaapi":
            continue
        assert encoder.platforms == ["linux"]
        assert encoder.hardware_setup is not None
        assert encoder.hardware_setup.filter_tail == ["format={sw_pix_fmt}", "hwupload"]
