"""Where the D-0 spike keeps its parts. The build and measurement scripts import these, so
each path is written once."""

from __future__ import annotations

from pathlib import Path

SPIKE = Path(__file__).resolve().parent.parent
REPO = SPIKE.parent.parent
TAURI = SPIKE / "src-tauri"
SIDECAR_DIST = SPIKE / "dist"
SIDECAR_ONEDIR = SIDECAR_DIST / "reframe-server"
FROZEN_SERVER = SIDECAR_ONEDIR / "reframe-server"
"""The frozen ``reframe-server`` of the onedir build (the tests also accept
``REFRAME_FROZEN_SERVER``)."""
APP = TAURI / "target" / "release" / "reframe-spike"
"""The spike app of ``npx tauri build --no-bundle``."""
