"""Encode plans (C-7): the exact commands for one job.

``build_plan(job, source, caps, tools) -> EncodePlan`` is pure. The queue runner (C-11) runs
the steps in order.

**Measured values.** A later step can need a value that an earlier step measures: two-pass
``loudnorm`` needs the ``input_i`` / ``input_tp`` / ``input_lra`` / ``input_thresh`` /
``target_offset`` that the ``analyse`` step prints. Such an argument is an
:class:`ArgTemplate` instead of a plain string: literal parts and :class:`ValueRef` parts,
joined after substitution. A step declares what it measures in ``measures``
(:class:`Measurement`: an id and a parser); the runner parses the step's output and stores
the values as ``"<measurement id>.<key>"`` (``"a0.input_i"``). :func:`resolve_argv` turns
an argv with templates into plain strings. Example (one audio track)::

    PlanStep(kind="analyse", tool="ffmpeg", argv=[..., "-af",
             "loudnorm=I=-23:TP=-1:LRA=7:print_format=json", "-f", "null", "-"],
             measures=[Measurement(id="a0", parser="loudnorm")])
    PlanStep(kind="encode", tool="ffmpeg", argv=[..., "-filter:a:0", ArgTemplate(parts=[
             "loudnorm=I=-23:TP=-1:LRA=7:measured_I=", ValueRef(ref="a0.input_i"),
             ":measured_TP=", ValueRef(ref="a0.input_tp"), ...]), ...])

The command preview (:attr:`EncodePlan.display`) shows a reference as
``<a0.input_i>``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from reframe.models.base import NonNegativeFloat, ReframeModel

__all__ = [
    "ArgTemplate",
    "EncodePlan",
    "JobType",
    "Measurement",
    "PlanArg",
    "PlanStep",
    "StepKind",
    "ValueRef",
    "resolve_argv",
]

JobType = Literal["encode", "remux", "metadata_edit"]
StepKind = Literal["analyse", "pass1", "pass2", "encode", "mkvpropedit", "finalize"]


class ValueRef(ReframeModel):
    """A value measured by an earlier step: ``"<measurement id>.<key>"``."""

    ref: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_]+$")]


class ArgTemplate(ReframeModel):
    """An argument built from literal text and measured values (joined without spaces)."""

    parts: list[str | ValueRef]


#: One argv element: a plain string, or a template with measured values.
PlanArg = str | ArgTemplate


class Measurement(ReframeModel):
    """A value set that a step measures. ``loudnorm``: the JSON block that
    ``loudnorm=print_format=json`` prints on stderr (one per filter, in filter order)."""

    id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]+$")]
    parser: Literal["loudnorm"]


class PlanStep(ReframeModel):
    """One step of a plan."""

    kind: StepKind
    tool: Literal["ffmpeg", "ffprobe", "mkvpropedit"] | None
    """``None`` for ``finalize`` (rename ``.part`` → final name, done in Python)."""
    argv: list[PlanArg] = Field(default_factory=list)
    """Arguments **after** the program (the runner prepends the discovered tool path)."""
    progress_weight: NonNegativeFloat = 1.0
    """Share of the job's progress bar (relative; the runner normalises the weights)."""
    description: str = ""
    measures: list[Measurement] = Field(default_factory=list)


class EncodePlan(ReframeModel):
    """``EncodePlan`` exactly as C-7 sketches it."""

    job_type: JobType
    steps: list[PlanStep]
    output_tmp: Path
    """``<name>.part.<ext>``."""
    output_final: Path
    expected_duration: NonNegativeFloat
    """Seconds, range-adjusted, for progress."""
    display: str
    """Shell-quoted command preview (POSIX or Windows style)."""


def resolve_argv(argv: Sequence[PlanArg], values: Mapping[str, str]) -> list[str]:
    """Replace every :class:`ArgTemplate` by its text. A missing value raises ``KeyError``
    (a plan whose analyse step did not run is a programming error)."""
    result: list[str] = []
    for arg in argv:
        if isinstance(arg, str):
            result.append(arg)
            continue
        result.append(
            "".join(part if isinstance(part, str) else values[part.ref] for part in arg.parts)
        )
    return result
