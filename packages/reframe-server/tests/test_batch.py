"""The batch routes: group, derive, resolve, a whole run, save a group template."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from reframe.models import JobDraft, JobSettings, JobTemplate, MediaSource, Preset, VideoSettings
from reframe_testing.server import Api

pytestmark = pytest.mark.anyio

QUALITY = {"op": "replace", "path": "/video/rate_control/value", "value": 30}


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
        Path(row["path"]).name: (
            row["job"]["video"]["encoder"],
            row["job"]["video"]["rate_control"]["value"],
        )
        for row in rows
    }


async def test_group_at_a_level(api: Api) -> None:
    ids = await add_sources(api)
    response = await api.client.post("/api/batch/group", json={"source_ids": ids, "level": "loose"})
    assert response.status_code == 200
    [group] = response.json()["groups"]
    assert group["level"] == "loose"
    assert [Path(m["path"]).name for m in group["members"]] == [
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


@pytest.mark.parametrize("route", ["resolve", "resolve-run"])
async def test_a_row_saved_outside_the_output_roots_is_an_error(api: Api, route: str) -> None:
    ids = await add_sources(api)
    response = await api.client.post(f"/api/batch/{route}", json={"source_ids": ids})
    assert response.status_code == 200
    body = response.json()
    rows = body["rows"] if route == "resolve" else body["resolutions"][0]["rows"]
    assert len(rows) == 2
    for row in rows:
        assert row["issues"][-1]["code"] == "output.folder_required"
        assert row["status"] == "error"


async def test_a_row_saved_in_an_output_root_has_no_folder_issue(api: Api) -> None:
    ids = await add_sources(api, 1)
    template = {"naming": {"output_folder_mode": "fixed", "output_folder": str(api.output)}}
    response = await api.client.post(
        "/api/batch/resolve", json={"template": template, "source_ids": ids}
    )
    [row] = response.json()["rows"]
    assert row["job"]["output"]["path"] == str(api.output / "Show S01E01.mkv")
    assert "output.folder_required" not in [issue["code"] for issue in row["issues"]]


@pytest.mark.parametrize("route", ["resolve", "resolve-run"])
async def test_an_output_path_of_a_files_override(api: Api, route: str) -> None:
    [sid] = await add_sources(api, 1)
    inside = str(api.output / "Mine.mkv")
    response = await api.client.post(
        f"/api/batch/{route}",
        json={
            "source_ids": [sid],
            "overrides": {sid: [{"op": "replace", "path": "/job/output/path", "value": inside}]},
        },
    )
    assert response.status_code == 200
    body = response.json()
    [row] = body["rows"] if route == "resolve" else body["resolutions"][0]["rows"]
    assert row["job"]["output"]["path"] == inside
    assert "output.folder_required" not in [issue["code"] for issue in row["issues"]]

    outside = str(api.outside / "Mine.mkv")
    response = await api.client.post(
        f"/api/batch/{route}",
        json={
            "source_ids": [sid],
            "overrides": {sid: [{"op": "replace", "path": "/job/output/path", "value": outside}]},
        },
    )
    assert response.status_code == 403
    assert response.json()["code"] == "path.outside_roots"


def outside_subtitle_if(api: Api, encoder: str) -> list[dict[str, Any]]:
    """An override that adds a subtitle outside the roots when the job encodes with
    ``encoder``."""
    return [
        {"op": "test", "path": "/job/video/encoder", "value": encoder},
        {
            "op": "add",
            "path": "/job/subtitles/-",
            "value": {"source": {"path": str(api.outside / "x.srt")}},
        },
    ]


def validated(api: Api, monkeypatch: pytest.MonkeyPatch) -> list[JobSettings]:
    """The jobs the facade validates from now on."""
    jobs: list[JobSettings] = []
    real = api.reframe.jobs.validate

    async def spy(job: JobSettings, *args: Any, **kwargs: Any) -> Any:
        jobs.append(job)
        return await real(job, *args, **kwargs)

    monkeypatch.setattr(api.reframe.jobs, "validate", spy)
    return jobs


def before_service(
    api: Api, monkeypatch: pytest.MonkeyPatch, step: Callable[[], Awaitable[object]]
) -> None:
    """``step`` runs just before each batch resolution of the service."""
    for name in ("resolve", "resolve_batch"):
        real = getattr(api.reframe.batch, name)

        async def spy(*args: Any, _real: Any = real, **kwargs: Any) -> Any:
            await step()
            return await _real(*args, **kwargs)

        monkeypatch.setattr(api.reframe.batch, name, spy)


@pytest.mark.parametrize(
    ("template", "encoder"),
    [
        ({"video": {"encoder": "libx264"}}, "libx264"),
        ("H.264 MKV 1080p", "libx264"),
        ("No Such Preset", "libx265"),
        (None, "libx265"),
    ],
)
async def test_an_override_is_jailed_as_the_template_applies_it(
    api: Api, monkeypatch: pytest.MonkeyPatch, template: object, encoder: str
) -> None:
    """The patch adds a file outside the roots only when its test op passes, that is with the
    template the batch service uses: the file never reaches the service's validation."""
    [sid] = await add_sources(api, 1)
    seen = validated(api, monkeypatch)
    for route in ("resolve", "resolve-run"):
        response = await api.client.post(
            f"/api/batch/{route}",
            json={
                "template": template,
                "source_ids": [sid],
                "overrides": {sid: outside_subtitle_if(api, encoder)},
            },
        )
        assert response.status_code == 403, response.text
        assert response.json()["code"] == "path.outside_roots"
    assert seen == []


@pytest.mark.parametrize("route", ["resolve", "resolve-run"])
async def test_an_override_that_a_changed_preset_lets_out_is_refused(
    api: Api, monkeypatch: pytest.MonkeyPatch, route: str
) -> None:
    """The preset changes just before the service resolves: the test op fails under the old
    preset and passes under the new one, and the outside file never reaches validation."""
    [sid] = await add_sources(api, 1)
    preset = await api.reframe.presets.create(
        JobTemplate(video=VideoSettings(encoder="libx264")), "Mine"
    )
    assert isinstance(preset, Preset)
    changed = preset.model_copy(
        update={"video": preset.video.model_copy(update={"encoder": "libx265"})}
    )
    before_service(api, monkeypatch, lambda: api.reframe.presets.save(changed))
    seen = validated(api, monkeypatch)
    response = await api.client.post(
        f"/api/batch/{route}",
        json={
            "template": "Mine",
            "source_ids": [sid],
            "overrides": {sid: outside_subtitle_if(api, "libx265")},
        },
    )
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "path.outside_roots"
    assert seen == []


async def test_derive_takes_a_job_saved_outside_the_output_roots(api: Api) -> None:
    [sid] = await add_sources(api, 1)
    job = {
        "source": {"path": str(api.media / "Show S01E01.mkv")},
        "output": {"path": str(api.media / "Show S01E01 (1).mkv")},
    }
    response = await api.client.post(
        "/api/batch/derive", json={"job": job, "source_id": sid, "sections": ["video"]}
    )
    assert response.status_code == 200
