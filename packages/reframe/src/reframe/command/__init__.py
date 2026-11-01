"""The command builder: one validated job becomes the exact FFmpeg commands (an ``EncodePlan``).

The builder is pure: no I/O, no clock, no subprocess, no environment reads.
"""

from reframe.command.audio import PlannedAudio, planned_audio
from reframe.command.builder import build_plan, output_chapters, partial_path
from reframe.command.errors import PlanError
from reframe.command.filtergraph import escape_value, filter_path, quote_value, subtitles_filter
from reframe.command.jobtype import (
    in_place_blockers,
    is_matroska_source,
    job_type,
    job_type_info,
)
from reframe.command.quoting import Shell, command_line, quote_posix, quote_windows

__all__ = [
    "PlanError",
    "PlannedAudio",
    "Shell",
    "build_plan",
    "command_line",
    "escape_value",
    "filter_path",
    "in_place_blockers",
    "is_matroska_source",
    "job_type",
    "job_type_info",
    "output_chapters",
    "partial_path",
    "planned_audio",
    "quote_posix",
    "quote_value",
    "quote_windows",
    "subtitles_filter",
]
