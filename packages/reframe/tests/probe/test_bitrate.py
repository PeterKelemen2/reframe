"""The bitrate chain: stream → statistics tags → MediaInfo → unknown.

MediaInfo is mocked: whether ``pymediainfo`` and its library load differs between machines.
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


@dataclass
class FakeTrack:
    track_type: str
    streamorder: str | None
    bit_rate: Any = None
    bit_rate_nominal: Any = None
    language: Any = None
    frame_rate_mode: Any = None


def test_track_data() -> None:
    tracks = [
        FakeTrack("General", None, 5_000_000),
        FakeTrack("Video", "0", 4_000_000, language="zh-Hant-TW", frame_rate_mode="VFR"),
        FakeTrack("Audio", "1", "2104000 / 1509000", language="pt-BR"),  # first value counts
        FakeTrack("Audio", "2", None, 640_000.0, language="Portuguese (BR)"),  # not a tag
        FakeTrack("Audio", "3", "junk", frame_rate_mode="VFR"),  # audio: no mode
        FakeTrack("Audio", "0-1", 128000),
        FakeTrack("Text", "4", 100, language="hu"),
        FakeTrack("Audio", "5", 0),
        FakeTrack("Audio", "6", True),
        FakeTrack("Audio", "7", -2.0, frame_rate_mode="CFR"),
        FakeTrack("Video", "8", frame_rate_mode="weird"),
        FakeTrack("Menu", "9", 1),
    ]
    data = mediainfo.track_data(tracks)
    assert data.bitrates == {
        ("video", 0): 4_000_000,
        ("audio", 1): 2_104_000,
        ("audio", 2): 640_000,
    }
    assert data.languages == {
        ("video", 0): "zh-Hant-TW",
        ("audio", 1): "pt-BR",
        ("subtitle", 4): "hu",
    }
    assert data.frame_rate_modes == {("video", 0): "VFR"}


@pytest.fixture
def no_mediainfo_cache() -> Any:
    mediainfo._library.cache_clear()
    yield
    mediainfo._library.cache_clear()


def test_mediainfo_not_importable(
    monkeypatch: pytest.MonkeyPatch, no_mediainfo_cache: None
) -> None:
    def fail(name: str) -> Any:
        raise ImportError(name)

    monkeypatch.setattr(importlib, "import_module", fail)
    assert not mediainfo.mediainfo_available()
    assert mediainfo.mediainfo_version() is None
    assert mediainfo.read_mediainfo(Path("x.mkv")) == mediainfo.MediaInfoData()


class _FakeModule:
    __version__ = "9.9"

    def __init__(self, can_parse: bool, tracks: list[FakeTrack], library: bool = True) -> None:
        tracks_ = tracks

        class MediaInfo:
            @staticmethod
            def can_parse() -> bool:
                return can_parse

            @staticmethod
            def _get_library() -> tuple[object, object, str, tuple[int, ...]]:
                if not library:
                    raise OSError("no")
                return (None, None, "25.04", (25, 4))

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


def test_mediainfo_reads_tracks_and_version(
    monkeypatch: pytest.MonkeyPatch, no_mediainfo_cache: None
) -> None:
    module = _FakeModule(True, [FakeTrack("Audio", "1", 1_509_000, language="pt-BR")])
    monkeypatch.setattr(importlib, "import_module", lambda name: module)
    assert mediainfo.mediainfo_available()
    assert mediainfo.mediainfo_version() == "pymediainfo 9.9, libmediainfo 25.04"
    data = mediainfo.read_mediainfo(Path("x.mkv"))
    assert data.bitrates == {("audio", 1): 1_509_000}
    assert data.languages == {("audio", 1): "pt-BR"}


def test_mediainfo_version_without_library_version(
    monkeypatch: pytest.MonkeyPatch, no_mediainfo_cache: None
) -> None:
    monkeypatch.setattr(importlib, "import_module", lambda name: _FakeModule(True, [], False))
    assert mediainfo.mediainfo_version() == "pymediainfo 9.9"


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
            {"index": 4, "codec_type": "subtitle", "codec_name": "subrip"},
        ],
        "format": {"format_name": "matroska,webm", "duration": "1"},
    }
    return parse_ffprobe(data, Path("/m/x.mkv"))


def test_apply_mediainfo_fills_bitrates_languages_vfr_and_redoes_roles() -> None:
    info = mediainfo.MediaInfoData(
        bitrates={("audio", 1): 1_509_000, ("audio", 2): 192_000, ("audio", 3): 1, ("video", 0): 9},
        languages={("audio", 1): "en-GB", ("subtitle", 4): "pt-BR"},
        frame_rate_modes={("video", 0): "VFR"},
    )
    source = _source()
    assert source.audio[1].roles[0].role is TrackRole.MAIN  # unknown bit rate: no heuristic
    undecided = {0}
    prober._apply_mediainfo(source, info, undecided)
    assert source.video[0].bitrate == BitrateInfo(value=9, source=BitrateSource.MEDIAINFO)
    assert source.audio[0].bitrate == BitrateInfo(value=1_509_000, source=BitrateSource.MEDIAINFO)
    assert source.audio[2].bitrate.source is BitrateSource.STREAM
    assert [(r.role, r.evidence) for r in source.audio[1].roles] == [
        (TrackRole.COMMENTARY, RoleEvidence.HEURISTIC)
    ]
    assert (source.audio[0].language, source.audio[0].language_ietf) == ("eng", "en-GB")
    assert source.subtitles[0].language_ietf == "pt-BR"
    assert source.video[0].vfr
    assert undecided == set()


def test_apply_mediainfo_leaves_decided_vfr_alone() -> None:
    source = _source()
    info = mediainfo.MediaInfoData(frame_rate_modes={("video", 0): "VFR"})
    undecided: set[int] = set()
    prober._apply_mediainfo(source, info, undecided)
    assert not source.video[0].vfr


async def test_read_mediainfo_error_is_a_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(path: Path) -> Any:
        raise RuntimeError("cannot parse")

    monkeypatch.setattr(mediainfo, "read_mediainfo", fail)
    source = _source()
    from reframe.tools import CancelToken

    assert await prober._read_mediainfo(source, Path("/m/x.mkv"), CancelToken()) is None
    assert source.warnings[-1] == "MediaInfo could not read the file: cannot parse"


async def test_read_mediainfo_timeout_and_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    import threading

    from reframe.tools import CancelToken

    release = threading.Event()

    def slow(path: Path) -> Any:
        release.wait(5)
        return mediainfo.MediaInfoData()

    monkeypatch.setattr(mediainfo, "read_mediainfo", slow)
    monkeypatch.setattr(prober, "MEDIAINFO_TIMEOUT", 0.05)
    source = _source()
    try:
        assert await prober._read_mediainfo(source, Path("/m/x.mkv"), CancelToken()) is None
        assert source.warnings[-1] == "MediaInfo did not finish within 0.05 s."
        monkeypatch.setattr(prober, "MEDIAINFO_TIMEOUT", 30.0)
        token = CancelToken()
        import asyncio

        task = asyncio.create_task(prober._read_mediainfo(source, Path("/m/x.mkv"), token))
        await asyncio.sleep(0.02)
        token.cancel()
        assert isinstance(await asyncio.wait_for(task, 1.0), prober._Cancelled)
    finally:
        release.set()


pytestmark = pytest.mark.anyio


def test_apply_mediainfo_rejects_a_bit_rate_above_the_container() -> None:
    source = _source()
    source.container.bitrate = 200_000
    info = mediainfo.MediaInfoData(bitrates={("video", 0): 1_858_881, ("audio", 2): 192_000})
    prober._apply_mediainfo(source, info, set())
    assert source.video[0].bitrate == BitrateInfo()
    assert source.audio[1].bitrate.value == 192_000
    assert source.warnings == [
        "Stream 0: MediaInfo's bit rate 1858881 is more than the file's 200000; not used."
    ]
