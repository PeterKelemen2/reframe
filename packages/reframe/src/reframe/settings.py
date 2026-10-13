"""The settings store (C-9): ``<config>/settings.json``, and the JSON file helpers that the
preset store (``reframe.presets``) uses too.

**Files.** :class:`JsonDocumentFile` reads and writes one JSON document:

- Writes are atomic: the JSON goes to a temporary file in the same folder (flushed and
  ``fsync``-ed), then ``os.replace`` puts it in place. A reader sees the old or the new file,
  never half of one.
- **Windows**: ``os.replace`` onto a file that another process holds open (an antivirus
  scanner, a backup tool, a second Reframe) raises ``PermissionError`` (a sharing violation).
  On Windows the replace is tried again :data:`REPLACE_ATTEMPTS` times with a short, growing
  pause; then it fails, the temporary file is removed and the old file stays. On Linux a
  ``PermissionError`` is a real permission problem and is not retried.
- Reading accepts a UTF-8 BOM (Windows editors write one).

**Loading** (:meth:`SettingsStore.load`; the preset store does the same):

- No file: the defaults. Nothing is written until something is saved.
- The file runs through the schema migrations (``reframe.models.migrations``), then the model
  validates it. Unknown fields are kept and written back (``DocumentModel``).
- **Corrupt** (not JSON, not an object, a failed migration, or a value the model rejects): the
  file is renamed to ``settings.corrupt-<time>.json`` (the backup), the defaults are written in
  its place, and an ``app.warning`` event (``settings.corrupt``) says where the backup is.
- **Newer** than this Reframe (``UnsupportedSchemaVersion``): the file is kept untouched and
  the defaults are used for this session only. Saving is refused (``settings.not_saved``), so
  the newer file is never overwritten. Warning ``settings.newer_version``.
- **Unreadable** (permission denied, a folder in its place …): the same as newer: defaults,
  nothing written, warning ``settings.unreadable``.

Expected failures are never exceptions: they are ``app.warning`` events, published on the
event bus and kept in :attr:`SettingsStore.problems` (the events of the start-up load are
published before any UI could subscribe, so a UI reads them there).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from reframe.events import EventBus
from reframe.models.events import AppWarningEvent
from reframe.models.issues import ValidationIssue
from reframe.models.migrations import (
    MigrationError,
    MigrationRegistry,
    UnsupportedSchemaVersion,
    migrate,
)
from reframe.models.preset import FieldChange
from reframe.models.settings import AppSettings

__all__ = [
    "REPLACE_ATTEMPTS",
    "SETTINGS_FILE",
    "DocumentRead",
    "JsonDocumentFile",
    "SettingsStore",
    "SettingsUpdate",
    "is_newer",
    "migrate_document",
    "replace_file",
    "validation_detail",
]

log = logging.getLogger(__name__)

SETTINGS_FILE = "settings.json"
#: How often a replace that fails with ``PermissionError`` is tried on Windows.
REPLACE_ATTEMPTS = 6
#: The first pause between two tries (seconds); it doubles each time (about 1.5 s in all).
REPLACE_DELAY = 0.05
#: ``True`` on Windows: a ``PermissionError`` of ``os.replace`` is retried (tests set it).
WINDOWS = os.name == "nt"


def _replace(source: Path, target: Path) -> None:
    """``os.replace`` (one place, so tests can make it fail)."""
    os.replace(source, target)


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def replace_file(source: Path, target: Path) -> None:
    """``os.replace(source, target)``; on Windows a ``PermissionError`` (the target is open
    in another process) is retried a few times before it is raised."""
    delay = REPLACE_DELAY
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            _replace(source, target)
            return
        except PermissionError:
            if not WINDOWS or attempt == REPLACE_ATTEMPTS - 1:
                raise
            _sleep(delay)
            delay *= 2


# --------------------------------------------------------------------------- JSON files


@dataclass(frozen=True)
class DocumentRead:
    """What :meth:`JsonDocumentFile.read` found.

    ``missing``: no file. ``unreadable``: it exists but cannot be read (``detail`` says why).
    ``corrupt``: not UTF-8 JSON or not an object. ``ok``: ``data`` is the parsed object.
    """

    status: Literal["missing", "unreadable", "corrupt", "ok"]
    data: dict[str, Any] | None = None
    detail: str | None = None


class JsonDocumentFile:
    """One JSON document on disk: read, atomic write, backup."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> DocumentRead:
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return DocumentRead("missing")
        except OSError as exc:  # permission denied, a folder in its place, I/O error …
            return DocumentRead("unreadable", detail=_os_error(exc))
        try:
            data = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return DocumentRead("corrupt", detail=f"not valid JSON: {exc}")
        if not isinstance(data, dict):
            return DocumentRead("corrupt", detail="the file is not a JSON object")
        return DocumentRead("ok", data=data)

    def write(self, data: Mapping[str, Any]) -> str | None:
        """Write ``data`` atomically. Returns ``None``, or why it failed (the old file stays)."""
        folder = self.path.parent
        tmp: Path | None = None
        try:
            folder.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(dir=folder, prefix=f".{self.path.name}.", suffix=".tmp")
            tmp = Path(name)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            replace_file(tmp, self.path)
            tmp = None
            _sync_folder(folder)
            return None
        except (OSError, TypeError, ValueError) as exc:
            return _os_error(exc) if isinstance(exc, OSError) else str(exc)
        finally:
            if tmp is not None:
                with contextlib.suppress(OSError):
                    tmp.unlink()

    def backup(self, label: str = "corrupt") -> Path:
        """Rename the file to ``<stem>.<label>-<time>[-n]<suffix>`` next to it and return the
        new path. Raises ``OSError`` when that fails."""
        stamp = time.strftime("%Y%m%d-%H%M%S")
        stem, suffix = self.path.stem, self.path.suffix
        target = self.path.with_name(f"{stem}.{label}-{stamp}{suffix}")
        number = 1
        while target.exists():
            number += 1
            target = self.path.with_name(f"{stem}.{label}-{stamp}-{number}{suffix}")
        replace_file(self.path, target)
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


def migrate_document(
    kind: str, data: dict[str, Any], registry: MigrationRegistry | None = None
) -> dict[str, Any]:
    """``reframe.models.migrations.migrate`` (the real registry), or ``registry.migrate`` when
    one is given (tests). Raises ``UnsupportedSchemaVersion`` / ``MigrationError``."""
    return migrate(kind, data) if registry is None else registry.migrate(kind, data)


def is_newer(exc: UnsupportedSchemaVersion) -> bool:
    """The document is from a newer Reframe (an integer version above ours), not just a bad
    ``schema_version`` value (which makes the file damaged)."""
    found = exc.found
    return isinstance(found, int) and not isinstance(found, bool) and found > exc.current


def validation_detail(exc: ValidationError, limit: int = 5) -> str:
    """A short text of a Pydantic error: ``queue.parallel_jobs: Input should be …``."""
    parts = []
    for error in exc.errors()[:limit]:
        where = ".".join(str(part) for part in error["loc"])
        parts.append(f"{where}: {error['msg']}" if where else str(error["msg"]))
    more = len(exc.errors()) - limit
    if more > 0:
        parts.append(f"… and {more} more")
    return "; ".join(parts)


# --------------------------------------------------------------------------- settings


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


class SettingsStore:
    """``<config>/settings.json``: load (with migrations and the corrupt-file handling of the
    module doc) and atomic save."""

    def __init__(
        self,
        config_dir: Path,
        events: EventBus | None = None,
        *,
        registry: MigrationRegistry | None = None,
    ) -> None:
        self.path = Path(config_dir) / SETTINGS_FILE
        self._file = JsonDocumentFile(self.path)
        self._events = events
        self._registry = registry
        self._problems: list[AppWarningEvent] = []
        self._protected: str | None = None
        self._lock = threading.Lock()

    @property
    def problems(self) -> list[AppWarningEvent]:
        """The warnings of the last :meth:`load` and of later failed saves."""
        return list(self._problems)

    @property
    def read_only(self) -> bool:
        """``True`` when the file must not be overwritten (it is newer or unreadable)."""
        return self._protected is not None

    def load(self) -> AppSettings:
        with self._lock:
            self._problems = []
            self._protected = None
            read = self._file.read()
            if read.status == "missing":
                return AppSettings()
            if read.status == "unreadable":
                self._protect(
                    "settings.unreadable",
                    f"The settings file {self.path} cannot be read. Reframe uses the default "
                    "settings and does not change the file.",
                    read.detail,
                )
                return AppSettings()
            detail: str | None = read.detail
            if read.status == "ok" and read.data is not None:
                try:
                    data = migrate_document("settings", read.data, self._registry)
                    return AppSettings.model_validate(data)
                except UnsupportedSchemaVersion as exc:
                    if not is_newer(exc):
                        return self._replace_corrupt(str(exc))
                    self._protect(
                        "settings.newer_version",
                        f"The settings file {self.path} was written by a newer Reframe. "
                        "Reframe uses the default settings for now and does not change the "
                        "file; changes are not saved.",
                        str(exc),
                    )
                    return AppSettings()
                except ValidationError as exc:
                    detail = validation_detail(exc)
                except (MigrationError, LookupError, TypeError, ValueError) as exc:
                    detail = f"migration failed: {exc}"
            return self._replace_corrupt(detail)

    def save(self, settings: AppSettings) -> None:
        """Write ``settings``. A failure is an ``app.warning`` event, not an exception."""
        self.write(settings)

    def write(self, settings: AppSettings) -> AppWarningEvent | None:
        """Write ``settings``; returns the warning (also published) when it was not written."""
        with self._lock:
            if self._protected is not None:
                return self._warn(
                    "settings.not_saved",
                    f"The settings were not saved: {self._protected}",
                )
            error = self._file.write(settings.model_dump(mode="json"))
            if error is not None:
                return self._warn(
                    "settings.write_failed",
                    f"The settings could not be saved to {self.path}.",
                    error,
                )
            return None

    # ------------------------------------------------------------------ internals

    def _replace_corrupt(self, detail: str | None) -> AppSettings:
        try:
            backup = self._file.backup()
        except OSError as exc:
            self._protect(
                "settings.corrupt",
                f"The settings file {self.path} is damaged and could not be backed up. Reframe "
                "uses the default settings and does not change the file.",
                f"{detail}; backup failed: {_os_error(exc)}",
            )
            return AppSettings()
        settings = AppSettings()
        error = self._file.write(settings.model_dump(mode="json"))
        message = (
            f"The settings file was damaged. It was saved as {backup}, and the default settings "
            "are used."
        )
        if error is not None:
            message += f" Writing the default settings failed: {error}"
        self._warn("settings.corrupt", message, detail)
        return settings

    def _protect(self, code: str, message: str, detail: str | None) -> None:
        self._protected = message
        self._warn(code, message, detail)

    def _warn(self, code: str, message: str, detail: str | None = None) -> AppWarningEvent:
        event = AppWarningEvent(code=code, message=message, detail=detail)
        self._problems.append(event)
        log.warning("%s: %s (%s)", code, message, detail)
        if self._events is not None:
            self._events.publish(event)
        return event
