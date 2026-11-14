"""The app log ``<data dir>/logs/reframe.log``: one JSON object per line, rotated by size.

The server process installs it (:func:`install`) and closes it when it stops; once the last
open app log is closed, every logger level and handler is as it was before the first one
opened. Reframe's own loggers reach the file at the level of the setting; no other logger
reaches it below INFO, because libraries log request headers and WebSocket frames (the session
cookie, the auth token) at DEBUG. What reached stderr before still does. A file that cannot be
opened or written never stops the program: one stderr line says why.
"""

from __future__ import annotations

import contextlib
import logging
import math
import os
import sys
import threading
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from pydantic_core import to_jsonable_python

from reframe.models.settings import LogLevel
from reframe.models.text import json_text

__all__ = [
    "BACKUP_COUNT",
    "LOG_FILE",
    "MAX_BYTES",
    "SERVER_LOG",
    "AppLog",
    "JsonLinesFormatter",
    "install",
    "logs_dir",
]

LOG_FILE = "reframe.log"
SERVER_LOG = "server.log"
"""The stderr of a server that a CLI client started, in :func:`logs_dir`."""
MAX_BYTES = 5 * 1024 * 1024
"""Size above which ``reframe.log`` is moved to ``reframe.log.1``."""
BACKUP_COUNT = 3
"""Old files kept: ``reframe.log.1`` … ``reframe.log.3``."""

OWN_LOGGERS = ("reframe", "reframe_server")
"""Loggers (with their children) written at the level of the setting."""
_SERVER = "uvicorn.error"
"""uvicorn's start-up, shutdown and error lines; written from INFO up."""
_ACCESS = "uvicorn.access"
_UVICORN = "uvicorn"

_LEVELS: dict[LogLevel, int] = {
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
}

_RECORD_FIELDS = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
    # uvicorn's copy of the message with terminal colours.
    "color_message",
}


def logs_dir(data_dir: Path) -> Path:
    """``<data dir>/logs``: the app log, the job logs and the desktop's sidecar log."""
    return data_dir / "logs"


def _within(name: str, parent: str) -> bool:
    return name == parent or name.startswith(parent + ".")


def _repr(value: object) -> str:
    try:
        return repr(value)
    except Exception:
        return f"<{type(value).__name__} object: its repr failed>"


def _str(value: object) -> str:
    try:
        return str(value)
    except Exception:
        return _repr(value)


def _finite(data: object) -> object:
    if isinstance(data, float) and not math.isfinite(data):
        return str(data)  # JSON has no NaN or Infinity
    if isinstance(data, list):
        return [_finite(item) for item in data]
    if isinstance(data, dict):
        return {key: _finite(item) for key, item in data.items()}
    return data


def _field(value: object) -> object:
    try:
        return _finite(to_jsonable_python(value, fallback=_repr))
    except Exception:  # a circular value, bytes that are not UTF-8
        return _repr(value)


class JsonLinesFormatter(logging.Formatter):
    """A record as one JSON line: ``time`` (UTC, milliseconds), ``level``, ``logger``,
    ``message``, ``exception`` when there is one, then the fields given through ``extra``.
    Never raises: a value that cannot be written as JSON is written as its ``repr``."""

    def format(self, record: logging.LogRecord) -> str:
        try:
            message = record.getMessage()
        except Exception:  # a bad format string, or a message whose str() raises
            message = f"{_str(record.msg)} {_repr(record.args)}"
        data: dict[str, object] = {
            "time": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": message,
        }
        if record.exc_info:
            data["exception"] = record.exc_text or self.formatException(record.exc_info)
        elif record.exc_text:
            data["exception"] = record.exc_text
        for key, value in record.__dict__.items():
            if key not in _RECORD_FIELDS and key not in data:
                data[key] = _field(value)
        return json_text(data, ensure_ascii=False)


class _File(RotatingFileHandler):
    """The file handler. A write that fails turns it off with one stderr line (Python's
    logging would print a traceback for every record that follows); a record that cannot be
    formatted is dropped alone."""

    def __init__(self, path: Path, *, max_bytes: int, backup_count: int) -> None:
        super().__init__(path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
        self.threshold = logging.INFO
        self.broken = False
        self.rotation_failed = False
        self.setFormatter(JsonLinesFormatter())

    def filter(self, record: logging.LogRecord) -> bool:
        name = record.name
        if self.broken or _within(name, _ACCESS):
            return False
        if any(_within(name, own) for own in OWN_LOGGERS):
            return record.levelno >= self.threshold
        floor = logging.INFO if _within(name, _SERVER) else logging.WARNING
        return record.levelno >= max(floor, self.threshold)

    def doRollover(self) -> None:
        if self.stream is not None:
            self.stream.close()
        try:
            if self.backupCount > 0:
                self._shift()
        except OSError as exc:
            # Windows: another process has a file open, so it cannot be renamed. The next
            # record tries again; the file grows meanwhile.
            if not self.rotation_failed:
                self.rotation_failed = True
                _say(f"the app log {self.baseFilename} cannot be rotated ({exc})", "it grows")
        # An OSError here reaches handleError: the log is off.
        self.stream = self._open()

    def _shift(self) -> None:
        """Move each file one number up, but only as far as the first number that is free:
        a rotation that failed half way then loses no old file when it is tried again."""
        base = self.baseFilename
        names = [base] + [
            self.rotation_filename(f"{base}.{n}") for n in range(1, self.backupCount + 1)
        ]
        free = next((n for n in range(1, len(names)) if not os.path.exists(names[n])), None)
        if free is None:
            free = len(names) - 1
            os.remove(names[free])
        for n in range(free, 0, -1):
            self.rotate(names[n - 1], names[n])

    def handleError(self, record: logging.LogRecord) -> None:
        error = sys.exc_info()[1]
        if self.broken or not isinstance(error, OSError):
            return
        self.broken = True
        _say(f"the app log {self.baseFilename} cannot be written ({error})")
        with contextlib.suppress(OSError):
            self.close()


class _Forward(logging.Handler):
    """Hands the records that reach its logger to the file handler. ``skip``: a logger whose
    records reach the file through another forwarder."""

    def __init__(self, target: _File, *, skip: str | None = None) -> None:
        super().__init__()
        self._target = target
        self._skip = skip

    def emit(self, record: logging.LogRecord) -> None:
        if self._skip is None or not _within(record.name, self._skip):
            self._target.handle(record)


def _say(problem: str, outcome: str = "the server runs without it") -> None:
    stream = sys.stderr
    if stream is None:  # a frozen app without a console
        return
    with contextlib.suppress(OSError, ValueError):
        print(f"reframe: {problem}; {outcome}", file=stream, flush=True)


class _Shared:
    """What the open app logs change together: the levels of Reframe's loggers and the
    stderr fallback. They are taken when the first one opens and put back when the last one
    closes, in whatever order they close."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._open: list[_File] = []
        self._levels: dict[str, tuple[int, int]] = {}
        self._last_resort: logging.Handler | None = None

    def add(self, handler: _File) -> None:
        with self._lock:
            if not self._open:
                self._levels = {
                    name: (
                        logging.getLogger(name).level,
                        logging.getLogger(name).getEffectiveLevel(),
                    )
                    for name in OWN_LOGGERS
                }
                # A record that finds no handler goes to logging.lastResort (stderr, WARNING
                # and up). The forwarder on the root logger counts as a handler, so keep that
                # stderr output.
                root = logging.getLogger()
                if not root.handlers and logging.lastResort is not None:
                    self._last_resort = logging.lastResort
                    root.addHandler(self._last_resort)
            self._open.append(handler)
            self._apply()

    def remove(self, handler: _File) -> None:
        with self._lock:
            self._open.remove(handler)
            if self._open:
                self._apply()
                return
            for name, (level, _) in self._levels.items():
                logging.getLogger(name).setLevel(level)
            if self._last_resort is not None:
                logging.getLogger().removeHandler(self._last_resort)
                self._last_resort = None

    def changed(self) -> None:
        with self._lock:
            self._apply()

    def _apply(self) -> None:
        threshold = min(handler.threshold for handler in self._open)
        for name, (_, effective) in self._levels.items():
            # Never above the level the logger had: that would take records away from stderr.
            logging.getLogger(name).setLevel(min(threshold, effective))


_shared = _Shared()


class AppLog:
    """An installed app log. :meth:`set_level` and :meth:`close` never raise."""

    def __init__(self, handler: _File) -> None:
        self._handler = handler
        self._closed = False
        _shared.add(handler)
        # uvicorn's own loggers do not propagate to the root logger once its log config is
        # applied, so their records come through a forwarder on the "uvicorn" logger.
        self._forwards: list[tuple[logging.Logger, logging.Handler]] = [
            (logging.getLogger(), _Forward(handler, skip=_UVICORN)),
            (logging.getLogger(_UVICORN), _Forward(handler)),
        ]
        for logger, forward in self._forwards:
            logger.addHandler(forward)

    @property
    def max_bytes(self) -> int:
        return self._handler.maxBytes

    @property
    def backup_count(self) -> int:
        return self._handler.backupCount

    @property
    def broken(self) -> bool:
        """Writing failed: the log is off until the next start."""
        return self._handler.broken

    def set_level(self, level: LogLevel) -> None:
        """Write Reframe's records from ``level`` up, at once."""
        if self._closed:
            return
        self._handler.threshold = _LEVELS[level]
        _shared.changed()

    def close(self) -> None:
        """Remove the handlers, put the logger levels back and close the file."""
        if self._closed:
            return
        self._closed = True
        for logger, forward in self._forwards:
            logger.removeHandler(forward)
        _shared.remove(self._handler)
        with contextlib.suppress(OSError):
            self._handler.close()


def install(
    folder: Path,
    level: LogLevel,
    *,
    max_bytes: int = MAX_BYTES,
    backup_count: int = BACKUP_COUNT,
) -> AppLog | None:
    """Start writing ``folder/reframe.log`` at ``level``. ``None`` when the file cannot be
    opened (one line on stderr says why). Close the result when the program stops."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
        handler = _File(folder / LOG_FILE, max_bytes=max_bytes, backup_count=backup_count)
    except OSError as exc:
        _say(f"the app log {folder / LOG_FILE} cannot be opened ({exc})")
        return None
    handler.threshold = _LEVELS[level]
    return AppLog(handler)
