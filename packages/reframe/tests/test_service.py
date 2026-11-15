"""The ``Reframe`` facade: ``create()`` returns at once; tools are discovered in the background."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from pathlib import Path

import psutil
import pytest

import reframe
from reframe.events import Subscription
from reframe.models import (
    AppSettings,
    Event,
    MediaSource,
    TaskDoneEvent,
    TaskProgressEvent,
    TaskState,
    ToolOrigin,
    ToolPaths,
    ToolsChangedEvent,
    ToolStatus,
)
from reframe.service import (
    FolderProbeResult,
    ProbeError,
    ProbeErrorKind,
    Reframe,
    ReframeClosedError,
    tool_usable,
)
from reframe.tools import ENV_VARS
from reframe_testing import fake_tools as ft

pytestmark = pytest.mark.anyio

PROBES = Path(__file__).resolve().parents[3] / "testdata" / "probes"
MULTITRACK = PROBES / "fixtures" / "multitrack.mkv.json"


async def until(condition: Callable[[], bool], limit: float = 30.0) -> None:
    """Wait (polling) until ``condition()`` is true."""
    deadline = time.monotonic() + limit
    while not condition():
        if time.monotonic() > deadline:
            raise TimeoutError("condition not met in time")
        await asyncio.sleep(0.02)


def alive(pids: list[int]) -> list[int]:
    """The pids that still run (zombies count as ended)."""
    running = []
    for pid in pids:
        try:
            if psutil.Process(pid).status() != psutil.STATUS_ZOMBIE:
                running.append(pid)
        except psutil.Error:
            pass
    return running


def stdout_file(path: Path) -> ft.Action:
    return {"stdout_file": str(path)}


def probe_rule(*actions: ft.Action, exit_code: int = 0) -> ft.Rule:
    return ft.Rule(tool="ffprobe", argv_has=["-show_streams"], actions=actions, exit_code=exit_code)


def drain(subscription: Subscription) -> list[Event]:
    events = []
    while (event := subscription.get_nowait()) is not None:
        events.append(event)
    return events


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """No tool overrides, user folders in ``tmp_path``, MediaInfo off (deterministic)."""
    for var in ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    for name in ("config", "data", "cache"):
        monkeypatch.setenv(f"REFRAME_{name.upper()}_DIR", str(tmp_path / name))
    return tmp_path


@pytest.fixture
def fake(env: Path, fake_tools: ft.FakeTools, monkeypatch: pytest.MonkeyPatch) -> ft.FakeTools:
    """``REFRAME_FFMPEG`` / ``REFRAME_FFPROBE`` point at the fake tools (multitrack probe)."""
    monkeypatch.setenv("REFRAME_FFMPEG", str(fake_tools.ffmpeg))
    monkeypatch.setenv("REFRAME_FFPROBE", str(fake_tools.ffprobe))
    fake_tools.set_scenario(ft.Scenario([probe_rule(stdout_file(MULTITRACK))]))
    return fake_tools


@pytest.fixture
def media(tmp_path: Path) -> Path:
    path = tmp_path / "Show S01E01.mkv"
    path.write_bytes(b"\x1a\x45\xdf\xa3 not really matroska")
    return path


def test_reframe_is_exported() -> None:
    assert reframe.Reframe is Reframe
    assert "Reframe" in reframe.__all__


async def test_create_returns_at_once_while_discovery_is_slow(
    fake: ft.FakeTools, media: Path
) -> None:
    fake.set_scenario(
        ft.Scenario(
            [
                ft.Rule(argv_has=["-version"], actions=[ft.sleep(1.5), ft.version()]),
                probe_rule(stdout_file(MULTITRACK)),
            ]
        )
    )
    started = time.monotonic()
    app = await Reframe.create()
    elapsed = time.monotonic() - started
    try:
        assert elapsed < 0.5, f"create() took {elapsed:.2f} s"
        before, discovering = app.tools.current, app.tools.discovering
        assert before is None
        assert discovering
        # probe() waits for the discovery and then uses the discovered ffprobe.
        source = await app.sources.probe(media)
        assert isinstance(source, MediaSource), source
        assert time.monotonic() - started >= 1.4
        after = app.tools.current
        assert after is not None
        assert not app.tools.discovering
        assert after.ffprobe.origin is ToolOrigin.ENV
    finally:
        await app.close()


async def test_close_kills_a_hanging_discovery(fake: ft.FakeTools) -> None:
    fake.set_scenario(ft.Scenario([ft.Rule(argv_has=["-version"], actions=[ft.hang()])]))
    app = await Reframe.create()
    await until(lambda: len(fake.calls()) >= 2)  # ffmpeg and ffprobe version checks run
    pids = fake.pids()
    assert alive(pids)
    started = time.monotonic()
    await app.close()
    assert time.monotonic() - started < 5
    assert alive(pids) == []
    assert app.closed
    assert app.events.closed
    await app.close()  # a second close does nothing


async def test_close_cancels_folder_probe_and_kills_ffprobe(fake: ft.FakeTools, env: Path) -> None:
    folder = env / "season"
    folder.mkdir()
    for n in range(1, 4):
        (folder / f"Show.S01E0{n}.mkv").write_bytes(b"x")
    fake.set_scenario(ft.Scenario([probe_rule(ft.hang())]))
    app = await Reframe.create()
    info = app.sources.probe_folder(folder)
    await until(lambda: len(fake.calls("ffprobe")) >= 4)  # -version + 3 probes
    pids = fake.pids()
    await app.close()
    assert alive(pids) == []
    final = app.tasks.get(info.id)
    assert final is not None
    assert final.state is TaskState.CANCELLED


async def test_close_cancels_a_running_probe(fake: ft.FakeTools, media: Path) -> None:
    fake.set_scenario(ft.Scenario([probe_rule(ft.hang())]))
    app = await Reframe.create()
    task = asyncio.create_task(app.sources.probe(media))
    await until(lambda: len(fake.calls("ffprobe")) >= 2)
    pids = fake.pids()
    await app.close()
    outcome = await task
    assert isinstance(outcome, ProbeError)
    assert outcome.kind is ProbeErrorKind.CANCELLED
    assert alive(pids) == []


async def test_probe_waiting_for_discovery_is_cancelled_by_close(
    fake: ft.FakeTools, media: Path
) -> None:
    fake.set_scenario(ft.Scenario([ft.Rule(argv_has=["-version"], actions=[ft.hang()])]))
    app = await Reframe.create()
    task = asyncio.create_task(app.sources.probe(media))
    await until(lambda: len(fake.calls()) >= 2)
    await app.close()
    outcome = await task
    assert isinstance(outcome, ProbeError)
    assert outcome.kind is ProbeErrorKind.CANCELLED
    assert "shutting down" in outcome.message


async def test_async_with_closes(fake: ft.FakeTools, media: Path) -> None:
    async with await Reframe.create() as app:
        source = await app.sources.probe(media)
        assert isinstance(source, MediaSource)
        assert [a.display_codec for a in source.audio] == ["AC-3", "AAC-LC", "AAC-LC"]
    assert app.closed
    with pytest.raises(ReframeClosedError):
        await app.sources.probe(media)
    with pytest.raises(ReframeClosedError):
        app.sources.probe_folder(media.parent)
    with pytest.raises(ReframeClosedError):
        await app.sources.get(media)
    with pytest.raises(ReframeClosedError):
        await app.tools.status()
    with pytest.raises(ReframeClosedError):
        await app.tools.rescan()
    with pytest.raises(ReframeClosedError):
        app.tools.start()


async def test_folders_default_to_paths_and_can_be_given(env: Path) -> None:
    app = Reframe(
        config_dir=env / "c", data_dir=env / "d", cache_dir=env / "k", settings=AppSettings()
    )
    assert app.sources.cache.directory == env / "k" / "probe"
    async with await Reframe.create() as default:
        assert default.config_dir == env / "config"
        assert default.data_dir == env / "data"
        assert default.cache_dir == env / "cache"
        assert default.sources.cache.directory == env / "cache" / "probe"
    async with await Reframe.create(env / "c2", env / "d2", cache_dir=env / "k2") as given:
        assert (given.config_dir, given.data_dir, given.cache_dir) == (
            env / "c2",
            env / "d2",
            env / "k2",
        )


async def test_data_dir_holds_the_fetched_tools(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = env / "my-data"
    bundled = ft.make_fake_tools(data / "tools" / "ffmpeg")
    try:
        async with await Reframe.create(data_dir=data) as app:
            tools = await app.tools.status()
            if tools.ffprobe.origin is not ToolOrigin.BUNDLED:  # pragma: no cover
                pytest.skip(f"a system bundled build comes first: {tools.ffprobe.path}")
            assert tools.ffprobe.path == bundled.ffprobe
            assert tools.ffprobe.status is ToolStatus.FOUND
    finally:
        bundled.kill_leftovers()


async def test_settings_tool_paths_feed_discovery(
    env: Path, fake_tools: ft.FakeTools, monkeypatch: pytest.MonkeyPatch, media: Path
) -> None:
    fake_tools.set_scenario(ft.Scenario([probe_rule(stdout_file(MULTITRACK))]))
    settings = AppSettings(tools=ToolPaths(ffmpeg=fake_tools.ffmpeg, ffprobe=fake_tools.ffprobe))
    monkeypatch.setattr(Reframe, "_load_settings", staticmethod(lambda config_dir: settings))
    async with await Reframe.create() as app:
        assert app.settings_snapshot() == settings
        assert app.settings_snapshot() is not app.settings_snapshot()
        tools = await app.tools.status()
        assert tools.ffprobe.origin is ToolOrigin.SETTINGS
        assert tools.ffprobe.path == fake_tools.ffprobe
        assert isinstance(await app.sources.probe(media), MediaSource)


async def test_missing_ffprobe_is_a_tool_error(
    env: Path, monkeypatch: pytest.MonkeyPatch, media: Path
) -> None:
    monkeypatch.setenv("REFRAME_FFPROBE", str(env / "nowhere" / "ffprobe"))
    async with await Reframe.create() as app:
        outcome = await app.sources.probe(media)
        assert isinstance(outcome, ProbeError)
        assert outcome.kind is ProbeErrorKind.TOOL_FAILED
        assert outcome.message == "ffprobe cannot be used (missing)."
        assert outcome.detail is not None
        assert "REFRAME_FFPROBE" in outcome.detail
        tools = await app.tools.status()
        assert not tool_usable(tools.ffprobe)
        # A file problem is reported first: it is what the user must fix.
        missing = await app.sources.probe(env / "missing.mkv")
        assert isinstance(missing, ProbeError)
        assert missing.kind is ProbeErrorKind.NOT_FOUND
        folder = await app.sources.probe(env)
        assert isinstance(folder, ProbeError)
        assert folder.kind is ProbeErrorKind.NOT_A_FILE
        # A folder probe gives one tool error for the folder.
        info = app.sources.probe_folder(env)
        final = await app.tasks.wait(info.id)
        assert final.state is TaskState.DONE
        assert isinstance(final.result, dict)
        errors = final.result["errors"]
        assert isinstance(errors, list)
        assert [e["kind"] for e in errors if isinstance(e, dict)] == ["tool_failed"]
        assert app.sources.cache.directory == env / "cache" / "probe"


async def test_probe_errors_are_values(fake: ft.FakeTools, media: Path, env: Path) -> None:
    fake.set_scenario(
        ft.Scenario(
            [probe_rule(ft.stderr("Invalid data found when processing input\n"), exit_code=1)]
        )
    )
    async with await Reframe.create() as app:
        outcome = await app.sources.probe(media)
        assert isinstance(outcome, ProbeError)
        assert outcome.kind is ProbeErrorKind.FAILED
        assert outcome.detail == "Invalid data found when processing input"
        missing = await app.sources.probe(env / "missing.mkv")
        assert isinstance(missing, ProbeError)
        assert missing.kind is ProbeErrorKind.NOT_FOUND


async def test_probe_folder_emits_task_events(fake: ft.FakeTools, env: Path) -> None:
    folder = env / "season"
    folder.mkdir()
    files = [folder / f"Show.S01E{n:02d}.mkv" for n in range(1, 4)]
    for path in files:
        path.write_bytes(b"x")
    (folder / "notes.txt").write_text("not media", encoding="utf-8")
    async with await Reframe.create() as app:
        events = app.events.subscribe(types={"task.progress", "task.done"})
        info = app.sources.probe_folder(folder)
        assert info.kind == "probe_folder"
        assert info.state is TaskState.QUEUED
        final = await app.tasks.wait(info.id)
        assert final.state is TaskState.DONE
        received = drain(events)
        progress = [e for e in received if isinstance(e, TaskProgressEvent)]
        done = [e for e in received if isinstance(e, TaskDoneEvent)]
        assert len(progress) + len(done) == len(received)
        assert all(e.task.id == info.id for e in progress)
        assert all(e.task.id == info.id for e in done)
        # The bus coalesces the progress of one task (only the latest is queued), and this
        # test reads after the task ended: the last progress is always there.
        messages = [e.task.message for e in progress]
        assert set(messages) <= {
            "Waiting for tool discovery",
            "1/3 files",
            "2/3 files",
            "3/3 files",
        }
        assert messages[-1] == "3/3 files"
        assert progress[-1].task.progress == 100.0
        assert len(done) == 1
        assert done[0].task.result == {
            "folder": str(folder),
            "total": 3,
            "probed": [str(p) for p in files],
            "errors": [],
        }
        value = app.tasks.value(info.id)
        assert isinstance(value, FolderProbeResult)
        assert [s.ref.path for s in value.sources] == files
        # Every probed source is known now, without another ffprobe run.
        calls = len(fake.calls("ffprobe"))
        for path in files:
            source = await app.sources.get(path)
            assert source is not None
            assert source.ref.path == path
        assert len(fake.calls("ffprobe")) == calls
        with pytest.raises(ValueError, match="concurrency"):
            app.sources.probe_folder(folder, concurrency=0)


async def test_get_returns_known_unchanged_sources(fake: ft.FakeTools, media: Path) -> None:
    async with await Reframe.create() as app:
        assert await app.sources.get(media) is None  # never probed (no disk entry yet)
        assert await app.sources.get(media.parent / "missing.mkv") is None
        source = await app.sources.probe(media)
        assert isinstance(source, MediaSource)
        known = await app.sources.get(media)
        assert known == source
        assert known is not source  # a copy
        # A changed file is not known any more (the disk cache entry is for the old version).
        with media.open("ab") as f:
            f.write(b"more")
        assert await app.sources.get(media) is None
        again = await app.sources.probe(media)
        assert isinstance(again, MediaSource)
        assert await app.sources.get(media) == again
    # A new instance finds it in the disk cache once tool discovery has finished.
    async with await Reframe.create() as fresh:
        await fresh.tools.status()
        cached = await fresh.sources.get(media)
        assert cached == again


async def test_get_before_discovery_uses_memory_only(fake: ft.FakeTools, media: Path) -> None:
    fake.set_scenario(ft.Scenario([ft.Rule(argv_has=["-version"], actions=[ft.hang()])]))
    async with await Reframe.create() as app:
        assert await app.sources.get(media) is None
        assert app.tools.current is None


async def test_known_sources_are_bounded(
    fake: ft.FakeTools, env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from reframe import service

    monkeypatch.setattr(service, "KNOWN_SOURCES", 2)
    files = []
    for n in range(3):
        path = env / f"f{n}.mkv"
        path.write_bytes(b"x")
        files.append(path)
    async with await Reframe.create() as app:
        for path in files:
            assert isinstance(await app.sources.probe(path, use_cache=False), MediaSource)
        assert list(app.sources._known) == files[1:]


async def test_rescan_publishes_tools_changed(fake: ft.FakeTools) -> None:
    async with await Reframe.create() as app:
        events = app.events.subscribe(types={"tools.changed"})
        first = await app.tools.status()
        second = await app.tools.rescan()
        assert second.ffprobe.path == first.ffprobe.path
        versions = await app.tools.versions()
        assert versions["ffprobe"] == "n9.0.2-17-g2a571b6068-20260930"  # the fake's version
        assert set(versions) == {"ffmpeg", "ffprobe", "mkvpropedit", "mediainfo"}
        received = drain(events)
        # The first discovery may have ended before the subscription.
        assert 1 <= len(received) <= 2
        assert all(isinstance(e, ToolsChangedEvent) for e in received)


async def test_rescan_replaces_a_running_discovery(fake: ft.FakeTools, media: Path) -> None:
    fake.set_scenario(ft.Scenario([ft.Rule(argv_has=["-version"], actions=[ft.hang()])]))
    async with await Reframe.create() as app:
        waiting = asyncio.create_task(app.tools.status())
        await until(lambda: len(fake.calls()) >= 2)
        hanging = fake.pids()
        fake.set_scenario(ft.Scenario([probe_rule(stdout_file(MULTITRACK))]))
        tools = await app.tools.rescan()
        assert tools.ffprobe.status is ToolStatus.FOUND
        # The waiter of the first (cancelled) discovery gets the new result.
        assert await waiting == tools
        await until(lambda: alive(hanging) == [], limit=10)


async def test_status_starts_a_discovery_if_none_ran(env: Path) -> None:
    app = Reframe(
        config_dir=env / "c", data_dir=env / "d", cache_dir=env / "k", settings=AppSettings()
    )
    try:
        before = app.tools.current
        assert before is None
        assert not app.tools.discovering
        tools = await app.tools.status()
        assert app.tools.current == tools
        app.tools.start()  # a discovery ran: no new one
        assert not app.tools.discovering
    finally:
        await app.close()


async def test_status_restarts_a_discovery_cancelled_from_outside(fake: ft.FakeTools) -> None:
    async with await Reframe.create() as app:
        running = app.tools._task
        assert running is not None
        running.cancel()
        tools = await app.tools.status()
        assert tools.ffprobe.status is ToolStatus.FOUND
        assert app.tools._task is not running
