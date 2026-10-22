"""The queue routes on the real facade and the fake FFmpeg: adding jobs (jail, output path,
attach, position), the actions on one job or on the whole queue, the order, the log and the
when-done setting."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from typing import Any

import pytest

from reframe.models import JobDraft, JobSettings
from reframe_server.routers.queue import LOG_CHUNK
from reframe_testing import fake_tools as ft
from reframe_testing.server import PROBE_RULE, Api, ApiFactory

pytestmark = pytest.mark.anyio

HANG = ft.Scenario(
    [
        PROBE_RULE,
        ft.Rule(
            tool="ffmpeg",
            argv_has=["matroska"],
            actions=[ft.progress(blocks=1, end=False), ft.hang()],
        ),
    ]
)
"""Each encode prints one progress block, then runs until it is stopped."""


async def draft_job(api: Api, name: str = "Show S01E01.mkv") -> dict[str, Any]:
    """A job for a new file below the media root, written below the output root, as a client
    sends it."""
    source = api.media_file(name)
    draft = await api.reframe.jobs.draft(source, output=api.output / f"{source.stem}.mkv")
    assert isinstance(draft, JobDraft)
    data: dict[str, Any] = draft.job.model_dump(mode="json")
    return data


async def add_jobs(api: Api, *names: str) -> list[str]:
    jobs = [await draft_job(api, name) for name in names]
    response = await api.client.post("/api/queue", json={"jobs": jobs})
    assert response.status_code == 201, response.text
    return [job["id"] for job in response.json()]


async def snapshot(api: Api) -> list[tuple[str, str]]:
    """``(id, state)`` of each job, in queue order."""
    response = await api.client.get("/api/queue")
    assert response.status_code == 200
    return [(job["id"], job["state"]) for job in response.json()["jobs"]]


async def poll(condition: Callable[[], bool], limit: float = 20.0) -> None:
    deadline = time.monotonic() + limit
    while not condition():
        assert time.monotonic() < deadline, "condition not met in time"
        await asyncio.sleep(0.01)


async def ended(api: Api, *job_ids: str) -> None:
    await asyncio.wait_for(api.reframe.queue.wait(job_ids), 30)


async def encoding(api: Api, *job_ids: str) -> None:
    """Until each job's encode has printed its first progress block."""

    def started(job_id: str) -> bool:
        job = api.reframe.queue.get(job_id)
        assert job is not None
        return job.progress is not None and job.progress.output_size is not None

    await poll(lambda: all(started(job_id) for job_id in job_ids))


async def test_jobs_are_added_in_order_at_the_position(api: Api) -> None:
    [old] = await add_jobs(api, "Old.mkv")
    first, second = await draft_job(api, "First.mkv"), await draft_job(api, "Second.mkv")
    response = await api.client.post("/api/queue", json={"jobs": [first, second], "position": 0})
    assert response.status_code == 201
    added = response.json()
    assert [job["settings"]["source"]["path"] for job in added] == [
        first["source"]["path"],
        second["source"]["path"],
    ]
    assert [job["state"] for job in added] == ["waiting", "waiting"]
    assert await snapshot(api) == [
        (added[0]["id"], "waiting"),
        (added[1]["id"], "waiting"),
        (old, "waiting"),
    ]


async def test_a_job_without_an_output_path_is_refused(api: Api) -> None:
    """The jail cannot check an output that the queue would name later."""
    named, unnamed = await draft_job(api, "Named.mkv"), await draft_job(api, "Unnamed.mkv")
    unnamed["output"]["path"] = None
    response = await api.client.post("/api/queue", json={"jobs": [named, unnamed]})
    assert response.status_code == 422
    problem = response.json()
    assert problem["code"] == "output.no_path"
    assert "jobs[1]" in problem["detail"]
    assert await snapshot(api) == []


async def test_attach_needs_an_open_event_connection(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[str] = []

    def client_open(client_id: str) -> bool:
        asked.append(client_id)
        return client_id == "open-client"

    monkeypatch.setattr(api.app.state.hub, "client_open", client_open)
    job = await draft_job(api)
    refused = await api.client.post("/api/queue", json={"jobs": [job], "attach": "gone-client"})
    assert refused.status_code == 409
    assert refused.json()["code"] == "queue.attach_unknown_client"
    assert await snapshot(api) == []
    accepted = await api.client.post("/api/queue", json={"jobs": [job], "attach": "open-client"})
    assert accepted.status_code == 201
    assert asked == ["gone-client", "open-client"]


async def test_cancel_retry_and_remove_act_on_their_job(api: Api) -> None:
    first, second = await add_jobs(api, "First.mkv", "Second.mkv")
    cancel = await api.client.post(f"/api/queue/{first}/cancel")
    assert (cancel.status_code, cancel.content) == (204, b"")
    assert await snapshot(api) == [(first, "cancelled"), (second, "waiting")]
    retry = await api.client.post(f"/api/queue/{first}/retry")
    assert retry.status_code == 200
    assert (retry.json()["id"], retry.json()["state"]) == (first, "waiting")
    assert (await api.client.delete(f"/api/queue/{first}")).status_code == 204
    assert await snapshot(api) == [(second, "waiting")]


async def test_reorder_moves_the_named_jobs_among_their_places(api: Api) -> None:
    a, b, c = await add_jobs(api, "A.mkv", "B.mkv", "C.mkv")
    response = await api.client.put("/api/queue/order", json={"job_ids": [c, a]})
    assert response.status_code == 204
    assert [job_id for job_id, _ in await snapshot(api)] == [c, b, a]


async def test_reorder_with_a_job_twice_is_refused(api: Api) -> None:
    a, b = await add_jobs(api, "A.mkv", "B.mkv")
    response = await api.client.put("/api/queue/order", json={"job_ids": [b, a, b]})
    assert response.status_code == 422
    assert response.json()["errors"][0]["loc"] == ["body", "job_ids"]
    assert [job_id for job_id, _ in await snapshot(api)] == [a, b]


async def test_duplicate_adds_a_copy_right_after_the_job(api: Api) -> None:
    first, second = await add_jobs(api, "First.mkv", "Second.mkv")
    response = await api.client.post(f"/api/queue/{first}/duplicate")
    assert response.status_code == 201
    copy = response.json()
    original = api.reframe.queue.get(first)
    assert original is not None
    assert copy["id"] not in (first, second)
    assert JobSettings.model_validate(copy["settings"]) == original.settings
    assert [job_id for job_id, _ in await snapshot(api)] == [first, copy["id"], second]


async def test_duplicate_checks_the_saved_job_against_the_roots(api: Api) -> None:
    """The saved queue may hold a job from a run with other roots."""
    link = api.media / "escape"
    try:
        link.symlink_to(api.outside, target_is_directory=True)
    except OSError as exc:  # Windows without the symlink privilege
        pytest.skip(f"cannot make a symbolic link: {exc}")
    job = JobSettings.model_validate(await draft_job(api))
    job.source.path = link / "Show.mkv"
    saved = await api.reframe.queue.add(job)
    response = await api.client.post(f"/api/queue/{saved.id}/duplicate")
    assert (response.status_code, response.json()["code"]) == (403, "path.outside_roots")
    assert len(await snapshot(api)) == 1


@pytest.mark.parametrize(
    ("method", "path"),
    [("POST", "/api/queue/{}/duplicate"), ("GET", "/api/queue/{}/log")],
)
async def test_an_unknown_job_is_404(api: Api, method: str, path: str) -> None:
    response = await api.client.request(method, path.format("no-such-job"))
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "queue.unknown_job"


async def test_a_job_added_through_the_api_runs_to_done(api: Api) -> None:
    [job_id] = await add_jobs(api, "Show.mkv")
    response = await api.client.post("/api/queue/start")
    assert (response.status_code, response.content) == (204, b"")
    await ended(api, job_id)
    [job] = (await api.client.get("/api/queue")).json()["jobs"]
    assert job["state"] == "done", job["error"]
    assert job["output_path"] == str(api.output / "Show.mkv")
    assert (api.output / "Show.mkv").is_file()
    log = (await api.client.get(f"/api/queue/{job_id}/log")).json()["text"]
    assert f"Reframe job {job_id}" in log
    assert "Job done" in log


async def test_a_running_job_is_cancelled_not_removed(api: Api) -> None:
    api.fake.set_scenario(HANG)
    [job_id] = await add_jobs(api, "Show.mkv")
    await api.client.post("/api/queue/start")
    await encoding(api, job_id)
    refused = await api.client.delete(f"/api/queue/{job_id}")
    assert (refused.status_code, refused.json()["code"]) == (409, "queue.job_state")
    assert (await api.client.post(f"/api/queue/{job_id}/cancel")).status_code == 204
    assert await snapshot(api) == [(job_id, "cancelled")]  # the answer came after the stop
    assert api.fake.kill_leftovers() == []
    assert (await api.client.delete(f"/api/queue/{job_id}")).status_code == 204


async def test_pause_and_resume_one_job_or_all(api: Api) -> None:
    await api.reframe.settings.update(
        [{"op": "replace", "path": "/queue/parallel_jobs", "value": 2}]
    )
    api.fake.set_scenario(HANG)
    first, second = await add_jobs(api, "First.mkv", "Second.mkv")
    await api.client.post("/api/queue/start")
    await encoding(api, first, second)
    assert (await api.client.post(f"/api/queue/{first}/pause")).status_code == 204
    assert await snapshot(api) == [(first, "paused"), (second, "running")]
    assert (await api.client.post("/api/queue/pause")).status_code == 204
    assert await snapshot(api) == [(first, "paused"), (second, "paused")]
    assert (await api.client.post(f"/api/queue/{second}/resume")).status_code == 204
    assert await snapshot(api) == [(first, "paused"), (second, "running")]
    assert (await api.client.post("/api/queue/resume")).status_code == 204
    assert await snapshot(api) == [(first, "running"), (second, "running")]
    assert (await api.client.post("/api/queue/cancel")).status_code == 204
    assert await snapshot(api) == [(first, "cancelled"), (second, "cancelled")]


async def test_start_with_job_ids_leaves_the_other_jobs_waiting(api: Api) -> None:
    first, second = await add_jobs(api, "First.mkv", "Second.mkv")
    response = await api.client.post("/api/queue/start", json={"job_ids": [second]})
    assert response.status_code == 204
    await ended(api, second)
    assert await snapshot(api) == [(first, "waiting"), (second, "done")]


async def test_stop_takes_no_new_job(api: Api) -> None:
    api.fake.set_scenario(HANG)
    first, second = await add_jobs(api, "First.mkv", "Second.mkv")
    await api.client.post("/api/queue/start")
    await encoding(api, first)
    assert (await api.client.post("/api/queue/stop")).status_code == 204
    await api.client.post(f"/api/queue/{first}/cancel")
    await asyncio.sleep(0.1)  # a job that the runner took would be running by now
    assert await snapshot(api) == [(first, "cancelled"), (second, "waiting")]


async def test_the_log_is_read_from_a_byte_offset(api: Api) -> None:
    """Before the first run there is no file: the answer is empty, not an error."""
    [job_id] = await add_jobs(api, "Show.mkv")
    url = f"/api/queue/{job_id}/log"
    assert (await api.client.get(url)).json() == {"text": "", "next": 0, "more": False}
    path = api.reframe.queue.log_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"run 1\n")
    first = (await api.client.get(url)).json()
    assert first == {"text": "run 1\n", "next": 6, "more": False}
    with path.open("ab") as file:
        file.write("run 2 ✓\n".encode())
    second = (await api.client.get(url, params={"from": first["next"]})).json()
    assert second == {"text": "run 2 ✓\n", "next": 16, "more": False}
    assert (await api.client.get(url, params={"from": 16})).json()["text"] == ""


async def test_a_character_cut_by_the_chunk_end_comes_whole_next_time(api: Api) -> None:
    [job_id] = await add_jobs(api, "Show.mkv")
    path = api.reframe.queue.log_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"a" * (LOG_CHUNK - 1) + "é!\n".encode())
    url = f"/api/queue/{job_id}/log"
    first = (await api.client.get(url)).json()
    assert first["text"] == "a" * (LOG_CHUNK - 1)
    assert (first["next"], first["more"]) == (LOG_CHUNK - 1, True)
    second = (await api.client.get(url, params={"from": first["next"]})).json()
    assert second == {"text": "é!\n", "next": LOG_CHUNK + 3, "more": False}


async def test_when_done_is_saved_in_the_settings(api: Api) -> None:
    response = await api.client.put("/api/queue/when-done", json={"when_done": "sleep"})
    assert response.status_code == 200
    assert response.json() == {"when_done": "sleep"}
    saved = json.loads(api.reframe.settings.path.read_text(encoding="utf-8"))
    assert saved["queue"]["when_done"] == "sleep"


@pytest.mark.parametrize(("when_done", "kept"), [("sleep", False), ("shutdown", True)])
async def test_when_done_cancels_a_countdown_for_another_action(
    api: Api, when_done: str, kept: bool
) -> None:
    """The user changed what happens: an action they no longer chose must not run, also when
    the new choice is another power action."""
    countdown = api.reframe.power.schedule("shutdown", reason="1 job done")
    response = await api.client.put("/api/queue/when-done", json={"when_done": when_done})
    assert response.status_code == 200
    pending = api.reframe.power.pending
    if kept:
        assert pending is not None
        assert pending.countdown_id == countdown
    else:
        assert pending is None


async def test_a_queue_answer_names_no_server_folder(api: Api) -> None:
    """The log is read through its route: a client is not told where the server keeps it."""
    data = str(api.reframe.data_dir)
    added = await api.client.post("/api/queue", json={"jobs": [await draft_job(api)]})
    [job] = added.json()
    assert job["log_path"].startswith("<data>")
    await api.client.post(f"/api/queue/{job['id']}/cancel")
    answers = [
        added,
        await api.client.get("/api/queue"),
        await api.client.post(f"/api/queue/{job['id']}/retry"),
        await api.client.post(f"/api/queue/{job['id']}/duplicate"),
    ]
    assert [answer.status_code for answer in answers] == [201, 200, 200, 201]
    assert [data in answer.text for answer in answers] == [False] * 4


async def test_a_jobs_own_paths_come_back_as_sent(make_api: ApiFactory) -> None:
    """Desktop mode: the user may write into a folder the server also uses, and the editor
    loads the settings back."""
    async with make_api(mode="desktop") as api:
        job = await draft_job(api)
        job["output"]["path"] = str(api.reframe.data_dir / "Show.mkv")
        response = await api.client.post("/api/queue", json={"jobs": [job]})
        [added] = response.json()
        assert added["settings"]["output"]["path"] == job["output"]["path"]
