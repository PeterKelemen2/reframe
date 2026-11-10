"""Paths that Windows refuses because of their length while long paths are off."""

from __future__ import annotations

import sys
from pathlib import PureWindowsPath

import pytest

from reframe.platform import longpath


@pytest.fixture
def long_paths_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(longpath, "long_paths_enabled", lambda: False)


def padded(length: int) -> PureWindowsPath:
    head = "C:\\Videos\\"
    return PureWindowsPath(head + "x" * (length - len(head)))


@pytest.mark.usefixtures("long_paths_off")
def test_a_path_is_refused_from_max_path_on() -> None:
    assert not longpath.refused(padded(259))
    assert longpath.refused(padded(260))
    assert not longpath.refused(padded(247), limit=longpath.MAX_FOLDER_PATH)
    assert longpath.refused(padded(248), limit=longpath.MAX_FOLDER_PATH)


@pytest.mark.usefixtures("long_paths_off")
def test_a_character_outside_the_bmp_counts_twice() -> None:
    assert longpath.refused(PureWindowsPath(str(padded(258)) + "🎬"))


def test_nothing_is_refused_while_long_paths_are_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(longpath, "long_paths_enabled", lambda: True)
    assert not longpath.refused(padded(1000))
    assert longpath.missing_text(padded(1000), "missing") == "missing"


@pytest.mark.usefixtures("long_paths_off")
def test_the_text_names_the_length_and_the_limit() -> None:
    text = longpath.missing_text(padded(300), "missing")
    assert text.startswith("Windows refuses this path: it has 300 characters")
    assert "allows 259" in text
    assert "Turn on long paths" in text
    assert longpath.missing_text(padded(100), "missing") == "missing"


if sys.platform == "win32":
    import winreg

    def test_windows_reports_the_policy_of_this_process() -> None:
        path = r"SYSTEM\CurrentControlSet\Control\FileSystem"
        policy = winreg.QueryValueEx(
            winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path), "LongPathsEnabled"
        )
        # Python's own executable opts in through its manifest, so the policy decides.
        assert longpath._query() is bool(policy[0])


@pytest.mark.skipif(sys.platform == "win32", reason="the policy off Windows")
def test_off_windows_long_paths_are_always_on() -> None:
    assert longpath._query() is True
