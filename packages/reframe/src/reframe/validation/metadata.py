"""Track metadata rules: a language that is not a known language or BCP 47 tag would be
written as ``und``, and several output tracks of one kind marked default."""

from __future__ import annotations

from collections.abc import Iterator

from reframe import languages
from reframe.command.metadata import dispositions, needs_ietf
from reframe.definitions import ContainerDef
from reframe.models.issues import ValidationIssue
from reframe.models.job import TrackMetadata
from reframe.models.tools import ToolStatus
from reframe.validation.common import error, fix, replace, tool_problem, warning
from reframe.validation.context import JobContext
from reframe.validation.registry import job_rule


def _blocks(ctx: JobContext) -> Iterator[tuple[str, TrackMetadata]]:
    yield "video.metadata", ctx.job.video.metadata
    for index, audio in enumerate(ctx.job.audio):
        yield f"audio[{index}].metadata", audio.metadata
    for index, subtitle in enumerate(ctx.job.subtitles):
        yield f"subtitles[{index}].metadata", subtitle.metadata


def _written_languages(ctx: JobContext) -> Iterator[tuple[str, str | None]]:
    stream = ctx.video_stream
    source = (stream.language_ietf or stream.language) if stream is not None else None
    yield "video.metadata", ctx.job.video.metadata.language or source
    for index, audio in enumerate(ctx.job.audio):
        found = (
            ctx.audio_streams.get(audio.source_stream) if audio.source_stream is not None else None
        )
        source = (found.language_ietf or found.language) if found is not None else None
        yield f"audio[{index}].metadata", audio.metadata.language or source
    for index, subtitle in enumerate(ctx.job.subtitles):
        if subtitle.action == "burn":
            # A burned-in subtitle has no track to write a language into.
            continue
        if isinstance(subtitle.source, int):
            sub = ctx.subtitle_streams.get(subtitle.source)
            source = (sub.language_ietf or sub.language) if sub is not None else None
        else:
            source = subtitle.source.language
        yield f"subtitles[{index}].metadata", subtitle.metadata.language or source


@job_rule("metadata", "metadata.language_tag_lost")
def language_tags(ctx: JobContext) -> Iterator[ValidationIssue]:
    """A BCP 47 tag that ISO 639-2 cannot say (``pt-BR``, ``yue``) needs mkvpropedit to write
    Matroska's ``LanguageIETF``. Without it only the ISO 639-2 code is written: a warning,
    with a fix that writes the code on purpose."""
    container = ctx.container
    if (
        container is None
        or container.id != "mkv"
        or container.language_format != "iso639_2b"
        or ctx.tools.mkvpropedit.status is ToolStatus.FOUND
    ):
        return
    for prefix, language in _written_languages(ctx):
        if language is None or languages.validate(language) is not None:
            continue
        if not needs_ietf(language):
            continue
        legacy = languages.to_matroska_legacy(language)
        yield warning(
            "metadata.language_tag_lost",
            f"{prefix}.language",
            f"The language {language} needs mkvpropedit after muxing (Matroska LanguageIETF), "
            f"which is not available: only {legacy!r} is written."
            f"{tool_problem(ctx.tools.mkvpropedit)}",
            fix(f"Write it as {legacy}", replace(f"{prefix}.language", legacy), target=ctx.target),
        )


@job_rule("metadata", "metadata.language_invalid")
def track_languages(ctx: JobContext) -> Iterator[ValidationIssue]:
    for prefix, metadata in _blocks(ctx):
        if metadata.language is None:
            continue
        problem = languages.validate(metadata.language)
        if problem is None:
            continue
        yield warning(
            "metadata.language_invalid",
            f"{prefix}.language",
            f"{problem} It would be written as 'und' (undetermined).",
            fix(
                "Keep the source language",
                replace(f"{prefix}.language", None),
                target=ctx.target,
            ),
        )


@job_rule("metadata", "metadata.nul_character")
def track_names(ctx: JobContext) -> Iterator[ValidationIssue]:
    """A track name is a process argument, which cannot hold a NUL character."""
    names = [(f"{prefix}.name", metadata.name) for prefix, metadata in _blocks(ctx)]
    names += [
        (f"subtitles[{index}].source.name", track.source.name)
        for index, track in enumerate(ctx.job.subtitles)
        if not isinstance(track.source, int)
    ]
    for at, name in names:
        if name is not None and "\0" in name:
            yield error(
                "metadata.nul_character",
                at,
                "The track name has a NUL character, which FFmpeg cannot be given: the job "
                "would fail.",
                fix(
                    "Remove the NUL characters",
                    replace(at, name.replace("\0", "")),
                    target=ctx.target,
                ),
            )


def _written_default(ctx: JobContext, container: ContainerDef, metadata: TrackMetadata) -> bool:
    """The default flag as the plan writes it: an FFmpeg disposition, else the mkvpropedit
    step after muxing."""
    if not metadata.default:
        return False
    disposition = ctx.definitions.track_flags["default"].disposition
    if disposition in dispositions(metadata, container, ctx.definitions).split("+"):
        return True
    return (
        "default" in container.mkvpropedit_flags
        and ctx.tools.mkvpropedit.status is ToolStatus.FOUND
    )


@job_rule("metadata", "metadata.several_defaults")
def default_tracks(ctx: JobContext) -> Iterator[ValidationIssue]:
    """More than one output track of a kind marked default is allowed, so a warning, with a fix
    that keeps only the first one default. A burned-in subtitle is not an output track."""
    container = ctx.container
    if container is None:
        return
    audio = [
        index
        for index, track in enumerate(ctx.job.audio)
        if _written_default(ctx, container, track.metadata)
    ]
    subtitles = [
        index
        for index, sub in enumerate(ctx.job.subtitles)
        if sub.action != "burn" and _written_default(ctx, container, sub.metadata)
    ]
    for field, kind, marked in (("audio", "audio", audio), ("subtitles", "subtitle", subtitles)):
        if len(marked) < 2:
            continue
        first, *others = marked
        numbers = [str(index + 1) for index in marked]
        names = ", ".join(numbers[:-1]) + " and " + numbers[-1]
        yield warning(
            "metadata.several_defaults",
            f"{field}[{others[0]}].metadata.default",
            f"{kind.capitalize()} tracks {names} are {'both' if len(marked) == 2 else 'all'} "
            f"marked default; usually only one {kind} track is.",
            fix(
                f"Keep only {kind} track {first + 1} default",
                *(replace(f"{field}[{index}].metadata.default", False) for index in others),
                target=ctx.target,
            ),
        )
