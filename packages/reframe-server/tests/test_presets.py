"""The preset routes: CRUD, the default, import, export, diff and the defaults preview."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import AsyncIterator
from typing import Any

import pytest

from reframe.models import MediaSource
from reframe_server.config import ServerMode
from reframe_server.routers import presets
from reframe_testing.server import Api, ApiFactory

pytestmark = pytest.mark.anyio

BUILT_IN = "h265-mkv-1080p"


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


@pytest.mark.skipif(
    sys.platform == "win32" or os.geteuid() == 0,
    reason="chmod does not keep Windows or root from writing the folder",
)
@pytest.mark.parametrize("mode", ["web", "desktop"])
async def test_presets_that_cannot_be_written_name_the_folder_only_on_the_desktop(
    make_api: ApiFactory, mode: ServerMode
) -> None:
    document = {"schema_version": 1, "presets": [{"id": "x", "name": "X"}]}
    async with make_api(mode=mode) as api:
        config = api.config.config_dir
        assert config is not None
        os.chmod(config, 0o500)
        try:
            created = await api.client.post("/api/presets", json={"template": {}, "name": "Mine"})
            imported = await api.client.post("/api/presets/import", content=json.dumps(document))
        finally:
            os.chmod(config, 0o700)
    assert (created.status_code, created.json()["code"]) == (503, "presets.write_failed")
    assert [issue["code"] for issue in imported.json()["issues"]] == ["presets.write_failed"]
    for answer in (created, imported):
        assert (str(config) in answer.text) is (mode == "desktop")


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


ENGLISH_AT_96 = {
    "selector": {"kind": "audio", "languages": ["en"]},
    "multiple": True,
    "settings": {
        "kind": "audio", "action": "encode", "encoder": "aac", "mixdown": "stereo", "bitrate": 96,
    },
}  # fmt: skip


def outputs(draft: dict[str, Any]) -> list[tuple[Any, ...]]:
    audio = [(t["source_stream"], t["encoder"], t["bitrate"]) for t in draft["audio"]]
    return [*audio, *((t["source"],) for t in draft["subtitles"])]


async def test_the_defaults_preview_of_a_template_is_what_apply_drafts(api: Api) -> None:
    sid = await add_source(api)
    preset = (await api.client.get(f"/api/presets/{BUILT_IN}")).json()
    template = {k: v for k, v in preset.items() if k not in ("id", "name", "category", "built_in")}
    template["audio_rules"] = [ENGLISH_AT_96]
    subtitles = {"selection": {"languages": ["ja"]}}
    body = {
        "audio_defaults": template["audio_defaults"],
        "subtitle_defaults": subtitles,
        "source_ids": [sid],
    }

    async def post(path: str, data: dict[str, Any]) -> Any:
        response = await api.client.post(path, json=data)
        assert response.status_code == 200, response.text
        return response.json()

    [preview] = await post("/api/presets/defaults/preview", {**body, "template": template})
    applied = await post(
        "/api/jobs/explain",
        {"source_id": sid, "template": {**template, "subtitle_defaults": subtitles}},
    )
    assert outputs(preview) == outputs(applied)
    assert outputs(preview)[:2] == [(2, "aac", 96), (3, "aac", 96)]
    [defaults_only] = await post("/api/presets/defaults/preview", body)
    assert outputs(defaults_only)[:2] != outputs(preview)[:2]
    own = await post("/api/jobs/explain", {"source_id": sid, "template": template})
    assert outputs(own) != outputs(preview)


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
