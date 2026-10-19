"""The analysis scans through the facade, with the real FFmpeg: concurrent updates of one source
keep each value, and ``mov_text`` tracks count their cues, not the muxer's empty samples.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest

from reframe.models import (
    BitrateInfo,
    BitrateSource,
    MediaSource,
    SubtitleScanTrack,
    TaskInfo,
    TaskState,
)
from reframe.service import Reframe
from reframe_testing import media

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


def _ffmpeg(cwd: Path, *args: str) -> None:
    ffmpeg = media.find_ffmpeg()
    assert ffmpeg
    subprocess.run(
        [ffmpeg, "-v", "error", "-y", *args], cwd=cwd, check=True, capture_output=True, timeout=60
    )


async def test_two_bitrate_scans_keep_both_measurements(
    app: Reframe, tmp_path: Path, fixture_media: FixtureMedia
) -> None:
    """Both scans run at once (the ``bitrate_scan`` limit is 2) and each probed the source
    before the other stored its value."""
    path = _copy(fixture_media, "dts-hd-ma", tmp_path)
    probed = await app.sources.probe(path)
    assert isinstance(probed, MediaSource)
    assert [(a.index, a.bitrate.source) for a in probed.audio[:2]] == [
        (1, BitrateSource.UNKNOWN),  # DTS-HD MA: no bit rate in the file
        (2, BitrateSource.STREAM),  # AC-3: from the frame headers
    ]
    first = app.sources.bitrate_scan(path, 1)
    second = app.sources.bitrate_scan(path, 2)
    for info in (first, second):
        await _finish(app, info)
    known = await app.sources.get(path)
    assert known is not None
    assert [(a.index, a.bitrate.source) for a in known.audio[:2]] == [
        (1, BitrateSource.MEASURED),
        (2, BitrateSource.MEASURED),
    ]
    again = await app.sources.probe(path)  # the probe cache has both too
    assert isinstance(again, MediaSource)
    assert [a.bitrate for a in again.audio[:2]] == [a.bitrate for a in known.audio[:2]]


async def test_subtitle_scan_and_bitrate_scan_keep_both(
    app: Reframe, tmp_path: Path, fixture_media: FixtureMedia
) -> None:
    path = _copy(fixture_media, "multitrack", tmp_path)
    probed = await app.sources.probe(path)
    assert isinstance(probed, MediaSource)
    assert probed.subtitles
    first = app.sources.bitrate_scan(path, probed.audio[0].index)
    second = app.sources.subtitle_scan(path)
    for info in (first, second):
        await _finish(app, info)
    known = await app.sources.get(path)
    assert known is not None
    assert known.audio[0].bitrate.source is BitrateSource.MEASURED
    assert [s.event_count_source for s in known.subtitles] == ["measured"] * len(known.subtitles)


async def test_concurrent_updates_are_serialised(
    app: Reframe, tmp_path: Path, fixture_media: FixtureMedia
) -> None:
    """``SourceService.update`` reads the latest known source under a per-file lock: two
    updates started together both land."""
    path = _copy(fixture_media, "dts-hd-ma", tmp_path)
    probed = await app.sources.probe(path)
    assert isinstance(probed, MediaSource)

    def measured(index: int, value: int) -> Callable[[MediaSource], MediaSource]:
        def change(latest: MediaSource) -> MediaSource:
            updated = latest.model_copy(deep=True)
            for track in updated.audio:
                if track.index == index:
                    track.bitrate = BitrateInfo(value=value, source=BitrateSource.MEASURED)
            return updated

        return change

    await asyncio.gather(
        app.sources.update(probed, measured(1, 1_000)),
        app.sources.update(probed, measured(2, 2_000)),
        app.sources.update(probed, measured(3, 3_000)),
    )
    known = await app.sources.get(path)
    assert known is not None
    assert [a.bitrate.value for a in known.audio] == [1_000, 2_000, 3_000]


async def test_update_after_the_file_changed_stores_nothing(
    app: Reframe, tmp_path: Path, fixture_media: FixtureMedia
) -> None:
    """A value measured on an older version of the file is not applied to the new one."""
    path = _copy(fixture_media, "dts-hd-ma", tmp_path)
    old = await app.sources.probe(path)
    assert isinstance(old, MediaSource)
    with path.open("ab") as handle:  # the file changes (a new size)
        handle.write(b"\0" * 16)
    new = await app.sources.probe(path)
    assert isinstance(new, MediaSource)
    assert new.ref.fingerprint != old.ref.fingerprint

    def change(latest: MediaSource) -> MediaSource:
        updated = latest.model_copy(deep=True)
        updated.audio[0].bitrate = BitrateInfo(value=1_000, source=BitrateSource.MEASURED)
        return updated

    await app.sources.update(old, change)
    known = await app.sources.get(path)
    assert known is not None
    assert known.audio[0].bitrate == new.audio[0].bitrate


CUES = [(1.0, 2.0, "Hello"), (3.0, 4.0, "World"), (5.0, 6.5, "Goodbye")]


@pytest.mark.parametrize("extension", ["mp4", "mov"])
async def test_mov_text_event_count(app: Reframe, tmp_path: Path, extension: str) -> None:
    """3 SRT cues muxed as ``mov_text``: FFmpeg writes 6 samples (an empty 2-byte sample
    before the first cue and in each gap, ``testdata/README.md``); the scan counts 3."""
    (tmp_path / "three.srt").write_text(media.srt(CUES), encoding="utf-8")
    name = f"three.{extension}"
    _ffmpeg(
        tmp_path, "-f", "lavfi", "-i", "color=c=black:s=64x64:r=10:d=8", "-i", "three.srt",
        "-map", "0", "-map", "1", "-c:v", "libx264", "-c:s", "mov_text", name,
    )  # fmt: skip
    path = tmp_path / name
    done = await _finish(app, app.sources.subtitle_scan(path))
    assert app.tasks.value(done.id).tracks == [SubtitleScanTrack(stream_index=1, event_count=3)]
    known = await app.sources.get(path)
    assert known is not None
    assert (known.subtitles[0].codec, known.subtitles[0].event_count) == ("mov_text", 3)


EMPTY_CUES_ASS = """\
[Script Info]
ScriptType: v4.00+
PlayResX: 384
PlayResY: 288

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, \
Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, \
Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,16,&Hffffff,&Hffffff,&H0,&H0,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,0

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,Hello
Dialogue: 0,0:00:02.00,0:00:03.00,Default,,0,0,0,,
Dialogue: 0,0:00:03.00,0:00:04.00,Default,,0,0,0,,{\\b1}{\\b0}
Dialogue: 0,0:00:05.00,0:00:06.00,Default,,0,0,0,,{\\i1}Styled{\\i0}
"""


async def test_mov_text_cues_without_text_are_not_events(app: Reframe, tmp_path: Path) -> None:
    """A cue with empty text, or with override tags only, gets no sample of its own in MP4:
    its time is covered by an empty 2-byte sample. A styled cue has style boxes after its
    text and counts."""
    (tmp_path / "cues.ass").write_text(EMPTY_CUES_ASS, encoding="utf-8")
    _ffmpeg(tmp_path, "-i", "cues.ass", "-c:s", "mov_text", "-f", "mp4", "cues.mp4")
    done = await _finish(app, app.sources.subtitle_scan(tmp_path / "cues.mp4"))
    assert app.tasks.value(done.id).tracks == [SubtitleScanTrack(stream_index=0, event_count=2)]
