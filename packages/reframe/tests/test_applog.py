"""The app log: JSON lines, rotation, the level, a file that cannot be written, clean removal."""

from __future__ import annotations

import errno
import json
import logging
import re
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any, Protocol

import pytest

from reframe import applog
from reframe.models.settings import LogLevel
from reframe.service import Reframe

TIME = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")


def strict_json(line: str) -> Any:
    def refuse(constant: str) -> None:
        raise ValueError(f"{constant} is not JSON")

    return json.loads(line, parse_constant=refuse)


def lines(folder: Path, name: str = applog.LOG_FILE) -> list[dict[str, Any]]:
    path = folder / name
    if not path.exists():
        return []
    return [strict_json(line) for line in path.read_text(encoding="utf-8").splitlines()]


def messages(folder: Path) -> list[str]:
    return [line["message"] for line in lines(folder)]


def levels_of(names: Iterable[str]) -> dict[str, int]:
    return {name: logging.getLogger(name).level for name in names}


class Install(Protocol):
    def __call__(self, folder: Path, level: LogLevel, *, max_bytes: int = ...) -> applog.AppLog: ...


@pytest.fixture
def install() -> Iterator[Install]:
    """:func:`applog.install`; each log is closed after the test, also when the test fails."""
    opened: list[applog.AppLog] = []

    def start(folder: Path, level: LogLevel, *, max_bytes: int = applog.MAX_BYTES) -> applog.AppLog:
        app_log = applog.install(folder, level, max_bytes=max_bytes)
        assert app_log is not None
        opened.append(app_log)
        return app_log

    yield start
    for app_log in opened:
        app_log.close()


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


@pytest.fixture
def known_levels() -> Iterator[dict[str, int]]:
    """Reframe's levels set to values that the app log never sets, whatever earlier tests left
    behind, and uvicorn's as its log config sets them."""
    levels = {
        "reframe": logging.ERROR,
        "reframe_server": logging.NOTSET,
        "uvicorn": logging.INFO,
        "uvicorn.error": logging.INFO,
    }
    before = levels_of(levels)
    for name, level in levels.items():
        logging.getLogger(name).setLevel(level)
    yield levels
    for name, level in before.items():
        logging.getLogger(name).setLevel(level)


def without_root_handlers(monkeypatch: pytest.MonkeyPatch) -> None:
    """The root logger of a process that configured no logging: Python prints WARNING and up
    on stderr. Called in the test itself: pytest adds its handlers after the fixtures ran,
    and they fail a test on a record they cannot format."""
    monkeypatch.setattr(logging.getLogger(), "handlers", [])


def test_each_record_is_a_json_line_with_its_fields_and_context(
    folder: Path, install: Install
) -> None:
    app_log = install(folder, "debug")
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


class _BadRepr:
    def __repr__(self) -> str:
        raise RuntimeError("repr fails")


class _BadStr:
    def __str__(self) -> str:
        raise RuntimeError("str fails")


def _circular() -> list[object]:
    items: list[object] = []
    items.append(items)
    return items


@pytest.mark.parametrize(
    ("args", "extra", "expected"),
    [
        pytest.param((), {"o": _BadRepr()}, {"o": "<_BadRepr object: its repr failed>"}, id="repr"),
        pytest.param((), {"items": _circular()}, {"items": "[[...]]"}, id="circular"),
        pytest.param((), {"file": b"\xff\xfe"}, {"file": "b'\\xff\\xfe'"}, id="bytes"),
        pytest.param(
            (),
            {"ratio": float("nan"), "range": [1.5, float("inf"), -float("inf")]},
            {"ratio": "nan", "range": [1.5, "inf", "-inf"]},
            id="nan",
        ),
        pytest.param((_BadRepr(),), {}, {}, id="args"),
    ],
)
def test_a_value_that_is_not_json_is_written_as_text_and_the_log_goes_on(
    folder: Path,
    install: Install,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    args: tuple[object, ...],
    extra: dict[str, object],
    expected: dict[str, object],
) -> None:
    without_root_handlers(monkeypatch)
    app_log = install(folder, "info")
    log = logging.getLogger("reframe.test")
    log.info("odd %d" if args else "odd", *args, extra=extra)
    log.info("the next record")
    assert not app_log.broken
    app_log.close()
    odd, following = lines(folder)
    assert odd["message"].startswith("odd")
    assert {key: odd[key] for key in expected} == expected
    assert following["message"] == "the next record"
    assert capsys.readouterr().err == ""


def test_a_message_whose_str_raises_is_written_as_its_repr(
    folder: Path, install: Install, monkeypatch: pytest.MonkeyPatch
) -> None:
    without_root_handlers(monkeypatch)
    app_log = install(folder, "info")
    logging.getLogger("reframe.test").info(_BadStr())
    assert not app_log.broken
    app_log.close()
    [message] = messages(folder)
    assert re.fullmatch(r"<\S+\._BadStr object at 0x[0-9a-fA-F]+> \(\)", message)


def test_a_record_that_cannot_be_written_is_dropped_alone(
    folder: Path,
    install: Install,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_log = install(folder, "info")
    formatter = app_log._handler.formatter
    assert formatter is not None
    format_record = formatter.format

    def failing(record: logging.LogRecord) -> str:
        if record.msg == "cannot be formatted":
            raise ValueError("a formatter bug")
        return format_record(record)

    monkeypatch.setattr(formatter, "format", failing)
    log = logging.getLogger("reframe.test")
    log.info("cannot be formatted")
    log.info("the next record")
    assert not app_log.broken
    app_log.close()
    assert messages(folder) == ["the next record"]
    assert capsys.readouterr().err == ""


def test_the_file_rotates_at_its_size_and_keeps_three_old_files(
    folder: Path, install: Install
) -> None:
    app_log = install(folder, "info", max_bytes=2000)
    log = logging.getLogger("reframe.test")
    for n in range(200):
        log.info("record %03d %s", n, "x" * 60)
    app_log.close()

    names = sorted(path.name for path in folder.iterdir())
    assert names == ["reframe.log", "reframe.log.1", "reframe.log.2", "reframe.log.3"]
    assert all((folder / name).stat().st_size <= 2000 for name in names)
    assert messages(folder)[-1].startswith("record 199")


def _in_use(source: str, _dest: str) -> None:
    """``os.rename`` on Windows while another process has the file open."""
    raise PermissionError(13, "The process cannot access the file", source)


def test_a_rotation_that_fails_does_not_stop_the_log(
    folder: Path,
    install: Install,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_log = install(folder, "info", max_bytes=2000)
    monkeypatch.setattr(app_log._handler, "rotate", _in_use)
    log = logging.getLogger("reframe.test")
    for n in range(100):
        log.info("record %03d %s", n, "x" * 60)
    assert not app_log.broken
    app_log.close()
    assert messages(folder) == [f"record {n:03d} {'x' * 60}" for n in range(100)]
    err = capsys.readouterr().err.splitlines()
    assert len(err) == 1
    assert "cannot be rotated" in err[0]


def test_a_rotation_tried_again_keeps_every_old_file(
    folder: Path, install: Install, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The renames of the old files succeed and the one of reframe.log fails: the next try
    must not move the old files again, which would delete one each time."""
    app_log = install(folder, "info", max_bytes=2000)
    handler = app_log._handler
    log = logging.getLogger("reframe.test")
    n = 0

    def write_until(done: Callable[[], bool]) -> None:
        nonlocal n
        while not done():
            log.info("record %04d %s", n, "x" * 60)
            n += 1

    write_until(lambda: (folder / "reframe.log.3").exists())
    rename = handler.rotate

    def base_in_use(source: str, dest: str) -> None:
        (_in_use if source == handler.baseFilename else rename)(source, dest)

    monkeypatch.setattr(handler, "rotate", base_in_use)
    write_until(lambda: (folder / "reframe.log").stat().st_size > 6000)  # tried many times
    monkeypatch.setattr(handler, "rotate", rename)
    write_until(lambda: (folder / "reframe.log").stat().st_size < 6000)
    app_log.close()
    kept = [
        int(line["message"].split()[1])
        for name in ("reframe.log.3", "reframe.log.2", "reframe.log.1", "reframe.log")
        for line in lines(folder, name)
    ]
    assert kept == list(range(kept[0], n))
    assert all(lines(folder, f"reframe.log.{k}") for k in (1, 2, 3))


def test_the_defaults_are_five_mib_and_three_old_files(folder: Path, install: Install) -> None:
    app_log = install(folder, "info")
    assert (app_log.max_bytes, app_log.backup_count) == (5 * 1024 * 1024, 3)


def test_the_level_filters_reframe_records_and_a_change_applies_at_once(
    folder: Path, install: Install
) -> None:
    app_log = install(folder, "warning")
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
    folder: Path, install: Install, library: logging.Logger
) -> None:
    app_log = install(folder, "debug")
    library.debug("library debug")
    library.info("library info")
    library.warning("library warning")
    logging.getLogger("reframe_server.test").debug("server debug")
    app_log.close()
    assert messages(folder) == ["library warning", "server debug"]


@pytest.mark.usefixtures("known_levels")
def test_the_access_log_is_never_written(folder: Path, install: Install) -> None:
    app_log = install(folder, "debug")
    logging.getLogger("uvicorn.access").warning('127.0.0.1 - "GET /api/fs?path=/x" 200')
    logging.getLogger("uvicorn.error").info("Application startup complete.")
    app_log.close()
    assert messages(folder) == ["Application startup complete."]


@pytest.mark.usefixtures("known_levels")
def test_at_debug_uvicorn_stays_at_info_and_its_debug_records_are_not_written(
    folder: Path, install: Install
) -> None:
    """The WebSocket library logs every upgrade header and short frame to uvicorn's logger at
    DEBUG: the session cookie and the auth message's token."""
    server = logging.getLogger("uvicorn.error")
    app_log = install(folder, "debug")
    assert server.level == logging.INFO
    server.setLevel(logging.DEBUG)  # lowered by someone else: the file still takes INFO up
    server.debug('< TEXT \'{"type":"auth","token":"..."}\'')
    server.info("connection open")
    logging.getLogger("uvicorn.error.websockets").debug("> Cookie: reframe_session=...")
    app_log.close()
    assert messages(folder) == ["connection open"]


def test_close_removes_every_handler_and_puts_the_levels_back(
    folder: Path, install: Install, known_levels: dict[str, int]
) -> None:
    names = ["", *known_levels]
    handlers = {name: logging.getLogger(name).handlers[:] for name in names}
    app_log = install(folder, "debug")
    assert levels_of(applog.OWN_LOGGERS) == dict.fromkeys(applog.OWN_LOGGERS, logging.DEBUG)
    app_log.close()
    app_log.set_level("debug")  # after close: nothing changes
    logging.getLogger("reframe.test").error("after close")
    assert levels_of(known_levels) == known_levels
    assert {name: logging.getLogger(name).handlers[:] for name in names} == handlers
    assert "after close" not in messages(folder)


def test_app_logs_closed_in_any_order_put_everything_back(
    tmp_path: Path,
    install: Install,
    known_levels: dict[str, int],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    without_root_handlers(monkeypatch)
    first = install(tmp_path / "first", "debug")
    second = install(tmp_path / "second", "info")
    first.close()
    log = logging.getLogger("reframe.test")
    assert log.getEffectiveLevel() == logging.INFO
    log.warning("while the second runs")
    assert "while the second runs" in capsys.readouterr().err
    second.close()
    assert levels_of(known_levels) == known_levels
    assert logging.getLogger().handlers == []


def test_stderr_shows_what_it_showed_without_the_log(
    folder: Path,
    install: Install,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The server's stderr (the desktop's sidecar.log, a CLI-started server's server.log)
    keeps the WARNING lines Python prints when nothing is configured."""
    without_root_handlers(monkeypatch)
    app_log = install(folder, "debug")
    log = logging.getLogger("reframe.test")
    log.debug("debug for the file only")
    log.warning("a warning for both")
    app_log.close()
    err = capsys.readouterr().err
    assert "a warning for both" in err
    assert "debug for the file only" not in err
    assert messages(folder) == ["debug for the file only", "a warning for both"]


def test_stderr_keeps_the_warnings_when_the_file_takes_errors_only(
    folder: Path,
    install: Install,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    without_root_handlers(monkeypatch)
    app_log = install(folder, "error")
    logging.getLogger("reframe.test").warning("a warning for stderr")
    app_log.close()
    assert "a warning for stderr" in capsys.readouterr().err
    assert messages(folder) == []


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
    folder: Path, install: Install, capsys: pytest.CaptureFixture[str]
) -> None:
    app_log = install(folder, "info")
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
