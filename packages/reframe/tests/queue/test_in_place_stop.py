"""A running in-place mkvpropedit step is never killed by a cancel or by ``close()``: it
catches no signal and a kill can damage the source, so a stop waits for the step (the step's
time limit still applies). The mkvpropedit here is a gate that runs until the test opens it,
and the runner's refusal check of the harness source (not real Matroska) is replaced."""

from __future__ import annotations

import asyncio
import os
import textwrap
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from reframe.models import JobState
from reframe.queue import runner
from reframe.queue.watchdog import StepWatch
from reframe.tools import run_streaming
from reframe_testing import fake_tools as ft

from .conftest import Harness, encode_rule, queue_at, store_rows, tool_set
from .test_in_place_scheduling import in_place_job

pytestmark = pytest.mark.anyio

WRITTEN = (
    "The edit was already written to Movie.Source.mkv when {when}: mkvpropedit is never "
    "stopped while it writes the source (that can damage the file). The check of the edited "
    "file did not run."
)
CANCELLED = WRITTEN.format(when="the job was cancelled")
CLOSED = WRITTEN.format(when="Reframe was closed")


@dataclass
class Gate:
    folder: Path
    tool: Path

    @property
    def started(self) -> Path:
        return self.folder / "started"

    @property
    def finished(self) -> Path:
        return self.folder / "finished"

    def open(self) -> None:
        (self.folder / "gate").touch()


def gate_tool(folder: Path) -> Gate:
    """A stand-in for mkvpropedit that runs until :meth:`Gate.open` (at most 60 s)."""
    folder.mkdir(parents=True)
    script = folder / "gate.py"
    script.write_text(
        textwrap.dedent(
            f"""\
            import pathlib, sys, time
            folder = pathlib.Path({str(folder)!r})
            (folder / "started").write_text(" ".join(sys.argv[1:]), encoding="utf-8")
            deadline = time.monotonic() + 60
            while not (folder / "gate").exists():
                if time.monotonic() > deadline:
                    sys.exit(3)
                time.sleep(0.01)
            (folder / "finished").touch()
            """
        ),
        encoding="utf-8",
    )
    if os.name == "nt":
        tool = folder / "mkvpropedit.cmd"
        tool.write_text(f'@"{ft.PYTHON}" "{script}" %*\r\n', encoding="utf-8")
    else:
        tool = folder / "mkvpropedit"
        tool.write_text(f'#!/bin/sh\nexec "{ft.PYTHON}" "{script}" "$@"\n', encoding="utf-8")
        tool.chmod(0o755)
    return Gate(folder, tool)


@pytest.fixture
def gate(harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Gate]:
    made = gate_tool(tmp_path / "gate")
    harness.tools.tools = tool_set(harness.fake.ffmpeg, mkvpropedit=made.tool)
    monkeypatch.setattr(runner, "_in_place_refusal", lambda plan, source, probed: None)
    try:
        yield made
    finally:
        made.open()  # never leave it waiting (the harness closes the queue next)


def stop_requested(h: Harness, job_id: str) -> bool:
    """The job's stop was requested (or the job has already ended)."""
    active = h.queue._active.get(job_id)
    return active is None or active.token.cancelled


def last_state(h: Harness, job_id: str) -> tuple[str, str | None]:
    [*_, event] = [e for e in h.events_of(job_id) if e.type == "job.state"]
    return event.state.value, event.error


async def test_a_cancel_lets_the_running_edit_finish(harness: Harness, gate: Gate) -> None:
    h = harness
    job = await h.queue.add(in_place_job(h))
    h.queue.start()
    await h.wait_for(gate.started.exists)
    cancel = asyncio.create_task(h.queue.cancel(job.id))
    await h.wait_for(lambda: stop_requested(h, job.id))
    gate.open()
    await cancel
    ended = h.queue.get(job.id)
    assert ended is not None
    assert gate.finished.exists()  # mkvpropedit ran to its end
    assert ended.state is JobState.CANCELLED
    assert ended.error == CANCELLED
    assert ended.output_path == h.source_path
    log = h.log_text(job.id)
    assert "ended: exit code 0" in log
    assert "mkvpropedit is writing Movie.Source.mkv: it is let finish" in log


async def test_close_lets_the_running_edit_finish(harness: Harness, gate: Gate) -> None:
    """The queue's close() has no time limit of its own: it waits for every run to end."""
    h = harness
    job = await h.queue.add(in_place_job(h))
    h.queue.start()
    await h.wait_for(gate.started.exists)
    close = asyncio.create_task(h.queue.close())
    await h.wait_for(lambda: stop_requested(h, job.id))
    gate.open()
    await close
    assert gate.finished.exists()
    assert last_state(h, job.id) == ("interrupted", CLOSED)


async def test_a_cancel_of_a_paused_edit_resumes_it_and_lets_it_finish(
    harness: Harness, gate: Gate
) -> None:
    h = harness
    job = await h.queue.add(in_place_job(h))
    h.queue.start()
    await h.wait_for(gate.started.exists)
    await h.running_process(job.id)
    await h.queue.pause(job.id)  # the step's process is suspended
    gate.open()  # it sees the gate only when it runs again
    await h.queue.cancel(job.id)
    ended = h.queue.get(job.id)
    assert ended is not None
    assert gate.finished.exists()
    assert ended.state is JobState.CANCELLED
    assert ended.error == CANCELLED


async def test_a_cancel_before_the_edit_starts_changes_nothing(
    harness: Harness, gate: Gate
) -> None:
    h = harness
    h.sources.delay = 0.3  # the run's probe of the source is slow: the cancel comes first
    job = await h.queue.add(in_place_job(h))
    h.sources.calls.clear()
    h.queue.start()
    await h.wait_for(lambda: bool(h.sources.calls))
    await h.queue.cancel(job.id)
    ended = h.queue.get(job.id)
    assert ended is not None
    assert ended.state is JobState.CANCELLED
    assert ended.error is None
    assert not gate.started.exists()


IN_PLACE_TIMEOUT = (
    "mkvpropedit did not finish within 0.3 seconds and was stopped while it was editing "
    "Movie.Source.mkv in place: the file may be damaged."
)


async def test_the_time_limit_still_stops_a_hung_edit(harness: Harness, gate: Gate) -> None:
    h = harness
    h.queue._runner._step_time_limit = 0.3
    job = await h.queue.add(in_place_job(h))
    h.queue.start()
    [ended] = await h.queue.wait([job.id])
    assert ended.state is JobState.FAILED
    assert ended.error == IN_PLACE_TIMEOUT
    assert not gate.finished.exists()


async def test_a_cancelled_edit_that_hangs_is_stopped_by_the_time_limit(
    harness: Harness, gate: Gate
) -> None:
    """The cancel waits for the edit, but not for ever: the step's time limit ends it."""
    h = harness
    h.queue._runner._step_time_limit = 0.3
    job = await h.queue.add(in_place_job(h))
    h.queue.start()
    await h.wait_for(gate.started.exists)
    await h.queue.cancel(job.id)
    ended = h.queue.get(job.id)
    assert ended is not None
    assert ended.state is JobState.FAILED
    assert ended.error == IN_PLACE_TIMEOUT
    assert not gate.finished.exists()


async def test_a_cancelled_run_task_lets_the_edit_finish(harness: Harness, gate: Gate) -> None:
    """The run's asyncio task is cancelled from outside (an event loop that shuts down does this):
    the edit still ends first."""
    h = harness
    job = await h.queue.add(in_place_job(h))
    h.queue.start()
    await h.wait_for(gate.started.exists)
    task = h.queue._active[job.id].task
    assert task is not None
    task.cancel()
    await asyncio.sleep(0.05)  # give a kill time to happen
    gate.open()
    [ended] = await h.queue.wait([job.id])
    assert gate.finished.exists()
    assert ended.state is JobState.INTERRUPTED
    assert "it was let finish" in h.log_text(job.id)


async def test_an_encode_is_still_killed_at_once(harness: Harness) -> None:
    """Other steps keep their cancel: the process tree is killed (the fake hangs)."""
    h = harness
    h.scenario(encode_rule(ft.hang()))
    job = await h.queue.add(h.job("Encode"))
    h.queue.start()
    await h.running_process(job.id)
    await h.queue.cancel(job.id)
    ended = h.queue.get(job.id)
    assert ended is not None
    assert ended.state is JobState.CANCELLED
    assert ended.error is None
    assert "ended: stopped" in h.log_text(job.id)
    assert h.leftovers() == []


class LateLimit(StepWatch):
    """A step watch whose time limit fires only once :attr:`fire` is set (after the step's
    process has exited)."""

    fire = False

    def tick(self, mono: float, cpu: float | None, *, paused: bool) -> Any:
        if LateLimit.fire:
            return "timeout"
        return super().tick(mono, cpu, paused=paused)


async def test_a_time_limit_after_the_edit_ended_does_not_cancel_the_job(
    harness: Harness, gate: Gate, monkeypatch: pytest.MonkeyPatch
) -> None:
    """mkvpropedit exited 0; the step's time limit fires before the step's clean-up stops the
    watchdog."""
    h = harness
    LateLimit.fire = False
    monkeypatch.setattr(runner, "StepWatch", LateLimit)
    real = run_streaming

    async def late_limit(*args: Any, **kwargs: Any) -> Any:
        result = await real(*args, **kwargs)
        LateLimit.fire = True
        await asyncio.sleep(0.3)  # several watchdog ticks (0.05 s) before the step's clean-up
        return result

    checked: list[bool] = []

    def check(*args: Any, **kwargs: Any) -> list[str]:
        checked.append(True)
        return []

    monkeypatch.setattr(runner, "run_streaming", late_limit)
    monkeypatch.setattr(runner, "check_output", check)
    gate.open()  # mkvpropedit ends at once, exit code 0
    job = await h.queue.add(in_place_job(h))
    h.queue.start()
    [ended] = await h.queue.wait([job.id])
    assert gate.finished.exists()
    assert checked == [True]
    assert (ended.state, ended.error) == (JobState.DONE, None)
    assert ended.output_path == h.source_path
    assert "Checking the edited source Movie.Source.mkv" in h.log_text(job.id)


async def test_an_exit_0_that_came_with_the_time_limit_is_a_finished_edit(
    harness: Harness, gate: Gate, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``run_streaming`` reports ``cancelled`` when the token fired first, even if the process
    then exited 0 on its own before the kill (``returncode`` 0): that edit is complete and is
    checked."""
    h = harness
    real = run_streaming

    async def raced(*args: Any, **kwargs: Any) -> Any:
        result = await real(*args, **kwargs)
        kwargs["cancel"].cancel("timeout")
        return replace(result, cancelled=True)

    monkeypatch.setattr(runner, "run_streaming", raced)
    monkeypatch.setattr(runner, "check_output", lambda *args, **kwargs: [])
    gate.open()
    job = await h.queue.add(in_place_job(h))
    h.queue.start()
    [ended] = await h.queue.wait([job.id])
    assert (ended.state, ended.error) == (JobState.DONE, None)
    assert "ended: exit code 0" in h.log_text(job.id)


def test_a_time_limit_is_never_reported_as_a_cancel(tmp_path: Path) -> None:
    active = runner.ActiveJob(job_id="j")
    active.stop("timeout")
    plan: Any = None
    outcome = runner._stopped_after_edit(active, tmp_path / "Show.mkv", plan, 1, 1)
    assert outcome.state is JobState.FAILED
    assert outcome.stop_reason == "timeout"
    assert "when the job was cancelled" not in (outcome.error or "")
    assert (outcome.error or "").startswith("The edit was already written to Show.mkv")
    for reason, state in (("cancel", JobState.CANCELLED), ("close", JobState.INTERRUPTED)):
        stopped = runner.ActiveJob(job_id="j")
        stopped.stop(reason)  # type: ignore[arg-type]
        assert runner._stopped_after_edit(stopped, tmp_path / "Show.mkv", plan, 1, 1).state is state


async def test_an_event_loop_that_shuts_down_says_the_file_may_be_damaged(
    harness: Harness, gate: Gate
) -> None:
    """What ``asyncio.run`` does when it ends with tasks left (a second Ctrl+C): it cancels
    every task, the step's own run too, whose clean-up kills mkvpropedit."""
    h = harness
    job = await h.queue.add(in_place_job(h))
    h.queue.start()
    await h.wait_for(gate.started.exists)
    await h.running_process(job.id)
    me = asyncio.current_task()
    others = [
        task
        for task in asyncio.all_tasks()
        if task is not me and "TestRunner" not in getattr(task.get_coro(), "__qualname__", "")
    ]
    for task in others:
        task.cancel()
    await asyncio.gather(*others, return_exceptions=True)
    gate.open()
    damaged = (
        "Reframe was shut down while mkvpropedit was editing Movie.Source.mkv in place: "
        "mkvpropedit was stopped before it ended, so the file may be damaged."
    )
    log = h.log_text(job.id)
    assert f"Step 1/1 ended: stopped. {damaged}" in log
    assert "let finish" not in log
    assert last_state(h, job.id) == ("interrupted", damaged)
    assert not gate.finished.exists()  # it was killed


async def test_a_restored_in_place_job_that_was_running_may_be_damaged(harness: Harness) -> None:
    h = harness
    h.tools.tools = tool_set(h.fake.ffmpeg, mkvpropedit=h.fake.ffmpeg)
    edit = await h.queue.add(in_place_job(h))
    encode = await h.queue.add(h.job("Encode"))
    await h.queue.close()
    rows = []
    for added in (edit, encode):
        stored = h.queue.get(added.id)
        assert stored is not None
        stored.state = JobState.RUNNING
        stored.plan = h.plan(stored.settings)
        rows.append(stored)
    assert rows[0].plan is not None
    assert rows[0].plan.job_type == "metadata_edit"
    store_rows(h, *rows)
    again = queue_at(h)
    try:
        errors = [job.error for job in again.list()]
    finally:
        await again.close()
    assert errors == [
        "Reframe stopped while the job was running. If mkvpropedit was editing "
        "Movie.Source.mkv in place at that moment, the file may be damaged.",
        "Reframe stopped while the job was running.",
    ]


def inhibit_held(h: Harness) -> bool:
    return h.backend.held


@pytest.mark.parametrize("stop", ["cancel", "close"])
async def test_a_paused_edit_that_a_stop_resumes_is_shown_running(
    harness: Harness, gate: Gate, stop: str
) -> None:
    h = harness
    h.settings.queue.sleep_inhibit = True
    job = await h.queue.add(in_place_job(h))
    h.queue.start()
    await h.wait_for(gate.started.exists)
    process = await h.running_process(job.id)
    await h.queue.pause(job.id)
    assert h.queue.get(job.id).state is JobState.PAUSED  # type: ignore[union-attr]
    assert not inhibit_held(h)
    stopper = h.queue.cancel(job.id) if stop == "cancel" else h.queue.close()
    stopping = asyncio.ensure_future(stopper)
    await h.wait_for(lambda: stop_requested(h, job.id))
    await h.wait_for(lambda: h.states(job.id)[-1] == ("paused", "running"))
    assert process.status() != "stopped"  # it runs again …
    assert inhibit_held(h)  # … and the machine does not sleep under it
    gate.open()
    await stopping
    end = ("running", "cancelled") if stop == "cancel" else ("running", "interrupted")
    assert h.states(job.id)[-3:] == [("running", "paused"), ("paused", "running"), end]
    assert not inhibit_held(h)
    assert gate.finished.exists()
