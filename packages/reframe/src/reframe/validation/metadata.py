"""Track metadata rules (03 §Track metadata & languages): a language that is not a known
language or BCP 47 tag would be written as ``und``."""

from __future__ import annotations

from collections.abc import Iterator

from reframe import languages
from reframe.models.issues import ValidationIssue
from reframe.models.job import TrackMetadata
from reframe.validation.common import fix, replace, warning
from reframe.validation.context import JobContext
from reframe.validation.registry import job_rule


def _blocks(ctx: JobContext) -> Iterator[tuple[str, TrackMetadata]]:
    yield "video.metadata", ctx.job.video.metadata
    for index, audio in enumerate(ctx.job.audio):
        yield f"audio[{index}].metadata", audio.metadata
    for index, subtitle in enumerate(ctx.job.subtitles):
        yield f"subtitles[{index}].metadata", subtitle.metadata


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
