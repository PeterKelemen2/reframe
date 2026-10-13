"""The capability service (C-4): encoder detection in the background, cached, never blocking.

:class:`CapabilityService` is ``Reframe.capabilities``:

- :meth:`~CapabilityService.start` (called by ``Reframe.create()``) returns at once. A
  background task waits for tool discovery, shows the cached result of the same ffmpeg and GPU
  (``from_cache=True``), runs a full detection anyway ("checked again in the background") and
  replaces the result with it.
- :attr:`~CapabilityService.snapshot` never waits. Before the first result every encoder is
  ``unknown`` (``detecting=True``); without a cached result, every encoder is ``checking``
  while the detection runs.
- ``capabilities.changed`` is published when statuses change: all encoders when the cached
  result or the ``checking`` statuses are put in place, each encoder whose status changes
  while the detection runs, and all encoders when a detection ends.
- A new ffmpeg (a ``tools.changed`` event with another path, version or status, for example
  after a Settings → Tools change) starts a new detection (02 §Bundled FFmpeg).
- :meth:`~CapabilityService.close` cancels the detection; the running test encodes are killed
  (process tree).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from reframe.capabilities.cache import CacheKey, CapabilityCache, cache_key
from reframe.capabilities.detect import (
    LIST_TIMEOUT,
    MAX_PARALLEL_TESTS,
    DetectionOptions,
    current_os,
    detect_capabilities,
    initial_statuses,
    unusable_snapshot,
)
from reframe.capabilities.devices import render_nodes as list_render_nodes
from reframe.capabilities.fingerprint import gpu_fingerprint
from reframe.capabilities.hwtest import TEST_TIMEOUT
from reframe.capabilities.issues import closest_available
from reframe.definitions import Definitions, load_definitions
from reframe.events import EventBus, Subscription
from reframe.models.capabilities import CapabilitySnapshot, EncoderState, EncoderStatus
from reframe.models.events import CapabilitiesChangedEvent, ToolsChangedEvent
from reframe.models.tools import ToolInfo, ToolStatus
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


def _closed_error() -> Exception:
    from reframe.service import ReframeClosedError  # reframe.service imports this module

    return ReframeClosedError()


class CapabilityService:
    """Which encoders this FFmpeg build and this computer can use (C-4).

    :param events: ``capabilities.changed`` goes here; ``tools.changed`` is watched.
    :param tools: tool discovery; detection waits for its result (``ToolsService.status()``).
    :param settings: the current settings (``encoders.hardware_tests``).
    :param cache_dir: the folder of the capability cache.
    :param definitions: the encoder definitions (default :func:`load_definitions`).
    :param platform: a ``sys.platform`` value for the definitions' ``platforms`` (default:
        this one); tests use it to get the same results on every OS.
    :param render_nodes: lists the VAAPI render nodes to try (blocking; called in a worker
        thread before each detection on Linux; default ``/dev/dri/renderD*``). Settings →
        Encoders ``vaapi_device`` replaces the list with one node.
    :param gpu_fingerprint: returns the GPU fingerprint of the cache key (blocking; called
        in a worker thread once per service).
    :param watch_tools: start a new detection when ``tools.changed`` reports another ffmpeg.
    """

    def __init__(
        self,
        events: EventBus,
        tools: ToolsService,
        settings: SettingsGetter,
        *,
        cache_dir: Path,
        definitions: Definitions | None = None,
        platform: str | None = None,
        render_nodes: Callable[[], Sequence[str]] | None = None,
        test_timeout: float = TEST_TIMEOUT,
        list_timeout: float = LIST_TIMEOUT,
        max_parallel_tests: int = MAX_PARALLEL_TESTS,
        gpu_fingerprint: Callable[[], str] | None = None,
        watch_tools: bool = True,
    ) -> None:
        self._events = events
        self._tools = tools
        self._settings = settings
        self._definitions = definitions if definitions is not None else load_definitions()
        self._cache = CapabilityCache(cache_dir)
        self._os = current_os(platform)
        self._render_nodes = render_nodes or list_render_nodes
        self._test_timeout = test_timeout
        self._list_timeout = list_timeout
        self._max_parallel_tests = max_parallel_tests
        self._gpu_source = gpu_fingerprint or (lambda: _default_fingerprint(platform))
        self._gpu: str | None = None
        self._watch_tools = watch_tools
        self._snapshot = CapabilitySnapshot(encoders=initial_statuses(self._definitions))
        self._task: asyncio.Task[CapabilitySnapshot] | None = None
        self._token: CancelToken | None = None
        self._ffmpeg_identity: _FfmpegIdentity | None = None
        self._subscription: Subscription | None = None
        self._watcher: asyncio.Task[None] | None = None
        self._closed = False

    # ------------------------------------------------------------------ public API

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
        if self._watch_tools and self._watcher is None:
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
            # (raise above), or cancelled from outside (start a new one).
            if self._task is task:
                self._task = None

    async def rescan(self) -> CapabilitySnapshot:
        """Detect again without the cache (*Re-scan*, *Check again*). A running detection is
        cancelled first (its test encodes are killed); every encoder is ``checking`` until
        its new result is in."""
        self._check_open()
        self._start(use_cache=False)
        return await self.wait()

    def closest_available(self, encoder_id: str) -> str | None:
        """:func:`reframe.capabilities.closest_available` on the current snapshot."""
        return closest_available(encoder_id, self._snapshot, self._definitions)

    async def close(self) -> None:
        """Cancel the detection (killing its test encodes) and stop watching tool changes."""
        self._closed = True
        if self._token is not None:
            self._token.cancel("shutting down")
        tasks = [t for t in (self._task, self._watcher) if t is not None and not t.done()]
        if self._subscription is not None:
            self._subscription.close()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks)

    # ------------------------------------------------------------------ internals

    def _check_open(self) -> None:
        if self._closed:
            raise _closed_error()

    def _start(self, *, use_cache: bool) -> asyncio.Task[CapabilitySnapshot]:
        previous, old_token = self._task, self._token
        if old_token is not None:
            old_token.cancel("replaced by a new detection")
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
            test_timeout=self._test_timeout,
            list_timeout=self._list_timeout,
            max_parallel_tests=self._max_parallel_tests,
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
        except Exception as exc:  # ReframeClosedError: Reframe is shutting down
            log.info("encoder detection stopped: %s", exc)
            return self._snapshot
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
        if ffmpeg.status is not ToolStatus.FOUND or ffmpeg.path is None:
            return self._finish(unusable_snapshot(ffmpeg, definitions), token)

        key = await self._key(ffmpeg, options)
        cached = None
        if use_cache and key is not None:
            cached = await asyncio.to_thread(self._cache.get, key)
        if cached is not None:
            first = cached.model_copy(update={"from_cache": True, "detecting": True})
        else:
            first = CapabilitySnapshot(
                encoders=initial_statuses(definitions, EncoderState.CHECKING),
                # the filter results of the last detection stay until the new ones are in
                filters=self._snapshot.filters,
                filter_failures=self._snapshot.filter_failures,
                untested_filters=self._snapshot.untested_filters,
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
        finished = self._finish(final, token)
        if key is not None:
            await asyncio.to_thread(self._cache.put, key, finished)
        return finished

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
