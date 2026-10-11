"""Where Reframe keeps its files, and where it looks for the bundled tools.

User folders (platformdirs), each overridable by an environment variable — the same names
that the server's ``ServerConfig`` reads with its ``REFRAME_`` prefix (06 §S-0):

- config: ``REFRAME_CONFIG_DIR``; default ``~/.config/reframe`` (Linux),
  ``%LOCALAPPDATA%\\Reframe`` (Windows).
- data: ``REFRAME_DATA_DIR``; default ``~/.local/share/reframe``, ``%LOCALAPPDATA%\\Reframe``.
- cache: ``REFRAME_CACHE_DIR``; default ``~/.cache/reframe``, ``%LOCALAPPDATA%\\Reframe\\Cache``.

(The platformdirs defaults also follow ``XDG_*`` variables on Linux.) An empty variable counts
as unset; a relative path is made absolute. These functions do not create the folders.

**Bundled tools** (02 §Bundled FFmpeg, 07 §Tool bundling). :func:`bundled_tool_roots`
returns the ``tools`` folders that may hold a bundled build, in this order:

1. Frozen app (PyInstaller sidecar, Tauri), relative to ``sys.executable``:
   ``<exe dir>/tools`` (Windows installer, AppImage) and ``<exe dir>/../tools`` (the Tauri
   layout ``resources/sidecar/reframe-server`` next to ``resources/tools``).
2. Linux: ``/usr/lib/reframe/tools`` (.deb / .rpm) and ``/opt/reframe/tools`` (Docker).
3. ``<data dir>/tools``: where ``reframe tools fetch`` installs the pinned build (06 §S-6),
   and where CI installs it.

Inside a root, FFmpeg is in ``ffmpeg/`` (``tools/ffmpeg/bin/ffmpeg``), mkvpropedit in
``mkvtoolnix/`` and mediainfo in ``mediainfo/`` (:data:`BUNDLED_SUBDIRS`). Discovery looks in
``<root>/<subdir>/bin`` and then ``<root>/<subdir>``.
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
BUNDLED_SUBDIRS: Mapping[str, str] = {
    "ffmpeg": "ffmpeg",
    "ffprobe": "ffmpeg",
    "mkvpropedit": "mkvtoolnix",
    "mediainfo": "mediainfo",
}

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
    """The ``tools`` folders to search for a bundled build, in order (see the module doc).

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
