"""Probe one file (C-3): ffprobe, HDR frame fallback, MediaInfo, cache.

:class:`Prober` holds the configuration (which ffprobe, the cache, MediaInfo on or off) and is
what ``SourceService`` (C-15) uses. :func:`probe_file` is the one-call form.

Steps of :meth:`Prober.probe`:

1. ``stat`` the file (missing, folder, unreadable → :class:`ProbeError`).
2. Cache lookup by path + size + mtime, ffprobe identity and options.
3. ``ffprobe … -show_format -show_streams -show_chapters -show_programs`` (60 s).
4. If the main video stream may be HDR without static side data (or may have HDR10+), read its
   first frame (:func:`reframe.probe.hdr.needs_frame_side_data`). A failure here is a
   warning, not an error.
5. Parse (:func:`reframe.probe.parse.parse_ffprobe`).
6. MediaInfo for audio/video bit rates that are still unknown (if available and enabled; in a
   worker thread, at most :data:`MEDIAINFO_TIMEOUT` s). A failure is a warning.
7. Store in the cache.
"""

from __future__ import annotations

import asyncio
import os
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
    VideoStream,
)
from reframe.models.tools import ToolInfo
from reframe.probe import mediainfo, roles
from reframe.probe.cache import CacheKey, ProbeCache
from reframe.probe.ffprobe import (
    FRAME_TIMEOUT,
    PROBE_TIMEOUT,
    ProbeError,
    ProbeErrorKind,
    ProbeTool,
    frames_argv,
    probe_argv,
    run_json,
)
from reframe.probe.hdr import needs_frame_side_data
from reframe.probe.parse import main_video_index, parse_ffprobe, video_bit_depth
from reframe.tools import CancelToken

__all__ = ["MEDIAINFO_TIMEOUT", "ProbeOutcome", "Prober", "probe_file"]

#: Seconds to wait for MediaInfo (the thread cannot be killed; the probe stops waiting).
MEDIAINFO_TIMEOUT = 30.0

#: The result of probing one file.
ProbeOutcome = MediaSource | ProbeError


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

    def _mediainfo_on(self) -> bool:
        return self.use_mediainfo and mediainfo.mediainfo_available()

    def cache_options(self) -> dict[str, Any]:
        """The options that change a probe result (part of the cache entry)."""
        return {"mediainfo": self._mediainfo_on()}

    async def probe(
        self,
        path: str | os.PathLike[str],
        *,
        cancel: CancelToken | None = None,
        use_cache: bool = True,
    ) -> ProbeOutcome:
        """Probe ``path``. Never raises for problems with the file or the tool."""
        identity = self.tool.identity()
        options = self.cache_options()
        # stat() and the cache file read can block on a network share: use a worker thread.
        prepared = await asyncio.to_thread(self._prepare, path, identity, options, use_cache)
        if isinstance(prepared, (ProbeError, MediaSource)):
            return prepared
        file, stat, key = prepared

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
        frames = await self._first_frame(data, file, cancel, warnings)
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
        if options["mediainfo"]:
            await _apply_mediainfo(source, file)
        if self.cache is not None:
            await asyncio.to_thread(self.cache.put, key, source, tool=identity, options=options)
        return source

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

    async def _first_frame(
        self,
        data: dict[str, Any],
        file: Path,
        cancel: CancelToken | None,
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
            what="reading the first frame",
        )
        if isinstance(frames, ProbeError):
            if frames.kind is ProbeErrorKind.CANCELLED:
                return frames
            warnings.append(
                f"The HDR side data of the first frame could not be read: {frames.message}"
                + (f" ({frames.detail})" if frames.detail else "")
            )
            return None
        return frames


async def _apply_mediainfo(source: MediaSource, file: Path) -> None:
    streams: list[VideoStream | AudioStream] = [*source.video, *source.audio]
    if not any(s.bitrate.source is BitrateSource.UNKNOWN for s in streams):
        return
    try:
        rates = await asyncio.wait_for(
            asyncio.to_thread(mediainfo.read_bitrates, file), timeout=MEDIAINFO_TIMEOUT
        )
    except TimeoutError:
        source.warnings.append(f"MediaInfo did not finish within {MEDIAINFO_TIMEOUT:g} s.")
        return
    except Exception as exc:  # the library's own errors for a file it cannot read
        source.warnings.append(f"MediaInfo could not read the file: {exc}")
        return
    for stream in streams:
        if stream.bitrate.source is not BitrateSource.UNKNOWN:
            continue
        value = rates.get((stream.kind, stream.index))
        if value is not None:
            stream.bitrate = BitrateInfo(value=value, source=BitrateSource.MEDIAINFO)
    roles.assign_audio_roles(source.audio)  # the commentary heuristic uses bit rates


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
