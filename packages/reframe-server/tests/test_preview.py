"""``/api/preview``: frames and rendered frames (the request waits), crop detection and clips
(tasks), clip links and the cache."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from reframe.models import JobDraft, JobSettings, PreviewClip, TaskInfo, TaskState
from reframe.preview.cache import PreviewCache
from reframe.tasks import TaskContext
from reframe_server import security
from reframe_server.config import ServerConfig
from reframe_server.errors import ProblemError
from reframe_server.sources import source_id
from reframe_testing import fake_tools as ft
from reframe_testing.server import PROBE_RULE, Api

pytestmark = pytest.mark.anyio

FixtureMedia = Callable[[str], Path]
FRAME_RUN = ["-frames:v"]


def _signed(config: ServerConfig, url_path: str, *, ttl: float = 300.0) -> str:
    return f"{url_path}?ttl={ttl:g}"


async def _until(check: Callable[[], bool], limit: float = 10.0) -> None:
    deadline = time.monotonic() + limit
    while not check():
        if time.monotonic() > deadline:
            raise TimeoutError("condition not met in time")
        await asyncio.sleep(0.02)


async def _source(api: Api, file: Path) -> str:
    response = await api.client.post("/api/sources", json={"paths": [str(file)]})
    info = await api.reframe.tasks.wait(response.json()["task_id"])
    assert info.state is TaskState.DONE
    return source_id(file)


async def _job(api: Api, file: Path) -> dict[str, Any]:
    draft = await api.reframe.jobs.draft(file, output=api.output / "out.mkv")
    assert isinstance(draft, JobDraft)
    return draft.job.model_dump(mode="json")


def _multitrack(api: Api, fixture_media: FixtureMedia, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The real fixture with the real tools. ``use_real_tools`` finds the tools through the
    environment, which points at the fake: without it the fake would run itself."""
    with monkeypatch.context() as env:
        env.delenv("REFRAME_FFMPEG")
        env.delenv("REFRAME_FFPROBE")
        return api.add_fixture("multitrack", fixture_media)


def _frames_hang(api: Api) -> None:
    api.fake.set_scenario(
        ft.Scenario([ft.Rule(tool="ffmpeg", argv_has=FRAME_RUN, actions=[ft.hang()]), PROBE_RULE])
    )


def _frames_task(api: Api) -> TaskInfo | None:
    tasks = api.reframe.tasks.list("frames")
    return tasks[0] if tasks else None


@pytest.mark.needs_ffmpeg
async def test_frames_answer_signed_urls_that_serve_the_pngs(
    api: Api, fixture_media: FixtureMedia, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(security, "sign_media_url", _signed)
    sid = await _source(api, _multitrack(api, fixture_media, monkeypatch))
    response = await api.client.post("/api/preview/frames", json={"source_id": sid, "count": 2})
    assert response.status_code == 200
    frames = response.json()["frames"]
    assert [frame["kind"] for frame in frames] == ["source", "source"]
    assert str(api.reframe.cache_dir) not in response.text
    url = frames[0]["url"]
    assert url == f"/api/preview/frames/{frames[0]['key']}.png?ttl=300"
    png = await api.anonymous.get(url)
    assert png.status_code == 200
    assert png.content.startswith(b"\x89PNG")


@pytest.mark.needs_ffmpeg
async def test_frames_at_the_given_timestamps(
    api: Api, fixture_media: FixtureMedia, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = await _source(api, _multitrack(api, fixture_media, monkeypatch))
    body = {"source_id": sid, "timestamps": [1.0]}
    frames = (await api.client.post("/api/preview/frames", json=body)).json()["frames"]
    assert [frame["timestamp"] for frame in frames] == [1.0]


async def test_frames_take_a_count_or_timestamps_not_both(api: Api) -> None:
    body = {"source_id": "0" * 24, "count": 2, "timestamps": [1.0]}
    response = await api.client.post("/api/preview/frames", json=body)
    assert (response.status_code, response.json()["code"]) == (422, "request.invalid")


@pytest.mark.needs_ffmpeg
async def test_render_answers_the_source_and_the_output_frame(
    api: Api, fixture_media: FixtureMedia, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = _multitrack(api, fixture_media, monkeypatch)
    await _source(api, file)
    body = {"job": await _job(api, file), "timestamp": 1.0}
    response = await api.client.post("/api/preview/render", json=body)
    assert response.status_code == 200
    frames = response.json()["frames"]
    assert [(frame["kind"], frame["timestamp"]) for frame in frames] == [
        ("source", 1.0),
        ("output", 1.0),
    ]


@pytest.mark.parametrize(
    ("route", "window"),
    [
        ("/api/preview/render", {"timestamp": 1.0}),
        ("/api/preview/clip", {"start": 0, "seconds": 2}),
    ],
)
async def test_a_job_route_passes_the_job_to_the_jail(
    api: Api, monkeypatch: pytest.MonkeyPatch, route: str, window: dict[str, float]
) -> None:
    file = api.media_file()
    body = {"job": await _job(api, file), **window}
    jailed: list[Path] = []

    def refuse(config: ServerConfig, job: JobSettings) -> None:
        jailed.append(Path(job.source.path))
        raise ProblemError(403, "path.outside_roots", "Outside the roots")

    monkeypatch.setattr(security, "jail_job", refuse)
    response = await api.client.post(route, json=body)
    assert (response.status_code, response.json()["code"]) == (403, "path.outside_roots")
    assert jailed == [file]
    assert api.reframe.tasks.list("frames") == api.reframe.tasks.list("preview_clip") == []


@pytest.mark.parametrize(
    ("route", "body"),
    [("/api/preview/frames", {"count": 2}), ("/api/preview/cropdetect", {})],
)
async def test_an_unknown_source_is_404(api: Api, route: str, body: dict[str, Any]) -> None:
    response = await api.client.post(route, json={"source_id": "0" * 24, **body})
    assert (response.status_code, response.json()["code"]) == (404, "source.unknown")


async def test_a_failed_frames_task_is_a_problem_with_its_reason(api: Api) -> None:
    fail = ft.Rule(tool="ffmpeg", argv_has=FRAME_RUN, actions=[ft.stderr("boom\n")], exit_code=1)
    api.fake.set_scenario(ft.Scenario([fail, PROBE_RULE]))
    sid = await _source(api, api.media_file())
    response = await api.client.post("/api/preview/frames", json={"source_id": sid, "count": 1})
    assert (response.status_code, response.json()["code"]) == (422, "preview.failed")
    assert response.json()["title"].startswith("No frame of")


async def test_a_frames_task_cancelled_elsewhere_is_a_conflict(api: Api) -> None:
    _frames_hang(api)
    sid = await _source(api, api.media_file())
    body = {"source_id": sid, "count": 1}
    request = asyncio.ensure_future(api.client.post("/api/preview/frames", json=body))
    await _until(lambda: any("-frames:v" in call for call in api.fake.calls("ffmpeg")))
    task = _frames_task(api)
    assert task is not None
    assert api.reframe.tasks.cancel(task.id)
    response = await request
    assert (response.status_code, response.json()["code"]) == (409, "preview.cancelled")


async def test_shutdown_while_frames_are_made_is_503(api: Api) -> None:
    _frames_hang(api)
    sid = await _source(api, api.media_file())
    body = {"source_id": sid, "count": 1}
    request = asyncio.ensure_future(api.client.post("/api/preview/frames", json=body))
    await _until(lambda: any("-frames:v" in call for call in api.fake.calls("ffmpeg")))
    await api.reframe.close()
    response = await request
    assert (response.status_code, response.json()["code"]) == (503, "server.closing")


async def test_a_client_that_goes_away_cancels_the_frames_task(api: Api) -> None:
    _frames_hang(api)
    await api.reframe.capabilities.wait()  # its ffmpeg runs are not this test's
    body = {"source_id": await _source(api, api.media_file()), "count": 1}
    headers = {"Authorization": f"Bearer {api.token}"}
    async with api.live() as server:
        async with httpx.AsyncClient(base_url=server.http_url, headers=headers) as client:
            with pytest.raises(httpx.ReadTimeout):
                await client.post("/api/preview/frames", json=body, timeout=1.0)
        task = _frames_task(api)
        assert task is not None
        info = await asyncio.wait_for(api.reframe.tasks.wait(task.id), 10)
    assert info.state is TaskState.CANCELLED
    assert api.fake.kill_leftovers() == []


async def test_cropdetect_starts_the_task_for_the_sources_file(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = api.media_file()
    sid = await _source(api, file)
    asked: list[tuple[Path, int | None]] = []

    def cropdetect(path: Path, *, count: int | None = None) -> TaskInfo:
        asked.append((path, count))
        return api.reframe.tasks.start("cropdetect", _nothing)

    monkeypatch.setattr(api.reframe.sources, "cropdetect", cropdetect)
    response = await api.client.post("/api/preview/cropdetect", json={"source_id": sid, "count": 3})
    assert response.status_code == 202
    assert api.reframe.tasks.get(response.json()["task_id"]) is not None
    assert asked == [(file, 3)]


async def _nothing(_ctx: TaskContext) -> None:
    return None


async def test_clip_starts_the_task_with_the_job_and_window(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = api.media_file()
    job = await _job(api, file)
    asked: list[tuple[Path, float, float]] = []

    def preview_clip(job: JobSettings, *, start: float, seconds: float) -> TaskInfo:
        asked.append((Path(job.source.path), start, seconds))
        return api.reframe.tasks.start("preview_clip", _nothing)

    monkeypatch.setattr(api.reframe.jobs, "preview_clip", preview_clip)
    body = {"job": job, "start": 1.5, "seconds": 2.0}
    response = await api.client.post("/api/preview/clip", json=body)
    assert response.status_code == 202
    assert api.reframe.tasks.get(response.json()["task_id"]) is not None
    assert asked == [(file, 1.5, 2.0)]


@pytest.mark.needs_ffmpeg
async def test_a_clip_task_result_leads_to_a_playable_url(
    api: Api, fixture_media: FixtureMedia, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(security, "sign_media_url", _signed)
    file = _multitrack(api, fixture_media, monkeypatch)
    await _source(api, file)
    body = {"job": await _job(api, file), "start": 0.0, "seconds": 1.0}
    response = await api.client.post("/api/preview/clip", json=body)
    info = await api.reframe.tasks.wait(response.json()["task_id"])
    assert info.state is TaskState.DONE, info.error
    clip_id = PreviewClip.model_validate(info.result).id
    link = await api.client.get(f"/api/preview/clips/{clip_id}/link")
    assert link.status_code == 200
    assert str(api.reframe.cache_dir) not in link.text
    url = link.json()["url"]
    assert url == f"/api/preview/clips/{clip_id}?ttl=3600"
    part = await api.anonymous.get(url, headers={"range": "bytes=0-9"})
    assert (part.status_code, len(part.content)) == (206, 10)


async def test_the_link_of_a_clip_not_in_the_cache_is_404(api: Api) -> None:
    response = await api.client.get(f"/api/preview/clips/{'a' * 32}/link")
    assert (response.status_code, response.json()["code"]) == (404, "preview.unknown_clip")


async def test_cache_size_and_clear(api: Api) -> None:
    cache = PreviewCache(api.reframe.cache_dir)
    clip = cache.clip("b" * 32, ".mkv")
    frame = cache.frame("0123456789abcdef-1500-fedcba9876543210")
    for file, size in ((clip, 700), (frame, 300)):
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"x" * size)
    assert (await api.client.get("/api/preview/cache")).json() == {"size": 1000}
    cleared = await api.client.delete("/api/preview/cache")
    assert cleared.json() == {"freed": 1000}
    assert (await api.client.get("/api/preview/cache")).json() == {"size": 0}
