"""A committed script with a shebang is executable in git: a fresh checkout, as on a CI runner,
runs it as git stored it."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def test_every_script_with_a_shebang_is_executable_in_git() -> None:
    if shutil.which("git") is None or not (REPO / ".git").exists():
        pytest.skip("not a git checkout")
    listing = subprocess.run(
        ["git", "ls-files", "-s", "-z"], cwd=REPO, capture_output=True, check=True
    ).stdout
    not_executable = []
    for entry in filter(None, listing.split(b"\0")):
        info, name = entry.split(b"\t", 1)
        path = REPO / name.decode()
        if info.split()[0] == b"100644" and path.is_file():
            with path.open("rb") as file:
                if file.read(2) == b"#!":
                    not_executable.append(name.decode())
    assert not_executable == [], f"git update-index --chmod=+x {' '.join(not_executable)}"
