"""The Windows retry of a file call that hits a file another process holds open (mocked)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from reframe import fsretry
from reframe.fsretry import ATTEMPTS, replace_file

REAL_REPLACE = os.replace


class FlakyReplace:
    """``os.replace`` that fails ``failures`` times with a Windows sharing violation."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    def __call__(self, source: Path, target: Path) -> None:
        self.calls += 1
        if self.calls <= self.failures:
            # ERROR_SHARING_VIOLATION as Python reports it on Windows
            raise PermissionError(13, "The process cannot access the file", str(target))
        REAL_REPLACE(source, target)


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    slept: list[float] = []
    monkeypatch.setattr(fsretry, "_sleep", slept.append)
    return slept


def test_windows_sharing_violation_is_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    (tmp_path / "a").write_text("new")
    flaky = FlakyReplace(failures=2)
    monkeypatch.setattr(fsretry, "WINDOWS", True)
    monkeypatch.setattr(os, "replace", flaky)
    replace_file(tmp_path / "a", tmp_path / "b")
    assert flaky.calls == 3
    assert sleeps == [0.05, 0.1]
    assert (tmp_path / "b").read_text() == "new"


def test_windows_gives_up_after_the_last_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    flaky = FlakyReplace(failures=100)
    monkeypatch.setattr(fsretry, "WINDOWS", True)
    monkeypatch.setattr(os, "replace", flaky)
    with pytest.raises(PermissionError):
        replace_file(tmp_path / "a", tmp_path / "b")
    assert flaky.calls == ATTEMPTS
    assert len(sleeps) == ATTEMPTS - 1


def test_permission_error_is_not_retried_on_linux(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    flaky = FlakyReplace(failures=1)
    monkeypatch.setattr(fsretry, "WINDOWS", False)
    monkeypatch.setattr(os, "replace", flaky)
    with pytest.raises(PermissionError):
        replace_file(tmp_path / "a", tmp_path / "b")
    assert flaky.calls == 1
    assert sleeps == []


def test_other_os_errors_are_not_retried_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    calls: list[int] = []

    def gone(source: Path, target: Path) -> None:
        calls.append(1)
        raise FileNotFoundError(2, "No such file", str(source))

    monkeypatch.setattr(fsretry, "WINDOWS", True)
    monkeypatch.setattr(os, "replace", gone)
    with pytest.raises(FileNotFoundError):
        replace_file(tmp_path / "a", tmp_path / "b")
    assert calls == [1]
    assert sleeps == []
