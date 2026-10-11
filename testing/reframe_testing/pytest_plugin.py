"""pytest plugin for Reframe tests (registered with ``-p reframe_testing.pytest_plugin``).

Fixtures:

- ``fixture_media``: a function ``(name: str) -> Path``. It returns the path of a generated
  media fixture (see ``reframe_testing.media.fixture_names()``) and generates it first if it
  is missing or out of date. It skips the test if no usable ffmpeg is available.
- ``fake_tools``: a :class:`reframe_testing.fake_tools.FakeTools` in a temporary folder with
  the default scenario. Change it with ``fake_tools.set_scenario(...)``. The teardown kills
  every fake process that still runs (:meth:`~reframe_testing.fake_tools.FakeTools.kill_leftovers`).

Tests marked ``needs_ffmpeg`` are skipped (with a reason) when ffmpeg or ffprobe is missing or
does not run (``-version`` fails). With ``REFRAME_REQUIRE_FFMPEG=1`` (set in CI) such a test
fails instead, so a broken tool path cannot make a CI job green by skipping every real-tool
test.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import NoReturn

import pytest

from reframe_testing import media
from reframe_testing.fake_tools import FakeTools, make_fake_tools

REQUIRE_ENV = "REFRAME_REQUIRE_FFMPEG"
NO_FFMPEG_REASON = "needs ffmpeg and ffprobe"

_PROBLEM = pytest.StashKey[str | None]()


def require_ffmpeg() -> bool:
    """``REFRAME_REQUIRE_FFMPEG`` is set to something other than empty, ``0``, ``false``, ``no``."""
    return os.environ.get(REQUIRE_ENV, "").strip().lower() not in ("", "0", "false", "no")


def _tool_problem(name: str, env: str, path: str | None) -> str | None:
    if path is None:
        value = os.environ.get(env)
        if value:
            return f"{name}: {env}={value} is not a file"
        return f"{name} not found: set {env} or put {name} on PATH"
    try:
        out = subprocess.run(
            [path, "-hide_banner", "-version"], capture_output=True, timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"{name} at {path} does not run: {exc}"
    if out.returncode != 0 or not out.stdout.startswith(f"{name} version ".encode()):
        err = out.stderr.decode("utf-8", errors="replace").strip().splitlines()
        detail = err[-1] if err else out.stdout[:80].decode("utf-8", errors="replace")
        return f"{name} at {path} does not run: -version exited with {out.returncode}: {detail}"
    return None


def ffmpeg_problem() -> str | None:
    """Why the real ffmpeg/ffprobe cannot be used, or ``None`` if both run (not cached)."""
    problems = [
        p
        for p in (
            _tool_problem("ffmpeg", media.FFMPEG_ENV, media.find_ffmpeg()),
            _tool_problem("ffprobe", media.FFPROBE_ENV, media.find_ffprobe()),
        )
        if p is not None
    ]
    return f"{NO_FFMPEG_REASON}: {'; '.join(problems)}" if problems else None


def ffmpeg_available() -> bool:
    return ffmpeg_problem() is None


def skip_or_fail(reason: str) -> NoReturn:
    """Skip the current test, or fail it when ``REFRAME_REQUIRE_FFMPEG`` is set."""
    if require_ffmpeg():
        pytest.fail(
            f"{REQUIRE_ENV} is set, so this test must not be skipped: {reason}", pytrace=False
        )
    pytest.skip(reason)


def _session_problem(config: pytest.Config) -> str | None:
    """:func:`ffmpeg_problem`, checked once per test session."""
    if _PROBLEM not in config.stash:
        config.stash[_PROBLEM] = ffmpeg_problem()
    return config.stash[_PROBLEM]


def fixture_media_path(name: str) -> Path:
    """Path of media fixture ``name``, generated on demand; skips the test without ffmpeg."""
    problem = ffmpeg_problem()
    if problem is not None:
        skip_or_fail(problem)
    return media.ensure_fixture(name)


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    if item.get_closest_marker("needs_ffmpeg") is None:
        return
    problem = _session_problem(item.config)
    if problem is not None:
        skip_or_fail(problem)


@pytest.fixture(scope="session")
def fixture_media(request: pytest.FixtureRequest) -> Callable[[str], Path]:
    """``fixture_media("multitrack")`` -> path of ``testdata/media/multitrack.mkv``."""

    def get(name: str) -> Path:
        problem = _session_problem(request.config)
        if problem is not None:
            skip_or_fail(problem)
        return media.ensure_fixture(name)

    return get


@pytest.fixture
def fake_tools(tmp_path: Path) -> Iterator[FakeTools]:
    """Fake ffmpeg/ffprobe launchers with the default scenario (real captured outputs).

    The teardown kills every fake process (main or grandchild) that still runs.
    """
    tools = make_fake_tools(tmp_path / "fake-tools")
    yield tools
    tools.kill_leftovers()
