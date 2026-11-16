"""The Matroska header edits of a plan, as :class:`~reframe.models.HeaderEdit`. Pure.

:func:`in_place_edit` writes only the track headers and the title that differ from the probed
source. :func:`fixup_edit` writes the ``LanguageIETF`` that FFmpeg's Matroska muxer never
writes, on the ``.part`` file.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from reframe import languages
from reframe.command.metadata import OutputTrack, needs_ietf
from reframe.command.quoting import Shell, quoter
from reframe.definitions import Definitions
from reframe.definitions.models import TRACK_FLAGS, TrackFlag
from reframe.models import (
    Disposition,
    HeaderEdit,
    HeaderTrackType,
    InfoHeaderEdit,
    JobSettings,
    MediaSource,
    TrackHeaderEdit,
    TrackMetadata,
)

__all__ = [
    "edit_line",
    "fixup_edit",
    "flag_value",
    "in_place_edit",
    "is_empty",
    "language_pair",
]

_TRACK_TYPES: dict[str, HeaderTrackType] = {"v": "video", "a": "audio", "s": "subtitle"}


def language_pair(value: str | None) -> tuple[str, str]:
    """``(ISO 639-2/B, BCP 47)`` written for ``value``: ``pt-BR`` → ``("por", "pt-BR")``,
    ``None`` → ``("und", "und")``."""
    return languages.to_matroska_legacy(value), languages.to_matroska_ietf(value)


def flag_value(disposition: Disposition, flag: TrackFlag, definitions: Definitions) -> bool:
    """A flag of the probed track (its FFmpeg disposition)."""
    return bool(getattr(disposition, definitions.track_flags[flag].disposition))


def is_empty(edit: HeaderEdit) -> bool:
    """The edit changes nothing."""
    return not edit.tracks and edit.info is None


def _track_edit(
    track_type: HeaderTrackType,
    number: int,
    metadata: TrackMetadata,
    *,
    language: str | None,
    ietf: str | None,
    title: str | None,
    disposition: Disposition,
    definitions: Definitions,
) -> TrackHeaderEdit | None:
    """What differs between ``metadata`` (the job's) and the probed track; ``None``: nothing."""
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
    flags = {
        flag: bool(getattr(metadata, flag))
        for flag in TRACK_FLAGS
        if bool(getattr(metadata, flag)) != flag_value(disposition, flag, definitions)
    }
    if pair is None and name is None and not delete and not flags:
        return None
    return TrackHeaderEdit(
        track_type=track_type,
        number=number,
        language=pair[0] if pair else None,
        language_ietf=pair[1] if pair else None,
        name=name,
        delete_name=delete,
        flags=flags,
    )


def in_place_edit(
    path: Path,
    job: JobSettings,
    source: MediaSource,
    definitions: Definitions,
    *,
    render_title: Callable[[str], str] | None = None,
) -> HeaderEdit:
    """The edit of a ``metadata_edit`` job on ``path``: every track of the job against the
    probed track it keeps (the job type guarantees the same tracks in the same order), and the
    segment title when the job sets one (``tags.title``, rendered with ``render_title``). Only
    what differs is written; :func:`is_empty` when the file already has every value."""
    edits: list[TrackHeaderEdit | None] = []
    if source.video:
        video = source.video[0]
        edits.append(
            _track_edit(
                "video", 1, job.video.metadata, language=video.language,
                ietf=video.language_ietf, title=video.title, disposition=video.disposition,
                definitions=definitions,
            )
        )  # fmt: skip
    for number, (track, stream) in enumerate(zip(job.audio, source.audio, strict=False), 1):
        edits.append(
            _track_edit(
                "audio", number, track.metadata, language=stream.language,
                ietf=stream.language_ietf, title=stream.title, disposition=stream.disposition,
                definitions=definitions,
            )
        )  # fmt: skip
    for number, (sub, sub_stream) in enumerate(
        zip(job.subtitles, source.subtitles, strict=False), 1
    ):
        edits.append(
            _track_edit(
                "subtitle", number, sub.metadata, language=sub_stream.language,
                ietf=sub_stream.language_ietf, title=sub_stream.title,
                disposition=sub_stream.disposition, definitions=definitions,
            )
        )  # fmt: skip
    info: InfoHeaderEdit | None = None
    if job.tags.title is not None:
        text = render_title(job.tags.title) if render_title is not None else job.tags.title
        title = text.strip() or None
        if title != (source.container.title or None):
            info = InfoHeaderEdit(title=title)
    return HeaderEdit(path=path, tracks=[e for e in edits if e is not None], info=info)


def fixup_edit(path: Path, tracks: Sequence[OutputTrack]) -> HeaderEdit:
    """What FFmpeg's Matroska muxer did not write into ``path``: ``LanguageIETF`` (with
    ``Language``) for a language that ISO 639-2 cannot say (``pt-BR``, ``yue``). FFmpeg
    writes all six track flags, so none are here."""
    edits: list[TrackHeaderEdit] = []
    for track in tracks:
        if not needs_ietf(track.language):
            continue
        legacy, ietf = language_pair(track.language)
        edits.append(
            TrackHeaderEdit(
                track_type=_TRACK_TYPES[track.type],
                number=track.index + 1,
                language=legacy,
                language_ietf=ietf,
            )
        )
    return HeaderEdit(path=path, tracks=edits)


def edit_line(edit: HeaderEdit, shell: Shell) -> str:
    """The command preview's line of a ``header_edit`` step: the file, then per track its
    type and number and each ``field=value``, then the title. Values are shell-quoted, so the
    line splits into words as a command line does; it is not a command to run.

    ``header_edit /m/Movie.mkv audio 2: language=por language_ietf=pt-BR default=1 title='A B'``
    """
    quote = quoter(shell)
    words = ["header_edit", quote(str(edit.path))]
    for track in edit.tracks:
        words.append(f"{track.track_type} {track.number}:")
        if track.language is not None and track.language_ietf is not None:
            words.append("language=" + quote(track.language))
            words.append("language_ietf=" + quote(track.language_ietf))
        if track.delete_name:
            words.append("delete_name")
        elif track.name is not None:
            words.append("name=" + quote(track.name))
        words += [f"{flag}={int(value)}" for flag, value in track.flags.items()]
    if edit.info is not None:
        if edit.info.title is None:
            words.append("delete_title")
        else:
            words.append("title=" + quote(edit.info.title))
    return " ".join(words)
