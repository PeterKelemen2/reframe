"""The task routes: the list, one task's state and result, cancel."""

from __future__ import annotations

import asyncio

import pytest

from reframe.tasks import TaskContext
from reframe_testing.server import Api

pytestmark = pytest.mark.anyio


async def _done(_ctx: TaskContext) -> dict[str, int]:
    return {"files": 2}


async def test_the_routes_have_stable_operation_ids(api: Api) -> None:
    paths = (await api.client.get("/api/openapi.json")).json()["paths"]
    assert paths["/api/tasks"]["get"]["operationId"] == "tasks_snapshot"
    assert paths["/api/tasks/{task_id}"]["get"]["operationId"] == "tasks_get"
    assert paths["/api/tasks/{task_id}/cancel"]["post"]["operationId"] == "tasks_cancel"


async def test_a_finished_task_is_listed_with_its_result(api: Api) -> None:
    task = api.reframe.tasks.start("probe_folder", _done)
    await api.reframe.tasks.wait(task.id)
    listed = (await api.client.get("/api/tasks")).json()
    assert [(t["id"], t["state"]) for t in listed if t["id"] == task.id] == [(task.id, "done")]
    response = await api.client.get(f"/api/tasks/{task.id}")
    assert response.status_code == 200
    assert (response.json()["state"], response.json()["result"]) == ("done", {"files": 2})


async def test_kind_keeps_the_tasks_of_one_kind(api: Api) -> None:
    frames = api.reframe.tasks.start("frames", _done)
    crop = api.reframe.tasks.start("cropdetect", _done)
    listed = (await api.client.get("/api/tasks", params={"kind": "frames"})).json()
    ids = [t["id"] for t in listed]
    assert frames.id in ids
    assert crop.id not in ids
    assert {t["kind"] for t in listed} == {"frames"}


async def test_cancel_a_running_task(api: Api) -> None:
    async def forever(_ctx: TaskContext) -> None:
        await asyncio.Event().wait()

    task = api.reframe.tasks.start("loudness", forever)
    response = await api.client.post(f"/api/tasks/{task.id}/cancel")
    assert (response.status_code, response.json()) == (200, {"cancelled": True})
    await asyncio.wait_for(api.reframe.tasks.wait(task.id), 10)
    assert (await api.client.get(f"/api/tasks/{task.id}")).json()["state"] == "cancelled"
    again = await api.client.post(f"/api/tasks/{task.id}/cancel")
    assert again.json() == {"cancelled": False}


@pytest.mark.parametrize(
    ("method", "path"), [("GET", "/api/tasks/{}"), ("POST", "/api/tasks/{}/cancel")]
)
async def test_an_unknown_task_is_404(api: Api, method: str, path: str) -> None:
    response = await api.client.request(method, path.format("t-none-1"))
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "tasks.unknown"
