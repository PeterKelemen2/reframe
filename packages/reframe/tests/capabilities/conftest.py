"""Fixtures for the C-4 tests (helpers are in ``reframe_testing.capabilities``)."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from reframe.models import AppSettings, ToolInfo
from reframe_testing import fake_tools as ft
from reframe_testing.capabilities import ffmpeg_info


@pytest.fixture
def fake_ffmpeg(fake_tools: ft.FakeTools) -> ToolInfo:
    """The fake ffmpeg as found by discovery (default scenario: real captured texts, and
    every test encode works)."""
    return ffmpeg_info(fake_tools.ffmpeg)


@pytest.fixture
def settings() -> Callable[[], AppSettings]:
    value = AppSettings()
    return lambda: value
