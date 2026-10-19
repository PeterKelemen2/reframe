"""MediaInfo's ``StreamOrder`` and bit rates are ASCII digits only.

``str.isdigit()`` accepts superscripts, which ``int()`` rejects, and other scripts' decimal
digits, which ``int()`` reads. A MediaInfo stream order is a plain ASCII number; anything else
is not matched to an ffprobe stream.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from reframe.probe import mediainfo

SUPERSCRIPT_TWO = "\u00b2"  # superscript two
ARABIC_INDIC_THREE = "\u0663"  # Arabic-Indic digit three
FULL_WIDTH_THREE = "\uff13"  # full-width digit three


@dataclass
class FakeTrack:
    track_type: str
    streamorder: Any
    bit_rate: Any = None
    language: Any = None
    frame_rate_mode: Any = None


@pytest.mark.parametrize(
    "order",
    [
        SUPERSCRIPT_TWO,
        ARABIC_INDIC_THREE,
        FULL_WIDTH_THREE,
        f"1{SUPERSCRIPT_TWO}",
        f"1{FULL_WIDTH_THREE}",
        " 1",
        "1 ",
        "1\n",
        "+1",
        "-1",
        "1.0",
        "",
        None,
    ],
)
def test_a_stream_order_that_is_not_ascii_digits_is_not_matched(order: Any) -> None:
    tracks = [FakeTrack("Audio", order, 128_000, language="pt-BR", frame_rate_mode="CFR")]
    assert mediainfo.track_data(tracks) == mediainfo.MediaInfoData()


@pytest.mark.parametrize(("order", "index"), [("0", 0), ("12", 12), ("007", 7), (4, 4)])
def test_an_ascii_stream_order_is_matched(order: Any, index: int) -> None:
    tracks = [FakeTrack("Video", order, 4_000_000, language="hu", frame_rate_mode="VFR")]
    data = mediainfo.track_data(tracks)
    assert data.bitrates == {("video", index): 4_000_000}
    assert data.languages == {("video", index): "hu"}
    assert data.frame_rate_modes == {("video", index): "VFR"}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (f"{FULL_WIDTH_THREE}{FULL_WIDTH_THREE}", None),
        (f"{ARABIC_INDIC_THREE}00", 0),  # "00" is the first ASCII number: 0 is no bit rate
        (f"{ARABIC_INDIC_THREE} 128000", 128_000),
        (f"128{SUPERSCRIPT_TWO}", 128),
    ],
)
def test_a_bit_rate_is_read_from_ascii_digits(value: str, expected: int | None) -> None:
    data = mediainfo.track_data([FakeTrack("Audio", "1", value)])
    assert data.bitrates == ({} if not expected else {("audio", 1): expected})
