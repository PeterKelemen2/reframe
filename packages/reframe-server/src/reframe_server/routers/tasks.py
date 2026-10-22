"""Background tasks: the list, one task's state and result, cancel. Routes that start a long
operation answer with its task id. No answer names a folder of the server's own."""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, JsonValue

from reframe.models import TaskInfo
from reframe.service import Reframe
from reframe_server.api import JsonTextResponse, api_router
from reframe_server.deps import ReframeDep
from reframe_server.errors import ProblemError

router = api_router("tasks")


class TaskCancel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    cancelled: bool
    """``false``: the task had already ended. Its end comes as a ``task.done`` event."""


@dataclass(frozen=True)
class _FolderMask:
    pattern: re.Pattern[str]
    labels: dict[str, str]

    def text(self, text: str) -> str:
        return self.pattern.sub(lambda match: self.labels[match.group(0)], text)

    def value(self, value: JsonValue) -> JsonValue:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.value(item) for item in value]
        if isinstance(value, dict):
            return {self.text(key): self.value(item) for key, item in value.items()}
        return value


@functools.cache
def _mask(config: str, data: str, cache: str) -> _FolderMask:
    labels: dict[str, str] = {}
    for folder, label in ((config, "<config>"), (data, "<data>"), (cache, "<cache>")):
        labels.setdefault(folder, label)
    # Longest first: on Windows the cache folder is inside the data folder.
    texts = sorted(labels, key=len, reverse=True)
    alternatives = "|".join(re.escape(text) for text in texts)
    # The folder's text inside a longer name ("/srv/data2", "/mnt/srv/data") is another path.
    pattern = re.compile(rf"(?<![\w.\-\\/])(?:{alternatives})(?![\w.\-])")
    return _FolderMask(pattern, labels)


def hide_server_folders(reframe: Reframe, value: JsonValue) -> JsonValue:
    """``value`` with the server's config, data and cache folders written as ``<config>``,
    ``<data>`` and ``<cache>`` in every string: a client never learns where the server keeps
    its own files."""
    mask = _mask(str(reframe.config_dir), str(reframe.data_dir), str(reframe.cache_dir))
    return mask.value(value)


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
