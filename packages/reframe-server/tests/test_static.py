"""The built frontend in web mode: cache headers, the SPA fallback, the 404 of ``/api``, the
folder jail and the folders refused at start-up."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from starlette import responses
from websockets.exceptions import InvalidStatus

from reframe import paths
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
async def test_no_static_file_or_folder_check_without_web_mode_and_folder(
    make_api: ApiFactory, site: Path, mode: str, static: bool
) -> None:
    (site / "index.html").unlink()
    async with make_api(mode=mode, static_dir=site if static else None) as api:
        assert_problem_404(await api.client.get("/"))
        assert_problem_404(await api.client.get("/assets/index-Ab12.js"))


async def test_folder_without_index_html_is_refused(make_api: ApiFactory, tmp_path: Path) -> None:
    folder = tmp_path / "empty"
    folder.mkdir()
    with pytest.raises(ValidationError, match=r"has no index\.html"):
        async with make_api(static_dir=folder):
            pass


@pytest.mark.parametrize(
    ("held", "overrides", "env"),
    [
        pytest.param("config folder", {"config_dir": "web"}, {}, id="config"),
        pytest.param(
            "data folder", {"data_dir": None}, {paths.DATA_DIR_ENV: "web/reframe"}, id="data"
        ),
        pytest.param("cache folder", {}, {paths.CACHE_DIR_ENV: "alias/cache"}, id="cache"),
        pytest.param("endpoint file", {"endpoint_file": "web/server.json"}, {}, id="endpoint"),
        pytest.param("media root", {"media_roots": ["media", "web/media"]}, {}, id="media"),
        pytest.param("output root", {"output_roots": ["output", "web"]}, {}, id="output"),
    ],
)
async def test_folder_that_holds_a_server_folder_is_refused(
    make_api: ApiFactory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    held: str,
    overrides: dict[str, str | list[str] | None],
    env: dict[str, str],
) -> None:
    # Its files are served without a login, server.json with the token among them. The folder
    # is named through one link and the cache folder through another: both are resolved.
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_bytes(INDEX)
    for link in ("current", "alias"):
        (tmp_path / link).symlink_to(web, target_is_directory=True)
    for variable, relative in env.items():
        monkeypatch.setenv(variable, str(tmp_path / relative))
    folders: dict[str, Path | list[Path] | None] = {}
    for name, value in overrides.items():
        if isinstance(value, list):
            folders[name] = [tmp_path / item for item in value]
        else:
            folders[name] = None if value is None else tmp_path / value
    with pytest.raises(ValidationError, match=f"holds the {held}"):
        async with make_api(static_dir=tmp_path / "current", **folders):
            pass


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


@pytest.mark.parametrize(
    ("target", "status"),
    [
        pytest.param("/%5c%5cattacker.example%5cshare%5cx.js", 200, id="unc"),
        pytest.param("/C:/Windows/win.ini", 200, id="drive"),
        pytest.param("/assets/COM1", 404, id="device"),
    ],
)
async def test_windows_path_in_a_request_is_never_resolved(
    web: Api, site: Path, monkeypatch: pytest.MonkeyPatch, target: str, status: int
) -> None:
    # On Windows the join drops the folder, and resolving opens the path (a UNC path: an SMB
    # session with the server user's credentials) before any check can refuse it.
    resolved: list[Path] = []
    resolve = Path.resolve

    def recording(path: Path, strict: bool = False) -> Path:
        resolved.append(path)
        return resolve(path, strict)

    async with web.live() as server:
        monkeypatch.setattr(Path, "resolve", recording)
        assert (await raw_get(server.port, target))[0] == status
    assert {path.name for path in resolved} <= {site.name, "index.html"}


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
