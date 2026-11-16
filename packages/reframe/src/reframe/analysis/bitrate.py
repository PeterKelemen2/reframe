"""The bit rate of one stream: its packet sizes over the time that the packets cover. One
ffprobe run, read line by line, so a long file is never one JSON document in memory. Why the
covered time is measured this way (decode order, Matroska's rounded durations): see
``testdata/README.md``, "Analysis scans".
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from reframe.analysis.common import (
    ProgressReporter,
    fields,
    find_stream,
    number,
    run_scan,
    stream_duration,
)
from reframe.mediatask import MediaTaskContext, TaskFailed, require_source, require_tool
from reframe.models.analysis import BitrateScan
from reframe.models.media import (
    AudioStream,
    BitrateInfo,
    BitrateSource,
    MediaSource,
    VideoStream,
)
from reframe.probe import roles
from reframe.tasks import TaskContext

__all__ = ["Packet", "PacketStats", "parse_packet", "scan", "scan_argv"]


@dataclass(frozen=True, slots=True)
class Packet:
    time: float | None
    """``pts_time``, else ``dts_time`` (seconds)."""
    duration: float | None
    size: int | None


def parse_packet(line: str) -> Packet | None:
    """One line of :func:`scan_argv`'s output, or ``None`` for a line that is not a packet."""
    values = fields(line)
    if "size" not in values:
        return None
    time = number(values.get("pts_time"))
    if time is None:
        time = number(values.get("dts_time"))
    size = number(values.get("size"))
    duration = number(values.get("duration_time"))
    return Packet(
        time=time,
        duration=duration if duration is not None and duration >= 0 else None,
        size=int(size) if size is not None and size >= 0 else None,
    )


@dataclass(slots=True)
class PacketStats:
    """Running totals of a packet listing (constant memory)."""

    packets: int = 0
    bytes: int = 0
    timed: int = 0
    """Packets with a time."""
    first: float | None = None
    last: float | None = None
    end: float | None = None
    """Latest time + duration of a packet that has a duration."""

    def add(self, packet: Packet) -> None:
        if packet.size is None:
            return
        self.packets += 1
        self.bytes += packet.size
        t = packet.time
        if t is None:
            return
        self.timed += 1
        self.first = t if self.first is None else min(self.first, t)
        self.last = t if self.last is None else max(self.last, t)
        if packet.duration is not None:
            stop = t + packet.duration
            self.end = stop if self.end is None else max(self.end, stop)

    def covered(self, fallback: float | None = None) -> float | None:
        """Seconds that the packets cover, else ``fallback``."""
        if self.first is not None and self.last is not None:
            if self.end is not None and self.end > self.first:
                return max(self.end, self.last) - self.first
            if self.timed >= 2 and self.last > self.first:
                span = self.last - self.first
                return span + span / (self.timed - 1)
        if fallback is not None and fallback > 0:
            return fallback
        return None

    def bitrate(self, fallback: float | None = None) -> int | None:
        """Bits per second; ``None`` without packets, bytes or a covered time, or when the rate
        rounds to 0."""
        seconds = self.covered(fallback)
        if not self.bytes or seconds is None or seconds <= 0:
            return None
        return round(self.bytes * 8 / seconds) or None


def scan_argv(ffprobe: str, path: Path, stream_index: int) -> list[str]:
    return [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        str(stream_index),
        "-show_entries",
        "packet=pts_time,dts_time,duration_time,size",
        "-of",
        "compact=p=0",
        "-i",
        str(path),
    ]


def _with_bitrate(source: MediaSource, stream_index: int, bitrate: BitrateInfo) -> MediaSource:
    updated = source.model_copy(deep=True)
    for stream in updated.video:
        if stream.index == stream_index:
            stream.bitrate = bitrate
    for track in updated.audio:
        if track.index == stream_index:
            track.bitrate = bitrate
    roles.assign_audio_roles(updated.audio)  # the commentary heuristic uses bit rates
    return updated


async def scan(
    ctx: MediaTaskContext, path: Path, stream_index: int, task: TaskContext
) -> BitrateScan:
    """The body of the ``bitrate_scan`` task."""
    task.progress(None, "Waiting for the probe")
    ffprobe = await require_tool(ctx, "ffprobe")
    source = await require_source(ctx, path, cancel=task.cancel)
    stream = find_stream(source, stream_index)
    if stream is None:
        raise TaskFailed(f"{path.name} has no stream {stream_index}.")
    if not isinstance(stream, (AudioStream, VideoStream)):
        raise TaskFailed(
            f"Stream {stream_index} of {path.name} is a {stream.kind} stream; only audio and "
            "video streams have a bit rate to measure."
        )
    duration = stream_duration(source, stream)
    stats = PacketStats()
    message = f"Reading the packets of stream {stream_index}"
    reporter = ProgressReporter(task.progress)
    task.progress(0.0, message)

    def on_line(line: str) -> None:
        packet = parse_packet(line)
        if packet is None:
            return
        stats.add(packet)
        if duration and packet.time is not None and stats.first is not None:
            reporter.update(100.0 * (packet.time - stats.first) / duration, message)

    await run_scan(
        ffprobe, lambda program: scan_argv(program, path, stream_index), path, task, on_line
    )
    value = stats.bitrate(duration)
    bitrate = (
        BitrateInfo(value=value, source=BitrateSource.MEASURED)
        if value is not None
        else BitrateInfo()
    )
    if value is not None:
        # Onto the source as it is known now: another scan of the file may have stored its
        # values since this one probed it.
        await ctx.sources.update(
            source, lambda latest: _with_bitrate(latest, stream_index, bitrate)
        )
    return BitrateScan(
        path=path,
        stream_index=stream_index,
        bitrate=bitrate,
        packets=stats.packets,
        bytes=stats.bytes,
        duration=stats.covered(duration),
    )
