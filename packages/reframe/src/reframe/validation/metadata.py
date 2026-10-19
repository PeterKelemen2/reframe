"""Track metadata rules: a language that is not a known language or BCP 47 tag would be
written as ``und``."""

from __future__ import annotations

from collections.abc import Iterator

from reframe import languages
from reframe.command.metadata import needs_ietf
from reframe.models.issues import ValidationIssue
from reframe.models.job import TrackMetadata
from reframe.models.tools import ToolStatus
from reframe.validation.common import fix, replace, warning
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
            f"and mkvpropedit was not found: only {legacy!r} is written.",
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
