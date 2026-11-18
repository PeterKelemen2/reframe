"""``/api/settings``: read, and change with a JSON patch; what a web client may not change."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any

import pytest

from reframe.models import AppSettings
from reframe.service import SettingsUpdate
from reframe.tools import ENV_VARS
from reframe_testing.server import Api, ApiFactory
from reframe_testing.waiting import wait_until

pytestmark = pytest.mark.anyio

VAAPI = "/encoders/vaapi_device"
WITH_OPTIONS = "/dev/dri/renderD128,driver=../../tmp/x"


def _start_with(tmp_path: Path, settings: dict[str, Any]) -> None:
    file = tmp_path / "config" / "settings.json"
    file.write_text(json.dumps(json.loads(file.read_text("utf-8")) | settings), encoding="utf-8")


async def test_get_answers_the_settings_in_effect(api: Api) -> None:
    body = (await api.client.get("/api/settings")).json()
    assert body["encoders"]["hardware_tests"] is False


async def test_a_patch_takes_effect_and_is_saved(api: Api) -> None:
    patch = [{"op": "replace", "path": "/preview/sample_frames", "value": 4}]
    response = await api.client.put("/api/settings", json=patch)
    assert response.status_code == 200
    body = response.json()
    assert body["settings"]["preview"]["sample_frames"] == 4
    assert body["saved"] is True
    assert [change["path"] for change in body["changes"]] == ["preview.sample_frames"]
    assert api.reframe.settings.get().preview.sample_frames == 4


async def test_an_invalid_patch_is_a_problem_with_its_issues(api: Api) -> None:
    patch = [{"op": "replace", "path": "/preview/sample_frames", "value": 1000}]
    response = await api.client.put("/api/settings", json=patch)
    assert response.status_code == 422
    problem = response.json()
    assert problem["code"] == "settings.invalid"
    assert problem["issues"][0]["path"] == "preview.sample_frames"
    assert api.reframe.settings.get().preview.sample_frames != 1000


@pytest.mark.parametrize(
    ("tools", "named"),
    [
        (["ffprobe"], ["REFRAME_FFPROBE"]),
        (["ffprobe", "ffmpeg"], ["REFRAME_FFMPEG", "REFRAME_FFPROBE"]),
        (["extra"], []),
    ],
)
async def test_a_refused_program_names_the_variables_of_the_tools_it_sets(
    api: Api, tools: list[str], named: list[str]
) -> None:
    patch = [{"op": "add", "path": f"/tools/{tool}", "value": "/bin/sh"} for tool in tools]
    response = await api.client.put("/api/settings", json=patch)
    problem = response.json()
    assert (response.status_code, problem["code"]) == (403, "settings.tools_forbidden")
    shown = [variable for variable in ENV_VARS.values() if variable in problem["detail"]]
    assert shown == named
    assert api.reframe.settings.get().tools.model_dump(exclude_none=True) == {}


async def test_a_concurrent_change_cannot_slip_a_program_past_the_check(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second patch applies only once the first is in: the check must see the settings
    the patch is applied to, not the ones before the first change."""
    service = api.reframe.settings
    store = service._store
    entered, release = threading.Event(), threading.Event()
    real_write = store.write

    def slow_write(settings: AppSettings) -> Any:
        entered.set()
        release.wait(10)
        return real_write(settings)

    calls: list[object] = []
    real_update = service.update

    async def update(change: Any, **options: Any) -> SettingsUpdate:
        calls.append(change)
        return await real_update(change, **options)

    monkeypatch.setattr(store, "write", slow_write)
    monkeypatch.setattr(service, "update", update)
    frames = [{"op": "replace", "path": "/preview/sample_frames", "value": 4}]
    first = asyncio.ensure_future(api.client.put("/api/settings", json=frames))
    await wait_until(entered.is_set)
    program = [
        {"op": "test", "path": "/preview/sample_frames", "value": 4},
        {"op": "add", "path": "/tools/ffmpeg", "value": "/bin/sh"},
    ]
    second = asyncio.ensure_future(api.client.put("/api/settings", json=program))
    await wait_until(lambda: len(calls) == 2)  # the second request waits for the store's lock
    release.set()
    assert (await first).status_code == 200
    response = await second
    assert (response.status_code, response.json()["code"]) == (403, "settings.tools_forbidden")
    assert service.get().tools.ffmpeg is None


async def test_a_web_client_may_remove_a_tool_override(
    make_api: ApiFactory, tmp_path: Path
) -> None:
    """The "Use bundled" fix: discovery chooses again."""
    _start_with(tmp_path, {"tools": {"ffmpeg": "/opt/ffmpeg/bin/ffmpeg"}})
    async with make_api() as api:
        patch = [{"op": "remove", "path": "/tools/ffmpeg"}]
        response = await api.client.put("/api/settings", json=patch)
    assert response.status_code == 200
    assert response.json()["settings"]["tools"]["ffmpeg"] is None


@pytest.mark.parametrize(
    ("device", "status"),
    [("/dev/dri/renderD129", 200), (None, 200), (WITH_OPTIONS, 403)],
    ids=["a render node", "automatic", "device options"],
)
async def test_a_web_client_can_only_choose_a_vaapi_render_node(
    make_api: ApiFactory, tmp_path: Path, device: str | None, status: int
) -> None:
    """FFmpeg passes the options after a comma to libva (``driver=`` loads a library)."""
    _start_with(tmp_path, {"encoders": {"hardware_tests": False, "vaapi_device": "/dev/dri/x"}})
    async with make_api() as api:
        patch = [{"op": "replace", "path": VAAPI, "value": device}]
        response = await api.client.put("/api/settings", json=patch)
        now = api.reframe.settings.get().encoders.vaapi_device
    assert response.status_code == status
    if status == 403:
        assert response.json()["code"] == "settings.vaapi_device_forbidden"
    assert now == (device if status == 200 else "/dev/dri/x")


async def test_a_desktop_client_may_choose_a_program_and_any_device(
    make_api: ApiFactory, tmp_path: Path
) -> None:
    program = str(tmp_path / "opt" / "ffprobe")
    async with make_api(mode="desktop") as api:
        patch = [
            {"op": "add", "path": "/tools/ffprobe", "value": program},
            {"op": "replace", "path": VAAPI, "value": WITH_OPTIONS},
        ]
        response = await api.client.put("/api/settings", json=patch)
    assert response.status_code == 200
    settings = response.json()["settings"]
    assert settings["tools"]["ffprobe"] == program
    assert settings["encoders"]["vaapi_device"] == WITH_OPTIONS


async def test_a_value_the_patch_does_not_change_is_not_checked_again(
    make_api: ApiFactory, tmp_path: Path
) -> None:
    """A folder saved before the roots changed, or a device the server's owner set, does not
    block every other change."""
    _start_with(
        tmp_path,
        {
            "output": {"naming": {"output_folder": str(tmp_path / "old")}},
            "encoders": {"hardware_tests": False, "vaapi_device": WITH_OPTIONS},
        },
    )
    async with make_api() as api:
        patch = [{"op": "replace", "path": "/preview/sample_frames", "value": 3}]
        response = await api.client.put("/api/settings", json=patch)
    assert response.status_code == 200
