"""Running and finding external tools.

Every subprocess in Reframe goes through :func:`run` or :func:`run_streaming` (timeout,
cancel, output limit, process-tree kill).
"""

from reframe.tools.discovery import (
    ENV_VARS,
    TOOL_NAMES,
    ToolLocation,
    check_tool,
    discover_tools,
    discover_tools_sync,
    locate_tools,
)
from reframe.tools.exitcodes import crashed
from reframe.tools.runner import (
    CancelToken,
    LineCallback,
    RunResult,
    kill_leftovers,
    kill_process_tree,
    run,
    run_streaming,
)
from reframe.tools.versions import (
    MIN_FFMPEG,
    FfmpegVersion,
    parse_ffmpeg_version,
    parse_mediainfo_version,
    parse_mkvpropedit_version,
)

__all__ = [
    "ENV_VARS",
    "MIN_FFMPEG",
    "TOOL_NAMES",
    "CancelToken",
    "FfmpegVersion",
    "LineCallback",
    "RunResult",
    "ToolLocation",
    "check_tool",
    "crashed",
    "discover_tools",
    "discover_tools_sync",
    "kill_leftovers",
    "kill_process_tree",
    "locate_tools",
    "parse_ffmpeg_version",
    "parse_mediainfo_version",
    "parse_mkvpropedit_version",
    "run",
    "run_streaming",
]
