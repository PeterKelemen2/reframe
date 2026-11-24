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

from pydantic import Field, model_validator

from reframe.models.base import NonNegativeFloat, NonNegativeInt, PositiveInt, ReframeModel
from reframe.models.text import DisplayText

__all__ = [
    "ArgTemplate",
    "EncodePlan",
    "HeaderEdit",
    "HeaderFlag",
    "HeaderTrackType",
    "InfoHeaderEdit",
    "JobType",
    "Measurement",
    "PlanArg",
    "PlanFile",
    "PlanStep",
    "StepKind",
    "TrackHeaderEdit",
    "ValueRef",
    "resolve_argv",
]

JobType = Literal["encode", "remux", "metadata_edit"]
StepKind = Literal["analyse", "pass1", "pass2", "encode", "header_edit", "finalize"]
#: The track types of a header edit: the Matroska ``TrackType`` values Reframe edits.
HeaderTrackType = Literal["video", "audio", "subtitle"]
#: The track flags of a header edit (the names of ``reframe.models.job.TrackFlags``).
HeaderFlag = Literal[
    "default", "forced", "commentary", "hearing_impaired", "visual_impaired", "original"
]


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


class TrackHeaderEdit(ReframeModel):
    """The changes to one Matroska ``TrackEntry``. A field left at its default is kept."""

    track_type: HeaderTrackType
    number: PositiveInt
    """1-based: the n-th track of ``track_type`` in ``TrackEntry`` order."""
    language: str | None = None
    """ISO 639-2/B for ``Language``. Set together with ``language_ietf``: both are written."""
    language_ietf: str | None = None
    """BCP 47 for ``LanguageIETF``."""
    name: str | None = None
    """A new track name (not empty)."""
    delete_name: bool = False
    """Remove the ``Name`` element."""
    flags: dict[HeaderFlag, bool] = Field(default_factory=dict)
    """The flags to write, in the order of ``HeaderFlag``."""

    @model_validator(mode="after")
    def _consistent(self) -> TrackHeaderEdit:
        if (self.language is None) != (self.language_ietf is None):
            raise ValueError("language and language_ietf are set together")
        if self.delete_name and self.name is not None:
            raise ValueError("name and delete_name exclude each other")
        if self.name == "":
            raise ValueError("an empty name is delete_name")
        return self


class InfoHeaderEdit(ReframeModel):
    """The change to the segment ``Info``."""

    title: str | None
    """The new ``Title``; ``None`` removes it."""


class HeaderEdit(ReframeModel):
    """The Matroska header changes of one ``header_edit`` step, written into ``path`` in
    place (``reframe.metadata.header``)."""

    path: Path
    """The file to edit: the source of a ``metadata_edit`` job, else the ``.part`` file."""
    tracks: list[TrackHeaderEdit] = Field(default_factory=list)
    info: InfoHeaderEdit | None = None


class PlanStep(ReframeModel):
    """One step of a plan."""

    kind: StepKind
    tool: Literal["ffmpeg", "ffprobe"] | None
    """``None`` for ``finalize`` (rename ``.part`` → final name, done in Python) and
    ``header_edit`` (Reframe's own Matroska writer)."""
    argv: list[PlanArg] = Field(default_factory=list)
    """Arguments **after** the program (the runner prepends the discovered tool path)."""
    progress_weight: NonNegativeFloat = 1.0
    """Share of the job's progress bar (relative; the runner normalises the weights)."""
    description: DisplayText = ""
    measures: list[Measurement] = Field(default_factory=list)
    header_edit: HeaderEdit | None = None
    """The edits of a ``header_edit`` step, and only of one."""

    @model_validator(mode="after")
    def _header_edit_matches_kind(self) -> PlanStep:
        if (self.kind == "header_edit") != (self.header_edit is not None):
            raise ValueError("header_edit is set exactly on a header_edit step")
        if self.kind == "header_edit" and (self.tool is not None or self.argv):
            raise ValueError("a header_edit step runs no tool")
        return self


class PlanFile(ReframeModel):
    """A file that the runner writes before the steps run."""

    path: Path
    """Where to write it: next to ``output_tmp`` (``<name>.part.chapters.txt``)."""
    content: str
    """The full text, written as UTF-8 with LF line ends."""
    description: DisplayText = ""
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
    expected_frames: NonNegativeInt | None = None
    """Video frames that the encode writes (``expected_duration`` times the output frame
    rate), for progress when FFmpeg prints no output time; ``None`` when the rate is unknown."""
    display: DisplayText
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
