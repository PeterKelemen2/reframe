"""Queue jobs and progress (03 §Queue, C-11).

A :class:`QueueJob` is one row of the SQLite ``jobs`` table (C-11): ``id, position, state,
settings_json, plan_json, issues_json, created_at, started_at, finished_at, output_path,
log_path, error``, with the JSON columns as models.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

from pydantic import AwareDatetime, Field

from reframe.models.base import NonNegativeFloat, NonNegativeInt, ReframeModel
from reframe.models.issues import ValidationIssue
from reframe.models.job import JobSettings
from reframe.models.plan import EncodePlan, StepKind

__all__ = ["JobProgress", "JobState", "QueueJob"]


class JobState(StrEnum):
    """The seven queue states. ``interrupted``: it was running when Reframe stopped."""

    WAITING = "waiting"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class JobProgress(ReframeModel):
    """Progress of a running job (``job.progress`` event, queue columns)."""

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
    log_path: Path | None = None
    error: str | None = None
    progress: JobProgress | None = None
    """Live progress while running (not a database column)."""
