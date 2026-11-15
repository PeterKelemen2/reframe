"""Tool rules. The FFmpeg fixes change Settings, not the job, and take effect when tool
discovery runs again.
"""

from __future__ import annotations

from collections.abc import Iterator

from reframe.models.issues import ValidationIssue
from reframe.models.tools import ToolStatus
from reframe.validation.common import error
from reframe.validation.context import JobContext
from reframe.validation.registry import job_rule

_CODES = {
    ToolStatus.MISSING: ("tool.missing", "was not found"),
    ToolStatus.TOO_OLD: ("tool.too_old", "is too old"),
    ToolStatus.BROKEN: ("tool.broken", "does not work"),
}


@job_rule("tools", "tool.missing", "tool.too_old", "tool.broken")
def ffmpeg(ctx: JobContext) -> Iterator[ValidationIssue]:
    tool = ctx.tools.ffmpeg
    if tool.status is ToolStatus.FOUND:
        return
    code, what = _CODES[tool.status]
    reason = f": {tool.reason}" if tool.reason else "."
    yield error(code, "", f"FFmpeg {what}{reason}", *tool.fixes)
