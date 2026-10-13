from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path

import pytest

from reframe.naming import FileTimes, NamingFs

#: A fixed "now" for ``{date}`` / ``{time}``: 2026-10-11 14:30, local time.
NOW = datetime(2026, 10, 11, 14, 30, 5).astimezone()


class FakeFs:
    """A file system for naming: folder listings and file times from dictionaries."""

    def __init__(
        self,
        files: Mapping[Path, list[str]] | None = None,
        times: Mapping[Path, FileTimes] | None = None,
    ) -> None:
        self.files = dict(files or {})
        self.times = dict(times or {})
        self.listed: list[Path] = []

    def list_files(self, folder: Path) -> list[str] | None:
        self.listed.append(folder)
        names = self.files.get(folder)
        return None if names is None else sorted(names)

    def file_times(self, file: Path) -> FileTimes | None:
        return self.times.get(file)


type FsFactory = Callable[..., FakeFs]


@pytest.fixture
def fake_fs() -> FsFactory:
    """``fake_fs({folder: [file names]}, {file: FileTimes(...)})``."""
    return FakeFs


@pytest.fixture
def empty_fs() -> NamingFs:
    """No folder can be listed, no file has times (paths that do not exist)."""
    return FakeFs()


@pytest.fixture
def now() -> datetime:
    return NOW
