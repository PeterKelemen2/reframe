"""MKVToolNix as a test oracle: ``mkvmerge``, ``mkvinfo`` and ``mkvpropedit`` from ``PATH``.

No product code runs MKVToolNix. Tests that compare Reframe's Matroska reader and writer with
it carry the ``needs_mkvtoolnix`` marker, and are skipped where it is not installed.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from reframe.models import HeaderEdit

__all__ = [
    "MKVTOOLNIX_TOOLS",
    "mkvpropedit_args",
    "mkvtoolnix_problem",
    "mkvtoolnix_tool",
    "with_bad_tag",
]

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


_FLAG_PROPERTIES = {
    "default": "flag-default",
    "forced": "flag-forced",
    "commentary": "flag-commentary",
    "hearing_impaired": "flag-hearing-impaired",
    "visual_impaired": "flag-visual-impaired",
    "original": "flag-original",
}


def mkvpropedit_args(edit: HeaderEdit) -> list[str]:
    """The mkvpropedit command line (after the program) that makes the ``header_edit`` step's
    ``edit``: the oracle's form of the same edit."""
    args = [str(edit.path)]
    for track in edit.tracks:
        args += ["--edit", f"track:{track.track_type[0]}{track.number}"]
        if track.language is not None and track.language_ietf is not None:
            # In this order: a later ``--set language`` overwrites ``language-ietf``.
            args += ["--set", f"language={track.language}"]
            args += ["--set", f"language-ietf={track.language_ietf}"]
        if track.delete_name:
            args += ["--delete", "name"]
        elif track.name is not None:
            args += ["--set", f"name={track.name}"]
        for flag, value in track.flags.items():
            args += ["--set", f"{_FLAG_PROPERTIES[flag]}={int(value)}"]
    if edit.info is not None:
        args += ["--edit", "info"]
        if edit.info.title is None:
            args += ["--delete", "title"]
        else:
            args += ["--set", f"title={edit.info.title}"]
    return args


def with_bad_tag(path: Path, mkvpropedit: str, bad: bytes) -> None:
    """Write ``LanguageIETF=en-US`` on a1 with mkvpropedit, then put ``bad`` (5 bytes) in its
    place (mkvpropedit refuses to write such a value)."""
    assert len(bad) == 5
    subprocess.run(
        [mkvpropedit, str(path), "--edit", "track:a1", "--set", "language-ietf=en-US"],
        check=True,
        capture_output=True,
    )
    data = bytearray(path.read_bytes())
    needle = bytes.fromhex("22B59D85") + b"en-US"
    assert data.count(needle) == 1
    at = data.index(needle) + 4
    data[at : at + 5] = bad
    path.write_bytes(bytes(data))
