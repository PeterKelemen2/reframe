from __future__ import annotations

import subprocess
import sys

from reframe_testing import processes


def test_interpreter_is_the_process_that_runs_the_code() -> None:
    code = "import os, sys; print(os.getpid(), flush=True); sys.stdin.read()"
    with subprocess.Popen(
        [sys.executable, "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
    ) as child:
        assert child.stdin is not None
        assert child.stdout is not None
        reported = int(child.stdout.readline())
        assert processes.interpreter(child.pid).pid == reported
        assert (reported != child.pid) is processes.LAUNCHER
        child.stdin.close()
        assert child.wait(30) == 0
