"""On Windows, a file call that fails because another process holds the file open is retried.

A leaf module: ``settings`` and ``queue.files`` both use it, and ``queue`` imports ``settings``.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from functools import partial
from pathlib import Path

__all__ = ["ATTEMPTS", "DELAY", "WINDOWS", "replace_file", "retry"]

#: How often a call that fails with ``PermissionError`` is tried on Windows.
ATTEMPTS = 6
#: The first pause between two tries (seconds); it doubles each time.
DELAY = 0.05
#: ``True`` on Windows (tests set it).
WINDOWS = os.name == "nt"


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def retry[T](call: Callable[[], T]) -> T:
    """``call()``; on Windows a ``PermissionError`` is retried until the last attempt raises it."""
    delay = DELAY
    for attempt in range(ATTEMPTS):
        try:
            return call()
        except PermissionError:
            if not WINDOWS or attempt == ATTEMPTS - 1:
                raise
            _sleep(delay)
            delay *= 2
    raise AssertionError("unreachable")  # pragma: no cover


def replace_file(source: Path, target: Path) -> None:
    """``os.replace``, retried on Windows while the target is open in another process."""
    retry(partial(os.replace, source, target))
