"""The analysis scans through the facade, with the real FFmpeg and ffprobe on the fixtures."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest

from reframe.models import (
    BitrateInfo,
    BitrateScan,
    BitrateSource,
    LoudnessMeasurement,
    MediaSource,
    SubtitleScan,
    SubtitleScanTrack,
    TaskInfo,
    TaskState,
    TrackRole,
)
from reframe.service import Reframe
from reframe_testing import dts, media, vobsub

pytestmark = [pytest.mark.anyio, pytest.mark.needs_ffmpeg]

FixtureMedia = Callable[[str], Path]


@pytest.fixture
async def app(tmp_path: Path) -> AsyncIterator[Reframe]:
    reframe = await Reframe.create(
        tmp_path / "config", tmp_path / "data", cache_dir=tmp_path / "cache"
    )
    try:
        yield reframe
    finally:
        await reframe.close()


async def _finish(app: Reframe, info: TaskInfo) -> TaskInfo:
    done = await app.tasks.wait(info.id)
    assert done.state is TaskState.DONE, done.error
    return done


def _copy(fixture_media: FixtureMedia, name: str, tmp_path: Path) -> Path:
    source = fixture_media(name)
    target = tmp_path / source.name
    shutil.copy(source, target)
    return target


def _dts_bitrate() -> float:
    """The exact bit rate of the fixture's DTS-HD MA track: every byte that the writer wrote,
    over the time it lasts."""
    return len(dts.dts_hd_ma(media.DTS_HD_MA_SECONDS)) * 8 / media.DTS_HD_MA_SECONDS


async def test_measure_the_bit_rate_of_a_dts_hd_ma_track(
    tmp_path: Path, fixture_media: FixtureMedia
) -> None:
    path = _copy(fixture_media, "dts-hd-ma", tmp_path)
    app = await Reframe.create(tmp_path / "config", tmp_path / "data", cache_dir=tmp_path / "cache")
    try:
        probed = await app.sources.probe(path)
        assert isinstance(probed, MediaSource)
        track = probed.audio[0]
        assert (track.index, track.display_codec, track.lossless) == (1, "DTS-HD MA", True)
        assert track.bitrate == BitrateInfo()  # no bit rate in the file: "—" and Measure

        info = app.sources.bitrate_scan(path, 1)
        assert (info.kind, info.state) == ("bitrate_scan", TaskState.QUEUED)
        done = await _finish(app, info)
        scan = app.tasks.value(done.id)
        assert isinstance(scan, BitrateScan)
        assert scan.bitrate.source is BitrateSource.MEASURED
        assert scan.bitrate.value is not None
        assert scan.bitrate.value == pytest.approx(_dts_bitrate(), rel=1e-3)
        assert scan.packets == dts.frame_count(media.DTS_HD_MA_SECONDS)
        assert scan.bytes == len(dts.dts_hd_ma(media.DTS_HD_MA_SECONDS))
        assert scan.duration == pytest.approx(4.0, abs=0.002)
        assert done.result == scan.model_dump(mode="json")
        assert done.progress == 100.0

        known = await app.sources.get(path)
        assert known is not None
        assert known.audio[0].bitrate == scan.bitrate
        assert known.audio[1].bitrate == BitrateInfo(value=224_000, source=BitrateSource.STREAM)
    finally:
        await app.close()

    # A new Reframe (another process, the next day) reads the measurement from the probe cache.
    again = await Reframe.create(
        tmp_path / "config", tmp_path / "data", cache_dir=tmp_path / "cache"
    )
    try:
        cached = await again.sources.probe(path)
        assert isinstance(cached, MediaSource)
        assert cached.audio[0].bitrate == scan.bitrate
    finally:
        await again.close()


async def test_bitrate_scan_of_a_video_stream(
    app: Reframe, tmp_path: Path, fixture_media: FixtureMedia
) -> None:
    path = _copy(fixture_media, "chapters", tmp_path)
    done = await _finish(app, app.sources.bitrate_scan(path, 0))
    scan = app.tasks.value(done.id)
    assert isinstance(scan, BitrateScan)
    assert scan.packets == 125  # 5 s at 25 fps
    assert scan.duration is not None
    assert scan.duration == pytest.approx(5.0, abs=0.001)
    assert scan.bitrate.value == round(scan.bytes * 8 / scan.duration)
    known = await app.sources.get(path)
    assert known is not None
    assert known.video[0].bitrate == scan.bitrate


async def test_subtitle_scan_of_pgs_counts_the_forced_display_sets(
    tmp_path: Path, fixture_media: FixtureMedia
) -> None:
    path = _copy(fixture_media, "pgs", tmp_path)
    events = media.PGS_EVENTS
    app = await Reframe.create(tmp_path / "config", tmp_path / "data", cache_dir=tmp_path / "cache")
    try:
        done = await _finish(app, app.sources.subtitle_scan(path))
        assert app.tasks.value(done.id) == SubtitleScan(
            path=path,
            tracks=[
                # show + clear display set per subtitle; the forced ones counted once
                SubtitleScanTrack(
                    stream_index=1,
                    event_count=2 * len(events["eng"]),
                    forced_event_count=sum(e.forced for e in events["eng"]),
                ),
                SubtitleScanTrack(
                    stream_index=2,
                    event_count=2 * len(events["eng-forced"]),
                    forced_event_count=len(events["eng-forced"]),
                ),
            ],
        )
        known = await app.sources.get(path)
        assert known is not None
        counts = [
            (s.event_count, s.event_count_source, s.forced_event_count) for s in known.subtitles
        ]
        assert counts == [(12, "measured", 2), (4, "measured", 2)]
        assert not list((tmp_path / "cache" / "scans").iterdir())  # the .sup copies are gone
    finally:
        await app.close()
    again = await Reframe.create(
        tmp_path / "config", tmp_path / "data", cache_dir=tmp_path / "cache"
    )
    try:
        cached = await again.sources.probe(path)
        assert isinstance(cached, MediaSource)
        assert [(s.event_count, s.forced_event_count) for s in cached.subtitles] == [
            (12, 2),
            (4, 2),
        ]
    finally:
        await again.close()


async def test_subtitle_scan_of_text_and_vobsub_tracks(
    app: Reframe, fixture_media: FixtureMedia
) -> None:
    multitrack = fixture_media("multitrack")
    done = await _finish(app, app.sources.subtitle_scan(multitrack, [6, 4]))
    assert app.tasks.value(done.id) == SubtitleScan(
        path=multitrack,
        tracks=[
            SubtitleScanTrack(stream_index=6, event_count=1),
            SubtitleScanTrack(stream_index=4, event_count=2),
        ],
    )
    text = fixture_media("text-subs")
    done = await _finish(app, app.sources.subtitle_scan(text))
    assert [(t.event_count, t.forced_event_count) for t in app.tasks.value(done.id).tracks] == [
        (2, None),  # SRT
        (3, None),  # ASS: one packet per Dialogue line
    ]
    vob = fixture_media("vobsub")
    done = await _finish(app, app.sources.subtitle_scan(vob))
    assert [(t.event_count, t.forced_event_count) for t in app.tasks.value(done.id).tracks] == [
        (len(media.VOBSUB_EVENTS["eng"]), 0),
        (len(media.VOBSUB_EVENTS["fre"]), 0),  # forced disposition, no forced subpictures
    ]


def _ffmpeg(cwd: Path, *args: str) -> None:
    ffmpeg = media.find_ffmpeg()
    assert ffmpeg
    subprocess.run(
        [ffmpeg, "-v", "error", "-y", *args], cwd=cwd, check=True, capture_output=True, timeout=60
    )


def _forced_vobsub(tmp_path: Path, forced: set[int]) -> Path:
    """A VobSub track whose subpictures ``forced`` start with the forced start command
    (``0x00``, not ``0x01``): the flag that ``forced_subs_only`` keeps."""
    events = [vobsub.Event(500, 1000, 300), vobsub.Event(1200, 1800, 200)]
    events.append(vobsub.Event(2000, 2600, 400))
    idx, sub = vobsub.vobsub(events, language="en")
    data = bytearray(sub)
    for i in forced:
        pack = bytes(data[i * vobsub.PACK_SIZE : (i + 1) * vobsub.PACK_SIZE])
        # the end of control sequence 1 (start display, end) followed by sequence 2
        # (delay, offset, stop display, end)
        pos = pack.find(b"\x01\xff")
        while pack[pos + 6 : pos + 8] != b"\x02\xff":
            pos = pack.find(b"\x01\xff", pos + 1)
        data[i * vobsub.PACK_SIZE + pos] = 0x00
    (tmp_path / "v.idx").write_text(idx, encoding="utf-8")
    (tmp_path / "v.sub").write_bytes(bytes(data))
    _ffmpeg(tmp_path, "-i", "v.idx", "-map", "0:s", "-c:s", "copy", "v.mkv")
    return tmp_path / "v.mkv"


async def test_subtitle_scan_counts_forced_vobsub_subpictures(app: Reframe, tmp_path: Path) -> None:
    path = _forced_vobsub(tmp_path, {0, 2})
    done = await _finish(app, app.sources.subtitle_scan(path))
    assert app.tasks.value(done.id).tracks == [
        SubtitleScanTrack(stream_index=0, event_count=3, forced_event_count=2)
    ]


async def test_loudness_of_a_track(app: Reframe, fixture_media: FixtureMedia) -> None:
    path = fixture_media("multitrack")
    done = await _finish(app, app.sources.loudness_scan(path, 2))
    result = app.tasks.value(done.id)
    assert isinstance(result, LoudnessMeasurement)
    # A 660 Hz sine at FFmpeg's default amplitude (1/8: -18 dBFS), upmixed from mono to
    # stereo at -3 dB per channel.
    assert result.true_peak == pytest.approx(-20.6, abs=1.0)
    assert result.integrated is not None
    assert result.integrated == pytest.approx(-21.7, abs=1.0)
    assert result.lra == pytest.approx(0.0, abs=0.5)  # a steady tone
    assert result.threshold == pytest.approx(result.integrated - 10.0, abs=0.1)
    assert (result.start, result.duration) == (None, None)
    assert done.progress == 100.0


async def test_loudness_of_a_part(app: Reframe, fixture_media: FixtureMedia) -> None:
    path = fixture_media("dts-hd-ma")
    done = await _finish(app, app.sources.loudness_scan(path, 1, start=1.0, duration=1.0))
    result = app.tasks.value(done.id)
    assert isinstance(result, LoudnessMeasurement)
    assert (result.start, result.duration) == (1.0, 1.0)
    assert result.integrated is not None  # the second second of the DTS-HD MA track (-6 dB)
    whole = app.tasks.value((await _finish(app, app.sources.loudness_scan(path, 1))).id)
    assert whole.integrated is not None
    assert result.integrated < whole.integrated


async def test_loudness_of_silence_is_none(app: Reframe, tmp_path: Path) -> None:
    _ffmpeg(
        tmp_path, "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "2", "-c:a", "flac",
        "silence.mka",
    )  # fmt: skip
    done = await _finish(app, app.sources.loudness_scan(tmp_path / "silence.mka", 0))
    result = app.tasks.value(done.id)
    assert isinstance(result, LoudnessMeasurement)
    assert (result.integrated, result.true_peak) == (None, None)  # loudnorm says -inf
    assert result.lra == 0.0
    assert result.threshold == -70.0


async def test_loudness_after_the_end_fails(app: Reframe, fixture_media: FixtureMedia) -> None:
    path = fixture_media("multitrack")
    done = await app.tasks.wait(app.sources.loudness_scan(path, 1, start=100.0).id)
    assert done.state is TaskState.FAILED
    assert done.error is not None
    assert "Stream 1 of multitrack.mkv has no audio in the part to measure." in done.error


async def test_measured_counts_feed_the_forced_heuristic(app: Reframe, tmp_path: Path) -> None:
    """FFmpeg writes no ``NUMBER_OF_FRAMES``, so the forced heuristic has no counts after
    the probe; the scan stores them and works the roles out again."""
    full = [(i + 0.1, i + 0.9, f"Line {i}") for i in range(12)]
    signs = [(2.1, 2.9, "A SIGN")]
    (tmp_path / "full.srt").write_text(media.srt(full), encoding="utf-8")
    (tmp_path / "signs.srt").write_text(media.srt(signs), encoding="utf-8")
    _ffmpeg(
        tmp_path, "-i", "full.srt", "-i", "signs.srt", "-map", "0", "-map", "1", "-c:s", "srt",
        "-metadata:s:s:0", "language=eng", "-metadata:s:s:1", "language=eng", "subs.mkv",
    )  # fmt: skip
    path = tmp_path / "subs.mkv"
    before = await app.sources.probe(path)
    assert isinstance(before, MediaSource)
    assert [s.event_count for s in before.subtitles] == [None, None]
    assert [r.role for r in before.subtitles[1].roles] == [TrackRole.MAIN]
    await _finish(app, app.sources.subtitle_scan(path))
    after = await app.sources.get(path)
    assert after is not None
    assert [s.event_count for s in after.subtitles] == [12, 1]
    assert [r.role for r in after.subtitles[1].roles] == [TrackRole.FORCED]
