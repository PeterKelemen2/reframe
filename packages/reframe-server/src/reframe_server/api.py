"""What every router shares: the JSON response class, the router factory with its
``operationId`` rule, and the ``202 {task_id}`` answer of a long operation."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from reframe.models import TaskInfo, ValidationIssue, json_text

__all__ = [
    "API_VERSION",
    "PROBLEM_RESPONSES",
    "JsonTextResponse",
    "Problem",
    "RequestError",
    "TaskAccepted",
    "accepted",
    "api_router",
    "operation_id",
]

API_VERSION = 1
"""Raised when a change breaks a client of an earlier version (the CLI checks it)."""


class JsonTextResponse(JSONResponse):
    """JSON written with :func:`reframe.models.json_text`: a path byte that is not UTF-8 is a
    ``\\udcXX`` escape instead of an error."""

    def render(self, content: Any) -> bytes:
        return json_text(content).encode("ascii")


class TaskAccepted(BaseModel):
    """A long operation started as a background task; its progress arrives as events."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    task_id: str
    """Poll ``GET /api/tasks/{task_id}`` or follow ``task.*`` events."""


def accepted(task: TaskInfo) -> JsonTextResponse:
    """The ``202`` answer for ``task``, with its status URL in ``Location``."""
    return JsonTextResponse(
        TaskAccepted(task_id=task.id).model_dump(),
        status_code=202,
        headers={"Location": f"/api/tasks/{task.id}"},
    )


def operation_id(route: APIRoute) -> str:
    """``<tag>_<handler name>``: the generated client's function name, so it never changes
    when a path does."""
    return f"{route.tags[0]}_{route.name}" if route.tags else route.name


class RequestError(BaseModel):
    """One field of a request that did not validate."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    loc: list[str | int]
    """Where: ``["body", "job", "video", "quality"]``, ``["query", "path"]``."""
    msg: str
    type: str


class Problem(BaseModel):
    """An error answer (``application/problem+json``, RFC 9457)."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    code: str
    """Stable dotted identifier, for example ``path.outside_roots`` or ``queue.unknown_job``."""
    issues: list[ValidationIssue] = Field(default_factory=list)
    """The validation issues behind the failure, if any."""
    errors: list[RequestError] = Field(default_factory=list)
    """The request fields that did not validate (``request.invalid``)."""


PROBLEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    "4XX": {"description": "An expected failure", "model": Problem},
}


def api_router(tag: str) -> APIRouter:
    """A router whose handlers get ``operationId`` ``<tag>_<handler name>`` and write JSON with
    :class:`JsonTextResponse`. Name handlers by what they do: ``probe`` in ``sources`` is
    ``sources_probe``."""
    return APIRouter(
        tags=[tag],
        default_response_class=JsonTextResponse,
        generate_unique_id_function=operation_id,
        responses=PROBLEM_RESPONSES,
    )
