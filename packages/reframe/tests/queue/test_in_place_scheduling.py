"""In-place metadata edits in the queue (C-13, decision 0034 follow-up): the same-output rule
keys an in-place job on its source (it writes it), so no job that reads that source runs while
it is edited, and two edits of one file never run at once; restored interrupted in-place jobs
have nothing to clean up. With the fake tools (the harness of ``conftest.py``)."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from reframe.command import build_plan
from reframe.metadata import remux_job
from reframe.models import JobSettings, JobState, QueueJob, SourceRef
from reframe.queue.runner import ActiveJob
from reframe.queue.service import _conflicts, _output_key, _source_key
from reframe_testing import fake_tools as ft

from .conftest import Harness, all_caps, encode_rule, tool_set

pytestmark = pytest.mark.anyio


def in_place_job(h: Harness, name: str = "Renamed") -> JobSettings:
    job = remux_job(JobSettings(source=SourceRef(path=h.source_path)), h.sources.source)
    job.audio[0].metadata.name = name
    return job


def queued(job: JobSettings, job_id: str = "j") -> QueueJob:
    return QueueJob(id=job_id, position=0, settings=job, created_at=datetime.now(UTC))


def active_for(job: QueueJob) -> ActiveJob:
    return ActiveJob(
        job_id=job.id,
        output_key=_output_key(job),
        source_key=_source_key(job),
        in_place=job.settings.output.edit_in_place,
    )


def ended_before_started(h: Harness, first: str, second: str) -> bool:
    """``first`` reached its end state before ``second`` started running."""
    order = [(e.job_id, e.state.value) for e in h.events.published if e.type == "job.state"]
    end = next(
        i for i, (j, s) in enumerate(order) if j == first and s in ("done", "failed", "cancelled")
    )
    start = next(i for i, (j, s) in enumerate(order) if j == second and s == "running")
    return end < start


# --------------------------------------------------------------------------- the rule


async def test_conflict_rule(harness: Harness, tmp_path: Path) -> None:
    h = harness
    edit = queued(in_place_job(h), "edit")
    encode = queued(h.job("Encode"), "encode")
    other = queued(h.job("Other"), "other")
    other.settings.source = SourceRef(path=tmp_path / "media" / "Another.mkv")
    assert _output_key(edit) == _source_key(edit)  # an in-place edit writes its source
    assert _conflicts(encode, [active_for(edit)])  # its source is being edited
    assert _conflicts(edit, [active_for(encode)])  # its source is being read
    assert _conflicts(edit, [active_for(queued(in_place_job(h, "X"), "edit2"))])
    assert not _conflicts(other, [active_for(edit)])  # another source: no conflict
    assert not _conflicts(encode, [active_for(queued(h.job("Second"), "e2"))])
    assert _conflicts(encode, [active_for(queued(h.job("Encode"), "e3"))])  # same output
    writes_source = queued(h.job("Other"), "w")
    writes_source.settings.output.path = h.source_path  # validation stops this; the rule too
    assert _conflicts(edit, [active_for(writes_source)])


# --------------------------------------------------------------------------- the queue


async def test_an_in_place_edit_waits_for_an_encode_of_its_source(harness: Harness) -> None:
    h = harness
    h.settings.queue.parallel_jobs = 2
    h.tools.tools = tool_set(h.fake.ffmpeg, mkvpropedit=h.fake.ffmpeg)
    h.scenario(encode_rule(ft.progress(blocks=1, end=False), ft.hang()))
    encode = await h.queue.add(h.job("Encode"))
    edit = await h.queue.add(in_place_job(h))
    assert edit.state is JobState.WAITING, edit.issues
    h.queue.start()
    await h.running_process(encode.id)
    await asyncio.sleep(0.3)  # a free slot, but the edit must not start
    assert h.queue.get(edit.id).state is JobState.WAITING  # type: ignore[union-attr]
    await h.queue.cancel(encode.id)
    await h.queue.wait([encode.id, edit.id])
    assert ended_before_started(h, encode.id, edit.id)
    assert h.source_path.exists()
    h.leftovers()


async def test_an_encode_waits_for_an_in_place_edit_of_its_source(harness: Harness) -> None:
    h = harness
    h.settings.queue.parallel_jobs = 2
    h.tools.tools = tool_set(h.fake.ffmpeg, mkvpropedit=h.fake.ffmpeg)
    h.scenario(encode_rule(ft.progress(blocks=1, end=True)))
    edit = await h.queue.add(in_place_job(h))
    encode = await h.queue.add(h.job("Encode"))
    h.queue.start()
    await h.queue.wait([edit.id, encode.id])
    assert ended_before_started(h, edit.id, encode.id)


async def test_two_in_place_edits_of_one_file_run_one_after_the_other(harness: Harness) -> None:
    h = harness
    h.settings.queue.parallel_jobs = 2
    h.tools.tools = tool_set(h.fake.ffmpeg, mkvpropedit=h.fake.ffmpeg)
    first = await h.queue.add(in_place_job(h, "One"))
    second = await h.queue.add(in_place_job(h, "Two"))
    h.queue.start()
    await h.queue.wait([first.id, second.id])
    assert ended_before_started(h, first.id, second.id)


# --------------------------------------------------------------------------- restore


async def test_restored_in_place_jobs_have_nothing_to_clean_up(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    h = harness
    h.settings.output.partial_file = "delete"
    tools = tool_set(h.fake.ffmpeg, mkvpropedit=h.fake.ffmpeg)
    job = in_place_job(h)
    plan = build_plan(job, h.sources.source, all_caps(), tools)
    assert plan.job_type == "metadata_edit"
    interrupted = queued(job)
    interrupted.plan = plan
    encode = queued(h.job("Encode"), "encode")
    encode.plan = build_plan(encode.settings, h.sources.source, all_caps(), tools)
    encode.plan.output_tmp.write_bytes(b"part")
    with caplog.at_level(logging.WARNING, logger="reframe.queue.service"):
        h.queue._remove_leftovers([interrupted, encode])
    assert h.source_path.exists()
    assert not encode.plan.output_tmp.exists()  # other jobs are still cleaned up
    assert [r.getMessage() for r in caplog.records] == []
