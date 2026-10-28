"""The job queue: the snapshot, adding jobs, the actions on one job or on the whole queue, the
job log and the when-done setting. Every job passes the path jail before the queue sees it; no
answer names a folder of the server's own."""

from __future__ import annotations

import asyncio
import codecs
from pathlib import Path
from typing import Annotated

from fastapi import Body, Query
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from reframe.models import JobSettings, QueueJob, WhenDone
from reframe.queue.errors import UnknownJobError
from reframe.service import Reframe
from reframe_server import security
from reframe_server.api import JsonTextResponse, api_router
from reframe_server.config import ServerConfig
from reframe_server.deps import ConfigDep, HubDep, ReframeDep
from reframe_server.errors import ProblemError
from reframe_server.folders import hide_server_folders

router = api_router("queue")

LOG_CHUNK = 1 << 20
"""Bytes of a job log that one answer carries at most."""


class QueueSnapshot(BaseModel):
    """The queue now. A client reads it again after its event connection was lost."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    jobs: list[QueueJob]
    """Every job, in queue order."""


class AddJobs(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    jobs: list[JobSettings]
    """Added in this order. Each job needs ``output.path``."""
    position: Annotated[int, Field(ge=0)] | None = None
    """Queue position of the first job (0: first); ``null``: at the end."""
    attach: str | None = None
    """The ``client_id`` of the caller's event connection, which must be open."""


class StartQueue(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    job_ids: list[str] | None = None
    """Only these jobs start; other waiting jobs stay waiting. ``null``: every waiting job."""


class QueueOrder(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    job_ids: list[str]
    """These jobs in their new order. They take the places they had among themselves; the
    other jobs do not move."""

    @field_validator("job_ids")
    @classmethod
    def _each_once(cls, job_ids: list[str]) -> list[str]:
        if len(set(job_ids)) != len(job_ids):
            raise ValueError("a job id is given twice")
        return job_ids


class JobLogChunk(BaseModel):
    """Part of a job log. The file grows while the job runs and keeps every run."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    text: str
    """The log from ``from`` to ``next``; empty when nothing new was written."""
    next: int
    """The ``from`` of the next request."""
    more: bool
    """More of the log is already written: ask again at once with ``next``."""


class WhenDoneSetting(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    when_done: WhenDone
    """What happens when the queue is finished."""


def _check(config: ServerConfig, job: JobSettings, which: str) -> None:
    if job.output.path is None:
        raise ProblemError(
            422,
            "output.no_path",
            "A job has no output path",
            f"{which}: the server checks every path a job writes before the job is queued.",
        )
    security.jail_job(config, job)


def _public(reframe: Reframe, job: QueueJob) -> JsonValue:
    # The settings come back as the client sent them: it may load them into its editor again.
    return {
        key: value if key == "settings" else hide_server_folders(reframe, value)
        for key, value in job.model_dump(mode="json").items()
    }


@router.get("/queue", response_model=QueueSnapshot)
async def snapshot(reframe: ReframeDep) -> JsonTextResponse:
    """Every job in queue order."""
    return JsonTextResponse({"jobs": [_public(reframe, job) for job in reframe.queue.list()]})


@router.post("/queue", status_code=201, response_model=list[QueueJob])
async def add(
    body: AddJobs, reframe: ReframeDep, config: ConfigDep, hub: HubDep
) -> JsonTextResponse:
    """Add jobs; the answer holds them in order. The queue validates each job again: one with
    errors is added ``failed`` with its issues. A refused request adds no job."""
    if body.attach is not None and not hub.client_open(body.attach):
        raise ProblemError(
            409, "queue.attach_unknown_client", "No open event connection has this client id"
        )
    for index, job in enumerate(body.jobs):
        _check(config, job, f"jobs[{index}]")
    added: list[JsonValue] = []
    for index, job in enumerate(body.jobs):
        position = None if body.position is None else body.position + index
        added.append(_public(reframe, await reframe.queue.add(job, position=position)))
    return JsonTextResponse(added, status_code=201)


@router.post("/queue/start", status_code=204)
async def start(reframe: ReframeDep, body: Annotated[StartQueue | None, Body()] = None) -> None:
    """Start taking waiting jobs in queue order, ``parallel_jobs`` at a time."""
    reframe.queue.start(job_ids=None if body is None else body.job_ids)


@router.post("/queue/stop", status_code=204)
async def stop(reframe: ReframeDep) -> None:
    """Take no new jobs; running jobs go on."""
    await reframe.queue.stop()


@router.post("/queue/pause", status_code=204)
async def pause_all(reframe: ReframeDep) -> None:
    """Pause every running job."""
    await reframe.queue.pause()


@router.post("/queue/resume", status_code=204)
async def resume_all(reframe: ReframeDep) -> None:
    """Resume every paused job."""
    await reframe.queue.resume()


@router.post("/queue/cancel", status_code=204)
async def cancel_all(reframe: ReframeDep) -> None:
    """Cancel every job that has not ended. Answers when the running ones have stopped."""
    await reframe.queue.cancel()


@router.put("/queue/order", status_code=204)
async def reorder(body: QueueOrder, reframe: ReframeDep) -> None:
    """Put jobs in a new order."""
    await reframe.queue.reorder(body.job_ids)


@router.put("/queue/when-done")
async def set_when_done(body: WhenDoneSetting, reframe: ReframeDep) -> WhenDoneSetting:
    """Set what happens when the queue is finished (the ``queue.when_done`` setting). A power
    countdown that is running for another action is cancelled."""
    update = await reframe.settings.update(
        [{"op": "replace", "path": "/queue/when_done", "value": body.when_done}]
    )
    when_done = update.settings.queue.when_done
    pending = reframe.power.pending
    if pending is not None and pending.action != when_done:
        reframe.power.cancel(pending.countdown_id)
    return WhenDoneSetting(when_done=when_done)


@router.post("/queue/{job_id}/pause", status_code=204)
async def pause_job(job_id: str, reframe: ReframeDep) -> None:
    """Pause a running job: its processes are suspended. Other states: nothing happens."""
    await reframe.queue.pause(job_id)


@router.post("/queue/{job_id}/resume", status_code=204)
async def resume_job(job_id: str, reframe: ReframeDep) -> None:
    """Resume a paused job. Other states: nothing happens."""
    await reframe.queue.resume(job_id)


@router.post("/queue/{job_id}/cancel", status_code=204)
async def cancel_job(job_id: str, reframe: ReframeDep) -> None:
    """Cancel a job that has not ended. Answers when it has stopped."""
    await reframe.queue.cancel(job_id)


@router.post("/queue/{job_id}/retry", response_model=QueueJob)
async def retry(job_id: str, reframe: ReframeDep) -> JsonTextResponse:
    """Make a failed, cancelled or interrupted job wait again (409 for a running, paused or
    done job)."""
    return JsonTextResponse(_public(reframe, await reframe.queue.retry(job_id)))


@router.post("/queue/{job_id}/duplicate", status_code=201, response_model=QueueJob)
async def duplicate(job_id: str, reframe: ReframeDep, config: ConfigDep) -> JsonTextResponse:
    """Add a copy of the job's settings right after it."""
    job = reframe.queue.get(job_id)
    if job is None:
        raise UnknownJobError(job_id)
    # Checked again: the saved queue may hold a job from a run with other roots.
    _check(config, job.settings, "the job")
    copy = await reframe.queue.add(job.settings, position=job.position + 1)
    return JsonTextResponse(_public(reframe, copy), status_code=201)


@router.delete("/queue/{job_id}", status_code=204)
async def remove(job_id: str, reframe: ReframeDep) -> None:
    """Remove a job and its log (409 while it runs or is paused: cancel it first)."""
    await reframe.queue.remove(job_id)


@router.get("/queue/{job_id}/log")
async def log(
    job_id: str,
    reframe: ReframeDep,
    from_: Annotated[int, Query(alias="from", ge=0)] = 0,
) -> JobLogChunk:
    """The job's log from byte ``from``: the command, the tool output and the timing of each
    run. Before the first run the log is empty."""
    if reframe.queue.get(job_id) is None:  # log_path() makes a path for any id
        raise UnknownJobError(job_id)
    return await asyncio.to_thread(_read_log, reframe.queue.log_path(job_id), from_)


def _read_log(path: Path, offset: int) -> JobLogChunk:
    try:
        with path.open("rb") as file:
            file.seek(offset)
            data = file.read(LOG_CHUNK)
    except FileNotFoundError:
        data = b""
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    text = decoder.decode(data)
    # A character cut by the chunk end or by a write in progress comes in the next answer.
    held, _ = decoder.getstate()
    return JobLogChunk(text=text, next=offset + len(data) - len(held), more=len(data) == LOG_CHUNK)
