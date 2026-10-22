"""``/api/settings``: read, and change with a JSON patch; what a web client may not change."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from reframe_server import security
from reframe_server.config import ServerConfig
from reframe_server.errors import ProblemError
from reframe_testing.server import Api, ApiFactory

pytestmark = pytest.mark.anyio

FOLDER = "/output/naming/output_folder"


def _refuse(config: ServerConfig, path: str | os.PathLike[str]) -> Path:
    raise ProblemError(403, "path.outside_roots", "Outside the roots")


def _start_with(tmp_path: Path, settings: dict[str, Any]) -> None:
    file = tmp_path / "config" / "settings.json"
    file.write_text(json.dumps(json.loads(file.read_text("utf-8")) | settings), encoding="utf-8")


async def test_get_answers_the_settings_in_effect(api: Api) -> None:
    body = (await api.client.get("/api/settings")).json()
    assert body["encoders"]["hardware_tests"] is False


async def test_a_patch_takes_effect_and_is_saved(api: Api) -> None:
    patch = [{"op": "replace", "path": "/preview/sample_frames", "value": 4}]
    response = await api.client.put("/api/settings", json=patch)
    assert response.status_code == 200
    body = response.json()
    assert body["settings"]["preview"]["sample_frames"] == 4
    assert body["saved"] is True
    assert [change["path"] for change in body["changes"]] == ["preview.sample_frames"]
    assert api.reframe.settings.get().preview.sample_frames == 4


async def test_an_invalid_patch_is_a_problem_with_its_issues(api: Api) -> None:
    patch = [{"op": "replace", "path": "/preview/sample_frames", "value": 1000}]
    response = await api.client.put("/api/settings", json=patch)
    assert response.status_code == 422
    problem = response.json()
    assert problem["code"] == "settings.invalid"
    assert problem["issues"][0]["path"] == "preview.sample_frames"
    assert api.reframe.settings.get().preview.sample_frames != 1000


@pytest.mark.parametrize(
    "patch",
    [
        [{"op": "add", "path": "/tools/ffmpeg", "value": "/bin/sh"}],
        [{"op": "add", "path": "/tools/extra", "value": "/bin/sh"}],
        [{"op": "replace", "path": "", "value": {"tools": {"ffprobe": "/bin/sh"}}}],
    ],
    ids=["a tool", "an unknown tool key", "the whole document"],
)
async def test_a_web_client_cannot_choose_a_program(api: Api, patch: list[dict[str, Any]]) -> None:
    response = await api.client.put("/api/settings", json=patch)
    assert (response.status_code, response.json()["code"]) == (403, "settings.tools_forbidden")
    assert api.reframe.settings.get().tools.model_dump(exclude_none=True) == {}


async def test_a_web_client_may_remove_a_tool_override(
    make_api: ApiFactory, tmp_path: Path
) -> None:
    """The "Use bundled" fix: discovery chooses again."""
    _start_with(tmp_path, {"tools": {"ffmpeg": "/opt/ffmpeg/bin/ffmpeg"}})
    async with make_api() as api:
        patch = [{"op": "remove", "path": "/tools/ffmpeg"}]
        response = await api.client.put("/api/settings", json=patch)
    assert response.status_code == 200
    assert response.json()["settings"]["tools"]["ffmpeg"] is None


async def test_a_desktop_client_may_choose_a_program(make_api: ApiFactory) -> None:
    async with make_api(mode="desktop") as api:
        patch = [{"op": "add", "path": "/tools/mediainfo", "value": "/opt/mediainfo"}]
        response = await api.client.put("/api/settings", json=patch)
    assert response.status_code == 200
    assert response.json()["settings"]["tools"]["mediainfo"] == "/opt/mediainfo"


async def test_a_new_folder_goes_through_the_write_jail(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[Path] = []

    def write(config: ServerConfig, path: str | os.PathLike[str]) -> Path:
        asked.append(Path(path))
        return _refuse(config, path)

    monkeypatch.setattr(security, "jail_write", write)
    patch = [{"op": "replace", "path": FOLDER, "value": str(api.output / "Movies")}]
    response = await api.client.put("/api/settings", json=patch)
    assert (response.status_code, response.json()["code"]) == (403, "path.outside_roots")
    assert asked == [api.output / "Movies"]
    assert api.reframe.settings.get().output.naming.output_folder is None


async def test_a_folder_the_patch_does_not_change_is_not_checked_again(
    make_api: ApiFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A folder saved before the roots changed does not block every other change."""
    _start_with(tmp_path, {"output": {"naming": {"output_folder": str(tmp_path / "old")}}})
    monkeypatch.setattr(security, "jail_write", _refuse)
    async with make_api() as api:
        patch = [{"op": "replace", "path": "/preview/sample_frames", "value": 3}]
        response = await api.client.put("/api/settings", json=patch)
    assert response.status_code == 200
