"""``/api/sources``: probing files and folders into source ids, the probed sources, scans."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from reframe.models import TaskInfo, TaskState
from reframe.platform import longpath
from reframe.tasks import TaskContext
from reframe_server.routers.sources import ProbeSummary
from reframe_server.sources import source_id
from reframe_testing import fake_tools as ft
from reframe_testing.server import PROBE_RULE, Api
from reframe_testing.waiting import wait_until

pytestmark = pytest.mark.anyio


async def _probe(api: Api, *paths: Path, recursive: bool = False) -> TaskInfo:
    response = await api.client.post(
        "/api/sources", json={"paths": [str(path) for path in paths], "recursive": recursive}
    )
    assert response.status_code == 202
    task_id = response.json()["task_id"]
    assert response.headers["location"] == f"/api/tasks/{task_id}"
    return await api.reframe.tasks.wait(task_id)


async def test_a_probed_file_gets_a_source_id(api: Api) -> None:
    file = api.media_file("Show S01E01.mkv")
    info = await _probe(api, file)
    assert info.state is TaskState.DONE
    sid = source_id(file.resolve())
    assert info.result == {"sources": [{"id": sid, "path": str(file.resolve())}], "errors": []}
    source = (await api.client.get(f"/api/sources/{sid}")).json()
    assert Path(source["ref"]["path"]) == file.resolve()
    assert source["audio"]


async def test_folders_missing_paths_and_failed_probes_are_in_the_result(api: Api) -> None:
    broken = ft.Rule(
        tool="ffprobe",
        argv_contains=["broken.mkv"],
        actions=[ft.stderr("broken.mkv: Invalid data found when processing input\n")],
        exit_code=1,
    )
    api.fake.set_scenario(ft.Scenario([broken, PROBE_RULE]))
    episode = api.media_file("Season/E01.mkv")
    nested = api.media_file("Season/Extras/Making of.mkv")
    api.media_file("Season/notes.txt")
    failed = api.media_file("broken.mkv")
    empty = api.media / "Empty"
    empty.mkdir()
    missing = api.media / "gone.mkv"
    info = await _probe(api, episode.parent, failed, empty, missing, recursive=True)
    summary = ProbeSummary.model_validate(info.result)
    assert [item.path for item in summary.sources] == [episode, nested]
    errors = {item.path: item.code for item in summary.errors}
    assert errors == {
        failed: "probe.failed",
        empty: "sources.no_media",
        missing: "probe.not_found",
    }
    listed = (await api.client.get("/api/sources")).json()
    assert [item["id"] for item in listed] == [source_id(episode), source_id(nested)]


async def test_a_path_windows_refuses_is_named_as_too_long(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(longpath, "long_paths_enabled", lambda: False)
    missing = api.media / ("x" * 250) / "gone.mkv"
    summary = ProbeSummary.model_validate((await _probe(api, missing)).result)
    (error,) = summary.errors
    assert error.code == "probe.not_found"
    assert error.message.startswith("Windows refuses this path")


async def test_a_link_in_a_folder_that_points_outside_the_roots_is_not_probed(api: Api) -> None:
    secret = api.outside / "secret.mkv"
    secret.write_bytes(b"x")
    (api.outside / "Hidden").mkdir()
    (api.outside / "Hidden" / "other.mkv").write_bytes(b"x")
    film = api.media_file("Show/film.mkv")
    link = film.parent / "link.mkv"
    try:
        link.symlink_to(secret)
        (film.parent / "linked").symlink_to(api.outside / "Hidden", target_is_directory=True)
    except OSError as exc:  # Windows without the symlink privilege
        pytest.skip(f"cannot make a symbolic link: {exc}")
    info = await _probe(api, film.parent, recursive=True)
    summary = ProbeSummary.model_validate(info.result)
    assert [item.path for item in summary.sources] == [film.resolve()]
    assert [(item.path, item.code) for item in summary.errors] == [(link, "path.outside_roots")]
    assert str(api.outside) not in json.dumps(info.result)
    assert not any(str(api.outside) in " ".join(call) for call in api.fake.calls("ffprobe"))


async def test_cancelling_the_probe_task_stops_its_ffprobe(api: Api) -> None:
    hang = ft.Rule(tool="ffprobe", argv_has=["-show_streams"], actions=[ft.hang()])
    api.fake.set_scenario(ft.Scenario([hang]))
    await api.reframe.capabilities.wait()  # its ffmpeg runs are not this test's
    response = await api.client.post("/api/sources", json={"paths": [str(api.media_file())]})
    task_id = response.json()["task_id"]
    await wait_until(lambda: any("-show_streams" in call for call in api.fake.calls("ffprobe")))
    assert api.reframe.tasks.cancel(task_id)
    info = await api.reframe.tasks.wait(task_id)
    assert info.state is TaskState.CANCELLED
    assert api.fake.kill_leftovers() == []
    assert (await api.client.get("/api/sources")).json() == []


async def test_a_source_whose_file_changed_is_listed_without_its_probe(api: Api) -> None:
    kept, changed = api.media_file("A.mkv"), api.media_file("B.mkv")
    await _probe(api, kept, changed)
    changed.write_bytes(b"another file now")
    listed = {item["id"]: item["source"] for item in (await api.client.get("/api/sources")).json()}
    assert listed[source_id(kept)] is not None
    assert listed[source_id(changed)] is None


@pytest.mark.parametrize(
    ("change", "status", "code"), [(False, 404, "source.unknown"), (True, 409, "source.stale")]
)
async def test_get_of_an_unknown_or_stale_source_is_a_problem(
    api: Api, change: bool, status: int, code: str
) -> None:
    file = api.media_file()
    await _probe(api, file)
    if change:
        file.unlink()
    sid = source_id(file) if change else "0" * 24
    response = await api.client.get(f"/api/sources/{sid}")
    assert (response.status_code, response.json()["code"]) == (status, code)


async def test_delete_forgets_the_source(api: Api) -> None:
    file = api.media_file()
    await _probe(api, file)
    sid = source_id(file)
    assert (await api.client.delete(f"/api/sources/{sid}")).status_code == 204
    assert (await api.client.get(f"/api/sources/{sid}")).status_code == 404
    again = await api.client.delete(f"/api/sources/{sid}")
    assert (again.status_code, again.json()["code"]) == (404, "source.unknown")


SCANS: list[tuple[str, str, dict[str, Any] | None, tuple[Any, ...]]] = [
    ("bitrate_scan", "streams/0/bitrate-scan", None, (0,)),
    ("subtitle_scan", "subtitle-scan", None, (None,)),
    ("subtitle_scan", "subtitle-scan", {"stream_indexes": [4, 5]}, ([4, 5],)),
    ("loudness_scan", "streams/1/loudness", None, (1, None, None)),
    ("loudness_scan", "streams/2/loudness", {"start": 10.0, "duration": 5.0}, (2, 10.0, 5.0)),
]


@pytest.mark.parametrize(("method", "route", "body", "args"), SCANS)
async def test_a_scan_starts_the_facades_task_for_the_sources_file(
    api: Api,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    route: str,
    body: dict[str, Any] | None,
    args: tuple[Any, ...],
) -> None:
    file = api.media_file()
    await _probe(api, file)
    asked: list[tuple[Any, ...]] = []

    async def nothing(_ctx: TaskContext) -> None:
        return None

    def scan(path: Path, *rest: Any, **window: float | None) -> TaskInfo:
        asked.append((path, *rest, *window.values()))
        return api.reframe.tasks.start(method, nothing)

    monkeypatch.setattr(api.reframe.sources, method, scan)
    response = await api.client.post(f"/api/sources/{source_id(file)}/{route}", json=body)
    assert response.status_code == 202
    assert api.reframe.tasks.get(response.json()["task_id"]) is not None
    assert asked == [(file, *args)]


@pytest.mark.parametrize("route", ["streams/0/bitrate-scan", "subtitle-scan", "streams/1/loudness"])
async def test_a_scan_of_an_unknown_source_is_a_problem(api: Api, route: str) -> None:
    response = await api.client.post(f"/api/sources/{'0' * 24}/{route}")
    assert (response.status_code, response.json()["code"]) == (404, "source.unknown")
