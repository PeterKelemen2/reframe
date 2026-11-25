"""Queue jobs and progress.

A :class:`QueueJob` is one row of the queue's SQLite ``jobs`` table, with the JSON columns as
models.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

from pydantic import AwareDatetime, ConfigDict, Field

from reframe.models.base import (
    DocumentModel,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveInt,
    ReframeModel,
)
from reframe.models.issues import ValidationIssue
from reframe.models.job import JobSettings
from reframe.models.plan import EncodePlan, StepKind
from reframe.models.text import DisplayText

__all__ = ["JobProgress", "JobState", "QueueJob", "ServerEndpoint"]


class JobState(StrEnum):
    """The queue states. ``interrupted``: it was running when Reframe stopped."""

    WAITING = "waiting"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class JobProgress(ReframeModel):
    """Progress of a running job."""

    percent: Annotated[float, Field(ge=0.0, le=100.0)] = 0.0
    """Whole job, weighted across steps."""
    fps: NonNegativeFloat | None = None
    speed: NonNegativeFloat | None = None
    """Encoding speed as a multiple of real time (``2.5`` = 2.5x)."""
    eta: NonNegativeFloat | None = None
    """Seconds left (from a smoothed speed); ``None`` while unknown."""
    output_size: NonNegativeInt | None = None
    """Bytes written so far."""
    step: NonNegativeInt = 0
    """Index of the running step."""
    step_count: NonNegativeInt = 1
    step_kind: StepKind | None = None


class QueueJob(ReframeModel):
    """One job of the queue. ``settings`` is a document model: unknown fields of a newer
    Reframe are kept. ``plan`` and ``issues`` are derived data: the runner validates and
    plans again before it starts a job."""

    id: str
    position: NonNegativeInt
    state: JobState = JobState.WAITING
    settings: JobSettings
    plan: EncodePlan | None = None
    issues: list[ValidationIssue] = Field(default_factory=list)
    created_at: AwareDatetime
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    output_path: Path | None = None
    output_size: NonNegativeInt | None = None
    """Bytes of the finished output; ``None`` until the job is done."""
    log_path: Path | None = None
    error: DisplayText | None = None
    progress: JobProgress | None = None
    """Live progress while running (not a database column)."""


class ServerEndpoint(DocumentModel):
    """``<data dir>/server.json``: how a front end reaches the server that owns the queue. It is
    a hint: a process that can take ``queue.lock`` knows that the file is stale. A file of a
    newer server keeps its unknown fields; ``api_version`` says whether a client can use it."""

    # A validation error would otherwise show the token as its input.
    model_config = ConfigDict(hide_input_in_errors=True)

    pid: PositiveInt
    instance: str
    """Random id of the server run, as in ``GET /api/health``."""
    port: Annotated[int, Field(ge=1, le=65535)]
    token: str = Field(repr=False)
    """The local token: accepted as ``Authorization: Bearer`` in every auth mode."""
    version: str
    api_version: PositiveInt
    started_at: AwareDatetime
