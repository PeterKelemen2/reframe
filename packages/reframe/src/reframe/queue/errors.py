"""Errors of the queue, and the short reason of a failed step (``QueueJob.error``).

The reason is read from the end of the tool's stderr. Generic follow-up lines and FFmpeg's
``[module @ 0x…]`` prefixes are left out of it.
"""

from __future__ import annotations

import re
import signal
from collections.abc import Sequence

__all__ = [
    "JobStateError",
    "QueueError",
    "UnknownJobError",
    "closed_error",
    "exit_text",
    "printable",
    "stderr_reason",
]


class QueueError(Exception):
    """A queue call that cannot be done (a programming error or a race between two clients)."""


class UnknownJobError(QueueError, KeyError):
    """No job with this id is in the queue."""

    def __init__(self, job_id: str) -> None:
        super().__init__(job_id)
        self.job_id = job_id

    def __str__(self) -> str:
        return f"no job {self.job_id!r} in the queue"


class JobStateError(QueueError):
    """The job is in a state that does not allow the call (``remove`` of a running job)."""


def closed_error() -> type[Exception]:
    """``reframe.service.ReframeClosedError``: what a queue call after ``close()`` raises."""
    from reframe.service import ReframeClosedError  # reframe.service imports this package

    return ReframeClosedError


#: Causes that say more than any other line; the first one found wins.
_KNOWN_CAUSES = (
    ("No space left on device", "No space left on device: the disk is full."),
    ("Disk quota exceeded", "Disk quota exceeded."),
    ("Permission denied", "Permission denied."),
    ("Read-only file system", "The output folder is on a read-only file system."),
    ("Cannot allocate memory", "Not enough memory."),
)
_ERROR_WORDS = re.compile(
    r"error|failed|invalid|cannot|can't|could not|unable|not supported|unsupported|"
    r"no such|denied|not found|unknown|nan/|out of range|incorrect|corrupt",
    re.IGNORECASE,
)
#: Lines that only say "it failed" after the real error, or are noise.
_GENERIC = re.compile(
    r"^(conversion failed!?|exiting with exit code|exiting normally|"
    r"terminating thread with return code|task finished with error code|"
    r"error while filtering: |nothing was written into output file|"
    r"error closing file: invalid argument|press \[q\])",
    re.IGNORECASE,
)
_PREFIX = re.compile(r"^(\[[^\]]+ @ 0x[0-9a-fA-F]+\]\s*)+")
#: How many lines from the end are searched.
TAIL = 40
MAX_LENGTH = 300


def _clean(line: str) -> str:
    text = _PREFIX.sub("", line.strip())
    # FFmpeg can nest two prefixes on one line.
    return _PREFIX.sub("", text).strip()


def stderr_reason(lines: Sequence[str], *, last_line: bool = True) -> str | None:
    """A short reason from the last stderr lines, or ``None`` when nothing useful is there.

    ``last_line``: without a line that reads like an error, use the last plain line (not for
    a crash, whose last line is whatever the tool printed before it died)."""
    tail = [line for line in lines[-TAIL:] if line.strip()]
    for needle, text in _KNOWN_CAUSES:
        if any(needle in line for line in tail):
            return text
    candidates: list[str] = []
    for line in tail:
        text = _clean(line)
        if not text or line.startswith((" ", "\t")) or _GENERIC.match(text):
            continue
        if _ERROR_WORDS.search(text) and text not in candidates:
            candidates.append(text)
    if candidates:
        return _shorten("; ".join(candidates[:2]))
    if not last_line:
        return None
    for line in reversed(tail):
        text = _clean(line)
        if text and not _GENERIC.match(text) and not line.startswith((" ", "\t")):
            return _shorten(text)
    return None


def printable(text: str) -> str:
    """``text`` as valid UTF-8: a lone surrogate (from a file name that is not UTF-8) is
    written as an escape, so a JSON encoder or a UTF-8 log never fails on it."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return text.encode("utf-8", "backslashreplace").decode("utf-8")
    return text


def _shorten(text: str) -> str:
    return text if len(text) <= MAX_LENGTH else text[: MAX_LENGTH - 1].rstrip() + "…"


def exit_text(returncode: int | None) -> str:
    """Text for a return code: a negative code is a POSIX signal, a large one a Windows
    status in hexadecimal."""
    if returncode is None:
        return "no exit code"
    if returncode < 0:
        number = -returncode
        try:
            name = signal.Signals(number).name
        except ValueError:
            return f"signal {number}"
        return f"signal {number} ({name})"
    if returncode > 0xFFFF:
        return f"exit code {returncode:#X}".replace("0X", "0x")
    return f"exit code {returncode}"
