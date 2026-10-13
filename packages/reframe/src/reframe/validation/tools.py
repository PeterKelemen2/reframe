"""Tool rules (05 §C-8 "Tools"): ffmpeg missing, too old or broken; mkvpropedit needed but
missing.

The ffmpeg issues carry C-1's fixes ("Use bundled FFmpeg": a patch on ``AppSettings``, target
``settings``). Tool discovery reads Settings, so such a fix works when discovery runs again;
it is not a change of the job. mkvpropedit is needed to edit an MKV in place (03 §Remux-only
jobs) and to write flags the muxer cannot (``container.mkvpropedit_flags``; the flag case is a
warning of the container rule ``track_flags``).
"""

from __future__ import annotations

from collections.abc import Iterator

from reframe.models.issues import ValidationIssue
from reframe.models.tools import ToolStatus
from reframe.validation.common import error, fix, replace
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


@job_rule("tools", "tool.mkvpropedit_missing")
def mkvpropedit(ctx: JobContext) -> Iterator[ValidationIssue]:
    output = ctx.job.output
    tool = ctx.tools.mkvpropedit
    if not output.edit_in_place or output.container != "mkv" or tool.status is ToolStatus.FOUND:
        return
    reason = f" ({tool.reason})" if tool.reason else ""
    yield error(
        "tool.mkvpropedit_missing",
        "output.edit_in_place",
        f"Editing in place needs mkvpropedit, which is not available{reason}.",
        fix("Write a new file", replace("output.edit_in_place", False), target=ctx.target),
        *tool.fixes,
    )
