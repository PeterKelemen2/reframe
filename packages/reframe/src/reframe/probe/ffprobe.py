"""Running ffprobe: the commands, the tool identity and typed failures.

Every run goes through :func:`reframe.tools.run`. A failure is a :class:`ProbeError` value with
a :class:`ProbeErrorKind`, never an exception.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from reframe.models.tools import ToolInfo
from reframe.tools import CancelToken, RunResult, run

__all__ = [
    "FRAME_TIMEOUT",
    "PROBE_TIMEOUT",
    "ProbeError",
    "ProbeErrorKind",
    "ProbeTool",
    "frames_argv",
    "packets_argv",
    "probe_argv",
    "run_json",
]

#: Seconds for the main probe. Network shares can be slow.
PROBE_TIMEOUT = 60.0
#: Seconds for the first-frame read (it decodes one frame).
FRAME_TIMEOUT = 30.0
#: Packets read for the HDR frame fallback. The first packet may decode to no frame, and
#: SEI-only HDR would then be missed.
FRAME_PACKETS = 5
#: Packets sampled for the VFR check of a Matroska stream without statistics tags.
VFR_SAMPLE_PACKETS = 120
#: ffprobe JSON of a file with many streams and chapters is small; this is a safety limit.
MAX_OUTPUT = 64 * 2**20


class ProbeErrorKind(StrEnum):
    NOT_FOUND = "not_found"
    """The file does not exist."""
    NOT_A_FILE = "not_a_file"
    """The path is a folder or another non-file."""
    UNREADABLE = "unreadable"
    """The file exists but cannot be read (permissions, I/O error)."""
    TOOL_FAILED = "tool_failed"
    """ffprobe could not be started (missing, not executable)."""
    TIMEOUT = "timeout"
    """ffprobe did not finish in time; its process tree was killed."""
    CANCELLED = "cancelled"
    """The probe was cancelled; the process tree was killed."""
    FAILED = "failed"
    """ffprobe exited with an error."""
    INVALID_OUTPUT = "invalid_output"
    """ffprobe printed something that is not the expected JSON."""


@dataclass(frozen=True, slots=True)
class ProbeError:
    """Why a file could not be probed (an expected failure, so a value)."""

    path: Path
    kind: ProbeErrorKind
    message: str
    detail: str | None = None
    """The useful part of ffprobe's stderr, if any."""

    def to_json(self) -> dict[str, str | None]:
        return {
            "path": str(self.path),
            "kind": self.kind.value,
            "message": self.message,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class ProbeTool:
    """The ffprobe to run, and how the probe cache tells builds apart."""

    path: str
    version: str | None = None
    """The version string, when known."""
    env: Mapping[str, str] = field(default_factory=dict)
    """Extra environment variables (:attr:`ToolInfo.env`)."""

    @classmethod
    def of(cls, tool: ToolInfo | ProbeTool | str | os.PathLike[str]) -> ProbeTool:
        if isinstance(tool, ProbeTool):
            return tool
        if isinstance(tool, ToolInfo):
            if tool.path is None:
                raise ValueError("ToolInfo for ffprobe has no path (it was not found)")
            return cls(str(tool.path), tool.version, dict(tool.env))
        return cls(os.fspath(tool))

    def identity(self) -> str:
        """``ffprobe <version>``, or the binary's path, size and mtime when the version is not
        known (so a replaced binary still invalidates the cache)."""
        if self.version:
            return f"ffprobe {self.version}"
        try:
            stat = os.stat(self.path)
        except OSError:
            return f"ffprobe at {self.path}"
        return f"ffprobe at {self.path} ({stat.st_size} bytes, mtime {stat.st_mtime_ns})"


def probe_argv(ffprobe: str, path: str) -> list[str]:
    """The probe command for ``path``."""
    return [
        ffprobe,
        "-v",
        "error",
        "-of",
        "json",
        "-show_format",
        "-show_streams",
        "-show_chapters",
        "-show_programs",
        "-i",
        path,
    ]


def frames_argv(ffprobe: str, path: str, stream_index: int) -> list[str]:
    """The first-frame command (HDR side data) for one stream (absolute index)."""
    return [
        ffprobe,
        "-v",
        "error",
        "-of",
        "json",
        "-show_frames",
        "-read_intervals",
        f"%+#{FRAME_PACKETS}",
        "-select_streams",
        str(stream_index),
        "-i",
        path,
    ]


def packets_argv(ffprobe: str, path: str, stream_index: int) -> list[str]:
    """Packet timestamps of the first :data:`VFR_SAMPLE_PACKETS` packets of one stream."""
    return [
        ffprobe,
        "-v",
        "error",
        "-of",
        "json",
        "-select_streams",
        str(stream_index),
        "-show_entries",
        "packet=pts_time",
        "-read_intervals",
        f"%+#{VFR_SAMPLE_PACKETS}",
        "-i",
        path,
    ]


def _stderr_detail(result: RunResult) -> str | None:
    lines = [line.strip() for line in result.stderr_text.splitlines() if line.strip()]
    return lines[-1] if lines else None


def _failure(path: Path, result: RunResult, timeout: float, what: str) -> ProbeError | None:
    if result.error is not None:
        return ProbeError(
            path, ProbeErrorKind.TOOL_FAILED, "ffprobe could not be started.", result.error
        )
    if result.timed_out:
        return ProbeError(
            path,
            ProbeErrorKind.TIMEOUT,
            f"ffprobe did not finish {what} within {timeout:g} s and was stopped.",
            _stderr_detail(result),
        )
    if result.cancelled:
        return ProbeError(path, ProbeErrorKind.CANCELLED, "The probe was cancelled.")
    if result.returncode != 0:
        detail = _stderr_detail(result)
        return ProbeError(
            path,
            ProbeErrorKind.FAILED,
            f"ffprobe could not read the file (exit code {result.returncode}).",
            detail,
        )
    return None


async def run_json(
    argv: list[str],
    path: Path,
    *,
    tool: ProbeTool,
    timeout: float,  # noqa: ASYNC109
    cancel: CancelToken | None,
    what: str = "",
) -> dict[str, Any] | ProbeError:
    """Run one ffprobe command and decode its JSON object."""
    result = await run(
        argv, timeout=timeout, cancel=cancel, max_output=MAX_OUTPUT, extra_env=tool.env or None
    )
    failure = _failure(path, result, timeout, what or "reading the file")
    if failure is not None:
        return failure
    if result.truncated:
        return ProbeError(
            path, ProbeErrorKind.INVALID_OUTPUT, "ffprobe printed more output than expected."
        )
    try:
        data = json.loads(result.stdout.decode("utf-8", errors="replace"))
    except ValueError as exc:
        return ProbeError(
            path,
            ProbeErrorKind.INVALID_OUTPUT,
            "ffprobe printed something that is not JSON.",
            f"{exc}; stderr: {_stderr_detail(result)}",
        )
    if not isinstance(data, dict):
        return ProbeError(
            path, ProbeErrorKind.INVALID_OUTPUT, "ffprobe printed JSON that is not an object."
        )
    return data
