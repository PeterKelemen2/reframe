"""Bit rates estimated from a sample of a Matroska file's clusters, for the video and audio
streams that ffprobe and the statistics tags give no rate.

Every read is bounded: :data:`WINDOW` bytes to find a cluster, at most :data:`MAX_CLUSTER` bytes
per cluster, :data:`MAX_SAMPLE_READ` bytes in all and the reader's ``MAX_ELEMENTS`` per cluster.
A cluster that does not parse cleanly is not used; a file without a usable cluster gives no
sample.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from reframe.models.media import (
    AudioStream,
    BitrateInfo,
    BitrateSource,
    MediaSource,
    SubtitleStream,
    VideoStream,
)
from reframe.probe import matroska
from reframe.probe.matroska import (
    _CLUSTER,
    _CRC32,
    _VOID,
    MatroskaError,
    MatroskaFile,
    TrackKind,
    read_exactly,
)

__all__ = [
    "MAX_CLUSTER",
    "MAX_SAMPLE_READ",
    "MAX_SPAN",
    "SAMPLES",
    "WINDOW",
    "ClusterSample",
    "estimate_bitrates",
    "sample_clusters",
]

#: Clusters sampled, at evenly spaced offsets from 2 % to 98 % of the file.
SAMPLES = 32
#: Bytes read at each offset to find the next cluster.
WINDOW = 256 * 1024
#: A larger cluster is not read.
MAX_CLUSTER = 64 * 1024 * 1024
#: Bytes one sample reads in all; when they run out, the clusters read so far are the sample.
MAX_SAMPLE_READ = 256 * 1024 * 1024
#: Seconds one cluster may cover; a longer span means the next cluster's timestamp is not the
#: end of this one.
MAX_SPAN = 60.0

_FIRST = 0.02
_LAST = 0.98
_CLUSTER_MAGIC = b"\x1f\x43\xb6\x75"
_TIMESTAMP = 0xE7
_SIMPLE_BLOCK = 0xA3
_BLOCK_GROUP = 0xA0
_BLOCK = 0xA1
#: Enough for a cluster's header and its first children up to the Timestamp.
_CLUSTER_HEAD = 64


@dataclass(frozen=True, slots=True)
class ClusterSample:
    """What the sampled clusters hold."""

    clusters: int
    seconds: float
    """The time the sampled clusters cover."""
    track_bytes: dict[int, int] = field(default_factory=dict)
    """Block payload bytes by track number."""
    complete: bool = False
    """Every cluster of the file was read, so the bytes are exact."""


class _Stop(Exception):
    """Stop sampling: asked to, or the read budget is spent."""


class _File:
    def __init__(self, handle: BinaryIO, size: int, stop: Callable[[], bool]) -> None:
        self.handle = handle
        self.size = size
        self.stop = stop
        self.left = MAX_SAMPLE_READ
        self.window_pos = 0
        self.window = b""

    def read(self, pos: int, count: int) -> bytes:
        if pos < 0 or count <= 0 or pos >= self.size:
            return b""
        count = min(count, self.size - pos)
        start = pos - self.window_pos
        if start >= 0 and start + count <= len(self.window):
            return self.window[start : start + count]
        if self.stop() or count > self.left:
            raise _Stop
        self.left -= count
        return read_exactly(self.handle, pos, count)

    def load_window(self, pos: int) -> bytes:
        self.window = b""
        data = self.read(pos, WINDOW)
        self.window_pos, self.window = pos, data
        return data


@dataclass(slots=True)
class _Cluster:
    end: int
    timestamp: int
    track_bytes: dict[int, int]


def _add_block(payload: bytes, out: dict[int, int]) -> None:
    track, length, _ = matroska._vint(payload, 0, keep_marker=False)
    if len(payload) < length + 3:
        raise MatroskaError("truncated block header")
    out[track] = out.get(track, 0) + len(payload) - length - 3


def _blocks(data: bytes) -> tuple[int, dict[int, int]]:
    """The cluster's Timestamp and block bytes per track. :raises MatroskaError: damaged."""
    budget = matroska._Budget()
    timestamp: int | None = None
    out: dict[int, int] = {}
    pos = 0
    while pos < len(data):
        budget.element()
        element_id, size, header = matroska._header(data, pos)
        start = pos + header
        if size is None or start + size > len(data):
            raise MatroskaError("a cluster child overruns the cluster")
        end = start + size
        if element_id == _TIMESTAMP:
            if timestamp is not None or size > 8:
                raise MatroskaError("a second or oversized cluster Timestamp")
            timestamp = matroska._uint(data[start:end])
        elif element_id in (_CRC32, _VOID):
            pass
        elif timestamp is None:
            raise MatroskaError("a cluster child before the Timestamp")
        elif element_id == _SIMPLE_BLOCK:
            _add_block(data[start:end], out)
        elif element_id == _BLOCK_GROUP:
            group = data[start:end]
            inner = 0
            while inner < len(group):
                budget.element()
                child_id, child_size, child_header = matroska._header(group, inner)
                child_start = inner + child_header
                if child_size is None or child_start + child_size > len(group):
                    raise MatroskaError("a BlockGroup child overruns the group")
                if child_id == _BLOCK:
                    _add_block(group[child_start : child_start + child_size], out)
                inner = child_start + child_size
        pos = end
    if timestamp is None:
        raise MatroskaError("a cluster without a Timestamp")
    return timestamp, out


class _Sampler:
    def __init__(self, file: _File, limit: int, info: MatroskaFile) -> None:
        self.file = file
        self.limit = limit
        self.scale = info.timestamp_scale
        self.duration = info.duration
        self.tried: set[int] = set()
        self.clusters = 0
        self.seconds = 0.0
        self.track_bytes: dict[int, int] = {}
        self.complete = False

    def cluster(self, pos: int) -> _Cluster | None:
        """The sized cluster at ``pos`` if it parses cleanly."""
        try:
            element_id, size, header = matroska._header(self.file.read(pos, 12), 0)
            if element_id != _CLUSTER or size is None or size > MAX_CLUSTER:
                return None
            end = pos + header + size
            if end > self.limit:
                return None
            data = self.file.read(pos + header, size)
            if len(data) != size:
                return None
            timestamp, track_bytes = _blocks(data)
        except MatroskaError:
            return None
        return _Cluster(end, timestamp, track_bytes)

    def next_cluster(self, pos: int) -> tuple[bool, int | None]:
        """``(a cluster starts at pos, its Timestamp)``; the Timestamp is ``None`` when it
        cannot be read from the cluster's first bytes."""
        if pos >= self.limit:
            return False, None
        head = self.file.read(pos, _CLUSTER_HEAD)
        try:
            element_id, _, at = matroska._header(head, 0)
            if element_id != _CLUSTER:
                return False, None
            while at < len(head):
                child_id, size, header = matroska._header(head, at)
                if size is None:
                    break
                if child_id == _TIMESTAMP:
                    data = head[at + header : at + header + size]
                    return True, matroska._uint(data) if size <= 8 and len(data) == size else None
                if child_id not in (_CRC32, _VOID):
                    break
                at += header + size
        except MatroskaError:
            pass
        return True, None

    def span(self, cluster: _Cluster) -> tuple[float | None, int | None]:
        """``(seconds the cluster covers, the position of the next cluster)``. Other top-level
        elements between two clusters are skipped; the last cluster ends at the segment's
        ``Duration``."""
        after = cluster.end
        follows, timestamp = self.next_cluster(after)
        if not follows:
            later = self.first_cluster(after)
            if later is not None:
                after = later
                follows, timestamp = self.next_cluster(later)
        if follows:
            if timestamp is None:
                return None, after
            seconds = (timestamp - cluster.timestamp) * self.scale / 1e9
        elif self.duration is not None:
            seconds = self.duration - cluster.timestamp * self.scale / 1e9
        else:
            return None, None
        return (seconds if 0 < seconds <= MAX_SPAN else None), after if follows else None

    def add(self, cluster: _Cluster, seconds: float) -> None:
        self.clusters += 1
        self.seconds += seconds
        for track, count in cluster.track_bytes.items():
            self.track_bytes[track] = self.track_bytes.get(track, 0) + count

    def from_window(self, offset: int) -> None:
        """Sample the first usable cluster that starts in the window at ``offset``."""
        window = self.file.load_window(offset)
        at = window.find(_CLUSTER_MAGIC)
        while at != -1:
            pos = offset + at
            if pos not in self.tried:
                self.tried.add(pos)
                cluster = self.cluster(pos)
                seconds = self.span(cluster)[0] if cluster is not None else None
                if cluster is not None and seconds is not None:
                    self.add(cluster, seconds)
                    return
            at = window.find(_CLUSTER_MAGIC, at + 1)

    def first_cluster(self, pos: int) -> int | None:
        for _ in range(matroska.MAX_TOP_LEVEL):
            if pos >= self.limit:
                return None
            try:
                element_id, size, header = matroska._header(self.file.read(pos, 12), 0)
            except MatroskaError:
                return None
            if element_id == _CLUSTER:
                return pos
            if size is None:
                return None
            pos += header + size
        return None

    def walk(self, segment: int, count: int | None) -> None:
        """Sample up to ``count`` clusters (``None``: all) in a row from the first one."""
        pos = self.first_cluster(segment)
        while pos is not None and (count is None or self.clusters < count):
            cluster = self.cluster(pos)
            if cluster is None:
                return
            seconds, pos = self.span(cluster)
            if seconds is None:
                return
            self.add(cluster, seconds)
            if pos is None:
                self.complete = True

    def result(self) -> ClusterSample | None:
        if not self.clusters or self.seconds <= 0:
            return None
        return ClusterSample(self.clusters, self.seconds, self.track_bytes, self.complete)


def _never() -> bool:
    return False


def sample_clusters(
    path: str | os.PathLike[str],
    info: MatroskaFile,
    *,
    stop: Callable[[], bool] = _never,
) -> ClusterSample | None:
    """Read :data:`SAMPLES` clusters at evenly spaced offsets of the file (blocking). A segment no
    larger than the windows together is read whole instead, and when no offset finds a cluster
    (a file of few large clusters), the clusters from the first one on are read in a row.
    ``None`` when no cluster could be used. ``stop`` is checked before each read; when it
    returns true, the clusters read so far are the sample.

    :raises OSError: the file cannot be read.
    """
    if info.timestamp_scale <= 0:
        return None
    # Unbuffered: a network share's large block size would make every small read after a
    # seek fetch a whole buffer.
    with open(Path(path), "rb", buffering=0) as handle:
        size = os.fstat(handle.fileno()).st_size
        limit = size if info.segment_size is None else min(size, info.segment + info.segment_size)
        file = _File(handle, size, stop)
        sampler = _Sampler(file, limit, info)
        try:
            if limit - info.segment <= SAMPLES * WINDOW:
                sampler.walk(info.segment, None)
                if sampler.complete:
                    return sampler.result()
                sampler = _Sampler(file, limit, info)
            for k in range(SAMPLES):
                fraction = _FIRST + (_LAST - _FIRST) * k / max(SAMPLES - 1, 1)
                sampler.from_window(int(size * fraction))
            if not sampler.clusters:
                sampler.walk(info.segment, SAMPLES)
        except _Stop:
            pass
    return sampler.result()


Rated = VideoStream | AudioStream


def estimate_bitrates(source: MediaSource, info: MatroskaFile, sample: ClusterSample) -> list[int]:
    """Give each video and audio stream without a bit rate an ``estimated`` one, and return
    their indexes.

    Audio gets its bytes per sampled second. A single video stream without a rate gets the
    rate of the file's bytes outside ``info.other_bytes`` (attachments, cues, tags…) minus
    every other stream's, which does not depend on how evenly its bits are spread; with more
    than one, or when the sample holds every cluster, each gets its bytes per sampled second.
    The n-th track of a kind is the n-th stream of that kind; when the counts differ, nothing
    is estimated.
    """
    kinds = matroska.tracks_by_kind(info)
    streams: list[tuple[list[VideoStream] | list[AudioStream] | list[SubtitleStream], TrackKind]]
    streams = [(source.video, "video"), (source.audio, "audio"), (source.subtitles, "subtitle")]
    if any(len(found) != len(kinds[kind]) for found, kind in streams):
        return []
    number: dict[int, int | None] = {}
    for found, kind in streams:
        for stream, track in zip(found, kinds[kind], strict=True):
            number[stream.index] = track.number

    def sampled(track: int | None) -> float | None:
        count = sample.track_bytes.get(track, 0) if track is not None else 0
        return count * 8 / sample.seconds if count else None

    def give(stream: Rated, value: float | None) -> None:
        if value is not None and value >= 1:
            stream.bitrate = BitrateInfo(
                value=round(value), source=BitrateSource.ESTIMATED, samples=sample.clusters
            )
            estimated.append(stream.index)

    estimated: list[int] = []
    for audio in source.audio:
        if audio.bitrate.source is BitrateSource.UNKNOWN:
            give(audio, sampled(number[audio.index]))
    unknown = [v for v in source.video if v.bitrate.source is BitrateSource.UNKNOWN]
    file_rate = _file_rate(source, info)
    if len(unknown) == 1 and not sample.complete and file_rate is not None:
        target = unknown[0]
        others = 0.0
        rated: list[Rated] = [*source.video, *source.audio]
        for stream in rated:
            if stream is not target:
                others += stream.bitrate.value or sampled(number[stream.index]) or 0
        mapped = {number[s.index] for s in rated}
        for track in info.tracks:
            if track.number not in mapped:
                others += sampled(track.number) or 0
        rest = file_rate - others
        give(target, rest if rest > 0 else sampled(number[target.index]))
    else:
        for video in unknown:
            give(video, sampled(number[video.index]))
    return estimated


def _file_rate(source: MediaSource, info: MatroskaFile) -> float | None:
    container = source.container
    if not container.duration:
        return container.bitrate or None
    rate = container.bitrate or (container.size or 0) * 8 / container.duration
    rate -= info.other_bytes * 8 / container.duration
    return rate if rate > 0 else None
