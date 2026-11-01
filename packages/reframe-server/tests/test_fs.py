"""``/api/fs``: the server-side file browser."""

from __future__ import annotations

import os
import types
from collections.abc import Callable
from pathlib import Path

import pytest

from reframe_server.routers import fs
from reframe_testing.server import Api, ApiFactory

pytestmark = pytest.mark.anyio


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


async def test_list_with_extensions_shows_those_files_instead_of_media_files(api: Api) -> None:
    for name in ("Show.en.srt", "Show.hu.ASS", "Show.mkv", "notes.txt", ".hidden.srt"):
        (api.media / name).write_bytes(b"x")
    (api.media / "Subs").mkdir()
    params = {"path": str(api.media), "extensions": [".srt", "ass"]}
    response = await api.client.get("/api/fs/list", params=params)
    assert response.status_code == 200
    assert _names(response.json()) == ["Subs", "Show.en.srt", "Show.hu.ASS"]


@pytest.mark.parametrize("extension", ["", ".", "a/b", "srt.bak"])
async def test_an_extension_that_names_no_extension_is_refused(api: Api, extension: str) -> None:
    params = {"path": str(api.media), "extensions": [extension]}
    response = await api.client.get("/api/fs/list", params=params)
    assert (response.status_code, response.json()["code"]) == (422, "fs.bad_extension")


async def test_in_desktop_mode_the_parent_goes_up_to_the_file_system_root(
    make_api: ApiFactory,
) -> None:
    async with make_api(mode="desktop") as api:
        media = (await api.client.get("/api/fs/list", params={"path": str(api.media)})).json()
        top = Path(api.media.anchor)
        root = (await api.client.get("/api/fs/list", params={"path": str(top)})).json()
    assert Path(media["parent"]) == api.media.resolve().parent
    assert root["parent"] is None


async def test_a_folder_below_an_output_root_can_be_listed(api: Api) -> None:
    """The output folder picker browses below the output roots."""
    (api.output / "Movies").mkdir()
    response = await api.client.get("/api/fs/list", params={"path": str(api.output)})
    assert response.status_code == 200
    assert _names(response.json()) == ["Movies"]


async def test_a_folder_outside_the_roots_is_refused_as_outside_media_and_output(
    api: Api, tmp_path: Path
) -> None:
    """The dialog shows the detail: browsing to open a file is not a write."""
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    response = await api.client.get("/api/fs/list", params={"path": str(outside)})
    problem = response.json()
    assert (response.status_code, problem["code"]) == (403, "path.outside_roots")
    assert "media and output folders" in problem["detail"]
    assert "write" not in problem["detail"]


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
