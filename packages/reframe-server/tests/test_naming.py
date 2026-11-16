"""The naming preview."""

from __future__ import annotations

from typing import Any

import pytest

from reframe.models import JobSettings
from reframe_testing.server import Api

pytestmark = pytest.mark.anyio


def naming(api: Api, template: str) -> dict[str, Any]:
    return {
        "movie_template": template,
        "episode_template": template,
        "output_folder_mode": "fixed",
        "output_folder": str(api.output / "Shows"),
    }


async def test_preview_from_the_paths(api: Api) -> None:
    first = await api.add_source("Show S01E01.mkv")
    second = await api.add_source("Show S01E02.mkv")
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
    sid = await api.add_source("Show S01E01.mkv")
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


@pytest.mark.parametrize("with_job", [False, True])
async def test_a_name_beside_the_source_has_the_settings_fix(api: Api, with_job: bool) -> None:
    sid = await api.add_source("Show S01E01.mkv")
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
