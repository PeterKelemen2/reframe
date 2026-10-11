"""Background tasks (02 §Events, C-10): folder probe, crop scan, bitrate scan, …

Every long operation is a task with an id; the API returns the id at once and reports
progress with ``task.progress`` / ``task.done`` events.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import AwareDatetime, Field, JsonValue

from reframe.models.base import ReframeModel

__all__ = ["TaskInfo", "TaskState"]


class TaskState(StrEnum):
    QUEUED = "queued"
    """Waiting for a slot (each task kind has a concurrency limit)."""
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskInfo(ReframeModel):
    """``TaskInfo(id, kind, state, progress, message)``."""

    id: str
    kind: str
    """``probe_folder``, ``cropdetect``, ``bitrate_scan``, ``frames``, …"""
    state: TaskState = TaskState.QUEUED
    progress: Annotated[float, Field(ge=0.0, le=100.0)] | None = None
    """Percent; ``None`` = indeterminate."""
    message: str | None = None
    created_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    result: JsonValue = None
    """The task's result when ``done`` (its shape depends on ``kind``)."""
    error: str | None = None
