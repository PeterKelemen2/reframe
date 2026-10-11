"""Discovery against the real FFmpeg of this machine or CI job (C-1).

Unlike ``test_discovery.py`` this keeps the real environment: in CI the main jobs install the
pinned build into ``$REFRAME_DATA_DIR/tools/ffmpeg`` (origin ``bundled``), and the override
job sets ``REFRAME_FFMPEG`` / ``REFRAME_FFPROBE`` (origin ``env``).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from reframe.models import ToolOrigin, ToolStatus
from reframe.tools import discover_tools, run
from reframe_testing import media

pytestmark = [pytest.mark.needs_ffmpeg, pytest.mark.anyio]


async def test_real_ffmpeg_and_ffprobe_are_found() -> None:
    tools = await discover_tools()
    for info in (tools.ffmpeg, tools.ffprobe):
        assert info.status is ToolStatus.FOUND, info.reason
        assert info.path is not None
        assert info.release_series is not None
        major, minor = map(int, info.release_series.split("."))
        assert (major, minor) >= (7, 0)
        assert any(flag.startswith("--enable-") for flag in info.build_flags)
        assert "libavcodec" in info.library_versions
    # The test helpers use exactly the binaries that discovery picks.
    assert tools.ffmpeg.path == Path(str(media.find_ffmpeg()))
    assert tools.ffprobe.path == Path(str(media.find_ffprobe()))
    if os.environ.get("REFRAME_FFMPEG"):
        assert tools.ffmpeg.origin is ToolOrigin.ENV
    # It runs, with the environment discovery asks for.
    argv = [str(tools.ffprobe.path), "-hide_banner", "-version"]
    result = await run(argv, timeout=60, extra_env=tools.ffprobe.env)
    assert result.ok
    assert result.stdout.startswith(b"ffprobe version ")
