"""Background tasks: the list, one task's state and result, cancel. Routes that start a long
operation answer with its task id."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from reframe.models import TaskInfo
from reframe.service import Reframe
from reframe_server.api import api_router
from reframe_server.deps import ReframeDep
from reframe_server.errors import ProblemError

router = api_router("tasks")


class TaskCancel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    cancelled: bool
    """``false``: the task had already ended. Its end comes as a ``task.done`` event."""


def _task(reframe: Reframe, task_id: str) -> TaskInfo:
    info = reframe.tasks.get(task_id)
    if info is None:
        raise ProblemError(404, "tasks.unknown", f"No task {task_id}")
    return info


@router.get("/tasks")
async def snapshot(reframe: ReframeDep, kind: str | None = None) -> list[TaskInfo]:
    """Running and recently finished tasks, oldest first; ``kind`` keeps one kind."""
    return reframe.tasks.list(kind)


@router.get("/tasks/{task_id}")
async def get(task_id: str, reframe: ReframeDep) -> TaskInfo:
    """One task's state, progress and, when done, its result."""
    return _task(reframe, task_id)


@router.post("/tasks/{task_id}/cancel")
async def cancel(task_id: str, reframe: ReframeDep) -> TaskCancel:
    """Cancel a queued or running task."""
    _task(reframe, task_id)  # cancel() says False for an unknown id too
    return TaskCancel(cancelled=reframe.tasks.cancel(task_id))
