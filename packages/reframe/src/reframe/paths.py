"""Where Reframe keeps its files, and where it looks for the bundled tools. Each user folder
(config, data, cache) is the platformdirs default unless its environment variable (the
``*_DIR_ENV`` constants) is set; an empty variable counts as unset, and a relative path is made
absolute. These functions create no folders. The folders that may hold a bundled build are
listed by :func:`bundled_tool_roots`; each tool's sub-folder is in :data:`BUNDLED_SUBDIRS`.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path

import platformdirs

__all__ = [
    "APP_NAME",
    "BUNDLED_SUBDIRS",
    "CACHE_DIR_ENV",
    "CONFIG_DIR_ENV",
    "DATA_DIR_ENV",
    "bundled_tool_roots",
    "cache_dir",
    "config_dir",
    "data_dir",
]

CONFIG_DIR_ENV = "REFRAME_CONFIG_DIR"
DATA_DIR_ENV = "REFRAME_DATA_DIR"
CACHE_DIR_ENV = "REFRAME_CACHE_DIR"

#: platformdirs app name: ``reframe`` on Linux, ``Reframe`` on Windows (the usual spelling).
APP_NAME = "Reframe" if sys.platform == "win32" else "reframe"

#: Sub-folder of a ``tools`` root for each tool.
BUNDLED_SUBDIRS: Mapping[str, str] = {"ffmpeg": "ffmpeg", "ffprobe": "ffmpeg"}

_LINUX_ROOTS = (Path("/usr/lib/reframe/tools"), Path("/opt/reframe/tools"))


def _from_env(name: str, environ: Mapping[str, str] | None) -> Path | None:
    value = (os.environ if environ is None else environ).get(name, "").strip()
    if not value:
        return None
    return Path(value).expanduser().absolute()


def config_dir(environ: Mapping[str, str] | None = None) -> Path:
    """Settings and user presets (``settings.json``, ``presets.json``)."""
    return _from_env(CONFIG_DIR_ENV, environ) or platformdirs.user_config_path(
        APP_NAME, appauthor=False
    )


def data_dir(environ: Mapping[str, str] | None = None) -> Path:
    """Queue database, logs and the fetched tools."""
    return _from_env(DATA_DIR_ENV, environ) or platformdirs.user_data_path(
        APP_NAME, appauthor=False
    )


def cache_dir(environ: Mapping[str, str] | None = None) -> Path:
    """Probe cache, preview frames, capability cache."""
    return _from_env(CACHE_DIR_ENV, environ) or platformdirs.user_cache_path(
        APP_NAME, appauthor=False
    )


def bundled_tool_roots(
    *,
    environ: Mapping[str, str] | None = None,
    executable: str | None = None,
    frozen: bool | None = None,
    platform: str | None = None,
) -> list[Path]:
    """The ``tools`` folders to search for a bundled build, in order: the app's own folder when
    frozen (installers, the Tauri sidecar layout), then the Linux system folders (packages,
    Docker), then the data folder (``reframe tools fetch``, CI).

    The keyword arguments exist for tests: by default they come from ``os.environ``,
    ``sys.executable``, ``sys.frozen`` and ``sys.platform``.
    """
    platform = sys.platform if platform is None else platform
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    roots: list[Path] = []
    if frozen:
        exe_dir = Path(executable or sys.executable).absolute().parent
        roots += [exe_dir / "tools", exe_dir.parent / "tools"]
    if platform.startswith("linux"):
        roots += _LINUX_ROOTS
    roots.append(data_dir(environ) / "tools")
    unique: list[Path] = []
    for root in roots:
        if root not in unique:
            unique.append(root)
    return unique
