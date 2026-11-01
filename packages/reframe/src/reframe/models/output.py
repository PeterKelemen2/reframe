"""What a job's output will hold, shown before it is encoded: its job type, its chapters and its
tags; and chapter files read or written for it. Runtime models, never stored as documents."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from reframe.models.base import NonNegativeFloat, NonNegativeInt, PositiveInt, ReframeModel
from reframe.models.issues import ValidationIssue
from reframe.models.plan import JobType
from reframe.models.text import DisplayText

__all__ = [
    "ChapterExport",
    "ChapterFormat",
    "ChapterImport",
    "ChapterOrigin",
    "ImportedChapter",
    "JobTypeInfo",
    "OutputChapter",
    "OutputChapters",
    "RenderedTags",
    "TagValues",
]

#: A chapter file: HandBrake's CSV (``number,name``), OGM text (``CHAPTER01=…`` and
#: ``CHAPTER01NAME=…``) or Matroska XML (mkvmerge's ``--chapters`` file).
ChapterFormat = Literal["csv", "ogm", "xml"]
#: Where the output's chapters come from: the source's (copied or renamed), generated every N
#: minutes, or none.
ChapterOrigin = Literal["source", "generated", "none"]


class JobTypeInfo(ReframeModel):
    """The job type a job gets, and why."""

    job_type: JobType
    reason: DisplayText
    """One sentence; two when *Edit in place* is chosen but cannot be used (the second says
    why)."""
    in_place_blockers: list[DisplayText] = Field(default_factory=list)
    """Why this job could not edit its source in place, whether or not *Edit in place* is
    chosen; each a sentence fragment (``the video is encoded``). Empty: it could. For a source
    that is not MKV, the first one says so."""


class OutputChapter(ReframeModel):
    """One chapter of the output, in output time (seconds from the output's start)."""

    number: PositiveInt
    """1-based position in the output."""
    start: NonNegativeFloat
    end: NonNegativeFloat
    name: DisplayText
    """The name written; ``""``: none (a source chapter without a title, copied as it is)."""
    source_name: DisplayText | None
    """The source chapter's title; ``null`` for a generated chapter or a source chapter without
    one."""
    source_index: NonNegativeInt | None
    """0-based index of the source chapter this one comes from: its slot in
    ``ChapterSettings.names``, which is indexed by source chapter (a range leaves chapters out,
    so it can differ from ``number - 1``). ``null`` for a generated chapter, whose name is
    ``names[number - 1]``."""


class OutputChapters(ReframeModel):
    """The chapters the output gets, as the command writes them: the range, the renamed
    chapters, the generated ones, the container and *Create chapter markers* applied."""

    origin: ChapterOrigin
    chapters: list[OutputChapter] = Field(default_factory=list)
    reason: DisplayText = ""
    """Why there are none (``origin`` ``none``); empty otherwise."""


class ImportedChapter(ReframeModel):
    """One chapter read from a chapter file, in file order."""

    start: NonNegativeFloat | None
    """Seconds; ``null`` when the file has no time for it (CSV has none)."""
    name: DisplayText
    """``""`` when the file gives no name."""


class ChapterImport(ReframeModel):
    """The chapters of a chapter file. The names are meant to be used by position; the times
    only to compare with the output's chapters."""

    format: ChapterFormat
    chapters: list[ImportedChapter] = Field(default_factory=list)
    issues: list[ValidationIssue] = Field(default_factory=list)
    """What was read differently from the file (an encoding guessed, a part left out)."""


class ChapterExport(ReframeModel):
    """The output's chapters as the text of a chapter file."""

    format: ChapterFormat
    file_name: str
    """A file name to save it as: the output's name without its extension, then
    ``.chapters.csv``, ``.chapters.txt`` (OGM) or ``.chapters.xml``."""
    content: str
    """The file's text (to be saved as UTF-8)."""


class TagValues(ReframeModel):
    """One value per tag; ``null``: none."""

    title: str | None
    actors: str | None
    director: str | None
    release_date: str | None
    comment: str | None
    genre: str | None
    description: str | None
    plot: str | None


class RenderedTags(ReframeModel):
    """The job's tags as they will be written, next to the source's."""

    values: TagValues
    """Each set tag with the naming variables filled in (``{date}`` and ``{time}`` as of now);
    ``null`` for a tag the job does not set. An unknown variable is empty; a template with a
    syntax error is written as typed."""
    source: TagValues
    """The source file's value of each tag: what *Passthru common metadata* copies when the
    job does not set it."""
    issues: list[ValidationIssue] = Field(default_factory=list)
    """Template errors, at ``tags.<name>``."""
