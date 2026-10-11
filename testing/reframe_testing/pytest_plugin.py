"""pytest plugin for Reframe tests (registered with ``-p reframe_testing.pytest_plugin``).

Fixtures:

- ``fixture_media``: a function ``(name: str) -> Path``. It returns the path of a generated
  media fixture (see ``reframe_testing.media.fixture_names()``) and generates it first if it
  is missing or out of date. It skips the test if no ffmpeg is available.
- ``fake_tools``: a :class:`reframe_testing.fake_tools.FakeTools` in a temporary folder with
  the default scenario. Change it with ``fake_tools.set_scenario(...)``.

Tests marked ``needs_ffmpeg`` are skipped (with a reason) when ffmpeg or ffprobe is missing.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from reframe_testing import media
from reframe_testing.fake_tools import FakeTools, make_fake_tools

NO_FFMPEG_REASON = (
    f"needs ffmpeg and ffprobe: set {media.FFMPEG_ENV} / {media.FFPROBE_ENV} or put them on PATH"
)


def ffmpeg_available() -> bool:
    return media.find_ffmpeg() is not None and media.find_ffprobe() is not None


def fixture_media_path(name: str) -> Path:
    """Path of media fixture ``name``, generated on demand; skips the test without ffmpeg."""
    if not ffmpeg_available():
        pytest.skip(NO_FFMPEG_REASON)
    return media.ensure_fixture(name)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if ffmpeg_available():
        return
    skip = pytest.mark.skip(reason=NO_FFMPEG_REASON)
    for item in items:
        if item.get_closest_marker("needs_ffmpeg") is not None:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def fixture_media() -> Callable[[str], Path]:
    """``fixture_media("multitrack")`` -> path of ``testdata/media/multitrack.mkv``."""
    return fixture_media_path


@pytest.fixture
def fake_tools(tmp_path: Path) -> FakeTools:
    """Fake ffmpeg/ffprobe launchers with the default scenario (real captured outputs)."""
    return make_fake_tools(tmp_path / "fake-tools")
