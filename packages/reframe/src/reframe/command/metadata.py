"""Track metadata, chapters and tags of the plan.

Stream tags are never copied: every output track gets its language, title and flags written
explicitly. A BCP 47 tag that ISO 639-2 cannot express is written to Matroska ``LanguageIETF``
by an mkvpropedit step, since FFmpeg never writes that element.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from reframe import languages
from reframe.command.errors import PlanError
from reframe.definitions import ContainerDef, Definitions
from reframe.models import (
    Chapter,
    ChapterRange,
    JobSettings,
    MediaSource,
    NamingOptions,
    OutputChapter,
    OutputChapters,
    PlanFile,
    RenderedTags,
    Severity,
    TagSettings,
    TagValues,
    TrackMetadata,
    ValidationIssue,
)
from reframe.models.issues import FixTarget
from reframe.naming import check_template, render_value
from reframe.probe.bitrate import tag_value

__all__ = [
    "MAX_GENERATED_CHAPTERS",
    "TAG_KEYS",
    "ChapterPlan",
    "OutputTrack",
    "chapter_plan",
    "chapter_range",
    "container_language",
    "dispositions",
    "ffmetadata",
    "generated_starts",
    "ietf_edits",
    "needs_ietf",
    "planned_chapters",
    "render_tag",
    "rendered_tags",
    "stream_metadata_args",
    "tag_args",
    "tag_template_issues",
]

StreamType = Literal["v", "a", "s"]

#: TagSettings field → FFmpeg metadata key (HandBrake's mapping).
TAG_KEYS: dict[str, str] = {
    "title": "title",
    "actors": "artist",
    "director": "album_artist",
    "release_date": "date",
    "comment": "comment",
    "genre": "genre",
    "description": "description",
    "plot": "synopsis",
}


@dataclass(frozen=True, slots=True)
class OutputTrack:
    """One output stream with its metadata."""

    type: StreamType
    index: int
    metadata: TrackMetadata
    source_language: str | None
    source_title: str | None

    @property
    def language(self) -> str | None:
        """The effective language: the track's, else the source's (BCP 47 or ISO 639)."""
        return self.metadata.language or self.source_language

    @property
    def title(self) -> str | None:
        name = self.metadata.name
        return self.source_title if name is None else (name or None)


def container_language(value: str | None, container: ContainerDef) -> str:
    if container.language_format == "iso639_2t":
        return languages.to_mp4(value)
    return languages.to_matroska_legacy(value)


def needs_ietf(value: str | None) -> bool:
    """The BCP 47 tag says more than its ISO 639-2 code (``pt-BR``, ``yue``)."""
    if value is None:
        return False
    tag = languages.to_matroska_ietf(value)
    return tag != languages.to_matroska_ietf(languages.to_matroska_legacy(value))


def dispositions(flags: TrackMetadata, container: ContainerDef, definitions: Definitions) -> str:
    """``default+comment``, or ``0``: the flags the muxer can write."""
    names = [
        definitions.track_flags[flag].disposition
        for flag in container.flags
        if getattr(flags, flag)
    ]
    return "+".join(names) or "0"


def stream_metadata_args(
    tracks: list[OutputTrack], container: ContainerDef, definitions: Definitions
) -> list[str]:
    args: list[str] = []
    for t in tracks:
        target = f"s:{t.type}:{t.index}"
        args += [f"-metadata:{target}", f"language={container_language(t.language, container)}"]
        if t.title:
            args += [f"-metadata:{target}", f"title={t.title}"]
        args += [
            f"-disposition:{t.type}:{t.index}",
            dispositions(t.metadata, container, definitions),
        ]
    return args


def ietf_edits(tracks: list[OutputTrack]) -> list[str]:
    """``mkvpropedit`` arguments for the tracks whose language needs ``LanguageIETF``."""
    args: list[str] = []
    for t in tracks:
        if needs_ietf(t.language):
            tag = languages.to_matroska_ietf(t.language)
            args += ["--edit", f"track:{t.type}{t.index + 1}", "--set", f"language={tag}"]
    return args


@dataclass(slots=True)
class ChapterPlan:
    """``-map_chapters`` and, for renamed or generated chapters, the FFMETADATA file (the
    builder makes it an input and fills in its index)."""

    map_from: int | None
    """``0`` (the source), ``None`` (no chapters), or ``-1`` for "the FFMETADATA input"."""
    file: PlanFile | None = None

    FROM_FILE = -1


def _escape_ffmetadata(text: str) -> str:
    return "".join("\\" + c if c in "=;#\\\n" else c for c in text)


def ffmetadata(chapters: list[tuple[float, float, str]]) -> str:
    """An FFMETADATA file with the chapters ``(start, end, title)`` in seconds (millisecond
    time base; ``= ; # \\`` and line ends escaped)."""
    lines = [";FFMETADATA1"]
    for start, end, title in chapters:
        lines += [
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={round(start * 1000)}",
            f"END={round(end * 1000)}",
        ]
        if title:
            lines.append(f"title={_escape_ffmetadata(title)}")
    return "\n".join(lines) + "\n"


#: Seconds: a chapter edge this close to the range start or end counts as on it.
CHAPTER_EDGE = 0.001


def _empty_when_copied(chapters: list[Chapter], start: float, duration: float | None) -> bool:
    """Whether ``-map_chapters 0`` would write an empty chapter: FFmpeg's copy (fftools
    ``copy_chapters``) skips a chapter only when it ends *before* the range start, and stops
    only at one that starts *after* the range end (testdata/README.md)."""
    if start > 0 and any(abs(ch.end - start) < CHAPTER_EDGE for ch in chapters):
        return True
    if duration is None:
        return False
    return any(abs(ch.start - (start + duration)) < CHAPTER_EDGE for ch in chapters)


def _renamed(
    chapters: list[Chapter], names: list[str] | None, start: float, duration: float | None
) -> list[OutputChapter]:
    out: list[OutputChapter] = []
    for i, ch in enumerate(chapters):
        s, e = ch.start - start, ch.end - start
        if duration is not None:
            e = min(e, duration)
        if e < CHAPTER_EDGE or (duration is not None and s > duration - CHAPTER_EDGE):
            continue
        name = names[i] if names is not None and i < len(names) and names[i] else None
        # An untitled chapter stays untitled, as when FFmpeg copies the chapters.
        out.append(
            OutputChapter(
                number=len(out) + 1, start=max(0.0, s), end=e, name=name or ch.title or "",
                source_name=ch.title, source_index=i,
            )
        )  # fmt: skip
    return out


#: A generated last chapter shorter than this share of the interval is merged into the one
#: before it, so that no tiny chapter ends the film.
GENERATED_TAIL = 0.25
#: More generated chapters than this is a mistake in the interval; none are made.
MAX_GENERATED_CHAPTERS = 1000


def generated_starts(every_minutes: float, duration: float) -> list[float] | None:
    """The start times of the chapters generated every ``every_minutes`` over ``duration``
    seconds; ``None`` when they would be more than :data:`MAX_GENERATED_CHAPTERS`. The work is
    bounded by that limit, whatever the interval."""
    step = every_minutes * 60
    count = duration / step if step > 0 else math.inf
    if not count < MAX_GENERATED_CHAPTERS + 1:
        return None
    starts = [k * step for k in range(int(count) + 1) if k * step < duration]
    if len(starts) > 1 and duration - starts[-1] < GENERATED_TAIL * step:
        starts.pop()
    return starts if len(starts) <= MAX_GENERATED_CHAPTERS else None


def _generated(
    every_minutes: float, duration: float, names: list[str] | None
) -> list[OutputChapter] | None:
    starts = generated_starts(every_minutes, duration)
    if starts is None:
        return None
    out: list[OutputChapter] = []
    for k, start in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else duration
        name = names[k] if names is not None and k < len(names) and names[k] else None
        out.append(
            OutputChapter(
                number=k + 1, start=start, end=end, name=name or f"Chapter {k + 1}",
                source_name=None, source_index=None,
            )
        )  # fmt: skip
    return out


def _none(reason: str) -> tuple[OutputChapters, bool]:
    return OutputChapters(origin="none", reason=reason), False


def planned_chapters(
    job: JobSettings,
    source: MediaSource,
    container: ContainerDef,
    *,
    start: float,
    duration: float | None,
    expected_duration: float,
) -> tuple[OutputChapters, bool]:
    """The chapters the output gets, in output time, and whether ``-map_chapters 0`` writes
    them (else an FFMETADATA file does). ``start`` and ``duration`` are the range's seek and
    length (``None``: to the end); ``expected_duration`` the output's length."""
    settings = job.chapters
    if not settings.enabled:
        return _none("Create chapter markers is off.")
    if not container.chapters:
        return _none(f"{container.label} files cannot hold chapters.")
    if source.chapters:
        names = settings.names
        copied = names is None and not _empty_when_copied(source.chapters, start, duration)
        chapters = _renamed(source.chapters, names, start, duration)
        if copied:
            # FFmpeg copies the chapters as they are: one without a title stays without one.
            chapters = [c.model_copy(update={"name": c.source_name or ""}) for c in chapters]
        if not chapters:
            return _none("No chapter of the source is inside the range.")
        return OutputChapters(origin="source", chapters=chapters), copied
    if settings.generate_every is None:
        return _none("The source has no chapters.")
    if expected_duration <= 0:
        return _none("The source's duration is not known, so no chapters can be generated.")
    generated = _generated(settings.generate_every, expected_duration, settings.names)
    if generated is None:
        return _none(
            f"A chapter every {settings.generate_every:g} minutes would make more than "
            f"{MAX_GENERATED_CHAPTERS} chapters, so none are generated."
        )
    return OutputChapters(origin="generated", chapters=generated), False


def chapter_plan(
    job: JobSettings,
    source: MediaSource,
    container: ContainerDef,
    *,
    start: float,
    duration: float | None,
    expected_duration: float,
    file_path: Path,
) -> ChapterPlan:
    planned, copied = planned_chapters(
        job, source, container, start=start, duration=duration, expected_duration=expected_duration
    )
    if not planned.chapters:
        return ChapterPlan(map_from=None)
    if copied:
        return ChapterPlan(map_from=0)
    content = ffmetadata([(c.start, c.end, c.name) for c in planned.chapters])
    file = PlanFile(path=file_path, content=content, description="FFMETADATA chapters")
    return ChapterPlan(map_from=ChapterPlan.FROM_FILE, file=file)


def chapter_range(source: MediaSource, job_range: ChapterRange) -> tuple[float, float]:
    """``(start, end)`` seconds of a chapter range (1-based, inclusive).

    An end after the last chapter is clamped to the last chapter, as a time or frame range is
    clamped to the source. A range that starts after the last chapter, or ends before it starts,
    cannot be planned.
    """
    chapters = source.chapters
    if not 1 <= job_range.start <= min(job_range.end, len(chapters)):
        raise PlanError(
            f"chapters {job_range.start} to {job_range.end} are not in the source "
            f"({len(chapters)} chapters; validation reports it)"
        )
    last = min(job_range.end, len(chapters))
    return chapters[job_range.start - 1].start, chapters[last - 1].end


def render_tag(
    template: str,
    job: JobSettings,
    source: MediaSource,
    *,
    options: NamingOptions,
    output_size: tuple[int, int] | None,
    now: datetime | None,
    definitions: Definitions,
) -> str:
    """A tag value with the naming variables filled in, through :func:`reframe.naming.render_value`
    with no file-system reads. Without ``now``, ``{date}`` and ``{time}`` are empty;
    ``{modification-date}`` is always empty (it needs the file system). A template with errors is
    written as typed."""
    return render_value(
        template, job, source, options=options, output_size=output_size, now=now,
        definitions=definitions,
    )  # fmt: skip


def tag_template_issues(tags: TagSettings, *, target: FixTarget = "job") -> list[ValidationIssue]:
    """The template errors of the set tags (:func:`reframe.naming.check_template`'s errors), at
    ``tags.<name>``, with fixes for ``target``."""
    issues: list[ValidationIssue] = []
    for name in TAG_KEYS:
        template = getattr(tags, name)
        if template is None:
            continue
        issues += [
            issue
            for issue in check_template(template, field=f"tags.{name}", target=target)
            if issue.severity is Severity.ERROR
        ]
    return issues


def rendered_tags(
    job: JobSettings,
    source: MediaSource,
    *,
    options: NamingOptions,
    output_size: tuple[int, int] | None,
    now: datetime | None,
    definitions: Definitions,
) -> RenderedTags:
    """Each tag of ``job`` as :func:`tag_args` writes it, the source's values, and the template
    errors of the tags (at ``tags.<name>``)."""
    values: dict[str, str | None] = {}
    found: dict[str, str | None] = {}
    for name, key in TAG_KEYS.items():
        template = getattr(job.tags, name)
        found[name] = (source.container.title if name == "title" else None) or tag_value(
            source.container.tags, key
        )
        if template is None:
            values[name] = None
            continue
        values[name] = render_tag(
            template, job, source, options=options, output_size=output_size, now=now,
            definitions=definitions,
        )  # fmt: skip
    return RenderedTags(
        values=TagValues.model_validate(values),
        source=TagValues.model_validate(found),
        issues=tag_template_issues(job.tags),
    )


def tag_args(tags: TagSettings, *, passthru: bool, render_value: Callable[[str], str]) -> list[str]:
    """``-map_metadata 0`` (or ``:g -1``) and one ``-metadata key=value`` per set tag."""
    args = ["-map_metadata", "0"] if passthru else ["-map_metadata:g", "-1"]
    for field_name, key in TAG_KEYS.items():
        value = getattr(tags, field_name)
        if value is None:
            continue
        args += ["-metadata", f"{key}={render_value(value)}"]
    return args
