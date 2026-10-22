"""The job routes: draft, validate, plan, geometry, explain, remux draft, dry run, HDR
metadata."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from reframe.models import JobDraft, JobSettings, MediaSource
from reframe_server import security
from reframe_server.config import ServerConfig
from reframe_server.errors import ProblemError
from reframe_testing import fake_tools as ft
from reframe_testing.server import PROBE_RULE, ROOT, Api

pytestmark = pytest.mark.anyio

PROBES = ROOT / "testdata" / "probes" / "fixtures"


def serve(api: Api, path: Path, recording: str) -> None:
    """The fake ffprobe answers for ``path`` with ``recording``, for the rest with
    ``multitrack``."""
    probe = ft.Rule(
        tool="ffprobe",
        argv_has=["-show_streams", str(path)],
        actions=[{"stdout_file": str(PROBES / f"{recording}.json")}],
    )
    rules = [probe]
    frames = PROBES / f"{recording}.frames.json"
    if frames.exists():
        rules.append(
            ft.Rule(
                tool="ffprobe", argv_has=["-show_frames"], actions=[{"stdout_file": str(frames)}]
            )
        )
    api.fake.set_scenario(ft.Scenario([*rules, PROBE_RULE]))


async def add_source(
    api: Api, name: str = "Show S01E01.mkv", recording: str | None = None
) -> tuple[str, Path]:
    path = api.media_file(name)
    if recording is not None:
        serve(api, path, recording)
    assert isinstance(await api.reframe.sources.probe(path), MediaSource)
    return api.app.state.sources.add(path), path


async def job_of(api: Api, path: Path, preset: str | None = None) -> dict[str, Any]:
    """A drafted job of ``path`` that writes below the output root."""
    draft = await api.reframe.jobs.draft(path, preset)
    assert isinstance(draft, JobDraft)
    job = draft.job.model_dump(mode="json")
    job["output"]["path"] = str(api.output / f"{path.stem}.mkv")
    return job


def refuse(monkeypatch: pytest.MonkeyPatch, name: str) -> list[object]:
    """Replace ``security.<name>`` with a jail that refuses every path; returns what it got."""
    seen: list[object] = []

    def jail(_config: ServerConfig, value: object) -> None:
        seen.append(value)
        raise ProblemError(403, "path.outside_roots", "Outside the roots")

    monkeypatch.setattr(security, name, jail)
    return seen


async def test_operation_ids(api: Api) -> None:
    paths = (await api.client.get("/api/openapi.json")).json()["paths"]
    names = {
        "draft": "jobs_draft",
        "validate": "jobs_validate",
        "plan": "jobs_plan",
        "geometry": "jobs_geometry",
        "explain": "jobs_explain",
        "draft-remux": "jobs_draft_remux",
        "dry-run": "jobs_dry_run",
        "hdr-metadata": "jobs_hdr_metadata",
    }
    assert {route: paths[f"/api/jobs/{route}"]["post"]["operationId"] for route in names} == names


async def test_draft_uses_the_source_and_the_preset(api: Api) -> None:
    sid, path = await add_source(api)
    response = await api.client.post(
        "/api/jobs/draft", json={"source_id": sid, "preset_id": "h264-mkv-1080p"}
    )
    assert response.status_code == 200
    job = response.json()["job"]
    assert job["source"]["path"] == str(path)
    assert job["preset_id"] == "h264-mkv-1080p"
    assert job["video"]["encoder"] == "libx264"
    assert response.json()["naming"]["relative_path"] == "Show S01E01.mkv"


async def test_an_unknown_source_id_is_404(api: Api) -> None:
    response = await api.client.post("/api/jobs/draft", json={"source_id": "f00d"})
    assert response.status_code == 404
    assert response.json()["code"] == "source.unknown"


async def test_validate_answers_200_with_the_issues(api: Api) -> None:
    _, path = await add_source(api)
    job = await job_of(api, path)
    job["source"]["path"] = str(api.media / "gone.mkv")
    response = await api.client.post("/api/jobs/validate", json={"job": job})
    assert response.status_code == 200
    assert [issue["code"] for issue in response.json()] == ["source.probe_failed"]


async def test_plan_gives_the_command(api: Api) -> None:
    _, path = await add_source(api)
    job = await job_of(api, path)
    response = await api.client.post("/api/jobs/plan", json={"job": job})
    assert response.status_code == 200
    plan = response.json()
    assert plan["job_type"] == "encode"
    argv = plan["steps"][0]["argv"]
    assert str(path) in argv
    assert any(arg.startswith(str(api.output / "Show S01E01")) for arg in argv)


async def test_a_job_with_errors_has_no_plan(api: Api) -> None:
    _, path = await add_source(api)
    job = await job_of(api, path)
    job["video"]["encoder"] = "no-such-encoder"
    response = await api.client.post("/api/jobs/plan", json={"job": job})
    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == "jobs.invalid"
    assert "encoder.unknown" in [issue["code"] for issue in body["issues"]]


@pytest.mark.parametrize(("deinterlace", "top"), [(True, 2), (False, 0)])
async def test_geometry_crops_an_interlaced_source_as_the_builder_does(
    api: Api, deinterlace: bool, top: int
) -> None:
    """Interlaced 4:2:0 crops in steps of 4; once deinterlaced, in steps of 2."""
    _, path = await add_source(api, "Old.mkv", "interlaced.mkv")
    job = await job_of(api, path)
    if not deinterlace:
        del job["filters"]["deinterlace"]
    job["dimensions"]["crop"] = {"mode": "manual", "rect": {"top": 2, "bottom": 2}}
    response = await api.client.post("/api/jobs/geometry", json={"job": job})
    assert response.status_code == 200
    body = response.json()
    assert body["source"]["interlaced"] is True
    assert body["geometry"]["crop"]["top"] == top
    assert body["geometry"]["cropped_height"] == 240 - 2 * top


async def test_geometry_of_a_copied_video_is_the_source_only(api: Api) -> None:
    _, path = await add_source(api)
    job = await job_of(api, path)
    job["video"]["passthrough"] = True
    body = (await api.client.post("/api/jobs/geometry", json={"job": job})).json()
    assert body["source"]["width"] == 320
    assert body["geometry"] is None


async def test_geometry_of_a_source_without_video(api: Api) -> None:
    _, path = await add_source(api, "Show.en.srt", "text-subs.en.srt")
    job = JobSettings.model_validate({"source": {"path": str(path)}}).model_dump(mode="json")
    body = (await api.client.post("/api/jobs/geometry", json={"job": job})).json()
    assert body == {"source": None, "geometry": None}


async def test_a_job_whose_source_is_gone_is_a_probe_problem(api: Api) -> None:
    _, path = await add_source(api)
    job = await job_of(api, path)
    job["source"]["path"] = str(api.media / "gone.mkv")
    response = await api.client.post("/api/jobs/hdr-metadata", json={"job": job})
    assert response.status_code == 404
    assert response.json()["code"] == "probe.not_found"


async def test_explain_with_a_container(api: Api) -> None:
    """WebM cannot hold the default preset's AAC: the defaults lint says so."""
    sid, _ = await add_source(api)
    response = await api.client.post(
        "/api/jobs/explain", json={"source_id": sid, "container": "webm"}
    )
    assert response.status_code == 200
    draft = response.json()
    assert [track["source_stream"] for track in draft["audio"]] == [1, 2, 3]
    assert "defaults.codec_not_in_container" in [issue["code"] for issue in draft["issues"]]


async def test_explain_takes_a_template_or_a_preset_name(api: Api) -> None:
    sid, _ = await add_source(api)
    template = {"audio_defaults": {"selection": {"languages": ["jpn"]}}}
    by_template = await api.client.post(
        "/api/jobs/explain", json={"source_id": sid, "template": template}
    )
    assert [track["source_stream"] for track in by_template.json()["audio"]] == [1]
    by_name = await api.client.post(
        "/api/jobs/explain", json={"source_id": sid, "template": "No Such Preset"}
    )
    assert by_name.status_code == 200
    assert by_name.json()["issues"][0]["code"] == "preset.not_found"


@pytest.mark.parametrize("edit_in_place", [True, False])
async def test_draft_remux(api: Api, edit_in_place: bool) -> None:
    sid, path = await add_source(api)
    response = await api.client.post(
        "/api/jobs/draft-remux",
        json={"source_id": sid, "preset_id": "h264-mkv-1080p", "edit_in_place": edit_in_place},
    )
    assert response.status_code == 200
    job = response.json()["job"]
    assert job["preset_id"] == "h264-mkv-1080p"
    assert job["video"]["passthrough"] is True
    assert job["output"]["edit_in_place"] is edit_in_place
    assert job["source"]["path"] == str(path)


async def test_dry_run_gives_what_ffmpeg_refuses_as_issues(api: Api) -> None:
    _, path = await add_source(api)
    job = await job_of(api, path)
    job["video"]["custom_params"] = "foo=1"
    refused = ft.Rule(
        tool="ffmpeg",
        argv_has=["-frames:v"],
        actions=[ft.stderr("[libx265 @ 0x1] Unknown option foo\n")],
        exit_code=1,
    )
    api.fake.set_scenario(ft.Scenario([refused, PROBE_RULE]))
    response = await api.client.post("/api/jobs/dry-run", json={"job": job})
    assert response.status_code == 200
    assert [issue["code"] for issue in response.json()] == ["encoder.custom_param_rejected"]


async def test_hdr_metadata_is_a_patch_from_the_source(api: Api) -> None:
    _, path = await add_source(api, "HDR.mkv", "hdr10.mkv")
    job = await job_of(api, path, "h265-mkv-2160p-4k")
    response = await api.client.post("/api/jobs/hdr-metadata", json={"job": job})
    assert response.status_code == 200
    patch = {op["path"]: op["value"] for op in response.json()}
    assert patch["/video/advanced/max-cll"] == "1000,400"
    assert "/video/advanced/master-display" in patch


@pytest.mark.parametrize("route", ["validate", "plan", "geometry", "dry-run", "hdr-metadata"])
async def test_the_job_passes_the_jail_before_any_file_is_read(
    api: Api, monkeypatch: pytest.MonkeyPatch, route: str
) -> None:
    _, path = await add_source(api)
    job = await job_of(api, path)
    job["source"]["path"] = str(api.media_file("Not Probed.mkv"))
    seen = refuse(monkeypatch, "jail_job")
    api.fake.clear_log()
    response = await api.client.post(f"/api/jobs/{route}", json={"job": job})
    assert response.status_code == 403
    assert response.json()["code"] == "path.outside_roots"
    assert [str(j.source.path) for j in seen if isinstance(j, JobSettings)] == [
        job["source"]["path"]
    ]
    assert api.fake.calls() == []


async def test_explain_jails_the_templates_naming_folder(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid, _ = await add_source(api)
    seen = refuse(monkeypatch, "jail_write")
    folder = str(api.output / "Shows")
    template = {"naming": {"output_folder_mode": "fixed", "output_folder": folder}}
    response = await api.client.post(
        "/api/jobs/explain", json={"source_id": sid, "template": template}
    )
    assert response.status_code == 403
    assert [str(value) for value in seen] == [folder]
