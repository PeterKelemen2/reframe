"""Build the desktop sidecar into ``desktop/src-tauri/resources/sidecar/``: a PyInstaller onedir
with the frozen ``reframe-server`` and ``reframe`` CLI. Run it with ``uv run python
desktop/sidecar/build.py``."""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

import reframe
import reframe_server

HERE = Path(__file__).resolve().parent
SPEC = HERE / "sidecar.spec"
WORK = HERE / "build"
OUT = HERE.parent / "src-tauri" / "resources" / "sidecar"
PLACEHOLDER = "README.md"
"""Committed, so that the app builds without a sidecar: tauri-build refuses a missing
resource folder."""


def main() -> int:
    if reframe_server.__version__ != reframe.__version__:
        sys.stderr.write(
            f"reframe-server {reframe_server.__version__} and reframe {reframe.__version__} "
            "must have the same version: the frozen CLI starts the frozen server as its owner\n"
        )
        return 1
    started = time.monotonic()
    built = WORK / "dist" / "sidecar"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(built.parent),
            "--workpath",
            str(WORK / "work"),
            str(SPEC),
        ],
        check=False,
    )
    if result.returncode != 0:
        return result.returncode
    OUT.mkdir(parents=True, exist_ok=True)
    for entry in OUT.iterdir():
        if entry.name == PLACEHOLDER:
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    for entry in built.iterdir():
        entry.rename(OUT / entry.name)
    shutil.rmtree(WORK)
    print(f"built reframe {reframe.__version__} in {OUT} in {time.monotonic() - started:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
