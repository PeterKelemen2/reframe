"""The app log: JSON lines, rotation, the level, a file that cannot be written, clean removal."""

from __future__ import annotations

import errno
import json
import logging
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from reframe import applog
from reframe.service import Reframe

TIME = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")


def lines(folder: Path, name: str = applog.LOG_FILE) -> list[dict[str, Any]]:
    path = folder / name
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def messages(folder: Path) -> list[str]:
    return [line["message"] for line in lines(folder)]


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    return tmp_path / "logs"


@pytest.fixture
def library() -> Iterator[logging.Logger]:
    """A third-party logger that lets its DEBUG records through."""
    logger = logging.getLogger("somelibrary")
    logger.setLevel(logging.DEBUG)
    yield logger
    logger.setLevel(logging.NOTSET)


def test_each_record_is_a_json_line_with_its_fields_and_context(folder: Path) -> None:
    app_log = applog.install(folder, "debug")
    assert app_log is not None
    log = logging.getLogger("reframe.queue.test")
    log.info("job %s started", "j1", extra={"job_id": "j1", "path": Path("/media/a.mkv")})
    try:
        raise ValueError("bad value")
    except ValueError:
        log.exception("it failed")
    log.warning("name \udcff and é")
    app_log.close()

    first, second, third = lines(folder)
    assert TIME.match(first["time"])
    assert (first["level"], first["logger"], first["message"]) == (
        "info",
        "reframe.queue.test",
        "job j1 started",
    )
    assert (first["job_id"], first["path"]) == ("j1", "/media/a.mkv")
    assert "exception" not in first
    assert second["level"] == "error"
    assert "Traceback" in second["exception"]
    assert "ValueError: bad value" in second["exception"]
    assert third["message"] == "name \udcff and é"


def test_the_file_rotates_at_its_size_and_keeps_three_old_files(folder: Path) -> None:
    app_log = applog.install(folder, "info", max_bytes=2000)
    assert app_log is not None
    log = logging.getLogger("reframe.test")
    for n in range(200):
        log.info("record %03d %s", n, "x" * 60)
    app_log.close()

    names = sorted(path.name for path in folder.iterdir())
    assert names == ["reframe.log", "reframe.log.1", "reframe.log.2", "reframe.log.3"]
    assert all((folder / name).stat().st_size <= 2000 for name in names)
    assert messages(folder)[-1].startswith("record 199")


def test_the_defaults_are_five_mib_and_three_old_files(folder: Path) -> None:
    app_log = applog.install(folder, "info")
    assert app_log is not None
    app_log.close()
    assert (app_log.max_bytes, app_log.backup_count) == (5 * 1024 * 1024, 3)


def test_the_level_filters_reframe_records_and_a_change_applies_at_once(folder: Path) -> None:
    app_log = applog.install(folder, "warning")
    assert app_log is not None
    log = logging.getLogger("reframe.capabilities.test")
    log.info("info at warning")
    log.warning("warning at warning")
    app_log.set_level("debug")
    log.debug("debug at debug")
    app_log.set_level("error")
    log.warning("warning at error")
    log.error("error at error")
    app_log.close()
    assert messages(folder) == ["warning at warning", "debug at debug", "error at error"]


def test_other_libraries_are_written_only_from_warning_up(
    folder: Path, library: logging.Logger
) -> None:
    app_log = applog.install(folder, "debug")
    assert app_log is not None
    library.debug("library debug")
    library.info("library info")
    library.warning("library warning")
    logging.getLogger("reframe_server.test").debug("server debug")
    app_log.close()
    assert messages(folder) == ["library warning", "server debug"]


def test_the_access_log_is_never_written(folder: Path) -> None:
    app_log = applog.install(folder, "debug")
    assert app_log is not None
    logging.getLogger("uvicorn.access").warning('127.0.0.1 - "GET /api/fs?path=/x" 200')
    logging.getLogger("uvicorn.error").info("Application startup complete.")
    app_log.close()
    assert messages(folder) == ["Application startup complete."]


def test_close_removes_every_handler_and_puts_the_levels_back(folder: Path) -> None:
    names = ["", "uvicorn", *applog.OWN_LOGGERS]
    before = {
        name: (logging.getLogger(name).level, logging.getLogger(name).handlers[:]) for name in names
    }
    app_log = applog.install(folder, "debug")
    assert app_log is not None
    app_log.close()
    app_log.set_level("debug")  # after close: nothing changes
    logging.getLogger("reframe.test").error("after close")
    after = {
        name: (logging.getLogger(name).level, logging.getLogger(name).handlers[:]) for name in names
    }
    assert after == before
    assert "after close" not in messages(folder)


def test_stderr_shows_what_it_showed_without_the_log(
    folder: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without handlers, Python prints WARNING and up on stderr: the server's stderr (the
    desktop's sidecar.log, a CLI-started server's server.log) must keep those lines."""
    monkeypatch.setattr(logging.getLogger(), "handlers", [])
    app_log = applog.install(folder, "debug")
    assert app_log is not None
    log = logging.getLogger("reframe.test")
    log.debug("debug for the file only")
    log.warning("a warning for both")
    app_log.close()
    err = capsys.readouterr().err
    assert "a warning for both" in err
    assert "debug for the file only" not in err
    assert messages(folder) == ["debug for the file only", "a warning for both"]


def test_a_file_that_cannot_be_opened_gives_one_stderr_line(
    folder: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (folder / applog.LOG_FILE).mkdir(parents=True)
    root_handlers = logging.getLogger().handlers[:]
    assert applog.install(folder, "info") is None
    err = capsys.readouterr().err
    assert len(err.splitlines()) == 1
    assert "cannot be opened" in err
    assert "Traceback" not in err
    assert logging.getLogger().handlers == root_handlers


class _FullDisk:
    def seek(self, _offset: int, _whence: int = 0) -> int:
        return 0

    def tell(self) -> int:
        return 0

    def write(self, _text: str) -> int:
        raise OSError(errno.ENOSPC, "No space left on device")

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


def test_a_write_that_fails_turns_the_log_off_with_one_stderr_line(
    folder: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    app_log = applog.install(folder, "info")
    assert app_log is not None
    handler = app_log._handler
    assert handler.stream is not None
    handler.stream.close()
    handler.stream = _FullDisk()  # type: ignore[assignment]
    log = logging.getLogger("reframe.test")
    for n in range(5):
        log.error("record %d", n)
    assert app_log.broken
    app_log.close()
    err = capsys.readouterr().err
    assert len(err.splitlines()) == 1
    assert "cannot be written" in err
    assert "No space left on device" in err
    assert "Traceback" not in err


@pytest.mark.anyio
async def test_a_log_level_change_in_the_settings_is_passed_on_at_once(tmp_path: Path) -> None:
    levels: list[str] = []
    reframe = Reframe(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        on_log_level=levels.append,
    )
    try:
        await reframe.settings.update(
            [{"op": "replace", "path": "/preview/sample_frames", "value": 5}]
        )
        assert levels == []
        await reframe.settings.update(
            [{"op": "replace", "path": "/diagnostics/log_level", "value": "debug"}]
        )
        assert levels == ["debug"]
    finally:
        await reframe.close()
