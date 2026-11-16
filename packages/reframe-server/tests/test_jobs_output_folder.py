"""Web mode: an output outside the output roots is the ``output.folder_required`` issue, an
in-place edit of a source in a media root ``inplace.not_allowed``, with fixes, wherever a job is
drafted or checked."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from reframe.jsonpatch import apply_patch
from reframe_testing.server import Api, ApiFactory

pytestmark = pytest.mark.anyio

DRAFTED = "Show S01E01 (1).mkv"
"""The default naming saves beside the source, under a free name."""


async def drafted(api: Api, route: str = "draft", **request: Any) -> dict[str, Any]:
    response = await api.client.post(
        f"/api/jobs/{route}", json={"source_id": await api.add_source(), **request}
    )
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


def folder_issue(
    issues: list[dict[str, Any]], code: str = "output.folder_required"
) -> dict[str, Any]:
    [issue] = [i for i in issues if i["code"] == code]
    return issue


def codes(issues: list[dict[str, Any]]) -> list[str]:
    return [issue["code"] for issue in issues]


async def test_a_draft_beside_the_source_has_the_issue_with_both_fixes(api: Api) -> None:
    draft = await drafted(api)
    assert draft["job"]["output"]["path"] == str(api.media / DRAFTED)
    issue = folder_issue(draft["issues"])
    assert (issue["severity"], issue["path"]) == ("error", "output.path")
    settings_fix, job_fix = issue["fixes"]
    assert settings_fix["target"] == "settings"
    assert settings_fix["patch"] == [
        {"op": "add", "path": "/output/naming/output_folder_mode", "value": "fixed"},
        {"op": "add", "path": "/output/naming/output_folder", "value": str(api.output)},
    ]
    assert job_fix["target"] == "job"
    assert job_fix["patch"] == [
        {"op": "replace", "path": "/output/path", "value": str(api.output / DRAFTED)}
    ]


async def test_the_settings_fix_makes_drafts_land_in_the_output_root(api: Api) -> None:
    [settings_fix, _] = folder_issue((await drafted(api))["issues"])["fixes"]
    changed = await api.client.put("/api/settings", json=settings_fix["patch"])
    assert changed.status_code == 200, changed.text
    draft = await drafted(api)
    assert draft["job"]["output"]["path"] == str(api.output / "Show S01E01.mkv")
    assert "output.folder_required" not in [i["code"] for i in draft["issues"]]
    plan = await api.client.post("/api/jobs/plan", json={"job": draft["job"]})
    assert plan.status_code == 200


async def test_validate_reports_the_outside_output_and_the_job_fix_clears_it(api: Api) -> None:
    """Validation never looks at the outside file: an existing one gives no overwrite issue."""
    job = (await drafted(api))["job"]
    existing = api.outside / "Existing.mkv"
    existing.write_bytes(b"")
    job["output"]["path"] = str(existing)
    response = await api.client.post("/api/jobs/validate", json={"job": job})
    assert response.status_code == 200
    about_output = [i["code"] for i in response.json() if i["path"] == "output.path"]
    assert about_output == ["output.folder_required"]
    [_, job_fix] = folder_issue(response.json())["fixes"]
    fixed = apply_patch(job, job_fix["patch"])
    again = await api.client.post("/api/jobs/validate", json={"job": fixed})
    assert "output.folder_required" not in [issue["code"] for issue in again.json()]


@pytest.mark.parametrize("route", ["plan", "dry-run"])
async def test_plan_and_dry_run_refuse_the_outside_output(api: Api, route: str) -> None:
    job = (await drafted(api))["job"]
    api.fake.clear_log()
    response = await api.client.post(f"/api/jobs/{route}", json={"job": job})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "jobs.invalid"
    assert [issue["code"] for issue in body["issues"]] == ["output.folder_required"]
    assert api.fake.calls("ffmpeg") == []


async def test_a_remux_draft_that_writes_a_new_file_has_the_issue(api: Api) -> None:
    draft = await drafted(api, "draft-remux", edit_in_place=False)
    assert draft["job"]["output"]["path"] == str(api.media / DRAFTED)
    folder_issue(draft["issues"])


async def test_an_in_place_edit_is_an_issue_whose_fix_writes_a_new_file(api: Api) -> None:
    """The naming fixes cannot move an in-place edit: it writes its source."""
    draft = await drafted(api, "draft-remux")
    job = draft["job"]
    assert job["output"]["edit_in_place"] is True
    assert "output.folder_required" not in codes(draft["issues"])
    issue = folder_issue(draft["issues"], "inplace.not_allowed")
    assert (issue["severity"], issue["path"]) == ("error", "output.edit_in_place")
    validated = await api.client.post("/api/jobs/validate", json={"job": job})
    assert validated.status_code == 200
    assert "inplace.not_allowed" in codes(validated.json())
    [fix] = issue["fixes"]
    assert fix["patch"] == [
        {"op": "replace", "path": "/output/edit_in_place", "value": False},
        {"op": "replace", "path": "/output/path", "value": str(api.output / "Show S01E01.mkv")},
    ]
    again = await api.client.post(
        "/api/jobs/validate", json={"job": apply_patch(job, fix["patch"])}
    )
    assert {"inplace.not_allowed", "output.folder_required"}.isdisjoint(codes(again.json()))


@pytest.mark.parametrize("route", ["geometry", "hdr-metadata"])
async def test_routes_that_write_nothing_take_the_outside_output(api: Api, route: str) -> None:
    job = (await drafted(api))["job"]
    response = await api.client.post(f"/api/jobs/{route}", json={"job": job})
    assert response.status_code == 200


async def test_a_source_outside_the_media_roots_is_still_refused(api: Api) -> None:
    job = (await drafted(api))["job"]
    job["source"]["path"] = str(api.outside / "Other.mkv")
    response = await api.client.post("/api/jobs/validate", json={"job": job})
    assert response.status_code == 403
    assert response.json()["code"] == "path.outside_roots"


async def test_a_relative_output_path_is_invalid(api: Api) -> None:
    job = (await drafted(api))["job"]
    job["output"]["path"] = "out.mkv"
    response = await api.client.post("/api/jobs/validate", json={"job": job})
    assert response.status_code == 400
    assert response.json()["code"] == "path.invalid"


@pytest.mark.parametrize(("roots", "targets"), [(0, []), (2, ["settings"])])
async def test_the_fixes_depend_on_the_output_roots(
    make_api: ApiFactory, tmp_path: Path, roots: int, targets: list[str]
) -> None:
    folders = [tmp_path / f"out{n}" for n in range(roots)]
    async with make_api(output_roots=folders) as api:
        issue = folder_issue((await drafted(api))["issues"])
        in_place = folder_issue(
            (await drafted(api, "draft-remux"))["issues"], "inplace.not_allowed"
        )
    assert [fix["target"] for fix in issue["fixes"]] == targets
    assert len(in_place["fixes"]) == len(targets)
    if folders:
        assert issue["fixes"][0]["patch"][1]["value"] == str(folders[0])
        assert in_place["fixes"][0]["patch"][1]["value"] == str(folders[0] / "Show S01E01.mkv")


async def test_desktop_mode_drafts_beside_the_source(make_api: ApiFactory) -> None:
    async with make_api(mode="desktop") as api:
        draft = await drafted(api)
        job = draft["job"]
        validated = await api.client.post("/api/jobs/validate", json={"job": job})
        in_place = await drafted(api, "draft-remux")
    assert job["output"]["path"] == str(api.media / DRAFTED)
    assert "output.folder_required" not in codes(draft["issues"])
    assert "output.folder_required" not in codes(validated.json())
    assert "inplace.not_allowed" not in codes(in_place["issues"])
