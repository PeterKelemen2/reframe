"""Source rules. The command builder encodes or copies the source's first video stream, so a
source without video is an error."""

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
