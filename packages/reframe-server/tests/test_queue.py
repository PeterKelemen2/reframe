"""The queue routes on the real facade and the fake FFmpeg: adding jobs (jail, output path,
attach, position), the actions on one job or on the whole queue, the order, the log and the
when-done setting."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from reframe.models import JobDraft, JobSettings
from reframe_server import security
from reframe_server.config import ServerConfig
from reframe_server.errors import ProblemError
from reframe_server.routers.queue import LOG_CHUNK
from reframe_testing import fake_tools as ft
from reframe_testing.server import PROBE_RULE, Api

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


async def test_the_routes_have_stable_operation_ids(api: Api) -> None:
    """The generated client's function names."""
    paths = (await api.client.get("/api/openapi.json")).json()["paths"]
    found = {
        (method, path): operation["operationId"]
        for path, operations in paths.items()
        if path.startswith("/api/queue")
        for method, operation in operations.items()
    }
    assert found == {
        ("get", "/api/queue"): "queue_snapshot",
        ("post", "/api/queue"): "queue_add",
        ("post", "/api/queue/start"): "queue_start",
        ("post", "/api/queue/stop"): "queue_stop",
        ("post", "/api/queue/pause"): "queue_pause_all",
        ("post", "/api/queue/resume"): "queue_resume_all",
        ("post", "/api/queue/cancel"): "queue_cancel_all",
        ("put", "/api/queue/order"): "queue_reorder",
        ("put", "/api/queue/when-done"): "queue_set_when_done",
        ("post", "/api/queue/{job_id}/pause"): "queue_pause_job",
        ("post", "/api/queue/{job_id}/resume"): "queue_resume_job",
        ("post", "/api/queue/{job_id}/cancel"): "queue_cancel_job",
        ("post", "/api/queue/{job_id}/retry"): "queue_retry",
        ("post", "/api/queue/{job_id}/duplicate"): "queue_duplicate",
        ("delete", "/api/queue/{job_id}"): "queue_remove",
        ("get", "/api/queue/{job_id}/log"): "queue_log",
    }


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


async def test_a_job_with_errors_is_added_failed_with_its_issues(api: Api) -> None:
    """The server validates again; an invalid job is queued as ``failed``, not refused, as
    the queue does for every front end."""
    job = await draft_job(api)
    job["video"]["encoder"] = "no_such_encoder"
    response = await api.client.post("/api/queue", json={"jobs": [job]})
    assert response.status_code == 201
    [added] = response.json()
    assert added["state"] == "failed"
    assert any(issue["severity"] == "error" for issue in added["issues"])
    assert await snapshot(api) == [(added["id"], "failed")]


async def test_every_job_goes_through_the_jail(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    """A refusal of the second job adds neither."""
    good, bad = await draft_job(api, "Good.mkv"), await draft_job(api, "Bad.mkv")
    seen: list[tuple[ServerConfig, str]] = []

    def jail(config: ServerConfig, job: JobSettings) -> None:
        seen.append((config, str(job.source.path)))
        if job.source.path == Path(bad["source"]["path"]):
            raise ProblemError(403, "path.outside_roots", "The path is outside the roots")

    monkeypatch.setattr(security, "jail_job", jail)
    response = await api.client.post("/api/queue", json={"jobs": [good, bad]})
    assert response.status_code == 403
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "path.outside_roots"
    assert seen == [
        (api.config, good["source"]["path"]),
        (api.config, bad["source"]["path"]),
    ]
    assert await snapshot(api) == []


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


async def test_cancel_all_cancels_every_waiting_job(api: Api) -> None:
    first, second = await add_jobs(api, "First.mkv", "Second.mkv")
    assert (await api.client.post("/api/queue/cancel")).status_code == 204
    assert await snapshot(api) == [(first, "cancelled"), (second, "cancelled")]


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


async def test_duplicate_goes_through_the_jail(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    [job_id] = await add_jobs(api, "Show.mkv")

    def jail(config: ServerConfig, job: JobSettings) -> None:
        raise ProblemError(403, "path.outside_roots", "The path is outside the roots")

    monkeypatch.setattr(security, "jail_job", jail)
    response = await api.client.post(f"/api/queue/{job_id}/duplicate")
    assert (response.status_code, response.json()["code"]) == (403, "path.outside_roots")
    assert [state for _, state in await snapshot(api)] == ["waiting"]


async def test_duplicate_of_a_job_without_an_output_path_is_refused(api: Api) -> None:
    job = JobSettings.model_validate(await draft_job(api))
    job.output.path = None
    unnamed = await api.reframe.queue.add(job)
    response = await api.client.post(f"/api/queue/{unnamed.id}/duplicate")
    assert (response.status_code, response.json()["code"]) == (422, "output.no_path")
    assert len(await snapshot(api)) == 1


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/queue/{}/pause"),
        ("POST", "/api/queue/{}/resume"),
        ("POST", "/api/queue/{}/cancel"),
        ("POST", "/api/queue/{}/retry"),
        ("POST", "/api/queue/{}/duplicate"),
        ("DELETE", "/api/queue/{}"),
        ("GET", "/api/queue/{}/log"),
    ],
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


async def test_the_when_done_action_follows_the_last_job(api: Api) -> None:
    """The session's PowerGuard fails the test if the countdown reaches a real power action."""
    await api.client.put("/api/queue/when-done", json={"when_done": "shutdown"})
    [job_id] = await add_jobs(api, "Show.mkv")
    await api.client.post("/api/queue/start")
    await ended(api, job_id)
    pending = (await api.client.get("/api/power")).json()["pending"]
    assert pending["action"] == "shutdown"
    assert pending["phase"] in ("started", "tick")
