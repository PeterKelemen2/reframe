"""``Reframe.queue`` (C-11 wiring in ``reframe.service``): built in ``__init__``, restored in
``create()``, closed first in ``close()``, given ``Reframe.power`` for when done; with the
fake tools behind the real services."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from reframe.events import EventBus
from reframe.models import JobState, NamingOptions
from reframe.probe import mediainfo
from reframe.queue import QueueService
from reframe.service import Reframe
from reframe.tools import ENV_VARS
from reframe_testing import fake_tools as ft

from .conftest import draft, encode_rule, recorded
from .test_when_done import FakePower

pytestmark = pytest.mark.anyio

MULTITRACK = Path(__file__).resolve().parents[4] / "testdata" / "probes" / "fixtures"
PROBE = ft.Rule(
    tool="ffprobe",
    argv_has=["-show_streams"],
    actions=[{"stdout_file": str(MULTITRACK / "multitrack.mkv.json")}],
)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fake_tools: ft.FakeTools) -> Path:
    for var in ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    for name in ("config", "data", "cache"):
        monkeypatch.setenv(f"REFRAME_{name.upper()}_DIR", str(tmp_path / name))
    monkeypatch.setenv("REFRAME_FFMPEG", str(fake_tools.ffmpeg))
    monkeypatch.setenv("REFRAME_FFPROBE", str(fake_tools.ffprobe))
    monkeypatch.setattr(mediainfo, "mediainfo_available", lambda: False)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "settings.json").write_text(
        json.dumps({"encoders": {"hardware_tests": False}, "queue": {"sleep_inhibit": False}}),
        encoding="utf-8",
    )
    fake_tools.set_scenario(ft.Scenario([PROBE]))
    (tmp_path / "media").mkdir()
    (tmp_path / "media" / "Show.mkv").write_bytes(b"not really matroska")
    return tmp_path


async def test_create_restores_and_close_interrupts(env: Path, fake_tools: ft.FakeTools) -> None:
    app = await Reframe.create()
    try:
        assert isinstance(app.queue, QueueService)
        assert app.queue.list() == []
        assert app.queue._store.path == env / "data" / "queue.sqlite3"
        assert not app.queue._store.path.exists()  # nothing written before a job is added
        source = recorded("multitrack.mkv", env / "media" / "Show.mkv")
        done = await app.queue.add(draft(source, env / "out" / "Done.mkv"))
        app.queue.start()
        [ended] = await app.queue.wait([done.id])
        assert ended.state is JobState.DONE, ended.error
        assert ended.output_path == env / "out" / "Done.mkv"
        fake_tools.set_scenario(
            ft.Scenario([PROBE, encode_rule(ft.progress(blocks=1, end=False), ft.hang())])
        )
        running = await app.queue.add(draft(source, env / "out" / "Running.mkv"))
        async with app.events.subscribe(types={"job.progress"}) as events:
            async for event in events:
                if event.job_id == running.id:  # type: ignore[union-attr]
                    break
    finally:
        await app.close()
    assert app.queue.get(running.id).state is JobState.INTERRUPTED  # type: ignore[union-attr]
    assert fake_tools.kill_leftovers() == []
    fake_tools.set_scenario(ft.Scenario([PROBE]))
    again = await Reframe.create()
    try:
        assert [(j.id, j.state) for j in again.queue.list()] == [
            (done.id, JobState.DONE),
            (running.id, JobState.INTERRUPTED),
        ]
        await again.queue.retry(running.id)
        again.queue.start()
        [ended] = await again.queue.wait([running.id])
        assert ended.state is JobState.DONE, ended.error
    finally:
        await again.close()


async def test_naming_options_come_from_the_jobs_preset(env: Path) -> None:
    app = await Reframe.create()
    try:
        preset = app.presets.default()
        custom = await app.presets.create(preset, "With naming")
        assert not isinstance(custom, Exception)
        assert hasattr(custom, "id")
        custom.naming = NamingOptions(movie_template="{main_title} ({year})")  # type: ignore[union-attr]
        saved = await app.presets.save(custom)  # type: ignore[arg-type]
        assert hasattr(saved, "id")
        source = recorded("multitrack.mkv", env / "media" / "Show.mkv")
        job = draft(source, env / "out" / "x.mkv")
        naming = app.queue._runner._naming
        assert naming(job) is None  # no preset: Settings → Output
        job.preset_id = custom.id
        assert naming(job) == NamingOptions(movie_template="{main_title} ({year})")
        job.preset_id = "no-such-preset"
        assert naming(job) is None
    finally:
        await app.close()


async def test_the_when_done_action_goes_to_reframe_power(
    env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``Reframe`` gives the queue its power service (here a fake that only records: no real
    power call is possible); ``close()`` cancels the countdown and never runs it."""
    made: list[FakePower] = []

    def create(events: EventBus) -> FakePower:
        made.append(FakePower(events))
        return made[-1]

    monkeypatch.setattr("reframe.service.create_power_service", create)
    app = await Reframe.create()
    try:
        [power] = made
        assert app.queue._power is app.power
        assert app.power is cast(object, power)
        await app.settings.update(
            [{"op": "replace", "path": "/queue/when_done", "value": "shutdown"}]
        )
        source = recorded("multitrack.mkv", env / "media" / "Show.mkv")
        added = await app.queue.add(draft(source, env / "out" / "Show.mkv"))
        app.queue.start(job_ids=[added.id])  # as `reframe encode` does
        [ended] = await app.queue.wait([added.id])
        assert ended.state is JobState.DONE, ended.error
        assert power.scheduled == [("countdown-1", "shutdown", "1 job done")]
        assert power.pending is not None  # a front end can show it as soon as wait() returns
    finally:
        await app.close()
    assert power.closed
    assert power.cancelled == ["countdown-1"]
    assert power.executed == []
