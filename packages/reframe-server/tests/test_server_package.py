from __future__ import annotations

import subprocess
import sys

import reframe
import reframe_server


def test_server_version_matches_core() -> None:
    assert reframe_server.__version__ == reframe.__version__


def test_the_server_starts_without_the_name_parser() -> None:
    # A fresh interpreter: this test session has imported guessit already.
    code = (
        "import sys, reframe_server.__main__; "
        "print(sorted({'guessit', 'rebulk'} & set(sys.modules)))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]"
