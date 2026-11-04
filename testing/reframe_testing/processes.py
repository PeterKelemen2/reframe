"""The Python process behind a command that a test starts with ``sys.executable``."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import psutil

_WINDOWS = sys.platform == "win32"
#: On Windows a virtual environment's ``python.exe`` is a launcher: it runs the base
#: interpreter as its child and ends with the child's exit code.
LAUNCHER = _WINDOWS and sys.prefix != sys.base_prefix


def interpreter(pid: int, *, timeout: float = 10.0) -> psutil.Process:
    """The interpreter of the process ``pid`` that ``[sys.executable, ...]`` started: that
    process, or the launcher's interpreter child (waits up to ``timeout`` for it to start)."""
    process = psutil.Process(pid)
    if not LAUNCHER:
        return process
    name = Path(getattr(sys, "_base_executable", sys.executable)).name.lower()
    deadline = time.monotonic() + timeout
    while True:
        found = [child for child in process.children() if child.name().lower() == name]
        if found:
            return found[0]
        if time.monotonic() > deadline:
            raise AssertionError(f"process {pid} started no {name} within {timeout:g} s")
        time.sleep(0.01)
