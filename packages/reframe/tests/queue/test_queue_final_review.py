"""The queue's file keys, NUL paths, time limits, shutdown, pauses and zero file indexes."""

from __future__ import annotations

import asyncio
import dataclasses
import os
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from reframe.models import JobState, SourceRef
from reframe.platform.sleep import SleepInhibitor
from reframe.queue import QueueService, files, runner
from reframe.queue import service as queue_service
from reframe.queue.service import _conflicts, _output_key, _source_key
from reframe.queue.store import row_of
from reframe.queue.watchdog import StepWatch
from reframe.tools import run_streaming
from reframe_testing import fake_tools as ft

from .conftest import Harness, encode_rule, tool_set
from .test_in_place_scheduling import active_for, in_place_job, queued
from .test_in_place_stop import Gate, gate_tool, last_state, stop_requested

pytestmark = pytest.mark.anyio

DONE_QUICKLY = encode_rule(ft.progress(blocks=2, interval=0.01), ft.write_output())


@pytest.fixture
def gate(harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Gate]:
    made = gate_tool(tmp_path / "gate")
    harness.tools.tools = tool_set(harness.fake.ffmpeg, mkvpropedit=made.tool)
    monkeypatch.setattr(runner, "_in_place_refusal", lambda plan, source, probed: None)
    try:
        yield made
    finally:
        made.open()


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


def store_rows(h: Harness, *jobs: Any) -> None:
    db = sqlite3.connect(h.tmp / "data" / "queue.sqlite3")
    for job in jobs:
        row = row_of(job)
        db.execute(f"INSERT OR REPLACE INTO jobs VALUES ({', '.join('?' * len(row))})", row)
    db.commit()
    db.close()


#: How long a ``stat`` / ``lstat`` of the share takes on the event-loop thread: longer than
#: any pause the loop takes on its own, so one such call shows in the heartbeat.
LOOP_DELAY = 0.3
#: The same in a worker thread (the share is slow there too, but that waits only the caller).
THREAD_DELAY = 0.01


def slow_share(monkeypatch: pytest.MonkeyPatch, share: Path, loop_thread: int) -> list[str]:
    """``os.stat`` and ``os.lstat`` of a path under ``share`` are slow; each call made on the
    event-loop thread is recorded (the list returned)."""
    on_loop: list[str] = []
    prefix = str(share)

    def slow(real: Callable[..., os.stat_result]) -> Callable[..., os.stat_result]:
        def call(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
            text = os.fspath(path) if isinstance(path, (str, os.PathLike)) else None
            if isinstance(text, str) and text.startswith(prefix):
                if threading.get_ident() == loop_thread:
                    on_loop.append(f"{real.__name__}({text})")
                    time.sleep(LOOP_DELAY)
                else:
                    time.sleep(THREAD_DELAY)
            return real(path, *args, **kwargs)

        return call

    monkeypatch.setattr(os, "stat", slow(os.stat))
    monkeypatch.setattr(os, "lstat", slow(os.lstat))
    return on_loop


async def test_choosing_a_job_never_reads_a_slow_share_on_the_event_loop(
    harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With a slow share and ``parallel_jobs`` 2, ``add``, ``start``, ``retry``, ``reorder`` and
    every job end must not ``stat`` the share on the event loop."""
    h = harness
    h.settings.queue.parallel_jobs = 2
    h.scenario(DONE_QUICKLY)
    share = tmp_path / "share"
    (share / "deep").mkdir(parents=True)
    on_loop = slow_share(monkeypatch, share, threading.get_ident())
    gaps: list[float] = []
    beating = True

    async def heartbeat() -> None:
        last = time.monotonic()
        while beating:
            await asyncio.sleep(0.01)
            now = time.monotonic()
            gaps.append(now - last)
            last = now

    beat = asyncio.ensure_future(heartbeat())
    ids: list[str] = []
    for name in ("S0", "S1", "S2"):
        job = h.job(name)
        job.output.path = share / "deep" / "er" / f"{name}.mkv"
        ids.append((await h.queue.add(job)).id)
    later = h.job("Later")
    later.output.path = share / "deep" / "Later.mkv"
    retried = await h.queue.add(later)
    await h.queue.cancel(retried.id)  # waiting → cancelled; retried below, while jobs run
    await h.queue.reorder(list(reversed(ids)))
    began = time.monotonic()
    h.queue.start()
    start_took = time.monotonic() - began
    await h.queue.retry(retried.id)
    ended = await h.queue.wait([*ids, retried.id])
    beating = False
    await beat
    monkeypatch.undo()
    print(f"start() took {start_took:.3f} s; the longest event-loop pause {max(gaps):.3f} s")
    assert on_loop == []
    assert start_took < LOOP_DELAY
    assert max(gaps) < LOOP_DELAY
    assert [job.state for job in ended] == [JobState.DONE] * 4


async def test_a_restored_job_gets_its_keys_off_the_event_loop(
    harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A restored waiting job has no keys yet: they are read in the background when the store
    is opened, and the job runs once they are there."""
    h = harness
    h.scenario(DONE_QUICKLY)
    share = tmp_path / "share"
    share.mkdir()
    job = h.job("Restored")
    job.output.path = share / "Restored.mkv"
    waiting = await h.queue.add(job)
    await h.queue.close()
    on_loop = slow_share(monkeypatch, share, threading.get_ident())
    again = queue_at(h)
    try:
        assert [j.state for j in again.list()] == [JobState.WAITING]  # opens the store
        again.start()
        [ended] = await again.wait([waiting.id])
    finally:
        await again.close()
    monkeypatch.undo()
    assert on_loop == []
    assert ended.state is JobState.DONE


async def test_the_keys_are_what_the_rule_compares(harness: Harness, tmp_path: Path) -> None:
    """``_conflicts`` with the keys the queue keeps gives what it gives with keys read now, and
    the keys of an in-place edit are its source."""
    h = harness
    edit = queued(in_place_job(h), "edit")
    encode = queued(h.job("Encode"), "encode")
    other = queued(h.job("Other"), "other")
    other.settings.source = SourceRef(path=tmp_path / "media" / "Another.mkv")
    job_keys = queue_service._job_keys
    keys = job_keys(edit)
    assert keys.output == keys.source == _source_key(edit) == _output_key(edit)
    for job, expected in ((encode, True), (other, False)):
        assert _conflicts(job, [active_for(edit)], job_keys(job)) is expected
        assert _conflicts(job, [active_for(edit)]) is expected


NUL_MESSAGE = "has a NUL character, which no file system allows, so the job cannot run"


def test_python_facts_behind_the_rule(tmp_path: Path) -> None:
    """``abspath`` takes a NUL character; ``stat`` and, on POSIX, ``realpath`` raise
    ``ValueError``, not ``OSError``."""
    bad = tmp_path / "Mo\0vie.mkv"
    assert "\0" in os.path.abspath(bad)
    with pytest.raises(ValueError, match="embedded null"):
        os.stat(bad)
    if os.name != "nt":
        with pytest.raises(ValueError, match="embedded null"):
            os.path.realpath(bad)


def test_no_key_function_raises_for_a_path_with_a_nul(tmp_path: Path) -> None:
    bad = tmp_path / "Mo\0vie.mkv"
    assert files.same_file(bad, bad)
    assert not files.same_file(bad, tmp_path / "Movie.mkv")
    assert files.remove_files([bad]) == [f"{os.fspath(bad)!r} could not be removed: " + _nul(bad)]
    key = files.file_key(bad)
    assert key.identity is None
    assert files._path_key(bad) == key.path.casefold()


def _nul(path: Path) -> str:
    try:
        path.unlink(missing_ok=True)
    except ValueError as exc:
        return str(exc)
    raise AssertionError("unlink accepted a NUL character")


async def test_a_nul_in_a_path_fails_its_job_and_the_queue_goes_on(harness: Harness) -> None:
    h = harness
    h.scenario(DONE_QUICKLY)
    bad = await h.queue.add(h.job("Mo\0vie"))
    assert bad.state is JobState.FAILED
    assert [issue.code for issue in bad.issues] == ["queue.path_unusable"]
    assert NUL_MESSAGE in (bad.error or "")
    h.queue.start()
    assert (await h.queue.retry(bad.id)).state is JobState.WAITING
    good = await h.queue.add(h.job("Good"))
    h.queue.start()
    ended = {job.id: job for job in await h.queue.wait([bad.id, good.id])}
    assert ended[good.id].state is JobState.DONE
    assert ended[bad.id].state is JobState.FAILED
    assert "The output path" in (ended[bad.id].error or "")
    assert NUL_MESSAGE in (ended[bad.id].error or "")


async def test_a_nul_in_the_source_path_is_a_clean_failure(harness: Harness) -> None:
    h = harness
    job = h.job("Movie")
    job.source = SourceRef(path=Path(f"{h.source_path}\0x"))
    added = await h.queue.add(job)
    assert added.state is JobState.FAILED
    assert [issue.code for issue in added.issues] == ["queue.path_unusable"]
    assert (added.error or "").startswith("The job has errors: The source path")


async def test_a_restored_job_with_a_nul_in_its_path(harness: Harness) -> None:
    h = harness
    h.scenario(DONE_QUICKLY)
    bad = await h.queue.add(h.job("Mo\0vie"))
    await h.queue.retry(bad.id)  # waiting: the queue was never started
    crashed = await h.queue.add(h.job("Cr\0shed"))
    good = await h.queue.add(h.job("Good"))
    await h.queue.close()
    stored = h.queue.get(crashed.id)
    assert stored is not None
    stored.state = JobState.RUNNING
    stored.plan = h.plan(h.job("Cr\0shed"))
    assert "\0" in str(stored.plan.output_tmp)
    store_rows(h, stored)
    again = queue_at(h)
    try:
        states = {job.id: job.state for job in again.list()}  # opens the store
        assert states == {
            bad.id: JobState.WAITING,
            crashed.id: JobState.INTERRUPTED,
            good.id: JobState.WAITING,
        }
        restored = again.get(crashed.id)
        assert restored is not None
        again._remove_leftovers([restored])  # what the background clean-up runs
        again.start()
        ended = {job.id: job for job in await again.wait([bad.id, good.id])}
    finally:
        await again.close()
    assert ended[good.id].state is JobState.DONE
    assert ended[bad.id].state is JobState.FAILED
    assert NUL_MESSAGE in (ended[bad.id].error or "")


async def test_the_conflict_rule_takes_a_nul_path(harness: Harness) -> None:
    h = harness
    bad = queued(h.job("Mo\0vie"), "bad")
    other = queued(h.job("Mo\0vie"), "other")
    assert _conflicts(bad, [active_for(other)])  # the same path, as written
    assert not _conflicts(bad, [active_for(queued(h.job("Good"), "good"))])


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
        return dataclasses.replace(result, cancelled=True)

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


def zero_file_index(monkeypatch: pytest.MonkeyPatch, volume: Path) -> None:
    real_stat = os.stat
    prefix = str(volume)

    def stat(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
        result = real_stat(path, *args, **kwargs)
        if isinstance(path, (str, os.PathLike)) and os.fspath(path).startswith(prefix):
            fields = list(result)
            fields[1], fields[2] = 0, 7  # st_ino, st_dev
            return os.stat_result(fields)
        return result

    monkeypatch.setattr(os, "stat", stat)


async def test_a_zero_file_index_is_no_identity(
    harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness
    other = tmp_path / "media" / "Other.mkv"
    other.write_bytes(b"another file")
    part = tmp_path / "out" / "Movie.part.mkv"
    part.write_bytes(b"part")
    edit = queued(in_place_job(h), "edit")
    encode = queued(h.job("Encode"), "encode")
    encode.settings.source = SourceRef(path=other)
    zero_file_index(monkeypatch, tmp_path)
    assert not _conflicts(encode, [active_for(edit)])
    assert not files.same_file(other, h.source_path)
    assert runner._writes_source(h.plan(h.job("Movie")), h.source_path) is None
    assert files.remove_files([part], keep=h.source_path) == []
    assert not part.exists()
    assert files.same_file(h.source_path, h.source_path)  # the path still decides
    assert files.file_key(other).identity is None
