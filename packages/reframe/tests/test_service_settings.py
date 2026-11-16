"""The ``settings`` and ``presets`` services of the facade: loading and saving the settings, and
the rescans that a change starts."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from reframe.models import (
    AppSettings,
    AppWarningEvent,
    CapabilitySnapshot,
    JobTemplate,
    Preset,
    ReplaceOp,
    ToolOrigin,
    ToolsChangedEvent,
    ToolSet,
    ToolStatus,
    ValidationIssue,
)
from reframe.models.migrations import current_version
from reframe.service import Reframe
from reframe.tools import ENV_VARS
from reframe_testing import fake_tools as ft
from reframe_testing.waiting import wait_until

pytestmark = pytest.mark.anyio


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """No tool overrides, user folders in ``tmp_path``."""
    for var in ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    for name in ("config", "data", "cache"):
        monkeypatch.setenv(f"REFRAME_{name.upper()}_DIR", str(tmp_path / name))
    return tmp_path


@pytest.fixture
def config(env: Path, fake_tools: ft.FakeTools) -> Path:
    """``settings.json`` that points ffmpeg and ffprobe at the fake tools (no real tool runs)."""
    folder = env / "config"
    folder.mkdir()
    settings = {"tools": {"ffmpeg": str(fake_tools.ffmpeg), "ffprobe": str(fake_tools.ffprobe)}}
    (folder / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    return folder


class Calls:
    """Stands in for ``rescan`` and counts the calls."""

    def __init__(self, result: Any = None, *, block: bool = False) -> None:
        self.count = 0
        self.result = result
        self.block = block
        self.cancelled = False

    async def __call__(self) -> Any:
        self.count += 1
        if self.block:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        return self.result


async def test_create_reads_settings_json(config: Path, fake_tools: ft.FakeTools) -> None:
    async with await Reframe.create() as app:
        assert app.settings.path == config / "settings.json"
        assert app.settings_snapshot().tools.ffprobe == fake_tools.ffprobe
        assert app.settings.problems == []
        tools = await app.tools.status()
        assert tools.ffprobe.origin is ToolOrigin.SETTINGS
        assert tools.ffprobe.path == fake_tools.ffprobe


async def test_corrupt_settings_at_start_are_kept_as_problems(env: Path) -> None:
    folder = env / "config"
    folder.mkdir()
    (folder / "settings.json").write_text("{nope", encoding="utf-8")
    async with await Reframe.create() as app:
        assert app.settings_snapshot() == AppSettings()
        [problem] = app.settings.problems
        assert problem.code == "settings.corrupt"
        assert len(list(folder.glob("settings.corrupt-*.json"))) == 1
        assert json.loads((folder / "settings.json").read_text("utf-8")) == (
            AppSettings().model_dump(mode="json")
        )


async def test_update_with_a_patch_saves_and_takes_effect(config: Path) -> None:
    async with await Reframe.create() as app:
        capabilities_rescan = Calls()
        tools_rescan = Calls()
        app.capabilities.rescan = capabilities_rescan  # type: ignore[method-assign]
        app.tools.rescan = tools_rescan  # type: ignore[method-assign]
        result = await app.settings.update(
            [
                ReplaceOp(path="/queue/parallel_jobs", value=2),
                {"op": "add", "path": "/languages/preferred_audio", "value": ["hu", "en"]},
            ]
        )
        assert result.ok
        assert result.saved
        assert [c.path for c in result.changes] == [
            "languages.preferred_audio[0]",
            "languages.preferred_audio[1]",
            "queue.parallel_jobs",
        ]
        assert app.settings_snapshot().queue.parallel_jobs == 2
        saved = json.loads((config / "settings.json").read_text("utf-8"))
        assert saved["queue"]["parallel_jobs"] == 2
        assert saved["languages"]["preferred_audio"] == ["hu", "en"]
        # Neither tools nor encoder settings changed: nothing is re-run.
        await asyncio.sleep(0)
        assert tools_rescan.count == 0
        assert capabilities_rescan.count == 0


async def test_update_with_a_whole_settings_object(config: Path) -> None:
    async with await Reframe.create() as app:
        new = app.settings.get()
        new.appearance.theme = "dark"
        result = await app.settings.update(new)
        assert result.saved
        assert [c.path for c in result.changes] == ["appearance.theme"]
        assert app.settings.get().appearance.theme == "dark"
        unchanged = await app.settings.update(app.settings.get())
        assert unchanged.ok
        assert unchanged.changes == []
        assert not unchanged.saved


@pytest.mark.parametrize(
    ("patch", "path"),
    [
        ([{"op": "replace", "path": "/queue/parallel_jobs", "value": 99}], "queue.parallel_jobs"),
        ([{"op": "replace", "path": "/no/such/thing", "value": 1}], ""),
        ([{"op": "dance", "path": "/queue"}], "0"),
    ],
)
async def test_an_invalid_change_is_an_issue_and_changes_nothing(
    config: Path, patch: list[dict[str, Any]], path: str
) -> None:
    async with await Reframe.create() as app:
        before = (config / "settings.json").read_bytes()
        result = await app.settings.update(patch)
        [issue] = result.issues
        assert issue.code == "settings.invalid"
        assert issue.path.startswith(path)
        assert not result.saved
        assert result.settings == app.settings.get()
        assert app.settings.get().queue.parallel_jobs == 1
        assert (config / "settings.json").read_bytes() == before


async def test_the_check_sees_the_settings_the_change_applies_to(config: Path) -> None:
    """A caller that refuses some changes must judge the settings the patch is applied to,
    not a copy that a concurrent update has made stale."""
    seen: list[tuple[int, int]] = []

    def refuse_three(old: AppSettings, new: AppSettings) -> None:
        seen.append((old.queue.parallel_jobs, new.queue.parallel_jobs))
        if new.queue.parallel_jobs == 3:
            raise PermissionError("three is refused")

    async with await Reframe.create() as app:
        patch = [
            {"op": "test", "path": "/queue/parallel_jobs", "value": 2},
            {"op": "replace", "path": "/queue/parallel_jobs", "value": 3},
        ]
        first = app.settings.update([{"op": "replace", "path": "/queue/parallel_jobs", "value": 2}])
        second = app.settings.update(patch, check=refuse_three)
        results = await asyncio.gather(first, second, return_exceptions=True)
        assert isinstance(results[1], PermissionError)
        assert seen == [(2, 3)]
        assert app.settings.get().queue.parallel_jobs == 2
        saved = json.loads((config / "settings.json").read_text(encoding="utf-8"))
        assert saved["queue"]["parallel_jobs"] == 2


@pytest.mark.parametrize(
    "change",
    [
        [{"op": "replace", "path": "/schema_version", "value": 7}],
        AppSettings.model_validate({"schema_version": 7, "queue": {"parallel_jobs": 2}}),
    ],
)
async def test_schema_version_cannot_be_changed(config: Path, change: Any) -> None:
    """Saving it would make the next start read the file as newer and use the defaults."""
    async with await Reframe.create() as app:
        before = (config / "settings.json").read_bytes()
        result = await app.settings.update(change)
        [issue] = result.issues
        assert issue.code == "settings.schema_version"
        assert issue.path == "schema_version"
        assert not result.saved
        assert app.settings.get().schema_version == current_version("settings")
        assert app.settings.get().queue.parallel_jobs == 1
        assert (config / "settings.json").read_bytes() == before
        same = await app.settings.update(
            [{"op": "replace", "path": "/schema_version", "value": current_version("settings")}]
        )
        assert same.ok
        assert same.changes == []
    async with await Reframe.create() as again:
        assert again.settings.problems == []


@pytest.mark.parametrize("depth", [100, 1_000])
async def test_a_too_deep_settings_value_is_an_issue(config: Path, depth: int) -> None:
    value: list[Any] = []
    for _ in range(depth):
        value = [value]
    async with await Reframe.create() as app:
        before = (config / "settings.json").read_bytes()
        result = await app.settings.update([{"op": "add", "path": "/x", "value": value}])
        [issue] = result.issues
        assert issue.code == "settings.invalid"
        assert "nested" in issue.message
        assert not result.saved
        assert (config / "settings.json").read_bytes() == before


async def test_a_deeply_nested_settings_file_does_not_stop_the_app(env: Path) -> None:
    folder = env / "config"
    folder.mkdir()
    (folder / "settings.json").write_text(
        '{"x": ' + "[" * 100_000 + "]" * 100_000 + "}", encoding="utf-8"
    )
    async with await Reframe.create() as app:
        assert app.settings_snapshot() == AppSettings()
        assert [p.code for p in app.settings.problems] == ["settings.corrupt"]
        assert len(list(folder.glob("settings.corrupt-*.json"))) == 1


async def test_tool_path_change_reruns_tool_discovery(
    config: Path, fake_tools: ft.FakeTools, env: Path
) -> None:
    async with await Reframe.create() as app:
        first = await app.tools.status()
        assert first.ffprobe.status is ToolStatus.FOUND
        events = app.events.subscribe(types={"tools.changed"})
        missing = env / "elsewhere" / "ffprobe"
        result = await app.settings.update(
            [{"op": "replace", "path": "/tools/ffprobe", "value": str(missing)}]
        )
        assert result.saved
        seen: list[ToolSet] = []
        async with asyncio.timeout(30):
            async for event in events:
                assert isinstance(event, ToolsChangedEvent)
                seen.append(event.tools)
                if event.tools.ffprobe.path == missing:
                    break
        assert seen[-1].ffprobe.status is ToolStatus.MISSING
        assert seen[-1].ffprobe.origin is ToolOrigin.SETTINGS


@pytest.mark.parametrize(
    "patch",
    [
        [{"op": "replace", "path": "/encoders/hardware_tests", "value": False}],
        [{"op": "replace", "path": "/encoders/vaapi_device", "value": "/dev/dri/renderD129"}],
    ],
)
async def test_encoder_settings_change_reruns_detection(
    config: Path, patch: list[dict[str, Any]]
) -> None:
    async with await Reframe.create() as app:
        rescan = Calls(CapabilitySnapshot())
        tools = Calls()
        app.capabilities.rescan = rescan  # type: ignore[method-assign]
        app.tools.rescan = tools  # type: ignore[method-assign]
        result = await app.settings.update(patch)
        assert result.saved
        await wait_until(lambda: rescan.count == 1)
        assert tools.count == 0


async def test_tools_and_encoders_changed_together_rescan_both(config: Path) -> None:
    async with await Reframe.create() as app:
        order: list[str] = []

        async def tools_rescan() -> None:
            order.append("tools")

        async def capabilities_rescan() -> None:
            order.append("capabilities")

        app.tools.rescan = tools_rescan  # type: ignore[method-assign,assignment]
        app.capabilities.rescan = capabilities_rescan  # type: ignore[method-assign,assignment]
        new = app.settings.get()
        new.tools.ffprobe = Path("/opt/ffmpeg/ffprobe")
        new.encoders.hardware_tests = False
        await app.settings.update(new)
        await wait_until(lambda: len(order) == 2)
        assert order == ["tools", "capabilities"]


async def test_close_cancels_a_running_reaction(config: Path) -> None:
    app = await Reframe.create()
    rescan = Calls(block=True)
    app.capabilities.rescan = rescan  # type: ignore[method-assign]
    await app.settings.update(
        [{"op": "replace", "path": "/encoders/hardware_tests", "value": False}]
    )
    await wait_until(lambda: rescan.count == 1)
    async with asyncio.timeout(10):
        await app.close()
    assert rescan.cancelled


async def test_a_newer_settings_file_is_not_overwritten(env: Path) -> None:
    folder = env / "config"
    folder.mkdir()
    (folder / "settings.json").write_text('{"schema_version": 42}', encoding="utf-8")
    async with await Reframe.create() as app:
        assert app.settings.read_only
        assert [p.code for p in app.settings.problems] == ["settings.newer_version"]
        events = app.events.subscribe(types={"app.warning"})
        result = await app.settings.update(
            [{"op": "replace", "path": "/queue/parallel_jobs", "value": 3}]
        )
        assert result.ok
        assert not result.saved
        assert [w.code for w in result.warnings] == ["settings.not_saved"]
        assert app.settings.get().queue.parallel_jobs == 3  # in effect for this session
        event = events.get_nowait()
        assert isinstance(event, AppWarningEvent)
        assert event.code == "settings.not_saved"
    assert (folder / "settings.json").read_text("utf-8") == '{"schema_version": 42}'


async def test_settings_hook_still_overrides_the_file(
    env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = AppSettings.model_validate({"queue": {"parallel_jobs": 4}})
    monkeypatch.setattr(Reframe, "_load_settings", staticmethod(lambda config_dir: settings))
    async with await Reframe.create() as app:
        assert app.settings_snapshot() == settings
        await app.settings.update([{"op": "replace", "path": "/queue/parallel_jobs", "value": 5}])
    saved = json.loads((env / "config" / "settings.json").read_text("utf-8"))
    assert saved["queue"]["parallel_jobs"] == 5


async def test_presets_are_read_at_first_use_not_in_create(env: Path) -> None:
    folder = env / "config"
    folder.mkdir()
    (folder / "presets.json").write_text("{damaged", encoding="utf-8")
    async with await Reframe.create() as app:
        assert list(folder.glob("presets.corrupt-*")) == []
        events = app.events.subscribe(types={"app.warning"})
        assert app.presets.find("H.265 MKV 1080p") is not None
        [problem] = app.presets.problems
        assert problem.code == "presets.corrupt"
        assert events.get_nowait() == problem
        assert len(list(folder.glob("presets.corrupt-*.json"))) == 1


async def test_preset_service_round_trip(config: Path) -> None:
    async with await Reframe.create() as app:
        presets = app.presets
        assert presets.default().name == "H.265 MKV 1080p"
        demo = presets.find("h.265 mkv 1080p")
        assert demo is not None
        assert demo.built_in
        mine = await presets.create(
            JobTemplate.model_validate({"video": {"encoder": "libx265", "preset": "slower"}}),
            "My x265",
        )
        assert isinstance(mine, Preset)
        assert presets.list()[-1] == mine
        clash = await presets.create(JobTemplate(), "my X265")
        assert isinstance(clash, ValidationIssue)
        assert clash.code == "preset.name_conflict"
        renamed = await presets.rename(mine.id, "My x265, slower")
        assert isinstance(renamed, Preset)
        assert await presets.set_default(mine.id) == renamed
        copy = await presets.duplicate("h265-nvenc-1080p")
        assert isinstance(copy, Preset)
        changed = copy.model_copy(update={"description": "mine"}, deep=True)
        changed.video.preset = "p7"
        saved = await presets.save(changed)
        assert isinstance(saved, Preset)
        assert presets.diff(changed, "h265-nvenc-1080p") == presets.diff(changed, copy)
        [change] = presets.diff(changed, "h265-nvenc-1080p") or []
        assert (change.path, change.preset_value, change.value) == ("video.preset", "p4", "p7")
        assert presets.diff(changed, "nope") is None
        exported = presets.export()
        assert exported.issues == []
        assert [p.id for p in exported.file.presets] == [renamed.id, copy.id]
        deleted = await presets.delete(copy.id)
        assert isinstance(deleted, Preset)
        builtin = await presets.delete("h265-mkv-1080p")
        assert isinstance(builtin, ValidationIssue)
        result = await presets.import_(exported.document(), "skip")
        assert [p.name for p in result.imported] == [copy.name]
        assert result.skipped == [renamed.name]
    # A new facade on the same folder sees the same user presets and default.
    async with await Reframe.create() as again:
        assert [p.name for p in again.presets.list() if not p.built_in] == [
            "My x265, slower",
            "H.265 NVENC 1080p (2)",
        ]
        assert again.presets.default().id == renamed.id
