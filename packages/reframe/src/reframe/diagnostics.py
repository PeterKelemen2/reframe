"""The diagnostics report for a bug report: plain text a person can read and paste in an issue.

It holds no secret and no user name: the settings are written with their known fields only (an
unknown field from a newer version could hold anything), and every path under the home folder
starts with ``~``. The order of every part is stable.
"""

from __future__ import annotations

import os
import platform
import re
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path

from pydantic import BaseModel
from pydantic_core import to_jsonable_python

from reframe import __version__
from reframe.applog import BACKUP_COUNT, LOG_FILE
from reframe.models.capabilities import CapabilitySnapshot
from reframe.models.settings import AppSettings
from reframe.models.text import json_text
from reframe.models.tools import ToolSet
from reframe.tools.discovery import TOOL_NAMES

__all__ = ["build_report", "home_relative"]

SIDECAR_LOGS = ("sidecar.log", "sidecar.log.1")
"""The desktop shell's copy of the server's stderr."""
SERVER_LOG = "server.log"
"""The stderr of a server that a CLI client started."""

_SEPARATORS = r"[/\\]+"
_NAME_CHAR = re.compile(r"[\w.~-]")


def _home() -> str | None:
    try:
        return str(Path.home())
    except (RuntimeError, KeyError, OSError):
        return None


def home_relative(
    text: str, *, home: str | None = None, windows: bool = sys.platform == "win32"
) -> str:
    """``text`` with every path under the home folder starting with ``~``.

    ``home``: the home folder (default: this user's, ``%USERPROFILE%`` on Windows). On Windows
    the match ignores case and takes either separator. A path that only ends with the home
    folder's path (``/srv/home/ann``) is left alone.
    """
    home = _home() if home is None else home
    if not home:
        return text
    parts = [part for part in re.split(_SEPARATORS, home) if part]
    if not parts or (windows and len(parts) == 1):  # "/" or "C:\": every path would match
        return text
    lead = _SEPARATORS if home[0] in "/\\" else ""
    pattern = re.compile(
        lead + _SEPARATORS.join(re.escape(part) for part in parts) + r"""(?=[/\\\s"',;:)\]}]|$)""",
        re.IGNORECASE if windows else 0,
    )

    def replace(match: re.Match[str]) -> str:
        start = match.start()
        while start > 0 and _NAME_CHAR.match(text, start - 1):
            start -= 1
        if start > 0 and text[start - 1] in "/\\":
            return match[0]  # a longer path that contains the home folder's path
        return "~"

    return pattern.sub(replace, text)


if sys.platform == "win32":

    def _os() -> str:
        version = sys.getwindowsversion().platform_version
        try:
            edition = platform.win32_edition()
        except OSError:
            edition = None
        text = "Windows " + ".".join(str(part) for part in version)
        if edition:
            text += f" ({edition})"
        return f"{text} {os.environ.get('PROCESSOR_ARCHITECTURE', '')}".rstrip()

else:

    def _os() -> str:
        uname = os.uname()
        text = f"{uname.sysname} {uname.release} {uname.machine}"
        try:
            name = platform.freedesktop_os_release().get("PRETTY_NAME")
        except OSError:
            name = None
        return f"{text} ({name})" if name else text


def _python() -> str:
    frozen = ", frozen" if getattr(sys, "frozen", False) else ""
    return f"{platform.python_version()} ({platform.python_implementation()}{frozen})"


def _value(value: object) -> str:
    return json_text(value, ensure_ascii=False)


def _tools(tools: ToolSet) -> Iterable[str]:
    for name in TOOL_NAMES:
        info = tools.get(name)
        yield f"  {name}: {info.status.value}"
        details: list[tuple[str, object]] = [
            ("origin", info.origin.value if info.origin is not None else None),
            ("path", str(info.path) if info.path is not None else None),
            ("version", info.version),
            ("release", info.release),
            ("reason", info.reason),
            ("build flags", " ".join(info.build_flags) or None),
            (
                "libraries",
                ", ".join(f"{lib} {ver}" for lib, ver in info.library_versions.items()) or None,
            ),
        ]
        yield from (f"    {label}: {value}" for label, value in details if value is not None)


def _encoders(snapshot: CapabilitySnapshot) -> Iterable[str]:
    if snapshot.detecting:
        yield "  detection running: the statuses may still change"
    if snapshot.from_cache:
        yield "  from the cache: not checked again yet"
    if snapshot.ffmpeg is not None:
        yield f"  ffmpeg: {snapshot.ffmpeg} ({snapshot.ffmpeg_version or 'version unknown'})"
    if snapshot.checked_at is not None:
        yield f"  checked: {snapshot.checked_at.isoformat(timespec='seconds')}"
    for encoder_id in sorted(snapshot.encoders):
        status = snapshot.encoders[encoder_id]
        line = f"  {encoder_id}: {status.state.value}"
        yield f"{line}: {status.reason}" if status.reason else line
        if status.detail:
            yield f"    detail: {status.detail}"
    if not snapshot.encoders:
        yield "  (none)"


def _known(value: object) -> object:
    if isinstance(value, BaseModel):
        return {name: _known(getattr(value, name)) for name in type(value).model_fields}
    if isinstance(value, list | tuple):
        return [_known(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _known(item) for key, item in value.items()}
    return to_jsonable_python(value, fallback=str)


def _settings(settings: AppSettings) -> Iterable[str]:
    def walk(prefix: str, data: object) -> Iterable[str]:
        if isinstance(data, dict) and data:
            for key, item in data.items():
                yield from walk(f"{prefix}.{key}" if prefix else key, item)
        else:
            yield f"  {prefix} = {_value(data)}"

    yield from walk("", _known(settings))


def _size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KiB"
    return f"{size / (1024 * 1024):.1f} MiB"


def _logs(folder: Path) -> Iterable[str]:
    yield f"  folder: {folder}"
    try:
        files = {entry.name: entry for entry in os.scandir(folder) if entry.is_file()}
    except FileNotFoundError:
        yield "  (the folder does not exist yet)"
        return
    except OSError as exc:
        yield f"  (the folder cannot be read: {exc.strerror or exc})"
        return
    app_logs = [LOG_FILE, *(f"{LOG_FILE}.{n}" for n in range(1, BACKUP_COUNT + 1))]
    named = [*app_logs, *SIDECAR_LOGS, SERVER_LOG]
    for name in named:
        entry = files.get(name)
        if entry is not None:
            try:
                yield f"  {name}: {_size(entry.stat().st_size)}"
            except OSError:
                yield f"  {name}"
    jobs = [name for name in files if name.endswith(".log") and name not in named]
    yield f"  job logs: {len(jobs)}"


def build_report(
    *,
    tools: ToolSet,
    encoders: CapabilitySnapshot,
    settings: AppSettings,
    logs: Path,
    server: Mapping[str, str] | None = None,
    home: str | None = None,
) -> str:
    """The report. ``server``: lines the server adds after the version (its mode, the login
    kind), in their order. ``logs``: the logs folder. Reads the folder and the OS release
    file: call it off the event loop."""
    head = [
        ("Reframe", __version__),
        *(server or {}).items(),
        ("OS", _os()),
        ("Python", _python()),
    ]
    lines = [
        "Reframe diagnostics",
        "",
        *(f"{label}: {value}" for label, value in head),
        "",
        "Tools",
        *_tools(tools),
        "",
        "Encoders",
        *_encoders(encoders),
        "",
        "Settings",
        *_settings(settings),
        "",
        "Logs",
        *_logs(logs),
    ]
    return home_relative("\n".join(lines) + "\n", home=home)
