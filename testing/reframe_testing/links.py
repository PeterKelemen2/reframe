"""Whether this process can make symbolic links: Windows allows it only with a privilege (or in
Developer Mode)."""

from __future__ import annotations

import functools
import os
import tempfile
from pathlib import Path

import pytest

__all__ = ["can_symlink", "needs_symlinks"]


@functools.cache
def can_symlink() -> bool:
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "target"
        target.write_bytes(b"")
        try:
            os.symlink(target, Path(folder) / "link")
        except OSError:
            return False
    return True


needs_symlinks = pytest.mark.skipif(
    not can_symlink(), reason="this process cannot make symbolic links (Windows: no privilege)"
)
