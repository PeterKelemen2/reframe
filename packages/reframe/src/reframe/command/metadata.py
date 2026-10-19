"""Track metadata, chapters and tags of the plan.

Stream tags are never copied: every output track gets its language, title and flags written
explicitly. A BCP 47 tag that ISO 639-2 cannot express is written to Matroska ``LanguageIETF``
by an mkvpropedit step, since FFmpeg never writes that element.
"""

from __future__ import annotations

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
    PlanFile,
    TagSettings,
    TrackMetadata,
)
from reframe.naming import render_value

__all__ = [
    "TAG_KEYS",
    "ChapterPlan",
    "OutputTrack",
    "chapter_plan",
    "chapter_range",
    "container_language",
    "dispositions",
    "ffmetadata",
    "ietf_edits",
    "needs_ietf",
    "render_tag",
    "stream_metadata_args",
    "tag_args",
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


# --------------------------------------------------------------------------- languages


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


# --------------------------------------------------------------------------- chapters


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
) -> list[tuple[float, float, str]]:
    out: list[tuple[float, float, str]] = []
    for i, ch in enumerate(chapters):
        s, e = ch.start - start, ch.end - start
        if duration is not None:
            e = min(e, duration)
        if e < CHAPTER_EDGE or (duration is not None and s > duration - CHAPTER_EDGE):
            continue
        name = names[i] if names is not None and i < len(names) and names[i] else None
        out.append((max(0.0, s), e, name or ch.title or f"Chapter {i + 1}"))
    return out


#: A generated last chapter shorter than this share of the interval is merged into the one
#: before it, so that no tiny chapter ends the film.
GENERATED_TAIL = 0.25


def _generated(
    every_minutes: float, duration: float, names: list[str] | None
) -> list[tuple[float, float, str]]:
    step = every_minutes * 60
    starts = [k * step for k in range(int(duration // step) + 1) if k * step < duration]
    if len(starts) > 1 and duration - starts[-1] < GENERATED_TAIL * step:
        starts.pop()
    out: list[tuple[float, float, str]] = []
    for k, start in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else duration
        name = names[k] if names is not None and k < len(names) and names[k] else None
        out.append((start, end, name or f"Chapter {k + 1}"))
    return out


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
    settings = job.chapters
    if not settings.enabled or not container.chapters:
        return ChapterPlan(map_from=None)
    if source.chapters:
        names = settings.names
        if names is None and not _empty_when_copied(source.chapters, start, duration):
            return ChapterPlan(map_from=0)
        chapters = _renamed(source.chapters, names, start, duration)
    elif settings.generate_every is not None and expected_duration > 0:
        chapters = _generated(settings.generate_every, expected_duration, settings.names)
    else:
        return ChapterPlan(map_from=None)
    if not chapters:
        return ChapterPlan(map_from=None)
    file = PlanFile(path=file_path, content=ffmetadata(chapters), description="FFMETADATA chapters")
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


# --------------------------------------------------------------------------- tags


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


def tag_args(tags: TagSettings, *, passthru: bool, render_value: Callable[[str], str]) -> list[str]:
    """``-map_metadata 0`` (or ``:g -1``) and one ``-metadata key=value`` per set tag."""
    args = ["-map_metadata", "0"] if passthru else ["-map_metadata:g", "-1"]
    for field_name, key in TAG_KEYS.items():
        value = getattr(tags, field_name)
        if value is None:
            continue
        args += ["-metadata", f"{key}={render_value(value)}"]
    return args
