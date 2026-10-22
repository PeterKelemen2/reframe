"""Every error answer is ``application/problem+json`` (:class:`~reframe_server.api.Problem`).
Routers raise :class:`ProblemError` or let the facade's expected failures through; the
handlers here map them. A request body is never echoed back, so a secret in it cannot leak."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from reframe.models import ValidationIssue
from reframe.probe import ProbeError, ProbeErrorKind
from reframe.queue.errors import JobStateError, UnknownJobError
from reframe.service import ReframeClosedError
from reframe_server.api import JsonTextResponse, Problem, RequestError

__all__ = [
    "PROBLEM_MEDIA_TYPE",
    "ProblemError",
    "install_error_handlers",
    "issue_problem",
    "probe_problem",
    "problem_response",
]

log = logging.getLogger(__name__)

PROBLEM_MEDIA_TYPE = "application/problem+json"

_PROBE_STATUS = {
    ProbeErrorKind.NOT_FOUND: 404,
    ProbeErrorKind.NOT_A_FILE: 404,
    ProbeErrorKind.UNREADABLE: 403,
    ProbeErrorKind.TOOL_FAILED: 503,
    ProbeErrorKind.TIMEOUT: 504,
    ProbeErrorKind.CANCELLED: 503,
    ProbeErrorKind.FAILED: 422,
    ProbeErrorKind.INVALID_OUTPUT: 422,
}


class ProblemError(Exception):
    """Raise in a handler or dependency to answer with a problem."""

    def __init__(
        self,
        status: int,
        code: str,
        title: str,
        detail: str | None = None,
        *,
        issues: Sequence[ValidationIssue] = (),
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(f"{status} {code}: {title}")
        self.problem = Problem(
            title=title, status=status, detail=detail, code=code, issues=list(issues)
        )
        self.headers = headers


def problem_response(problem: Problem, headers: dict[str, str] | None = None) -> JsonTextResponse:
    return JsonTextResponse(
        problem.model_dump(mode="json"),
        status_code=problem.status,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=headers,
    )


def issue_problem(issue: ValidationIssue, status: int = 422) -> ProblemError:
    """A facade call that returned one issue instead of a result (``presets.save``, …)."""
    return ProblemError(status, issue.code, issue.message, issues=[issue])


def probe_problem(error: ProbeError) -> ProblemError:
    """A file that could not be probed; the status says whose fault it is."""
    return ProblemError(
        _PROBE_STATUS[error.kind], f"probe.{error.kind.value}", error.message, error.detail
    )


async def _problem(_request: Request, exc: Exception) -> JsonTextResponse:
    assert isinstance(exc, ProblemError)
    return problem_response(exc.problem, exc.headers)


async def _invalid_request(_request: Request, exc: Exception) -> JsonTextResponse:
    assert isinstance(exc, RequestValidationError)
    errors = [
        RequestError(
            loc=[part for part in error.get("loc", ()) if isinstance(part, str | int)],
            msg=str(error.get("msg", "")),
            type=str(error.get("type", "")),
        )
        for error in exc.errors()
    ]
    return problem_response(
        Problem(title="The request is not valid", status=422, code="request.invalid", errors=errors)
    )


async def _http(_request: Request, exc: Exception) -> JsonTextResponse:
    assert isinstance(exc, HTTPException)
    problem = Problem(title=str(exc.detail), status=exc.status_code, code=f"http.{exc.status_code}")
    return problem_response(problem, dict(exc.headers) if exc.headers else None)


async def _unknown_job(_request: Request, exc: Exception) -> JsonTextResponse:
    assert isinstance(exc, UnknownJobError)
    return problem_response(
        Problem(title=f"No job {exc.job_id}", status=404, code="queue.unknown_job")
    )


async def _job_state(_request: Request, exc: Exception) -> JsonTextResponse:
    return problem_response(Problem(title=str(exc), status=409, code="queue.job_state"))


async def _closed(_request: Request, _exc: Exception) -> JsonTextResponse:
    return problem_response(
        Problem(title="The server is shutting down", status=503, code="server.closing")
    )


async def _unexpected(request: Request, exc: Exception) -> JsonTextResponse:
    log.error("unexpected error in %s %s", request.method, request.url.path, exc_info=exc)
    return problem_response(
        Problem(title="Internal Server Error", status=500, code="server.unexpected")
    )


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ProblemError, _problem)
    app.add_exception_handler(RequestValidationError, _invalid_request)
    app.add_exception_handler(HTTPException, _http)
    app.add_exception_handler(UnknownJobError, _unknown_job)
    app.add_exception_handler(JobStateError, _job_state)
    app.add_exception_handler(ReframeClosedError, _closed)
    app.add_exception_handler(Exception, _unexpected)
