"""The settings store: ``<config>/settings.json`` with migrations, atomic writes, and the
handling of damaged, newer, unreadable and linked files. The JSON file helpers here are shared
with the preset store. Expected failures are ``app.warning`` events, never exceptions.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from reframe.events import EventBus
from reframe.fsretry import replace_file
from reframe.models.events import AppWarningEvent
from reframe.models.issues import ValidationIssue
from reframe.models.migrations import (
    MigrationError,
    UnsupportedSchemaVersion,
    current_version,
    migrate,
)
from reframe.models.preset import FieldChange
from reframe.models.settings import AppSettings
from reframe.models.text import json_text

__all__ = [
    "MAX_DEPTH",
    "SETTINGS_FILE",
    "DocumentRead",
    "JsonDocumentFile",
    "SettingsStore",
    "SettingsUpdate",
    "StoreProblems",
    "parse_document",
    "too_deep",
    "validation_detail",
]

log = logging.getLogger(__name__)

SETTINGS_FILE = "settings.json"
#: ``True`` on Windows (tests set it).
WINDOWS = os.name == "nt"
#: The deepest nesting (objects and lists, the document itself is level 1) that a settings or
#: presets document may have. Far below the depth where the parser, Pydantic's ``model_dump``
#: or the migrations' ``deepcopy`` fail.
MAX_DEPTH = 64
#: The detail of a damaged document that is nested too deeply.
TOO_DEEP = f"the JSON is nested more than {MAX_DEPTH} levels deep"


def too_deep(value: object, limit: int = MAX_DEPTH) -> bool:
    """``True`` when ``value`` (parsed JSON) has more than ``limit`` levels of objects and
    lists. Iterative, so any depth is safe."""
    stack: list[tuple[object, int]] = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        if isinstance(item, Mapping):
            children: Iterable[object] = item.values()
        elif isinstance(item, (list, tuple)):
            children = item
        else:
            continue
        if depth > limit:
            return True
        stack.extend((child, depth + 1) for child in children)
    return False


def _link_target(path: Path) -> Path:
    """The file that a read or write of ``path`` touches: ``path``, or the end of its chain of
    symbolic links."""
    try:
        if not path.is_symlink():
            return path
    except OSError:
        return path
    return Path(os.path.realpath(path))


@dataclass(frozen=True)
class DocumentRead:
    """What :meth:`JsonDocumentFile.read` found: no file, an unreadable one (``detail`` says
    why), a damaged one (not UTF-8 JSON, not an object, or nested too deeply), or a parsed
    object in ``data``.
    """

    status: Literal["missing", "unreadable", "corrupt", "ok"]
    data: dict[str, Any] | None = None
    detail: str | None = None


class JsonDocumentFile:
    """One JSON document on disk: read, atomic write, backup. A symbolic link at ``path`` is
    followed: its target is read, written and backed up, and the link stays."""

    def __init__(self, path: Path, *, max_depth: int | None = MAX_DEPTH) -> None:
        """``max_depth``: a deeper document is ``corrupt`` on read and never written. ``None``:
        the caller checks the parts itself, so that one deep preset does not damage the whole
        file."""
        self.path = path
        self.max_depth = max_depth

    @property
    def target(self) -> Path:
        """The file that is really read and written (``path``, or where a link there points)."""
        return _link_target(self.path)

    def read(self) -> DocumentRead:
        try:
            raw = self.target.read_bytes()
        except FileNotFoundError:
            return DocumentRead("missing")
        except OSError as exc:  # permission denied, a folder in its place, I/O error …
            return DocumentRead("unreadable", detail=_os_error(exc))
        try:
            data = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return DocumentRead("corrupt", detail=f"not valid JSON: {exc}")
        except RecursionError:
            return DocumentRead("corrupt", detail=TOO_DEEP)
        if not isinstance(data, dict):
            return DocumentRead("corrupt", detail="the file is not a JSON object")
        if self.max_depth is not None and too_deep(data, self.max_depth):
            return DocumentRead("corrupt", detail=TOO_DEEP)
        return DocumentRead("ok", data=data)

    def write(self, data: Mapping[str, Any]) -> str | None:
        """Write ``data`` atomically. Returns ``None``, or why it failed (the old file stays)."""
        if too_deep(data, self.max_depth or MAX_DEPTH):
            return f"not written: {TOO_DEEP}"
        target = self.target
        folder = target.parent
        tmp: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            folder.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(dir=folder, prefix=f".{target.name}.", suffix=".tmp")
            tmp = Path(name)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(json_text(data, ensure_ascii=False, indent=2))
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            replace_file(tmp, target)
            tmp = None
            _sync_folder(folder)
            return None
        except (OSError, TypeError, ValueError, RecursionError) as exc:
            return _os_error(exc) if isinstance(exc, OSError) else str(exc)
        finally:
            if tmp is not None:
                with contextlib.suppress(OSError):
                    tmp.unlink()

    def backup(self) -> Path:
        """Rename the file (a link's target) to ``<stem>.corrupt-<time>[-n]<suffix>`` next to
        it and return the new path. Raises ``OSError`` when that fails."""
        source = self.target
        stamp = time.strftime("%Y%m%d-%H%M%S")
        stem, suffix = source.stem, source.suffix
        target = source.with_name(f"{stem}.corrupt-{stamp}{suffix}")
        number = 1
        while target.exists():
            number += 1
            target = source.with_name(f"{stem}.corrupt-{stamp}-{number}{suffix}")
        replace_file(source, target)
        return target


def _sync_folder(folder: Path) -> None:
    """``fsync`` the folder so the rename survives a crash (POSIX only; best effort)."""
    if WINDOWS or not hasattr(os, "O_DIRECTORY"):
        return
    with contextlib.suppress(OSError):
        fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _os_error(exc: OSError) -> str:
    return f"{exc.strerror or type(exc).__name__}: {exc.filename or ''}".rstrip(": ")


def parse_document[T](
    kind: str, data: dict[str, Any], build: Callable[[dict[str, Any]], T]
) -> T | UnsupportedSchemaVersion | str:
    """``build`` of the migrated ``data``; the error of a document of a newer Reframe; or why
    the document is damaged."""
    try:
        return build(migrate(kind, data))
    except UnsupportedSchemaVersion as exc:
        found = exc.found
        # A bad ``schema_version`` value (not an integer above ours) makes the file damaged.
        newer = isinstance(found, int) and not isinstance(found, bool) and found > exc.current
        return exc if newer else str(exc)
    except ValidationError as exc:
        return validation_detail(exc)
    except (MigrationError, LookupError, TypeError, ValueError) as exc:
        return f"migration failed: {exc}"


def validation_detail(exc: ValidationError, limit: int = 5) -> str:
    """A short text of a Pydantic error: ``where: message`` for each error, up to ``limit``."""
    parts = []
    for error in exc.errors()[:limit]:
        where = ".".join(str(part) for part in error["loc"])
        parts.append(f"{where}: {error['msg']}" if where else str(error["msg"]))
    more = len(exc.errors()) - limit
    if more > 0:
        parts.append(f"… and {more} more")
    return "; ".join(parts)


@dataclass
class SettingsUpdate:
    """The result of a settings change (``Reframe.settings.update``).

    ``settings``: the settings now in effect. ``changes``: what changed (dotted paths, as
    in the preset diff). ``saved``: the file was written. ``issues``: why the change was
    rejected (nothing changed then). ``warnings``: why it was not saved (it is still in effect
    for this session).
    """

    settings: AppSettings
    changes: list[FieldChange] = field(default_factory=list)
    saved: bool = False
    issues: list[ValidationIssue] = field(default_factory=list)
    warnings: list[AppWarningEvent] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues


class StoreProblems:
    """The warnings of a store's last load and of its later failed writes, and why its file
    is protected (newer or unreadable: never overwritten). Each warning is logged and
    published."""

    def __init__(self, events: EventBus | None) -> None:
        self._events = events
        self.problems: list[AppWarningEvent] = []
        self.protected: str | None = None

    def reset(self) -> None:
        self.problems = []
        self.protected = None

    def warn(self, code: str, message: str, detail: str | None = None) -> AppWarningEvent:
        event = AppWarningEvent(code=code, message=message, detail=detail)
        self.problems.append(event)
        log.warning("%s: %s (%s)", code, message, detail)
        if self._events is not None:
            self._events.publish(event)
        return event

    def protect(self, code: str, message: str, detail: str | None) -> None:
        self.protected = message
        self.warn(code, message, detail)


class SettingsStore:
    """``<config>/settings.json``: load (migrations, corrupt-file handling) and atomic save."""

    def __init__(self, config_dir: Path, events: EventBus | None = None) -> None:
        self.path = Path(config_dir) / SETTINGS_FILE
        self._file = JsonDocumentFile(self.path)
        self._warnings = StoreProblems(events)
        self._lock = threading.Lock()

    @property
    def problems(self) -> list[AppWarningEvent]:
        """The warnings of the last :meth:`load` and of later failed saves. The start-up ones
        are published before any UI can subscribe, so a UI reads them here."""
        return list(self._warnings.problems)

    @property
    def read_only(self) -> bool:
        """``True`` when the file must not be overwritten (it is newer or unreadable)."""
        return self._warnings.protected is not None

    def load(self) -> AppSettings:
        with self._lock:
            self._warnings.reset()
            read = self._file.read()
            if read.status == "missing":
                return AppSettings()
            if read.status == "unreadable":
                self._warnings.protect(
                    "settings.unreadable",
                    f"The settings file {self.path} cannot be read. Reframe uses the default "
                    "settings and does not change the file.",
                    read.detail,
                )
                return AppSettings()
            if read.data is None:
                return self._replace_corrupt(read.detail)
            parsed = parse_document("settings", read.data, AppSettings.model_validate)
            if isinstance(parsed, UnsupportedSchemaVersion):
                self._warnings.protect(
                    "settings.newer_version",
                    f"The settings file {self.path} was written by a newer Reframe. "
                    "Reframe uses the default settings for now and does not change the "
                    "file; changes are not saved.",
                    str(parsed),
                )
                return AppSettings()
            if isinstance(parsed, str):
                return self._replace_corrupt(parsed)
            return parsed

    def write(self, settings: AppSettings) -> AppWarningEvent | None:
        """Write ``settings``; returns the warning (also published) when it was not written.

        The file gets the current ``schema_version`` whatever ``settings`` says: its content
        is what this Reframe's model holds, and a newer number would make the next start
        treat the file as newer (and use the defaults)."""
        with self._lock:
            if self._warnings.protected is not None:
                return self._warnings.warn(
                    "settings.not_saved",
                    f"The settings were not saved: {self._warnings.protected}",
                )
            try:
                data = settings.model_dump(mode="json")
            except (ValueError, TypeError, RecursionError) as exc:  # nested far too deeply
                error: str | None = str(exc)
            else:
                data["schema_version"] = current_version("settings")
                error = self._file.write(data)
            if error is not None:
                return self._warnings.warn(
                    "settings.write_failed",
                    f"The settings could not be saved to {self.path}.",
                    error,
                )
            return None

    def _replace_corrupt(self, detail: str | None) -> AppSettings:
        try:
            backup = self._file.backup()
        except OSError as exc:
            self._warnings.protect(
                "settings.corrupt",
                f"The settings file {self.path} is damaged and could not be backed up. Reframe "
                "uses the default settings and does not change the file.",
                f"{detail}; backup failed: {_os_error(exc)}",
            )
            return AppSettings()
        settings = AppSettings()
        data = settings.model_dump(mode="json")
        data["schema_version"] = current_version("settings")
        error = self._file.write(data)
        message = (
            f"The settings file was damaged. It was saved as {backup}, and the default settings "
            "are used."
        )
        if error is not None:
            message += f" Writing the default settings failed: {error}"
        self._warnings.warn("settings.corrupt", message, detail)
        return settings
