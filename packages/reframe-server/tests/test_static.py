"""The built frontend in web mode: cache headers, the SPA fallback, the 404 of ``/api`` and
the folder jail."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from starlette import responses
from websockets.exceptions import InvalidStatus

from reframe_server.security import APP_CSP
from reframe_testing.server import Api, ApiFactory

pytestmark = pytest.mark.anyio

INDEX = b'<!doctype html><script type="module" src="/assets/index-Ab12.js"></script>'
SCRIPT = b"console.log('reframe')"
SECRET = b"a file outside the frontend folder"


@pytest.fixture
def site(tmp_path: Path) -> Path:
    """A Vite-like build; ``outside/secret.txt`` beside it, reachable through two links."""
    folder = tmp_path / "site"
    (folder / "assets").mkdir(parents=True)
    (folder / "index.html").write_bytes(INDEX)
    (folder / "assets" / "index-Ab12.js").write_bytes(SCRIPT)
    (folder / "favicon.svg").write_bytes(b"<svg/>")
    secret = tmp_path / "outside" / "secret.txt"
    secret.parent.mkdir(exist_ok=True)
    secret.write_bytes(SECRET)
    (folder / "leak").symlink_to(secret)
    (folder / "assets" / "leak.js").symlink_to(secret)
    return folder


@pytest.fixture
async def web(make_api: ApiFactory, site: Path) -> AsyncIterator[Api]:
    async with make_api(static_dir=site) as api:
        yield api


def assert_problem_404(response: httpx.Response) -> None:
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "http.404"


async def test_hashed_asset_is_cached_for_good_without_credentials(web: Api) -> None:
    response = await web.anonymous.get("/assets/index-Ab12.js")
    assert response.status_code == 200
    assert response.content == SCRIPT
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


async def test_file_outside_assets_is_revalidated(web: Api) -> None:
    response = await web.anonymous.get("/favicon.svg")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/queue/42"), ("HEAD", "/queue/42"), ("GET", "/apiary")],
)
async def test_unknown_path_gets_index_html(web: Api, method: str, path: str) -> None:
    response = await web.anonymous.request(method, path)
    assert response.status_code == 200
    assert response.content == (INDEX if method == "GET" else b"")
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert response.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/nope"),
        ("GET", "/api"),
        ("POST", "/queue/42"),
        pytest.param("GET", "/assets/index-Old9.js", id="missing-hashed-asset"),
    ],
)
async def test_api_other_methods_and_missing_assets_keep_the_problem_404(
    web: Api, method: str, path: str
) -> None:
    assert_problem_404(await web.client.request(method, path))


@pytest.mark.parametrize(("mode", "static"), [("desktop", True), ("web", False)])
async def test_no_static_file_without_web_mode_and_folder(
    make_api: ApiFactory, site: Path, mode: str, static: bool
) -> None:
    async with make_api(mode=mode, static_dir=site if static else None) as api:
        assert_problem_404(await api.client.get("/"))
        assert_problem_404(await api.client.get("/assets/index-Ab12.js"))


async def test_folder_without_index_is_logged_and_serves_no_page(
    make_api: ApiFactory, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    folder = tmp_path / "empty"
    folder.mkdir()
    with caplog.at_level(logging.WARNING, logger="reframe_server.static"):
        async with make_api(static_dir=folder) as api:
            assert_problem_404(await api.client.get("/queue"))
    assert f"{folder} has no index.html" in caplog.text


async def test_folder_behind_a_link_follows_the_link_on_each_request(
    make_api: ApiFactory, tmp_path: Path
) -> None:
    releases = tmp_path / "releases"
    for name in ("1", "2"):
        (releases / name).mkdir(parents=True)
        (releases / name / "index.html").write_text(f"build {name}")
    current = tmp_path / "current"
    current.symlink_to(releases / "1")
    async with make_api(static_dir=current) as api:
        assert (await api.anonymous.get("/queue")).text == "build 1"
        swap = tmp_path / "current.new"
        swap.symlink_to(releases / "2")
        swap.replace(current)
        assert (await api.anonymous.get("/queue")).text == "build 2"


async def test_static_answers_pass_the_security_middleware(web: Api) -> None:
    page = await web.anonymous.get("/")
    assert page.content == INDEX
    assert page.headers["content-security-policy"] == APP_CSP
    assert page.headers["x-frame-options"] == "DENY"
    assert page.headers["x-content-type-options"] == "nosniff"
    foreign = await web.anonymous.get("/", headers={"Host": "evil.example"})
    assert foreign.status_code == 400
    assert foreign.json()["code"] == "request.host"


async def raw_get(port: int, target: str) -> tuple[int, bytes]:
    """``GET target`` as sent on the wire: httpx would remove the dot segments first."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(f"GET {target} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n".encode())
    await writer.drain()
    data = await asyncio.wait_for(reader.read(), 10)
    writer.close()
    await writer.wait_closed()
    head, _, body = data.partition(b"\r\n\r\n")
    return int(head.split()[1]), body


@pytest.mark.parametrize(
    "target",
    [
        "/../outside/secret.txt",
        "/%2e%2e/outside/secret.txt",
        "/assets%2f..%2f..%2foutside%2fsecret.txt",
        "/leak",
        "/assets/leak.js",
        "/%00",
    ],
)
async def test_no_path_leaves_the_folder(web: Api, target: str) -> None:
    async with web.live() as server:
        status, body = await raw_get(server.port, target)
    assert SECRET not in body
    assert (status, body) == (200, INDEX) or status == 404


async def test_websocket_to_a_page_path_is_refused(web: Api) -> None:
    async with web.live() as server:
        with pytest.raises(InvalidStatus) as refused:
            async with server.connect("/queue"):
                pass
    assert refused.value.response.status_code == 403


async def test_script_type_does_not_depend_on_the_os(
    web: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    # What a Windows registry entry can make of .js.
    monkeypatch.setattr(responses, "guess_type", lambda *_args, **_kwargs: ("text/plain", None))
    response = await web.anonymous.get("/assets/index-Ab12.js")
    assert response.headers["content-type"] == "text/javascript; charset=utf-8"
