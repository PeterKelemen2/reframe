"""Tool rules (05 §C-8 "Tools"): ffmpeg missing, too old or broken; mkvpropedit needed but
missing.

The ffmpeg issues carry C-1's fixes ("Use bundled FFmpeg": a patch on ``AppSettings``, target
``settings``). Tool discovery reads Settings, so such a fix works when discovery runs again;
it is not a change of the job. mkvpropedit is needed to edit an MKV in place (03 §Remux-only
jobs) and to write flags the muxer cannot (``container.mkvpropedit_flags``; the flag case is a
warning of the container rule ``track_flags``). The in-place case's fix writes a new file: edit
in place off and, when the output path is the source, a new path
(:func:`reframe.validation.inplace.write_new_file_fix`).
"""

from __future__ import annotations

from collections.abc import Iterator

from reframe.models.issues import ValidationIssue
from reframe.models.tools import ToolStatus
from reframe.validation.common import error
from reframe.validation.context import JobContext
from reframe.validation.inplace import write_new_file_fix
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
        write_new_file_fix(ctx),
        *tool.fixes,
    )
