"""The app log ``<data dir>/logs/reframe.log``: one JSON object per line, rotated by size.

The server process installs it (:func:`install`) and closes it when it stops; closing puts
every logger level and handler back as it was, so apps that start one after another in one
process do not leak into each other. Reframe's own loggers reach the file at the level of the
setting, other libraries only from WARNING up, and what reached stderr before still does. A
file that cannot be opened or written never stops the program: one stderr line says why.
"""

from __future__ import annotations

import contextlib
import logging
import sys
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
    "AppLog",
    "JsonLinesFormatter",
    "install",
    "logs_dir",
]

LOG_FILE = "reframe.log"
MAX_BYTES = 5 * 1024 * 1024
"""Size above which ``reframe.log`` is moved to ``reframe.log.1``."""
BACKUP_COUNT = 3
"""Old files kept: ``reframe.log.1`` … ``reframe.log.3``."""

OWN_LOGGERS = ("reframe", "reframe_server", "uvicorn.error")
"""Loggers (with their children) written at the level of the setting."""
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


class JsonLinesFormatter(logging.Formatter):
    """A record as one JSON line: ``time`` (UTC, milliseconds), ``level``, ``logger``,
    ``message``, ``exception`` when there is one, then the fields given through ``extra``."""

    def format(self, record: logging.LogRecord) -> str:
        try:
            message = record.getMessage()
        except Exception:  # a bad format string must not lose the record
            message = f"{record.msg!s} {record.args!r}"
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
                data[key] = to_jsonable_python(value, fallback=repr)
        return json_text(data, ensure_ascii=False)


class _File(RotatingFileHandler):
    """The file handler. Its first failure turns it off with one stderr line: Python's
    logging would print a traceback for every record that follows."""

    def __init__(self, path: Path, *, max_bytes: int, backup_count: int) -> None:
        super().__init__(path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
        self.threshold = logging.INFO
        self.broken = False
        self.setFormatter(JsonLinesFormatter())

    def filter(self, record: logging.LogRecord) -> bool:
        name = record.name
        if self.broken or _within(name, _ACCESS):
            return False
        if any(_within(name, own) for own in OWN_LOGGERS):
            return record.levelno >= self.threshold
        return record.levelno >= max(logging.WARNING, self.threshold)

    def handleError(self, record: logging.LogRecord) -> None:
        if self.broken:
            return
        self.broken = True
        _say(f"the app log {self.baseFilename} cannot be written ({sys.exc_info()[1]})")
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


def _say(problem: str) -> None:
    stream = sys.stderr
    if stream is None:  # a frozen app without a console
        return
    with contextlib.suppress(OSError, ValueError):
        print(f"reframe: {problem}; the server runs without it", file=stream, flush=True)


class AppLog:
    """An installed app log. :meth:`set_level` and :meth:`close` never raise."""

    def __init__(self, handler: _File) -> None:
        self._handler = handler
        self._closed = False
        root = logging.getLogger()
        # uvicorn's own loggers do not propagate to the root logger once its log config is
        # applied, so their records come through a forwarder on the "uvicorn" logger.
        self._forwards: list[tuple[logging.Logger, logging.Handler]] = [
            (root, _Forward(handler, skip=_UVICORN)),
            (logging.getLogger(_UVICORN), _Forward(handler)),
        ]
        # A record that finds no handler goes to logging.lastResort (stderr, WARNING and up).
        # The forwarder on the root logger counts as a handler, so keep that stderr output.
        if not root.handlers and logging.lastResort is not None:
            self._forwards.append((root, logging.lastResort))
        self._levels = {
            name: (logging.getLogger(name).level, logging.getLogger(name).getEffectiveLevel())
            for name in OWN_LOGGERS
        }
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
        threshold = _LEVELS[level]
        self._handler.threshold = threshold
        for name, (_, effective) in self._levels.items():
            # Never above the level the logger had: that would take records away from stderr.
            logging.getLogger(name).setLevel(min(threshold, effective))

    def close(self) -> None:
        """Remove the handlers, put the logger levels back and close the file."""
        if self._closed:
            return
        self._closed = True
        for logger, forward in self._forwards:
            logger.removeHandler(forward)
        for name, (level, _) in self._levels.items():
            logging.getLogger(name).setLevel(level)
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
    app_log = AppLog(handler)
    app_log.set_level(level)
    return app_log
