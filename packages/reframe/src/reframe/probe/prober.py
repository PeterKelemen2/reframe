"""Probe one file (C-3): ffprobe, HDR frame fallback, MediaInfo, VFR check, cache.

:class:`Prober` holds the configuration (which ffprobe, the cache, MediaInfo on or off) and is
what ``SourceService`` (C-15) uses. :func:`probe_file` is the one-call form.

Steps of :meth:`Prober.probe`:

1. ``stat`` the file (missing, folder, unreadable → :class:`ProbeError`) and look it up in the
   cache (path + size + mtime, ffprobe identity, parser fingerprint, options). Both in a
   worker thread (a network share can block), raced against the cancel token.
2. **Single flight**: concurrent probes of the same file version share one run.
3. ``ffprobe … -show_format -show_streams -show_chapters -show_programs`` (60 s).
4. If the main video stream may be HDR without static side data (or may have HDR10+), read
   its first frames (:func:`reframe.probe.hdr.needs_frame_side_data`). A failure, or no frame
   decoded, is a warning, not an error.
5. Parse (:func:`reframe.probe.parse.parse_ffprobe`).
6. MediaInfo (if available and enabled; worker thread, at most :data:`MEDIAINFO_TIMEOUT` s,
   raced against the cancel token): bit rates that are still unknown, ``language_ietf``, and
   ``FrameRate_Mode`` for Matroska streams whose VFR state ffprobe cannot tell. A failure is
   a warning.
7. A Matroska file's track headers (:mod:`reframe.probe.matroska`; worker thread, raced
   against the cancel token): ``language_ietf`` of each stream whose track has a
   ``LanguageIETF`` element, which ffprobe does not show (decision 0034). It wins over
   MediaInfo's value. A file the reader cannot read is skipped (logged); tracks that do not
   match the streams are a warning.
8. Streams whose VFR state is still undecided: sample packet timestamps
   (:func:`reframe.probe.ffprobe.packets_argv`, :func:`reframe.probe.parse.vfr_from_timestamps`).
9. Store in the cache.

Cancelling (the token or the calling task) stops the probe at once: ffprobe is killed by
``reframe.tools.run``, and a worker thread (``stat``, MediaInfo) is left to finish on its own
while the probe returns ``ProbeErrorKind.CANCELLED``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from stat import S_ISREG
from typing import Any

from pydantic import ValidationError

from reframe.models.media import (
    AudioStream,
    BitrateInfo,
    BitrateSource,
    MediaSource,
    SourceFingerprint,
    SubtitleStream,
    VideoStream,
)
from reframe.models.tools import ToolInfo
from reframe.probe import matroska, mediainfo, roles
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
    main_video_index,
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
    "MEDIAINFO_TIMEOUT",
    "ProbeOutcome",
    "Prober",
    "apply_matroska",
    "probe_file",
]

#: Seconds to wait for MediaInfo (the thread cannot be killed; the probe stops waiting).
MEDIAINFO_TIMEOUT = 30.0
#: Seconds to wait for the Matroska track reader (a slow network share).
MATROSKA_TIMEOUT = 30.0
#: The version of what the Matroska reader adds to a probe (part of the cache entry's options:
#: entries made before it lack ``language_ietf``).
MATROSKA_READER = 1

#: The result of probing one file.
ProbeOutcome = MediaSource | ProbeError


class _Cancelled:
    """Returned by :func:`_race` when the token was cancelled first."""


_CANCELLED = _Cancelled()


async def _race[T](
    work: Awaitable[T],
    cancel: CancelToken | None,
    timeout: float | None = None,  # noqa: ASYNC109 - a limit for the work, not this coroutine
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
        use_mediainfo: bool = True,
        timeout: float = PROBE_TIMEOUT,
        frame_timeout: float = FRAME_TIMEOUT,
    ) -> None:
        self.tool = ProbeTool.of(ffprobe)
        self.cache = cache
        self.use_mediainfo = use_mediainfo
        self.timeout = timeout
        self.frame_timeout = frame_timeout
        self._flights: dict[tuple[CacheKey, bool], _Flight] = {}

    def _mediainfo_on(self) -> bool:
        return self.use_mediainfo and mediainfo.mediainfo_available()

    def cache_options(self) -> dict[str, Any]:
        """The options that change a probe result (part of the cache entry): the MediaInfo
        version in use, or ``False``."""
        return {
            "mediainfo": mediainfo.mediainfo_version() if self._mediainfo_on() else False,
            "matroska": MATROSKA_READER,
        }

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
                # Nobody waits any more: stop the shared run (a new caller starts a new one),
                # and do not return before its ffprobe is gone (a TaskGroup caller relies on
                # that).
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
            return ProbeError(file, ProbeErrorKind.NOT_FOUND, "The file does not exist.")
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
            )
        except (ValidationError, ValueError, TypeError) as exc:
            return ProbeError(
                file,
                ProbeErrorKind.INVALID_OUTPUT,
                "ffprobe's output could not be understood.",
                str(exc),
            )
        undecided = set(vfr_undecided(data))
        if options["mediainfo"]:
            info = await _read_mediainfo(source, file, cancel)
            if isinstance(info, _Cancelled):
                return _cancelled(file)
            if info is not None:
                _apply_mediainfo(source, info, undecided)
        if _is_matroska(source):
            tracks = await _read_matroska(source, file, cancel)
            if isinstance(tracks, _Cancelled):
                return _cancelled(file)
            if tracks is not None:
                apply_matroska(source, tracks)
        for stream in source.video:
            if stream.index in undecided:
                vfr = await self._vfr_from_packets(file, stream.index, cancel, source.warnings)
                if isinstance(vfr, ProbeError):
                    return vfr  # cancelled
                stream.vfr = bool(vfr)
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
        index = main_video_index(data)
        if index is None:
            return None
        stream = next(
            s for s in data.get("streams", []) if isinstance(s, dict) and s.get("index") == index
        )
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


async def _read_mediainfo(
    source: MediaSource, file: Path, cancel: CancelToken
) -> mediainfo.MediaInfoData | _Cancelled | None:
    try:
        return await _race(
            asyncio.to_thread(mediainfo.read_mediainfo, file), cancel, MEDIAINFO_TIMEOUT
        )
    except TimeoutError:
        source.warnings.append(f"MediaInfo did not finish within {MEDIAINFO_TIMEOUT:g} s.")
    except Exception as exc:  # the library's own errors for a file it cannot read
        source.warnings.append(f"MediaInfo could not read the file: {exc}")
    return None


def _apply_mediainfo(
    source: MediaSource, info: mediainfo.MediaInfoData, undecided: set[int]
) -> None:
    """Fill unknown bit rates, ``language_ietf`` and undecided VFR states (``undecided`` loses
    the streams that MediaInfo decides).

    MediaInfo reads the Matroska statistics tags too, so it repeats stale ones: a MediaInfo
    bit rate above the container's bit rate (+5 %) is not used either.
    """
    limit = source.container.bitrate * 1.05 if source.container.bitrate else None
    rated: list[VideoStream | AudioStream] = [*source.video, *source.audio]
    for stream in rated:
        if stream.bitrate.source is BitrateSource.UNKNOWN:
            value = info.bitrates.get((stream.kind, stream.index))
            if value is not None and limit is not None and value > limit:
                source.warnings.append(
                    f"Stream {stream.index}: MediaInfo's bit rate {value} is more than the "
                    f"file's {source.container.bitrate}; not used."
                )
            elif value is not None:
                stream.bitrate = BitrateInfo(value=value, source=BitrateSource.MEDIAINFO)
    tracks: list[VideoStream | AudioStream | SubtitleStream] = [*rated, *source.subtitles]
    for track in tracks:
        language = info.languages.get((track.kind, track.index))
        if language is not None:
            track.language_ietf = language
    for video in source.video:
        mode = info.frame_rate_modes.get(("video", video.index))
        if video.index in undecided and mode is not None:
            video.vfr = mode == "VFR"
            undecided.discard(video.index)
    roles.assign_audio_roles(source.audio)  # the commentary heuristic uses bit rates


def _is_matroska(source: MediaSource) -> bool:
    return "matroska" in (source.container.format_name or "").split(",")


async def _read_matroska(
    source: MediaSource, file: Path, cancel: CancelToken
) -> matroska.MatroskaFile | _Cancelled | None:
    """The track headers, or ``None`` when they cannot be read. Not a warning: ffprobe read
    the file, only ``language_ietf`` stays unknown (as without MediaInfo before 0034); an
    in-place edit reads them again and refuses to run without them."""
    try:
        return await _race(
            asyncio.to_thread(matroska.read_matroska, file), cancel, MATROSKA_TIMEOUT
        )
    except TimeoutError:
        log.info("%s: the Matroska track headers were not read within %g s", file, MATROSKA_TIMEOUT)
    except (matroska.MatroskaError, OSError) as exc:
        log.info("%s: the Matroska track headers could not be read: %s", file, exc)
    return None


def apply_matroska(source: MediaSource, info: matroska.MatroskaFile) -> bool:
    """Set ``language_ietf`` from the tracks' ``LanguageIETF`` elements. The n-th video,
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
            if track.language_ietf:
                stream.language_ietf = track.language_ietf
    return True


async def probe_file(
    path: str | os.PathLike[str],
    ffprobe: ToolInfo | ProbeTool | str | os.PathLike[str],
    *,
    cache: ProbeCache | None = None,
    cancel: CancelToken | None = None,
    use_mediainfo: bool = True,
    timeout: float = PROBE_TIMEOUT,  # noqa: ASYNC109 - passed to run()
) -> ProbeOutcome:
    """Probe one file: ``Prober(ffprobe, cache=cache, …).probe(path, cancel=cancel)``."""
    prober = Prober(ffprobe, cache=cache, use_mediainfo=use_mediainfo, timeout=timeout)
    return await prober.probe(path, cancel=cancel)
