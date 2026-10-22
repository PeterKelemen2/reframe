"""Background tasks: the list, one task's state and result, cancel. Routes that start a long
operation answer with its task id. No answer names a folder of the server's own."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, JsonValue

from reframe.models import TaskInfo
from reframe.service import Reframe
from reframe_server.api import JsonTextResponse, api_router
from reframe_server.deps import ReframeDep
from reframe_server.errors import ProblemError
from reframe_server.folders import hide_server_folders

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


@router.get("/tasks", response_model=list[TaskInfo])
async def snapshot(reframe: ReframeDep, kind: str | None = None) -> JsonTextResponse:
    """Running and recently finished tasks, oldest first; ``kind`` keeps one kind."""
    tasks: JsonValue = [info.model_dump(mode="json") for info in reframe.tasks.list(kind)]
    return JsonTextResponse(hide_server_folders(reframe, tasks))


@router.get("/tasks/{task_id}", response_model=TaskInfo)
async def get(task_id: str, reframe: ReframeDep) -> JsonTextResponse:
    """One task's state, progress and, when done, its result."""
    info: JsonValue = _task(reframe, task_id).model_dump(mode="json")
    return JsonTextResponse(hide_server_folders(reframe, info))


@router.post("/tasks/{task_id}/cancel")
async def cancel(task_id: str, reframe: ReframeDep) -> TaskCancel:
    """Cancel a queued or running task."""
    _task(reframe, task_id)  # cancel() says False for an unknown id too
    return TaskCancel(cancelled=reframe.tasks.cancel(task_id))
