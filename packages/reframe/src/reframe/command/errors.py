"""The one exception of the command builder."""

from __future__ import annotations

__all__ = ["PlanError"]


class PlanError(ValueError):
    """The job cannot be planned.

    Validation reports every expected problem as an issue, and the caller runs it before
    :func:`reframe.command.build_plan`. So this is a programming error (a job with validation
    errors reached the builder), never an expected failure: the builder never returns a
    half-built plan.
    """
