"""The queue test harness: the real queue with the fake ffmpeg and stand-in services."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import threading
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psutil
import pytest

from reframe.command import build_plan
from reframe.definitions import load_definitions
from reframe.events import EventBus
from reframe.metadata import header
from reframe.metadata.header import HeaderEditResult
from reframe.models import (
    AppSettings,
    AudioOutputTrack,
    CapabilitySnapshot,
    EncodePlan,
    EncoderState,
    EncoderStatus,
    Event,
    HeaderEdit,
    JobSettings,
    MediaSource,
    OutputSettings,
    QueueJob,
    SourceFingerprint,
    SourceRef,
    SubtitleOutputTrack,
    ToolInfo,
    ToolSet,
    ToolStatus,
    TrackMetadata,
)
from reframe.platform.sleep import SleepInhibitor
from reframe.probe import ProbeError, ProbeErrorKind, parse_ffprobe
from reframe.queue import QueueService
from reframe.queue.store import row_of
from reframe.tools import CancelToken
from reframe_testing import fake_tools as ft
from reframe_testing.waiting import wait_until

ROOT = Path(__file__).resolve().parents[4]
PROBES = ROOT / "testdata" / "probes" / "fixtures"


class RecordingBus(EventBus):
    """An event bus that keeps every published event, in publish order (no coalescing)."""

    def __init__(self) -> None:
        super().__init__(max_queue=100_000)
        self.published: list[Event] = []

    def publish(self, event: Event) -> None:
        self.published.append(event)
        super().publish(event)


def of_job(events: Iterable[Event], job_id: str) -> list[Event]:
    return [e for e in events if getattr(e, "job_id", None) == job_id]


def state_changes(events: Iterable[Event]) -> list[tuple[str | None, str]]:
    """``(previous, state)`` of each ``job.state`` event."""
    return [
        (None if e.previous is None else e.previous.value, e.state.value)
        for e in events
        if e.type == "job.state"
    ]


def event_kinds(events: Iterable[Event]) -> list[str]:
    """The event types with repeats of progress and log collapsed."""
    kinds: list[str] = []
    for event in events:
        if kinds and kinds[-1] == event.type and event.type in ("job.progress", "job.log"):
            continue
        kinds.append(event.type)
    return kinds


def recorded(name: str, path: Path) -> MediaSource:
    """The recorded probe of fixture ``name`` (``multitrack.mkv``) as a source at ``path``."""
    data = json.loads((PROBES / f"{name}.json").read_text(encoding="utf-8"))
    return parse_ffprobe(data, path, fingerprint=SourceFingerprint(size=0, mtime=0.0))


def all_caps(*, state: EncoderState = EncoderState.AVAILABLE) -> CapabilitySnapshot:
    defs = load_definitions()
    encoders = {
        enc: EncoderStatus(id=enc, state=state, in_build=state is EncoderState.AVAILABLE)
        for enc in [*defs.video_encoders, *defs.audio_encoders]
    }
    names = sorted({n for f in defs.filters.values() for i in f.implementations for n in i.filters})
    return CapabilitySnapshot(encoders=encoders, filters=names)


def tool_set(ffmpeg: Path) -> ToolSet:
    """The fake FFmpeg as ffmpeg and ffprobe."""

    def info(name: Any, path: Path | None) -> ToolInfo:
        return ToolInfo(
            name=name,
            status=ToolStatus.FOUND if path is not None else ToolStatus.MISSING,
            path=path,
        )

    return ToolSet(
        ffmpeg=info("ffmpeg", ffmpeg),
        ffprobe=info("ffprobe", ffmpeg),
    )


@dataclass
class FakeWriter:
    """Stands in for the Matroska header writer (it runs in a worker thread): records each
    edit and returns :attr:`result`, or raises :attr:`raises`. With :attr:`hold`, a write
    waits for :meth:`release` (at most 30 s). :attr:`effect` runs when a write ends (the
    stubbed probe then shows the new values)."""

    result: HeaderEditResult = field(default_factory=lambda: HeaderEditResult("written"))
    raises: Exception | None = None
    hold: bool = False
    effect: Callable[[], None] | None = None
    edits: list[HeaderEdit] = field(default_factory=list)
    started: threading.Event = field(default_factory=threading.Event)
    finished: threading.Event = field(default_factory=threading.Event)
    _released: threading.Event = field(default_factory=threading.Event)

    def __call__(self, edit: HeaderEdit) -> HeaderEditResult:
        self.edits.append(edit)
        self.started.set()
        if self.hold and not self._released.wait(30):
            raise TimeoutError("the test never released the write")
        if self.effect is not None:
            self.effect()
        self.finished.set()
        if self.raises is not None:
            raise self.raises
        return self.result

    def release(self) -> None:
        self._released.set()


@dataclass
class StubTools:
    tools: ToolSet

    async def status(self) -> ToolSet:
        return self.tools


@dataclass
class StubCaps:
    """``snapshot`` until :meth:`wait`; ``final`` (if given) after it."""

    snapshot: CapabilitySnapshot
    final: CapabilitySnapshot | None = None
    waited: int = 0

    async def wait(self) -> CapabilitySnapshot:
        self.waited += 1
        await asyncio.sleep(0.01)
        if self.final is not None:
            self.snapshot = self.final
        return self.snapshot


OutputProbe = Callable[[Path], MediaSource | ProbeError]


@dataclass
class StubSources:
    """The source is the recorded ``multitrack`` probe; any other path is the output."""

    source: MediaSource
    output: OutputProbe | None = None
    calls: list[tuple[Path, bool]] = field(default_factory=list)
    delay: float = 0.0

    async def probe(
        self,
        path: str | os.PathLike[str],
        *,
        use_cache: bool = True,
        cancel: CancelToken | None = None,
    ) -> MediaSource | ProbeError:
        file = Path(path)
        self.calls.append((file, use_cache))
        if self.delay:
            await asyncio.sleep(self.delay)
        if cancel is not None and cancel.cancelled:
            return ProbeError(file, ProbeErrorKind.CANCELLED, "cancelled")
        if file == self.source.ref.path:
            return self.source.model_copy(deep=True)
        if not await asyncio.to_thread(file.exists):
            return ProbeError(file, ProbeErrorKind.NOT_FOUND, "The file does not exist.")
        if self.output is not None:
            return self.output(file)
        return self.source.model_copy(update={"ref": SourceRef(path=file)}, deep=True)


class CountingBackend:
    name = "fake"
    stops = "nothing (a test backend)"

    def __init__(self) -> None:
        self.holds: list[str] = []
        self.frees = 0
        self.held = False
        self.delay = 0.0
        """Seconds a hold takes (a slow D-Bus call)."""

    async def hold(self, why: str) -> str | None:
        self.holds.append(why)
        if self.delay:
            await asyncio.sleep(self.delay)
        self.held = True
        return None

    async def free(self) -> None:
        self.frees += 1
        self.held = False


def encode_rule(*actions: ft.Action, exit_code: int = 0) -> ft.Rule:
    """A rule for the encode step (its output is ``-f matroska <name>.part.mkv``)."""
    return ft.Rule(tool="ffmpeg", argv_has=["matroska"], actions=actions, exit_code=exit_code)


def draft(source: MediaSource, output: Path, **video: Any) -> JobSettings:
    """A job with every audio track to AAC, every subtitle copied, and x264."""

    def flags(stream: Any) -> TrackMetadata:
        d = stream.disposition
        return TrackMetadata(default=d.default, forced=d.forced, commentary=d.comment)

    job = JobSettings(
        source=SourceRef(path=source.ref.path),
        output=OutputSettings(container="mkv", path=output),
        audio=[
            AudioOutputTrack(source_stream=a.index, encoder="aac", metadata=flags(a))
            for a in source.audio
        ],
        subtitles=[
            SubtitleOutputTrack(source=s.index, metadata=flags(s)) for s in source.subtitles
        ],
    )
    job.video.encoder = "libx264"
    job.video.preset = "ultrafast"
    job.video.metadata = TrackMetadata(default=True)
    for key, value in video.items():
        setattr(job.video, key, value)
    return job


@dataclass
class Harness:
    tmp: Path
    fake: ft.FakeTools
    writer: FakeWriter
    events: RecordingBus
    settings: AppSettings
    tools: StubTools
    caps: StubCaps
    sources: StubSources
    backend: CountingBackend
    inhibitor: SleepInhibitor
    queue: QueueService

    @property
    def source_path(self) -> Path:
        return self.sources.source.ref.path

    def job(self, name: str = "Movie", **video: Any) -> JobSettings:
        return draft(self.sources.source, self.tmp / "out" / f"{name}.mkv", **video)

    def scenario(self, *rules: ft.Rule) -> None:
        self.fake.set_scenario(ft.Scenario(list(rules)))

    def plan(self, job: JobSettings) -> EncodePlan:
        """The plan the runner builds for ``job`` (same inputs)."""
        return build_plan(job, self.sources.source, self.caps.snapshot, self.tools.tools)

    async def run_one(self, job: JobSettings) -> QueueJob:
        added = await self.queue.add(job)
        self.queue.start()
        [ended] = await self.queue.wait([added.id])
        return ended

    def leftovers(self) -> list[int]:
        """Fake processes that still run (killed now); a test expects none."""
        return self.fake.kill_leftovers()

    def events_of(self, job_id: str) -> list[Event]:
        return of_job(self.events.published, job_id)

    def of_type(self, type_: str) -> list[Event]:
        return [e for e in self.events.published if e.type == type_]

    def states(self, job_id: str) -> list[tuple[str | None, str]]:
        return state_changes(self.events_of(job_id))

    def kinds(self, job_id: str) -> list[str]:
        return event_kinds(self.events_of(job_id))

    def log_text(self, job_id: str) -> str:
        return self.queue.log_path(job_id).read_text(encoding="utf-8")

    async def wait_for(self, condition: Callable[[], bool], limit: float = 20.0) -> None:
        await wait_until(condition, limit)

    async def running_process(self, job_id: str, limit: float = 20.0) -> psutil.Process:
        """The process of the job's running step, once it exists: the first ``job.progress``
        comes before the process starts."""

        def current() -> psutil.Process | None:
            active = self.queue._active.get(job_id)
            return None if active is None else active.process

        await wait_until(lambda: current() is not None, limit)
        process = current()
        assert process is not None
        return process

    async def first_event(
        self, job_id: str, type_: str, *, state: str | None = None, limit: float = 20.0
    ) -> Event:
        def find() -> Event | None:
            for event in self.events_of(job_id):
                if event.type == type_ and (state is None or event.state.value == state):  # type: ignore[union-attr]
                    return event
            return None

        await wait_until(lambda: find() is not None, limit)
        found = find()
        assert found is not None
        return found


def queue_at(h: Harness, **options: Any) -> QueueService:
    """A second queue on the harness's data folder (a restarted Reframe)."""
    return QueueService(
        h.events,
        lambda: h.settings.model_copy(deep=True),
        data_dir=h.tmp / "data",
        tools=h.tools,
        capabilities=h.caps,
        sources=h.sources,
        inhibitor=SleepInhibitor([], h.events),
        stall_after=None,
        watchdog_tick=0.05,
        log_interval=0.02,
        **options,
    )


def store_rows(h: Harness, *jobs: QueueJob) -> None:
    db = sqlite3.connect(h.tmp / "data" / "queue.sqlite3")
    for job in jobs:
        row = row_of(job)
        db.execute(f"INSERT OR REPLACE INTO jobs VALUES ({', '.join('?' * len(row))})", row)
    db.commit()
    db.close()


async def store_together(h: Harness, *jobs: JobSettings) -> list[str]:
    """``jobs`` waiting in the saved queue, in this order, without the output claims of ``add``
    (a store saved by an older Reframe). ``h.queue`` is closed."""
    ids = [(await h.queue.add(h.job(f"Placeholder {index}"))).id for index in range(len(jobs))]
    await h.queue.close()
    rows = []
    for job_id, job in zip(ids, jobs, strict=True):
        stored = h.queue.get(job_id)
        assert stored is not None
        stored.settings = job
        rows.append(stored)
    store_rows(h, *rows)
    return ids


async def restore_together(h: Harness, *jobs: JobSettings) -> list[str]:
    """:func:`store_together`, then ``h.queue`` becomes the restored queue."""
    ids = await store_together(h, *jobs)
    h.queue = queue_at(h)
    h.queue.list()
    # Restored keys are taken in the background: the first to arrive would start first.
    await wait_until(lambda: all(job_id in h.queue._keys for job_id in ids))
    return ids


@pytest.fixture
async def harness(
    tmp_path: Path, fake_tools: ft.FakeTools, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Harness]:
    source_path = tmp_path / "media" / "Movie.Source.mkv"
    source_path.parent.mkdir()
    source_path.write_bytes(b"not really matroska")
    (tmp_path / "out").mkdir()
    events = RecordingBus()
    settings = AppSettings()
    settings.encoders.hardware_tests = False
    tools = StubTools(tool_set(fake_tools.ffmpeg))
    caps = StubCaps(all_caps())
    sources = StubSources(recorded("multitrack.mkv", source_path))
    backend = CountingBackend()
    inhibitor = SleepInhibitor([backend], events)
    writer = FakeWriter()
    monkeypatch.setattr(header, "apply_header_edit", writer)
    harness = Harness(
        tmp=tmp_path,
        fake=fake_tools,
        writer=writer,
        events=events,
        settings=settings,
        tools=tools,
        caps=caps,
        sources=sources,
        backend=backend,
        inhibitor=inhibitor,
        queue=QueueService(
            events,
            lambda: settings.model_copy(deep=True),
            data_dir=tmp_path / "data",
            tools=tools,
            capabilities=caps,
            sources=sources,
            inhibitor=inhibitor,
            stall_after=None,
            watchdog_tick=0.05,
            log_interval=0.02,
        ),
    )
    try:
        yield harness
    finally:
        writer.release()  # never leave a write waiting (the queue's close waits for it)
        await harness.queue.close()
