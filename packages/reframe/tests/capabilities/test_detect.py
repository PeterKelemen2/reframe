"""One detection run with the fake ffmpeg (05 §C-4 "Done when": a fake-ffmpeg test double that
sleeps or prints driver errors proves timeouts and reason mapping)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from reframe.capabilities import NOT_IN_BUILD, DetectionOptions, detect_capabilities
from reframe.capabilities import hwtest as hwtest_module
from reframe.definitions import load_definitions
from reframe.models import EncoderState, EncoderStatus, ToolInfo, ToolStatus
from reframe.tools import CancelToken, RunResult, run
from reframe_testing import fake_tools as ft
from reframe_testing.capabilities import c4_rule, ffmpeg_info

pytestmark = pytest.mark.anyio

DEFS = load_definitions()
LINUX = DetectionOptions(os="linux")
HARDWARE = [enc.id for enc in DEFS.video_encoders.values() if enc.hardware]
SOFTWARE = [enc.id for enc in DEFS.video_encoders.values() if not enc.hardware]
AVAILABLE = EncoderState.AVAILABLE
UNAVAILABLE = EncoderState.UNAVAILABLE
ERROR = EncoderState.ERROR


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
    # every hardware encoder was tested at 8 bit, and those with a 10-bit format at 10 bit
    calls = encode_calls(fake_tools)
    eight = [c[c.index("-c:v") + 1] for c in calls if not any("p010le" in a for a in c)]
    ten = [c[c.index("-c:v") + 1] for c in calls if any("p010le" in a for a in c)]
    assert sorted(eight) == sorted(HARDWARE)
    ten_bit = [e for e in HARDWARE if "10" in DEFS.video_encoders[e].pix_fmts]
    assert sorted(ten) == sorted(ten_bit)
    # help was read for every encoder in the build
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
    options = DetectionOptions(os="linux", test_timeout=0.5)
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
    assert fake_tools.kill_leftovers() == []  # nothing left running


async def test_a_crash_is_an_error(fake_tools: ft.FakeTools, fake_ffmpeg: ToolInfo) -> None:
    fake_tools.set_scenario(
        ft.Scenario([ft.Rule(argv_has=["-c:v", "hevc_amf"], actions=[ft.crash(exit_code=139)])])
    )
    snap = await detect_capabilities(fake_ffmpeg, DEFS, LINUX)
    status = snap.status("hevc_amf")
    assert status.state is ERROR
    assert status.reason == "The test encode failed with no message (exit code 139)"


async def test_hardware_tests_off(fake_tools: ft.FakeTools, fake_ffmpeg: ToolInfo) -> None:
    options = DetectionOptions(os="linux", hardware_tests=False)
    snap = await detect_capabilities(fake_ffmpeg, DEFS, options)
    for encoder in HARDWARE:
        status = snap.status(encoder)
        assert status.state is EncoderState.UNKNOWN
        assert status.in_build is True
        assert status.reason == "Not tested: hardware test encodes are off (Settings → Encoders)"
        assert status.private_options  # the help was still read
    assert encode_calls(fake_tools) == []
    assert snap.status("libx265").state is AVAILABLE


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
    options = DetectionOptions(os="linux", list_timeout=0.5)
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
