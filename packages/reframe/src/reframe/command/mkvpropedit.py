"""The ``mkvpropedit`` arguments of a plan. Pure.

:func:`in_place_edits` writes only the track headers and the title that differ from the probed
source. :func:`fixup_edits` writes what FFmpeg's Matroska muxer does not write, on the ``.part``
file.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from reframe import languages
from reframe.command.metadata import needs_ietf
from reframe.definitions import ContainerDef, Definitions
from reframe.definitions.models import TRACK_FLAGS, TrackFlag
from reframe.models import Disposition, JobSettings, MediaSource, TrackMetadata

__all__ = [
    "FixupTrack",
    "InfoEdit",
    "StreamType",
    "TrackEdit",
    "edit_args",
    "fixup_edits",
    "flag_value",
    "in_place_edits",
    "language_pair",
    "track_selector",
]

StreamType = Literal["v", "a", "s"]


def track_selector(kind: StreamType, number: int) -> str:
    """``track:a2``: the ``number``-th (1-based) track of that type in file order."""
    return f"track:{kind}{number}"


def language_pair(value: str | None) -> tuple[str, str]:
    """``(ISO 639-2/B, BCP 47)`` written for ``value``: ``pt-BR`` → ``("por", "pt-BR")``,
    ``None`` → ``("und", "und")``."""
    return languages.to_matroska_legacy(value), languages.to_matroska_ietf(value)


def flag_value(disposition: Disposition, flag: TrackFlag, definitions: Definitions) -> bool:
    """A flag of the probed track (its FFmpeg disposition)."""
    return bool(getattr(disposition, definitions.track_flags[flag].disposition))


@dataclass(frozen=True, slots=True)
class TrackEdit:
    """The changes of one track header (``--edit track:…``)."""

    selector: str
    language: tuple[str, str] | None = None
    """``(ISO 639-2/B, BCP 47)`` to write, or ``None`` to keep."""
    name: str | None = None
    """A new track name."""
    delete_name: bool = False
    """Remove the track name (the job writes none)."""
    flags: tuple[tuple[str, bool], ...] = field(default_factory=tuple)
    """``(mkvpropedit property, value)`` in the order of ``TRACK_FLAGS``."""

    @property
    def empty(self) -> bool:
        return (
            self.language is None
            and self.name is None
            and not self.delete_name
            and not (self.flags)
        )

    def args(self) -> list[str]:
        out = ["--edit", self.selector]
        if self.language is not None:
            legacy, ietf = self.language
            # Both, in this order: a later ``--set language`` overwrites ``language-ietf``.
            out += ["--set", f"language={legacy}", "--set", f"language-ietf={ietf}"]
        if self.delete_name:
            out += ["--delete", "name"]
        elif self.name is not None:
            out += ["--set", f"name={self.name}"]
        for prop, value in self.flags:
            out += ["--set", f"{prop}={int(value)}"]
        return out


@dataclass(frozen=True, slots=True)
class InfoEdit:
    """The segment title (``--edit info``)."""

    title: str | None
    """The new title; ``None`` removes it."""

    def args(self) -> list[str]:
        if self.title is None:
            return ["--edit", "info", "--delete", "title"]
        return ["--edit", "info", "--set", f"title={self.title}"]


def edit_args(edits: Sequence[TrackEdit | InfoEdit]) -> list[str]:
    """The arguments of every non-empty edit, in order (after the file name)."""
    out: list[str] = []
    for edit in edits:
        if isinstance(edit, TrackEdit) and edit.empty:
            continue
        out += edit.args()
    return out


def _track_edit(
    selector: str,
    metadata: TrackMetadata,
    *,
    language: str | None,
    ietf: str | None,
    title: str | None,
    disposition: Disposition,
    definitions: Definitions,
) -> TrackEdit:
    """What differs between ``metadata`` (the job's) and the probed track."""
    pair: tuple[str, str] | None = None
    if metadata.language is not None:
        wanted = language_pair(metadata.language)
        have = (
            languages.to_matroska_legacy(language),
            languages.to_matroska_ietf(ietf or language),
        )
        if wanted != have:
            pair = wanted
    name: str | None = None
    delete = False
    if metadata.name is not None:
        if not metadata.name:
            delete = title is not None
        elif metadata.name != title:
            name = metadata.name
    flags: list[tuple[str, bool]] = []
    for flag in TRACK_FLAGS:
        wanted_flag = bool(getattr(metadata, flag))
        if wanted_flag != flag_value(disposition, flag, definitions):
            flags.append((definitions.track_flags[flag].mkvpropedit, wanted_flag))
    return TrackEdit(selector, pair, name, delete, tuple(flags))


def in_place_edits(
    job: JobSettings,
    source: MediaSource,
    definitions: Definitions,
    *,
    render_title: Callable[[str], str] | None = None,
) -> list[TrackEdit | InfoEdit]:
    """The edits of a ``metadata_edit`` job: every track of the job against the probed track
    it keeps (the job type guarantees the same tracks in the same order), and the segment
    title when the job sets one (``tags.title``, rendered with ``render_title``). Only what
    differs is written; an empty list means the file already has every value."""
    edits: list[TrackEdit | InfoEdit] = []
    if source.video:
        video = source.video[0]
        edits.append(
            _track_edit(
                track_selector("v", 1), job.video.metadata, language=video.language,
                ietf=video.language_ietf, title=video.title, disposition=video.disposition,
                definitions=definitions,
            )
        )  # fmt: skip
    for number, (track, stream) in enumerate(zip(job.audio, source.audio, strict=False), 1):
        edits.append(
            _track_edit(
                track_selector("a", number), track.metadata, language=stream.language,
                ietf=stream.language_ietf, title=stream.title, disposition=stream.disposition,
                definitions=definitions,
            )
        )  # fmt: skip
    for number, (sub, sub_stream) in enumerate(
        zip(job.subtitles, source.subtitles, strict=False), 1
    ):
        edits.append(
            _track_edit(
                track_selector("s", number), sub.metadata, language=sub_stream.language,
                ietf=sub_stream.language_ietf, title=sub_stream.title,
                disposition=sub_stream.disposition, definitions=definitions,
            )
        )  # fmt: skip
    edits = [e for e in edits if not (isinstance(e, TrackEdit) and e.empty)]
    if job.tags.title is not None:
        text = render_title(job.tags.title) if render_title is not None else job.tags.title
        title = text.strip() or None
        if title != (source.container.title or None):
            edits.append(InfoEdit(title))
    return edits


@dataclass(frozen=True, slots=True)
class FixupTrack:
    """One output track as the post-mux fix-up sees it."""

    type: StreamType
    number: int
    """1-based among the output tracks of its type."""
    language: str | None
    """The effective language written (BCP 47 or ISO 639)."""
    metadata: TrackMetadata


def fixup_edits(
    tracks: Sequence[FixupTrack], container: ContainerDef, definitions: Definitions
) -> list[TrackEdit]:
    """What FFmpeg's muxer did not write into the output: ``LanguageIETF`` for a language that
    ISO 639-2 cannot say (``pt-BR``, ``yue``), and the set flags of
    ``container.mkvpropedit_flags``."""
    edits: list[TrackEdit] = []
    for track in tracks:
        pair = language_pair(track.language) if needs_ietf(track.language) else None
        flags = tuple(
            (definitions.track_flags[flag].mkvpropedit, True)
            for flag in container.mkvpropedit_flags
            if getattr(track.metadata, flag)
        )
        edit = TrackEdit(track_selector(track.type, track.number), pair, flags=flags)
        if not edit.empty:
            edits.append(edit)
    return edits
