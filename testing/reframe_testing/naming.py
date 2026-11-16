"""A stand-in file system for the naming code."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from reframe.naming import FileTimes


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
