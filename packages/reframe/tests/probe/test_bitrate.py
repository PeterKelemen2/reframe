"""The bitrate chain (C-3): stream → statistics tags → MediaInfo → unknown.

MediaInfo is tested with mocks: whether ``pymediainfo`` and its library load differs between
machines (the ``pymediainfo`` 7 wheel bundles ``libmediainfo``).
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from reframe.models import BitrateInfo, BitrateSource, RoleEvidence, TrackRole
from reframe.probe import bitrate, mediainfo, parse_ffprobe, prober


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
        ({"bit_rate": "N/A"}, (None, BitrateSource.UNKNOWN)),
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
        ("", None),
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


# --------------------------------------------------------------------------- MediaInfo


@dataclass
class FakeTrack:
    track_type: str
    streamorder: str | None
    bit_rate: Any = None
    bit_rate_nominal: Any = None


def test_track_bitrates() -> None:
    tracks = [
        FakeTrack("General", None, 5_000_000),
        FakeTrack("Video", "0", 4_000_000),
        FakeTrack("Audio", "1", "2104000 / 1509000"),  # several values: the first counts
        FakeTrack("Audio", "2", None, 640_000.0),  # nominal
        FakeTrack("Audio", "3", "junk"),
        FakeTrack("Audio", "0-1", 128000),  # MPEG-TS program order: not matched
        FakeTrack("Text", "4", 100),
        FakeTrack("Audio", "5", 0),
        FakeTrack("Audio", "6", True),
        FakeTrack("Audio", "7", -2.0),
    ]
    assert mediainfo.track_bitrates(tracks) == {
        ("video", 0): 4_000_000,
        ("audio", 1): 2_104_000,
        ("audio", 2): 640_000,
    }


@pytest.fixture
def no_mediainfo_cache() -> Any:
    mediainfo._parser.cache_clear()
    yield
    mediainfo._parser.cache_clear()


def test_mediainfo_not_importable(
    monkeypatch: pytest.MonkeyPatch, no_mediainfo_cache: None
) -> None:
    def fail(name: str) -> Any:
        raise ImportError(name)

    monkeypatch.setattr(importlib, "import_module", fail)
    assert not mediainfo.mediainfo_available()
    assert mediainfo.read_bitrates(Path("x.mkv")) == {}


class _FakeModule:
    def __init__(self, can_parse: bool, tracks: list[FakeTrack]) -> None:
        tracks_ = tracks

        class MediaInfo:
            @staticmethod
            def can_parse() -> bool:
                return can_parse

            @staticmethod
            def parse(path: str) -> Any:
                class Info:
                    tracks = tracks_

                return Info()

        self.MediaInfo = MediaInfo


def test_mediainfo_library_does_not_load(
    monkeypatch: pytest.MonkeyPatch, no_mediainfo_cache: None
) -> None:
    monkeypatch.setattr(importlib, "import_module", lambda name: _FakeModule(False, []))
    assert not mediainfo.mediainfo_available()


def test_mediainfo_reads_bitrates(
    monkeypatch: pytest.MonkeyPatch, no_mediainfo_cache: None
) -> None:
    module = _FakeModule(True, [FakeTrack("Audio", "1", 1_509_000)])
    monkeypatch.setattr(importlib, "import_module", lambda name: module)
    assert mediainfo.mediainfo_available()
    assert mediainfo.read_bitrates(Path("x.mkv")) == {("audio", 1): 1_509_000}


def _source() -> Any:
    data = {
        "streams": [
            {"index": 0, "codec_type": "video", "codec_name": "h264", "width": 64, "height": 64},
            {
                "index": 1,
                "codec_type": "audio",
                "codec_name": "dts",
                "channels": 6,
                "tags": {"language": "eng"},
            },
            {
                "index": 2,
                "codec_type": "audio",
                "codec_name": "ac3",
                "channels": 2,
                "tags": {"language": "eng"},
            },
            {"index": 3, "codec_type": "audio", "codec_name": "ac3", "bit_rate": "448000"},
        ],
        "format": {"format_name": "matroska,webm", "duration": "1"},
    }
    return parse_ffprobe(data, Path("/m/x.mkv"))


async def test_apply_mediainfo_fills_unknown_bitrates_and_redoes_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rates = {("audio", 1): 1_509_000, ("audio", 2): 192_000, ("audio", 3): 1, ("video", 0): 9}
    monkeypatch.setattr(mediainfo, "read_bitrates", lambda path: rates)
    source = _source()
    assert source.audio[1].roles[0].role is TrackRole.MAIN  # unknown bit rate: no heuristic
    await prober._apply_mediainfo(source, Path("/m/x.mkv"))
    assert source.video[0].bitrate == BitrateInfo(value=9, source=BitrateSource.MEDIAINFO)
    assert source.audio[0].bitrate == BitrateInfo(value=1_509_000, source=BitrateSource.MEDIAINFO)
    assert source.audio[2].bitrate.source is BitrateSource.STREAM  # not replaced
    assert [(r.role, r.evidence) for r in source.audio[1].roles] == [
        (TrackRole.COMMENTARY, RoleEvidence.HEURISTIC)
    ]


async def test_apply_mediainfo_skips_when_nothing_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(path: Path) -> Any:
        raise AssertionError("must not be called")

    monkeypatch.setattr(mediainfo, "read_bitrates", explode)
    source = _source()
    for stream in [*source.video, *source.audio]:
        stream.bitrate = BitrateInfo(value=1, source=BitrateSource.STREAM)
    await prober._apply_mediainfo(source, Path("/m/x.mkv"))


async def test_apply_mediainfo_error_is_a_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(path: Path) -> Any:
        raise RuntimeError("cannot parse")

    monkeypatch.setattr(mediainfo, "read_bitrates", fail)
    source = _source()
    await prober._apply_mediainfo(source, Path("/m/x.mkv"))
    assert source.warnings[-1] == "MediaInfo could not read the file: cannot parse"
    assert source.audio[0].bitrate.source is BitrateSource.UNKNOWN


async def test_apply_mediainfo_timeout_is_a_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    import threading

    release = threading.Event()

    def slow(path: Path) -> Any:
        release.wait(5)
        return {}

    monkeypatch.setattr(mediainfo, "read_bitrates", slow)
    monkeypatch.setattr(prober, "MEDIAINFO_TIMEOUT", 0.05)
    source = _source()
    try:
        await prober._apply_mediainfo(source, Path("/m/x.mkv"))
    finally:
        release.set()
    assert source.warnings[-1] == "MediaInfo did not finish within 0.05 s."


pytestmark = pytest.mark.anyio
