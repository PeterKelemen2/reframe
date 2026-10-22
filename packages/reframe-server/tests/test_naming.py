"""The naming preview."""

from __future__ import annotations

from typing import Any

import pytest

from reframe.models import JobSettings, MediaSource
from reframe_server import security
from reframe_server.config import ServerConfig
from reframe_server.errors import ProblemError
from reframe_testing.server import Api

pytestmark = pytest.mark.anyio


def refuse(monkeypatch: pytest.MonkeyPatch, name: str) -> list[object]:
    seen: list[object] = []

    def jail(_config: ServerConfig, value: object) -> None:
        seen.append(value)
        raise ProblemError(403, "path.outside_roots", "Outside the roots")

    monkeypatch.setattr(security, name, jail)
    return seen


async def add_source(api: Api, name: str) -> str:
    path = api.media_file(name)
    assert isinstance(await api.reframe.sources.probe(path), MediaSource)
    sid: str = api.app.state.sources.add(path)
    return sid


def naming(api: Api, template: str) -> dict[str, Any]:
    return {
        "movie_template": template,
        "episode_template": template,
        "output_folder_mode": "fixed",
        "output_folder": str(api.output / "Shows"),
    }


async def test_operation_id(api: Api) -> None:
    paths = (await api.client.get("/api/openapi.json")).json()["paths"]
    assert paths["/api/naming/preview"]["post"]["operationId"] == "naming_preview"


async def test_preview_from_the_paths(api: Api) -> None:
    first = await add_source(api, "Show S01E01.mkv")
    second = await add_source(api, "Show S01E02.mkv")
    response = await api.client.post(
        "/api/naming/preview",
        json={
            "naming": naming(api, "{name} - {episode_code} {resolution}"),
            "source_ids": [second, first],
            "container": "mp4",
        },
    )
    assert response.status_code == 200
    names = response.json()
    assert [name["relative_path"] for name in names] == [
        "Show - S01E02.mp4",
        "Show - S01E01.mp4",
    ]
    assert names[0]["path"] == str(api.output / "Shows" / "Show - S01E02.mp4")
    assert names[0]["source"] == "file"


async def test_preview_of_a_job(api: Api) -> None:
    """The job's per-file overrides and its output size are in the name."""
    sid = await add_source(api, "Show S01E01.mkv")
    job = JobSettings.model_validate(
        {
            "source": {"path": str(api.media / "Show S01E01.mkv")},
            "output": {"naming": {"field_overrides": {"name": "Other"}}},
        }
    ).model_dump(mode="json")
    response = await api.client.post(
        "/api/naming/preview",
        json={"naming": naming(api, "{name} {resolution}"), "source_ids": [sid], "job": job},
    )
    assert response.status_code == 200
    [name] = response.json()
    assert name["relative_path"] == "Other 320x180.mkv"


@pytest.mark.parametrize("jail", ["jail_write", "jail_job"])
async def test_the_naming_folder_and_the_job_pass_the_jail(
    api: Api, monkeypatch: pytest.MonkeyPatch, jail: str
) -> None:
    sid = await add_source(api, "Show S01E01.mkv")
    job = {"source": {"path": str(api.media / "Show S01E01.mkv")}}
    seen = refuse(monkeypatch, jail)
    response = await api.client.post(
        "/api/naming/preview",
        json={"naming": naming(api, "{name}"), "source_ids": [sid], "job": job},
    )
    assert response.status_code == 403
    if jail == "jail_write":
        assert seen == [api.output / "Shows"]
    else:
        assert [str(j.source.path) for j in seen if isinstance(j, JobSettings)] == [
            job["source"]["path"]
        ]


@pytest.mark.parametrize("with_job", [False, True])
async def test_a_name_beside_the_source_has_the_settings_fix(api: Api, with_job: bool) -> None:
    sid = await add_source(api, "Show S01E01.mkv")
    body: dict[str, Any] = {"source_ids": [sid]}
    if with_job:
        body["job"] = {
            "source": {"path": str(api.media / "Show S01E01.mkv")},
            "output": {"path": str(api.media / "Show S01E01 (1).mkv")},
        }
    response = await api.client.post("/api/naming/preview", json=body)
    assert response.status_code == 200
    [name] = response.json()
    assert name["path"].startswith(str(api.media))
    [issue] = [i for i in name["issues"] if i["code"] == "output.folder_required"]
    assert [fix["target"] for fix in issue["fixes"]] == ["settings"]
