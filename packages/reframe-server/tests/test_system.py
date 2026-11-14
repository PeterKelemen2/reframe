"""``/api/system``: tool and encoder status, rescans, the FFmpeg fetch and shutdown."""

from __future__ import annotations

from pathlib import Path

import pytest

from reframe.models import CapabilitySnapshot, TaskInfo, TaskState
from reframe.tasks import TaskContext
from reframe_testing.server import Api, ApiFactory

pytestmark = pytest.mark.anyio


async def _finished(api: Api, response_json: dict[str, str]) -> TaskInfo:
    return await api.reframe.tasks.wait(response_json["task_id"])


async def test_system_shows_tools_mode_and_the_stores_start_up_problems(
    make_api: ApiFactory, tmp_path: Path
) -> None:
    config = tmp_path / "config"
    (config / "settings.json").write_text('{"schema_version": 999}', encoding="utf-8")
    (config / "presets.json").write_text("{not json", encoding="utf-8")
    async with make_api() as api:
        response = await api.client.get("/api/system")
    assert response.status_code == 200
    body = response.json()
    assert (body["mode"], body["auth"]) == ("web", "token")
    assert body["tools"]["ffprobe"]["status"] == "found"
    assert body["tools"]["ffmpeg"]["version"]
    codes = {problem["code"] for problem in body["problems"]}
    assert "settings.newer_version" in codes
    assert any(code.startswith("presets.") for code in codes)
    assert body["settings_read_only"] is True


async def test_a_missing_optional_tool_tells_a_web_client_what_it_can_do(
    make_api: ApiFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A web client cannot set a tool path in Settings: the reason must name the variable."""
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    async with make_api() as api:
        tools = (await api.client.get("/api/system")).json()["tools"]
    for name, variable in (
        ("mediainfo", "REFRAME_MEDIAINFO"),
        ("mkvpropedit", "REFRAME_MKVPROPEDIT"),
    ):
        assert tools[name]["status"] == "missing"
        assert variable in tools[name]["reason"]
        assert "Settings" not in tools[name]["reason"]


async def test_diagnostics_names_the_logs_folder(api: Api) -> None:
    body = (await api.client.get("/api/diagnostics")).json()
    assert body["logs_dir"] == str(api.reframe.data_dir / "logs")


async def test_encoders_is_the_capability_snapshot(api: Api) -> None:
    await api.reframe.capabilities.wait()
    body = (await api.client.get("/api/system/encoders")).json()
    assert body["encoders"]["libx264"]["in_build"] is True


async def test_encoder_rescan_detects_again_in_a_task(api: Api) -> None:
    await api.reframe.capabilities.wait()
    api.fake.clear_log()
    response = await api.client.post("/api/system/encoders/rescan")
    assert response.status_code == 202
    info = await _finished(api, response.json())
    assert info.state is TaskState.DONE
    assert CapabilitySnapshot.model_validate(info.result).encoders["libx264"].in_build is True
    assert any("-encoders" in call for call in api.fake.calls("ffmpeg"))


async def test_tools_rescan_runs_discovery_again(api: Api) -> None:
    await api.reframe.tools.status()
    api.fake.clear_log()
    response = await api.client.post("/api/system/tools/rescan")
    assert response.status_code == 200
    assert response.json()["ffmpeg"]["status"] == "found"
    assert any("-version" in call for call in api.fake.calls("ffmpeg"))


@pytest.mark.parametrize(("body", "build"), [(None, "default"), ({"build": "nightly"}, "nightly")])
async def test_tools_fetch_starts_the_fetch_of_the_build(
    api: Api, monkeypatch: pytest.MonkeyPatch, body: dict[str, str] | None, build: str
) -> None:
    asked: list[str] = []

    async def nothing(_ctx: TaskContext) -> None:
        return None

    def fetch(*, build: str = "default") -> TaskInfo:
        asked.append(build)
        return api.reframe.tasks.start("tools_fetch", nothing)

    monkeypatch.setattr(api.reframe.tools, "fetch", fetch)
    response = await api.client.post("/api/system/tools/fetch", json=body)
    assert response.status_code == 202
    task_id = response.json()["task_id"]
    assert response.headers["location"] == f"/api/tasks/{task_id}"
    assert api.reframe.tasks.get(task_id) is not None
    assert asked == [build]


async def test_shutdown_is_refused_in_web_mode(api: Api) -> None:
    calls: list[None] = []
    api.app.state.request_shutdown = lambda: calls.append(None)
    response = await api.client.post("/api/system/shutdown")
    assert (response.status_code, response.json()["code"]) == (403, "system.desktop_only")
    assert calls == []


async def test_shutdown_in_desktop_mode_asks_the_entry_point_to_stop(
    make_api: ApiFactory,
) -> None:
    async with make_api(mode="desktop") as api:
        calls: list[None] = []
        api.app.state.request_shutdown = lambda: calls.append(None)
        response = await api.client.post("/api/system/shutdown")
    assert response.status_code == 204
    assert calls == [None]
