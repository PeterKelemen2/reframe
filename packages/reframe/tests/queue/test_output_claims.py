"""Output claims: a job whose output is the output or the source of another waiting, running or
paused job is added (or retried) ``failed`` with ``queue.output_claimed``."""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from reframe.models import JobSettings, JobState, QueueJob, ValidationIssue
from reframe.queue import QueueService
from reframe.queue.service import OUTPUT_CLAIMED
from reframe_testing import fake_tools as ft

from .conftest import Harness, encode_rule, queue_at, store_together, tool_set
from .test_in_place_scheduling import in_place_job

pytestmark = pytest.mark.anyio

needs_symlinks = pytest.mark.skipif(
    sys.platform == "win32", reason="creating a symbolic link needs a privilege on Windows"
)


def claims(job: QueueJob | None) -> list[ValidationIssue]:
    assert job is not None
    return [issue for issue in job.issues if issue.code == OUTPUT_CLAIMED]


@dataclass
class HeldShare:
    """A share that does not answer: ``os.stat`` and ``os.lstat`` of a path under it wait, in a
    worker thread, until :attr:`answer` is set."""

    answer: threading.Event = field(default_factory=threading.Event)
    blocked: set[int] = field(default_factory=set)
    """The worker threads that wait for the share now."""


def hold_share(monkeypatch: pytest.MonkeyPatch, share: Path) -> HeldShare:
    held = HeldShare()
    loop_thread = threading.get_ident()
    prefix = str(share)

    def hold(real: Callable[..., os.stat_result]) -> Callable[..., os.stat_result]:
        def call(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
            text = os.fspath(path) if isinstance(path, (str, os.PathLike)) else None
            thread = threading.get_ident()
            if isinstance(text, str) and text.startswith(prefix) and thread != loop_thread:
                held.blocked.add(thread)
                try:
                    held.answer.wait(10)
                finally:
                    held.blocked.discard(thread)
            return real(path, *args, **kwargs)

        return call

    monkeypatch.setattr(os, "stat", hold(os.stat))
    monkeypatch.setattr(os, "lstat", hold(os.lstat))
    return held


def writing_to(h: Harness, folder: Path, name: str) -> JobSettings:
    job = h.job(name)
    job.output.path = folder / f"{name}.mkv"
    return job


async def test_a_job_that_writes_a_waiting_jobs_output_is_added_failed(harness: Harness) -> None:
    h = harness
    first = await h.queue.add(h.job("Same"))
    second = await h.queue.add(h.job("Same"))
    assert first.state is JobState.WAITING
    assert second.state is JobState.FAILED
    [issue] = claims(second)
    assert "Same.mkv is also the output of a job that is waiting" in issue.message
    assert "(Movie.Source.mkv)" in issue.message  # names the other job by its source
    assert second.error is not None
    assert second.error.startswith("The job has errors: Same.mkv")
    assert h.queue.get(first.id).state is JobState.WAITING  # type: ignore[union-attr]
    await h.queue.close()
    h.queue = queue_at(h)
    restored = h.queue.get(second.id)
    assert restored is not None
    assert claims(restored)  # saved with the job


async def test_an_in_place_edit_of_a_waiting_jobs_source_is_added_failed(
    harness: Harness,
) -> None:
    """An in-place edit writes its source, so its output is the encode's source."""
    h = harness
    h.tools.tools = tool_set(h.fake.ffmpeg, mkvpropedit=h.fake.ffmpeg)
    await h.queue.add(h.job("Encode"))
    edit = await h.queue.add(in_place_job(h))
    assert edit.state is JobState.FAILED
    [issue] = claims(edit)
    assert "is also the source of a job that is waiting" in issue.message


async def test_an_encode_of_a_file_that_is_edited_in_place_is_not_claimed(
    harness: Harness,
) -> None:
    """Its output is another file; the runner keeps the two from running at once."""
    h = harness
    h.tools.tools = tool_set(h.fake.ffmpeg, mkvpropedit=h.fake.ffmpeg)
    await h.queue.add(in_place_job(h))
    encode = await h.queue.add(h.job("Encode"))
    assert encode.state is JobState.WAITING, encode.issues


@pytest.mark.skipif(sys.platform == "win32", reason="a symbolic link needs a privilege there")
async def test_claims_compare_files_not_spellings(harness: Harness, tmp_path: Path) -> None:
    h = harness
    linked = tmp_path / "linked-out"
    linked.symlink_to(h.tmp / "out", target_is_directory=True)
    await h.queue.add(h.job("Same"))
    job = h.job("Same")
    job.output.path = linked / "Same.mkv"
    second = await h.queue.add(job)
    assert second.state is JobState.FAILED
    assert claims(second)


async def test_running_and_paused_jobs_claim_their_output(harness: Harness) -> None:
    h = harness
    h.scenario(encode_rule(ft.progress(blocks=1, end=False), ft.hang()))
    first = await h.queue.add(h.job("Same"))
    h.queue.start()
    await h.running_process(first.id)
    assert (await h.queue.add(h.job("Same"))).state is JobState.FAILED
    await h.queue.pause(first.id)
    assert h.queue.get(first.id).state is JobState.PAUSED  # type: ignore[union-attr]
    assert (await h.queue.add(h.job("Same"))).state is JobState.FAILED
    await h.queue.cancel(first.id)
    assert h.leftovers() == []


async def test_an_ended_job_claims_nothing(harness: Harness) -> None:
    h = harness
    first = await h.queue.add(h.job("Same"))
    await h.queue.cancel(first.id)
    second = await h.queue.add(h.job("Same"))
    assert second.state is JobState.WAITING, second.issues


async def test_a_retry_fails_while_another_job_holds_the_output(harness: Harness) -> None:
    h = harness
    first = await h.queue.add(h.job("Same"))
    await h.queue.cancel(first.id)
    second = await h.queue.add(h.job("Same"))
    retried = await h.queue.retry(first.id)
    assert retried.state is JobState.FAILED
    assert len(claims(retried)) == 1
    assert h.queue.get(first.id).state is JobState.FAILED  # type: ignore[union-attr]
    again = await h.queue.retry(first.id)
    assert len(claims(again)) == 1  # one issue, not one per retry
    await h.queue.remove(second.id)
    retried = await h.queue.retry(first.id)
    assert retried.state is JobState.WAITING
    assert claims(retried) == []


async def test_adds_of_one_output_at_the_same_time_queue_one(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The adds have their keys in the same pass of the event loop: the claim and the insert
    must be one step."""
    h = harness
    take = h.queue._take_keys
    together = asyncio.Event()
    taken = 0

    async def take_together(job: QueueJob) -> object:
        nonlocal taken
        keys = await take(job)
        taken += 1
        if taken == 4:
            together.set()
        await together.wait()
        return keys

    monkeypatch.setattr(h.queue, "_take_keys", take_together)
    added = await asyncio.gather(*(h.queue.add(h.job("Same")) for _ in range(4)))
    assert [job.state for job in added].count(JobState.WAITING) == 1


async def test_a_restored_job_claims_its_output_before_its_keys_arrive(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness
    first = await h.queue.add(h.job("Same"))
    await h.queue.close()
    # The background key task of a restored job never runs: only the add can take them.
    monkeypatch.setattr(QueueService, "_want_keys", lambda _self, _job: None)
    h.queue = queue_at(h)
    assert h.queue.get(first.id).state is JobState.WAITING  # type: ignore[union-attr]
    second = await h.queue.add(h.job("Same"))
    assert second.state is JobState.FAILED
    assert claims(second)


async def test_a_retry_is_claimed_by_a_restored_job_whose_keys_are_being_taken(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness
    first = await h.queue.add(h.job("Same"))
    second = await h.queue.add(h.job("Same"))  # failed: the first claims Same.mkv
    await h.queue.close()
    monkeypatch.setattr(QueueService, "_want_keys", lambda _self, _job: None)
    h.queue = queue_at(h)
    assert h.queue.get(first.id).state is JobState.WAITING  # type: ignore[union-attr]
    retried = await h.queue.retry(second.id)
    assert retried.state is JobState.FAILED
    assert len(claims(retried)) == 1


async def test_adds_return_at_once_while_a_restored_jobs_share_does_not_answer(
    harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A restored waiting job writes to a share that does not answer (a NAS that is off). Jobs
    that do not use the share are added at once, and no add leaves a thread waiting on it."""
    h = harness
    share = tmp_path / "share"
    share.mkdir()
    restored = await h.queue.add(writing_to(h, share, "Restored"))
    await h.queue.close()
    held = hold_share(monkeypatch, share)
    h.queue = queue_at(h)
    try:
        h.queue.list()  # restored: its keys are taken in the background
        await h.wait_for(lambda: len(held.blocked) == 1)
        for name in ("One", "Two", "Three"):
            added = await asyncio.wait_for(h.queue.add(h.job(name)), 5)
            assert added.state is JobState.WAITING
        assert len(held.blocked) == 1  # only the restored job's own
        assert h.queue.get(restored.id).state is JobState.WAITING  # type: ignore[union-attr]
    finally:
        held.answer.set()


@needs_symlinks
async def test_a_restored_job_fails_when_its_keys_show_a_claimed_output(
    harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """While its keys are taken, an add compares the restored job's output as written; a link
    to the same file shows when they arrive."""
    h = harness
    link = tmp_path / "out-link"
    link.symlink_to(tmp_path / "out", target_is_directory=True)
    restored = await h.queue.add(writing_to(h, link, "Same"))
    await h.queue.close()
    held = hold_share(monkeypatch, link)
    h.queue = queue_at(h)
    try:
        h.queue.list()
        added = await h.queue.add(h.job("Same"))  # out/Same.mkv: the same file
        assert added.state is JobState.WAITING
    finally:
        held.answer.set()
    await h.wait_for(lambda: claims(h.queue.get(restored.id)) != [])
    failed = h.queue.get(restored.id)
    assert failed is not None
    assert failed.state is JobState.FAILED
    assert (failed.error or "").startswith("The job has errors: Same.mkv is also the output")
    assert h.queue.get(added.id).state is JobState.WAITING  # type: ignore[union-attr]


@needs_symlinks
async def test_a_start_of_a_restored_job_that_its_keys_fail_goes_idle(
    harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness
    link = tmp_path / "out-link"
    link.symlink_to(tmp_path / "out", target_is_directory=True)
    restored = await h.queue.add(writing_to(h, link, "Same"))
    await h.queue.close()
    held = hold_share(monkeypatch, link)
    h.queue = queue_at(h)
    try:
        h.queue.list()
        await h.queue.add(h.job("Same"))
        h.queue.start(job_ids=[restored.id])
        assert h.queue.processing
    finally:
        held.answer.set()
    await h.wait_for(lambda: not h.queue.processing, 5)
    assert h.queue.only is None
    assert claims(h.queue.get(restored.id)) != []


@needs_symlinks
async def test_a_restored_job_cancelled_before_its_keys_arrive_stays_cancelled(
    harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness
    link = tmp_path / "out-link"
    link.symlink_to(tmp_path / "out", target_is_directory=True)
    restored = await h.queue.add(writing_to(h, link, "Same"))
    await h.queue.close()
    held = hold_share(monkeypatch, link)
    h.queue = queue_at(h)
    try:
        h.queue.list()
        await h.queue.cancel(restored.id)
        assert (await h.queue.add(h.job("Same"))).state is JobState.WAITING
    finally:
        held.answer.set()
    await h.wait_for(lambda: restored.id in h.queue._keys)
    assert h.queue.get(restored.id).state is JobState.CANCELLED  # type: ignore[union-attr]


@needs_symlinks
async def test_a_restored_job_removed_before_its_keys_arrive_is_not_saved_again(
    harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness
    link = tmp_path / "out-link"
    link.symlink_to(tmp_path / "out", target_is_directory=True)
    restored = await h.queue.add(writing_to(h, link, "Same"))
    await h.queue.close()
    held = hold_share(monkeypatch, link)
    h.queue = queue_at(h)
    try:
        h.queue.list()
        await h.queue.remove(restored.id)
        added = await h.queue.add(h.job("Same"))
    finally:
        held.answer.set()
    await h.wait_for(lambda: not h.queue._background)  # the keys arrived and were dropped
    await h.queue.close()
    h.queue = queue_at(h)
    assert [job.id for job in h.queue.list()] == [added.id]


@needs_symlinks
async def test_a_retried_restored_job_claims_against_the_restored_jobs_whose_keys_arrive(
    harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two restored jobs with one output (a store of an older Reframe) are not checked against
    each other; once one is retried, it is checked like any other job."""
    h = harness
    link = tmp_path / "out-link"
    link.symlink_to(tmp_path / "out", target_is_directory=True)
    first, second = await store_together(h, h.job("Same"), writing_to(h, link, "Same"))
    held = hold_share(monkeypatch, link)
    h.queue = queue_at(h)
    try:
        h.queue.list()
        await h.queue.cancel(first)
        # Compared with out-link/Same.mkv as written: the second job's keys are not there yet.
        assert (await h.queue.retry(first)).state is JobState.WAITING
    finally:
        held.answer.set()
    await h.wait_for(lambda: h.queue.get(second).state is JobState.FAILED)  # type: ignore[union-attr]
    assert len(claims(h.queue.get(second))) == 1
    assert h.queue.get(first).state is JobState.WAITING  # type: ignore[union-attr]
