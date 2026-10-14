"""The ``Reframe`` facade (C-15): the one object that UIs (CLI, server, desktop) talk to.

02 §Cross-cutting rules 5: UIs use this object and ``reframe.models``, never the internal
modules. M1 wired the services of that milestone (tools, sources); C-4 adds ``capabilities``;
C-11 adds ``queue``; the other M2 steps add theirs (presets, jobs, batch, settings) as
attributes of :class:`Reframe`.

Example::

    async with await Reframe.create() as app:
        outcome = await app.sources.probe("Show S01E01.mkv")
        if isinstance(outcome, ProbeError):
            print(outcome.message)
        else:
            print(outcome.audio[0].display_codec)

Expected failures are values, never exceptions: :meth:`SourceService.probe` returns a
:class:`ProbeError` for a missing file, a file that is not media, or an ffprobe that cannot be
used; :meth:`ToolsService.status` returns a :class:`~reframe.models.ToolSet` whose entries say
why a tool is missing. Using the facade after :meth:`Reframe.close` is a programming error
(:class:`ReframeClosedError`).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from stat import S_ISREG
from types import TracebackType

from pydantic import JsonValue, TypeAdapter, ValidationError

from reframe import paths
from reframe.capabilities import CapabilityService
from reframe.events import EventBus
from reframe.jobs import JobService
from reframe.jsonpatch import JsonPatchError, apply_patch
from reframe.models.events import AppWarningEvent, ToolsChangedEvent
from reframe.models.issues import JsonPatchOp, Severity, ValidationIssue
from reframe.models.job import JobSettings
from reframe.models.media import MediaSource
from reframe.models.naming import NamingOptions
from reframe.models.preset import FieldChange, Preset, PresetFile
from reframe.models.settings import AppSettings
from reframe.models.tasks import TaskInfo
from reframe.models.template import JobTemplate
from reframe.models.tools import ToolInfo, ToolName, ToolSet, ToolStatus
from reframe.presets import ConflictPolicy, ImportResult, PresetStore, diff, diff_documents
from reframe.probe import (
    ProbeCache,
    ProbeError,
    ProbeErrorKind,
    Prober,
    ProbeTool,
)
from reframe.probe.cache import CacheKey
from reframe.probe.folder import (
    DEFAULT_CONCURRENCY,
    TASK_KIND,
    FolderProbeResult,
    probe_folder,
)
from reframe.queue import QueueService
from reframe.settings import SettingsStore, SettingsUpdate, validation_detail
from reframe.tasks import TaskContext, TaskManager
from reframe.tools import CancelToken, check_tool, locate_tools
from reframe.tools.discovery import TOOL_NAMES, VERSION_TIMEOUT

__all__ = [
    "FolderProbeResult",
    "ImportResult",
    "JobService",
    "PresetService",
    "ProbeError",
    "ProbeErrorKind",
    "Reframe",
    "ReframeClosedError",
    "SettingsGetter",
    "SettingsService",
    "SettingsUpdate",
    "SourceService",
    "ToolsService",
    "tool_usable",
]

log = logging.getLogger(__name__)

#: Returns the current settings. Every service reads the settings through this one callable,
#: so the settings store (C-9) plugs in without changing the services or their callers.
SettingsGetter = Callable[[], AppSettings]

#: Sources that :meth:`SourceService.get` keeps in memory (the disk cache keeps all).
KNOWN_SOURCES = 1024
#: Seconds that :meth:`Reframe.close` waits for running probes to end after cancelling them.
CLOSE_TIMEOUT = 10.0


class ReframeClosedError(RuntimeError):
    """The facade was used after :meth:`Reframe.close`."""

    def __init__(self) -> None:
        super().__init__("this Reframe instance is closed")


def tool_usable(info: ToolInfo) -> bool:
    """A tool can be run: status ``found`` and a path. ``too_old`` and ``broken`` are not."""
    return info.status is ToolStatus.FOUND and info.path is not None


# --------------------------------------------------------------------------- tools


class ToolsService:
    """Which ffmpeg, ffprobe, mkvpropedit and mediainfo Reframe uses (C-1), and re-scans.

    Discovery runs in the background: :meth:`start` (called by :meth:`Reframe.create`) does
    not wait. :meth:`status` waits for the running discovery; :attr:`current` does not.
    Every finished discovery publishes ``tools.changed`` on the event bus.
    """

    def __init__(
        self,
        events: EventBus,
        settings: SettingsGetter,
        *,
        bundled_roots: Sequence[Path],
        timeout: float = VERSION_TIMEOUT,
    ) -> None:
        self._events = events
        self._settings = settings
        self._bundled_roots = list(bundled_roots)
        self._timeout = timeout
        self._task: asyncio.Task[ToolSet] | None = None
        self._current: ToolSet | None = None
        self._closed = False

    @property
    def current(self) -> ToolSet | None:
        """The result of the last finished discovery; ``None`` until the first one ends."""
        return self._current

    @property
    def discovering(self) -> bool:
        """A discovery is running."""
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        """Start a discovery in the background unless one is running. Returns at once."""
        if self._closed:
            raise ReframeClosedError
        if self._task is None:
            self._start()

    async def status(self) -> ToolSet:
        """The discovery result; waits for a running discovery (starts one if none ran)."""
        while True:
            if self._closed:
                raise ReframeClosedError
            task = self._task
            if task is None:
                task = self._start()
            await asyncio.wait({task})
            if not task.cancelled():
                return task.result()
            # Cancelled: replaced by rescan() (wait for the new one), closed (raise above), or
            # cancelled from outside (start a new one).
            if self._task is task:
                self._task = None

    async def versions(self) -> dict[ToolName, str | None]:
        """``{"ffmpeg": "n9.0.2", …}``; ``None`` for a tool that was not found."""
        tools = await self.status()
        return {name: tools.get(name).version for name in TOOL_NAMES}

    async def rescan(self) -> ToolSet:
        """Run discovery again (after a Settings → Tools change, or *Check again*).

        A discovery that is still running is cancelled first: its result would be stale.
        """
        if self._closed:
            raise ReframeClosedError
        old = self._task
        if old is not None and not old.done():
            old.cancel()
        self._start()
        return await self.status()

    async def close(self) -> None:
        """Cancel a running discovery (its version-check processes are killed)."""
        self._closed = True
        task = self._task
        if task is not None and not task.done():
            task.cancel()
            await asyncio.wait({task})

    def _start(self) -> asyncio.Task[ToolSet]:
        task = asyncio.get_running_loop().create_task(
            self._discover(), name="reframe-tool-discovery"
        )
        self._task = task
        return task

    async def _discover(self) -> ToolSet:
        # discover_tools(), but locate_tools() runs in a thread (a network share can be slow
        # to stat). The TaskGroup waits for every version check, so close() returns only
        # after every child process is gone.
        located = await asyncio.to_thread(
            locate_tools, self._settings().tools, bundled_roots=self._bundled_roots
        )
        async with asyncio.TaskGroup() as group:
            checks = [
                group.create_task(check_tool(located[name], timeout=self._timeout))
                for name in TOOL_NAMES
            ]
        tools = ToolSet(**{check.result().name: check.result() for check in checks})
        self._current = tools
        self._events.publish(ToolsChangedEvent(tools=tools))
        return tools


# --------------------------------------------------------------------------- sources


class SourceService:
    """Probing source files (C-3): one file, a folder (as a task), and the known sources.

    Results are cached in memory and on disk (``<cache dir>/probe``), keyed by path + size +
    mtime and the ffprobe build, so probing an unchanged file again is cheap.
    """

    def __init__(
        self,
        tools: ToolsService,
        tasks: TaskManager,
        cache: ProbeCache,
        *,
        is_closed: Callable[[], bool],
    ) -> None:
        self._tools = tools
        self._tasks = tasks
        self._cache = cache
        self._is_closed = is_closed
        self._prober: Prober | None = None
        self._known: OrderedDict[Path, MediaSource] = OrderedDict()
        self._tokens: set[CancelToken] = set()
        self._active = 0
        self._idle = asyncio.Event()
        self._idle.set()

    @property
    def cache(self) -> ProbeCache:
        return self._cache

    async def probe(
        self,
        path: str | os.PathLike[str],
        *,
        use_cache: bool = True,
        cancel: CancelToken | None = None,
    ) -> MediaSource | ProbeError:
        """Probe one file. Waits for tool discovery if it is still running.

        Never raises for problems with the file or the tool: a missing file is
        ``ProbeErrorKind.NOT_FOUND`` (also when ffprobe is missing too), an unusable ffprobe is
        ``TOOL_FAILED`` (``detail`` is the tool's status reason; see :meth:`ToolsService.status`
        for its origin), a file that is not media is ``FAILED``.
        """
        self._check_open()
        token = cancel or CancelToken()
        self._enter(token)
        try:
            try:
                prober = await self._get_prober()
            except ReframeClosedError:
                return ProbeError(
                    _absolute(path),
                    ProbeErrorKind.CANCELLED,
                    "The probe was cancelled: Reframe is shutting down.",
                )
            # The file checks first (missing, not a file, unreadable), so an unreadable file is
            # reported as such and not as an ffprobe failure.
            problem = await asyncio.to_thread(_check_file, path)
            if isinstance(prober, ToolInfo):
                return problem or _tool_error(_absolute(path), prober)
            if problem is not None:
                return problem
            outcome = await prober.probe(path, cancel=token, use_cache=use_cache)
            if isinstance(outcome, MediaSource):
                self._remember(outcome)
            return outcome
        finally:
            self._leave(token)

    def probe_folder(
        self,
        path: str | os.PathLike[str],
        *,
        recursive: bool = False,
        concurrency: int = DEFAULT_CONCURRENCY,
    ) -> TaskInfo:
        """Probe every media file of a folder as a background task (kind ``probe_folder``).

        Returns at once. Progress and the end come as ``task.progress`` / ``task.done``
        events. ``TaskInfo.result`` is ``{"folder", "total", "probed": [paths], "errors":
        [...]}``; the :class:`FolderProbeResult` (with the sources) is
        ``Reframe.tasks.value(task_id)``, and every source is also returned by :meth:`get`.
        An unusable ffprobe gives a result with one ``tool_failed`` error for the folder.
        """
        self._check_open()
        if concurrency < 1:
            raise ValueError(f"concurrency must be at least 1, got {concurrency}")
        root = _absolute(path)

        async def work(ctx: TaskContext) -> FolderProbeResult:
            ctx.progress(None, "Waiting for tool discovery")
            prober = await self._get_prober()
            if isinstance(prober, ToolInfo):
                return FolderProbeResult(root, errors=[_tool_error(root, prober)])

            def report(done: int, total: int, _path: Path) -> None:
                ctx.progress(done=done, total=total, message=f"{done}/{total} files")

            ctx.progress(0.0, "Listing files")
            # A cancel arrives both as the task's CancelledError and through ctx.cancel;
            # probe_folder() returns only after every ffprobe it started is gone.
            result = await probe_folder(
                prober,
                root,
                concurrency=concurrency,
                recursive=recursive,
                cancel=ctx.cancel,
                on_progress=report,
            )
            for source in result.sources:
                self._remember(source)
            return result

        def to_json(value: object) -> JsonValue:
            return value.to_json() if isinstance(value, FolderProbeResult) else None

        return self._tasks.start(
            TASK_KIND, work, message=f"Probing {root.name}", result_json=to_json
        )

    async def get(self, path: str | os.PathLike[str]) -> MediaSource | None:
        """The probed source of ``path`` if it is known and the file has not changed since.

        Never runs ffprobe. Looks in memory, then (once tool discovery has finished) in the
        disk cache.
        """
        self._check_open()
        file = _absolute(path)
        try:
            stat = await asyncio.to_thread(os.stat, file)
        except OSError:
            return None
        known = self._known.get(file)
        fingerprint = known.ref.fingerprint if known is not None else None
        if (
            known is not None
            and fingerprint is not None
            and fingerprint.size == stat.st_size
            and fingerprint.mtime == stat.st_mtime
        ):
            return known.model_copy(deep=True)
        prober = self._prober_now()
        if prober is None or prober.cache is None:
            return None
        key = CacheKey.for_file(file, stat)
        cached = await asyncio.to_thread(
            prober.cache.get, key, tool=prober.tool.identity(), options=prober.cache_options()
        )
        if cached is not None:
            self._remember(cached)
        return cached

    async def close(self, timeout: float = CLOSE_TIMEOUT) -> None:  # noqa: ASYNC109
        """Cancel running probes (their processes are killed) and wait for them to end."""
        for token in list(self._tokens):
            token.cancel("shutting down")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._idle.wait(), timeout)

    # ------------------------------------------------------------------ internals

    def _check_open(self) -> None:
        if self._is_closed():
            raise ReframeClosedError

    def _remember(self, source: MediaSource) -> None:
        self._known[source.ref.path] = source
        self._known.move_to_end(source.ref.path)
        while len(self._known) > KNOWN_SOURCES:
            self._known.popitem(last=False)

    def _enter(self, token: CancelToken) -> None:
        self._tokens.add(token)
        self._active += 1
        self._idle.clear()

    def _leave(self, token: CancelToken) -> None:
        self._tokens.discard(token)
        self._active -= 1
        if self._active == 0:
            self._idle.set()

    async def _get_prober(self) -> Prober | ToolInfo:
        """A prober for the discovered ffprobe, or its ``ToolInfo`` when it cannot be used."""
        tools = await self._tools.status()
        return self._prober_for(tools.ffprobe)

    def _prober_now(self) -> Prober | None:
        tools = self._tools.current
        if tools is None:
            return None
        prober = self._prober_for(tools.ffprobe)
        return prober if isinstance(prober, Prober) else None

    def _prober_for(self, info: ToolInfo) -> Prober | ToolInfo:
        if not tool_usable(info):
            return info
        tool = ProbeTool.of(info)
        if self._prober is None or self._prober.tool != tool:
            self._prober = Prober(tool, cache=self._cache)
        return self._prober


def _absolute(path: str | os.PathLike[str]) -> Path:
    """The absolute path, as :class:`Prober` stores it in ``MediaSource.ref.path``."""
    return Path(os.path.abspath(path))


def _check_file(path: str | os.PathLike[str]) -> ProbeError | None:
    """The file checks of :meth:`Prober.probe` (missing, not a file), plus a real open, because
    ``stat()`` succeeds on a file without read permission."""
    file = _absolute(path)
    try:
        stat = os.stat(file)
    except FileNotFoundError:
        return ProbeError(file, ProbeErrorKind.NOT_FOUND, "The file does not exist.")
    except OSError as exc:
        return ProbeError(file, ProbeErrorKind.UNREADABLE, "The file cannot be read.", str(exc))
    if not S_ISREG(stat.st_mode):
        return ProbeError(file, ProbeErrorKind.NOT_A_FILE, "The path is not a file.")
    try:  # stat() works without read permission; open() tells
        with open(file, "rb"):
            pass
    except OSError as exc:
        return ProbeError(file, ProbeErrorKind.UNREADABLE, "The file cannot be read.", str(exc))
    return None


def _tool_error(path: Path, info: ToolInfo) -> ProbeError:
    return ProbeError(
        path,
        ProbeErrorKind.TOOL_FAILED,
        f"ffprobe cannot be used ({info.status.value}).",
        info.reason,
    )


# --------------------------------------------------------------------------- settings

#: Called after a settings change took effect: ``(old, new)``.
SettingsListener = Callable[[AppSettings, AppSettings], None]

#: For annotations inside ``PresetService``, whose ``list`` method hides the builtin there.
_FieldChanges = list[FieldChange]

_PATCH_ADAPTER: TypeAdapter[list[JsonPatchOp]] = TypeAdapter(list[JsonPatchOp])


class SettingsService:
    """The application settings (C-9): ``<config>/settings.json`` through
    :class:`~reframe.settings.SettingsStore`.

    :meth:`get` is the one settings getter of every service (``Reframe.settings_snapshot``).
    :meth:`update` applies a change, saves it and tells the facade, which re-runs tool
    discovery when a tool path changed and encoder detection when ``encoders.hardware_tests``
    or ``encoders.vaapi_device`` changed. :attr:`problems` keeps the ``app.warning`` events of
    the start-up load (a damaged, newer or unreadable file), which were published before any
    UI could subscribe.
    """

    def __init__(
        self,
        store: SettingsStore,
        *,
        initial: AppSettings | None = None,
        on_change: SettingsListener | None = None,
    ) -> None:
        self._store = store
        self._settings = initial.model_copy(deep=True) if initial is not None else store.load()
        self._on_change = on_change
        self._lock = asyncio.Lock()

    @property
    def path(self) -> Path:
        """``<config>/settings.json``."""
        return self._store.path

    @property
    def problems(self) -> list[AppWarningEvent]:
        """Warnings of the start-up load and of failed saves (also published as events)."""
        return self._store.problems

    @property
    def read_only(self) -> bool:
        """The file is newer than this Reframe or unreadable: changes are not saved."""
        return self._store.read_only

    def get(self) -> AppSettings:
        """The current settings (a copy)."""
        return self._settings.model_copy(deep=True)

    async def update(
        self, change: AppSettings | Sequence[JsonPatchOp | Mapping[str, object]]
    ) -> SettingsUpdate:
        """Replace the settings (an :class:`AppSettings`) or change them with a JSON patch
        (RFC 6902, as the ``target="settings"`` fixes carry: ``[{"op": "replace", "path":
        "/queue/parallel_jobs", "value": 2}]``).

        An invalid change is rejected (``issues``; nothing changes). A valid one takes effect
        at once; when it cannot be saved, ``warnings`` says why (``saved`` is ``False``).
        """
        async with self._lock:
            old = self._settings
            new = self._apply(old, change)
            if isinstance(new, ValidationIssue):
                return SettingsUpdate(settings=old.model_copy(deep=True), issues=[new])
            changes = diff_documents(old.model_dump(mode="json"), new.model_dump(mode="json"))
            if not changes:
                return SettingsUpdate(settings=new.model_copy(deep=True), saved=False)
            warning = await asyncio.to_thread(self._store.write, new)
            self._settings = new
            if self._on_change is not None:
                self._on_change(old, new)
            return SettingsUpdate(
                settings=new.model_copy(deep=True),
                changes=changes,
                saved=warning is None,
                warnings=[] if warning is None else [warning],
            )

    @staticmethod
    def _apply(
        current: AppSettings, change: AppSettings | Sequence[JsonPatchOp | Mapping[str, object]]
    ) -> AppSettings | ValidationIssue:
        if isinstance(change, AppSettings):
            return change.model_copy(deep=True)
        try:
            patch = _PATCH_ADAPTER.validate_python(
                [
                    op.model_dump(by_alias=True) if not isinstance(op, Mapping) else op
                    for op in change
                ]
            )
            data = apply_patch(current.model_dump(mode="json"), patch)
            return AppSettings.model_validate(data)
        except ValidationError as exc:
            message = validation_detail(exc)
            path = ".".join(str(part) for part in exc.errors()[0]["loc"]) if exc.errors() else ""
        except JsonPatchError as exc:
            message, path = str(exc), ""
        return ValidationIssue(
            severity=Severity.ERROR,
            code="settings.invalid",
            path=path,
            message=f"The settings change is not valid: {message}",
        )


# --------------------------------------------------------------------------- presets


class PresetService:
    """Built-in and user presets (C-9) through :class:`~reframe.presets.PresetStore`.

    Reading is synchronous (the file is read once, at the first use). Changes are async: the
    file is written in a worker thread. Expected failures (a name clash, a built-in that
    cannot change, a file that cannot be written) come back as a
    :class:`~reframe.models.ValidationIssue`, never as an exception.
    """

    def __init__(self, store: PresetStore) -> None:
        self._store = store

    @property
    def store(self) -> PresetStore:
        return self._store

    @property
    def problems(self) -> list[AppWarningEvent]:
        """Warnings of loading ``presets.json`` and of failed writes (also published)."""
        return self._store.problems

    def list(self) -> list[Preset]:
        """Built-ins first (in their order), then the user presets."""
        return self._store.list()

    def get(self, preset_id: str) -> Preset | None:
        return self._store.get(preset_id)

    def find(self, name_or_id: str) -> Preset | None:
        """By id, else by name without case (user presets first)."""
        return self._store.find(name_or_id)

    def default(self) -> Preset:
        return self._store.default()

    def export(self, ids: Sequence[str] | None = None) -> PresetFile:
        return self._store.export(ids)

    def diff(self, template: JobTemplate, preset: Preset | str) -> _FieldChanges | None:
        """What ``template`` changes against ``preset`` (a preset or its id); ``None`` when
        the id is unknown."""
        if isinstance(preset, str):
            found = self._store.get(preset)
            if found is None:
                return None
            preset = found
        return diff(template, preset)

    async def create(
        self, template: JobTemplate, name: str, *, category: str = "Custom", description: str = ""
    ) -> Preset | ValidationIssue:
        return await asyncio.to_thread(
            self._store.create, template, name, category=category, description=description
        )

    async def save(self, preset: Preset) -> Preset | ValidationIssue:
        return await asyncio.to_thread(self._store.save, preset)

    async def rename(self, preset_id: str, name: str) -> Preset | ValidationIssue:
        return await asyncio.to_thread(self._store.rename, preset_id, name)

    async def delete(self, preset_id: str) -> Preset | ValidationIssue:
        return await asyncio.to_thread(self._store.delete, preset_id)

    async def duplicate(self, preset_id: str, name: str | None = None) -> Preset | ValidationIssue:
        return await asyncio.to_thread(self._store.duplicate, preset_id, name)

    async def set_default(self, preset_id: str | None) -> Preset | ValidationIssue:
        return await asyncio.to_thread(self._store.set_default, preset_id)

    async def import_(
        self, file: PresetFile | Mapping[str, object], on_conflict: ConflictPolicy = "rename"
    ) -> ImportResult:
        return await asyncio.to_thread(self._store.import_, file, on_conflict)


# --------------------------------------------------------------------------- facade


class Reframe:
    """The Reframe core as one object (C-15). Create it with ``await Reframe.create()``.

    Services that exist now:

    - :attr:`events` — the async event bus (``tools.changed``, ``capabilities.changed``,
      ``task.progress``, ``task.done``).
    - :attr:`tools` — :class:`ToolsService`: tool status, versions, re-scan (C-1).
    - :attr:`capabilities` — :class:`~reframe.capabilities.CapabilityService`: encoder
      statuses (``snapshot`` never waits, ``wait``, ``rescan``, ``closest_available``),
      detected in the background with a cache under ``<cache dir>/capabilities`` (C-4).
    - :attr:`sources` — :class:`SourceService`: ``probe``, ``probe_folder``, ``get`` (C-3).
    - :attr:`tasks` — the background task manager (``get``, ``list``, ``cancel``, ``wait``,
      ``value``) for the tasks that the services start.
    - :attr:`settings` — :class:`SettingsService`: ``get``, ``update``, ``problems`` (C-9).
    - :attr:`presets` — :class:`PresetService`: built-in and user presets, the default,
      export / import, ``diff`` (C-9).
    - :attr:`jobs` — :class:`~reframe.jobs.JobService`: ``draft`` a job from a source and a
      preset, ``validate`` it (waiting a bounded time for encoder detection), ``plan`` it,
      ``name`` a path, ``media_files`` of files and folders (C-15).
    - :attr:`queue` — :class:`~reframe.queue.QueueService`: the encode queue (``add``,
      ``list``, ``start``, ``pause``, ``resume``, ``cancel``, ``retry``, ``wait``, logs),
      saved in ``<data dir>/queue.sqlite3`` (C-11).

    The other M2 steps add ``batch`` (C-12).

    **Settings.** ``<config>/settings.json`` is read in :meth:`create` (a damaged, newer or
    unreadable file gives an ``app.warning``, kept in ``settings.problems``). Every service
    reads the settings through :meth:`settings_snapshot` (one :data:`SettingsGetter`). A
    change through ``settings.update`` takes effect at once; a changed tool path re-runs tool
    discovery, and a changed ``encoders.hardware_tests`` or ``encoders.vaapi_device`` re-runs
    encoder detection, both in the background.

    **Queue.** The queue opens ``<data dir>/queue.sqlite3`` at its first use, not in
    :meth:`create` (decision 0027): the process that takes the lock ``queue.lock`` owns the
    saved queue and restores it (jobs that were running become ``interrupted``); another
    process gets a private queue in memory and an ``app.warning``. The queue is not started
    (``queue.start()``). :meth:`close` stops the running jobs first (they end
    ``interrupted``, their ``.part`` files removed) and frees the lock.

    Use ``async with await Reframe.create() as app:`` or call :meth:`close` at the end:
    it stops the queue, cancels running tasks, probes and the encoder detection (killing their
    processes) and closes the event bus.
    """

    events: EventBus
    tasks: TaskManager
    tools: ToolsService
    capabilities: CapabilityService
    sources: SourceService
    settings: SettingsService
    presets: PresetService
    jobs: JobService
    queue: QueueService

    def __init__(
        self,
        *,
        config_dir: Path,
        data_dir: Path,
        cache_dir: Path,
        settings: AppSettings | None = None,
    ) -> None:
        """Wire the services without starting anything. Use :meth:`create` instead.

        ``settings``: the settings to start with instead of reading ``settings.json`` (they
        are saved there at the first change).
        """
        self.config_dir = config_dir
        self.data_dir = data_dir
        self.cache_dir = cache_dir
        self._closed = False
        self._reactions: set[asyncio.Task[None]] = set()
        self.events = EventBus()
        self.settings = SettingsService(
            SettingsStore(config_dir, self.events),
            initial=settings,
            on_change=self._settings_changed,
        )
        self.presets = PresetService(PresetStore(config_dir, self.events))
        self.tasks = TaskManager(self.events)
        roots = paths.bundled_tool_roots(environ={**os.environ, paths.DATA_DIR_ENV: str(data_dir)})
        self.tools = ToolsService(self.events, self.settings_snapshot, bundled_roots=roots)
        self.capabilities = CapabilityService(
            self.events, self.tools, self.settings_snapshot, cache_dir=cache_dir / "capabilities"
        )
        self.sources = SourceService(
            self.tools,
            self.tasks,
            ProbeCache(cache_dir / "probe"),
            is_closed=lambda: self._closed,
        )
        self.jobs = JobService(
            sources=self.sources,
            presets=self.presets,
            tools=self.tools,
            capabilities=self.capabilities,
            settings=self.settings_snapshot,
        )

        presets = self.presets

        def preset_naming(job: JobSettings) -> NamingOptions | None:
            """The naming options of the job's preset (``None``: Settings → Output)."""
            preset = presets.get(job.preset_id) if job.preset_id is not None else None
            return preset.naming if preset is not None else None

        self.queue = QueueService(
            self.events,
            self.settings_snapshot,
            data_dir=data_dir,
            tools=self.tools,
            capabilities=self.capabilities,
            sources=self.sources,
            naming=preset_naming,
        )

    @classmethod
    async def create(
        cls,
        config_dir: Path | None = None,
        data_dir: Path | None = None,
        *,
        cache_dir: Path | None = None,
    ) -> Reframe:
        """Create the facade and start tool discovery and encoder detection in the
        background. Returns at once. The saved queue is not opened here: the queue opens it at
        its first use (decision 0027).

        The folders default to :mod:`reframe.paths` (``REFRAME_CONFIG_DIR``,
        ``REFRAME_DATA_DIR``, ``REFRAME_CACHE_DIR`` or the platform folders). ``data_dir``
        also decides where the fetched tools are looked for (``<data dir>/tools``). Nothing is
        created on disk until a service writes there.
        """
        config = Path(config_dir) if config_dir is not None else paths.config_dir()
        data = Path(data_dir) if data_dir is not None else paths.data_dir()
        cache = Path(cache_dir) if cache_dir is not None else paths.cache_dir()
        settings = cls._load_settings(config)
        app = cls(config_dir=config, data_dir=data, cache_dir=cache, settings=settings)
        app.tools.start()
        app.capabilities.start()
        return app

    @staticmethod
    def _load_settings(config_dir: Path) -> AppSettings | None:
        """Settings to start with instead of ``<config>/settings.json`` (a test hook).
        ``None``, the default: the settings store reads the file."""
        del config_dir
        return None

    def settings_snapshot(self) -> AppSettings:
        """The current settings (a copy). The one place where the services read them."""
        return self.settings.get()

    def _settings_changed(self, old: AppSettings, new: AppSettings) -> None:
        """React to a settings change: tool discovery for tool paths, encoder detection for
        the hardware-test settings. Runs in the background; :meth:`close` cancels it."""
        tools = old.tools.model_dump(mode="json") != new.tools.model_dump(mode="json")
        encoders = (old.encoders.hardware_tests, old.encoders.vaapi_device) != (
            new.encoders.hardware_tests,
            new.encoders.vaapi_device,
        )
        if self._closed or not (tools or encoders):
            return
        task = asyncio.get_running_loop().create_task(
            self._react(tools=tools, encoders=encoders), name="reframe-settings-changed"
        )
        self._reactions.add(task)
        task.add_done_callback(self._reactions.discard)

    async def _react(self, *, tools: bool, encoders: bool) -> None:
        try:
            if tools:
                await self.tools.rescan()
            if encoders:
                await self.capabilities.rescan()
        except ReframeClosedError:
            pass
        except Exception:  # pragma: no cover - a bug in a service; never kill the loop
            log.exception("reacting to a settings change failed")

    @property
    def closed(self) -> bool:
        return self._closed

    async def close(self) -> None:
        """Stop everything: the queue (running jobs end ``interrupted``, the store is
        flushed), tool discovery, encoder detection, running tasks and probes (their process
        trees are killed), then close the event bus. Safe to call more than once."""
        if self._closed:
            return
        self._closed = True
        try:
            reactions = [task for task in self._reactions if not task.done()]
            for task in reactions:
                task.cancel()
            if reactions:
                await asyncio.wait(reactions)
            await self.queue.close()  # first: its jobs use the tools, sources and capabilities
            await self.tasks.close()  # first: a task may be waiting for tool discovery
            await self.capabilities.close()  # kills test encodes; may wait for discovery too
            await self.tools.close()  # a probe() waiting for discovery returns "cancelled"
            await self.sources.close()
        finally:
            self.events.close()

    async def __aenter__(self) -> Reframe:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()
