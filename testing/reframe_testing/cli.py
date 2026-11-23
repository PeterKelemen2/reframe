"""Run the ``reframe`` command line, in the test process or as a child."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest import mock

import typer.rich_utils
from typer.testing import CliRunner, Result

from reframe.cli import build_app
from reframe.tools import ENV_VARS
from reframe_testing.fake_tools import FakeTools

#: ``COLUMNS`` of :func:`invoke`: wide enough that no output line wraps.
WIDTH = "200"


def invoke(*args: str, env: dict[str, str] | None = None) -> Result:
    # Typer forces colour when GITHUB_ACTIONS or FORCE_COLOR is set, read once at import, so
    # `env` cannot turn it off: the help would split `--json` with escape codes.
    with mock.patch.object(typer.rich_utils, "FORCE_TERMINAL", False):
        return CliRunner().invoke(build_app(), list(args), env={"COLUMNS": WIDTH, **(env or {})})


def run_cli(
    fake: FakeTools, tmp_path: Path, *args: str, encoding: str | None
) -> subprocess.CompletedProcess[bytes]:
    """``python -m reframe.cli`` as a child with the fake tools and private folders in
    ``tmp_path``; ``encoding`` is its ``PYTHONIOENCODING`` (none: unset, and no ``PYTHONUTF8``)."""
    env = fake.env()
    for var in ENV_VARS.values():
        env.pop(var, None)
    env.update(
        REFRAME_FFMPEG=str(fake.ffmpeg),
        REFRAME_FFPROBE=str(fake.ffprobe),
        REFRAME_CACHE_DIR=str(tmp_path / "cache-sub"),
        REFRAME_CONFIG_DIR=str(tmp_path / "config-sub"),
        REFRAME_DATA_DIR=str(tmp_path / "data-sub"),
        COLUMNS="120",
    )
    env.pop("PYTHONUTF8", None)
    env.pop("PYTHONIOENCODING", None)
    if encoding is not None:
        env["PYTHONIOENCODING"] = encoding
    return subprocess.run(
        [sys.executable, "-m", "reframe.cli", *args],
        capture_output=True,
        env=env,
        timeout=60,
        check=False,
    )
