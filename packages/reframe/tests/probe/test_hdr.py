"""HDR detection from side data, with hand-made side data for the cases that cannot be
generated."""

from __future__ import annotations

from typing import Any

import pytest

from reframe.models import HdrFormat
from reframe.probe import hdr

MASTERING = {
    "side_data_type": "Mastering display metadata",
    "red_x": "17/25",
    "red_y": "8/25",
    "green_x": "53/200",
    "green_y": "69/100",
    "blue_x": "3/20",
    "blue_y": "3/50",
    "white_point_x": "3127/10000",
    "white_point_y": "329/1000",
    "min_luminance": "1/10000",
    "max_luminance": "1000/1",
}
CLL = {"side_data_type": "Content light level metadata", "max_content": 1000, "max_average": 400}
HDR10PLUS_FRAME = {
    "side_data_type": "HDR Dynamic Metadata SMPTE2094-40 (HDR10+)",
    "application_version": 1,
    "num_windows": 1,
}


def dovi(profile: int, compat: int) -> dict[str, Any]:
    return {
        "side_data_type": "DOVI configuration record",
        "dv_version_major": 1,
        "dv_version_minor": 0,
        "dv_profile": profile,
        "dv_level": 6,
        "rpu_present_flag": 1,
        "el_present_flag": 0,
        "bl_present_flag": 1,
        "dv_bl_signal_compatibility_id": compat,
    }


def stream(
    transfer: str | None = "smpte2084", *side: dict[str, Any], **extra: Any
) -> dict[str, Any]:
    data: dict[str, Any] = {"codec_type": "video", **extra}
    if transfer is not None:
        data["color_transfer"] = transfer
    if side:
        data["side_data_list"] = list(side)
    return data


def test_sdr_is_none() -> None:
    assert hdr.parse_hdr(stream("bt709")) is None
    assert hdr.parse_hdr(stream(None)) is None


def test_pq_without_metadata_is_hdr10() -> None:
    info = hdr.parse_hdr(stream())
    assert info is not None
    assert info.formats == [HdrFormat.HDR10]
    assert info.mastering_display is None
    assert info.content_light is None


def test_hdr10_plus_from_the_frame() -> None:
    info = hdr.parse_hdr(stream("smpte2084", MASTERING, CLL), {"side_data_list": [HDR10PLUS_FRAME]})
    assert info is not None
    assert info.formats == [HdrFormat.HDR10, HdrFormat.HDR10_PLUS]
    assert info.source == "stream"  # the static metadata came from the stream


def test_hdr10_plus_packet_name_in_stream_side_data() -> None:
    side = {"side_data_type": "HDR10+ Dynamic Metadata (SMPTE 2094-40)"}
    info = hdr.parse_hdr(stream("smpte2084", side))
    assert info is not None
    assert HdrFormat.HDR10_PLUS in info.formats


def test_dolby_vision_profile_5_has_no_hdr10() -> None:
    info = hdr.parse_hdr(stream("unknown", dovi(5, 0)))
    assert info is not None
    assert info.formats == [HdrFormat.DOLBY_VISION]
    assert info.dolby_vision is not None
    assert info.dolby_vision.profile == 5


def test_dolby_vision_8_4_is_hlg() -> None:
    info = hdr.parse_hdr(stream("arib-std-b67", dovi(8, 4)))
    assert info is not None
    assert info.formats == [HdrFormat.HLG, HdrFormat.DOLBY_VISION]
    assert info.dolby_vision is not None
    assert info.dolby_vision.bl_signal_compatibility_id == 4


def test_dovi_record_in_the_frame_counts_as_frame_source() -> None:
    info = hdr.parse_hdr(stream("smpte2084"), {"side_data_list": [dovi(8, 1)]})
    assert info is not None
    assert info.formats == [HdrFormat.HDR10, HdrFormat.DOLBY_VISION]
    assert info.source == "frame"


def test_unknown_transfer_with_static_metadata_is_hdr10() -> None:
    """One-pass x265 without colour tags: transfer unknown, metadata only in SEI."""
    frame = {"side_data_list": [MASTERING, CLL]}
    info = hdr.parse_hdr(stream("unknown", color_space="bt2020nc"), frame)
    assert info is not None
    assert info.formats == [HdrFormat.HDR10]
    assert info.source == "frame"


def test_frame_transfer_fills_an_unknown_stream_transfer() -> None:
    info = hdr.parse_hdr(stream(None), {"color_transfer": "arib-std-b67"})
    assert info is not None
    assert info.formats == [HdrFormat.HLG]


def test_static_metadata_with_sdr_transfer_is_none() -> None:
    """The contract: ``hdr`` is ``None`` for SDR, even with stray HDR metadata."""
    assert hdr.parse_hdr(stream("bt709", CLL, MASTERING)) is None


@pytest.mark.parametrize(
    "bad",
    [
        {**MASTERING, "red_x": "n/a"},
        {**MASTERING, "max_luminance": "1/0"},
        {**MASTERING, "min_luminance": "-1/1"},
        {k: v for k, v in MASTERING.items() if k != "white_point_y"},
    ],
)
def test_broken_mastering_display_is_ignored(bad: dict[str, Any]) -> None:
    info = hdr.parse_hdr(stream("smpte2084", bad))
    assert info is not None
    assert info.mastering_display is None


def test_broken_entries_are_ignored() -> None:
    info = hdr.parse_hdr(
        stream(
            "smpte2084",
            {"side_data_type": "Content light level metadata", "max_content": "x"},
            {**dovi(8, 1), "dv_profile": None},
            {"side_data_type": "Mastering display metadata", **dict.fromkeys(MASTERING, True)},
        )
    )
    assert info is not None
    assert (info.content_light, info.dolby_vision, info.mastering_display) == (None, None, None)
    assert hdr.parse_hdr({"color_transfer": "smpte2084", "side_data_list": "junk"}) is not None
    assert hdr.parse_hdr(stream("smpte2084", "junk", 3)) is not None  # type: ignore[arg-type]


def test_numbers_as_numbers() -> None:
    entry = {**MASTERING, "red_x": 0.68, "max_luminance": 1000}
    info = hdr.parse_hdr(stream("smpte2084", entry))
    assert info is not None
    assert info.mastering_display is not None
    assert info.mastering_display.red_x == pytest.approx(0.68)


@pytest.mark.parametrize(
    ("data", "depth", "needed"),
    [
        (stream("smpte2084", MASTERING), 10, True),  # PQ: HDR10+ is only in frames
        (stream("arib-std-b67"), 10, True),
        (stream("arib-std-b67", MASTERING), 10, False),
        (stream("bt709"), 10, False),
        (stream("unknown", color_space="bt2020nc"), 10, True),
        (stream(None, color_primaries="bt2020"), 12, True),
        (stream(None, color_primaries="bt2020"), 8, False),
        (stream(None, color_primaries="bt2020"), None, False),
        (stream(None, CLL, color_space="bt2020nc"), 10, False),
        (stream(None), 10, False),
    ],
)
def test_needs_frame_side_data(data: dict[str, Any], depth: int | None, needed: bool) -> None:
    assert hdr.needs_frame_side_data(data, depth) is needed
