"""The task routes: the list, one task's state and result, cancel."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

import pytest

from reframe.tasks import TaskContext
from reframe_testing.server import Api

pytestmark = pytest.mark.anyio


async def _done(_ctx: TaskContext) -> dict[str, int]:
    return {"files": 2}


async def test_a_finished_task_is_listed_with_its_result(api: Api) -> None:
    task = api.reframe.tasks.start("probe_sources", _done, result_json=lambda value: value)
    await api.reframe.tasks.wait(task.id)
    listed = (await api.client.get("/api/tasks")).json()
    assert [(t["id"], t["state"]) for t in listed if t["id"] == task.id] == [(task.id, "done")]
    response = await api.client.get(f"/api/tasks/{task.id}")
    assert response.status_code == 200
    assert (response.json()["state"], response.json()["result"]) == ("done", {"files": 2})


async def test_kind_keeps_the_tasks_of_one_kind(api: Api) -> None:
    frames = api.reframe.tasks.start("frames", _done, result_json=lambda value: value)
    crop = api.reframe.tasks.start("cropdetect", _done, result_json=lambda value: value)
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


@pytest.mark.needs_ffmpeg
async def test_a_task_answer_names_no_server_folder(
    api: Api, fixture_media: Callable[[str], Path]
) -> None:
    """A frames task names its PNGs in the cache; a client gets them by signed URLs."""
    task = api.reframe.sources.frames(api.add_fixture("multitrack", fixture_media), count=1)
    await api.reframe.tasks.wait(task.id)
    cache = str(api.reframe.cache_dir)
    one = await api.client.get(f"/api/tasks/{task.id}")
    [frame] = one.json()["result"]["frames"]
    assert frame["path"].startswith("<cache>")
    listed = await api.client.get("/api/tasks")
    assert task.id in listed.text
    assert (cache in one.text, cache in listed.text) == (False, False)


async def test_only_the_server_folders_are_hidden(api: Api) -> None:
    """A path that only shares a server folder's text is another path and comes back whole."""
    data = api.reframe.data_dir
    own = [f"{data}2/film.mkv", f"/mnt{data}/film.mkv"]

    async def fetch(_ctx: TaskContext) -> dict[str, object]:
        return {"own": own, "by_path": {f"{data}/tools": 1}}

    task = api.reframe.tasks.start(
        "tools_fetch", fetch, message=f"Checking {data} first", result_json=lambda value: value
    )
    await api.reframe.tasks.wait(task.id)
    answer = (await api.client.get(f"/api/tasks/{task.id}")).json()
    assert answer["message"] == "Checking <data> first"
    assert answer["result"] == {"own": own, "by_path": {"<data>/tools": 1}}
