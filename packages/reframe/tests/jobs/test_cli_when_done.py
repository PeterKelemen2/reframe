"""``reframe encode`` and the when-done countdown (C-15 with C-14 / C-11; decision 0038).

When Settings → Queue → When done is ``sleep`` or ``shutdown``, the queue starts the power
service's 60 s countdown as the last job ends; ``reframe encode`` shows it and Ctrl+C cancels
it. Here the queue is :class:`~.fake_queue.FakeQueue` and the power service is
:class:`FakePower` (the ``PowerService`` contract, with a short tick): **no test can reach a
real shutdown or suspend**, the fake only records what it would have done.
"""

from __future__ import annotations

import asyncio
import io
import itertools
import json
import signal
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from rich.console import Console

from reframe import cli
from reframe.cli import (
    EXIT_FAILED,
    EXIT_INTERRUPTED,
    EXIT_OK,
    CountdownView,
    countdown_text,
)
from reframe.events import EventBus
from reframe.models import AppSettings, JobSettings
from reframe.models.events import PowerAction, PowerCountdownEvent
from reframe.service import Reframe
from reframe_testing import fake_tools as ft

from .conftest import invoke, media_file, replay
from .fake_queue import Behaviour, FakeQueue

EPISODES = [f"Show.S01E{n:02d}.1080p.BluRay.x264-GRP.mkv" for n in (1, 2)]


class FakePower:
    """``PowerService`` (C-14 contract): ``schedule`` → ``started``, a ``tick`` per step, then
    ``executing`` (recorded, never run) or ``cancelled``."""

    _ids = itertools.count(1)

    def __init__(
        self,
        events: EventBus,
        *,
        seconds: int = 12,
        tick: float = 0.01,
        on_tick: Callable[[PowerCountdownEvent], None] | None = None,
    ) -> None:
        self.events = events
        self.seconds = seconds
        self.tick = tick
        self.on_tick = on_tick
        self.scheduled: list[PowerAction] = []
        self.executed: list[PowerAction] = []
        self.cancelled: list[str] = []
        self.closed = False
        self._pending: PowerCountdownEvent | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def pending(self) -> PowerCountdownEvent | None:
        return self._pending

    def _publish(self, event: PowerCountdownEvent) -> None:
        self._pending = None if event.phase in ("executing", "cancelled") else event
        self.events.publish(event)

    def schedule(self, action: PowerAction, *, reason: str = "") -> str:
        del reason
        self.cancel()
        countdown_id = f"c-{next(self._ids)}"
        self.scheduled.append(action)
        self._task = asyncio.get_running_loop().create_task(self._run(countdown_id, action))
        return countdown_id

    async def _run(self, countdown_id: str, action: PowerAction) -> None:
        def event(phase: str, left: int) -> PowerCountdownEvent:
            return PowerCountdownEvent(
                countdown_id=countdown_id,
                action=action,
                phase=phase,  # type: ignore[arg-type]
                seconds_left=left,
            )

        self._publish(event("started", self.seconds))
        for left in range(self.seconds - 1, -1, -1):
            await asyncio.sleep(self.tick)
            tick = event("tick", left)
            self._publish(tick)
            if self.on_tick is not None:
                self.on_tick(tick)
        await asyncio.sleep(self.tick)
        self.executed.append(action)  # a real service would run the executor here
        self._publish(event("executing", 0))

    def cancel(self, countdown_id: str | None = None) -> bool:
        pending = self._pending
        if pending is None or (countdown_id is not None and countdown_id != pending.countdown_id):
            return False
        if self._task is not None:
            self._task.cancel()
        self.cancelled.append(pending.countdown_id)
        self._publish(pending.model_copy(update={"phase": "cancelled"}))
        return True

    async def close(self) -> None:
        self.closed = True
        if self._pending is not None:
            self.cancel()


class Setup:
    """``cli.get_queue`` gives a :class:`FakeQueue`; ``app.power`` becomes a
    :class:`FakePower`; like the real queue, a watcher schedules ``action`` when every job
    has ended (``None``: no countdown starts)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.action: PowerAction | None = "shutdown"
        self.behaviour: Callable[[JobSettings], Behaviour] = lambda _job: "done"
        self.power_options: dict[str, object] = {}
        self.queue: FakeQueue | None = None
        self.power: FakePower | None = None
        monkeypatch.setattr(cli, "get_queue", self.make)

    def make(self, app: Reframe) -> FakeQueue:
        queue = FakeQueue(
            app.events, log_dir=self.tmp_path / "logs", validate=None, behaviour=self.behaviour
        )
        power = FakePower(app.events, **self.power_options)  # type: ignore[arg-type]
        app.power = power  # type: ignore[assignment]
        self.queue, self.power = queue, power
        if self.action is not None:
            asyncio.get_running_loop().create_task(self._when_done(app.events, queue, power))
        return queue

    async def _when_done(self, events: EventBus, queue: FakeQueue, power: FakePower) -> None:
        async for _event in events.subscribe(types={"job.state"}):
            jobs = queue.list()
            if jobs and all(job.state in cli.FINAL_STATES for job in jobs):
                assert self.action is not None
                power.schedule(self.action)
                return


@pytest.fixture
def setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Setup:
    return Setup(monkeypatch, tmp_path)


def when_done(tmp_path: Path, action: str) -> None:
    """Settings → Queue → When done, in the private config folder."""
    folder = tmp_path / "config"
    folder.mkdir(parents=True, exist_ok=True)
    settings = AppSettings.model_validate({"queue": {"when_done": action}})
    (folder / "settings.json").write_text(
        json.dumps(settings.model_dump(mode="json")), encoding="utf-8"
    )


@pytest.fixture
def season(cli_env: ft.FakeTools, tmp_path: Path) -> Path:
    replay(cli_env, "multitrack")
    folder = tmp_path / "media" / "Show.S01"
    for name in EPISODES:
        media_file(folder, name)
    return folder


def countdown_lines(stdout: str) -> list[str]:
    lines = stdout.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("Summary: "))
    return lines[start + 1 :]


def test_a_shutdown_countdown_is_shown_until_it_runs(
    season: Path, setup: Setup, tmp_path: Path
) -> None:
    when_done(tmp_path, "shutdown")
    result = invoke("encode", str(season))
    assert result.exit_code == EXIT_OK, result.output
    assert countdown_lines(result.stdout) == [
        "Shutting down in 12 s — press Ctrl+C to cancel",
        "Shutting down in 10 s — press Ctrl+C to cancel",
        "Shutting down now.",
    ]
    assert setup.power is not None
    assert setup.power.scheduled == ["shutdown"]
    assert setup.power.executed == ["shutdown"]
    assert setup.power.cancelled == []


def test_a_sleep_countdown(season: Path, setup: Setup, tmp_path: Path) -> None:
    when_done(tmp_path, "sleep")
    setup.action = "sleep"
    setup.power_options = {"seconds": 3}
    result = invoke("encode", str(season))
    assert result.exit_code == EXIT_OK, result.output
    assert countdown_lines(result.stdout) == [
        "Going to sleep in 3 s — press Ctrl+C to cancel",
        "Going to sleep now.",
    ]


def test_the_jobs_exit_code_stands(season: Path, setup: Setup, tmp_path: Path) -> None:
    """A failed job: the queue still runs the when-done action (C-11), exit 1."""
    when_done(tmp_path, "shutdown")
    setup.behaviour = lambda job: "fail" if "E02" in str(job.source.path) else "done"
    setup.power_options = {"seconds": 2}
    result = invoke("encode", str(season))
    assert result.exit_code == EXIT_FAILED
    assert countdown_lines(result.stdout)[-1] == "Shutting down now."


@pytest.mark.anyio
async def test_ctrl_c_cancels_the_countdown(season: Path, setup: Setup, tmp_path: Path) -> None:
    """Cancelling the command (how asyncio.run reacts to Ctrl+C on every OS) during the
    countdown cancels it through ``power.cancel``: nothing runs, exit 130."""
    when_done(tmp_path, "shutdown")
    setup.power_options = {"seconds": 60, "tick": 0.05}
    task = asyncio.create_task(cli.run_encode([season], preset=None, output=None))
    deadline = time.monotonic() + 30
    while setup.power is None or setup.power.pending is None:
        assert time.monotonic() < deadline, "the countdown did not start"
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.12)  # a tick or two
    task.cancel()
    assert await asyncio.wait_for(task, 30) == EXIT_INTERRUPTED
    power = setup.power
    assert power.executed == []
    assert power.cancelled == ["c-" + power.cancelled[0].split("-")[1]]
    assert power.pending is None


def _interrupt(event: PowerCountdownEvent) -> None:
    if event.seconds_left == 58:
        signal.raise_signal(signal.SIGINT)


@pytest.mark.skipif(
    signal.getsignal(signal.SIGINT) is not signal.default_int_handler,
    reason="needs Python's own SIGINT handler (asyncio.run replaces it)",
)
def test_a_real_sigint_cancels_the_countdown(season: Path, setup: Setup, tmp_path: Path) -> None:
    when_done(tmp_path, "shutdown")
    setup.power_options = {"seconds": 60, "tick": 0.02, "on_tick": _interrupt}
    result = invoke("encode", str(season))
    assert result.exit_code == EXIT_INTERRUPTED, result.output
    assert (
        "Interrupted: the countdown is cancelled, the computer will not shut down." in result.stderr
    )
    assert setup.power is not None
    assert setup.power.executed == []
    assert len(setup.power.cancelled) == 1
    assert "Summary: 2 done, 0 failed, 0 cancelled, 0 not queued." in result.stdout


def test_a_countdown_cancelled_elsewhere(season: Path, setup: Setup, tmp_path: Path) -> None:
    """Another front end (the web UI) cancels it: the command ends with the jobs' code."""
    when_done(tmp_path, "shutdown")

    def cancel_at_55(event: PowerCountdownEvent) -> None:
        if event.seconds_left == 55 and setup.power is not None:
            setup.power.cancel(event.countdown_id)

    setup.power_options = {"seconds": 60, "on_tick": cancel_at_55}
    result = invoke("encode", str(season))
    assert result.exit_code == EXIT_OK, result.output
    assert countdown_lines(result.stdout) == [
        "Shutting down in 60 s — press Ctrl+C to cancel",
        "Cancelled: the computer will not shut down.",
    ]


@pytest.mark.parametrize("setting", ["nothing", "quit"])
def test_no_wait_for_other_settings(
    season: Path, setup: Setup, tmp_path: Path, setting: str
) -> None:
    """``quit`` in a CLI: the command ends by itself (decision 0038); closing Reframe
    cancels the countdown, so nothing waits and nothing is shown."""
    when_done(tmp_path, setting)
    setup.action = "quit" if setting == "quit" else None
    started = time.monotonic()
    result = invoke("encode", str(season))
    assert result.exit_code == EXIT_OK, result.output
    assert countdown_lines(result.stdout) == []
    assert time.monotonic() - started < 10
    assert setup.power is not None
    assert setup.power.executed == []
    assert setup.power.closed


def test_no_countdown_ends_after_the_start_wait(
    season: Path, setup: Setup, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Shutdown is set but no countdown starts (the power service is not available): the
    command ends after the short start wait, as before."""
    monkeypatch.setattr(cli, "COUNTDOWN_START_WAIT", 0.2)
    when_done(tmp_path, "shutdown")
    setup.action = None
    result = invoke("encode", str(season))
    assert result.exit_code == EXIT_OK, result.output
    assert countdown_lines(result.stdout) == []


# --------------------------------------------------------------------------- the view


def _event(phase: str, left: int, action: PowerAction = "shutdown") -> PowerCountdownEvent:
    return PowerCountdownEvent(
        countdown_id="c-1",
        action=action,
        phase=phase,  # type: ignore[arg-type]
        seconds_left=left,
    )


def test_countdown_text() -> None:
    assert countdown_text(_event("started", 60)) == "Shutting down in 60 s — press Ctrl+C to cancel"
    assert countdown_text(_event("tick", 7, "sleep")) == (
        "Going to sleep in 7 s — press Ctrl+C to cancel"
    )
    assert countdown_text(_event("executing", 0)) == "Shutting down now."
    assert countdown_text(_event("cancelled", 3, "sleep")) == (
        "Cancelled: the computer will not go to sleep."
    )


def test_countdown_view_lines_every_ten_seconds() -> None:
    out = io.StringIO()
    view = CountdownView(Console(file=out, width=100), live=False)
    view.show(_event("started", 60))
    for left in range(59, -1, -1):
        view.show(_event("tick", left))
    view.show(_event("executing", 0))
    assert out.getvalue().splitlines() == [
        *(f"Shutting down in {n} s — press Ctrl+C to cancel" for n in (60, 50, 40, 30, 20, 10)),
        "Shutting down now.",
    ]


def test_countdown_view_live() -> None:
    out = io.StringIO()
    view = CountdownView(Console(file=out, width=100, force_terminal=True), live=True)
    view.show(_event("started", 60))
    view.show(_event("tick", 59))
    view.show(_event("cancelled", 59))
    view.close()
    assert "Cancelled: the computer will not shut down." in out.getvalue()


def test_no_wait_when_nothing_was_queued(
    season: Path, setup: Setup, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A job with errors is not queued; with no job the queue never ends one, so nothing
    waits for a countdown."""
    monkeypatch.setattr(cli, "COUNTDOWN_START_WAIT", 60.0)
    when_done(tmp_path, "shutdown")
    setup.action = None
    episode = season / EPISODES[0]
    started = time.monotonic()
    result = invoke("encode", str(episode), "-o", str(episode))
    assert result.exit_code == EXIT_FAILED
    assert "Nothing to encode." in result.stdout
    assert time.monotonic() - started < 30
