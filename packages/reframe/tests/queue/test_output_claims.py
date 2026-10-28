"""Output claims: a job whose output is the output or the source of another waiting, running or
paused job is added (or retried) ``failed`` with ``queue.output_claimed``."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from reframe.models import JobState, QueueJob, ValidationIssue
from reframe.queue import QueueService
from reframe.queue.service import OUTPUT_CLAIMED
from reframe_testing import fake_tools as ft

from .conftest import Harness, encode_rule, queue_at, tool_set
from .test_in_place_scheduling import in_place_job

pytestmark = pytest.mark.anyio


def claims(job: QueueJob) -> list[ValidationIssue]:
    return [issue for issue in job.issues if issue.code == OUTPUT_CLAIMED]


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


async def test_adds_of_one_output_at_the_same_time_queue_one(harness: Harness) -> None:
    h = harness
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
