"""The server's app log: written while the app runs, at the level of the setting, and gone
with the app."""

from __future__ import annotations

import json
import logging
import logging.config
import os
import secrets
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from websockets.sync.client import connect

from reframe import applog
from reframe.models import ServerEndpoint
from reframe.queue.lock import LOCK_FILE, StoreLock
from reframe.tools.discovery import ALLOW_SCRIPT_TOOLS_ENV
from reframe_server import login, owner, security
from reframe_server.__main__ import _log_config
from reframe_testing import fake_tools as ft
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
async def test_at_debug_uvicorn_is_written_from_info_up_and_its_access_log_never(
    make_api: ApiFactory, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """uvicorn hands its logger to the WebSocket library, which logs every upgrade header
    and short frame at DEBUG."""
    set_level(tmp_path, "debug")
    async with make_api():
        assert logging.getLogger("uvicorn.error").getEffectiveLevel() == logging.INFO
        logging.getLogger("uvicorn.error").debug('< TEXT \'{"type":"auth"}\'')
        logging.getLogger("uvicorn.error").info("uvicorn info")
        logging.getLogger("uvicorn.error").error("uvicorn error")
        logging.getLogger("uvicorn.access").info(
            '%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", "GET", "/api/x?sig=abc", "1.1", 200
        )
    assert messages(tmp_path)[-2:] == ["uvicorn info", "uvicorn error"]
    assert not any("TEXT" in message for message in messages(tmp_path))
    assert not any("GET /api/x" in message for message in messages(tmp_path))
    err = capsys.readouterr().err
    assert "uvicorn error" in err
    assert "TEXT" not in err


async def test_a_server_that_does_not_own_the_queue_writes_no_reframe_log(
    make_api: ApiFactory, tmp_path: Path
) -> None:
    """Two writers of one file push each other's records out, and on Windows the rename at
    rotation fails while the other has the file open."""
    lock = StoreLock(tmp_path / "data" / LOCK_FILE)
    assert lock.acquire().owned
    try:
        async with make_api() as api:
            assert api.app.state.app_log is None
            logging.getLogger("reframe.queue").error("from the second server")
        with pytest.raises(owner.StoreBusy):
            async with make_api(owner_only=True):
                pass
    finally:
        lock.release()
    assert not (tmp_path / "data" / "logs" / applog.LOG_FILE).exists()


async def test_the_app_log_takes_what_the_facade_logs_as_it_closes(
    make_api: ApiFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with make_api() as api:
        close = api.reframe.close

        async def close_and_log() -> None:
            await close()
            logging.getLogger("reframe.queue").warning("the last words of the facade")

        monkeypatch.setattr(api.reframe, "close", close_and_log)
    assert messages(tmp_path)[-1] == "the last words of the facade"


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


@pytest.fixture
def known_levels() -> Iterator[dict[str, int]]:
    """Levels that the app log does not set itself, whatever earlier tests left behind."""
    levels = {"reframe": logging.ERROR, "reframe_server": logging.NOTSET}
    before = {name: logging.getLogger(name).level for name in levels}
    for name, level in levels.items():
        logging.getLogger(name).setLevel(level)
    yield levels
    for name, level in before.items():
        logging.getLogger(name).setLevel(level)


async def test_no_handler_or_level_is_left_behind_when_the_app_stops(
    make_api: ApiFactory, tmp_path: Path, known_levels: dict[str, int]
) -> None:
    before = logging_state()
    set_level(tmp_path, "debug")
    async with make_api() as api:
        assert api.app.state.app_log is not None
        assert logging.getLogger("reframe").level == logging.DEBUG
    assert {name: logging.getLogger(name).level for name in known_levels} == known_levels
    assert logging_state() == before
    logging.getLogger("reframe.test").error("after the app stopped")
    assert "after the app stopped" not in messages(tmp_path)


def _wait_for_endpoint(path: Path, server: subprocess.Popen[str]) -> ServerEndpoint:
    deadline = time.monotonic() + 60
    while True:
        try:
            return ServerEndpoint.model_validate_json(path.read_bytes())
        except (FileNotFoundError, PermissionError, ValueError):
            pass
        assert server.poll() is None, f"the server exited with {server.returncode}"
        assert time.monotonic() < deadline, "no endpoint file in time"
        time.sleep(0.02)


@pytest.mark.slow
def test_at_debug_neither_the_token_nor_the_session_cookie_reaches_reframe_log(
    tmp_path: Path, fake_tools: ft.FakeTools
) -> None:
    """At ``debug`` the WebSocket library logs every upgrade header (the session cookie) and
    every short frame (the auth message with the token) to uvicorn's logger."""
    token = secrets.token_urlsafe(32)
    password = "correct horse battery staple"
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("REFRAME_") or name == ALLOW_SCRIPT_TOOLS_ENV
    }
    for name in ("config", "data", "cache"):
        env[f"REFRAME_{name.upper()}_DIR"] = str(tmp_path / name)
    env |= {
        "REFRAME_FFMPEG": str(fake_tools.ffmpeg),
        "REFRAME_FFPROBE": str(fake_tools.ffprobe),
        "REFRAME_TOKEN": token,
    }
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "settings.json").write_text(
        json.dumps(
            {
                "encoders": {"hardware_tests": False},
                "queue": {"sleep_inhibit": False},
                "diagnostics": {"log_level": "debug"},
            }
        ),
        encoding="utf-8",
    )
    assert login.save_password(login.auth_path(tmp_path / "config"), password) is None
    argv = [sys.executable, "-m", "reframe_server", "--port", "0", "--auth", "password"]
    server = subprocess.Popen(
        argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=env, text=True
    )
    try:
        endpoint = _wait_for_endpoint(tmp_path / "data" / owner.ENDPOINT_FILE, server)
        base_url = f"http://127.0.0.1:{endpoint.port}"
        session = httpx.post(f"{base_url}/api/auth/login", json={"password": password}, timeout=10)
        cookie = session.cookies[security.SESSION_COOKIE]
        settings = httpx.get(
            f"{base_url}/api/settings", cookies={security.SESSION_COOKIE: cookie}, timeout=10
        )
        assert settings.json()["diagnostics"]["log_level"] == "debug"
        with connect(
            f"ws://127.0.0.1:{endpoint.port}/api/events",
            additional_headers={"Cookie": f"{security.SESSION_COOKIE}={cookie}"},
            open_timeout=10,
        ) as events:
            events.send(json.dumps({"type": "auth", "token": token}, separators=(",", ":")))
            assert json.loads(events.recv(10))["type"] == "hello"
    finally:
        server.terminate()
        _out, err = server.communicate(timeout=30)
    log = (tmp_path / "data" / "logs" / applog.LOG_FILE).read_text(encoding="utf-8")
    assert "Application startup complete." in log
    secrets_in_log = {"token": token in log, "cookie": cookie in log}
    assert secrets_in_log == {"token": False, "cookie": False}
    assert token not in err
    assert cookie not in err
