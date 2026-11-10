"""Paths that Windows refuses to this process: past ``MAX_PATH`` while long paths are off. Such
a path looks missing to Python (``FileNotFoundError``) although the file may exist, so a
missing path is reported with the real reason."""

from __future__ import annotations

import functools
import os
import sys
from pathlib import PurePath

__all__ = [
    "MAX_FOLDER_PATH",
    "MAX_PATH",
    "long_paths_enabled",
    "missing_text",
    "refused",
    "refused_text",
]

#: Windows' limit in UTF-16 units, the terminating NUL included.
MAX_PATH = 260
#: A folder that is created leaves room for an 8.3 file name in it.
MAX_FOLDER_PATH = MAX_PATH - 12


@functools.cache
def long_paths_enabled() -> bool:
    """Whether this process may use paths past :data:`MAX_PATH`: the ``LongPathsEnabled``
    policy and a manifest that opts in. Always true off Windows."""
    return _query()


if sys.platform == "win32":
    import ctypes

    def _query() -> bool:
        try:
            function = ctypes.WinDLL("ntdll").RtlAreLongPathsEnabled
        except (OSError, AttributeError):  # Windows 10 before 1607
            return False
        function.restype = ctypes.c_ubyte
        function.argtypes = []
        return bool(function())

else:

    def _query() -> bool:
        return True


def _length(path: str | os.PathLike[str]) -> int:
    text = os.fspath(path)
    if not (path.is_absolute() if isinstance(path, PurePath) else os.path.isabs(text)):
        text = os.path.abspath(text)
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def refused(path: str | os.PathLike[str], *, limit: int = MAX_PATH) -> bool:
    """Whether Windows refuses ``path`` to this process because of its length; ``limit`` is
    :data:`MAX_FOLDER_PATH` for a folder that is to be created."""
    return not long_paths_enabled() and _length(path) >= limit


def refused_text(path: str | os.PathLike[str], *, limit: int = MAX_PATH) -> str:
    return (
        f"Windows refuses this path: it has {_length(path)} characters, and Windows allows "
        f"{limit - 1} while long paths are turned off. Turn on long paths in Windows, or use a "
        "shorter path."
    )


def missing_text(path: str | os.PathLike[str], missing: str) -> str:
    """``missing``, or :func:`refused_text` when the length of ``path`` is why it was not
    found."""
    return refused_text(path) if refused(path) else missing
