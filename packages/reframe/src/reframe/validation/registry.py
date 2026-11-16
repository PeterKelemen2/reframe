"""The rule registry. A rule is a function from a :class:`~reframe.validation.context.JobContext`
or :class:`~reframe.validation.context.TemplateContext` to issues. :func:`job_rule`,
:func:`template_rule` and :func:`shared_rule` register it with its area and the issue codes it
can produce. Rules run area by area, in :data:`AREAS` order, then in registration order.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, get_args

from reframe.models.issues import ValidationIssue

if TYPE_CHECKING:
    from reframe.validation.context import JobContext, TemplateContext

__all__ = [
    "AREAS",
    "JOB_RULES",
    "TEMPLATE_RULES",
    "Area",
    "Rule",
    "job_rule",
    "ordered",
    "shared_rule",
    "template_rule",
]

Area = Literal[
    "tools",
    "source",
    "encoder",
    "container",
    "dimensions",
    "filters",
    "audio",
    "subtitles",
    "metadata",
    "range",
    "output",
    "naming",
]
#: The order in which areas are checked (and issues are listed).
AREAS: tuple[Area, ...] = get_args(Area)


@dataclass(frozen=True, slots=True)
class Rule[C]:
    """One registered rule."""

    area: Area
    name: str
    check: Callable[[C], Iterable[ValidationIssue]]
    codes: tuple[str, ...]
    """The issue codes this rule can produce."""


#: Rules of :func:`reframe.validation.validate` (a job).
JOB_RULES: list[Rule[JobContext]] = []
#: Rules of :func:`reframe.validation.validate_template` (a preset or batch template).
TEMPLATE_RULES: list[Rule[TemplateContext]] = []

type _Check[C] = Callable[[C], Iterable[ValidationIssue]]


def job_rule(area: Area, *codes: str) -> Callable[[_Check[JobContext]], _Check[JobContext]]:
    """Register a job rule."""

    def register(check: _Check[JobContext]) -> _Check[JobContext]:
        JOB_RULES.append(Rule(area, check.__name__, check, codes))
        return check

    return register


def template_rule(
    area: Area, *codes: str
) -> Callable[[_Check[TemplateContext]], _Check[TemplateContext]]:
    """Register a template rule."""

    def register(check: _Check[TemplateContext]) -> _Check[TemplateContext]:
        TEMPLATE_RULES.append(Rule(area, check.__name__, check, codes))
        return check

    return register


def shared_rule(
    area: Area, *codes: str
) -> Callable[[_Check[JobContext | TemplateContext]], _Check[JobContext | TemplateContext]]:
    """Register a rule that checks a job and a template alike (through ``ctx.doc``)."""

    def register(
        check: _Check[JobContext | TemplateContext],
    ) -> _Check[JobContext | TemplateContext]:
        JOB_RULES.append(Rule(area, check.__name__, check, codes))
        TEMPLATE_RULES.append(Rule(area, check.__name__, check, codes))
        return check

    return register


def ordered[C](rules: Iterable[Rule[C]]) -> list[Rule[C]]:
    """``rules`` by area (:data:`AREAS`), then in registration order."""
    indexed = list(enumerate(rules))
    indexed.sort(key=lambda item: (AREAS.index(item[1].area), item[0]))
    return [rule for _, rule in indexed]
