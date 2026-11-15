"""MKVToolNix as a test oracle: ``mkvmerge``, ``mkvinfo`` and ``mkvpropedit`` from ``PATH``.

No product code runs MKVToolNix. Tests that compare Reframe's Matroska reader and writer with
it carry the ``needs_mkvtoolnix`` marker, and are skipped where it is not installed.
"""

from __future__ import annotations

import shutil

import pytest

__all__ = ["MKVTOOLNIX_TOOLS", "mkvtoolnix_problem", "mkvtoolnix_tool"]

MKVTOOLNIX_TOOLS = ("mkvmerge", "mkvinfo", "mkvpropedit")


def mkvtoolnix_problem() -> str | None:
    """Why the MKVToolNix oracle cannot run (a program is not on ``PATH``), or ``None``."""
    missing = [name for name in MKVTOOLNIX_TOOLS if shutil.which(name) is None]
    if missing:
        return "MKVToolNix not found on PATH: " + ", ".join(missing)
    return None


def mkvtoolnix_tool(name: str) -> str:
    """The path of ``mkvmerge``, ``mkvinfo`` or ``mkvpropedit``; skips the test without it."""
    if name not in MKVTOOLNIX_TOOLS:
        raise ValueError(f"not an MKVToolNix oracle program: {name}")
    found = shutil.which(name)
    if found is None:
        pytest.skip(f"{name} not found on PATH")
    return found
