"""Chapter rules: an interval of generated chapters that would make too many."""

from __future__ import annotations

import math
from collections.abc import Iterator

from reframe.command.metadata import MAX_GENERATED_CHAPTERS, generated_starts
from reframe.models.issues import ValidationIssue
from reframe.validation.common import error, fix, replace
from reframe.validation.context import JobContext
from reframe.validation.range import range_duration
from reframe.validation.registry import job_rule


def _shortest_interval(seconds: float) -> float:
    """The shortest interval in minutes, to two decimals as the Chapters tab shows it, that
    stays within :data:`MAX_GENERATED_CHAPTERS`."""
    every = math.ceil(seconds / 60 / MAX_GENERATED_CHAPTERS * 100) / 100
    while generated_starts(every, seconds) is None:
        every = round(every + 0.01, 2)
    return every


@job_rule("metadata", "chapters.too_many")
def generated_chapters(ctx: JobContext) -> Iterator[ValidationIssue]:
    settings = ctx.job.chapters
    every = settings.generate_every
    container = ctx.container
    if (
        every is None
        or not settings.enabled
        or ctx.source.chapters
        or container is None
        or not container.chapters
    ):
        return
    seconds = range_duration(ctx)
    if not seconds or generated_starts(every, seconds) is not None:
        return
    shortest = _shortest_interval(seconds)
    yield error(
        "chapters.too_many",
        "chapters.generate_every",
        f"A chapter every {every:g} minutes would make more than {MAX_GENERATED_CHAPTERS} "
        "chapters, so none would be generated.",
        fix(
            f"Generate a chapter every {shortest:g} minutes",
            replace("chapters.generate_every", shortest),
        ),
    )
