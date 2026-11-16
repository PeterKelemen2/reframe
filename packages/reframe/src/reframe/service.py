"""The ``Reframe`` facade. The UIs use this object and ``reframe.models``, never the internal
modules. Expected failures are values, never exceptions: :meth:`SourceService.probe` returns a
:class:`ProbeError` for a missing file, a file that is not media, or an ffprobe that cannot be
used, and :meth:`ToolsService.status` returns a :class:`~reframe.models.ToolSet` whose entries
say why a tool is missing. Using the facade after :meth:`Reframe.close` raises
:class:`ReframeClosedError`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from pathlib import Path
from types import TracebackType

from pydantic import TypeAdapter, ValidationError

from reframe import analysis, applog, paths, preview
from reframe.analysis.subtitlefile import inspect_subtitle_file
from reframe.batch.service import BatchService
from reframe.capabilities import CapabilityService
from reframe.definitions import load_definitions
from reframe.diagnostics import build_report
from reframe.errors import ReframeClosedError
from reframe.events import EventBus
from reframe.jobs import JobService
from reframe.jsonpatch import JsonPatchError, apply_patch
from reframe.mediatask import MediaTaskContext
from reframe.models.events import AppWarningEvent, ToolsChangedEvent
from reframe.models.issues import JsonPatchOp, Severity, ValidationIssue
from reframe.models.job import JobSettings
from reframe.models.media import MediaSource, SubtitleFileInfo
from reframe.models.naming import NamingOptions
from reframe.models.preset import FieldChange, Preset, PresetFile
from reframe.models.settings import AppSettings, LogLevel
from reframe.models.tasks import TaskInfo
from reframe.models.template import JobTemplate
from reframe.models.tools import ToolInfo, ToolSet
from reframe.platform.power import PowerService, create_power_service
from reframe.presets import (
    ConflictPolicy,
    ImportResult,
    PresetExport,
    PresetStore,
    diff,
    diff_documents,
)
from reframe.probe import (
    ProbeCache,
    ProbeError,
    ProbeErrorKind,
    Prober,
    ProbeTool,
)
from reframe.probe.cache import CacheKey
from reframe.probe.prober import stat_regular
from reframe.queue import QueueService
from reframe.settings import MAX_DEPTH, SettingsStore, SettingsUpdate, too_deep, validation_detail
from reframe.tasks import TaskManager
from reframe.tools import CancelToken, discover_tools
from reframe.tools.fetch import start_fetch
from reframe.validation.fs import has_nul

__all__ = [
    "PROBE_CONCURRENCY",
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
]

log = logging.getLogger(__name__)

#: Returns the current settings. Every service reads them through this one callable.
SettingsGetter = Callable[[], AppSettings]

#: Sources that :meth:`SourceService.get` keeps in memory (the disk cache keeps all).
KNOWN_SOURCES = 1024
#: Seconds that :meth:`Reframe.close` waits for running probes to end after cancelling them.
CLOSE_TIMEOUT = 10.0
#: ffprobe runs at once in :meth:`SourceService.probe_many`.
PROBE_CONCURRENCY = 4


class ToolsService:
    """Which external tools Reframe uses, and re-scans.

    Discovery runs in the background: :meth:`start` returns at once, :meth:`status` waits for
    it, :attr:`current` does not. Every finished discovery publishes ``tools.changed``.
    :meth:`fetch` downloads the pinned FFmpeg build into ``<data dir>/tools/ffmpeg``.
    """

    def __init__(
        self,
        events: EventBus,
        settings: SettingsGetter,
        *,
        bundled_roots: Sequence[Path],
        tasks: TaskManager,
        data_dir: Path,
    ) -> None:
        self._events = events
        self._settings = settings
        self._bundled_roots = list(bundled_roots)
        self._tasks = tasks
        self._data_dir = data_dir
        self._task: asyncio.Task[ToolSet] | None = None
        self._current: ToolSet | None = None
        self._closed = False

    @property
    def current(self) -> ToolSet | None:
        """The result of the last finished discovery; ``None`` until the first one ends."""
        return self._current

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

    async def rescan(self) -> ToolSet:
        """Run discovery again. A discovery that is still running is cancelled first: its
        result would be stale."""
        if self._closed:
            raise ReframeClosedError
        old = self._task
        if old is not None and not old.done():
            old.cancel()
        self._start()
        return await self.status()

    def fetch(
        self,
        *,
        build: str = "default",
        platform: str | None = None,
        manifest: Path | None = None,
    ) -> TaskInfo:
        """Download the FFmpeg build ``build`` of the manifest for ``platform`` (``None``: this
        one), check it, install it as the bundled build in ``<data dir>/tools/ffmpeg`` and run
        discovery again. Returns at once; the task result is
        :class:`~reframe.models.ToolFetchResult`. ``manifest``: another manifest file."""
        if self._closed:
            raise ReframeClosedError
        return start_fetch(
            self._tasks,
            data_dir=self._data_dir,
            rescan=self.rescan,
            build=build,
            platform=platform,
            manifest=manifest,
        )

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
        tools = await discover_tools(self._settings().tools, bundled_roots=self._bundled_roots)
        self._current = tools
        self._events.publish(ToolsChangedEvent(tools=tools))
        return tools


class SourceService:
    """Probing source files: one file, many files and the known sources. Also the
    analysis and preview tasks of a source: bitrate and subtitle scans, loudness, frames and
    crop detection.

    Results are cached in memory and on disk (``<cache dir>/probe``), keyed by path, size,
    mtime and the ffprobe build, so probing an unchanged file again is cheap. Measured values
    (a bitrate scan, subtitle event counts) are stored into the known source and the cache
    (:meth:`update`, :meth:`store`; one file at a time).

    The analysis and preview methods need :attr:`media`, which the facade sets. They start a
    background task and return its :class:`~reframe.models.TaskInfo` at once.
    """

    media: MediaTaskContext | None = None
    """What the analysis and preview tasks need from the facade (set by :class:`Reframe`)."""

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
        self._locks: dict[Path, tuple[asyncio.Lock, list[int]]] = {}
        """Per file: the lock of :meth:`store` / :meth:`update` and how many wait for it."""
        self._tokens: list[CancelToken] = []
        """One entry per running call: :meth:`probe_many` hands one token to many calls."""
        self._active = 0
        self._idle = asyncio.Event()
        self._idle.set()

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
        ``TOOL_FAILED``, a file that is not media is ``FAILED``.
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
            # File checks first: an unreadable file is reported as such, not as an ffprobe failure.
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

    async def inspect_subtitle(
        self, path: str | os.PathLike[str], *, cancel: CancelToken | None = None
    ) -> SubtitleFileInfo | ProbeError:
        """An external subtitle file's format, event count and character encoding, before it is
        added to a job. Never raises for problems with the file or the tool: a missing file is
        ``NOT_FOUND``, a file that is not a subtitle file a job can take ``FAILED``."""
        self._check_open()
        token = cancel or CancelToken()
        self._enter(token)
        try:
            try:
                prober = await self._get_prober()
            except ReframeClosedError:
                return ProbeError(
                    _absolute(path), ProbeErrorKind.CANCELLED, "Reframe is shutting down."
                )
            problem = await asyncio.to_thread(_check_file, path)
            if problem is not None:
                return problem
            if isinstance(prober, ToolInfo):
                return _tool_error(_absolute(path), prober)
            return await inspect_subtitle_file(_absolute(path), prober.tool, cancel=token)
        finally:
            self._leave(token)

    async def probe_many(
        self,
        files: Sequence[str | os.PathLike[str]],
        *,
        concurrency: int = PROBE_CONCURRENCY,
        cancel: CancelToken | None = None,
        on_progress: Callable[[int, int], object] | None = None,
    ) -> list[MediaSource | ProbeError]:
        """:meth:`probe` each file, ``concurrency`` at a time; the results in the order of
        ``files``. After ``cancel`` no new ffprobe starts: the rest are ``CANCELLED`` errors.
        ``on_progress(done, total)`` is called after each file."""
        if concurrency < 1:
            raise ValueError(f"concurrency must be at least 1, got {concurrency}")
        gate = asyncio.Semaphore(concurrency)
        results: list[MediaSource | ProbeError | None] = [None] * len(files)
        done = 0

        async def one(i: int, file: str | os.PathLike[str]) -> None:
            nonlocal done
            async with gate:
                if cancel is not None and cancel.cancelled:
                    results[i] = ProbeError(
                        _absolute(file), ProbeErrorKind.CANCELLED, "The probe was cancelled."
                    )
                else:
                    results[i] = await self.probe(file, cancel=cancel)
            done += 1
            if on_progress is not None:
                on_progress(done, len(files))

        # A TaskGroup, not gather(): a cancelled gather() returns at its first child's end, and
        # the other ffprobe kills can then be dropped when the loop stops.
        async with asyncio.TaskGroup() as group:
            for i, file in enumerate(files):
                group.create_task(one(i, file))
        return [result for result in results if result is not None]

    async def get(self, path: str | os.PathLike[str]) -> MediaSource | None:
        """The probed source of ``path`` if it is known and the file has not changed since.

        Never runs ffprobe. Looks in memory, then (once tool discovery has finished) in the
        disk cache.
        """
        self._check_open()
        file = _absolute(path)
        if has_nul(file):  # no file can have this name; os.stat would raise ValueError
            return None
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

    async def store(self, source: MediaSource) -> None:
        """Keep ``source`` (with measured values: a bitrate scan, subtitle event counts) as the
        known source of its file, in memory and in the probe cache, so that :meth:`probe` and
        :meth:`get` return it. Nothing is stored when the file changed since ``source`` was
        probed (its fingerprint no longer matches). Waits for an :meth:`update` of the same
        file that is running."""
        self._check_open()
        async with self._file_lock(Path(source.ref.path)):
            await self._store(source)

    async def update(
        self, source: MediaSource, change: Callable[[MediaSource], MediaSource]
    ) -> None:
        """Keep ``change(latest)`` like :meth:`store`: ``latest`` is the known source of
        ``source``'s file now (:meth:`get`; ``source`` itself when none is known). This is
        how a scan stores what it measured: it applies only its own values to what other
        scans have stored meanwhile (two scans of one file run at the same time, and each
        probed the file when it started).

        ``source`` is the version the values were measured on: when the known source is a
        newer version of the file, or the file has changed, nothing is stored. The stores and
        updates of one file run one at a time."""
        self._check_open()
        file = Path(source.ref.path)
        async with self._file_lock(file):
            latest = await self.get(file)
            if latest is None:
                base = source
            elif _same_version(latest, source):
                base = latest
            else:
                return  # the file has changed since the values were measured
            await self._store(change(base))

    @contextlib.asynccontextmanager
    async def _file_lock(self, file: Path) -> AsyncIterator[None]:
        """One :meth:`store` / :meth:`update` of ``file`` at a time; the lock is dropped when
        nobody holds or waits for it."""
        entry = self._locks.get(file)
        if entry is None:
            entry = self._locks[file] = (asyncio.Lock(), [0])
        lock, users = entry
        users[0] += 1
        try:
            async with lock:
                yield
        finally:
            users[0] -= 1
            if users[0] == 0:
                del self._locks[file]

    async def _store(self, source: MediaSource) -> None:
        file = Path(source.ref.path)
        if has_nul(file):  # a NUL character in the path: os.stat would raise ValueError
            return
        try:
            stat = await asyncio.to_thread(os.stat, file)
        except OSError:
            return
        fingerprint = source.ref.fingerprint
        if (
            fingerprint is None
            or fingerprint.size != stat.st_size
            or fingerprint.mtime != stat.st_mtime
        ):
            return
        self._remember(source)
        prober = self._prober_now()
        if prober is not None and prober.cache is not None:
            await asyncio.to_thread(
                prober.cache.put,
                CacheKey.for_file(file, stat),
                source,
                tool=prober.tool.identity(),
                options=prober.cache_options(),
            )

    def bitrate_scan(self, path: str | os.PathLike[str], stream_index: int) -> TaskInfo:
        """Measure one stream's bit rate from its packet sizes. The task result is
        :class:`~reframe.models.BitrateScan`. When it is done, the bit rate is stored with the
        source as measured (:meth:`store`)."""
        return analysis.start_bitrate_scan(self._media(), _absolute(path), stream_index)

    def subtitle_scan(
        self, path: str | os.PathLike[str], stream_indexes: Sequence[int] | None = None
    ) -> TaskInfo:
        """Count the events of the subtitle tracks (all when ``stream_indexes`` is ``None``)
        and the forced events of PGS and VobSub tracks. The task result is
        :class:`~reframe.models.SubtitleScan`; the counts are stored (:meth:`store`)."""
        return analysis.start_subtitle_scan(self._media(), _absolute(path), stream_indexes)

    def loudness_scan(
        self,
        path: str | os.PathLike[str],
        stream_index: int,
        *,
        start: float | None = None,
        duration: float | None = None,
    ) -> TaskInfo:
        """Measure an audio track's loudness (EBU R128, ``loudnorm``): the whole track, or
        ``duration`` seconds from ``start``. The task result is
        :class:`~reframe.models.LoudnessMeasurement`."""
        return analysis.start_loudness_scan(
            self._media(), _absolute(path), stream_index, start=start, duration=duration
        )

    def frames(
        self,
        path: str | os.PathLike[str],
        *,
        count: int | None = None,
        timestamps: Sequence[float] | None = None,
        job: JobSettings | None = None,
    ) -> TaskInfo:
        """PNG frames of the source, at ``timestamps``, else ``count`` evenly spaced ones
        (``None``: the default from the settings). With ``job``, also the output frames (crop,
        scale, filters). The task result is :class:`~reframe.models.FrameSet`. Cached on disk.
        """
        return preview.start_frames(
            self._media(), _absolute(path), count=count, timestamps=timestamps, job=job
        )

    async def frame(self, key: str) -> Path | None:
        """The cached PNG of a :class:`~reframe.models.PreviewFrame` key, else ``None``."""
        return await asyncio.to_thread(preview.frame_path, self._media(), key)

    async def preview_cache_size(self) -> int:
        """Bytes of cached preview frames and clips."""
        return await asyncio.to_thread(preview.cache_size, self._media())

    async def clear_preview_cache(self) -> int:
        """Remove every cached preview frame and clip; return the bytes freed. Temporary files
        of running tasks stay."""
        return await asyncio.to_thread(preview.clear_cache, self._media())

    def cropdetect(self, path: str | os.PathLike[str], *, count: int | None = None) -> TaskInfo:
        """Crop detection on the sample frames. The task result is
        :class:`~reframe.models.CropDetection`: the automatic and the conservative crop."""
        return preview.start_cropdetect(self._media(), _absolute(path), count=count)

    async def close(self, timeout: float = CLOSE_TIMEOUT) -> None:  # noqa: ASYNC109
        """Cancel running probes (their processes are killed) and wait for them to end."""
        for token in set(self._tokens):
            token.cancel()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._idle.wait(), timeout)

    def _check_open(self) -> None:
        if self._is_closed():
            raise ReframeClosedError

    def _media(self) -> MediaTaskContext:
        self._check_open()
        if self.media is None:
            raise RuntimeError("SourceService.media is not set (the facade sets it)")
        return self.media

    def _remember(self, source: MediaSource) -> None:
        self._known[source.ref.path] = source
        self._known.move_to_end(source.ref.path)
        while len(self._known) > KNOWN_SOURCES:
            self._known.popitem(last=False)

    def _enter(self, token: CancelToken) -> None:
        self._tokens.append(token)
        self._active += 1
        self._idle.clear()

    def _leave(self, token: CancelToken) -> None:
        self._tokens.remove(token)
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
        if not info.usable:
            return info
        tool = ProbeTool.of(info)
        if self._prober is None or self._prober.tool != tool:
            self._prober = Prober(tool, cache=self._cache)
        return self._prober


def _absolute(path: str | os.PathLike[str]) -> Path:
    """The absolute path, as :class:`Prober` stores it in ``MediaSource.ref.path``."""
    return Path(os.path.abspath(path))


def _same_version(a: MediaSource, b: MediaSource) -> bool:
    fa, fb = a.ref.fingerprint, b.ref.fingerprint
    return fa is not None and fb is not None and (fa.size, fa.mtime) == (fb.size, fb.mtime)


#: The ``ProbeError`` message of a path with a NUL character.
_NUL_PATH = "The path has a NUL character, which no file system allows: no file can have this name."


def _check_file(path: str | os.PathLike[str]) -> ProbeError | None:
    """The file checks of :func:`stat_regular` (missing, unreadable, not a file), plus a real
    open. A path with a NUL character is ``NOT_FOUND``: ``os.stat`` raises ``ValueError`` for
    it, not ``OSError``."""
    file = _absolute(path)
    if has_nul(file):
        return ProbeError(file, ProbeErrorKind.NOT_FOUND, _NUL_PATH)
    stat = stat_regular(file)
    if isinstance(stat, ProbeError):
        return stat
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


#: Called after a settings change took effect: ``(old, new)``.
SettingsListener = Callable[[AppSettings, AppSettings], None]

#: For annotations inside ``PresetService``, whose ``list`` method hides the builtin there.
_FieldChanges = list[FieldChange]

_PATCH_ADAPTER: TypeAdapter[list[JsonPatchOp]] = TypeAdapter(list[JsonPatchOp])


class SettingsService:
    """The application settings: ``<config>/settings.json`` through
    :class:`~reframe.settings.SettingsStore`.

    :meth:`get` is the one settings getter of every service (``Reframe.settings_snapshot``).
    :meth:`update` applies and saves a change; the facade then re-runs the discoveries that the
    change affects (:meth:`Reframe._settings_changed`). :attr:`problems` keeps the
    ``app.warning`` events of the start-up load (a damaged, newer or unreadable file), which
    were published before any UI could subscribe.
    """

    def __init__(
        self,
        store: SettingsStore,
        *,
        on_change: SettingsListener | None = None,
    ) -> None:
        self._store = store
        self._settings = store.load()
        self._on_change = on_change
        self._lock = asyncio.Lock()

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
        self,
        change: AppSettings | Sequence[JsonPatchOp | Mapping[str, object]],
        *,
        check: Callable[[AppSettings, AppSettings], None] | None = None,
    ) -> SettingsUpdate:
        """Replace the settings (an :class:`AppSettings`), or change them with a JSON patch
        (RFC 6902).

        An invalid change is rejected: nothing changes and ``issues`` says why. That is a value
        the model rejects, settings nested more than ``MAX_DEPTH`` levels deep, or a change of
        ``schema_version``: Reframe sets it, and a newer number would make the next start treat
        the file as newer and use the defaults. A valid change takes effect at once; when it
        cannot be saved, ``warnings`` says why (``saved`` is ``False``).

        ``check(old, new)`` runs under the same lock, on the settings the change was applied
        to, before anything is written: an exception from it propagates and nothing changes.
        """
        async with self._lock:
            old = self._settings
            new = self._apply(old, change)
            if isinstance(new, ValidationIssue):
                return SettingsUpdate(settings=old.model_copy(deep=True), issues=[new])
            if check is not None:
                check(old.model_copy(deep=True), new.model_copy(deep=True))
            if new.schema_version != old.schema_version:
                issue = ValidationIssue(
                    severity=Severity.ERROR,
                    code="settings.schema_version",
                    path="schema_version",
                    message="The settings schema version is set by Reframe and cannot be "
                    f"changed (it is {old.schema_version}).",
                )
                return SettingsUpdate(settings=old.model_copy(deep=True), issues=[issue])
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
        nested = f"the settings would be nested more than {MAX_DEPTH} levels deep"
        message, path = nested, ""
        try:
            if isinstance(change, AppSettings):
                if not too_deep(change.model_dump(mode="json")):
                    return change.model_copy(deep=True)
            else:
                ops = [
                    op.model_dump(by_alias=True) if not isinstance(op, Mapping) else op
                    for op in change
                ]
                if not too_deep(ops, MAX_DEPTH + 2):  # the list and the op add two levels
                    patch = _PATCH_ADAPTER.validate_python(ops)
                    data = apply_patch(current.model_dump(mode="json"), patch)
                    if not too_deep(data):
                        return AppSettings.model_validate(data)
        except ValidationError as exc:
            message = validation_detail(exc)
            path = ".".join(str(part) for part in exc.errors()[0]["loc"]) if exc.errors() else ""
        except JsonPatchError as exc:
            message, path = str(exc), ""
        except (RecursionError, ValueError):  # Pydantic's dump of a value nested far too deep
            pass
        return ValidationIssue(
            severity=Severity.ERROR,
            code="settings.invalid",
            path=path,
            message=f"The settings change is not valid: {message}",
        )


class PresetService:
    """Built-in and user presets through :class:`~reframe.presets.PresetStore`.

    Reading is synchronous (the file is read once, at the first use). Changes are async: the
    file is written in a worker thread. Expected failures (a name clash, a built-in that
    cannot change, a file that cannot be written) come back as a
    :class:`~reframe.models.ValidationIssue`, never as an exception.
    """

    def __init__(self, store: PresetStore) -> None:
        self._store = store

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

    def export(self, ids: Sequence[str] | None = None) -> PresetExport:
        """The presets (``None``: every user preset). ``document()`` is the export file;
        presets of a newer Reframe are in it unchanged, each with a warning in ``issues``."""
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

    async def delete(self, preset_id: str) -> Preset | ValidationIssue:
        return await asyncio.to_thread(self._store.delete, preset_id)

    async def set_default(self, preset_id: str | None) -> Preset | ValidationIssue:
        return await asyncio.to_thread(self._store.set_default, preset_id)

    async def import_(
        self,
        file: PresetFile | PresetExport | Mapping[str, object],
        on_conflict: ConflictPolicy = "rename",
    ) -> ImportResult:
        return await asyncio.to_thread(self._store.import_, file, on_conflict)


class Reframe:
    """The Reframe core as one object. Create it with ``await Reframe.create()``, then use it
    as an async context manager or call :meth:`close` at the end.

    **Settings.** ``<config>/settings.json`` is read in :meth:`create`; a damaged, newer or
    unreadable file gives an ``app.warning``, kept in ``settings.problems``. Every service reads
    the settings through :meth:`settings_snapshot`. A change through ``settings.update`` takes
    effect at once, and the facade re-runs the tool discovery or encoder detection that it
    affects, in the background.

    **Queue.** The queue opens ``<data dir>/queue.sqlite3`` at its first use, not in
    :meth:`create`, so that a second command cannot interrupt a running encode. The process
    that takes the lock ``queue.lock`` owns the saved queue and restores it (jobs that were
    running become ``interrupted``); another process gets a private queue in memory and an
    ``app.warning``. The queue is not started (``queue.start()``). :meth:`close` stops the
    running jobs first (they end ``interrupted``, their ``.part`` files removed) and frees the
    lock.
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
    power: PowerService
    batch: BatchService

    def __init__(
        self,
        *,
        config_dir: Path,
        data_dir: Path,
        cache_dir: Path,
        on_log_level: Callable[[LogLevel], None] | None = None,
    ) -> None:
        """Wire the services without starting anything. Use :meth:`create` instead."""
        self.config_dir = config_dir
        self.data_dir = data_dir
        self.cache_dir = cache_dir
        self._closed = False
        self._reactions: set[asyncio.Task[None]] = set()
        self._on_log_level = on_log_level
        self.events = EventBus()
        self.settings = SettingsService(
            SettingsStore(config_dir, self.events),
            on_change=self._settings_changed,
        )
        self.presets = PresetService(PresetStore(config_dir, self.events))
        self.tasks = TaskManager(self.events)
        roots = paths.bundled_tool_roots(environ={**os.environ, paths.DATA_DIR_ENV: str(data_dir)})
        self.tools = ToolsService(
            self.events,
            self.settings_snapshot,
            bundled_roots=roots,
            tasks=self.tasks,
            data_dir=data_dir,
        )
        self.capabilities = CapabilityService(
            self.events, self.tools, self.settings_snapshot, cache_dir=cache_dir / "capabilities"
        )
        self.sources = SourceService(
            self.tools,
            self.tasks,
            ProbeCache(cache_dir / "probe"),
            is_closed=lambda: self._closed,
        )
        media = MediaTaskContext(
            tasks=self.tasks,
            tools=self.tools,
            sources=self.sources,
            capabilities=self.capabilities,
            settings=self.settings_snapshot,
            cache_dir=cache_dir,
            definitions=load_definitions,
        )
        self.sources.media = media
        self.jobs = JobService(
            sources=self.sources,
            presets=self.presets,
            tools=self.tools,
            capabilities=self.capabilities,
            settings=self.settings_snapshot,
            media=media,
        )
        self.power = create_power_service(self.events)
        self.batch = BatchService(
            sources=self.sources,
            presets=self.presets,
            jobs=self.jobs,
            settings=self.settings_snapshot,
        )

        presets = self.presets

        def preset_naming(job: JobSettings) -> NamingOptions | None:
            """The naming options of the job's preset (``None``: the output settings)."""
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
            power=self.power,
        )

    @classmethod
    async def create(
        cls,
        config_dir: Path | None = None,
        data_dir: Path | None = None,
        *,
        cache_dir: Path | None = None,
        on_log_level: Callable[[LogLevel], None] | None = None,
    ) -> Reframe:
        """Create the facade and start tool discovery and encoder detection in the background.
        Returns at once. The saved queue is not opened here: the queue opens it at its first use.

        The folders default to those of :mod:`reframe.paths`. ``data_dir`` also decides where
        the fetched tools are looked for (``<data dir>/tools``). Nothing is created on disk
        until a service writes there.

        ``on_log_level`` is called with the new level whenever a settings change sets another
        ``diagnostics.log_level``, before ``settings.update`` returns.
        """
        config = Path(config_dir) if config_dir is not None else paths.config_dir()
        data = Path(data_dir) if data_dir is not None else paths.data_dir()
        cache = Path(cache_dir) if cache_dir is not None else paths.cache_dir()
        app = cls(config_dir=config, data_dir=data, cache_dir=cache, on_log_level=on_log_level)
        app.tools.start()
        app.capabilities.start()
        return app

    def settings_snapshot(self) -> AppSettings:
        """The current settings (a copy). The one place where the services read them."""
        return self.settings.get()

    async def diagnostics(self, *, server: Mapping[str, str] | None = None) -> str:
        """The diagnostics report (:func:`reframe.diagnostics.build_report`); ``server``: the
        lines the server adds after the version. Waits for a running tool discovery, never for
        an encoder detection: the report says that one is running."""
        tools = await self.tools.status()
        return await asyncio.to_thread(
            build_report,
            tools=tools,
            encoders=self.capabilities.snapshot,
            settings=self.settings.get(),
            logs=applog.logs_dir(self.data_dir),
            server=server,
        )

    def _settings_changed(self, old: AppSettings, new: AppSettings) -> None:
        """React to a settings change: tool discovery for tool paths, encoder detection for
        the hardware-test settings (in the background; :meth:`close` cancels it), and a new
        log level at once."""
        if self._closed:
            return
        level = new.diagnostics.log_level
        if self._on_log_level is not None and level != old.diagnostics.log_level:
            self._on_log_level(level)
        tools = old.tools.model_dump(mode="json") != new.tools.model_dump(mode="json")
        encoders = (old.encoders.hardware_tests, old.encoders.vaapi_device) != (
            new.encoders.hardware_tests,
            new.encoders.vaapi_device,
        )
        if not (tools or encoders):
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
            await self.power.close()  # a when-done countdown never fires after close
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
