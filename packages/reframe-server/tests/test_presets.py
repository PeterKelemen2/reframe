"""The preset routes: CRUD, the default, import, export, diff and the defaults preview."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from reframe.models import MediaSource
from reframe_server import security
from reframe_server.config import ServerConfig
from reframe_server.errors import ProblemError
from reframe_server.routers import presets
from reframe_testing.server import Api

pytestmark = pytest.mark.anyio

BUILT_IN = "h265-mkv-1080p"


def refuse(monkeypatch: pytest.MonkeyPatch, name: str) -> list[object]:
    seen: list[object] = []

    def jail(_config: ServerConfig, value: object) -> None:
        seen.append(value)
        raise ProblemError(403, "path.outside_roots", "Outside the roots")

    monkeypatch.setattr(security, name, jail)
    return seen


async def add_source(api: Api, name: str = "Show S01E01.mkv") -> str:
    path = api.media_file(name)
    assert isinstance(await api.reframe.sources.probe(path), MediaSource)
    sid: str = api.app.state.sources.add(path)
    return sid


async def create(api: Api, name: str = "Mine", **template: Any) -> dict[str, Any]:
    response = await api.client.post("/api/presets", json={"template": template, "name": name})
    assert response.status_code == 201, response.text
    preset: dict[str, Any] = response.json()
    return preset


async def test_operation_ids(api: Api) -> None:
    paths = (await api.client.get("/api/openapi.json")).json()["paths"]
    found = {
        (method, path): operation["operationId"]
        for path, item in paths.items()
        if path.startswith("/api/presets")
        for method, operation in item.items()
    }
    assert found == {
        ("get", "/api/presets"): "presets_list",
        ("post", "/api/presets"): "presets_create",
        ("get", "/api/presets/export"): "presets_export",
        ("post", "/api/presets/import"): "presets_import",
        ("post", "/api/presets/diff"): "presets_diff",
        ("post", "/api/presets/defaults/preview"): "presets_preview_defaults",
        ("get", "/api/presets/{preset_id}"): "presets_get",
        ("put", "/api/presets/{preset_id}"): "presets_save",
        ("delete", "/api/presets/{preset_id}"): "presets_delete",
        ("post", "/api/presets/{preset_id}/default"): "presets_set_default",
    }


async def test_a_created_preset_is_listed_and_found(api: Api) -> None:
    response = await api.client.post(
        "/api/presets",
        json={"template": {"video": {"encoder": "libx264"}}, "name": "Mine", "category": "TV"},
    )
    assert response.status_code == 201
    preset = response.json()
    assert response.headers["location"] == f"/api/presets/{preset['id']}"
    assert (preset["name"], preset["category"], preset["built_in"]) == ("Mine", "TV", False)
    found = await api.client.get(response.headers["location"])
    assert found.json()["video"]["encoder"] == "libx264"
    listed = (await api.client.get("/api/presets")).json()
    assert listed["presets"][-1]["id"] == preset["id"]
    assert listed["default_id"] == BUILT_IN


async def test_an_unknown_preset_is_404(api: Api) -> None:
    response = await api.client.get("/api/presets/nope")
    assert response.status_code == 404
    assert response.json()["code"] == "preset.not_found"


async def test_put_renames_a_preset(api: Api) -> None:
    preset = await create(api)
    preset["name"] = "Renamed"
    response = await api.client.put(f"/api/presets/{preset['id']}", json=preset)
    assert response.status_code == 200
    assert (await api.client.get(f"/api/presets/{preset['id']}")).json()["name"] == "Renamed"


async def test_put_with_another_id_in_the_body_is_refused(api: Api) -> None:
    preset = await create(api)
    other = await create(api, "Other")
    response = await api.client.put(f"/api/presets/{other['id']}", json=preset)
    assert response.status_code == 422
    assert response.json()["code"] == "presets.id_mismatch"
    assert (await api.client.get(f"/api/presets/{other['id']}")).json()["name"] == "Other"


@pytest.mark.parametrize(
    ("change", "status", "code"),
    [
        ("built_in", 409, "preset.built_in"),
        ("name_taken", 409, "preset.name_conflict"),
        ("no_name", 422, "preset.name_empty"),
    ],
)
async def test_a_refused_save_is_a_problem_with_the_issue(
    api: Api, change: str, status: int, code: str
) -> None:
    preset = await create(api)
    if change == "built_in":
        preset = (await api.client.get(f"/api/presets/{BUILT_IN}")).json()
    else:
        preset["name"] = "Fast 1080p30" if change == "name_taken" else " "
    response = await api.client.put(f"/api/presets/{preset['id']}", json=preset)
    assert response.status_code == status
    body = response.json()
    assert body["code"] == code
    assert [issue["code"] for issue in body["issues"]] == [code]


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="POSIX permissions")
async def test_a_preset_that_cannot_be_written_is_503(api: Api) -> None:
    config = api.config.config_dir
    assert config is not None
    os.chmod(config, 0o500)
    try:
        response = await api.client.post("/api/presets", json={"template": {}, "name": "Mine"})
    finally:
        os.chmod(config, 0o700)
    assert response.status_code == 503
    assert response.json()["code"] == "presets.write_failed"


async def test_delete_answers_with_the_deleted_preset(api: Api) -> None:
    preset = await create(api)
    response = await api.client.delete(f"/api/presets/{preset['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == preset["id"]
    assert (await api.client.get(f"/api/presets/{preset['id']}")).status_code == 404
    again = await api.client.delete(f"/api/presets/{preset['id']}")
    assert (again.status_code, again.json()["code"]) == (404, "preset.not_found")


async def test_set_default(api: Api) -> None:
    preset = await create(api)
    response = await api.client.post(f"/api/presets/{preset['id']}/default")
    assert response.status_code == 200
    assert response.json()["id"] == preset["id"]
    assert (await api.client.get("/api/presets")).json()["default_id"] == preset["id"]


async def test_export_then_import(api: Api) -> None:
    mine = await create(api, "Mine")
    await create(api, "Other")
    exported = await api.client.get("/api/presets/export", params={"ids": [mine["id"]]})
    assert exported.status_code == 200
    document = exported.json()["document"]
    assert [p["name"] for p in document["presets"]] == ["Mine"]
    imported = await api.client.post(
        "/api/presets/import", content=json.dumps(document), params={"on_conflict": "rename"}
    )
    assert imported.status_code == 200
    report = imported.json()
    assert report["renamed"] == [{"name": "Mine", "new_name": "Mine (2)"}]
    skipped = await api.client.post(
        "/api/presets/import", content=json.dumps(document), params={"on_conflict": "skip"}
    )
    assert skipped.json()["skipped"] == ["Mine"]


async def test_export_without_ids_has_every_user_preset(api: Api) -> None:
    await create(api, "Mine")
    await create(api, "Other")
    document = (await api.client.get("/api/presets/export")).json()["document"]
    assert [p["name"] for p in document["presets"]] == ["Mine", "Other"]


async def test_an_import_over_the_limit_is_413(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(presets, "IMPORT_LIMIT", 100)
    data = json.dumps({"presets": [], "padding": "x" * 200}).encode()

    async def body() -> AsyncIterator[bytes]:
        for start in range(0, len(data), 50):
            yield data[start : start + 50]

    response = await api.client.post("/api/presets/import", content=body())
    assert response.status_code == 413
    assert response.json()["code"] == "presets.import_too_large"


@pytest.mark.parametrize("content", [b"{", b"[]"])
async def test_an_import_that_is_not_a_json_object_is_422(api: Api, content: bytes) -> None:
    response = await api.client.post("/api/presets/import", content=content)
    assert response.status_code == 422
    assert response.json()["code"] == "presets.import_invalid"


@pytest.mark.parametrize("entries", [5, ["junk", {"id": "x", "naming": "junk"}]])
async def test_a_damaged_import_file_is_reported(api: Api, entries: object) -> None:
    document = {"schema_version": 1, "presets": entries}
    response = await api.client.post("/api/presets/import", content=json.dumps(document))
    assert response.status_code == 200
    report = response.json()
    assert report["imported"] == []
    assert report["issues"]


async def test_import_jails_each_naming_folder(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = str(api.output / "Shows")
    preset = (await api.client.get(f"/api/presets/{BUILT_IN}")).json()
    preset |= {"id": "x", "name": "Mine", "built_in": False}
    preset["naming"] = {"output_folder_mode": "fixed", "output_folder": folder}
    document = {"schema_version": 1, "presets": [preset]}
    seen = refuse(monkeypatch, "jail_write")
    response = await api.client.post("/api/presets/import", content=json.dumps(document))
    assert response.status_code == 403
    assert seen == [folder]


async def test_diff_against_a_preset(api: Api) -> None:
    template = (await api.client.get(f"/api/presets/{BUILT_IN}")).json()
    template["video"]["custom_params"] = "aq-mode=3"
    response = await api.client.post(
        "/api/presets/diff", json={"template": template, "preset_id": BUILT_IN}
    )
    assert response.status_code == 200
    assert [change["path"] for change in response.json()] == ["video.custom_params"]
    unknown = await api.client.post(
        "/api/presets/diff", json={"template": template, "preset_id": "nope"}
    )
    assert (unknown.status_code, unknown.json()["code"]) == (404, "preset.not_found")


async def test_defaults_preview_explains_each_source(api: Api) -> None:
    first, second = await add_source(api), await add_source(api, "Show S01E02.mkv")
    response = await api.client.post(
        "/api/presets/defaults/preview",
        json={
            "audio_defaults": {"selection": {"languages": ["jpn"]}},
            "subtitle_defaults": {},
            "source_ids": [first, second],
            "container": "webm",
        },
    )
    assert response.status_code == 200
    drafts = response.json()
    assert len(drafts) == 2
    for draft in drafts:
        assert [track["source_stream"] for track in draft["audio"]] == [1]
        assert "defaults.codec_not_in_container" in [i["code"] for i in draft["issues"]]


@pytest.mark.parametrize("route", ["create", "save", "diff"])
async def test_a_templates_naming_folder_passes_the_jail(
    api: Api, monkeypatch: pytest.MonkeyPatch, route: str
) -> None:
    folder = Path(api.output / "Shows")
    preset = await create(api)
    preset["naming"] = {"output_folder_mode": "fixed", "output_folder": str(folder)}
    seen = refuse(monkeypatch, "jail_write")
    if route == "create":
        response = await api.client.post(
            "/api/presets", json={"template": preset, "name": "Another"}
        )
    elif route == "save":
        response = await api.client.put(f"/api/presets/{preset['id']}", json=preset)
    else:
        response = await api.client.post(
            "/api/presets/diff", json={"template": preset, "preset_id": preset["id"]}
        )
    assert response.status_code == 403
    assert seen == [folder]
    stored = (await api.client.get(f"/api/presets/{preset['id']}")).json()
    assert stored["naming"] is None
