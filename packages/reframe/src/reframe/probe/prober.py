"""Probing one file: ffprobe, the HDR frame fallback, the Matroska track headers, the sampled
bit rates, the VFR check and the cache.

:class:`Prober` holds the configuration. :func:`probe_file` is the one-call form.

Cancelling (the token or the calling task) stops the probe at once: ffprobe is killed by
``reframe.tools.run``, and a worker thread (``stat``, the Matroska reader, the cluster sample) is
left to finish on its own while the probe returns ``ProbeErrorKind.CANCELLED``; the sample stops
at its next read.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import threading
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from stat import S_ISREG
from typing import Any

from pydantic import TypeAdapter, ValidationError

from reframe.models.base import LanguageTag
from reframe.models.media import (
    AudioStream,
    BitrateSource,
    MediaSource,
    SourceFingerprint,
    SubtitleStream,
    VideoStream,
)
from reframe.models.text import replace_undecodable
from reframe.models.tools import ToolInfo
from reframe.platform.longpath import missing_text
from reframe.probe import matroska, roles, sampling
from reframe.probe.cache import CacheKey, ProbeCache
from reframe.probe.ffprobe import (
    FRAME_PACKETS,
    FRAME_TIMEOUT,
    PROBE_TIMEOUT,
    ProbeError,
    ProbeErrorKind,
    ProbeTool,
    frames_argv,
    packets_argv,
    probe_argv,
    run_json,
)
from reframe.probe.hdr import needs_frame_side_data
from reframe.probe.parse import (
    main_video_stream,
    parse_ffprobe,
    vfr_from_timestamps,
    vfr_undecided,
    video_bit_depth,
)
from reframe.tools import CancelToken

log = logging.getLogger(__name__)

__all__ = [
    "MATROSKA_READER",
    "MATROSKA_TIMEOUT",
    "SAMPLE_TIMEOUT",
    "ProbeOutcome",
    "Prober",
    "apply_matroska",
    "probe_file",
]

#: Seconds to wait for the Matroska track reader (a slow network share).
MATROSKA_TIMEOUT = 30.0
#: Seconds the cluster sample may take; after that the bit rates stay unknown.
SAMPLE_TIMEOUT = 30.0
#: Bump when the Matroska reader or the sample changes what they add: the probe cache is keyed
#: on this number.
MATROSKA_READER = 3

#: The shape of a ``language_ietf`` value (the model's own type; assignment does not check it).
_LANGUAGE_TAG: TypeAdapter[str] = TypeAdapter(LanguageTag)

#: The result of probing one file.
ProbeOutcome = MediaSource | ProbeError


class _Cancelled:
    """Returned by :func:`_race` when the token was cancelled first."""


_CANCELLED = _Cancelled()


async def _race[T](
    work: Awaitable[T],
    cancel: CancelToken | None,
    timeout: float | None = None,  # noqa: ASYNC109
) -> T | _Cancelled:
    """Await ``work`` unless ``cancel`` fires first. ``work`` is not cancelled (it may be a
    worker thread or shared with other callers). :raises TimeoutError: after ``timeout``."""
    future = asyncio.ensure_future(work)
    if cancel is not None and cancel.cancelled:
        return _CANCELLED
    watch: set[asyncio.Future[Any]] = {future}
    cancel_waiter = asyncio.ensure_future(cancel.wait()) if cancel is not None else None
    if cancel_waiter is not None:
        watch.add(cancel_waiter)
    try:
        done, _ = await asyncio.wait(watch, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
    finally:
        if cancel_waiter is not None:
            cancel_waiter.cancel()
    if future in done:
        return future.result()
    if cancel_waiter is not None and cancel_waiter in done:
        return _CANCELLED
    raise TimeoutError


def _cancelled(path: Path) -> ProbeError:
    return ProbeError(path, ProbeErrorKind.CANCELLED, "The probe was cancelled.")


@dataclass
class _Flight:
    """One running probe of a file version, shared by every caller that asks for it."""

    task: asyncio.Task[ProbeOutcome]
    token: CancelToken
    waiters: int = 0


class Prober:
    """Probes files with one ffprobe, one cache and one set of options."""

    def __init__(
        self,
        ffprobe: ToolInfo | ProbeTool | str | os.PathLike[str],
        *,
        cache: ProbeCache | None = None,
        timeout: float = PROBE_TIMEOUT,
        frame_timeout: float = FRAME_TIMEOUT,
    ) -> None:
        self.tool = ProbeTool.of(ffprobe)
        self.cache = cache
        self.timeout = timeout
        self.frame_timeout = frame_timeout
        self._flights: dict[tuple[CacheKey, bool], _Flight] = {}

    def cache_options(self) -> dict[str, Any]:
        """The options that change a probe result (part of the cache entry)."""
        return {"matroska": MATROSKA_READER}

    async def probe(
        self,
        path: str | os.PathLike[str],
        *,
        cancel: CancelToken | None = None,
        use_cache: bool = True,
    ) -> ProbeOutcome:
        """Probe ``path``. Never raises for problems with the file or the tool."""
        if cancel is not None and cancel.cancelled:
            return _cancelled(Path(path))
        identity = self.tool.identity()
        options = self.cache_options()
        prepared = await _race(
            asyncio.to_thread(self._prepare, path, identity, options, use_cache), cancel
        )
        if isinstance(prepared, _Cancelled):
            return _cancelled(Path(path))
        if isinstance(prepared, (ProbeError, MediaSource)):
            return prepared
        file, stat, key = prepared

        flight_key = (key, use_cache)
        flight = self._flights.get(flight_key)
        if flight is None:
            token = CancelToken()
            task = asyncio.create_task(
                self._probe_file(file, stat, key, identity, options, token),
                name=f"reframe-probe-{file.name}",
            )
            flight = _Flight(task, token)
            self._flights[flight_key] = flight
            landed = flight

            def land(_task: asyncio.Task[ProbeOutcome]) -> None:
                self._land(flight_key, landed)

            task.add_done_callback(land)
        flight.waiters += 1
        try:
            outcome = await _race(asyncio.shield(flight.task), cancel)
        finally:
            flight.waiters -= 1
            if flight.waiters == 0 and not flight.task.done():
                # Nobody waits any more: stop the shared run, and do not return before its
                # ffprobe is gone (a TaskGroup caller relies on that).
                self._land(flight_key, flight)
                flight.token.cancel("no caller waits for this probe")
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await asyncio.shield(flight.task)
        if isinstance(outcome, _Cancelled):
            return _cancelled(file)
        if isinstance(outcome, MediaSource):
            return outcome.model_copy(deep=True)  # callers of one flight get their own copy
        return outcome

    def _land(self, flight_key: tuple[CacheKey, bool], flight: _Flight) -> None:
        if self._flights.get(flight_key) is flight:
            del self._flights[flight_key]

    def _prepare(
        self,
        path: str | os.PathLike[str],
        identity: str,
        options: dict[str, Any],
        use_cache: bool,
    ) -> tuple[Path, os.stat_result, CacheKey] | ProbeError | MediaSource:
        """Check the file and look it up in the cache (blocking)."""
        file = Path(os.path.abspath(path))
        try:
            stat = os.stat(file)
        except FileNotFoundError:
            message = missing_text(file, "The file does not exist.")
            return ProbeError(file, ProbeErrorKind.NOT_FOUND, message)
        except OSError as exc:
            return ProbeError(file, ProbeErrorKind.UNREADABLE, "The file cannot be read.", str(exc))
        if not S_ISREG(stat.st_mode):
            return ProbeError(file, ProbeErrorKind.NOT_A_FILE, "The path is not a file.")
        key = CacheKey.for_file(file, stat)
        if self.cache is not None and use_cache:
            cached = self.cache.get(key, tool=identity, options=options)
            if cached is not None:
                return cached
        return file, stat, key

    async def _probe_file(
        self,
        file: Path,
        stat: os.stat_result,
        key: CacheKey,
        identity: str,
        options: dict[str, Any],
        cancel: CancelToken,
    ) -> ProbeOutcome:
        data = await run_json(
            probe_argv(self.tool.path, str(file)),
            file,
            tool=self.tool,
            timeout=self.timeout,
            cancel=cancel,
        )
        if isinstance(data, ProbeError):
            return data

        warnings: list[str] = []
        frames = await self._first_frames(data, file, cancel, warnings)
        if isinstance(frames, ProbeError):
            return frames  # cancelled
        tracks: matroska.MatroskaFile | None = None
        if _is_matroska(data):
            read = await _read_matroska(file, cancel)
            if isinstance(read, _Cancelled):
                return _cancelled(file)
            tracks = read
        fingerprint = SourceFingerprint(size=stat.st_size, mtime=stat.st_mtime)
        try:
            source = parse_ffprobe(
                data,
                file,
                frames=frames,
                fingerprint=fingerprint,
                probe_tool=self.tool.version,
                probed_at=datetime.now(UTC),
                warnings=warnings,
                matroska=tracks,
            )
        except (ValidationError, ValueError, TypeError) as exc:
            return ProbeError(
                file,
                ProbeErrorKind.INVALID_OUTPUT,
                "ffprobe's output could not be understood.",
                str(exc),
            )
        undecided = set(vfr_undecided(data, matroska=tracks))
        if tracks is not None:
            apply_matroska(source, tracks)
            if _needs_rates(source):
                sample = await _sample(file, tracks, cancel)
                if isinstance(sample, _Cancelled):
                    return _cancelled(file)
                if sample is not None and sampling.estimate_bitrates(source, tracks, sample):
                    roles.assign_audio_roles(source.audio)  # the commentary heuristic uses rates
        for stream in source.video:
            if stream.index in undecided:
                vfr = await self._vfr_from_packets(file, stream.index, cancel, source.warnings)
                if isinstance(vfr, ProbeError):
                    return vfr  # cancelled
                stream.vfr = bool(vfr)
        # Warnings added after validation can quote the path: show it as the cached copy does.
        source.warnings = [replace_undecodable(text) for text in source.warnings]
        if self.cache is not None:
            await asyncio.to_thread(self.cache.put, key, source, tool=identity, options=options)
        return source

    async def _first_frames(
        self,
        data: dict[str, Any],
        file: Path,
        cancel: CancelToken,
        warnings: list[str],
    ) -> dict[str, Any] | ProbeError | None:
        main = main_video_stream(data)
        if main is None:
            return None
        index, stream = main
        if not needs_frame_side_data(stream, video_bit_depth(stream)):
            return None
        frames = await run_json(
            frames_argv(self.tool.path, str(file), index),
            file,
            tool=self.tool,
            timeout=self.frame_timeout,
            cancel=cancel,
            what="reading the first frames",
        )
        if isinstance(frames, ProbeError):
            if frames.kind is ProbeErrorKind.CANCELLED:
                return frames
            warnings.append(
                f"The HDR side data of the first frames could not be read: {frames.message}"
                + (f" ({frames.detail})" if frames.detail else "")
            )
            return None
        if not frames.get("frames"):
            warnings.append(
                f"No frame of video stream {index} could be decoded from its first "
                f"{FRAME_PACKETS} packets: HDR metadata that is only in the frames (SEI, "
                "HDR10+) was not checked."
            )
        return frames

    async def _vfr_from_packets(
        self, file: Path, index: int, cancel: CancelToken, warnings: list[str]
    ) -> bool | ProbeError:
        packets = await run_json(
            packets_argv(self.tool.path, str(file), index),
            file,
            tool=self.tool,
            timeout=self.frame_timeout,
            cancel=cancel,
            what="reading packet timestamps",
        )
        if isinstance(packets, ProbeError):
            if packets.kind is ProbeErrorKind.CANCELLED:
                return packets
            warnings.append(
                f"Video stream {index}: the packet timestamps could not be read, so a variable "
                f"frame rate cannot be ruled out: {packets.message}"
            )
            return False
        raw = packets.get("packets")
        pts: list[float] = []
        for packet in raw if isinstance(raw, list) else []:
            try:
                pts.append(float(packet["pts_time"]))
            except (KeyError, TypeError, ValueError):
                continue
        return bool(vfr_from_timestamps(pts))


def _is_matroska(data: dict[str, Any]) -> bool:
    fmt = data.get("format")
    name = fmt.get("format_name") if isinstance(fmt, dict) else None
    return "matroska" in str(name or "").split(",")


def _needs_rates(source: MediaSource) -> bool:
    streams: list[VideoStream | AudioStream] = [*source.video, *source.audio]
    return any(s.bitrate.source is BitrateSource.UNKNOWN for s in streams)


async def _sample(
    file: Path, tracks: matroska.MatroskaFile, cancel: CancelToken
) -> sampling.ClusterSample | _Cancelled | None:
    """A sample of the clusters, or ``None`` when there is none within :data:`SAMPLE_TIMEOUT`.
    That is not a warning: the rates stay unknown, and Measure finds them."""
    stop = threading.Event()

    def stopped() -> bool:
        return stop.is_set() or cancel.cancelled

    work = asyncio.to_thread(sampling.sample_clusters, file, tracks, stop=stopped)
    try:
        return await _race(work, cancel, SAMPLE_TIMEOUT)
    except TimeoutError:
        log.info("%s: the clusters were not sampled within %g s", file, SAMPLE_TIMEOUT)
    except OSError as exc:
        log.info("%s: the clusters could not be sampled: %s", file, exc)
    finally:
        stop.set()
    return None


async def _read_matroska(
    file: Path, cancel: CancelToken
) -> matroska.MatroskaFile | _Cancelled | None:
    """The track headers, or ``None`` when they cannot be read. That is not a warning: ffprobe
    read the file, and only ``language_ietf`` and the sampled rates stay unknown."""
    try:
        return await _race(
            asyncio.to_thread(matroska.read_matroska, file), cancel, MATROSKA_TIMEOUT
        )
    except TimeoutError:
        log.info("%s: the Matroska track headers were not read within %g s", file, MATROSKA_TIMEOUT)
    except (matroska.MatroskaError, OSError) as exc:
        log.info("%s: the Matroska track headers could not be read: %s", file, exc)
    return None


def _is_language_tag(value: str) -> bool:
    """``value`` is a valid :data:`~reframe.models.LanguageTag` (shape and length)."""
    try:
        _LANGUAGE_TAG.validate_python(value)
    except ValidationError:
        return False
    return True


def _shown(value: str, limit: int = 40) -> str:
    return repr(value if len(value) <= limit else value[:limit] + "…")


def apply_matroska(source: MediaSource, info: matroska.MatroskaFile) -> bool:
    """Set ``language_ietf`` of every stream to its track's ``LanguageIETF`` element, or to
    ``None`` when the track has none (no tag is derived from the legacy ``Language`` element).
    A value that is not a language tag is not used: ``None`` and a warning. The n-th video,
    audio and subtitle track of the file is the n-th stream of that kind (cover art is an
    attachment, not a track). When the counts differ nothing is set and a warning says so.
    ``True`` when the tracks matched."""
    kinds = matroska.tracks_by_kind(info)
    streams: dict[matroska.TrackKind, list[VideoStream] | list[AudioStream] | list[SubtitleStream]]
    streams = {"video": source.video, "audio": source.audio, "subtitle": source.subtitles}
    for kind, found in streams.items():
        if len(found) != len(kinds[kind]):
            source.warnings.append(
                f"The file has {len(kinds[kind])} {kind} tracks, ffprobe shows {len(found)}: "
                "the BCP 47 languages (LanguageIETF) were not read."
            )
            return False
    for kind, found in streams.items():
        for stream, track in zip(found, kinds[kind], strict=True):
            value = track.language_ietf or None
            if value is not None and not _is_language_tag(value):
                source.warnings.append(
                    f"Stream {stream.index}: the BCP 47 language (LanguageIETF) "
                    f"{_shown(value)} is not a language tag; not used."
                )
                value = None
            stream.language_ietf = value
    return True


async def probe_file(
    path: str | os.PathLike[str],
    ffprobe: ToolInfo | ProbeTool | str | os.PathLike[str],
    *,
    cache: ProbeCache | None = None,
    cancel: CancelToken | None = None,
    timeout: float = PROBE_TIMEOUT,  # noqa: ASYNC109
) -> ProbeOutcome:
    """Probe one file: ``Prober(ffprobe, cache=cache, …).probe(path, cancel=cancel)``."""
    prober = Prober(ffprobe, cache=cache, timeout=timeout)
    return await prober.probe(path, cancel=cancel)
