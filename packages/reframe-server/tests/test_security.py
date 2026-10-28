"""Who may call the server: the run's token, the ``Host`` and ``Origin`` checks, CORS, the
security headers and signed media URLs."""

from __future__ import annotations

import json
import logging
import re
import socket
from collections.abc import AsyncIterator
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi import Depends, FastAPI, WebSocket
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from reframe_server import security
from reframe_server.api import api_router
from reframe_server.config import AuthMode, ServerConfig, ServerMode
from reframe_testing.server import Api, ApiFactory, receive_json

pytestmark = pytest.mark.anyio


def mount_probe_routes(app: FastAPI) -> None:
    """Routes guarded the way the real routers are, so these tests do not depend on them."""
    router = api_router("probe")

    @router.get("/private", dependencies=[Depends(security.require_auth)])
    async def private() -> dict[str, bool]:
        return {"ok": True}

    @router.get("/media/{name}", dependencies=[Depends(security.require_media_access)])
    async def media(name: str) -> dict[str, str]:
        return {"name": name}

    @router.post("/private", dependencies=[Depends(security.require_auth)])
    async def private_change(body: dict[str, int]) -> dict[str, int]:
        return body

    @router.api_route("/change", methods=["POST", "PUT", "PATCH", "DELETE"])
    async def change() -> dict[str, bool]:
        return {"changed": True}

    @router.get("/fail")
    async def fail() -> None:
        raise RuntimeError("a bug")

    @router.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket.accept()
        message = await websocket.receive_json()
        config: ServerConfig = websocket.app.state.config
        allowed = security.ws_authenticated(config, websocket, message.get("token"))
        await websocket.send_json({"authenticated": allowed})
        await websocket.close()

    app.include_router(router, prefix="/t")


@pytest.fixture
def guarded(api: Api) -> Api:
    mount_probe_routes(api.app)
    return api


async def _upgrade(uri: str, **kwargs: Any) -> int:
    """The HTTP status of a WebSocket upgrade to the probe route (101: it opened)."""
    try:
        async with connect(uri, open_timeout=10, **kwargs) as connection:
            await connection.send('{"token": null}')
            await receive_json(connection)
    except InvalidStatus as exc:
        return exc.response.status_code
    return 101


@pytest.mark.parametrize(
    ("authorization", "code"),
    [
        (None, "auth.required"),
        (b"Bearer wrong", "auth.invalid"),
        ("Bearer tést".encode(), "auth.invalid"),
    ],
)
async def test_a_missing_or_wrong_token_is_refused(
    guarded: Api, authorization: bytes | None, code: str
) -> None:
    headers = {} if authorization is None else {b"Authorization": authorization}
    response = await guarded.anonymous.get("/t/private", headers=headers)
    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == code
    assert response.headers["www-authenticate"].startswith("Bearer")


async def test_the_runs_token_is_accepted_in_password_mode(make_api: ApiFactory) -> None:
    async with make_api(auth="password") as api:
        mount_probe_routes(api.app)
        assert (await api.client.get("/t/private")).json() == {"ok": True}


async def test_auth_none_lets_local_callers_in_and_warns_at_start(
    make_api: ApiFactory, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="reframe_server.security"):
        async with make_api(auth="none") as api:
            mount_probe_routes(api.app)
            assert (await api.anonymous.get("/t/private")).status_code == 200
    assert "authentication is off" in caplog.text


async def test_a_foreign_host_is_refused(guarded: Api) -> None:
    """A DNS rebinding page reaches the server under its own name: the token does not help."""
    for client in (guarded.anonymous, guarded.client):
        response = await client.get("/t/private", headers={"Host": "evil.example:8080"})
        assert response.status_code == 400
        assert response.json()["code"] == "request.host"
    async with guarded.live() as server:
        uri = f"ws://evil.example:{server.port}/t/ws"
        assert await _upgrade(uri, host="127.0.0.1", port=server.port) == 403


@pytest.mark.parametrize(
    ("host", "allowed_hosts", "header", "accepted"),
    [
        ("127.0.0.1", None, "localhost:8080", True),
        ("127.0.0.1", None, "[::1]:9", True),
        ("127.0.0.1", None, "nas.example", False),
        ("127.0.0.1", None, None, False),
        ("127.0.0.1", ["NAS.example."], "nas.EXAMPLE:443", True),
        ("192.168.1.10", None, "192.168.1.10:8080", True),
        ("192.168.1.10", None, "reframe-box:8080", True),
        ("192.168.1.10", None, "10.0.0.1", False),
        ("192.168.1.10", ["nas.example"], "192.168.1.10", False),
        ("0.0.0.0", None, "10.0.0.1:8080", True),
        ("0.0.0.0", None, "evil.example", False),
    ],
)
def test_check_host(
    monkeypatch: pytest.MonkeyPatch,
    host: str,
    allowed_hosts: list[str] | None,
    header: str | None,
    accepted: bool,
) -> None:
    monkeypatch.setattr(socket, "gethostname", lambda: "reframe-box.lan")
    config = ServerConfig(host=host, auth="token", allowed_hosts=allowed_hosts)
    assert security.check_host(config, header) is accepted


@pytest.mark.parametrize(
    ("origin", "status"), [("https://Reframe.example.com", 200), ("null", 403)]
)
async def test_a_page_of_an_allowed_host_behind_a_proxy(
    make_api: ApiFactory, origin: str, status: int
) -> None:
    """The proxy sends its own ``Host`` (loopback); the browser's ``Origin`` is the public name."""
    async with make_api(allowed_hosts=["reframe.example.com"]) as api:
        mount_probe_routes(api.app)
        response = await api.anonymous.post("/t/change", headers={"Origin": origin})
    assert response.status_code == status


@pytest.mark.parametrize(
    ("method", "origin", "status"),
    [
        ("POST", "http://evil.example", 403),
        ("PUT", "http://evil.example", 403),
        ("PATCH", "http://evil.example", 403),
        ("DELETE", "http://evil.example", 403),
        ("POST", "http://127.0.0.1", 200),
        ("GET", "http://evil.example", 200),
    ],
)
async def test_a_state_change_from_another_sites_page_is_refused(
    guarded: Api, method: str, origin: str, status: int
) -> None:
    """With ``auth none`` or a session cookie, a page elsewhere could send a form here."""
    path = "/api/health" if method == "GET" else "/t/change"
    response = await guarded.anonymous.request(method, path, headers={"Origin": origin})
    assert response.status_code == status
    if status == 403:
        assert response.json()["code"] == "request.origin"


@pytest.mark.parametrize(
    ("origin", "opens"),
    [("http://evil.example", False), (None, True), ("own", True), ("http://tauri.localhost", True)],
)
async def test_a_websocket_from_another_origin_is_refused(
    guarded: Api, origin: str | None, opens: bool
) -> None:
    async with guarded.live() as server:
        headers = (
            {} if origin is None else {"Origin": server.http_url if origin == "own" else origin}
        )
        uri = f"ws://127.0.0.1:{server.port}/t/ws"
        assert await _upgrade(uri, additional_headers=headers) == (101 if opens else 403)


@pytest.mark.parametrize(
    ("mode", "cors_origins", "origin", "allowed"),
    [
        ("desktop", [], "tauri://localhost", True),
        ("desktop", [], "http://evil.example", False),
        ("web", [], "tauri://localhost", False),
        ("web", ["http://localhost:5173"], "http://localhost:5173", True),
    ],
)
async def test_cors(
    make_api: ApiFactory, mode: ServerMode, cors_origins: list[str], origin: str, allowed: bool
) -> None:
    async with make_api(mode=mode, cors_origins=cors_origins) as api:
        response = await api.anonymous.options(
            "/api/health",
            headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
        )
    assert (response.headers.get("access-control-allow-origin") == origin) is allowed


async def test_every_answer_carries_the_security_headers(guarded: Api) -> None:
    transport = httpx.ASGITransport(app=guarded.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as plain:
        answers = [
            await plain.get("/api/health"),
            await plain.get("/t/private"),
            await plain.get("/api/health", headers={"Host": "evil.example"}),
            await plain.get("/t/fail"),
        ]
    assert [answer.status_code for answer in answers] == [200, 401, 400, 500]
    for answer in answers:
        assert answer.headers["x-content-type-options"] == "nosniff"
        assert "frame-ancestors 'none'" in answer.headers["content-security-policy"]
        assert "script-src 'self';" in answer.headers["content-security-policy"]


class _PageSources(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.needs: list[tuple[str, str]] = []
        self._inline = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script":
            source = values.get("src")
            self.needs.append(("script-src", _origin(source) if source else "'unsafe-inline'"))
        elif tag == "link" and values.get("href"):
            directive = "style-src" if values.get("rel") == "stylesheet" else "img-src"
            self.needs.append((directive, _origin(values["href"] or "")))


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}" if parts.netloc else "'self'"


async def test_the_docs_page_may_load_what_it_needs(guarded: Api) -> None:
    """Swagger UI comes from a CDN and starts with an inline script."""
    response = await guarded.anonymous.get("/api/docs")
    policy: dict[str, list[str]] = {}
    for directive in response.headers["content-security-policy"].split(";"):
        name, *sources = directive.split()
        policy[name] = sources
    page = _PageSources()
    page.feed(response.text)
    assert page.needs
    for directive, source in page.needs:
        assert source in policy[directive], (directive, source)
    assert policy["frame-ancestors"] == ["'none'"]


async def test_a_signed_media_url_needs_no_other_credentials(guarded: Api) -> None:
    url = security.sign_media_url(guarded.config, "/t/media/frame.png")
    assert (await guarded.anonymous.get(url)).json() == {"name": "frame.png"}
    assert (await guarded.client.get("/t/media/frame.png")).status_code == 200


def _tamper(url: str, case: str) -> str:
    path, _, query = url.partition("?")
    exp = re.search(r"exp=(\d+)", query)
    sig = re.search(r"sig=([^&]+)", query)
    assert exp is not None
    assert sig is not None
    return {
        "another path": f"/t/media/other.png?{query}",
        "later expiry": f"{path}?exp={int(exp[1]) + 3600}&sig={sig[1]}",
        "no expiry": f"{path}?sig={sig[1]}",
        "expiry not a number": f"{path}?exp=soon&sig={sig[1]}",
        "no signature": path,
    }[case]


@pytest.mark.parametrize(
    "case", ["another path", "later expiry", "no expiry", "expiry not a number", "no signature"]
)
async def test_a_tampered_media_url_is_refused(guarded: Api, case: str) -> None:
    url = _tamper(security.sign_media_url(guarded.config, "/t/media/frame.png"), case)
    response = await guarded.anonymous.get(url)
    assert response.status_code == 401
    expected = "auth.required" if case == "no signature" else "auth.invalid"
    assert response.json()["code"] == expected


async def test_an_expired_media_url_is_refused(guarded: Api) -> None:
    url = security.sign_media_url(guarded.config, "/t/media/frame.png", ttl=-1)
    assert (await guarded.anonymous.get(url)).status_code == 401


def test_a_media_url_of_another_run_is_refused() -> None:
    """A restarted server has a new token, so the URLs it gave out before stop working."""
    first, second = ServerConfig(auth="token"), ServerConfig(auth="token")
    url = security.sign_media_url(first, "/api/preview/frames/a.png")
    exp = re.search(r"exp=(\d+)", url)
    sig = re.search(r"sig=([^&]+)", url)
    assert exp is not None
    assert sig is not None
    assert security.verify_media_sig(first, "/api/preview/frames/a.png", exp[1], sig[1])
    assert not security.verify_media_sig(second, "/api/preview/frames/a.png", exp[1], sig[1])


async def _chunks(sent: list[bytes]) -> AsyncIterator[bytes]:
    for chunk in (b'{"a": ', b"1}"):
        sent.append(chunk)
        yield chunk


@pytest.mark.parametrize("framing", ["content-length", "chunked"])
async def test_a_body_without_credentials_is_refused_before_it_is_read(
    guarded: Api, framing: str
) -> None:
    """Else an anonymous client makes the server read and parse any body it sends."""
    sent: list[bytes] = []
    content = b"{not json" if framing == "content-length" else _chunks(sent)
    json_type = {"Content-Type": "application/json"}
    response = await guarded.anonymous.post("/t/private", content=content, headers=json_type)
    assert (response.status_code, response.json()["code"]) == (401, "auth.required")
    assert response.headers["www-authenticate"].startswith("Bearer")
    assert sent == []
    accepted = await guarded.client.post("/t/private", content=_chunks([]), headers=json_type)
    assert accepted.json() == {"a": 1}


@pytest.mark.parametrize(
    ("auth", "token", "authenticated"),
    [("token", "right", True), ("token", "wrong", False), ("none", None, True)],
)
async def test_the_websocket_token(
    make_api: ApiFactory, auth: AuthMode, token: str | None, authenticated: bool
) -> None:
    async with make_api(auth=auth) as api:
        mount_probe_routes(api.app)
        message: dict[str, Any] = {"token": api.token if token == "right" else token}
        async with api.live() as server, server.connect("/t/ws") as connection:
            await connection.send(json.dumps(message))
            assert await receive_json(connection) == {"authenticated": authenticated}
