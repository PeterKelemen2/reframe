"""The file-system reads of output naming, behind one small interface that tests replace.

Both reads are optional: the folder listing (season-pack detection) and the file times. A
missing file or an unreadable folder gives ``None``, never an exception.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

__all__ = ["FileTimes", "NamingFs", "RealNamingFs"]


@dataclass(frozen=True, slots=True)
class FileTimes:
    """Times of a file, local time zone."""

    modified: datetime
    created: datetime | None = None
    """``None`` where the OS does not report a creation time (Linux)."""


class NamingFs(Protocol):
    """What naming reads from the file system."""

    def list_files(self, folder: Path) -> list[str] | None:
        """Names of the files in ``folder`` (not sub-folders); ``None`` when unreadable."""
        ...

    def file_times(self, file: Path) -> FileTimes | None:
        """Modification and creation time of ``file``; ``None`` when it cannot be read."""
        ...


class RealNamingFs:
    """The real file system."""

    def list_files(self, folder: Path) -> list[str] | None:
        try:
            with os.scandir(folder) as entries:
                return sorted(entry.name for entry in entries if entry.is_file())
        except OSError:
            return None

    def file_times(self, file: Path) -> FileTimes | None:
        try:
            st = file.stat()
        except OSError:
            return None
        birth: float | None = getattr(st, "st_birthtime", None)
        return FileTimes(
            modified=datetime.fromtimestamp(st.st_mtime).astimezone(),
            created=None if birth is None else datetime.fromtimestamp(birth).astimezone(),
        )
