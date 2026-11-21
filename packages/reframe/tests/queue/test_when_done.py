"""The queue's when-done actions and job notifications, with a fake power service."""

from __future__ import annotations

import asyncio
from typing import cast

import pytest

from reframe.events import EventBus
from reframe.models import (
    AppWarningEvent,
    Event,
    JobState,
    NotificationEvent,
    PowerAction,
    PowerCountdownEvent,
)
from reframe.models.settings import WhenDone
from reframe.platform.power import OsAction, PowerService
from reframe.queue import QueueService
from reframe.queue.whendone import WhenDoneActions, summary
from reframe_testing import fake_tools as ft

from .conftest import Harness, encode_rule

pytestmark = pytest.mark.anyio

#: An encode that runs until it is cancelled: a first block, part of an output, then quiet.
LONG = encode_rule(ft.progress(blocks=1, end=False), ft.write_output(100), ft.hang())
#: The encode of a job whose output name has "Bad" fails (exit code 1).
BAD = ft.Rule(tool="ffmpeg", argv_has=["matroska"], argv_contains=["Bad"], exit_code=1)
#: The encode of a job whose output name has "Long" runs until it is cancelled.
LONG_BY_NAME = ft.Rule(
    tool="ffmpeg",
    argv_has=["matroska"],
    argv_contains=["Long"],
    actions=[ft.progress(blocks=1, end=False), ft.write_output(100), ft.hang()],
)


class FakePower:
    """A ``PowerService`` stand-in: the countdown ends only in :meth:`run_out`, and its action
    is only recorded (:attr:`executed`)."""

    def __init__(self, events: EventBus) -> None:
        self.events = events
        self.scheduled: list[tuple[str, PowerAction, str]] = []
        """``(countdown id, action, reason)`` of every ``schedule`` call."""
        self.cancel_calls: list[str | None] = []
        self.cancelled: list[str] = []
        """The ids of the countdowns that were cancelled."""
        self.executed: list[PowerAction] = []
        self.closed = False
        self._pending: PowerCountdownEvent | None = None

    def schedule(self, action: PowerAction, *, reason: str = "") -> str:
        if self._pending is not None:
            self._end(self._pending, "cancelled")
        countdown_id = f"countdown-{len(self.scheduled) + 1}"
        self.scheduled.append((countdown_id, action, reason))
        self._pending = PowerCountdownEvent(
            countdown_id=countdown_id, action=action, phase="started", seconds_left=60
        )
        self.events.publish(self._pending)
        return countdown_id

    def cancel(self, countdown_id: str | None = None) -> bool:
        self.cancel_calls.append(countdown_id)
        pending = self._pending
        if pending is None or countdown_id not in (None, pending.countdown_id):
            return False
        self._end(pending, "cancelled")
        return True

    @property
    def pending(self) -> PowerCountdownEvent | None:
        return self._pending

    async def close(self) -> None:
        self.closed = True
        if self._pending is not None:
            self._end(self._pending, "cancelled")

    def run_out(self) -> PowerAction | None:
        """The countdown reaches zero now: its action "runs" (recorded only). ``None`` when no
        countdown runs (it was cancelled, or none was started)."""
        pending = self._pending
        if pending is None:
            return None
        self._end(pending, "executing")
        self.executed.append(pending.action)
        return pending.action

    def _end(self, pending: PowerCountdownEvent, phase: str) -> None:
        self._pending = None
        if phase == "cancelled":
            self.cancelled.append(pending.countdown_id)
        self.events.publish(
            PowerCountdownEvent(
                countdown_id=pending.countdown_id,
                action=pending.action,
                phase="cancelled" if phase == "cancelled" else "executing",
                seconds_left=pending.seconds_left if phase == "cancelled" else 0,
            )
        )


def queue_with(
    h: Harness, power: object, unavailable: dict[WhenDone, str] | None = None
) -> QueueService:
    """A queue like the harness's, with ``power`` as its power service."""
    return QueueService(
        h.events,
        lambda: h.settings.model_copy(deep=True),
        data_dir=h.tmp / "data",
        tools=h.tools,
        capabilities=h.caps,
        sources=h.sources,
        inhibitor=h.inhibitor,
        power=cast(PowerService, power),
        unavailable_when_done=unavailable,
        stall_after=None,
        watchdog_tick=0.05,
        log_interval=0.02,
    )


@pytest.fixture
def power(harness: Harness) -> FakePower:
    """The harness's queue gets a :class:`FakePower` (the harness closes the queue). The
    queue it replaces was never used, so it holds no lock, store thread or file."""
    fake = FakePower(harness.events)
    harness.queue = queue_with(harness, fake)
    return fake


def notifications(h: Harness, *, job: bool | None = None) -> list[NotificationEvent]:
    """The ``notification`` events (``job``: only those of a job / only the queue's)."""
    found = [e for e in h.events.published if isinstance(e, NotificationEvent)]
    if job is None:
        return found
    return [e for e in found if (e.job_id is not None) == job]


def countdowns(h: Harness) -> list[tuple[str, str]]:
    return [
        (e.countdown_id, e.phase) for e in h.events.published if isinstance(e, PowerCountdownEvent)
    ]


def counting(power: FakePower | PowerService) -> bool:
    """A countdown runs (a call, so that type narrowing of ``pending`` does not stick)."""
    return power.pending is not None


def warnings(h: Harness, code: str) -> list[AppWarningEvent]:
    return [e for e in h.events.published if isinstance(e, AppWarningEvent) and e.code == code]


def index_of(h: Harness, event: Event) -> int:
    return next(i for i, e in enumerate(h.events.published) if e is event)


def end_state(h: Harness, job_id: str) -> Event:
    return [e for e in h.events_of(job_id) if e.type == "job.state"][-1]


@pytest.mark.parametrize("action", ["quit", "sleep", "shutdown"])
async def test_each_power_action_runs_once_after_the_queue_empties(
    harness: Harness, power: FakePower, action: PowerAction
) -> None:
    h = harness
    h.settings.queue.when_done = action
    h.settings.queue.parallel_jobs = 2
    h.scenario(BAD)
    ids = [(await h.queue.add(h.job(name))).id for name in ("One", "Bad", "Three")]
    h.queue.start()
    ended = await h.queue.wait()
    assert [j.state for j in ended] == [JobState.DONE, JobState.FAILED, JobState.DONE]
    # Taken before wait() returned: a front end can show the countdown at once.
    assert power.scheduled == [("countdown-1", action, "2 jobs done, 1 failed")]
    assert power.pending is not None
    assert power.pending.action == action
    assert warnings(h, "queue.when_done_unavailable") == []
    [started] = [e for e in h.events.published if isinstance(e, PowerCountdownEvent)]
    last_end = max(index_of(h, end_state(h, job_id)) for job_id in ids)
    assert index_of(h, started) > last_end
    assert power.run_out() == action
    assert power.executed == [action]
    assert countdowns(h) == [("countdown-1", "started"), ("countdown-1", "executing")]
    await h.queue.close()
    assert power.scheduled == [("countdown-1", action, "2 jobs done, 1 failed")]  # once only


@pytest.mark.parametrize(
    ("done", "failed", "text"),
    [
        (1, 0, "1 job done"),
        (3, 0, "3 jobs done"),
        (2, 1, "2 jobs done, 1 failed"),
    ],
)
def test_the_summary_is_the_reason(done: int, failed: int, text: str) -> None:
    assert summary(done, failed) == text


def test_an_unknown_action_does_nothing(caplog: pytest.LogCaptureFixture) -> None:
    """A value that this code does not know (it cannot pass the settings model today) is
    logged, never a crash in the run's end."""
    events = EventBus()
    subscription = events.subscribe()
    power = FakePower(events)
    actions = WhenDoneActions(events, cast(PowerService, power))
    actions.count(JobState.DONE)
    actions.emptied(JobState.DONE, cast(WhenDone, "hibernate"))
    assert power.scheduled == []
    assert subscription.get_nowait() is None
    assert "unknown action 'hibernate'" in caplog.text


async def test_the_user_cancels_the_countdown(harness: Harness, power: FakePower) -> None:
    h = harness
    h.settings.queue.when_done = "sleep"
    await h.run_one(h.job("First"))
    assert power.pending is not None
    assert power.cancel() is True
    assert power.run_out() is None
    assert power.executed == []
    assert len(power.scheduled) == 1  # the queue does not start it again
    # The next batch has its own countdown and counts. The queue cancels only by its own id:
    # the user's cancel left nothing to cancel when the second job started.
    second = await h.queue.add(h.job("Second"))
    [ended] = await h.queue.wait([second.id])
    assert ended.state is JobState.DONE
    assert [s[2] for s in power.scheduled] == ["1 job done", "1 job done"]
    await h.queue.close()
    assert power.cancel_calls == [None, "countdown-1", "countdown-2"]
    assert power.cancelled == ["countdown-1", "countdown-2"]
    assert power.executed == []


@pytest.mark.parametrize("how", ["add", "retry"])
async def test_new_work_cancels_the_countdown(harness: Harness, power: FakePower, how: str) -> None:
    h = harness
    h.settings.queue.when_done = "shutdown"
    h.scenario(BAD)
    first = await h.run_one(h.job("Bad" if how == "retry" else "First"))
    assert power.pending is not None
    h.scenario()
    if how == "add":
        second = await h.queue.add(h.job("Second"))  # the queue runs: it is taken at once
    else:
        second = await h.queue.retry(first.id)
    assert power.cancelled == ["countdown-1"]  # when the runner took the job
    [ended] = await h.queue.wait([second.id])
    assert ended.state is JobState.DONE
    [cancelled] = [
        e
        for e in h.events.published
        if isinstance(e, PowerCountdownEvent) and e.phase == "cancelled"
    ]
    running = [
        e for e in h.events_of(second.id) if e.type == "job.state" and e.state is JobState.RUNNING
    ][-1]
    assert index_of(h, cancelled) < index_of(h, running)
    # Whole tuples: a failed last job (``retry``) still starts the action; it does not need the
    # computer to stay on.
    assert power.scheduled == [
        ("countdown-1", "shutdown", "0 jobs done, 1 failed" if how == "retry" else "1 job done"),
        ("countdown-2", "shutdown", "1 job done"),
    ]
    assert power.run_out() == "shutdown"
    assert power.executed == ["shutdown"]


async def test_a_job_added_to_an_idle_queue_leaves_the_countdown_alone(
    harness: Harness, power: FakePower
) -> None:
    """``start(job_ids=…)``: the runner went idle. A job that is only added is not new work
    yet; it is when it starts."""
    h = harness
    h.settings.queue.when_done = "sleep"
    first = await h.queue.add(h.job("First"))
    h.queue.start(job_ids=[first.id])
    await h.queue.wait([first.id])
    assert not h.queue._processing
    assert power.pending is not None
    second = await h.queue.add(h.job("Second"))  # add schedules at once: nothing is taken
    assert power.pending is not None
    assert power.cancel_calls == []
    h.queue.start(job_ids=[second.id])
    assert power.cancelled == ["countdown-1"]
    await h.queue.wait([second.id])
    assert [s[0] for s in power.scheduled] == ["countdown-1", "countdown-2"]


@pytest.mark.parametrize("action", ["quit", "sleep", "shutdown"])
async def test_a_power_action_waits_for_the_jobs_that_a_row_start_left_waiting(
    harness: Harness, power: FakePower, action: PowerAction
) -> None:
    """A queue row's Start (``own_batch=False``): the queue has not emptied while other jobs
    wait; their end counts the started job too."""
    h = harness
    h.settings.queue.when_done = action
    first, second = [await h.queue.add(h.job(name)) for name in ("First", "Second")]
    h.queue.start(job_ids=[first.id], own_batch=False)
    [ended] = await h.queue.wait([first.id])
    assert ended.state is JobState.DONE
    assert not h.queue.processing
    assert power.scheduled == []
    assert notifications(h, job=False) == []
    h.queue.start(job_ids=[second.id], own_batch=False)
    await h.queue.wait([second.id])
    assert power.scheduled == [("countdown-1", action, "2 jobs done")]


async def test_notify_reports_the_jobs_of_a_row_start_with_others_waiting(
    harness: Harness, power: FakePower
) -> None:
    h = harness
    h.settings.queue.when_done = "notify"
    h.settings.queue.notifications = False
    ids = [(await h.queue.add(h.job(name))).id for name in ("A", "B", "C")]
    h.queue.start(job_ids=ids[:2], own_batch=False)
    await h.queue.wait(ids[:2])
    [note] = notifications(h)
    assert (note.title, note.message) == ("Queue finished", "2 jobs done.")
    assert h.queue.get(ids[2]).state is JobState.WAITING  # type: ignore[union-attr]


async def test_a_command_s_jobs_are_a_batch_of_their_own(
    harness: Harness, power: FakePower
) -> None:
    """``reframe encode`` (``own_batch``, the default): the action runs when its jobs end,
    although another front end's job waits."""
    h = harness
    h.settings.queue.when_done = "shutdown"
    others = await h.queue.add(h.job("Other"))
    mine = await h.queue.add(h.job("Mine"))
    h.queue.start(job_ids=[mine.id])
    await h.queue.wait([mine.id])
    assert power.scheduled == [("countdown-1", "shutdown", "1 job done")]
    assert h.queue.get(others.id).state is JobState.WAITING  # type: ignore[union-attr]


async def test_a_settings_change_does_not_cancel_the_countdown(
    harness: Harness, power: FakePower
) -> None:
    """The queue reads ``when_done`` when it empties."""
    h = harness
    h.settings.queue.when_done = "shutdown"
    await h.run_one(h.job())
    h.settings.queue.when_done = "nothing"
    await h.queue.wait()
    assert power.pending is not None
    assert power.cancel_calls == []


async def test_no_action_when_stopped_with_jobs_left(harness: Harness, power: FakePower) -> None:
    h = harness
    h.settings.queue.when_done = "shutdown"
    h.scenario(encode_rule(ft.progress(blocks=3, interval=0.05), ft.write_output()))
    first = await h.queue.add(h.job("A"))
    second = await h.queue.add(h.job("B"))
    h.queue.start()
    await h.first_event(first.id, "job.state", state="running")
    await h.queue.stop()
    assert not h.queue._processing
    await h.queue.wait([first.id])
    await asyncio.sleep(0.1)  # a job taken by mistake would have time to start
    assert h.queue.get(second.id).state is JobState.WAITING  # type: ignore[union-attr]
    assert power.scheduled == []
    assert [(n.job_id, n.level) for n in notifications(h, job=True)] == [(first.id, "success")]
    h.queue.start()  # the batch goes on
    await h.queue.wait([second.id])
    assert power.scheduled == [("countdown-1", "shutdown", "2 jobs done")]


async def test_no_action_when_the_last_job_was_cancelled(
    harness: Harness, power: FakePower
) -> None:
    h = harness
    h.settings.queue.when_done = "shutdown"
    h.scenario(LONG_BY_NAME)
    first = await h.queue.add(h.job("First"))
    long = await h.queue.add(h.job("Long"))
    h.queue.start()
    await h.queue.wait([first.id])
    await h.running_process(long.id)
    await h.queue.cancel(long.id)
    assert h.queue.get(long.id).state is JobState.CANCELLED  # type: ignore[union-attr]
    assert power.scheduled == []
    assert power.cancel_calls == []
    # The batch ended without its action; the next one counts from zero.
    await h.queue.add(h.job("Next"))
    await h.queue.wait()
    assert power.scheduled == [("countdown-1", "shutdown", "1 job done")]


async def test_cancel_all_runs_no_action(harness: Harness, power: FakePower) -> None:
    h = harness
    h.settings.queue.when_done = "shutdown"
    h.settings.queue.parallel_jobs = 2
    h.scenario(LONG)
    first = await h.queue.add(h.job("A"))
    third = await h.queue.add(h.job("C"))
    second = await h.queue.add(h.job("B"), position=2)
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
    assert power.scheduled == []
    assert notifications(h) == []  # cancelled by the user: no job notifications either
    await h.queue.cancel(first.id)  # an ended job: nothing happens


async def test_close_with_running_jobs_runs_no_action(harness: Harness, power: FakePower) -> None:
    h = harness
    h.settings.queue.when_done = "shutdown"
    h.scenario(LONG)
    added = await h.queue.add(h.job())
    h.queue.start()
    await h.running_process(added.id)
    await h.queue.close()
    assert h.queue.get(added.id).state is JobState.INTERRUPTED  # type: ignore[union-attr]
    assert power.scheduled == []
    assert notifications(h) == []


class BrokenSchedule(FakePower):
    def schedule(self, action: PowerAction, *, reason: str = "") -> str:
        raise RuntimeError("no countdown today")


class BrokenCancel(FakePower):
    def cancel(self, countdown_id: str | None = None) -> bool:
        super().cancel(countdown_id)
        raise RuntimeError("cannot cancel")


async def test_a_power_service_that_cannot_schedule_is_a_warning(harness: Harness) -> None:
    """``schedule`` raising (a bug in the power service) is an ``app.warning``; the job's
    ``wait()`` still returns and the queue goes on."""
    h = harness
    h.settings.queue.when_done = "shutdown"
    h.queue = queue_with(h, BrokenSchedule(h.events))
    ended = await h.run_one(h.job())
    assert ended.state is JobState.DONE
    [warning] = warnings(h, "queue.when_done_failed")
    assert warning.message == (
        "The queue is finished (1 job done). When done: “Shut down” could not be started, so "
        "nothing was done."
    )
    assert warning.detail == "RuntimeError: no countdown today"
    second = await h.run_one(h.job("Second"))  # the queue goes on
    assert second.state is JobState.DONE
    assert len(warnings(h, "queue.when_done_failed")) == 2


async def test_a_power_service_that_cannot_cancel_breaks_nothing(harness: Harness) -> None:
    h = harness
    h.settings.queue.when_done = "shutdown"
    power = BrokenCancel(h.events)
    h.queue = queue_with(h, power)
    await h.run_one(h.job("First"))
    second = await h.run_one(h.job("Second"))  # its start cancels (and the cancel raises)
    assert second.state is JobState.DONE
    await h.queue.close()  # the same at close
    assert power.cancel_calls == ["countdown-1", "countdown-2"]
    assert power.executed == []


async def test_without_a_power_service_nothing_is_done(harness: Harness) -> None:
    h = harness  # the harness's queue has no power service
    h.settings.queue.when_done = "sleep"
    await h.run_one(h.job())
    [warning] = warnings(h, "queue.when_done_unavailable")
    assert warning.message == (
        "The queue is finished (1 job done). When done: “Sleep” is not available here, so "
        "nothing was done."
    )
    assert warning.detail == "when_done=sleep: this Reframe has no power service"


async def test_an_action_this_process_cannot_carry_out_is_a_warning(
    harness: Harness, power: FakePower
) -> None:
    h = harness
    h.queue = queue_with(h, power, {"shutdown": "in a container"})
    h.settings.queue.when_done = "shutdown"
    await h.run_one(h.job("A"))
    assert power.scheduled == []
    [warning] = warnings(h, "queue.when_done_unavailable")
    assert "When done: “Shut down” is not available here" in warning.message
    assert warning.detail == "when_done=shutdown: in a container"
    h.settings.queue.when_done = "sleep"
    await h.run_one(h.job("B"))
    assert [action for _, action, _ in power.scheduled] == ["sleep"]


async def test_nothing_and_notify_never_use_the_power_service(
    harness: Harness, power: FakePower
) -> None:
    h = harness
    await h.run_one(h.job("A"))
    h.settings.queue.when_done = "notify"
    await h.run_one(h.job("B"))
    assert power.scheduled == []
    assert power.cancel_calls == []


async def test_job_notifications(
    harness: Harness, power: FakePower, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness
    h.scenario(BAD)
    good, bad = h.job("Good"), h.job("Bad")
    final, part = h.plan(good).output_final, h.plan(good).output_tmp
    seen: list[tuple[str, bool, bool]] = []
    publish = h.events.publish

    def spy(event: Event) -> None:
        if isinstance(event, NotificationEvent):
            seen.append((event.title, final.exists(), part.exists()))
        publish(event)

    monkeypatch.setattr(h.events, "publish", spy)
    first = await h.queue.add(good)
    second = await h.queue.add(bad)
    h.queue.start()
    await h.queue.wait()
    done, failed = notifications(h)
    assert (done.title, done.message, done.level, done.job_id) == (
        "Job done",
        "Good.mkv",
        "success",
        first.id,
    )
    assert (failed.title, failed.level, failed.job_id) == ("Job failed", "error", second.id)
    error = h.queue.get(second.id).error  # type: ignore[union-attr]
    assert error is not None
    assert error.startswith("The encode failed (exit code 1)")
    assert failed.message == f"Movie.Source.mkv: {error}"
    assert seen[0] == ("Job done", True, False)  # the output has its final name already
    for job_id in (first.id, second.id):
        kinds = h.kinds(job_id)
        assert kinds[-3:] == ["notification", "job.log", "job.state"]
    assert notifications(h, job=False) == []  # when done: nothing


async def test_no_job_notifications_when_they_are_off(harness: Harness, power: FakePower) -> None:
    h = harness
    h.settings.queue.notifications = False
    h.settings.queue.when_done = "notify"  # the when-done action notifies anyway
    h.scenario(BAD)
    await h.run_one(h.job("Good"))
    assert notifications(h, job=True) == []
    [note] = notifications(h)
    assert (note.title, note.message, note.level, note.job_id) == (
        "Queue finished",
        "1 job done.",
        "success",
        None,
    )
    await h.run_one(h.job("Bad"))
    assert notifications(h, job=True) == []
    assert [n.message for n in notifications(h)] == ["1 job done.", "0 jobs done, 1 failed."]


async def test_notify_after_one_job_is_not_sent_twice(harness: Harness, power: FakePower) -> None:
    """One job with notifications on: its own notification says it all."""
    h = harness
    h.settings.queue.when_done = "notify"
    ended = await h.run_one(h.job())
    [note] = notifications(h)
    assert (note.title, note.job_id) == ("Job done", ended.id)


async def test_notify_after_several_jobs(harness: Harness, power: FakePower) -> None:
    h = harness
    h.settings.queue.when_done = "notify"
    h.scenario(BAD)
    ids = [(await h.queue.add(h.job(name))).id for name in ("A", "Bad", "C")]
    h.queue.start()
    await h.queue.wait()
    assert [(n.title, n.job_id) for n in notifications(h, job=True)] == [
        ("Job done", ids[0]),
        ("Job failed", ids[1]),
        ("Job done", ids[2]),
    ]
    [queue_note] = notifications(h, job=False)
    assert (queue_note.message, queue_note.level) == ("2 jobs done, 1 failed.", "warning")
    assert h.events.published[-1] is queue_note  # after the last job's events


async def test_no_notification_for_a_job_that_fails_when_it_is_added(
    harness: Harness, power: FakePower
) -> None:
    h = harness
    h.settings.queue.when_done = "shutdown"
    job = h.job()
    job.source.path = h.tmp / "media" / "missing.mkv"
    added = await h.queue.add(job)
    assert added.state is JobState.FAILED
    h.queue.start()
    await h.queue.wait()
    assert notifications(h) == []
    assert power.scheduled == []  # it never ran: the queue did not empty after a run


class RecordingExecutor:
    """A ``PowerExecutor`` that only records: the operating system is never asked."""

    def __init__(self) -> None:
        self.actions: list[OsAction] = []

    async def execute(self, action: OsAction) -> str | None:
        self.actions.append(action)
        return None


def real_power(events: EventBus, *, countdown: float) -> tuple[PowerService, RecordingExecutor]:
    """A ``PowerService`` with a recording executor and a short countdown."""
    executor = RecordingExecutor()
    return PowerService(events, executor=executor, countdown=countdown), executor


async def test_with_the_power_service_the_action_runs_after_the_countdown(
    harness: Harness,
) -> None:
    h = harness
    service, executor = real_power(h.events, countdown=1.0)
    h.queue = queue_with(h, service)
    h.settings.queue.when_done = "sleep"
    try:
        await h.run_one(h.job())
        assert counting(service)
        await h.wait_for(lambda: executor.actions == ["sleep"])
        phases = [p for _, p in countdowns(h)]
        assert (phases[0], phases[-1]) == ("started", "executing")
        assert not counting(service)
    finally:
        await h.queue.close()
        await service.close()
    assert executor.actions == ["sleep"]


async def test_with_the_power_service_new_work_and_close_cancel(harness: Harness) -> None:
    h = harness
    service, executor = real_power(h.events, countdown=60.0)
    h.queue = queue_with(h, service)
    h.settings.queue.when_done = "shutdown"
    try:
        await h.run_one(h.job("First"))
        first = service.pending
        assert first is not None
        second = await h.queue.add(h.job("Second"))  # taken at once: the countdown stops
        assert service.pending is None or service.pending.countdown_id != first.countdown_id
        assert (first.countdown_id, "cancelled") in countdowns(h)
        await h.queue.wait([second.id])
        again = service.pending
        assert again is not None
        assert again.countdown_id != first.countdown_id
        await h.queue.close()
        assert not counting(service)
        assert (again.countdown_id, "cancelled") in countdowns(h)
    finally:
        await h.queue.close()
        await service.close()
    assert executor.actions == []
