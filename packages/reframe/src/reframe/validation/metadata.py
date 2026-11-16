"""Track metadata rules: a language that is not a known language or BCP 47 tag would be
written as ``und``, and several output tracks of one kind marked default."""

from __future__ import annotations

from collections.abc import Iterator

from reframe import languages
from reframe.command.metadata import dispositions
from reframe.definitions import ContainerDef
from reframe.models.issues import ValidationIssue
from reframe.models.job import TrackMetadata
from reframe.validation.common import error, fix, replace, warning
from reframe.validation.context import JobContext
from reframe.validation.registry import job_rule


def metadata_blocks(
    ctx: JobContext, *, written_only: bool = False
) -> Iterator[tuple[str, TrackMetadata]]:
    """The metadata of each output track and its path; ``written_only`` skips burned-in
    subtitles, which have no track to write it to."""
    yield "video.metadata", ctx.job.video.metadata
    for index, audio in enumerate(ctx.job.audio):
        yield f"audio[{index}].metadata", audio.metadata
    for index, subtitle in enumerate(ctx.job.subtitles):
        if not (written_only and subtitle.action == "burn"):
            yield f"subtitles[{index}].metadata", subtitle.metadata


@job_rule("metadata", "metadata.language_invalid")
def track_languages(ctx: JobContext) -> Iterator[ValidationIssue]:
    for prefix, metadata in metadata_blocks(ctx):
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
            ),
        )


@job_rule("metadata", "metadata.nul_character")
def track_names(ctx: JobContext) -> Iterator[ValidationIssue]:
    """A track name is a process argument, which cannot hold a NUL character."""
    names = [(f"{prefix}.name", metadata.name) for prefix, metadata in metadata_blocks(ctx)]
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
                ),
            )


def _written_default(ctx: JobContext, container: ContainerDef, metadata: TrackMetadata) -> bool:
    """The default flag as the plan writes it: an FFmpeg disposition."""
    if not metadata.default:
        return False
    disposition = ctx.definitions.track_flags["default"].disposition
    return disposition in dispositions(metadata, container, ctx.definitions).split("+")


@job_rule("metadata", "metadata.several_defaults")
def default_tracks(ctx: JobContext) -> Iterator[ValidationIssue]:
    """More than one output track of a kind marked default is allowed, so a warning, with a fix
    that keeps only the first one default. A burned-in subtitle is not an output track."""
    container = ctx.container
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
            ),
        )
