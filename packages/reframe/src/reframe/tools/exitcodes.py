"""What a process's exit code says about how it ended."""

from __future__ import annotations

__all__ = ["crashed"]


def crashed(returncode: int | None) -> bool:
    """The process ended by a POSIX signal (a negative code) or by a Windows system exception
    (NTSTATUS ``0xC000xxxx``, e.g. ``0xC0000005``, an access violation).

    A program's own negative exit code on Windows is not a crash: FFmpeg exits with its error
    code, so ``-22`` arrives as ``0xFFFFFFEA``, and some of its codes are above ``0xC0000000``
    (``AVERROR_EOF`` is ``0xDFB9B0BB``), but none has the form ``0xC000xxxx``."""
    if returncode is None:
        return False
    return returncode < 0 or returncode & 0xFFFF0000 == 0xC0000000
