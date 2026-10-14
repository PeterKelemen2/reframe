"""Source rules: what the source must have for a job. The command builder encodes or copies
the source's first video stream, so a source without video cannot be planned (decision 0013:
``build_plan`` refuses it)."""

from __future__ import annotations

from pathlib import PurePath

from reframe.models.issues import ValidationIssue
from reframe.validation.common import error
from reframe.validation.context import JobContext
from reframe.validation.registry import job_rule


@job_rule("source", "source.no_video")
def video_stream(ctx: JobContext) -> list[ValidationIssue]:
    if ctx.video_stream is not None:
        return []
    return [
        error(
            "source.no_video",
            "source",
            f"{PurePath(ctx.job.source.path).name} has no video track: Reframe encodes video "
            "files.",
        )
    ]
