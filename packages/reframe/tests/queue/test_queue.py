"""The queue's behaviour (C-11): the contract of ``QueueService``, pause and resume, cancel,
parallel slots, when-done, sleep inhibit, close and restart recovery, and the event order."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys

import psutil
import pytest

from reframe.models import (
    AppWarningEvent,
    JobState,
    NotificationEvent,
    QueueChangedEvent,
)
from reframe.platform.sleep import SleepInhibitor
from reframe.queue import JobStateError, QueueService, UnknownJobError
from reframe.queue.store import row_of
from reframe.service import ReframeClosedError
from reframe_testing import fake_tools as ft

from .conftest import Harness, encode_rule

pytestmark = pytest.mark.anyio

#: An encode that runs until it is cancelled (or for 50 s): a first block, then quiet.
LONG = encode_rule(ft.progress(blocks=1, end=False), ft.write_output(100), ft.hang())


def running_at_once(h: Harness) -> int:
    """The most jobs that were running or paused at the same time (from the events)."""
    active: set[str] = set()
    most = 0
    for event in h.events.published:
        if event.type != "job.state":
            continue
        if event.state in (JobState.RUNNING, JobState.PAUSED):
            active.add(event.job_id)
        else:
            active.discard(event.job_id)
        most = max(most, len(active))
    return most


# --------------------------------------------------------------------------- one run


async def test_a_run_and_its_events_in_order(harness: Harness) -> None:
    h = harness
    h.scenario(encode_rule(ft.progress(blocks=4, interval=0.02), ft.write_output()))
    ended = await h.run_one(h.job())
    assert ended.state is JobState.DONE
    assert ended.output_path == h.tmp / "out" / "Movie.mkv"
    assert ended.started_at is not None
    assert ended.finished_at is not None
    assert ended.progress is not None
    assert ended.progress.percent == 100.0
    assert ended.plan is not None
    assert ended.plan.output_final == ended.output_path
    events = h.events_of(ended.id)
    kinds = h.kinds(ended.id)
    # waiting (add; then queue.changed, which has no job id), running, 0 %
    assert kinds[:3] == ["job.state", "job.state", "job.progress"]
    # progress and log batches while it runs, as they come
    assert set(kinds[3:-3]) <= {"job.progress", "job.log"}
    # the last progress (100 %), the last log batch, then the end state
    assert kinds[-3:] == ["job.progress", "job.log", "job.state"]
    assert h.states(ended.id) == [(None, "waiting"), ("waiting", "running"), ("running", "done")]
    # queue.changed comes right after the add's job.state.
    published = h.events.published
    first = published.index(events[0])
    changed = published[first + 1]
    assert isinstance(changed, QueueChangedEvent)
    assert changed.job_ids == [ended.id]
    percents = [e.progress.percent for e in events if e.type == "job.progress"]
    assert percents == sorted(percents)
    assert percents[0] == 0.0
    assert percents[-1] == 100.0
    log = h.log_text(ended.id)
    assert log.startswith(f"=== Reframe job {ended.id}: run started ")
    lines = [line for e in events if e.type == "job.log" for line in e.lines]
    assert lines == log.splitlines()  # every line, nothing dropped at this rate
    assert h.backend.holds == ["Reframe is encoding Movie.Source.mkv"]
    assert h.backend.frees == 1
    assert h.leftovers() == []


async def test_job_log_events_are_rate_limited(harness: Harness) -> None:
    h = harness
    h.queue._runner.log_interval = 30.0  # one batch at the end
    noise = "".join(f"[libx264 @ 0x1] line {n}\n" for n in range(500))
    h.scenario(encode_rule(ft.stderr(noise), ft.progress(blocks=1), ft.write_output()))
    ended = await h.run_one(h.job())
    [batch] = [e for e in h.events_of(ended.id) if e.type == "job.log"]
    assert len(batch.lines) == 200
    assert batch.dropped > 300
    assert batch.lines[-1].startswith("[")  # the newest lines are kept  # type: ignore[union-attr]
    assert "line 499" in h.log_text(ended.id)  # the file has them all


# --------------------------------------------------------------------------- pause, resume


async def test_pause_suspends_the_tree_and_resume_continues(harness: Harness) -> None:
    h = harness
    h.scenario(
        encode_rule(
            ft.progress(blocks=1, end=False),
            ft.spawn_grandchild(),
            ft.progress(blocks=10, interval=0.03),
            ft.write_output(),
        )
    )
    added = await h.queue.add(h.job())
    h.queue.start()
    await h.first_event(added.id, "job.progress", limit=20)
    await h.wait_for(lambda: len(h.fake.pids()) >= 2)
    await h.queue.pause(added.id)
    assert h.queue.get(added.id).state is JobState.PAUSED  # type: ignore[union-attr]
    assert h.backend.frees == 1  # the sleep inhibit is released while paused
    pids = h.fake.pids()
    if sys.platform != "win32":
        await h.wait_for(
            lambda: all(psutil.Process(p).status() == psutil.STATUS_STOPPED for p in pids)
        )
    count = len(h.events.published)
    await asyncio.sleep(0.3)
    assert not [e for e in h.events.published[count:] if e.type == "job.progress"]
    await h.queue.resume(added.id)
    assert h.backend.holds == ["Reframe is encoding Movie.Source.mkv"] * 2
    [ended] = await h.queue.wait([added.id])
    assert ended.state is JobState.DONE
    assert h.states(added.id) == [
        (None, "waiting"),
        ("waiting", "running"),
        ("running", "paused"),
        ("paused", "running"),
        ("running", "done"),
    ]
    # A helper that the tool started and left running is not the queue's business once the
    # step ended normally (real FFmpeg starts none); only it may be left.
    grandchildren = {i.pid for i in h.fake.invocations() if i.role == "grandchild"}
    assert set(h.leftovers()) <= grandchildren


async def test_pause_before_the_first_step(harness: Harness) -> None:
    h = harness
    h.sources.delay = 0.2  # a slow probe: the job is still preparing
    added = await h.queue.add(h.job())
    h.sources.delay = 0.2
    h.queue.start()
    await h.first_event(added.id, "job.state", state="running")
    await h.queue.pause()
    await asyncio.sleep(0.4)
    assert h.fake.calls("ffmpeg") == []  # the step did not start while paused
    await h.queue.resume()
    [ended] = await h.queue.wait([added.id])
    assert ended.state is JobState.DONE


async def test_pause_and_resume_of_other_states_do_nothing(harness: Harness) -> None:
    h = harness
    added = await h.queue.add(h.job())
    await h.queue.pause(added.id)
    await h.queue.resume(added.id)
    await h.queue.pause()
    assert h.queue.get(added.id).state is JobState.WAITING  # type: ignore[union-attr]


# --------------------------------------------------------------------------- cancel


@pytest.mark.parametrize("paused", [False, True])
async def test_cancel_a_running_job(harness: Harness, paused: bool) -> None:
    h = harness
    h.settings.output.partial_file = "keep"  # a cancel removes the .part file anyway
    job = h.job()
    part = h.plan(job).output_tmp
    h.scenario(LONG)
    added = await h.queue.add(job)
    h.queue.start()
    await h.first_event(added.id, "job.progress", limit=20)
    await h.wait_for(part.exists)
    if paused:
        await h.queue.pause(added.id)
    await h.queue.cancel(added.id)
    ended = h.queue.get(added.id)
    assert ended is not None
    assert ended.state is JobState.CANCELLED
    assert ended.error is None
    assert not part.exists()
    assert h.leftovers() == []
    assert h.states(added.id)[-1] == ("paused" if paused else "running", "cancelled")
    assert "Job cancelled" in h.log_text(added.id)


async def test_cancel_all_cancels_waiting_jobs_too(harness: Harness) -> None:
    """``cancel()`` (the CLI's Ctrl+C): every running job is stopped with its ``.part`` file
    removed, every waiting one is marked cancelled; it returns when they have ended."""
    h = harness
    h.settings.queue.parallel_jobs = 2
    h.scenario(LONG)
    first = await h.queue.add(h.job("A"))
    third = await h.queue.add(h.job("C"))
    second = await h.queue.add(h.job("B"), position=2)
    h.settings.queue.parallel_jobs = 2
    h.queue.start()
    await h.first_event(first.id, "job.progress", limit=20)
    await h.first_event(third.id, "job.progress", limit=20)
    parts = [h.tmp / "out" / "A.part.mkv", h.tmp / "out" / "C.part.mkv"]
    await h.wait_for(lambda: all(p.exists() for p in parts))
    await h.queue.cancel()
    assert [j.state for j in h.queue.list()] == [JobState.CANCELLED] * 3
    assert not any(p.exists() for p in parts)
    assert h.leftovers() == []
    assert h.states(second.id) == [(None, "waiting"), ("waiting", "cancelled")]
    assert h.of_type("notification") == []  # cancelled by the user: no when-done
    await h.queue.cancel(first.id)  # an ended job: nothing happens


async def test_cancel_a_job_that_was_just_scheduled(harness: Harness) -> None:
    h = harness
    added = await h.queue.add(h.job())
    h.queue.start()  # scheduled, its task has not run yet
    await h.queue.cancel(added.id)
    assert h.queue.get(added.id).state is JobState.CANCELLED  # type: ignore[union-attr]
    assert h.fake.calls("ffmpeg") == []


# --------------------------------------------------------------------------- parallel


async def test_parallel_slots_from_the_settings(harness: Harness) -> None:
    h = harness
    h.settings.queue.parallel_jobs = 2
    h.scenario(encode_rule(ft.progress(blocks=6, interval=0.05), ft.write_output()))
    ids = [(await h.queue.add(h.job(name))).id for name in "ABCD"]
    h.queue.start()
    await h.wait_for(lambda: len(h.of_type("job.state")) >= 4 + 3)  # two started and one ended
    h.settings.queue.parallel_jobs = 1  # read again when a slot frees
    ended = await h.queue.wait()
    assert [j.state for j in ended] == [JobState.DONE] * 4
    assert [j.id for j in ended] == ids
    assert running_at_once(h) == 2
    starts = [e.job_id for e in h.of_type("job.state") if e.state is JobState.RUNNING]  # type: ignore[union-attr]
    assert starts == ids  # queue order


async def test_two_jobs_with_one_output_never_run_together(harness: Harness) -> None:
    h = harness
    h.settings.queue.parallel_jobs = 3
    h.scenario(encode_rule(ft.progress(blocks=4, interval=0.05), ft.write_output()))
    first = await h.queue.add(h.job("Same"))
    second = await h.queue.add(h.job("Same"))
    third = await h.queue.add(h.job("Other"))
    h.queue.start()
    ended = await h.queue.wait()
    assert [j.state for j in ended] == [JobState.DONE] * 3
    starts = [e.job_id for e in h.of_type("job.state") if e.state is JobState.RUNNING]  # type: ignore[union-attr]
    assert starts == [first.id, third.id, second.id]
    assert {j.output_path for j in ended} == {
        h.tmp / "out" / "Same.mkv",
        h.tmp / "out" / "Same (1).mkv",
        h.tmp / "out" / "Other.mkv",
    }


async def test_stop_takes_no_new_jobs(harness: Harness) -> None:
    h = harness
    h.scenario(encode_rule(ft.progress(blocks=3, interval=0.05), ft.write_output()))
    first = await h.queue.add(h.job("A"))
    second = await h.queue.add(h.job("B"))
    h.queue.start()
    await h.first_event(first.id, "job.state", state="running")
    await h.queue.stop()
    assert not h.queue._processing
    await h.queue.wait([first.id])
    await asyncio.sleep(0.1)
    assert h.queue.get(second.id).state is JobState.WAITING  # type: ignore[union-attr]
    assert h.of_type("notification") == []  # the queue is not empty: no when-done


async def test_start_with_job_ids_leaves_other_waiting_jobs_alone(harness: Harness) -> None:
    """``start(job_ids=…)`` (the CLI): two foreign jobs waiting in the shared store are not
    started and keep their state and position; the runner goes idle when the given jobs
    have ended, and ``when_done`` runs for them."""
    h = harness
    h.settings.queue.parallel_jobs = 4
    h.settings.queue.when_done = "notify"
    foreign = [(await h.queue.add(h.job(name))).id for name in ("Old1", "Old2")]
    own = [(await h.queue.add(h.job(name))).id for name in ("New1", "New2")]
    with pytest.raises(UnknownJobError):
        h.queue.start(job_ids=["nope"])
    assert not h.queue._processing
    h.queue.start(job_ids=own)
    ended = await h.queue.wait(own)
    assert [j.state for j in ended] == [JobState.DONE, JobState.DONE]
    await h.wait_for(lambda: not h.queue._processing)
    jobs = h.queue.list()
    assert [(j.id, j.state, j.position) for j in jobs[:2]] == [
        (foreign[0], JobState.WAITING, 0),
        (foreign[1], JobState.WAITING, 1),
    ]
    assert all(h.states(job_id) == [(None, "waiting")] for job_id in foreign)
    [note] = h.of_type("notification")
    assert note.message == "2 jobs done."  # type: ignore[union-attr]
    h.queue.start()  # no ids: every waiting job, as the contract says
    assert [j.state for j in await h.queue.wait(foreign)] == [JobState.DONE] * 2


async def test_start_with_job_ids_never_narrows_a_running_start(harness: Harness) -> None:
    h = harness
    h.scenario(encode_rule(ft.progress(blocks=3, interval=0.05), ft.write_output()))
    a, b, c = [(await h.queue.add(h.job(name))).id for name in "ABC"]
    h.queue.start(job_ids=[a])
    h.queue.start(job_ids=[b])  # added to the running start
    assert [j.state for j in await h.queue.wait([a, b])] == [JobState.DONE] * 2
    await h.wait_for(lambda: not h.queue._processing)
    assert h.queue.get(c).state is JobState.WAITING  # type: ignore[union-attr]
    h.queue.start()
    h.queue.start(job_ids=[a])  # does not narrow "every job"
    assert (await h.queue.wait([c]))[0].state is JobState.DONE
    assert h.queue._processing  # "every job" stays on, waiting for new jobs
    await h.queue.stop()
    h.queue.start(job_ids=[a])  # nothing of it is waiting: idle at once
    assert not h.queue._processing


async def test_start_and_stop_are_not_saved(harness: Harness) -> None:
    h = harness
    first = await h.queue.add(h.job())
    h.queue.start(job_ids=[first.id])
    await h.queue.wait()
    h.queue.start()
    await h.queue.stop()
    await h.queue.add(h.job("Second"))
    assert not h.queue._processing
    await h.queue.close()
    again = queue_at(h)
    await again._restore()
    try:
        assert not again._processing  # a restored queue is idle until start()
        assert [j.state for j in again.list()] == [JobState.DONE, JobState.WAITING]
    finally:
        await again.close()


# --------------------------------------------------------------------------- when done


async def test_when_done_notify(harness: Harness) -> None:
    h = harness
    h.settings.queue.when_done = "notify"
    h.scenario(
        ft.Rule(tool="ffmpeg", argv_has=["matroska"], argv_contains=["Bad"], exit_code=1),
    )
    await h.queue.add(h.job("Good"))
    await h.queue.add(h.job("Bad"))
    h.queue.start()
    await h.queue.wait()
    await h.wait_for(lambda: bool(h.of_type("notification")))
    [note] = h.of_type("notification")
    assert isinstance(note, NotificationEvent)
    assert (note.title, note.message, note.level) == (
        "Queue finished",
        "1 job done, 1 failed.",
        "warning",
    )
    assert h.events.published[-1] is note  # after the last job's events


@pytest.mark.parametrize("action", ["quit", "sleep", "shutdown"])
async def test_power_actions_are_reported_as_not_done(harness: Harness, action: str) -> None:
    h = harness
    h.settings.queue.when_done = action  # type: ignore[assignment]
    await h.run_one(h.job())
    [warning] = [e for e in h.of_type("app.warning") if e.code == "queue.when_done_unavailable"]  # type: ignore[union-attr]
    assert isinstance(warning, AppWarningEvent)
    assert "1 job done" in warning.message
    assert "nothing was done" in warning.message


async def test_when_done_nothing_and_sleep_inhibit_off(harness: Harness) -> None:
    h = harness
    h.settings.queue.sleep_inhibit = False
    await h.run_one(h.job())
    assert h.of_type("notification") == []
    assert h.backend.holds == []


# --------------------------------------------------------------------------- the contract


async def test_add_position_list_get_reorder_remove(harness: Harness) -> None:
    h = harness
    a = await h.queue.add(h.job("A"))
    b = await h.queue.add(h.job("B"))
    c = await h.queue.add(h.job("C"), position=0)
    d = await h.queue.add(h.job("D"), position=99)
    assert [j.id for j in h.queue.list()] == [c.id, a.id, b.id, d.id]
    assert [j.position for j in h.queue.list()] == [0, 1, 2, 3]
    assert h.queue.get("nope") is None
    copy = h.queue.list()[0]
    copy.error = "changed"
    assert h.queue.get(c.id).error is None  # type: ignore[union-attr]
    await h.queue.reorder([d.id, a.id])  # the places of a and d: 1 and 3
    assert [j.id for j in h.queue.list()] == [c.id, d.id, b.id, a.id]
    await h.queue.reorder([a.id, b.id, c.id, d.id])
    assert [j.id for j in h.queue.list()] == [a.id, b.id, c.id, d.id]
    with pytest.raises(ValueError, match="twice"):
        await h.queue.reorder([a.id, a.id])
    with pytest.raises(UnknownJobError):
        await h.queue.reorder(["nope"])
    await h.queue.remove(b.id)
    assert [j.id for j in h.queue.list()] == [a.id, c.id, d.id]
    orders = [e.job_ids for e in h.of_type("queue.changed")]  # type: ignore[union-attr]
    assert orders[-1] == [a.id, c.id, d.id]
    assert len(orders) == 4 + 2 + 1
    with pytest.raises(UnknownJobError):
        await h.queue.remove(b.id)


async def test_remove_a_running_job_is_refused(harness: Harness) -> None:
    h = harness
    h.scenario(LONG)
    added = await h.queue.add(h.job())
    h.queue.start()
    await h.first_event(added.id, "job.progress", limit=20)
    with pytest.raises(JobStateError):
        await h.queue.remove(added.id)
    await h.queue.cancel(added.id)
    log = h.queue.log_path(added.id)
    assert log.exists()
    await h.queue.remove(added.id)
    assert not log.exists()  # the log goes with the job


async def test_retry(harness: Harness) -> None:
    h = harness
    h.scenario(encode_rule(exit_code=1))
    failed = await h.run_one(h.job())
    assert failed.state is JobState.FAILED
    h.scenario()
    retried = await h.queue.retry(failed.id)
    assert (retried.state, retried.error, retried.started_at) == (JobState.WAITING, None, None)
    [ended] = await h.queue.wait([failed.id])
    assert ended.state is JobState.DONE
    with pytest.raises(JobStateError):
        await h.queue.retry(failed.id)  # done
    assert h.states(failed.id)[-3:] == [
        ("failed", "waiting"),
        ("waiting", "running"),
        ("running", "done"),
    ]
    log = h.log_text(failed.id)
    assert log.count("=== Reframe job") == 2  # the retry appends a new run
    await h.queue.stop()
    waiting = await h.queue.add(h.job("W"))
    assert (await h.queue.retry(waiting.id)).state is JobState.WAITING


async def test_wait_for_nothing_and_unknown_jobs(harness: Harness) -> None:
    h = harness
    assert await h.queue.wait() == []
    with pytest.raises(UnknownJobError):
        await h.queue.wait(["nope"])
    added = await h.queue.add(h.job())
    waiter = asyncio.ensure_future(h.queue.wait([added.id]))
    await asyncio.sleep(0.05)
    assert not waiter.done()  # the queue is not started
    await h.queue.remove(added.id)
    assert await waiter == []
    assert h.queue.log_path("x") == h.tmp / "data" / "logs" / "x.log"


async def test_closed_queue(harness: Harness) -> None:
    h = harness
    added = await h.queue.add(h.job())
    await h.queue.close()
    await h.queue.close()
    for call in (
        h.queue.add(h.job()),
        h.queue.remove(added.id),
        h.queue.retry(added.id),
        h.queue.reorder([]),
        h.queue.pause(),
        h.queue.resume(),
        h.queue.cancel(),
    ):
        with pytest.raises(ReframeClosedError):
            await call
    with pytest.raises(ReframeClosedError):
        h.queue.start()
    assert [j.id for j in h.queue.list()] == [added.id]
    assert await h.queue.wait() != []


# --------------------------------------------------------------------------- close, restart


def queue_at(h: Harness) -> QueueService:
    """A second queue on the same data folder (a restarted Reframe)."""
    return QueueService(
        h.events,
        lambda: h.settings.model_copy(deep=True),
        data_dir=h.tmp / "data",
        tools=h.tools,
        capabilities=h.caps,
        sources=h.sources,
        inhibitor=SleepInhibitor([], h.events),
    )


async def test_close_interrupts_running_jobs_and_restart_recovers(harness: Harness) -> None:
    h = harness
    job = h.job()
    plan = h.plan(job)
    h.scenario(LONG)
    added = await h.queue.add(job)
    waiting = await h.queue.add(h.job("Later"))
    h.queue.start()
    await h.first_event(added.id, "job.progress", limit=20)
    await h.wait_for(plan.output_tmp.exists)
    await h.queue.close()
    assert h.states(added.id)[-1] == ("running", "interrupted")
    assert h.queue.get(added.id).error == "Reframe was closed while the job was running."  # type: ignore[union-attr]
    assert not plan.output_tmp.exists()
    assert h.leftovers() == []
    assert not h.backend.held  # the inhibitor is closed
    assert h.inhibitor.closed
    again = queue_at(h)
    await again._restore()
    try:
        jobs = again.list()
        assert [(j.id, j.state) for j in jobs] == [
            (added.id, JobState.INTERRUPTED),
            (waiting.id, JobState.WAITING),
        ]
        assert jobs[0].plan is not None
        h.scenario()
        await again.retry(added.id)
        again.start()
        ended = await again.wait()
        assert [j.state for j in ended] == [JobState.DONE, JobState.DONE]
    finally:
        await again.close()


async def test_restore_turns_running_rows_into_interrupted(harness: Harness) -> None:
    """A crash: rows stay ``running`` / ``paused``. The restored queue marks them
    ``interrupted`` and removes their leftover files (the ``.part`` file by the policy)."""
    h = harness
    job = h.job()
    plan = h.plan(job)
    first = await h.queue.add(job)
    second = await h.queue.add(h.job("Kept"))
    await h.queue.close()
    stored = h.queue.get(first.id)
    assert stored is not None
    stored.state = JobState.RUNNING
    stored.plan = plan
    kept = h.queue.get(second.id)
    assert kept is not None
    kept.state = JobState.PAUSED
    db = sqlite3.connect(h.tmp / "data" / "queue.sqlite3")
    for row in (row_of(stored), row_of(kept)):
        db.execute(f"INSERT OR REPLACE INTO jobs VALUES ({', '.join('?' * len(row))})", row)
    db.commit()
    db.close()
    plan.output_tmp.write_text("half")
    for path in [*(f.path for f in plan.files), *plan.temp_files]:
        path.write_text("x")
    again = queue_at(h)
    count = len(h.events.published)
    await again._restore()
    try:
        assert [j.state for j in again.list()] == [JobState.INTERRUPTED, JobState.INTERRUPTED]
        assert again.list()[0].error == "Reframe stopped while the job was running."
        restored = [
            (e.previous.value if e.previous else None, e.state.value)
            for e in h.events.published[count:]
            if e.type == "job.state"
        ]
        assert restored == [("running", "interrupted"), ("paused", "interrupted")]
        await asyncio.wait(again._background) if again._background else None
        assert not plan.output_tmp.exists()
        await again._restore()  # once only
    finally:
        await again.close()
    db = sqlite3.connect(h.tmp / "data" / "queue.sqlite3")
    states = [row[0] for row in db.execute("SELECT state FROM jobs ORDER BY position")]
    db.close()
    assert states == ["interrupted", "interrupted"]


async def test_the_store_keeps_unknown_fields_of_a_job(harness: Harness) -> None:
    h = harness
    data = h.job().model_dump(mode="json")
    data["from_the_future"] = [1, 2]
    from reframe.models import JobSettings

    added = await h.queue.add(JobSettings.model_validate(data))
    await h.queue.close()
    again = queue_at(h)
    await again._restore()
    try:
        [job] = again.list()
        assert job.id == added.id
        assert json.loads(job.settings.model_dump_json())["from_the_future"] == [1, 2]
    finally:
        await again.close()


async def test_a_newer_store_is_reported(harness: Harness) -> None:
    h = harness
    await h.queue.add(h.job())
    await h.queue.close()
    db = sqlite3.connect(h.tmp / "data" / "queue.sqlite3")
    db.execute("PRAGMA user_version = 7")
    db.commit()
    db.close()
    again = queue_at(h)
    await again._restore()
    try:
        assert again.list() == []
        assert "queue.newer_version" in [e.code for e in h.of_type("app.warning")]  # type: ignore[union-attr]
    finally:
        await again.close()


async def test_a_store_that_cannot_be_written(harness: Harness) -> None:
    h = harness
    (h.tmp / "data").write_text("a file where the data folder should be")
    added = await h.queue.add(h.job())
    assert added.state is JobState.WAITING  # the queue goes on in memory
    assert [e.code for e in h.of_type("app.warning")] == ["queue.not_saved"]  # type: ignore[union-attr]
    assert h.queue._store.path.parent.is_file()
