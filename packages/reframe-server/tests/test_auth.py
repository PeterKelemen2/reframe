"""Password mode: login, the session cookie, logout, the rate limit, ``PUT /api/auth/password``,
``reframe-server --set-password`` and ``auth.json``, which the settings never touch."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import stat
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import Depends, FastAPI, WebSocket

from reframe_server import login, security
from reframe_server.__main__ import main
from reframe_server.api import api_router
from reframe_server.config import ServerConfig
from reframe_testing.server import Api, ApiFactory, receive_json

pytestmark = pytest.mark.anyio

PASSWORD = "correct horse battery"
NEW_PASSWORD = "staple tray lamp"
LOGIN = "/api/auth/login"


def _mount_probe_routes(app: FastAPI) -> None:
    router = api_router("probe")

    @router.get("/private", dependencies=[Depends(security.require_auth)])
    async def private() -> dict[str, bool]:
        return {"ok": True}

    @router.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket.accept()
        message = await websocket.receive_json()
        config: ServerConfig = websocket.app.state.config
        allowed = security.ws_authenticated(config, websocket, message.get("token"))
        await websocket.send_json({"authenticated": allowed})
        await websocket.close()

    app.include_router(router, prefix="/api/t")


@pytest.fixture
def cheap_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(login, "SCRYPT_N", 2**10)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """The sessions' and the rate limit's monotonic clock; move it by changing ``[0]``."""
    now = [1000.0]
    monkeypatch.setattr(login, "_clock", lambda: now[0])
    return now


@pytest.fixture
def auth_file(tmp_path: Path) -> Path:
    return tmp_path / "config" / login.AUTH_FILE


@pytest.fixture
async def password_api(
    make_api: ApiFactory, cheap_hash: None, auth_file: Path
) -> AsyncIterator[Api]:
    assert login.save_password(auth_file, PASSWORD) is None
    async with make_api(auth="password") as api:
        _mount_probe_routes(api.app)
        yield api


@asynccontextmanager
async def _browser(
    api: Api, address: str = "127.0.0.1", base_url: str = "http://127.0.0.1"
) -> AsyncIterator[httpx.AsyncClient]:
    """A client of its own address that keeps its cookies, as a browser does."""
    transport = httpx.ASGITransport(app=api.app, client=(address, 50000))
    async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
        yield client


async def _login(client: httpx.AsyncClient, password: str = PASSWORD) -> httpx.Response:
    return await client.post(LOGIN, json={"password": password})


async def test_login_sets_a_strict_http_only_session_cookie(password_api: Api) -> None:
    async with _browser(password_api) as browser:
        refused = await browser.get("/api/t/private")
        assert (refused.status_code, refused.json()["code"]) == (401, "auth.required")
        response = await _login(browser)
        assert response.json() == {"mode": "password", "authenticated": True}
        cookie = response.headers["set-cookie"].lower()
        assert cookie.startswith(f"{security.SESSION_COOKIE}=")
        for attribute in ("httponly", "samesite=strict", "path=/api"):
            assert attribute in cookie
        assert "secure" not in cookie
        assert (await browser.get("/api/t/private")).json() == {"ok": True}
        assert (await browser.get("/api/auth/status")).json()["authenticated"] is True


async def test_the_session_cookie_is_secure_over_https(password_api: Api) -> None:
    async with _browser(password_api, base_url="https://127.0.0.1") as browser:
        response = await _login(browser)
    assert "secure" in response.headers["set-cookie"].lower()


async def test_a_wrong_password_gets_no_session(password_api: Api) -> None:
    response = await _login(password_api.anonymous, "wrong password")
    assert (response.status_code, response.json()["code"]) == (401, "auth.invalid")
    assert "set-cookie" not in response.headers


async def test_a_made_up_session_cookie_is_refused(password_api: Api) -> None:
    async with _browser(password_api) as browser:
        browser.cookies.set(security.SESSION_COOKIE, "made-up")
        response = await browser.get("/api/t/private")
    assert (response.status_code, response.json()["code"]) == (401, "auth.invalid")


async def test_logout_ends_the_session_on_the_server(password_api: Api) -> None:
    async with _browser(password_api) as browser:
        session = (await _login(browser)).cookies[security.SESSION_COOKIE]
        response = await browser.post("/api/auth/logout")
        assert response.json() == {"mode": "password", "authenticated": False}
        assert 'reframe_session=""' in response.headers["set-cookie"]
    async with _browser(password_api) as replay:
        replay.cookies.set(security.SESSION_COOKIE, session)
        assert (await replay.get("/api/t/private")).status_code == 401


async def test_logout_without_a_session_is_harmless(password_api: Api) -> None:
    response = await password_api.anonymous.post("/api/auth/logout")
    assert response.json() == {"mode": "password", "authenticated": False}


async def test_the_oldest_session_ends_when_there_are_too_many(
    password_api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(login, "MAX_SESSIONS", 2)
    async with (
        _browser(password_api) as first,
        _browser(password_api) as second,
        _browser(password_api) as third,
    ):
        browsers = (first, second, third)
        for browser in browsers:
            await _login(browser)
        statuses = [(await browser.get("/api/t/private")).status_code for browser in browsers]
    assert statuses == [401, 200, 200]


async def test_a_session_ends_after_its_lifetime(password_api: Api, clock: list[float]) -> None:
    async with _browser(password_api) as browser:
        await _login(browser)
        clock[0] += login.SESSION_TTL - 1
        assert (await browser.get("/api/t/private")).status_code == 200
        clock[0] += 1
        assert (await browser.get("/api/t/private")).status_code == 401


async def test_login_needs_password_mode(api: Api) -> None:
    response = await _login(api.anonymous)
    assert (response.status_code, response.json()["code"]) == (409, "auth.not_password_mode")


@pytest.mark.parametrize(
    ("first", "second", "shared"),
    [
        ("10.0.0.1", "10.0.0.2", False),
        ("2001:db8::1", "2001:db8::2", True),
        ("::ffff:10.0.0.1", "::ffff:10.0.0.2", False),
        ("unix-socket", "unix-socket", True),
    ],
)
async def test_wrong_passwords_are_rate_limited_per_client(
    password_api: Api, clock: list[float], first: str, second: str, shared: bool
) -> None:
    """A client may pick any address of its IPv6 /64, but IPv4 clients behind a dual-stack
    socket are still told apart."""
    async with _browser(password_api, first) as guesser, _browser(password_api, second) as other:
        for _ in range(login.LOGIN_ATTEMPTS):
            assert (await _login(guesser, "wrong password")).status_code == 401
        limited = await _login(guesser)
        assert (limited.status_code, limited.json()["code"]) == (429, "auth.rate_limited")
        assert limited.headers["retry-after"] == "60"
        assert (await _login(other)).status_code == (429 if shared else 200)
        clock[0] += login.LOGIN_WINDOW
        assert (await _login(guesser)).status_code == 200


async def test_a_right_password_clears_the_failures(password_api: Api) -> None:
    async with _browser(password_api) as browser:
        for _ in range(2):
            for _ in range(login.LOGIN_ATTEMPTS - 1):
                await _login(browser, "wrong password")
            assert (await _login(browser)).status_code == 200


async def test_the_rate_limit_forgets_the_least_recent_client_first(
    password_api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guesses from ever new addresses cannot grow the server's memory without bound."""
    monkeypatch.setattr(login, "MAX_CLIENTS", 2)
    async with (
        _browser(password_api, "10.0.0.1") as first,
        _browser(password_api, "10.0.0.2") as second,
        _browser(password_api, "10.0.0.3") as third,
    ):
        for _ in range(login.LOGIN_ATTEMPTS):
            await _login(first, "wrong password")
        assert (await _login(first)).status_code == 429
        await _login(second, "wrong password")
        await _login(third, "wrong password")
        assert (await _login(first)).status_code == 200


async def test_parallel_guesses_cannot_pass_the_limit(password_api: Api) -> None:
    async with _browser(password_api) as browser:
        answers = await asyncio.gather(*(_login(browser, "wrong") for _ in range(12)))
    statuses = sorted(answer.status_code for answer in answers)
    assert statuses == [401] * login.LOGIN_ATTEMPTS + [429] * (12 - login.LOGIN_ATTEMPTS)


@pytest.mark.parametrize(
    ("content", "warned", "detail"),
    [
        (None, True, "--set-password"),
        ('{"schema_version": 1}', True, "--set-password"),
        ("not json", True, "not valid JSON"),
        (
            '{"password": {"algorithm": "scrypt", "n": 3, "r": 8, "p": 1, "salt": "AAAA",'
            ' "hash": "AAAA"}}',
            False,
            "the hash is damaged",
        ),
    ],
)
async def test_without_a_usable_password_login_is_unavailable(
    make_api: ApiFactory,
    auth_file: Path,
    caplog: pytest.LogCaptureFixture,
    content: str | None,
    warned: bool,
    detail: str,
) -> None:
    if content is not None:
        await asyncio.to_thread(auth_file.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(auth_file.write_text, content, encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="reframe_server.security"):
        async with make_api(auth="password") as api:
            response = await _login(api.anonymous)
    assert (response.status_code, response.json()["code"]) == (503, "auth.no_password")
    assert detail in response.json()["detail"]
    assert ("password login is not possible" in caplog.text) is warned


async def test_changing_the_password(password_api: Api, auth_file: Path) -> None:
    document = json.loads(await asyncio.to_thread(auth_file.read_bytes))
    document["from_a_newer_version"] = 1
    await asyncio.to_thread(auth_file.write_text, json.dumps(document), encoding="utf-8")
    async with _browser(password_api) as browser, _browser(password_api) as elsewhere:
        await _login(browser)
        await _login(elsewhere)
        response = await browser.put(
            "/api/auth/password", json={"current": PASSWORD, "new": NEW_PASSWORD}
        )
        assert response.json() == {"mode": "password", "authenticated": True}
        assert (await browser.get("/api/t/private")).status_code == 200
        assert (await elsewhere.get("/api/t/private")).status_code == 401
        assert (await _login(elsewhere, PASSWORD)).status_code == 401
        assert (await _login(elsewhere, NEW_PASSWORD)).status_code == 200
    assert json.loads(await asyncio.to_thread(auth_file.read_bytes))["from_a_newer_version"] == 1
    assert await asyncio.to_thread(lambda: sorted(p.name for p in auth_file.parent.iterdir())) == [
        login.AUTH_FILE,
        "settings.json",
    ]
    if sys.platform != "win32":
        assert stat.S_IMODE((await asyncio.to_thread(auth_file.stat)).st_mode) == 0o600


@pytest.mark.parametrize(
    ("client", "body", "status", "code"),
    [
        ("token", {"current": "wrong password", "new": NEW_PASSWORD}, 403, "auth.wrong_password"),
        ("token", {"current": PASSWORD, "new": "short"}, 422, "auth.weak_password"),
        ("anonymous", {"current": PASSWORD, "new": NEW_PASSWORD}, 401, "auth.required"),
    ],
)
async def test_a_refused_password_change_changes_nothing(
    password_api: Api, auth_file: Path, client: str, body: dict[str, str], status: int, code: str
) -> None:
    before = await asyncio.to_thread(auth_file.read_bytes)
    caller = password_api.client if client == "token" else password_api.anonymous
    response = await caller.put("/api/auth/password", json=body)
    assert (response.status_code, response.json()["code"]) == (status, code)
    assert await asyncio.to_thread(auth_file.read_bytes) == before


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="POSIX permissions")
async def test_a_password_that_cannot_be_saved(password_api: Api, auth_file: Path) -> None:
    await asyncio.to_thread(auth_file.parent.chmod, 0o500)
    try:
        response = await password_api.client.put(
            "/api/auth/password", json={"current": PASSWORD, "new": NEW_PASSWORD}
        )
    finally:
        await asyncio.to_thread(auth_file.parent.chmod, 0o700)
    assert (response.status_code, response.json()["code"]) == (500, "auth.not_saved")
    assert (await _login(password_api.anonymous)).status_code == 200


async def test_a_password_matches_in_either_unicode_form(password_api: Api) -> None:
    decomposed, composed = "jalapeño pepper", "jalapeño pepper"
    response = await password_api.client.put(
        "/api/auth/password", json={"current": PASSWORD, "new": decomposed}
    )
    assert response.status_code == 200
    assert "set-cookie" not in response.headers, "a token caller gets no session"
    assert (await _login(password_api.anonymous, composed)).status_code == 200


@pytest.mark.parametrize(("cookie", "authenticated"), [(True, True), (False, False)])
async def test_the_websocket_accepts_the_session_cookie(
    password_api: Api, cookie: bool, authenticated: bool
) -> None:
    session = (await _login(password_api.anonymous)).cookies[security.SESSION_COOKIE]
    headers = {"Cookie": f"{security.SESSION_COOKIE}={session}"} if cookie else {}
    async with (
        password_api.live() as server,
        server.connect("/api/t/ws", additional_headers=headers) as connection,
    ):
        await connection.send('{"token": null}')
        assert await receive_json(connection) == {"authenticated": authenticated}


async def test_the_auth_routes_have_stable_operation_ids(password_api: Api) -> None:
    schema = (await password_api.client.get("/api/openapi.json")).json()
    found = {
        (path, method): operation["operationId"]
        for path, item in schema["paths"].items()
        if path.startswith("/api/auth/")
        for method, operation in item.items()
    }
    assert found == {
        ("/api/auth/status", "get"): "auth_status",
        ("/api/auth/login", "post"): "auth_login",
        ("/api/auth/logout", "post"): "auth_logout",
        ("/api/auth/password", "put"): "auth_change_password",
    }


def _secrets(api: Api, auth_file: Path) -> list[str]:
    entry = json.loads(auth_file.read_text(encoding="utf-8"))["password"]
    return [api.token, PASSWORD, entry["hash"], entry["salt"]]


PATCH: list[dict[str, Any]] = [
    {"op": "add", "path": "/password", "value": NEW_PASSWORD},
    {"op": "add", "path": "/auth", "value": {"password": NEW_PASSWORD, "mode": "none"}},
]
"""A settings patch that tries to set a password."""


async def test_the_settings_hold_no_secret(password_api: Api, auth_file: Path) -> None:
    update = await password_api.reframe.settings.update(
        [{"op": "replace", "path": "/preview/sample_frames", "value": 12}]
    )
    assert update.saved
    stored = await asyncio.to_thread(password_api.reframe.settings.path.read_text, "utf-8")
    current = password_api.reframe.settings.get().model_dump_json()
    for secret in _secrets(password_api, auth_file):
        assert secret not in stored
        assert secret not in current


async def test_a_settings_patch_cannot_change_the_password(
    password_api: Api, auth_file: Path
) -> None:
    before = await asyncio.to_thread(auth_file.read_bytes)
    assert (await password_api.reframe.settings.update(PATCH)).ok
    assert await asyncio.to_thread(auth_file.read_bytes) == before
    assert (await _login(password_api.anonymous, NEW_PASSWORD)).status_code == 401
    assert (await _login(password_api.anonymous, PASSWORD)).status_code == 200


async def test_get_settings_holds_no_secret(password_api: Api, auth_file: Path) -> None:
    response = await password_api.client.get("/api/settings")
    assert response.status_code == 200
    for secret in _secrets(password_api, auth_file):
        assert secret not in response.text


async def test_put_settings_cannot_change_the_password(password_api: Api, auth_file: Path) -> None:
    before = await asyncio.to_thread(auth_file.read_bytes)
    await password_api.client.put("/api/settings", json=PATCH)
    assert await asyncio.to_thread(auth_file.read_bytes) == before
    assert (await _login(password_api.anonymous, NEW_PASSWORD)).status_code == 401
    assert (await _login(password_api.anonymous, PASSWORD)).status_code == 200
    response = await password_api.client.get("/api/settings")
    for secret in _secrets(password_api, auth_file):
        assert secret not in response.text


async def test_set_password_from_a_pipe(
    make_api: ApiFactory, auth_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole path with the real scrypt cost: the option, the file and a login."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(f"{PASSWORD}\n"))
    assert main(["--set-password"]) == 0
    if sys.platform != "win32":
        assert stat.S_IMODE((await asyncio.to_thread(auth_file.stat)).st_mode) == 0o600
    async with make_api(auth="password") as api:
        assert (await _login(api.anonymous)).status_code == 200


class _Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.mark.parametrize(
    ("answers", "code"),
    [
        ([PASSWORD, PASSWORD], 0),
        ([PASSWORD, NEW_PASSWORD], 1),
        (["short", "short"], 1),
        (KeyboardInterrupt, 130),
        (EOFError, 1),
    ],
)
def test_set_password_on_a_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cheap_hash: None,
    answers: list[str] | type[BaseException],
    code: int,
) -> None:
    def ask(prompt: str) -> str:
        if isinstance(answers, list):
            return answers.pop(0)
        raise answers

    monkeypatch.setattr(sys, "stdin", _Terminal())
    monkeypatch.setattr("getpass.getpass", ask)
    config = ServerConfig(auth="password", config_dir=tmp_path)
    assert security.set_password_interactive(config) == code
    assert (tmp_path / login.AUTH_FILE).exists() is (code == 0)


def test_set_password_that_cannot_be_saved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cheap_hash: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    not_a_folder = tmp_path / "file"
    not_a_folder.write_text("x", encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", io.StringIO(f"{PASSWORD}\n"))
    config = ServerConfig(auth="password", config_dir=not_a_folder)
    assert security.set_password_interactive(config) == 1
    assert "was not saved" in capsys.readouterr().err
