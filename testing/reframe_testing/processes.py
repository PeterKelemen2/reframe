"""The processes that tests start: the interpreter behind ``sys.executable``, and the server's
ready line."""

from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
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


def ready_port(process: subprocess.Popen[bytes], limit: float = 30.0) -> int:
    """The port of the server's ready line, the first line of its stdout."""
    lines: queue.Queue[bytes] = queue.Queue()
    stdout = process.stdout
    assert stdout is not None
    threading.Thread(target=lambda: lines.put(stdout.readline()), daemon=True).start()
    ready = json.loads(lines.get(timeout=limit))
    assert ready["event"] == "ready"
    port: int = ready["port"]
    return port
