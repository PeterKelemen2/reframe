"""Run the ``reframe`` command line in the test process."""

from __future__ import annotations

from typer.testing import CliRunner, Result

from reframe.cli import build_app

#: ``COLUMNS`` of :func:`invoke`: wide enough that no output line wraps.
WIDTH = "200"


def invoke(*args: str, env: dict[str, str] | None = None) -> Result:
    return CliRunner().invoke(build_app(), list(args), env={"COLUMNS": WIDTH, **(env or {})})
