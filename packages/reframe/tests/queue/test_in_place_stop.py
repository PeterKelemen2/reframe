"""A running in-place ``header_edit`` step writes the source in a worker thread, which nothing
can stop: a cancel, ``close()``, a pause or an event loop that shuts down waits for the write,
and the job's end says what the source holds. The writer here is the harness's fake, held
until the test releases it, and the runner's refusal check of the harness source (not real
Matroska) is replaced."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from reframe.metadata.header import HeaderEditResult
from reframe.models import JobState
from reframe.queue import runner
from reframe_testing import fake_tools as ft

from .conftest import Harness, encode_rule, queue_at, store_rows
from .test_in_place_scheduling import in_place_job

pytestmark = pytest.mark.anyio

WRITTEN = (
    "The edit was already written to Movie.Source.mkv when {when}: Reframe never stops a "
    "write into the source. The check of the edited file did not run."
)
CANCELLED = WRITTEN.format(when="the job was cancelled")
CLOSED = WRITTEN.format(when="Reframe was closed")
LET_FINISH = "while Reframe is writing the header of Movie.Source.mkv: it is let finish"
REFUSED = HeaderEditResult("refused", "header.no_room", "The SeekHead has no room")
FAILED = HeaderEditResult("failed", "header.write_error", "Input/output error", file_state="old")


@pytest.fixture
def held(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> Iterator[Harness]:
    """The harness with a writer that waits for ``h.writer.release()``."""
    harness.writer.hold = True
    harness.writer.effect = lambda: setattr(harness.sources.source.audio[0], "title", "Renamed")
    monkeypatch.setattr(runner, "_in_place_refusal", lambda plan, source, probed: None)
    try:
        yield harness
    finally:
        harness.writer.release()


def stop_requested(h: Harness, job_id: str) -> bool:
    """The job's stop was requested (or the job has already ended)."""
    active = h.queue._active.get(job_id)
    return active is None or active.token.cancelled


def last_state(h: Harness, job_id: str) -> tuple[str, str | None]:
    [*_, event] = [e for e in h.events_of(job_id) if e.type == "job.state"]
    return event.state.value, event.error


def inhibit_held(h: Harness) -> bool:
    return h.backend.held


async def writing(h: Harness) -> str:
    """Start an in-place job and wait until its write has started; its id."""
    job = await h.queue.add(in_place_job(h))
    h.queue.start()
    await h.wait_for(h.writer.started.is_set)
    return job.id


async def still_waiting(task: asyncio.Future[Any]) -> bool:
    await asyncio.sleep(0.2)
    return not task.done()


async def test_an_edit_runs_no_program_and_is_checked(held: Harness) -> None:
    h = held
    h.writer.release()
    job = await h.queue.add(in_place_job(h))
    h.queue.start()
    [ended] = await h.queue.wait([job.id])
    assert (ended.state, ended.error) == (JobState.DONE, None)
    [edit] = h.writer.edits
    assert edit.path == h.source_path
    assert [(t.track_type, t.number, t.name) for t in edit.tracks] == [("audio", 1, "Renamed")]
    assert h.fake.invocations() == []
    log = h.log_text(job.id)
    assert f"header_edit {h.source_path} audio 1: name=Renamed" in log
    assert "Step 1/1 ended: written after" in log
    assert "Checking the edited source Movie.Source.mkv" in log


async def test_a_cancel_lets_the_running_edit_finish(held: Harness) -> None:
    h = held
    job_id = await writing(h)
    cancel = asyncio.ensure_future(h.queue.cancel(job_id))
    await h.wait_for(lambda: stop_requested(h, job_id))
    assert await still_waiting(cancel)
    h.writer.release()
    await cancel
    ended = h.queue.get(job_id)
    assert ended is not None
    assert h.writer.finished.is_set()
    assert ended.state is JobState.CANCELLED
    assert ended.error == CANCELLED
    assert ended.output_path == h.source_path
    log = h.log_text(job_id)
    assert "Step 1/1 ended: written" in log
    assert f"The job is cancelled {LET_FINISH}" in log


async def test_close_lets_the_running_edit_finish(held: Harness) -> None:
    """The queue's close() has no time limit of its own: it waits for every run to end."""
    h = held
    job_id = await writing(h)
    close = asyncio.ensure_future(h.queue.close())
    await h.wait_for(lambda: stop_requested(h, job_id))
    assert await still_waiting(close)
    h.writer.release()
    await close
    assert h.writer.finished.is_set()
    assert last_state(h, job_id) == ("interrupted", CLOSED)
    assert f"Reframe is closing {LET_FINISH}" in h.log_text(job_id)


async def test_an_in_place_edit_has_no_time_limit(held: Harness) -> None:
    h = held
    h.queue._runner._step_time_limit = 0.1
    job_id = await writing(h)
    await asyncio.sleep(0.5)  # several watchdog ticks past the limit
    h.writer.release()
    [ended] = await h.queue.wait([job_id])
    assert (ended.state, ended.error) == (JobState.DONE, None)


async def test_a_pause_during_the_edit_holds_the_check_until_resume(held: Harness) -> None:
    """A thread cannot be suspended: the write ends, and nothing after it starts while the
    job is paused."""
    h = held
    job_id = await writing(h)
    await h.queue.pause(job_id)
    assert h.queue.get(job_id).state is JobState.PAUSED  # type: ignore[union-attr]
    h.writer.release()
    await h.wait_for(h.writer.finished.is_set)
    await asyncio.sleep(0.2)
    assert "Checking the edited source" not in h.log_text(job_id)
    assert h.queue.get(job_id).state is JobState.PAUSED  # type: ignore[union-attr]
    await h.queue.resume(job_id)
    [ended] = await h.queue.wait([job_id])
    assert (ended.state, ended.error) == (JobState.DONE, None)
    assert "Checking the edited source Movie.Source.mkv" in h.log_text(job_id)


async def test_a_cancel_after_a_paused_edit_ended_says_it_is_written(held: Harness) -> None:
    h = held
    job_id = await writing(h)
    await h.queue.pause(job_id)
    h.writer.release()
    await h.wait_for(h.writer.finished.is_set)
    await asyncio.sleep(0.1)
    await h.queue.cancel(job_id)
    ended = h.queue.get(job_id)
    assert ended is not None
    assert (ended.state, ended.error) == (JobState.CANCELLED, CANCELLED)


@pytest.mark.parametrize("stop", ["cancel", "close"])
async def test_a_paused_edit_that_a_stop_lets_finish_is_shown_running(
    held: Harness, stop: str
) -> None:
    h = held
    h.settings.queue.sleep_inhibit = True
    job_id = await writing(h)
    await h.queue.pause(job_id)
    assert h.queue.get(job_id).state is JobState.PAUSED  # type: ignore[union-attr]
    assert not inhibit_held(h)
    stopping = asyncio.ensure_future(
        h.queue.cancel(job_id) if stop == "cancel" else h.queue.close()
    )
    await h.wait_for(lambda: stop_requested(h, job_id))
    await h.wait_for(lambda: h.states(job_id)[-1] == ("paused", "running"))
    assert inhibit_held(h)  # the machine does not sleep under the write
    h.writer.release()
    await stopping
    end = ("running", "cancelled") if stop == "cancel" else ("running", "interrupted")
    assert h.states(job_id)[-3:] == [("running", "paused"), ("paused", "running"), end]
    assert not inhibit_held(h)
    assert h.writer.finished.is_set()


async def test_a_cancel_before_the_edit_starts_changes_nothing(held: Harness) -> None:
    h = held
    h.sources.delay = 0.3  # the run's probe of the source is slow: the cancel comes first
    job = await h.queue.add(in_place_job(h))
    h.sources.calls.clear()
    h.queue.start()
    await h.wait_for(lambda: bool(h.sources.calls))
    await h.queue.cancel(job.id)
    ended = h.queue.get(job.id)
    assert ended is not None
    assert (ended.state, ended.error) == (JobState.CANCELLED, None)
    assert h.writer.edits == []


async def test_a_refused_edit_fails_and_changed_nothing(held: Harness) -> None:
    h = held
    h.writer.result = REFUSED
    h.writer.release()
    job = await h.queue.add(in_place_job(h))
    h.queue.start()
    [ended] = await h.queue.wait([job.id])
    assert ended.state is JobState.FAILED
    assert ended.error == (
        "Reframe cannot edit the Matroska header of Movie.Source.mkv: The SeekHead has no "
        "room. Nothing was changed in the file."
    )
    assert "Checking the edited source" not in h.log_text(job.id)


async def test_a_failed_edit_says_the_source_holds_the_old_or_the_new_values(
    held: Harness,
) -> None:
    h = held
    h.writer.result = FAILED
    h.writer.release()
    job = await h.queue.add(in_place_job(h))
    h.queue.start()
    [ended] = await h.queue.wait([job.id])
    assert ended.state is JobState.FAILED
    assert ended.error == (
        "Writing the Matroska header of Movie.Source.mkv failed: Input/output error. The file "
        "holds all its old values."
    )


async def test_a_failed_edit_after_a_cancel_still_fails_with_what_the_source_holds(
    held: Harness,
) -> None:
    h = held
    h.writer.result = FAILED
    job_id = await writing(h)
    cancel = asyncio.ensure_future(h.queue.cancel(job_id))
    await h.wait_for(lambda: stop_requested(h, job_id))
    h.writer.release()
    await cancel
    ended = h.queue.get(job_id)
    assert ended is not None
    assert ended.state is JobState.FAILED
    assert ended.error is not None
    assert ended.error.endswith("The file holds all its old values.")


async def test_a_refused_edit_after_a_cancel_is_a_plain_cancel(held: Harness) -> None:
    h = held
    h.writer.result = REFUSED
    job_id = await writing(h)
    cancel = asyncio.ensure_future(h.queue.cancel(job_id))
    await h.wait_for(lambda: stop_requested(h, job_id))
    h.writer.release()
    await cancel
    ended = h.queue.get(job_id)
    assert ended is not None
    assert (ended.state, ended.error) == (JobState.CANCELLED, None)


LET_FINISHED = (
    "The job was stopped while Reframe was writing the header of Movie.Source.mkv: the write "
    "was let finish ({}). {}"
)


async def test_a_cancelled_run_task_lets_the_edit_finish(held: Harness) -> None:
    """The run's asyncio task is cancelled from outside: the write still ends first, and the
    job's end says what it left."""
    h = held
    job_id = await writing(h)
    task = h.queue._active[job_id].task
    assert task is not None
    task.cancel()
    await asyncio.sleep(0.1)
    assert not h.writer.finished.is_set()
    h.writer.release()
    [ended] = await h.queue.wait([job_id])
    assert ended.state is JobState.INTERRUPTED
    assert ended.error == LET_FINISHED.format(
        "written", "The new values are written; the check of the edited file did not run."
    )
    assert "Step 1/1 ended: written; the job was stopped during the write" in h.log_text(job_id)


async def test_a_cancelled_run_task_says_what_a_failed_write_left(held: Harness) -> None:
    h = held
    h.writer.result = FAILED
    job_id = await writing(h)
    task = h.queue._active[job_id].task
    assert task is not None
    task.cancel()
    h.writer.release()
    [ended] = await h.queue.wait([job_id])
    assert ended.error == LET_FINISHED.format(
        "failed (header.write_error): Input/output error",
        "The file holds all its old values.",
    )


async def test_an_event_loop_that_shuts_down_lets_the_edit_finish(held: Harness) -> None:
    """What ``asyncio.run`` does when it ends with tasks left (a second Ctrl+C): it cancels
    every task and waits for them. The wait for the writer is no task, so it is not cancelled."""
    h = held
    job_id = await writing(h)
    me = asyncio.current_task()
    others = [
        task
        for task in asyncio.all_tasks()
        if task is not me and "TestRunner" not in getattr(task.get_coro(), "__qualname__", "")
    ]
    for task in others:
        task.cancel()
    gathered = asyncio.ensure_future(asyncio.gather(*others, return_exceptions=True))
    assert await still_waiting(gathered)
    h.writer.release()
    await gathered
    assert h.writer.finished.is_set()
    assert last_state(h, job_id) == (
        "interrupted",
        LET_FINISHED.format(
            "written", "The new values are written; the check of the edited file did not run."
        ),
    )


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


async def test_a_restored_in_place_job_that_was_running_says_what_the_file_holds(
    harness: Harness,
) -> None:
    h = harness
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
        "Reframe stopped while the job was running. If Reframe was writing the header of "
        "Movie.Source.mkv at that moment, the file holds either all its old values or all the "
        "new ones, unless the computer lost power during the write: then check that the file "
        "still opens.",
        "Reframe stopped while the job was running.",
    ]
