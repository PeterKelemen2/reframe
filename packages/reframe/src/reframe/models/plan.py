"""Encode plans: the exact commands for one job.

``build_plan`` is pure: it builds the commands and runs nothing. A step can need a value that an
earlier step measures. Such an argument is an :class:`ArgTemplate` (literal text and
:class:`ValueRef` parts), and :func:`resolve_argv` turns it into plain strings once the values
are known.
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
    "PlanFile",
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


class PlanFile(ReframeModel):
    """A file that the runner writes before the steps run."""

    path: Path
    """Where to write it: next to ``output_tmp`` (``<name>.part.chapters.txt``)."""
    content: str
    """The full text, written as UTF-8 with LF line ends."""
    description: str = ""
    """For the log: ``FFMETADATA chapters``."""


class EncodePlan(ReframeModel):
    """The steps of one job, with the files they read and the files they leave behind."""

    job_type: JobType
    steps: list[PlanStep]
    output_tmp: Path
    """``<name>.part.<ext>``."""
    output_final: Path
    expected_duration: NonNegativeFloat
    """Seconds, range-adjusted, for progress."""
    display: str
    """Shell-quoted command preview (POSIX or Windows style); a measured value shows as
    ``<a0.input_i>``."""
    files: list[PlanFile] = Field(default_factory=list)
    """Files to write before the first step and remove after the job."""
    temp_files: list[Path] = Field(default_factory=list)
    """Files that the steps create and that the runner removes when the job ends, whatever
    the outcome (2-pass statistics). A file that does not exist is skipped."""


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
