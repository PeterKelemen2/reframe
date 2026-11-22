"""Encoder detection in the background: cached, and never blocking.

:attr:`~CapabilityService.snapshot` never waits. A detection ends with statuses, never with
``detecting`` left on: a bug, also one in tool discovery, ends it with ``error`` statuses.
A finished detection is in the cache before anyone can see that it ended, so a short CLI run
that closes the service on that event still leaves the result for the next start. A new
ffmpeg (another path, version or status) starts a new detection.
:meth:`~CapabilityService.close` cancels the detection and returns when every detection it
started has ended.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from reframe.capabilities.cache import CacheKey, CapabilityCache, cache_key
from reframe.capabilities.detect import (
    DetectionOptions,
    current_os,
    detect_capabilities,
    initial_statuses,
    unusable_snapshot,
)
from reframe.capabilities.devices import render_nodes as list_render_nodes
from reframe.capabilities.fingerprint import gpu_fingerprint
from reframe.capabilities.issues import closest_available
from reframe.definitions import Definitions, load_definitions
from reframe.errors import ReframeClosedError
from reframe.events import EventBus, Subscription
from reframe.models.capabilities import CapabilitySnapshot, EncoderState, EncoderStatus
from reframe.models.events import CapabilitiesChangedEvent, ToolsChangedEvent
from reframe.models.tools import ToolInfo
from reframe.tools import CancelToken

if TYPE_CHECKING:
    from reframe.service import SettingsGetter, ToolsService

__all__ = ["CapabilityService"]

log = logging.getLogger(__name__)

_FfmpegIdentity = tuple[str, str | None, str | None, tuple[tuple[str, str], ...]]


def _identity(info: ToolInfo) -> _FfmpegIdentity:
    path = None if info.path is None else str(info.path)
    return (info.status.value, path, info.version, tuple(sorted(info.env.items())))


def _same(a: EncoderStatus | None, b: EncoderStatus) -> bool:
    """Equal apart from the check time."""
    if a is None:
        return False
    return a.model_dump(exclude={"checked_at"}) == b.model_dump(exclude={"checked_at"})


class CapabilityService:
    """Which encoders this FFmpeg build and this computer can use.

    :param events: ``capabilities.changed`` goes here; ``tools.changed`` is watched.
    :param tools: tool discovery; detection waits for its result (``ToolsService.status()``).
    :param settings: the current settings (``encoders.hardware_tests``).
    :param cache_dir: the folder of the capability cache.
    :param platform: a ``sys.platform`` value for the definitions' ``platforms`` (default:
        this one); tests use it to get the same results on every OS.
    :param render_nodes: lists the VAAPI render nodes to try (blocking; called in a worker
        thread, on Linux only, and not when the settings force one device; default
        ``/dev/dri/renderD*``).
    :param gpu_fingerprint: returns the GPU fingerprint of the cache key (blocking; called
        in a worker thread once per service).
    """

    def __init__(
        self,
        events: EventBus,
        tools: ToolsService,
        settings: SettingsGetter,
        *,
        cache_dir: Path,
        platform: str | None = None,
        render_nodes: Callable[[], Sequence[str]] | None = None,
        gpu_fingerprint: Callable[[], str] | None = None,
    ) -> None:
        self._events = events
        self._tools = tools
        self._settings = settings
        self._definitions = load_definitions()
        self._cache = CapabilityCache(cache_dir)
        self._os = current_os(platform)
        self._render_nodes = render_nodes or list_render_nodes
        self._gpu_source = gpu_fingerprint or (lambda: _default_fingerprint(platform))
        self._gpu: str | None = None
        self._snapshot = CapabilitySnapshot(encoders=initial_statuses(self._definitions))
        self._task: asyncio.Task[CapabilitySnapshot] | None = None
        self._token: CancelToken | None = None
        self._ffmpeg_identity: _FfmpegIdentity | None = None
        self._subscription: Subscription | None = None
        self._watcher: asyncio.Task[None] | None = None
        self._detections: set[asyncio.Task[CapabilitySnapshot]] = set()
        """Every detection that has not ended (a replaced one may still kill its encodes)."""
        self._closed = False

    @property
    def definitions(self) -> Definitions:
        return self._definitions

    @property
    def snapshot(self) -> CapabilitySnapshot:
        """The current statuses. Never waits; do not change the returned object."""
        return self._snapshot

    @property
    def detecting(self) -> bool:
        """A detection is running."""
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        """Start the first detection in the background (unless one ran). Returns at once."""
        self._check_open()
        if self._watcher is None:
            self._subscription = self._events.subscribe(types={"tools.changed"})
            self._watcher = asyncio.get_running_loop().create_task(
                self._watch(self._subscription), name="reframe-capabilities-tools-watch"
            )
        if self._task is None:
            self._start(use_cache=True)

    async def wait(self) -> CapabilitySnapshot:
        """The detection result; waits for a running detection (starts one if none ran)."""
        while True:
            self._check_open()
            task = self._task
            if task is None:
                task = self._start(use_cache=True)
            await asyncio.wait({task})
            if not task.cancelled():
                return task.result()
            # Cancelled: replaced by rescan() or a new ffmpeg (wait for the new one), closed
            # (raised above), or cancelled from outside (start a new one).
            if self._task is task:
                self._task = None

    async def rescan(self) -> CapabilitySnapshot:
        """Detect again without the cache. A running detection is cancelled first (its test
        encodes are killed); every encoder is ``checking`` until its new result is in."""
        self._check_open()
        self._start(use_cache=False)
        return await self.wait()

    def closest_available(self, encoder_id: str) -> str | None:
        """:func:`reframe.capabilities.closest_available` on the current snapshot."""
        return closest_available(encoder_id, self._snapshot, self._definitions)

    async def close(self) -> None:
        """Cancel the detection (killing its test encodes) and stop watching tool changes.
        Returns when every detection it started has ended (one that ``rescan()`` replaced
        may still be killing its test encodes)."""
        self._closed = True
        if self._token is not None:
            self._token.cancel()
        tasks = [t for t in (self._task, self._watcher) if t is not None and not t.done()]
        if self._subscription is not None:
            self._subscription.close()
        for task in tasks:
            task.cancel()
        # A replaced detection was cancelled when it was replaced: wait for it, do not cancel it.
        pending = {*tasks, *self._detections}
        if pending:
            await asyncio.wait(pending)

    def _check_open(self) -> None:
        if self._closed:
            raise ReframeClosedError

    def _start(self, *, use_cache: bool) -> asyncio.Task[CapabilitySnapshot]:
        previous, old_token = self._task, self._token
        if old_token is not None:
            old_token.cancel()
        if previous is not None and not previous.done():
            previous.cancel()
        token = CancelToken()
        self._token = token
        self._ffmpeg_identity = None
        self._snapshot = self._snapshot.model_copy(update={"detecting": True})
        task = asyncio.get_running_loop().create_task(
            self._detect(use_cache=use_cache, token=token, previous=previous),
            name="reframe-encoder-detection",
        )
        self._task = task
        self._detections.add(task)
        task.add_done_callback(self._detections.discard)
        return task

    async def _options(self) -> DetectionOptions:
        encoders = self._settings().encoders
        forced = (encoders.vaapi_device or "").strip() or None
        nodes: tuple[str, ...] = ()
        if self._os == "linux" and encoders.hardware_tests and forced is None:
            nodes = tuple(await asyncio.to_thread(self._render_nodes))
        return DetectionOptions(
            hardware_tests=encoders.hardware_tests,
            os=self._os,
            vaapi_device=forced,
            render_nodes=nodes,
        )

    async def _detect(
        self,
        *,
        use_cache: bool,
        token: CancelToken,
        previous: asyncio.Task[CapabilitySnapshot] | None,
    ) -> CapabilitySnapshot:
        if previous is not None:
            await asyncio.wait({previous})  # its test encodes are gone before new ones start
        try:
            tools = await self._tools.status()
        except ReframeClosedError as exc:  # Reframe is shutting down
            log.info("encoder detection stopped: %s", exc)
            return self._snapshot
        except Exception as exc:
            log.exception("tool discovery failed: no encoder detection")
            return self._fail(exc, token)  # data, never "detecting" for ever
        ffmpeg = tools.ffmpeg
        self._ffmpeg_identity = _identity(ffmpeg)
        try:
            return await self._run(ffmpeg, use_cache=use_cache, token=token)
        except Exception as exc:  # a bug: report it as data, never leave "detecting" behind
            log.exception("encoder detection failed")
            return self._fail(exc, token)

    async def _run(
        self, ffmpeg: ToolInfo, *, use_cache: bool, token: CancelToken
    ) -> CapabilitySnapshot:
        definitions = self._definitions
        options = await self._options()
        if not ffmpeg.usable:
            return self._finish(unusable_snapshot(ffmpeg, definitions), token)

        key = await self._key(ffmpeg, options)
        cached = None
        if use_cache and key is not None:
            cached = await asyncio.to_thread(self._cache.get, key)
        if cached is not None:
            first = cached.model_copy(update={"from_cache": True, "detecting": True})
        else:
            # The filter results of the last detection of the same build stay until the new
            # ones are in; another build's are not shown under this one.
            last = self._snapshot
            if (last.ffmpeg, last.ffmpeg_version) != (ffmpeg.path, ffmpeg.version):
                last = CapabilitySnapshot()
            first = CapabilitySnapshot(
                encoders=initial_statuses(definitions, EncoderState.CHECKING),
                filters=last.filters,
                filter_failures=last.filter_failures,
                untested_filters=last.untested_filters,
                ffmpeg=ffmpeg.path,
                ffmpeg_version=ffmpeg.version,
                detecting=True,
            )
        self._replace(first, token)

        def on_update(changed: list[EncoderStatus]) -> None:
            self._merge(changed, token)

        final = await detect_capabilities(
            ffmpeg, definitions, options, cancel=token, on_update=on_update
        )
        if token.cancelled:
            return self._snapshot
        if key is not None:
            # On the loop with no await before _finish: a cancel cannot stop the write half-way,
            # no later detection can run during it, and the result is cached before anyone can
            # see that the detection ended. It is one small file.
            self._put(key, final)
        return self._finish(final, token)

    def _put(self, key: CacheKey, snapshot: CapabilitySnapshot) -> None:
        try:
            self._cache.put(key, snapshot)  # stores it with detecting and from_cache False
        except Exception:  # a bug; cache errors never fail a detection
            log.exception("capability cache: cannot store the detection result")

    async def _key(self, ffmpeg: ToolInfo, options: DetectionOptions) -> CacheKey | None:
        if self._gpu is None:
            try:
                self._gpu = await asyncio.to_thread(self._gpu_source)
            except Exception:
                log.exception("GPU fingerprint failed")
                self._gpu = "unknown"
        return await asyncio.to_thread(
            cache_key, ffmpeg, gpu=self._gpu, options=options, definitions=self._definitions
        )

    def _publish(self, statuses: list[EncoderStatus]) -> None:
        if statuses:
            self._events.publish(CapabilitiesChangedEvent(encoders=statuses))

    def _replace(self, snapshot: CapabilitySnapshot, token: CancelToken) -> None:
        if self._token is not token:
            return  # a replaced detection
        self._snapshot = snapshot
        self._publish(list(snapshot.encoders.values()))

    def _merge(self, changed: list[EncoderStatus], token: CancelToken) -> None:
        if self._token is not token:
            return
        current = self._snapshot.encoders
        visible = [status for status in changed if not _same(current.get(status.id), status)]
        encoders = {**current, **{status.id: status for status in changed}}
        self._snapshot = self._snapshot.model_copy(update={"encoders": encoders})
        self._publish(visible)

    def _finish(self, snapshot: CapabilitySnapshot, token: CancelToken) -> CapabilitySnapshot:
        final = snapshot.model_copy(update={"detecting": False, "from_cache": False})
        self._replace(final, token)
        return final

    def _fail(self, exc: Exception, token: CancelToken) -> CapabilitySnapshot:
        reason = f"Encoder detection failed: {type(exc).__name__}: {exc}"
        open_states = {EncoderState.CHECKING, EncoderState.UNKNOWN}
        encoders = {
            key: (
                status.model_copy(update={"state": EncoderState.ERROR, "reason": reason})
                if status.state in open_states
                else status
            )
            for key, status in self._snapshot.encoders.items()
        }
        return self._finish(self._snapshot.model_copy(update={"encoders": encoders}), token)

    async def _watch(self, subscription: Subscription) -> None:
        """Start a new detection when tool discovery reports another ffmpeg."""
        async for event in subscription:
            if not isinstance(event, ToolsChangedEvent) or self._closed:
                continue
            known = self._ffmpeg_identity
            new = _identity(event.tools.ffmpeg)
            if known is None or new == known:
                continue  # the detection has not read the tools yet, or nothing changed
            log.info("ffmpeg changed (%s): detecting the encoders again", event.tools.ffmpeg.path)
            self._start(use_cache=True)


def _default_fingerprint(platform: str | None) -> str:
    return gpu_fingerprint(platform=platform)
