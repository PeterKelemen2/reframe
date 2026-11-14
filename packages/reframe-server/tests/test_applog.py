"""The server's app log: written while the app runs, at the level of the setting, and gone
with the app."""

from __future__ import annotations

import json
import logging
import logging.config
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from reframe import applog
from reframe_server.__main__ import _log_config
from reframe_testing.server import ApiFactory

pytestmark = pytest.mark.anyio

LOGGERS = ("", "uvicorn", "uvicorn.error", "uvicorn.access", "reframe", "reframe_server")


def records(tmp_path: Path) -> list[dict[str, Any]]:
    path = tmp_path / "data" / "logs" / applog.LOG_FILE
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def messages(tmp_path: Path) -> list[str]:
    return [record["message"] for record in records(tmp_path)]


def logging_state() -> dict[str, tuple[int, list[logging.Handler], bool]]:
    return {
        name: (
            logging.getLogger(name).level,
            logging.getLogger(name).handlers[:],
            logging.getLogger(name).propagate,
        )
        for name in LOGGERS
    }


@pytest.fixture
def uvicorn_logging(capsys: pytest.CaptureFixture[str]) -> Iterator[None]:
    """uvicorn's log config as ``reframe-server`` applies it (its stderr is ``capsys``'s),
    undone after the test."""
    before = logging_state()
    logging.config.dictConfig(_log_config())
    yield
    for name, (level, handlers, propagate) in before.items():
        logger = logging.getLogger(name)
        for handler in logger.handlers:
            if handler not in handlers:
                handler.close()
        logger.setLevel(level)
        logger.handlers[:] = handlers
        logger.propagate = propagate


def set_level(tmp_path: Path, level: str) -> None:
    path = tmp_path / "config" / "settings.json"
    settings = json.loads(path.read_text(encoding="utf-8"))
    settings["diagnostics"] = {"log_level": level}
    path.write_text(json.dumps(settings), encoding="utf-8")


async def test_a_running_server_writes_reframe_log_as_json_lines(
    make_api: ApiFactory, tmp_path: Path
) -> None:
    async with make_api() as api:
        assert (await api.client.get("/api/system")).status_code == 200
        logging.getLogger("reframe.queue").info("job started", extra={"job_id": "j1"})
    record = records(tmp_path)[-1]
    assert (record["level"], record["logger"], record["message"], record["job_id"]) == (
        "info",
        "reframe.queue",
        "job started",
        "j1",
    )


async def test_the_level_of_the_settings_applies_at_start_and_a_change_at_once(
    make_api: ApiFactory, tmp_path: Path
) -> None:
    set_level(tmp_path, "warning")
    log = logging.getLogger("reframe.capabilities")
    async with make_api() as api:
        log.info("info at warning")
        patch = [{"op": "replace", "path": "/diagnostics/log_level", "value": "debug"}]
        assert (await api.client.put("/api/settings", json=patch)).status_code == 200
        log.debug("debug after the change")
    assert "info at warning" not in messages(tmp_path)
    assert "debug after the change" in messages(tmp_path)


@pytest.mark.usefixtures("uvicorn_logging")
async def test_uvicorn_errors_are_written_and_its_access_log_and_debug_on_stderr_are_not(
    make_api: ApiFactory, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    set_level(tmp_path, "debug")
    async with make_api():
        logging.getLogger("uvicorn.error").debug("uvicorn debug")
        logging.getLogger("uvicorn.error").error("uvicorn error")
        logging.getLogger("uvicorn.access").info(
            '%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", "GET", "/api/x?sig=abc", "1.1", 200
        )
    assert messages(tmp_path)[-2:] == ["uvicorn debug", "uvicorn error"]
    assert not any("GET /api/x" in message for message in messages(tmp_path))
    err = capsys.readouterr().err
    assert "uvicorn error" in err
    assert "uvicorn debug" not in err


async def test_a_log_that_cannot_be_written_does_not_stop_the_server(
    make_api: ApiFactory, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "data" / "logs" / applog.LOG_FILE).mkdir(parents=True)
    async with make_api() as api:
        assert api.app.state.app_log is None
        assert (await api.client.get("/api/system")).status_code == 200
        patch = [{"op": "replace", "path": "/diagnostics/log_level", "value": "debug"}]
        assert (await api.client.put("/api/settings", json=patch)).status_code == 200
    err = capsys.readouterr().err
    lines = [line for line in err.splitlines() if applog.LOG_FILE in line]
    assert len(lines) == 1
    assert "cannot be opened" in lines[0]
    assert "Traceback" not in err


async def test_no_handler_or_level_is_left_behind_when_the_app_stops(
    make_api: ApiFactory, tmp_path: Path
) -> None:
    before = logging_state()
    set_level(tmp_path, "debug")
    async with make_api() as api:
        assert api.app.state.app_log is not None
    assert logging_state() == before
    logging.getLogger("reframe.test").error("after the app stopped")
    assert "after the app stopped" not in messages(tmp_path)
