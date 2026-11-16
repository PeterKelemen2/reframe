"""The capability service and its ``Reframe.capabilities`` facade."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from reframe.capabilities import CacheKey, CapabilityCache, CapabilityService
from reframe.capabilities import service as service_module
from reframe.events import EventBus
from reframe.models import (
    AppSettings,
    CapabilitiesChangedEvent,
    CapabilitySnapshot,
    EncoderState,
    Event,
    ToolsChangedEvent,
    ToolStatus,
)
from reframe.service import Reframe, ReframeClosedError
from reframe.tools import ENV_VARS
from reframe_testing import fake_tools as ft
from reframe_testing.capabilities import StubTools, ffmpeg_info, tool_set
from reframe_testing.helpers import drain
from reframe_testing.waiting import wait_until

pytestmark = pytest.mark.anyio

AVAILABLE = EncoderState.AVAILABLE
CHECKING = EncoderState.CHECKING
UNKNOWN = EncoderState.UNKNOWN
GPU = "linux; drm 0x1002:0x7480 amdgpu; nvidia none"
NODE = "/dev/dri/renderD128"
OTHER_NODE = "/dev/dri/renderD129"


def running_detections() -> list[asyncio.Task[Any]]:
    return [
        t
        for t in asyncio.all_tasks()
        if t.get_name() == "reframe-encoder-detection" and not t.done()
    ]


def changed(events: list[Event]) -> list[CapabilitiesChangedEvent]:
    return [e for e in events if isinstance(e, CapabilitiesChangedEvent)]


def cache_files(folder: Path) -> list[Path]:
    return sorted(folder.glob("*.json"))


def encode_calls(fake: ft.FakeTools) -> list[tuple[str, ...]]:
    return [call for call in fake.calls() if "-c:v" in call]


class Harness:
    """A capability service on the fake ffmpeg, a stub tool discovery and its own bus."""

    def __init__(self, fake: ft.FakeTools, cache_dir: Path, **kw: Any) -> None:
        self.fake = fake
        self.cache_dir = cache_dir
        self.settings = AppSettings()
        self.events = EventBus()
        self.subscription = self.events.subscribe()
        self.tools = StubTools(tool_set(ffmpeg_info(fake.ffmpeg)))
        self.nodes = [NODE]
        self.service = self.make(**kw)

    def make(self, **kw: Any) -> CapabilityService:
        return CapabilityService(
            self.events,
            self.tools,  # type: ignore[arg-type]
            lambda: self.settings,
            cache_dir=self.cache_dir,
            platform="linux",
            **{"gpu_fingerprint": lambda: GPU, "render_nodes": lambda: self.nodes, **kw},
        )

    async def close(self) -> None:
        await self.service.close()
        self.events.close()


@pytest.fixture
async def harness(fake_tools: ft.FakeTools, tmp_path: Path) -> Any:
    h = Harness(fake_tools, tmp_path / "caps")
    yield h
    await h.close()


@pytest.fixture
def fake_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fake_tools: ft.FakeTools
) -> ft.FakeTools:
    for var in ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    for name in ("config", "data", "cache"):
        monkeypatch.setenv(f"REFRAME_{name.upper()}_DIR", str(tmp_path / name))
    monkeypatch.setenv("REFRAME_FFMPEG", str(fake_tools.ffmpeg))
    monkeypatch.setenv("REFRAME_FFPROBE", str(fake_tools.ffprobe))
    return fake_tools


async def test_create_is_fast_while_detection_runs(fake_env: ft.FakeTools) -> None:
    fake_env.set_scenario(
        ft.Scenario(
            [
                ft.Rule(
                    argv_has=["-encoders"],
                    actions=[ft.sleep(2.0), ft.stdout_data("encoders.stdout.txt")],
                )
            ]
        )
    )
    started = time.monotonic()
    app = await Reframe.create()
    try:
        subscription = app.events.subscribe(types={"capabilities.changed"})
        snapshot = app.capabilities.snapshot
        elapsed = time.monotonic() - started
        assert elapsed < 1.0, f"create() + snapshot took {elapsed:.2f} s"
        assert snapshot.detecting
        assert set(snapshot.encoders) >= {"libx265", "hevc_nvenc", "aac"}
        assert snapshot.status("libx265").state in (UNKNOWN, CHECKING)
        assert app.capabilities.closest_available("hevc_nvenc") is None  # nothing known yet

        final = await app.capabilities.wait()
        assert time.monotonic() - started >= 2.0  # it really waited for the slow listing
        assert not final.detecting
        assert final.status("libx265").state is AVAILABLE
        assert final.status("hevc_amf").state is AVAILABLE  # the fake's test encode works
        assert app.capabilities.snapshot is final
        events = changed(drain(subscription))
        assert events, "no capabilities.changed event"
        assert {s.id for s in events[-1].encoders} == set(final.encoders)
        assert cache_files(app.cache_dir / "capabilities")  # cached for the next start
    finally:
        await app.close()


async def test_close_kills_running_test_encodes(fake_env: ft.FakeTools) -> None:
    fake_env.set_scenario(ft.Scenario([ft.Rule(argv_has=["-c:v"], actions=[ft.hang()])]))
    app = await Reframe.create()
    try:
        await wait_until(lambda: len(encode_calls(fake_env)) >= 3)
        assert app.capabilities.snapshot.detecting
    finally:
        await app.close()
    assert not app.capabilities.detecting
    assert fake_env.kill_leftovers() == []
    with pytest.raises(ReframeClosedError):
        app.capabilities.start()
    with pytest.raises(ReframeClosedError):
        await app.capabilities.wait()
    with pytest.raises(ReframeClosedError):
        await app.capabilities.rescan()


async def test_a_new_ffmpeg_starts_a_new_detection(
    fake_env: ft.FakeTools, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = await Reframe.create()
    try:
        first = await app.capabilities.wait()
        other = ft.make_fake_tools(tmp_path / "other")
        other.set_scenario(
            ft.Scenario(
                [
                    ft.Rule(
                        argv_has=["-c:v", "hevc_amf"],
                        actions=[ft.stderr_data("detect_hevc_amf_no_runtime.stderr.txt")],
                        exit_code=171,
                    )
                ]
            )
        )
        monkeypatch.setenv("REFRAME_FFMPEG", str(other.ffmpeg))
        tools = await app.tools.rescan()
        assert tools.ffmpeg.path == other.ffmpeg
        await wait_until(lambda: app.capabilities.snapshot.ffmpeg == other.ffmpeg)
        second = await app.capabilities.wait()
        assert first.ffmpeg == fake_env.ffmpeg
        assert second.ffmpeg == other.ffmpeg
        assert second.status("hevc_amf").reason == "AMD AMF runtime not found (libamfrt64.so.1)"
        other.kill_leftovers()
    finally:
        await app.close()


async def test_first_start_without_cache(harness: Harness) -> None:
    harness.service.start()
    snapshot = harness.service.snapshot
    assert snapshot.detecting
    assert {s.state for s in snapshot.encoders.values()} == {UNKNOWN}
    final = await harness.service.wait()
    assert not final.detecting
    assert not final.from_cache
    events = changed(drain(harness.subscription))
    assert {s.state for s in events[0].encoders} == {CHECKING}
    assert len(events[0].encoders) == len(final.encoders)
    assert {s.id for s in events[-1].encoders} == set(final.encoders)
    middle = [s.id for e in events[1:-1] for s in e.encoders]
    assert "libx265" in middle
    assert "hevc_amf" in middle
    assert cache_files(harness.cache_dir)  # stored


async def test_second_start_shows_the_cached_result_at_once(
    harness: Harness, fake_tools: ft.FakeTools
) -> None:
    harness.service.start()
    first = await harness.service.wait()
    await harness.service.close()
    drain(harness.subscription)

    fake_tools.set_scenario(
        ft.Scenario(
            [
                ft.Rule(
                    argv_has=["-encoders"],
                    actions=[ft.sleep(1.5), ft.stdout_data("encoders.stdout.txt")],
                )
            ]
        )
    )
    harness.service = harness.make()
    harness.service.start()
    await wait_until(lambda: harness.service.snapshot.from_cache)
    cached = harness.service.snapshot
    assert cached.detecting  # checked again in the background
    assert cached.status("hevc_amf").state is AVAILABLE  # known before the detection ends
    assert cached.encoders == first.encoders
    final = await harness.service.wait()
    assert not final.from_cache
    assert not final.detecting
    events = changed(drain(harness.subscription))
    assert {s.state for s in events[0].encoders} == {s.state for s in first.encoders.values()}
    # nothing changed while checking again: only the cached and the final event
    assert len(events) == 2


async def test_a_changed_status_is_published(harness: Harness, fake_tools: ft.FakeTools) -> None:
    harness.service.start()
    await harness.service.wait()
    drain(harness.subscription)
    fake_tools.set_scenario(
        ft.Scenario(
            [
                ft.Rule(
                    argv_has=["-c:v", "hevc_amf"],
                    actions=[ft.stderr_data("detect_hevc_amf_no_runtime.stderr.txt")],
                    exit_code=171,
                )
            ]
        )
    )
    harness.service = harness.make()
    harness.service.start()
    final = await harness.service.wait()
    assert final.status("hevc_amf").state is EncoderState.UNAVAILABLE
    events = changed(drain(harness.subscription))
    middle = [s for e in events[1:-1] for s in e.encoders]
    assert [s.id for s in middle] == ["hevc_amf"]  # the only status that changed
    assert middle[0].reason == "AMD AMF runtime not found (libamfrt64.so.1)"


async def test_rescan_cancels_the_running_detection(
    harness: Harness, fake_tools: ft.FakeTools
) -> None:
    fake_tools.set_scenario(ft.Scenario([ft.Rule(argv_has=["-c:v"], actions=[ft.hang()])]))
    harness.service.start()
    await wait_until(lambda: len(encode_calls(fake_tools)) >= 3)
    hanging = fake_tools.pids()
    fake_tools.set_scenario(ft.Scenario())
    final = await harness.service.rescan()
    assert final.status("hevc_amf").state is AVAILABLE
    alive = [pid for pid in hanging if pid in fake_tools.kill_leftovers()]
    assert alive == []


async def test_rescan_ignores_the_cache(harness: Harness, fake_tools: ft.FakeTools) -> None:
    harness.service.start()
    await harness.service.wait()
    fake_tools.clear_log()
    drain(harness.subscription)
    final = await harness.service.rescan()
    assert not final.from_cache
    events = changed(drain(harness.subscription))
    assert {s.state for s in events[0].encoders} == {CHECKING}
    assert encode_calls(fake_tools)


async def test_waits_for_tool_discovery(harness: Harness) -> None:
    harness.tools.gate = asyncio.Event()
    harness.service.start()
    await asyncio.sleep(0.1)
    assert harness.service.snapshot.detecting
    assert harness.fake.calls() == []
    harness.tools.gate.set()
    assert (await harness.service.wait()).status("libx265").state is AVAILABLE


async def test_unusable_ffmpeg(harness: Harness, tmp_path: Path) -> None:
    harness.tools.tools = tool_set(
        ffmpeg_info(tmp_path / "ffmpeg", status=ToolStatus.TOO_OLD, reason="FFmpeg 6.1 is too old")
    )
    harness.service.start()
    final = await harness.service.wait()
    assert {s.state for s in final.encoders.values()} == {EncoderState.UNAVAILABLE}
    assert final.status("libx265").reason == "FFmpeg is too old"
    assert final.status("libx265").detail == "FFmpeg 6.1 is too old"
    assert harness.fake.calls() == []
    assert cache_files(tmp_path / "caps") == []


async def test_hardware_tests_off(harness: Harness, fake_tools: ft.FakeTools) -> None:
    harness.settings.encoders.hardware_tests = False
    harness.service.start()
    final = await harness.service.wait()
    assert final.status("hevc_amf").state is UNKNOWN
    assert encode_calls(fake_tools) == []


async def test_closest_available(harness: Harness, fake_tools: ft.FakeTools) -> None:
    fake_tools.set_scenario(
        ft.Scenario(
            [
                ft.Rule(
                    argv_has=["-c:v", "hevc_nvenc"],
                    actions=[ft.stderr_data("detect_hevc_nvenc_no_driver.stderr.txt")],
                    exit_code=255,
                ),
                ft.Rule(
                    argv_has=["-c:v", "hevc_qsv"],
                    actions=[ft.stderr_data("detect_hevc_qsv_no_device.stderr.txt")],
                    exit_code=187,
                ),
            ]
        )
    )
    await harness.service.wait()
    assert harness.service.closest_available("hevc_nvenc") == "hevc_amf"
    assert harness.service.closest_available("libx265") == "libx265"


async def test_a_detection_bug_becomes_error_statuses(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*args: object, **kw: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(service_module, "detect_capabilities", broken)
    harness.service.start()
    final = await harness.service.wait()
    assert not final.detecting
    assert {s.state for s in final.encoders.values()} == {EncoderState.ERROR}
    assert final.status("libx265").reason == "Encoder detection failed: RuntimeError: boom"


async def test_tools_changed_with_the_same_ffmpeg_does_nothing(harness: Harness) -> None:
    harness.service.start()
    await harness.service.wait()
    calls = len(harness.fake.calls())
    harness.events.publish(ToolsChangedEvent(tools=harness.tools.tools))
    await asyncio.sleep(0.2)
    assert not harness.service.detecting
    assert len(harness.fake.calls()) == calls


async def test_tools_changed_with_another_version_detects_again(harness: Harness) -> None:
    harness.service.start()
    await harness.service.wait()
    newer = ffmpeg_info(harness.fake.ffmpeg, version="n9.1")
    harness.tools.tools = tool_set(newer)
    harness.events.publish(ToolsChangedEvent(tools=harness.tools.tools))
    await wait_until(lambda: harness.service.snapshot.ffmpeg_version == "n9.1")
    final = await harness.service.wait()
    assert final.ffmpeg_version == "n9.1"


async def test_the_gpu_fingerprint_is_read_once(fake_tools: ft.FakeTools, tmp_path: Path) -> None:
    calls = 0

    def fingerprint() -> str:
        nonlocal calls
        calls += 1
        return GPU

    h = Harness(fake_tools, tmp_path / "caps", gpu_fingerprint=fingerprint)
    try:
        h.service.start()
        await h.service.wait()
        await h.service.rescan()
        assert calls == 1
    finally:
        await h.close()


async def test_a_failing_gpu_fingerprint_is_not_fatal(
    fake_tools: ft.FakeTools, tmp_path: Path
) -> None:
    def fingerprint() -> str:
        raise OSError("no sysfs")

    h = Harness(fake_tools, tmp_path / "caps", gpu_fingerprint=fingerprint)
    try:
        h.service.start()
        assert (await h.service.wait()).status("libx265").state is AVAILABLE
    finally:
        await h.close()


def cached_snapshot(folder: Path) -> Any:
    """The snapshot of the only cache entry, as JSON."""
    (path,) = cache_files(folder)
    return json.loads(path.read_text(encoding="utf-8"))["snapshot"]


async def test_closing_on_the_final_event_keeps_the_cache(
    harness: Harness, fake_tools: ft.FakeTools
) -> None:
    """The result is cached before the final event, so closing on that event keeps it."""
    service = harness.service
    subscription = harness.events.subscribe(types={"capabilities.changed"})

    async def close_on_the_final_event() -> CapabilitySnapshot:
        async for _event in subscription:
            if not service.snapshot.detecting:
                await service.close()
                break
        return service.snapshot

    closer = asyncio.ensure_future(close_on_the_final_event())
    service.start()
    first = await closer
    subscription.close()
    assert not first.detecting
    assert cache_files(harness.cache_dir), "the detection result was not cached"

    fake_tools.set_scenario(ft.Scenario([ft.Rule(argv_has=["-encoders"], actions=[ft.hang()])]))
    drain(harness.subscription)
    harness.service = harness.make()
    harness.service.start()
    event = await anext(harness.subscription)  # the first event of the next start
    assert isinstance(event, CapabilitiesChangedEvent)
    cached = harness.service.snapshot
    assert cached.from_cache
    assert cached.detecting  # checked again in the background (held by the hanging listing)
    assert cached.encoders == first.encoders
    assert {s.id: s for s in event.encoders} == first.encoders


async def test_wait_and_rescan_return_after_the_cache_write(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    put, publish = CapabilityCache.put, harness.events.publish

    def recording_put(cache: CapabilityCache, key: CacheKey, snapshot: CapabilitySnapshot) -> None:
        put(cache, key, snapshot)
        order.append("cached")

    def recording_publish(event: Event) -> None:
        if isinstance(event, CapabilitiesChangedEvent) and not harness.service.snapshot.detecting:
            order.append("final event")
        publish(event)

    monkeypatch.setattr(CapabilityCache, "put", recording_put)
    monkeypatch.setattr(harness.events, "publish", recording_publish)

    first = await harness.service.wait()
    assert order == ["cached", "final event"]
    assert cached_snapshot(harness.cache_dir) == first.model_dump(mode="json")

    order.clear()
    second = await harness.service.rescan()
    assert order == ["cached", "final event"]
    assert cached_snapshot(harness.cache_dir) == second.model_dump(mode="json")
    assert second.checked_at != first.checked_at


async def test_close_finishes_a_started_cache_write(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``close()`` cancels the detection but not a cache write that has started."""
    started, release = threading.Event(), threading.Event()
    put = CapabilityCache.put

    def slow_put(cache: CapabilityCache, key: CacheKey, snapshot: CapabilitySnapshot) -> None:
        started.set()
        release.wait(15)
        put(cache, key, snapshot)

    monkeypatch.setattr(CapabilityCache, "put", slow_put)
    harness.service.start()
    try:
        await wait_until(started.is_set)
        closing = asyncio.ensure_future(harness.service.close())
        await wait_until(lambda: not harness.service.detecting)  # the detection is cancelled ...
        assert not closing.done()  # ... but close() waits for the write
    finally:
        release.set()
    await closing
    assert cache_files(harness.cache_dir)
    assert not cached_snapshot(harness.cache_dir)["detecting"]


async def test_a_new_detection_waits_for_the_last_cache_write(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A re-scan during a cache write starts after the write: an older result never
    overwrites the newer one."""
    started, release = threading.Event(), threading.Event()
    put = CapabilityCache.put

    def slow_first_put(cache: CapabilityCache, key: CacheKey, snapshot: CapabilitySnapshot) -> None:
        if not started.is_set():
            started.set()
            release.wait(15)
        put(cache, key, snapshot)

    monkeypatch.setattr(CapabilityCache, "put", slow_first_put)
    harness.service.start()
    try:
        await wait_until(started.is_set)
        (first,) = running_detections()
        rescan = asyncio.ensure_future(harness.service.rescan())
        await wait_until(first.done)  # cancelled during its cache write ...
        await asyncio.sleep(0)
        assert harness.tools.calls == 1  # ... and the re-scan waits for the write
    finally:
        release.set()
    final = await rescan
    assert harness.tools.calls == 2
    assert cached_snapshot(harness.cache_dir) == final.model_dump(mode="json")


async def test_a_failing_cache_write_is_not_fatal(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(cache: CapabilityCache, key: CacheKey, snapshot: CapabilitySnapshot) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(CapabilityCache, "put", broken)
    final = await harness.service.wait()
    assert not final.detecting
    assert final.status("libx265").state is AVAILABLE
    assert final.status("hevc_amf").state is AVAILABLE
    assert cache_files(harness.cache_dir) == []


async def test_close_without_start(harness: Harness) -> None:
    await harness.service.close()
    await harness.service.close()  # twice is fine


def test_definitions_property(fake_tools: ft.FakeTools, tmp_path: Path) -> None:
    service = CapabilityService(
        EventBus(),
        StubTools(tool_set(ffmpeg_info(fake_tools.ffmpeg))),  # type: ignore[arg-type]
        AppSettings,
        cache_dir=tmp_path,
    )
    assert "libx265" in service.definitions.video_encoders
    assert not service.detecting
    assert set(service.snapshot.encoders) == set(service.definitions.video_encoders) | set(
        service.definitions.audio_encoders
    )


async def test_tool_discovery_closed_under_the_detection(harness: Harness) -> None:
    async def closed() -> object:
        raise ReframeClosedError

    harness.tools.status = closed  # type: ignore[method-assign,assignment]
    harness.service.start()
    snapshot = await harness.service.wait()
    assert {s.state for s in snapshot.encoders.values()} == {UNKNOWN}
    assert harness.fake.calls() == []


async def test_close_waits_for_a_replaced_detection(
    harness: Harness, fake_tools: ft.FakeTools
) -> None:
    """``rescan()`` replaces a detection whose test encodes are still being killed: ``close()``
    returns only when every detection it started has ended, so no test encode is left."""
    fake_tools.set_scenario(ft.Scenario([ft.Rule(argv_has=["-c:v"], actions=[ft.hang()])]))
    harness.service.start()
    await wait_until(lambda: len(encode_calls(fake_tools)) >= 3)
    rescan = asyncio.ensure_future(harness.service.rescan())
    await asyncio.sleep(0)  # rescan() cancels the running detection and starts a new one
    await harness.service.close()
    assert running_detections() == []
    assert fake_tools.kill_leftovers() == []
    with pytest.raises(ReframeClosedError):
        await rescan


async def test_a_new_ffmpeg_does_not_show_the_old_filter_results(
    harness: Harness, fake_tools: ft.FakeTools, tmp_path: Path
) -> None:
    """A re-scan of the same ffmpeg keeps the last filter results until the new ones are in;
    another ffmpeg starts without them."""
    capture = ft.captures()["detect_libplacebo_no_vulkan"]
    assert capture.stderr is not None
    fake_tools.set_scenario(
        ft.Scenario(
            [
                ft.Rule(
                    argv_has=["-vf", "libplacebo"],
                    actions=[ft.stderr_data(capture.stderr)],
                    exit_code=capture.exit_code,
                )
            ]
        )
    )
    harness.service.start()  # watches tools.changed
    first = await harness.service.wait()
    assert first.usable_filter("libplacebo") is False
    other = ft.make_fake_tools(tmp_path / "other")
    try:
        other.set_scenario(ft.Scenario([ft.Rule(argv_has=["-encoders"], actions=[ft.hang()])]))
        harness.tools.tools = tool_set(ffmpeg_info(other.ffmpeg))
        harness.events.publish(ToolsChangedEvent(tools=harness.tools.tools))
        await wait_until(lambda: harness.service.snapshot.ffmpeg == other.ffmpeg)
        snapshot = harness.service.snapshot
        assert snapshot.detecting
        assert snapshot.filters is None
        assert snapshot.filter_failures == {}
        assert snapshot.untested_filters == []
        assert snapshot.usable_filter("libplacebo") is None  # not known for this build yet
        await harness.service.close()
    finally:
        other.kill_leftovers()


async def test_a_failing_tool_discovery_ends_the_detection(harness: Harness) -> None:
    """An exception from tool discovery that is not "closed" is a failed detection (data):
    every status is an error and ``detecting`` ends, so nothing waits for ever."""

    async def broken() -> object:
        raise RuntimeError("discovery bug")

    harness.tools.status = broken  # type: ignore[method-assign,assignment]
    harness.service.start()
    final = await harness.service.wait()
    assert not final.detecting
    assert not harness.service.snapshot.detecting
    assert {s.state for s in final.encoders.values()} == {EncoderState.ERROR}
    assert final.status("libx265").reason == (
        "Encoder detection failed: RuntimeError: discovery bug"
    )
    events = changed(drain(harness.subscription))
    assert events, "no capabilities.changed event"
    assert {s.id for s in events[-1].encoders} == set(final.encoders)
    assert harness.fake.calls() == []


def no_driver_on(node: str) -> ft.Rule:
    """The real "no VA driver" failure for every VAAPI test encode on ``node``."""
    capture = ft.captures()["detect_h264_vaapi_no_driver"]
    assert capture.stderr is not None
    return ft.Rule(
        actions=[ft.stderr_data(capture.stderr)],
        exit_code=capture.exit_code,
        argv_contains=[f"vaapi=va:{node}"],
    )


def vaapi_nodes_used(fake: ft.FakeTools) -> set[str]:
    return {
        arg.removeprefix("vaapi=va:")
        for call in encode_calls(fake)
        for arg in call
        if arg.startswith("vaapi=va:")
    }


async def test_every_render_node_is_tried(harness: Harness, fake_tools: ft.FakeTools) -> None:
    harness.nodes = [NODE, OTHER_NODE]
    fake_tools.set_scenario(ft.Scenario([no_driver_on(NODE)]))
    final = await harness.service.wait()
    for encoder in ("h264_vaapi", "hevc_vaapi", "av1_vaapi"):
        status = final.status(encoder)
        assert (status.state, status.device) == (AVAILABLE, OTHER_NODE), status
    assert vaapi_nodes_used(fake_tools) == {NODE, OTHER_NODE}


async def test_the_setting_forces_one_node(harness: Harness, fake_tools: ft.FakeTools) -> None:
    harness.nodes = [NODE, OTHER_NODE]
    harness.settings.encoders.vaapi_device = OTHER_NODE
    final = await harness.service.wait()
    assert final.status("hevc_vaapi").device == OTHER_NODE
    assert vaapi_nodes_used(fake_tools) == {OTHER_NODE}


async def test_the_setting_and_the_nodes_are_in_the_cache_key(
    harness: Harness, fake_tools: ft.FakeTools
) -> None:
    await harness.service.wait()
    await harness.service.close()

    async def second_start() -> bool:
        """Start again; was the first snapshot after tool discovery from the cache?"""
        drain(harness.subscription)
        harness.service = harness.make()
        harness.service.start()
        await harness.service.wait()
        events = changed(drain(harness.subscription))
        cached = {s.state for s in events[0].encoders} != {CHECKING}
        await harness.service.close()
        return cached

    assert await second_start()  # same setting, same nodes: from the cache
    harness.settings.encoders.vaapi_device = OTHER_NODE
    assert not await second_start()  # the setting changed
    harness.settings.encoders.vaapi_device = None
    harness.nodes = [NODE, OTHER_NODE]
    assert not await second_start()  # another node appeared
    assert await second_start()


async def test_libplacebo_result_is_in_the_snapshot(
    harness: Harness, fake_tools: ft.FakeTools
) -> None:
    capture = ft.captures()["detect_libplacebo_no_vulkan"]
    assert capture.stderr is not None
    fake_tools.set_scenario(
        ft.Scenario(
            [
                ft.Rule(
                    argv_has=["-vf", "libplacebo"],
                    actions=[ft.sleep(0.5), ft.stderr_data(capture.stderr)],
                    exit_code=capture.exit_code,
                )
            ]
        )
    )
    first = await harness.service.wait()
    assert first.usable_filter("libplacebo") is False
    assert first.filter_failures["libplacebo"].startswith("No working Vulkan driver")
    # a re-scan keeps the last filter results until the new ones are in
    rescan = asyncio.ensure_future(harness.service.rescan())
    await wait_until(lambda: harness.service.snapshot.status("libx265").state is CHECKING)
    assert harness.service.snapshot.usable_filter("libplacebo") is False
    await rescan
