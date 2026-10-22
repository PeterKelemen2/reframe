"""``/api/fs``: the server-side file browser."""

from __future__ import annotations

import os
import types
from collections.abc import Callable
from pathlib import Path

import pytest

from reframe_server import security
from reframe_server.config import ServerConfig
from reframe_server.errors import ProblemError
from reframe_server.routers import fs
from reframe_testing.server import Api, ApiFactory

pytestmark = pytest.mark.anyio


def _refuse(config: ServerConfig, path: str | os.PathLike[str]) -> Path:
    raise ProblemError(403, "path.outside_roots", "Outside the roots")


def _names(body: dict[str, list[dict[str, str]]]) -> list[str]:
    return [entry["name"] for entry in body["entries"]]


async def test_roots_in_web_mode_are_the_media_and_output_roots(api: Api) -> None:
    roots = (await api.client.get("/api/fs/roots")).json()["roots"]
    assert [(Path(root["path"]), root["kind"]) for root in roots] == [
        (api.media.resolve(), "media"),
        (api.output.resolve(), "output"),
    ]


async def test_a_root_named_through_a_link_is_shown_resolved(
    make_api: ApiFactory, tmp_path: Path
) -> None:
    """Listings show resolved paths: the root must match them, and stay the top."""
    link = tmp_path / "media-link"
    try:
        link.symlink_to(tmp_path / "media", target_is_directory=True)
    except OSError:
        pytest.skip("symbolic links need a privilege here")
    async with make_api(media_roots=[link]) as api:
        root = (await api.client.get("/api/fs/roots")).json()["roots"][0]
        listing = (await api.client.get("/api/fs/list", params={"path": str(link)})).json()
    assert Path(root["path"]) == Path(listing["path"]) == api.media.resolve()
    assert listing["parent"] is None


@pytest.mark.parametrize(("platform", "drives"), [("linux", ["/"]), ("win32", ["C:\\", "D:\\"])])
async def test_roots_in_desktop_mode_are_home_and_the_drives(
    make_api: ApiFactory, monkeypatch: pytest.MonkeyPatch, platform: str, drives: list[str]
) -> None:
    monkeypatch.setattr(fs, "sys", types.SimpleNamespace(platform=platform))
    monkeypatch.setattr(os, "listdrives", lambda: ["C:\\", "D:\\"], raising=False)
    async with make_api(mode="desktop") as api:
        roots = (await api.client.get("/api/fs/roots")).json()["roots"]
    assert roots[0]["kind"] == "home"
    assert Path(roots[0]["path"]) == Path.home()
    assert [root["path"] for root in roots[1:]] == [str(Path(drive)) for drive in drives]


async def test_list_shows_folders_then_media_files_in_natural_order(api: Api) -> None:
    show = api.media / "Show"
    for name in ("Ep 10.mkv", "Ep 2.MP4", "notes.txt", ".hidden.mkv"):
        (show / name).parent.mkdir(exist_ok=True)
        (show / name).write_bytes(b"x" * 3)
    (show / "Extras").mkdir()
    (show / ".git").mkdir()
    response = await api.client.get("/api/fs/list", params={"path": str(show)})
    assert response.status_code == 200
    body = response.json()
    assert _names(body) == ["Extras", "Ep 2.MP4", "Ep 10.mkv"]
    assert [entry["kind"] for entry in body["entries"]] == ["folder", "file", "file"]
    assert body["entries"][1]["size"] == 3
    assert body["entries"][0]["size"] is None
    assert Path(body["entries"][2]["path"]) == show.resolve() / "Ep 10.mkv"
    assert Path(body["parent"]) == api.media.resolve()


async def test_a_root_has_no_parent_in_web_mode(api: Api) -> None:
    body = (await api.client.get("/api/fs/list", params={"path": str(api.media)})).json()
    assert body["parent"] is None


async def test_in_desktop_mode_the_parent_goes_up_to_the_file_system_root(
    make_api: ApiFactory,
) -> None:
    async with make_api(mode="desktop") as api:
        media = (await api.client.get("/api/fs/list", params={"path": str(api.media)})).json()
        top = Path(api.media.anchor)
        root = (await api.client.get("/api/fs/list", params={"path": str(top)})).json()
    assert Path(media["parent"]) == api.media.resolve().parent
    assert root["parent"] is None


async def test_list_passes_the_path_to_the_jail(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(security, "jail_read", _refuse)
    monkeypatch.setattr(security, "jail_write", _refuse)
    response = await api.client.get("/api/fs/list", params={"path": str(api.media)})
    assert (response.status_code, response.json()["code"]) == (403, "path.outside_roots")


async def test_a_folder_below_an_output_root_can_be_listed(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The output folder picker browses below the output roots."""
    asked: list[Path] = []
    real_write: Callable[[ServerConfig, str | os.PathLike[str]], Path] = security.jail_write

    def write(config: ServerConfig, path: str | os.PathLike[str]) -> Path:
        asked.append(Path(path))
        return real_write(config, path)

    monkeypatch.setattr(security, "jail_read", _refuse)
    monkeypatch.setattr(security, "jail_write", write)
    (api.output / "Movies").mkdir()
    response = await api.client.get("/api/fs/list", params={"path": str(api.output)})
    assert response.status_code == 200
    assert _names(response.json()) == ["Movies"]
    assert asked == [api.output]


@pytest.mark.parametrize(
    ("make", "status", "code"),
    [
        (lambda folder: folder / "gone", 404, "fs.not_found"),
        (lambda folder: _file(folder / "Show.mkv"), 422, "fs.not_a_folder"),
        (lambda folder: _locked(folder / "locked"), 403, "fs.unreadable"),
    ],
)
async def test_a_path_that_cannot_be_listed_is_a_problem(
    api: Api, make: Callable[[Path], Path], status: int, code: str
) -> None:
    path = make(api.media)
    try:
        response = await api.client.get("/api/fs/list", params={"path": str(path)})
    finally:
        if path.is_dir():
            path.chmod(0o700)
    assert (response.status_code, response.json()["code"]) == (status, code)


def _file(path: Path) -> Path:
    path.write_bytes(b"")
    return path


def _locked(path: Path) -> Path:
    path.mkdir()
    path.chmod(0)
    if os.access(path, os.R_OK):
        pytest.skip("a folder without permissions can still be read here")
    return path
