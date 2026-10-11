"""Folder probe (C-3): media files only, natural order, concurrency limit, progress, task."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import psutil
import pytest

from reframe.events import EventBus
from reframe.models import MediaSource, SourceRef, TaskState
from reframe.probe import (
    FolderProbeResult,
    ProbeError,
    ProbeErrorKind,
    Prober,
    ProbeTool,
    list_media_files,
    natural_key,
    probe_folder,
    start_probe_folder,
)
from reframe.tasks import TaskManager
from reframe.tools import CancelToken
from reframe_testing import fake_tools as ft

pytestmark = pytest.mark.anyio


async def until(condition: Callable[[], bool], limit: float = 30.0) -> None:
    """Wait (polling) until ``condition()`` is true."""
    deadline = time.monotonic() + limit
    while not condition():
        if time.monotonic() > deadline:
            raise TimeoutError("condition not met in time")
        await asyncio.sleep(0.02)


PROBES = Path(__file__).resolve().parents[4] / "testdata" / "probes"


def touch(folder: Path, *names: str) -> None:
    for name in names:
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")


def test_natural_key() -> None:
    names = ["Show.S01E10.mkv", "show.s01e2.mkv", "Show.S01E1.mkv", "Show.S01E02b.mkv", "a"]
    assert sorted(names, key=natural_key) == [
        "a",
        "Show.S01E1.mkv",
        "show.s01e2.mkv",
        "Show.S01E02b.mkv",
        "Show.S01E10.mkv",
    ]


def test_list_media_files(tmp_path: Path) -> None:
    touch(
        tmp_path,
        "E10.mkv",
        "E2.mkv",
        "e1.MP4",
        "E3.m2ts",
        ".hidden.mkv",
        "notes.txt",
        "E2.srt",
        "cover.jpg",
        "sub/E4.mkv",
    )
    (tmp_path / "folder.mkv").mkdir()
    assert [p.name for p in list_media_files(tmp_path)] == [
        "e1.MP4",
        "E2.mkv",
        "E3.m2ts",
        "E10.mkv",
    ]
    deep = list_media_files(tmp_path, recursive=True)
    assert [p.relative_to(tmp_path).as_posix() for p in deep] == [
        "e1.MP4",
        "E2.mkv",
        "E3.m2ts",
        "E10.mkv",
        "sub/E4.mkv",
    ]


def test_recursive_skips_hidden_folders(tmp_path: Path) -> None:
    touch(tmp_path, ".trash/E1.mkv", "Season 10/E1.mkv", "Season 2/E1.mkv")
    found = list_media_files(tmp_path, recursive=True)
    assert [p.parent.name for p in found] == ["Season 2", "Season 10"]


class FakeProber(Prober):
    """Records how many probes run at once; ``*.bad.mkv`` fail."""

    def __init__(self, delay: float = 0.02) -> None:
        super().__init__(ProbeTool("ffprobe"), use_mediainfo=False)
        self.delay = delay
        self.running = 0
        self.max_running = 0
        self.seen: list[str] = []

    async def probe(
        self, path: Any, *, cancel: CancelToken | None = None, use_cache: bool = True
    ) -> MediaSource | ProbeError:
        self.running += 1
        self.max_running = max(self.max_running, self.running)
        self.seen.append(Path(path).name)
        try:
            await asyncio.sleep(self.delay)
        finally:
            self.running -= 1
        if str(path).endswith(".bad.mkv"):
            return ProbeError(Path(path), ProbeErrorKind.FAILED, "bad")
        return MediaSource(ref=SourceRef(path=Path(path)))


async def test_probe_folder_limit_order_progress(tmp_path: Path) -> None:
    names = [f"Show.S01E{i:02d}.mkv" for i in range(1, 13)] + ["Show.S01E13.bad.mkv"]
    touch(tmp_path, *names, "readme.txt")
    prober = FakeProber()
    progress: list[tuple[int, int]] = []
    result = await probe_folder(
        prober, tmp_path, on_progress=lambda done, total, path: progress.append((done, total))
    )
    assert prober.max_running == 4  # the default limit
    assert [s.ref.path.name for s in result.sources] == names[:-1]  # natural order
    assert [e.path.name for e in result.errors] == ["Show.S01E13.bad.mkv"]
    assert progress == [(i, 13) for i in range(1, 14)]
    assert result.to_json() == {
        "folder": str(tmp_path),
        "total": 13,
        "probed": [str(tmp_path / n) for n in names[:-1]],
        "errors": [
            {
                "path": str(tmp_path / "Show.S01E13.bad.mkv"),
                "kind": "failed",
                "message": "bad",
                "detail": None,
            }
        ],
    }


async def test_probe_folder_custom_limit(tmp_path: Path) -> None:
    touch(tmp_path, *(f"{i}.mkv" for i in range(6)))
    prober = FakeProber()
    await probe_folder(prober, tmp_path, concurrency=2)
    assert prober.max_running == 2
    with pytest.raises(ValueError, match="at least 1"):
        await probe_folder(prober, tmp_path, concurrency=0)


async def test_probe_folder_problems(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prober = FakeProber()
    missing = await probe_folder(prober, tmp_path / "missing")
    assert [e.kind for e in missing.errors] == [ProbeErrorKind.NOT_FOUND]
    file = tmp_path / "a.mkv"
    file.write_bytes(b"x")
    not_dir = await probe_folder(prober, file)
    assert [e.kind for e in not_dir.errors] == [ProbeErrorKind.NOT_A_FILE]

    def denied(folder: Path, *, recursive: bool = False) -> list[Path]:
        raise PermissionError("denied")

    from reframe.probe import folder as folder_mod

    monkeypatch.setattr(folder_mod, "list_media_files", denied)
    unreadable = await probe_folder(prober, tmp_path)
    assert [e.kind for e in unreadable.errors] == [ProbeErrorKind.UNREADABLE]
    empty = FolderProbeResult(tmp_path)
    assert empty.to_json() == {"folder": str(tmp_path), "total": 0, "probed": [], "errors": []}


async def test_folder_task_events(tmp_path: Path) -> None:
    touch(tmp_path, "E1.mkv", "E2.mkv", "E3.mkv")
    bus = EventBus()
    sub = bus.subscribe()
    tasks = TaskManager(bus)
    info = start_probe_folder(tasks, FakeProber(), tmp_path)
    assert info.kind == "probe_folder"
    assert info.state is TaskState.QUEUED
    final = await tasks.wait(info.id)
    assert final.state is TaskState.DONE
    events = []
    while (event := sub.get_nowait()) is not None:
        events.append(event)
    summary = [(e.type, e.task.state.value, e.task.progress, e.task.message) for e in events]  # type: ignore[union-attr]
    assert summary == [
        ("task.progress", "queued", None, f"Probing {tmp_path.name}"),
        ("task.progress", "running", None, f"Probing {tmp_path.name}"),
        ("task.progress", "running", 0.0, "Listing files"),
        ("task.progress", "running", pytest.approx(100 / 3), "1/3 files"),
        ("task.progress", "running", pytest.approx(200 / 3), "2/3 files"),
        ("task.progress", "running", 100.0, "3/3 files"),
        ("task.done", "done", 100.0, "3/3 files"),
    ]
    assert isinstance(final.result, dict)
    assert final.result["total"] == 3
    value = tasks.value(info.id)
    assert isinstance(value, FolderProbeResult)
    assert len(value.sources) == 3


def _fake_prober(fake: ft.FakeTools) -> Prober:
    return Prober(ProbeTool(str(fake.ffprobe), version="n-fake"), use_mediainfo=False)


async def test_folder_task_with_fake_ffprobe(fake_tools: ft.FakeTools, tmp_path: Path) -> None:
    """24 files through the fake ffprobe (multi-track JSON), 4 at a time."""
    rule = ft.Rule(
        tool="ffprobe",
        argv_has=["-show_streams"],
        actions=[{"stdout_file": str(PROBES / "fixtures" / "multitrack.mkv.json")}],
    )
    fake_tools.set_scenario(ft.Scenario([rule]))
    media = tmp_path / "season"
    touch(media, *(f"Show.S01E{i:02d}.mkv" for i in range(1, 25)))
    tasks = TaskManager()
    info = start_probe_folder(tasks, _fake_prober(fake_tools), media)
    final = await tasks.wait(info.id)
    assert final.state is TaskState.DONE, final.error
    value = tasks.value(info.id)
    assert isinstance(value, FolderProbeResult)
    assert len(value.sources) == 24
    assert value.errors == []
    assert all(len(s.audio) == 3 for s in value.sources)
    assert len(fake_tools.calls("ffprobe")) == 24


async def test_cancel_folder_task_kills_ffprobe(fake_tools: ft.FakeTools, tmp_path: Path) -> None:
    fake_tools.set_scenario(
        ft.Scenario([ft.Rule(tool="ffprobe", argv_has=["-show_streams"], actions=[ft.hang()])])
    )
    touch(tmp_path, *(f"E{i}.mkv" for i in range(8)))
    tasks = TaskManager()
    info = start_probe_folder(tasks, _fake_prober(fake_tools), tmp_path)
    await until(lambda: len(fake_tools.pids()) >= 4)
    pids = fake_tools.pids()
    assert len(pids) == 4  # the folder limit: 4 ffprobe processes, the rest wait
    started = time.monotonic()
    assert tasks.cancel(info.id)
    final = await tasks.wait(info.id)
    assert final.state is TaskState.CANCELLED
    _, alive = psutil.wait_procs([_proc(p) for p in pids if _proc(p)], timeout=1.0)
    assert not [p for p in alive if p.status() != psutil.STATUS_ZOMBIE]
    assert time.monotonic() - started < 1.5
    assert len(fake_tools.pids()) == 4  # no new ffprobe was started after the cancel


def _proc(pid: int) -> Any:
    try:
        return psutil.Process(pid)
    except psutil.Error:
        return None


async def test_cancelling_probe_folder_reaps_every_ffprobe(
    fake_tools: ft.FakeTools, tmp_path: Path
) -> None:
    """A cancelled probe_folder() returns only after every running ffprobe is gone.

    Regression: with ``asyncio.gather`` a cancel returned as soon as the first probe ended,
    and the other probes' process kills could be dropped when the loop stopped (orphans).
    """
    fake_tools.set_scenario(
        ft.Scenario([ft.Rule(tool="ffprobe", argv_has=["-show_streams"], actions=[ft.hang()])])
    )
    touch(tmp_path, *(f"E{i}.mkv" for i in range(8)))
    task = asyncio.ensure_future(probe_folder(_fake_prober(fake_tools), tmp_path))
    await until(lambda: len(fake_tools.pids()) >= 4)
    pids = fake_tools.pids()
    task.cancel()
    await asyncio.wait({task})
    alive = [p for p in pids if (proc := _proc(p)) and proc.status() != psutil.STATUS_ZOMBIE]
    assert alive == []
