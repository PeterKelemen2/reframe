"""Capability detection against the fake ffmpeg."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from reframe.capabilities import (
    NOT_IN_BUILD,
    DetectionOptions,
    detect_capabilities,
    filter_test_argv,
    vaapi_nodes,
)
from reframe.capabilities import hwtest as hwtest_module
from reframe.definitions import load_definitions
from reframe.models import EncoderState, EncoderStatus, ToolInfo, ToolStatus
from reframe.tools import CancelToken, RunResult, run
from reframe_testing import fake_tools as ft
from reframe_testing.capabilities import c4_rule, ffmpeg_info

pytestmark = pytest.mark.anyio

DEFS = load_definitions()
NODE = "/dev/dri/renderD128"
OTHER_NODE = "/dev/dri/renderD129"


def linux(**kw: object) -> DetectionOptions:
    """Linux with one render node (the test does not depend on this machine's /dev/dri)."""
    return DetectionOptions(**{"os": "linux", "render_nodes": (NODE,), **kw})  # type: ignore[arg-type]


LINUX = linux()
HARDWARE = [enc.id for enc in DEFS.video_encoders.values() if enc.hardware]
SOFTWARE = [enc.id for enc in DEFS.video_encoders.values() if not enc.hardware]
AVAILABLE = EncoderState.AVAILABLE
UNAVAILABLE = EncoderState.UNAVAILABLE
ERROR = EncoderState.ERROR
#: The warning FFmpeg prints when it replaces the ``-pix_fmt`` of a test encode; it then exits 0.
AUTO_SELECTED = (
    "Incompatible pixel format 'p010le' for codec 'hevc_amf', auto-selecting format 'nv12'\n"
)


async def until(condition: Callable[[], bool], limit: float = 10.0) -> None:
    deadline = time.monotonic() + limit
    while not condition():
        if time.monotonic() > deadline:
            raise TimeoutError("condition not met in time")
        await asyncio.sleep(0.02)


def encode_calls(fake: ft.FakeTools) -> list[tuple[str, ...]]:
    return [call for call in fake.calls() if "-c:v" in call]


async def test_everything_works(fake_tools: ft.FakeTools, fake_ffmpeg: ToolInfo) -> None:
    updates: list[list[EncoderStatus]] = []
    snap = await detect_capabilities(fake_ffmpeg, DEFS, LINUX, on_update=updates.append)
    assert set(snap.encoders) == set(DEFS.video_encoders) | set(DEFS.audio_encoders)
    assert not snap.detecting
    assert not snap.from_cache
    assert snap.checked_at is not None
    assert (snap.ffmpeg, snap.ffmpeg_version) == (fake_tools.ffmpeg, fake_ffmpeg.version)
    assert snap.has_filter("libplacebo") is True
    assert snap.has_filter("zscale") is True
    for status in snap.encoders.values():
        if status.id == "libfdk_aac":
            assert (status.state, status.reason, status.in_build) == (
                UNAVAILABLE,
                NOT_IN_BUILD,
                False,
            )
            continue
        assert status.state is AVAILABLE, status
        assert status.in_build is True
        assert status.checked_at is not None
    x265 = snap.status("libx265")
    assert x265.supports_10bit is True  # yuv420p10le is in the build's pixel formats
    assert "x265-params" in x265.private_options
    assert snap.status("hevc_nvenc").presets[-1] == "p7"
    assert snap.status("hevc_nvenc").hardware
    # 10-bit: tested where the definition has a 10-bit pixel format, else False
    assert snap.status("hevc_vaapi").supports_10bit is True
    assert snap.status("h264_vaapi").supports_10bit is False
    assert snap.status("h264_amf").supports_10bit is False
    assert snap.status("aac").supports_10bit is None
    calls = encode_calls(fake_tools)
    eight = [c[c.index("-c:v") + 1] for c in calls if not any("p010le" in a for a in c)]
    ten = [c[c.index("-c:v") + 1] for c in calls if any("p010le" in a for a in c)]
    assert sorted(eight) == sorted(HARDWARE)
    ten_bit = [e for e in HARDWARE if "10" in DEFS.video_encoders[e].pix_fmts]
    assert sorted(ten) == sorted(ten_bit)
    helps = {c[-1] for c in fake_tools.calls() if "-h" in c}
    assert helps == {f"encoder={e}" for e in snap.encoders if e != "libfdk_aac"}
    # updates: the classification first, then each hardware encoder once, the help once
    first = {s.id: s.state for s in updates[0]}
    assert first["libx265"] is AVAILABLE
    assert "hevc_nvenc" not in first  # still being tested
    assert all(len(u) >= 1 for u in updates)


async def test_driver_errors_are_mapped(fake_tools: ft.FakeTools, fake_ffmpeg: ToolInfo) -> None:
    fake_tools.set_scenario(
        ft.Scenario(
            [
                c4_rule("c4_hevc_nvenc_no_driver"),
                c4_rule("c4_hevc_nvenc_no_driver", encoder="h264_nvenc"),
                c4_rule("c4_hevc_qsv_no_device"),
                c4_rule("c4_h264_vaapi_no_driver"),
                c4_rule("c4_h264_vaapi_bad_device", encoder="hevc_vaapi"),
                c4_rule("c4_hevc_amf_no_runtime"),
                c4_rule("c4_h264_amf_10bit", encoder="av1_amf", ten_bit=True),
            ]
        )
    )
    snap = await detect_capabilities(fake_ffmpeg, DEFS, LINUX)

    def row(encoder: str) -> tuple[EncoderState, str | None]:
        status = snap.status(encoder)
        return status.state, status.reason

    assert row("hevc_nvenc") == (UNAVAILABLE, "NVIDIA driver not found")
    assert row("h264_nvenc") == (UNAVAILABLE, "NVIDIA driver not found")
    assert row("av1_nvenc") == (AVAILABLE, None)  # no rule: the fake's test encode works
    assert row("hevc_qsv") == (
        UNAVAILABLE,
        "No Intel QSV device (needs an Intel GPU with its media driver)",
    )
    assert row("h264_vaapi") == (
        UNAVAILABLE,
        "VAAPI driver failed to start on /dev/dri/renderD128 (unknown libva error)",
    )
    # the capture asked for renderD999: the device in FFmpeg's text wins
    assert row("hevc_vaapi") == (UNAVAILABLE, "No VAAPI device (/dev/dri/renderD999)")
    assert row("hevc_amf") == (UNAVAILABLE, "AMD AMF runtime not found (libamfrt64.so.1)")
    assert snap.status("hevc_nvenc").detail == "[hevc_nvenc] Cannot load libcuda.so.1"
    assert snap.status("hevc_nvenc").supports_10bit is None  # 8-bit failed: 10-bit not run
    # 10-bit fails, 8-bit works: available, without 10-bit, with the reason
    av1 = snap.status("av1_amf")
    assert (av1.state, av1.supports_10bit, av1.reason_10bit) == (
        AVAILABLE,
        False,
        "10-bit is not supported by this encoder",
    )


async def test_timeouts_are_errors(fake_tools: ft.FakeTools, fake_ffmpeg: ToolInfo) -> None:
    fake_tools.set_scenario(
        ft.Scenario(
            [
                ft.Rule(argv_has=["-c:v", "hevc_vaapi"], actions=[ft.hang()]),
                ft.Rule(argv_has=["-c:v", "av1_vaapi"], actions=[ft.sleep(30)]),
                ft.Rule(
                    argv_has=["-c:v", "hevc_amf"], argv_contains=["p010le"], actions=[ft.hang()]
                ),
            ]
        )
    )
    options = linux(test_timeout=0.5)
    started = time.monotonic()
    snap = await detect_capabilities(fake_ffmpeg, DEFS, options)
    assert time.monotonic() - started < 10
    for encoder in ("hevc_vaapi", "av1_vaapi"):
        status = snap.status(encoder)
        assert (status.state, status.reason) == (
            ERROR,
            "The test encode did not finish within 0.5 s",
        )
    amf = snap.status("hevc_amf")
    assert (amf.state, amf.supports_10bit, amf.reason_10bit) == (
        AVAILABLE,
        False,
        "The test encode did not finish within 0.5 s",
    )
    assert fake_tools.kill_leftovers() == []


async def test_a_crash_is_an_error(fake_tools: ft.FakeTools, fake_ffmpeg: ToolInfo) -> None:
    fake_tools.set_scenario(
        ft.Scenario([ft.Rule(argv_has=["-c:v", "hevc_amf"], actions=[ft.crash(exit_code=139)])])
    )
    snap = await detect_capabilities(fake_ffmpeg, DEFS, LINUX)
    status = snap.status("hevc_amf")
    assert status.state is ERROR
    assert status.reason == "The test encode failed with no message (exit code 139)"


async def test_hardware_tests_off(fake_tools: ft.FakeTools, fake_ffmpeg: ToolInfo) -> None:
    options = linux(hardware_tests=False)
    snap = await detect_capabilities(fake_ffmpeg, DEFS, options)
    for encoder in HARDWARE:
        status = snap.status(encoder)
        assert status.state is EncoderState.UNKNOWN
        assert status.in_build is True
        assert status.reason == "Not tested: hardware test encodes are off (Settings → Encoders)"
        assert status.private_options  # the help was still read
    assert encode_calls(fake_tools) == []
    assert snap.status("libx265").state is AVAILABLE


async def test_hardware_tests_off_keeps_the_forced_vaapi_device(
    fake_tools: ft.FakeTools, fake_ffmpeg: ToolInfo
) -> None:
    forced = linux(hardware_tests=False, vaapi_device=f" {OTHER_NODE} ")
    snap = await detect_capabilities(fake_ffmpeg, DEFS, forced)
    for encoder in ("h264_vaapi", "hevc_vaapi", "av1_vaapi"):
        status = snap.status(encoder)
        assert (status.state, status.device) == (EncoderState.UNKNOWN, OTHER_NODE), status
    assert snap.status("hevc_amf").device is None  # not a VAAPI encoder
    assert snap.status("hevc_qsv").device is None
    automatic = await detect_capabilities(fake_ffmpeg, DEFS, linux(hardware_tests=False))
    assert automatic.status("hevc_vaapi").device is None  # no node is known without a test
    assert encode_calls(fake_tools) == []


async def test_a_10bit_test_with_another_pixel_format_fails(
    fake_tools: ft.FakeTools, fake_ffmpeg: ToolInfo
) -> None:
    """FFmpeg replaces a pixel format the encoder does not take and exits 0: the 10-bit test
    did not encode 10-bit."""
    fake_tools.set_scenario(
        ft.Scenario(
            [
                ft.Rule(
                    argv_has=["-c:v", "hevc_amf"],
                    argv_contains=["p010le"],
                    actions=[ft.stderr(AUTO_SELECTED)],
                )
            ]
        )
    )
    snap = await detect_capabilities(fake_ffmpeg, DEFS, LINUX)
    status = snap.status("hevc_amf")
    assert status.state is AVAILABLE  # the 8-bit test worked
    assert status.supports_10bit is False
    assert status.reason_10bit == "hevc_amf does not take p010le in this FFmpeg build (it got nv12)"
    assert snap.status("av1_amf").supports_10bit is True


async def test_platforms(fake_tools: ft.FakeTools, fake_ffmpeg: ToolInfo) -> None:
    snap = await detect_capabilities(fake_ffmpeg, DEFS, DetectionOptions(os="windows"))
    for encoder in ("h264_vaapi", "hevc_vaapi", "av1_vaapi"):
        status = snap.status(encoder)
        assert (status.state, status.reason) == (UNAVAILABLE, "Not available on Windows")
    assert snap.status("hevc_amf").state is AVAILABLE
    tested = {c[c.index("-c:v") + 1] for c in encode_calls(fake_tools)}
    assert not tested & {"h264_vaapi", "hevc_vaapi", "av1_vaapi"}


async def test_not_in_this_build(fake_tools: ft.FakeTools, fake_ffmpeg: ToolInfo) -> None:
    listing = (ft.DATA_DIR / "encoders.stdout.txt").read_text(encoding="utf-8")
    trimmed = "".join(
        line
        for line in listing.splitlines(keepends=True)
        if not any(f" {name} " in line for name in ("libx265", "hevc_nvenc", "libopus"))
    )
    fake_tools.set_scenario(
        ft.Scenario([ft.Rule(argv_has=["-encoders"], actions=[ft.stdout(trimmed)])])
    )
    snap = await detect_capabilities(fake_ffmpeg, DEFS, LINUX)
    for encoder in ("libx265", "hevc_nvenc", "libopus"):
        status = snap.status(encoder)
        assert (status.state, status.reason, status.in_build) == (UNAVAILABLE, NOT_IN_BUILD, False)
    tested = {c[c.index("-c:v") + 1] for c in encode_calls(fake_tools)}
    assert "hevc_nvenc" not in tested
    assert "encoder=libx265" not in {c[-1] for c in fake_tools.calls()}


@pytest.mark.parametrize(
    ("rule", "reason"),
    [
        (
            ft.Rule(argv_has=["-encoders"], actions=[ft.stderr("boom\n")], exit_code=1),
            "ffmpeg -encoders exited with code 1: boom",
        ),
        (
            ft.Rule(argv_has=["-encoders"], actions=[ft.stdout("nothing useful\n")]),
            "ffmpeg -encoders printed no encoder list",
        ),
        (
            ft.Rule(argv_has=["-encoders"], actions=[ft.hang()]),
            "FFmpeg did not list its encoders within 0.5 s",
        ),
    ],
)
async def test_no_encoder_list(
    fake_tools: ft.FakeTools, fake_ffmpeg: ToolInfo, rule: ft.Rule, reason: str
) -> None:
    fake_tools.set_scenario(ft.Scenario([rule]))
    options = linux(list_timeout=0.5)
    snap = await detect_capabilities(fake_ffmpeg, DEFS, options)
    assert {s.state for s in snap.encoders.values()} == {ERROR}
    assert {s.reason for s in snap.encoders.values()} == {reason}
    assert snap.filters is not None  # -filters still worked
    assert encode_calls(fake_tools) == []


async def test_no_filter_list(fake_tools: ft.FakeTools, fake_ffmpeg: ToolInfo) -> None:
    fake_tools.set_scenario(
        ft.Scenario([ft.Rule(argv_has=["-filters"], actions=[ft.stderr("x\n")], exit_code=1)])
    )
    snap = await detect_capabilities(fake_ffmpeg, DEFS, LINUX)
    assert snap.filters is None
    assert snap.has_filter("zscale") is None
    assert snap.status("libx265").state is AVAILABLE


async def test_failed_help_keeps_the_status(
    fake_tools: ft.FakeTools, fake_ffmpeg: ToolInfo
) -> None:
    fake_tools.set_scenario(
        ft.Scenario(
            [ft.Rule(argv_has=["encoder=libx265"], actions=[ft.stderr("x\n")], exit_code=1)]
        )
    )
    snap = await detect_capabilities(fake_ffmpeg, DEFS, LINUX)
    x265 = snap.status("libx265")
    assert (x265.state, x265.private_options, x265.supports_10bit) == (AVAILABLE, [], None)


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (ToolStatus.MISSING, "FFmpeg not found"),
        (ToolStatus.TOO_OLD, "FFmpeg is too old"),
        (ToolStatus.BROKEN, "FFmpeg does not work"),
    ],
)
async def test_unusable_ffmpeg(tmp_path: Path, status: ToolStatus, reason: str) -> None:
    info = ffmpeg_info(tmp_path / "ffmpeg", status=status, reason="the tool's own reason")
    updates: list[list[EncoderStatus]] = []
    snap = await detect_capabilities(info, DEFS, LINUX, on_update=updates.append)
    assert {s.state for s in snap.encoders.values()} == {UNAVAILABLE}
    assert {s.reason for s in snap.encoders.values()} == {reason}
    assert {s.detail for s in snap.encoders.values()} == {"the tool's own reason"}
    assert not snap.detecting
    assert len(updates) == 1


async def test_at_most_three_tests_at_once(
    fake_tools: ft.FakeTools, fake_ffmpeg: ToolInfo, monkeypatch: pytest.MonkeyPatch
) -> None:
    running = 0
    peak = 0

    async def counting_run(argv: list[str], **kw: object) -> RunResult:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        try:
            await asyncio.sleep(0.05)
            return await run(argv, **kw)  # type: ignore[arg-type]
        finally:
            running -= 1

    monkeypatch.setattr(hwtest_module, "run", counting_run)
    await detect_capabilities(fake_ffmpeg, DEFS, LINUX)
    assert peak == 3


async def test_cancel_kills_the_tests(fake_tools: ft.FakeTools, fake_ffmpeg: ToolInfo) -> None:
    fake_tools.set_scenario(ft.Scenario([ft.Rule(argv_has=["-c:v"], actions=[ft.hang()])]))
    token = CancelToken()
    task = asyncio.create_task(detect_capabilities(fake_ffmpeg, DEFS, LINUX, cancel=token))
    await until(lambda: len(encode_calls(fake_tools)) >= 3)
    token.cancel("test")
    snap = await asyncio.wait_for(task, 10)
    assert snap.status("hevc_vaapi").state is EncoderState.CHECKING
    assert fake_tools.kill_leftovers() == []


async def test_task_cancel_kills_the_tests(fake_tools: ft.FakeTools, fake_ffmpeg: ToolInfo) -> None:
    fake_tools.set_scenario(ft.Scenario([ft.Rule(argv_has=["-c:v"], actions=[ft.hang()])]))
    task = asyncio.create_task(detect_capabilities(fake_ffmpeg, DEFS, LINUX))
    await until(lambda: len(encode_calls(fake_tools)) >= 3)
    task.cancel()
    await asyncio.wait({task})
    assert task.cancelled()
    assert fake_tools.kill_leftovers() == []


def vaapi_calls(fake: ft.FakeTools, encoder: str) -> list[tuple[str, str]]:
    """``(node, pixel format)`` of each test encode of ``encoder``, in order."""
    calls = []
    for call in encode_calls(fake):
        if call[call.index("-c:v") + 1] != encoder:
            continue
        node = next(a.removeprefix("vaapi=va:") for a in call if a.startswith("vaapi=va:"))
        vf = call[call.index("-vf") + 1]
        calls.append((node, vf.split(",")[0].removeprefix("format=")))
    return calls


def node_rule(capture: str, node: str, encoder: str | None = None) -> ft.Rule:
    """Replay ``capture`` for the VAAPI test encodes on ``node`` only."""
    rule = c4_rule(capture, encoder=encoder)
    return ft.Rule(
        actions=rule.actions,
        exit_code=rule.exit_code,
        argv_has=rule.argv_has,
        argv_contains=[f"vaapi=va:{node}"],
    )


async def test_vaapi_uses_the_first_node_that_works(
    fake_tools: ft.FakeTools, fake_ffmpeg: ToolInfo
) -> None:
    """Two render nodes; the encoder fails on the first one (no VA driver)."""
    fake_tools.set_scenario(
        ft.Scenario([node_rule("c4_h264_vaapi_no_driver", NODE, encoder="hevc_vaapi")])
    )
    options = linux(render_nodes=(NODE, OTHER_NODE))
    snap = await detect_capabilities(fake_ffmpeg, DEFS, options)
    hevc = snap.status("hevc_vaapi")
    assert (hevc.state, hevc.device, hevc.supports_10bit) == (AVAILABLE, OTHER_NODE, True)
    assert hevc.reason is None
    assert vaapi_calls(fake_tools, "hevc_vaapi") == [
        (NODE, "nv12"),
        (OTHER_NODE, "nv12"),
        (OTHER_NODE, "p010le"),
    ]
    h264 = snap.status("h264_vaapi")
    assert (h264.state, h264.device) == (AVAILABLE, NODE)
    assert vaapi_calls(fake_tools, "h264_vaapi") == [(NODE, "nv12")]
    # encoders without a device choice have none
    assert snap.status("hevc_amf").device is None
    assert snap.status("libx265").device is None


async def test_vaapi_fails_on_every_node(fake_tools: ft.FakeTools, fake_ffmpeg: ToolInfo) -> None:
    fake_tools.set_scenario(
        ft.Scenario(
            [
                node_rule("c4_h264_vaapi_no_driver", NODE),
                node_rule("c4_h264_vaapi_bad_device", OTHER_NODE),
            ]
        )
    )
    snap = await detect_capabilities(fake_ffmpeg, DEFS, linux(render_nodes=(NODE, OTHER_NODE)))
    status = snap.status("h264_vaapi")
    # the first node's reason (its own failure), no device
    assert (status.state, status.reason, status.device) == (
        UNAVAILABLE,
        "VAAPI driver failed to start on /dev/dri/renderD128 (unknown libva error)",
        None,
    )
    assert [node for node, _ in vaapi_calls(fake_tools, "h264_vaapi")] == [NODE, OTHER_NODE]


async def test_vaapi_without_a_render_node(fake_tools: ft.FakeTools, fake_ffmpeg: ToolInfo) -> None:
    snap = await detect_capabilities(fake_ffmpeg, DEFS, linux(render_nodes=()))
    for encoder in ("h264_vaapi", "hevc_vaapi", "av1_vaapi"):
        status = snap.status(encoder)
        assert (status.state, status.reason) == (
            UNAVAILABLE,
            "No VAAPI device (no render node in /dev/dri)",
        )
        assert vaapi_calls(fake_tools, encoder) == []
    assert snap.status("hevc_amf").state is AVAILABLE


async def test_a_forced_vaapi_device_is_the_only_one_tested(
    fake_tools: ft.FakeTools, fake_ffmpeg: ToolInfo
) -> None:
    fake_tools.set_scenario(ft.Scenario([node_rule("c4_h264_vaapi_no_driver", OTHER_NODE)]))
    options = linux(render_nodes=(NODE, OTHER_NODE), vaapi_device=OTHER_NODE)
    snap = await detect_capabilities(fake_ffmpeg, DEFS, options)
    status = snap.status("h264_vaapi")
    assert (status.state, status.device) == (UNAVAILABLE, None)
    assert status.reason == (
        "VAAPI driver failed to start on /dev/dri/renderD129 (unknown libva error)"
    )
    assert vaapi_calls(fake_tools, "h264_vaapi") == [(OTHER_NODE, "nv12")]
    assert snap.status("hevc_vaapi").device == OTHER_NODE


def test_vaapi_nodes(tmp_path: Path) -> None:
    assert vaapi_nodes(DetectionOptions(vaapi_device=" /dev/dri/renderD130 ")) == [
        "/dev/dri/renderD130"
    ]
    assert vaapi_nodes(DetectionOptions(vaapi_device="", render_nodes=(NODE,))) == [NODE]
    assert vaapi_nodes(DetectionOptions(render_nodes=())) == []


async def test_libplacebo_works(fake_tools: ft.FakeTools, fake_ffmpeg: ToolInfo) -> None:
    snap = await detect_capabilities(fake_ffmpeg, DEFS, LINUX)
    assert snap.usable_filter("libplacebo") is True
    assert (snap.filter_failures, snap.untested_filters) == ({}, [])
    (call,) = [c for c in fake_tools.calls() if "libplacebo" in c]
    assert call == tuple(filter_test_argv("ffmpeg", "libplacebo")[1:])


async def test_libplacebo_without_vulkan(fake_tools: ft.FakeTools, fake_ffmpeg: ToolInfo) -> None:
    capture = ft.captures()["c4_libplacebo_no_vulkan"]
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
    snap = await detect_capabilities(fake_ffmpeg, DEFS, LINUX)
    assert snap.has_filter("libplacebo") is True  # listed by -filters
    assert snap.usable_filter("libplacebo") is False
    assert snap.filter_failures == {
        "libplacebo": "No working Vulkan driver (VK_ERROR_INCOMPATIBLE_DRIVER)"
    }
    assert snap.usable_filter("zscale") is True


async def test_libplacebo_timeout(fake_tools: ft.FakeTools, fake_ffmpeg: ToolInfo) -> None:
    fake_tools.set_scenario(
        ft.Scenario([ft.Rule(argv_has=["-vf", "libplacebo"], actions=[ft.hang()])])
    )
    snap = await detect_capabilities(fake_ffmpeg, DEFS, linux(test_timeout=0.5))
    assert snap.filter_failures == {"libplacebo": "The libplacebo test did not finish within 0.5 s"}
    assert snap.usable_filter("libplacebo") is False
    assert fake_tools.kill_leftovers() == []


async def test_libplacebo_untested_when_hardware_tests_are_off(
    fake_tools: ft.FakeTools, fake_ffmpeg: ToolInfo
) -> None:
    snap = await detect_capabilities(fake_ffmpeg, DEFS, linux(hardware_tests=False))
    assert snap.untested_filters == ["libplacebo"]
    assert snap.usable_filter("libplacebo") is None
    assert [c for c in fake_tools.calls() if "libplacebo" in c] == []


async def test_libplacebo_not_in_the_build(fake_tools: ft.FakeTools, fake_ffmpeg: ToolInfo) -> None:
    listing = (ft.DATA_DIR / "filters.stdout.txt").read_text(encoding="utf-8")
    trimmed = "".join(
        line for line in listing.splitlines(keepends=True) if " libplacebo " not in line
    )
    fake_tools.set_scenario(
        ft.Scenario([ft.Rule(argv_has=["-filters"], actions=[ft.stdout(trimmed)])])
    )
    snap = await detect_capabilities(fake_ffmpeg, DEFS, LINUX)
    assert snap.usable_filter("libplacebo") is False
    assert snap.untested_filters == []
    assert [c for c in fake_tools.calls() if "libplacebo" in c] == []
