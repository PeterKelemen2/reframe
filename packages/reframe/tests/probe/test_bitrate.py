"""The bitrate chain: stream → statistics tags → unknown, and the stale-tag check."""

from __future__ import annotations

from typing import Any

import pytest

from reframe.models import BitrateInfo, BitrateSource
from reframe.probe import bitrate


@pytest.mark.parametrize(
    ("stream", "expected"),
    [
        ({"bit_rate": "192000"}, (192000, BitrateSource.STREAM)),
        ({"bit_rate": 640000}, (640000, BitrateSource.STREAM)),
        ({"bit_rate": "0", "tags": {"BPS": "1000"}}, (1000, BitrateSource.STATS_TAG)),
        ({"tags": {"BPS": "3912000"}}, (3912000, BitrateSource.STATS_TAG)),
        ({"tags": {"BPS-eng": "2104000"}}, (2104000, BitrateSource.STATS_TAG)),
        ({"tags": {"bps": "128000"}}, (128000, BitrateSource.STATS_TAG)),
        (
            {"tags": {"NUMBER_OF_BYTES": "1000000", "DURATION": "00:00:08.000000000"}},
            (1000000, BitrateSource.STATS_TAG),
        ),
        (
            {"tags": {"NUMBER_OF_BYTES-eng": "500", "DURATION-eng": "00:00:04.000"}},
            (1000, BitrateSource.STATS_TAG),
        ),
        ({"tags": {"BPS": "junk", "NUMBER_OF_BYTES": "100"}}, (None, BitrateSource.UNKNOWN)),
        (
            {"tags": {"NUMBER_OF_BYTES": "100", "DURATION": "0:00:00"}},
            (None, BitrateSource.UNKNOWN),
        ),
        ({"tags": {"DURATION": "00:00:04.000000000"}}, (None, BitrateSource.UNKNOWN)),
        ({"tags": "junk"}, (None, BitrateSource.UNKNOWN)),
        ({}, (None, BitrateSource.UNKNOWN)),
    ],
)
def test_stream_bitrate(stream: dict[str, Any], expected: tuple[int | None, BitrateSource]) -> None:
    info = bitrate.stream_bitrate(stream)
    assert (info.value, info.source) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("192000", 192000),
        (" 7.6 ", 8),
        (True, None),
        (None, None),
        (0, None),
        ("-5", None),
        ("nan", None),
        ("inf", None),
        ("x", None),
    ],
)
def test_positive_int(value: Any, expected: int | None) -> None:
    assert bitrate.positive_int(value) == expected


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("00:00:04.021000000", 4.021),
        ("01:00:00", 3600.0),
        ("2:03.5", 123.5),
        ("junk", None),
        (None, None),
    ],
)
def test_parse_duration_tag(text: str | None, seconds: float | None) -> None:
    assert bitrate.parse_duration_tag(text) == (
        pytest.approx(seconds) if seconds is not None else None
    )


def test_tag_value_prefers_the_exact_key() -> None:
    assert bitrate.tag_value({"BPS-eng": "1", "BPS": "2"}, "bps") == "2"
    assert bitrate.tag_value({"BPS-eng": "1"}, "BPS") == "1"
    assert bitrate.tag_value(None, "BPS") is None
    assert bitrate.tag_value({"BPSX": "1"}, "BPS") is None


def _doc(*streams: dict[str, Any], **fmt: Any) -> dict[str, Any]:
    return {"streams": list(streams), "format": fmt}


def _stats(index: int, **tags: str) -> dict[str, Any]:
    return {"index": index, "codec_type": "video", "tags": {"_STATISTICS_TAGS": "BPS", **tags}}


def test_plausible_stats_are_trusted() -> None:
    check = bitrate.check_stats_tags(
        _doc(
            _stats(0, BPS="900000", NUMBER_OF_BYTES="225000", DURATION="00:00:02.000"),
            _stats(1, BPS="96000", NUMBER_OF_BYTES="24000", DURATION="00:00:02.000"),
            size="260000",
            bit_rate="1040000",
            duration="2.0",
        )
    )
    assert check.stale == {}
    assert check.trusted(0)
    assert check.trusted(1)


@pytest.mark.parametrize(
    ("stream", "fmt", "reason"),
    [
        (
            _stats(0, NUMBER_OF_BYTES="465185"),
            {"size": "49428"},
            "the tracks' NUMBER_OF_BYTES add up to 465185 bytes, more than the file's 49428 bytes",
        ),
        (
            _stats(0, BPS="1858881"),
            {"bit_rate": "197514"},
            "BPS 1858881 is more than the file's bit rate 197514",
        ),
        (
            _stats(0, DURATION="01:00:00.000"),
            {"duration": "2.0"},
            "DURATION 3600 s is longer than the file (2 s)",
        ),
    ],
)
def test_stale_stats(stream: dict[str, Any], fmt: dict[str, Any], reason: str) -> None:
    assert bitrate.check_stats_tags(_doc(stream, **fmt)).stale == {0: reason}


def test_the_byte_sum_check_covers_every_stream() -> None:
    check = bitrate.check_stats_tags(
        _doc(_stats(0, NUMBER_OF_BYTES="900"), _stats(1, NUMBER_OF_BYTES="200"), size="1000")
    )
    assert set(check.stale) == {0, 1}


def test_streams_without_stats_and_junk() -> None:
    plain = {"index": 0, "codec_type": "video", "tags": {"DURATION": "99:00:00"}}
    assert bitrate.check_stats_tags(_doc(plain, duration="1.0")).stale == {}
    assert bitrate.check_stats_tags({"streams": "junk", "format": []}).stale == {}
    tiny_rate = _stats(0, BPS="1000")
    assert bitrate.check_stats_tags(_doc(tiny_rate, bit_rate="1000", duration="inf")).stale == {}


def test_stream_bitrate_skips_untrusted_stats() -> None:
    stream = {"tags": {"BPS": "1000"}}
    assert bitrate.stream_bitrate(stream, trust_stats=False) == BitrateInfo()
    assert bitrate.stream_bitrate({"bit_rate": "5"}, trust_stats=False).value == 5


def test_a_compressed_track_is_left_out_of_the_size_check() -> None:
    """mkvmerge zlib-compresses PGS: its NUMBER_OF_BYTES counts the bytes before compression,
    so the sum passes the file size although every tag is right."""
    streams = (
        _stats(0, NUMBER_OF_BYTES="900"),
        _stats(1, NUMBER_OF_BYTES="50"),
        {"index": 2, "codec_type": "subtitle", "tags": {"NUMBER_OF_BYTES": "300"}},
    )
    doc = _doc(*streams, size="1000")
    assert set(bitrate.check_stats_tags(doc).stale) == {0, 1, 2}
    assert bitrate.check_stats_tags(doc, compressed={2}).stale == {}


def test_a_compressed_track_is_still_checked_against_the_rate_and_duration() -> None:
    sub = _stats(1, BPS="5000000")
    long = _stats(2, DURATION="01:00:00.000")
    check = bitrate.check_stats_tags(
        _doc(sub, long, size="1000", bit_rate="1000000", duration="2.0"), compressed={1, 2}
    )
    assert set(check.stale) == {1, 2}


def test_an_uncompressed_overrun_still_makes_every_uncompressed_track_stale() -> None:
    doc = _doc(
        _stats(0, NUMBER_OF_BYTES="1500"),
        {"index": 1, "codec_type": "subtitle", "tags": {"NUMBER_OF_BYTES": "10"}},
        size="1000",
    )
    assert set(bitrate.check_stats_tags(doc, compressed={1}).stale) == {0}
