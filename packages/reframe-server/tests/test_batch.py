"""The batch routes: group, derive, resolve, a whole run, save a group template."""

from __future__ import annotations

from typing import Any

import pytest

from reframe.models import JobDraft, JobSettings, MediaSource
from reframe_server import security
from reframe_server.config import ServerConfig
from reframe_server.errors import ProblemError
from reframe_testing.server import Api

pytestmark = pytest.mark.anyio

QUALITY = {"op": "replace", "path": "/video/rate_control/value", "value": 30}


def refuse(monkeypatch: pytest.MonkeyPatch, name: str) -> list[object]:
    seen: list[object] = []

    def jail(_config: ServerConfig, value: object) -> None:
        seen.append(value)
        raise ProblemError(403, "path.outside_roots", "Outside the roots")

    monkeypatch.setattr(security, name, jail)
    return seen


async def add_sources(api: Api, count: int = 2) -> list[str]:
    ids = []
    for number in range(1, count + 1):
        path = api.media_file(f"Show S01E0{number}.mkv")
        assert isinstance(await api.reframe.sources.probe(path), MediaSource)
        ids.append(api.app.state.sources.add(path))
    return ids


def videos(rows: list[dict[str, Any]]) -> dict[str, tuple[str, float]]:
    """Each row's encoder and quality, by file name."""
    return {
        row["path"].rsplit("/", 1)[-1]: (
            row["job"]["video"]["encoder"],
            row["job"]["video"]["rate_control"]["value"],
        )
        for row in rows
    }


async def test_operation_ids(api: Api) -> None:
    paths = (await api.client.get("/api/openapi.json")).json()["paths"]
    names = {
        "group": "batch_group",
        "derive": "batch_derive",
        "resolve": "batch_resolve",
        "resolve-run": "batch_resolve_run",
        "save-preset": "batch_save_preset",
    }
    assert {route: paths[f"/api/batch/{route}"]["post"]["operationId"] for route in names} == names


async def test_group_at_a_level(api: Api) -> None:
    ids = await add_sources(api)
    response = await api.client.post("/api/batch/group", json={"source_ids": ids, "level": "loose"})
    assert response.status_code == 200
    [group] = response.json()["groups"]
    assert group["level"] == "loose"
    assert [m["path"].rsplit("/", 1)[-1] for m in group["members"]] == [
        "Show S01E01.mkv",
        "Show S01E02.mkv",
    ]


async def test_derive_takes_the_chosen_sections(api: Api) -> None:
    [sid] = await add_sources(api, 1)
    path = api.app.state.sources.path(sid)
    draft = await api.reframe.jobs.draft(path)
    assert isinstance(draft, JobDraft)
    job = draft.job.model_dump(mode="json")
    job["video"]["rate_control"]["value"] = 30
    job["output"]["path"] = str(api.output / "out.mkv")
    base = {"video": {"encoder": "libx264"}, "tags": {"title": "Group"}}
    response = await api.client.post(
        "/api/batch/derive",
        json={"job": job, "source_id": sid, "sections": ["video"], "base": base},
    )
    assert response.status_code == 200
    template = response.json()
    assert template["video"]["rate_control"]["value"] == 30
    assert template["tags"]["title"] == "Group"


async def test_resolve_finds_each_override_by_source_id(api: Api) -> None:
    first, second = await add_sources(api)
    response = await api.client.post(
        "/api/batch/resolve",
        json={
            "template": "H.264 MKV 1080p",
            "source_ids": [first, second],
            "overrides": {second: [QUALITY]},
        },
    )
    assert response.status_code == 200
    rows = videos(response.json()["rows"])
    encoder, quality = rows["Show S01E01.mkv"]
    assert (encoder, quality != 30) == ("libx264", True)
    assert rows["Show S01E02.mkv"] == ("libx264", 30)


async def test_an_override_of_an_unknown_source_is_404(api: Api) -> None:
    ids = await add_sources(api, 1)
    response = await api.client.post(
        "/api/batch/resolve", json={"source_ids": ids, "overrides": {"f00d": [QUALITY]}}
    )
    assert response.status_code == 404
    assert response.json()["code"] == "source.unknown"


async def test_resolve_run_groups_and_resolves(api: Api) -> None:
    first, second = await add_sources(api)
    response = await api.client.post(
        "/api/batch/resolve-run",
        json={
            "template": {"video": {"encoder": "libx264"}},
            "source_ids": [first, second],
            "level": "strict",
            "overrides": {first: [QUALITY]},
        },
    )
    assert response.status_code == 200
    run = response.json()
    [group] = run["grouping"]["groups"]
    assert group["level"] == "strict"
    [resolution] = run["resolutions"]
    assert resolution["group"]["id"] == group["id"]
    assert videos(resolution["rows"]) == {
        "Show S01E01.mkv": ("libx264", 30),
        "Show S01E02.mkv": ("libx264", 22),
    }


async def test_save_preset(api: Api) -> None:
    template = {"video": {"encoder": "libx264"}}
    response = await api.client.post(
        "/api/batch/save-preset", json={"template": template, "name": "Season", "category": "TV"}
    )
    assert response.status_code == 201
    preset = response.json()
    assert response.headers["location"] == f"/api/presets/{preset['id']}"
    stored = (await api.client.get(response.headers["location"])).json()
    assert (stored["name"], stored["category"], stored["video"]["encoder"]) == (
        "Season",
        "TV",
        "libx264",
    )
    again = await api.client.post(
        "/api/batch/save-preset", json={"template": template, "name": "season"}
    )
    assert (again.status_code, again.json()["code"]) == (409, "preset.name_conflict")


async def test_derive_jails_the_job(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    [sid] = await add_sources(api, 1)
    job = {"source": {"path": str(api.media / "Show S01E01.mkv")}}
    seen = refuse(monkeypatch, "jail_job")
    response = await api.client.post(
        "/api/batch/derive", json={"job": job, "source_id": sid, "sections": ["video"]}
    )
    assert response.status_code == 403
    assert [str(j.source.path) for j in seen if isinstance(j, JobSettings)] == [
        job["source"]["path"]
    ]


@pytest.mark.parametrize("route", ["derive", "resolve", "resolve-run", "save-preset"])
async def test_a_templates_naming_folder_passes_the_jail(
    api: Api, monkeypatch: pytest.MonkeyPatch, route: str
) -> None:
    ids = await add_sources(api, 1)
    folder = api.output / "Shows"
    template = {"naming": {"output_folder_mode": "fixed", "output_folder": str(folder)}}
    seen = refuse(monkeypatch, "jail_write")
    body: dict[str, Any]
    if route == "derive":
        job = {"source": {"path": str(api.media / "Show S01E01.mkv")}}
        body = {"job": job, "source_id": ids[0], "sections": [], "base": template}
    elif route == "save-preset":
        body = {"template": template, "name": "Season"}
    else:
        body = {"template": template, "source_ids": ids}
    response = await api.client.post(f"/api/batch/{route}", json=body)
    assert response.status_code == 403
    assert seen == [folder]
    assert (await api.client.get("/api/presets")).json()["presets"][-1]["built_in"] is True
