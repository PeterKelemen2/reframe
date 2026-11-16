"""The ``Reframe`` facade: ``create()`` returns at once; tools are discovered in the background."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import psutil
import pytest

import reframe
from reframe.models import (
    AppSettings,
    MediaSource,
    SourceRef,
    ToolOrigin,
    ToolPaths,
    ToolsChangedEvent,
    ToolStatus,
)
from reframe.service import (
    ProbeError,
    ProbeErrorKind,
    Reframe,
    ReframeClosedError,
)
from reframe.tools import ENV_VARS, CancelToken
from reframe_testing import fake_tools as ft
from reframe_testing.helpers import drain
from reframe_testing.waiting import wait_until

pytestmark = pytest.mark.anyio

PROBES = Path(__file__).resolve().parents[3] / "testdata" / "probes"
MULTITRACK = PROBES / "fixtures" / "multitrack.mkv.json"


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


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """No tool overrides, user folders in ``tmp_path``."""
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
        before = app.tools.current
        assert before is None
        # probe() waits for the discovery and then uses the discovered ffprobe.
        source = await app.sources.probe(media)
        assert isinstance(source, MediaSource), source
        assert time.monotonic() - started >= 1.4
        after = app.tools.current
        assert after is not None
        assert after.ffprobe.origin is ToolOrigin.ENV
    finally:
        await app.close()


async def test_close_kills_a_hanging_discovery(fake: ft.FakeTools) -> None:
    fake.set_scenario(ft.Scenario([ft.Rule(argv_has=["-version"], actions=[ft.hang()])]))
    app = await Reframe.create()
    await wait_until(lambda: len(fake.calls()) >= 2)  # ffmpeg and ffprobe version checks run
    pids = fake.pids()
    assert alive(pids)
    started = time.monotonic()
    await app.close()
    assert time.monotonic() - started < 5
    assert alive(pids) == []
    assert app.closed
    assert app.events.closed
    await app.close()  # a second close does nothing


async def test_close_cancels_a_running_probe(fake: ft.FakeTools, media: Path) -> None:
    fake.set_scenario(ft.Scenario([probe_rule(ft.hang())]))
    app = await Reframe.create()
    task = asyncio.create_task(app.sources.probe(media))
    await wait_until(lambda: len(fake.calls("ffprobe")) >= 2)
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
    await wait_until(lambda: len(fake.calls()) >= 2)
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
        await app.sources.get(media)
    with pytest.raises(ReframeClosedError):
        await app.tools.status()
    with pytest.raises(ReframeClosedError):
        await app.tools.rescan()
    with pytest.raises(ReframeClosedError):
        app.tools.start()


async def test_folders_default_to_paths_and_can_be_given(env: Path) -> None:
    app = Reframe(config_dir=env / "c", data_dir=env / "d", cache_dir=env / "k")
    assert app.cache_dir == env / "k"
    async with await Reframe.create() as default:
        assert default.config_dir == env / "config"
        assert default.data_dir == env / "data"
        assert default.cache_dir == env / "cache"
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
    (env / "config").mkdir()
    (env / "config" / "settings.json").write_text(settings.model_dump_json(), "utf-8")
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
        assert not tools.ffprobe.usable
        # A file problem is reported first: it is what the user must fix.
        missing = await app.sources.probe(env / "missing.mkv")
        assert isinstance(missing, ProbeError)
        assert missing.kind is ProbeErrorKind.NOT_FOUND
        folder = await app.sources.probe(env)
        assert isinstance(folder, ProbeError)
        assert folder.kind is ProbeErrorKind.NOT_A_FILE


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


def touch(folder: Path, *names: str) -> list[Path]:
    folder.mkdir(exist_ok=True)
    for name in names:
        (folder / name).write_bytes(b"x")
    return [folder / name for name in names]


def counting_probe(app: Reframe, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replaces ``app.sources.probe``: records how many run at once; ``*.bad.mkv`` fail."""
    seen: dict[str, Any] = {"running": 0, "max_running": 0, "names": []}

    async def probe(path: Any, *, cancel: Any = None) -> MediaSource | ProbeError:
        seen["running"] += 1
        seen["max_running"] = max(seen["max_running"], seen["running"])
        seen["names"].append(Path(path).name)
        try:
            await asyncio.sleep(0.02)
        finally:
            seen["running"] -= 1
        if str(path).endswith(".bad.mkv"):
            return ProbeError(Path(path), ProbeErrorKind.FAILED, "bad")
        return MediaSource(ref=SourceRef(path=Path(path)))

    monkeypatch.setattr(app.sources, "probe", probe)
    return seen


async def test_probe_many_keeps_the_order_and_the_limit(
    env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = touch(env / "season", *(f"E{i:02d}.mkv" for i in range(1, 13)), "E13.bad.mkv")
    async with await Reframe.create() as app:
        seen = counting_probe(app, monkeypatch)
        progress: list[tuple[int, int]] = []
        results = await app.sources.probe_many(
            files, on_progress=lambda done, total: progress.append((done, total))
        )
        assert seen["max_running"] == 4
        assert [r.ref.path if isinstance(r, MediaSource) else r.path for r in results] == files
        assert isinstance(results[-1], ProbeError)
        assert progress == [(i, 13) for i in range(1, 14)]
        seen["max_running"] = 0
        await app.sources.probe_many(files[:6], concurrency=2)
        assert seen["max_running"] == 2


async def test_probe_many_refuses_a_concurrency_below_one(env: Path) -> None:
    async with await Reframe.create() as app:
        with pytest.raises(ValueError, match="at least 1"):
            await app.sources.probe_many([], concurrency=0)


async def test_probe_many_starts_no_probe_after_a_cancel(
    env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = touch(env / "season", *(f"E{i}.mkv" for i in range(5)))
    token = CancelToken()
    async with await Reframe.create() as app:
        seen = counting_probe(app, monkeypatch)
        progress: list[int] = []

        def on_progress(done: int, total: int) -> None:
            progress.append(done)
            token.cancel()

        results = await app.sources.probe_many(
            files, concurrency=1, cancel=token, on_progress=on_progress
        )
        assert seen["names"] == ["E0.mkv"]
        assert isinstance(results[0], MediaSource)
        assert [r.kind for r in results[1:] if isinstance(r, ProbeError)] == [
            ProbeErrorKind.CANCELLED
        ] * 4
        assert progress == [1, 2, 3, 4, 5]


def probe_calls(fake: ft.FakeTools) -> int:
    return len([c for c in fake.calls("ffprobe") if "-show_streams" in c])


async def test_a_cancelled_probe_many_kills_every_ffprobe(fake: ft.FakeTools, env: Path) -> None:
    files = touch(env / "season", *(f"E{i}.mkv" for i in range(8)))
    fake.set_scenario(ft.Scenario([probe_rule(ft.hang())]))
    token = CancelToken()
    async with await Reframe.create() as app:
        await app.tools.status()
        before = set(fake.pids())
        task = asyncio.create_task(app.sources.probe_many(files, cancel=token))
        await wait_until(lambda: probe_calls(fake) >= 4)
        pids = [p for p in fake.pids() if p not in before]
        assert probe_calls(fake) == 4  # the limit: the rest wait
        token.cancel()
        results = await task
        assert [r.kind for r in results if isinstance(r, ProbeError)] == [
            ProbeErrorKind.CANCELLED
        ] * 8
        assert alive(pids) == []
        assert probe_calls(fake) == 4  # no ffprobe started after the cancel


async def test_cancelling_the_probe_many_task_reaps_every_ffprobe(
    fake: ft.FakeTools, env: Path
) -> None:
    files = touch(env / "season", *(f"E{i}.mkv" for i in range(8)))
    fake.set_scenario(ft.Scenario([probe_rule(ft.hang())]))
    async with await Reframe.create() as app:
        await app.tools.status()
        before = set(fake.pids())
        task = asyncio.create_task(app.sources.probe_many(files))
        await wait_until(lambda: probe_calls(fake) >= 4)
        pids = [p for p in fake.pids() if p not in before]
        task.cancel()
        await asyncio.wait({task})
        assert alive(pids) == []
        assert probe_calls(fake) == 4


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
        received = drain(events)
        # The first discovery may have ended before the subscription.
        assert 1 <= len(received) <= 2
        assert all(isinstance(e, ToolsChangedEvent) for e in received)


async def test_rescan_replaces_a_running_discovery(fake: ft.FakeTools, media: Path) -> None:
    fake.set_scenario(ft.Scenario([ft.Rule(argv_has=["-version"], actions=[ft.hang()])]))
    async with await Reframe.create() as app:
        waiting = asyncio.create_task(app.tools.status())
        await wait_until(lambda: len(fake.calls()) >= 2)
        hanging = fake.pids()
        fake.set_scenario(ft.Scenario([probe_rule(stdout_file(MULTITRACK))]))
        tools = await app.tools.rescan()
        assert tools.ffprobe.status is ToolStatus.FOUND
        # The waiter of the first (cancelled) discovery gets the new result.
        assert await waiting == tools
        await wait_until(lambda: alive(hanging) == [], limit=10)


async def test_status_starts_a_discovery_if_none_ran(env: Path) -> None:
    app = Reframe(config_dir=env / "c", data_dir=env / "d", cache_dir=env / "k")
    try:
        before, task = app.tools.current, app.tools._task
        assert before is None
        assert task is None
        tools = await app.tools.status()
        assert app.tools.current == tools
        ran = app.tools._task
        app.tools.start()  # a discovery ran: no new one
        assert app.tools._task is ran
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
