"""Subtitle scans (05 §C-10, 03 §Subtitles): event counts, and the forced events of PGS and
VobSub tracks (the *Events* column and the foreign-audio-search suggestion).

Up to three kinds of passes over the file, each one process (decision 0032):

1. **Packet count** of the requested tracks that are not PGS: one ffprobe for all of them::

       ffprobe -v error -select_streams s -show_entries packet=stream_index,pts_time,size \\
           -of compact=p=0 -i <file>

   One packet is one event (an SRT / ASS line, a VobSub subpicture), as mkvmerge's
   ``NUMBER_OF_FRAMES`` statistics tag counts them. **MP4 / MOV text** (``mov_text``, the
   ``tx3g`` / ``text`` samples) is different: a sample is a 16-bit text length, the text and
   style boxes, and a text track has no gaps, so a muxer fills the time before the first cue
   and between two cues with an **empty sample** (length 0: 2 bytes). FFmpeg's MP4 / MOV
   muxer writes one for every gap (3 SRT cues with gaps: 6 samples of 2, 7, 2, 7, 2, 9 bytes);
   a cue without text (empty, or ASS override tags only) gets no sample of its own. So a
   ``mov_text`` packet of :data:`EMPTY_TEXT_SAMPLE` bytes or less is not an event (decision
   0032 §2; ``testdata/README.md``).
2. **PGS**: one ffmpeg copies every requested PGS track to a ``.sup`` file in a temporary
   folder under ``<cache dir>/scans`` (``-map 0:<index> -c copy -f sup``), and
   :func:`read_display_sets` reads the segment headers. The event count is the number of
   display sets (in Matroska, one block per display set: the same as the packet count and
   ``NUMBER_OF_FRAMES``; in M2TS every segment is a packet, so packets would count each event
   about four times). A display set is **forced** when its presentation composition has a
   composition object with the forced flag (``0x40``): the bit FFmpeg's PGS decoder checks.
   A decode with ``forced_subs_only`` **cannot** count them: FFmpeg's ``pgssubdec`` still
   returns every display set and only leaves the palette of a non-forced object empty
   (checked with ffprobe n9.0.2: the same subtitles with and without the option;
   ``testdata/README.md``). Every subtitle is two display sets (show, then clear), so the
   event count of a PGS track is about twice its number of subtitles, and the forced count
   counts the forced *show* display sets.
3. **VobSub** forced events: one ffprobe per track decodes it with the decoder option
   ``forced_subs_only``, which makes FFmpeg's ``dvdsubdec`` drop every subpicture that does not
   start with the forced command::

       ffprobe -v error -forced_subs_only 1 -select_streams <index> \\
           -show_entries subtitle=pts_time -of compact=p=0 -i <file>

   One line per forced event.

**Progress** is the packet time against the duration, the passes one after the other.
"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from reframe.analysis.common import (
    ProgressReporter,
    check_run,
    fields,
    number,
    stream_duration,
)
from reframe.mediatask import MediaTaskContext, TaskFailed, require_source, require_tool
from reframe.models.analysis import SubtitleScan, SubtitleScanTrack
from reframe.models.media import MediaSource, SubtitleStream
from reframe.models.tools import ToolInfo
from reframe.probe import roles
from reframe.queue.progress import ProgressParser
from reframe.tasks import TaskContext
from reframe.tools import CancelToken, run_streaming

__all__ = [
    "EMPTY_TEXT_SAMPLE",
    "FORCED_FLAG",
    "MOV_TEXT",
    "PGS",
    "VOBSUB",
    "DisplaySets",
    "SupError",
    "count_argv",
    "extract_argv",
    "forced_argv",
    "read_display_sets",
    "scan",
]

PGS = "hdmv_pgs_subtitle"
VOBSUB = "dvd_subtitle"
MOV_TEXT = "mov_text"
#: The size of an empty ``mov_text`` sample (the 16-bit text length 0, nothing else): the
#: filler that a muxer writes between two cues, not an event.
EMPTY_TEXT_SAMPLE = 2
#: Composition object flag of a forced object (``composition_flag & 0x40``).
FORCED_FLAG = 0x40
_SEGMENT_HEADER = 13
_PCS = 0x16
_END = 0x80
#: PCS bytes before the object count: width, height, frame rate, number, state, palette
#: update flag, palette id.
_PCS_FIXED = 10
_OBJECT = 8
_CROPPED = 0x80


class SupError(ValueError):
    """The ``.sup`` data is not a PGS segment stream."""


@dataclass(slots=True)
class DisplaySets:
    count: int = 0
    forced: int = 0


def _has_forced_object(pcs: bytes) -> bool:
    if len(pcs) <= _PCS_FIXED:
        return False
    objects = pcs[_PCS_FIXED]
    pos = _PCS_FIXED + 1
    for _ in range(objects):
        if pos + _OBJECT > len(pcs):
            break
        flags = pcs[pos + 3]
        if flags & FORCED_FLAG:
            return True
        pos += _OBJECT + (8 if flags & _CROPPED else 0)
    return False


def read_display_sets(stream: BinaryIO, *, cancel: CancelToken | None = None) -> DisplaySets:
    """Count the display sets of a ``.sup`` stream and those that show a forced object. Reads
    the segment headers and the presentation compositions only (the bitmaps are skipped)."""
    result = DisplaySets()
    forced = False
    segments = 0
    while True:
        header = stream.read(_SEGMENT_HEADER)
        if not header:
            break
        if len(header) < _SEGMENT_HEADER or header[:2] != b"PG":
            raise SupError(f"no PGS segment at byte {stream.tell() - len(header)}")
        kind = header[10]
        size = int.from_bytes(header[11:13], "big")
        if kind == _PCS:
            payload = stream.read(size)
            if len(payload) < size:
                raise SupError("the last segment is cut off")
            forced = _has_forced_object(payload)
        else:
            stream.seek(size, 1)
        if kind == _END:
            result.count += 1
            result.forced += forced
            forced = False
        segments += 1
        if cancel is not None and segments % 64 == 0 and cancel.cancelled:
            break
    return result


def count_argv(ffprobe: str, path: Path) -> list[str]:
    return [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "s",
        "-show_entries",
        "packet=stream_index,pts_time,size",
        "-of",
        "compact=p=0",
        "-i",
        str(path),
    ]


def forced_argv(ffprobe: str, path: Path, stream_index: int) -> list[str]:
    return [
        ffprobe,
        "-v",
        "error",
        "-forced_subs_only",
        "1",
        "-select_streams",
        str(stream_index),
        "-show_entries",
        "subtitle=pts_time",
        "-of",
        "compact=p=0",
        "-i",
        str(path),
    ]


def extract_argv(ffmpeg: str, path: Path, outputs: dict[int, Path]) -> list[str]:
    """Copy each PGS track ``index`` to the ``.sup`` file ``outputs[index]``."""
    argv = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-v", "error", "-nostats"]
    argv += ["-progress", "pipe:1", "-i", str(path)]
    for index, out in outputs.items():
        argv += ["-map", f"0:{index}", "-c", "copy", "-f", "sup", str(out)]
    return argv


def _read_file(path: Path, cancel: CancelToken) -> DisplaySets:
    with path.open("rb") as stream:
        return read_display_sets(stream, cancel=cancel)


def _with_counts(source: MediaSource, tracks: Sequence[SubtitleScanTrack]) -> MediaSource:
    updated = source.model_copy(deep=True)
    by_index = {t.stream_index: t for t in tracks}
    for stream in updated.subtitles:
        track = by_index.get(stream.index)
        if track is None or track.event_count is None:
            continue
        stream.event_count = track.event_count
        stream.event_count_source = "measured"
        stream.forced_event_count = track.forced_event_count
    roles.assign_subtitle_roles(updated.subtitles)  # the forced heuristic uses event counts
    return updated


def _requested(
    source: MediaSource, path: Path, stream_indexes: Sequence[int] | None
) -> list[SubtitleStream]:
    if stream_indexes is None:
        return list(source.subtitles)
    by_index = {s.index: s for s in source.subtitles}
    others = {s.index for s in (*source.video, *source.audio)}
    picked: list[SubtitleStream] = []
    for index in dict.fromkeys(stream_indexes):
        stream = by_index.get(index)
        if stream is None:
            what = "is not a subtitle stream" if index in others else "does not exist"
            raise TaskFailed(f"Stream {index} of {path.name} {what}.")
        picked.append(stream)
    return picked


class _Progress:
    """Progress over the passes of one scan: each pass is an equal share; within a pass, the
    packet time against the file's duration."""

    def __init__(self, task: TaskContext, passes: int, duration: float | None) -> None:
        self._task = task
        self._reporter = ProgressReporter(task.progress)
        self._passes = max(passes, 1)
        self._duration = duration
        self.done = 0

    def begin(self, message: str) -> None:
        """A new pass: its message, at the percent of the passes done so far."""
        self._task.progress(100.0 * self.done / self._passes, message)

    def update(self, seconds: float | None, message: str) -> None:
        share = 0.0
        if seconds is not None and self._duration:
            share = min(max(seconds / self._duration, 0.0), 1.0)
        self._reporter.update(100.0 * (self.done + share) / self._passes, message)


def _is_event(values: dict[str, str], *, text_samples: bool) -> bool:
    """A packet line of :func:`count_argv` is an event; for a ``mov_text`` track
    (``text_samples``) not when it is an empty sample (see the module doc)."""
    if not text_samples:
        return True
    size = number(values.get("size"))
    return size is None or size > EMPTY_TEXT_SAMPLE


async def _count_packets(
    ffprobe: ToolInfo,
    path: Path,
    tracks: Sequence[SubtitleStream],
    task: TaskContext,
    progress: _Progress,
) -> dict[int, int]:
    counts = dict.fromkeys((t.index for t in tracks), 0)
    text_samples = {t.index for t in tracks if t.codec == MOV_TEXT}
    message = "Counting subtitle events"
    progress.begin(message)

    def on_packet(line: str) -> None:
        values = fields(line)
        index = number(values.get("stream_index"))
        if index is None or int(index) not in counts:
            return
        if _is_event(values, text_samples=int(index) in text_samples):
            counts[int(index)] += 1
        progress.update(number(values.get("pts_time")), message)

    assert ffprobe.path is not None
    result = await run_streaming(
        count_argv(str(ffprobe.path), path), on_stdout_line=on_packet, on_stderr_line=None,
        cancel=task.cancel, extra_env=ffprobe.env or None,
    )  # fmt: skip
    check_run(result, "ffprobe", path)
    return counts


async def _read_in_thread(out: Path, cancel: CancelToken) -> DisplaySets:
    """:func:`read_display_sets` in a worker thread. On a cancel, wait for the thread (the
    token stops it within a few segments), so the file is closed before it is removed."""
    reader = asyncio.ensure_future(asyncio.to_thread(_read_file, out, cancel))
    try:
        return await asyncio.shield(reader)
    except asyncio.CancelledError:
        with contextlib.suppress(Exception):
            await reader
        raise


async def _read_pgs(
    ctx: MediaTaskContext,
    ffmpeg: ToolInfo,
    path: Path,
    indexes: Sequence[int],
    task: TaskContext,
    progress: _Progress,
) -> dict[int, DisplaySets]:
    scans = ctx.cache_dir / "scans"
    scans.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="subtitles-", dir=scans))
    found: dict[int, DisplaySets] = {}
    try:
        outputs = {index: folder / f"{index}.sup" for index in indexes}
        message = "Reading the PGS tracks"
        progress.begin(message)
        parser = ProgressParser()

        def on_progress(line: str) -> None:
            block = parser.feed(line)
            if block is not None:
                progress.update(block.out_time, message)

        assert ffmpeg.path is not None
        result = await run_streaming(
            extract_argv(str(ffmpeg.path), path, outputs), on_stdout_line=on_progress,
            on_stderr_line=None, cancel=task.cancel, extra_env=ffmpeg.env or None,
        )  # fmt: skip
        check_run(result, "ffmpeg", path)
        for index, out in outputs.items():
            try:
                found[index] = await _read_in_thread(out, task.cancel)
            except (OSError, SupError) as exc:
                raise TaskFailed(f"PGS track {index} could not be read: {exc}") from exc
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return found


async def _count_forced(
    ffprobe: ToolInfo, path: Path, index: int, task: TaskContext, progress: _Progress
) -> int:
    message = f"Looking for forced subtitles in track {index}"
    progress.begin(message)
    forced = 0

    def on_subtitle(line: str) -> None:
        nonlocal forced
        values = fields(line)
        if "pts_time" not in values:
            return
        forced += 1
        progress.update(number(values.get("pts_time")), message)

    assert ffprobe.path is not None
    result = await run_streaming(
        forced_argv(str(ffprobe.path), path, index), on_stdout_line=on_subtitle,
        on_stderr_line=None, cancel=task.cancel, extra_env=ffprobe.env or None,
    )  # fmt: skip
    check_run(result, "ffprobe", path)
    return forced


async def scan(
    ctx: MediaTaskContext, path: Path, stream_indexes: Sequence[int] | None, task: TaskContext
) -> SubtitleScan:
    """The body of the ``subtitle_scan`` task."""
    task.progress(None, "Waiting for the probe")
    ffprobe = await require_tool(ctx, "ffprobe")
    source = await require_source(ctx, path, cancel=task.cancel)
    tracks = _requested(source, path, stream_indexes)
    if not tracks:
        return SubtitleScan(path=path)
    pgs = [t.index for t in tracks if t.codec == PGS]
    others = [t for t in tracks if t.codec != PGS]
    vobsub = [t.index for t in tracks if t.codec == VOBSUB]
    ffmpeg = await require_tool(ctx, "ffmpeg") if pgs else None
    progress = _Progress(
        task, bool(others) + bool(pgs) + len(vobsub), stream_duration(source, None)
    )
    counts: dict[int, int] = {}
    sets: dict[int, DisplaySets] = {}
    forced: dict[int, int] = {}
    if others:
        counts = await _count_packets(ffprobe, path, others, task, progress)
        progress.done += 1
    if pgs:
        assert ffmpeg is not None
        sets = await _read_pgs(ctx, ffmpeg, path, pgs, task, progress)
        progress.done += 1
    for index in vobsub:
        forced[index] = await _count_forced(ffprobe, path, index, task, progress)
        progress.done += 1

    scanned: list[SubtitleScanTrack] = []
    for track in tracks:
        if track.index in sets:
            found = sets[track.index]
            event_count: int | None = found.count
            forced_count: int | None = found.forced
        else:
            event_count = counts.get(track.index)
            forced_count = forced.get(track.index)
        scanned.append(
            SubtitleScanTrack(
                stream_index=track.index, event_count=event_count, forced_event_count=forced_count
            )
        )
    # Onto the source as it is known now: another scan of the file may have stored its
    # values since this one probed it.
    await ctx.sources.update(source, lambda latest: _with_counts(latest, scanned))
    return SubtitleScan(path=path, tracks=scanned)
