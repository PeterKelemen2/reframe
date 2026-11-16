"""The hardware test encode command (pure) and one run with the fake ffmpeg."""

from __future__ import annotations

import pytest

from reframe.capabilities import (
    Failure,
    filter_test_argv,
    hardware_test_argv,
    run_filter_test,
    run_hardware_test,
)
from reframe.capabilities.hwtest import BitDepth
from reframe.definitions import load_definitions
from reframe.models import EncoderState, ToolInfo
from reframe_testing import fake_tools as ft
from reframe_testing.capabilities import detect_rule

pytestmark = pytest.mark.anyio

ENCODERS = load_definitions().video_encoders
HEAD = ["ffmpeg", "-hide_banner", "-nostdin"]
SOURCE = ["-f", "lavfi", "-i", "color=size=640x360", "-frames:v", "3"]


def test_vaapi_command() -> None:
    assert hardware_test_argv("ffmpeg", ENCODERS["hevc_vaapi"], "10") == [
        *HEAD,
        *("-init_hw_device", "vaapi=va:/dev/dri/renderD128", "-filter_hw_device", "va"),
        *SOURCE,
        *("-vf", "format=p010le,hwupload", "-c:v", "hevc_vaapi", "-f", "null", "-"),
    ]
    other = hardware_test_argv("ffmpeg", ENCODERS["h264_vaapi"], vaapi_device="/dev/dri/renderD129")
    assert "vaapi=va:/dev/dri/renderD129" in other


def test_software_frames_command() -> None:
    """NVENC and AMF take software frames: ``-pix_fmt`` from the definition."""
    assert hardware_test_argv("ffmpeg", ENCODERS["hevc_nvenc"]) == [
        *HEAD,
        *SOURCE,
        *("-pix_fmt", "yuv420p", "-c:v", "hevc_nvenc", "-f", "null", "-"),
    ]
    assert hardware_test_argv("ffmpeg", ENCODERS["av1_amf"], "10")[-7:] == [
        *("-pix_fmt", "p010le", "-c:v", "av1_amf", "-f", "null", "-"),
    ]


def test_qsv_command() -> None:
    argv = hardware_test_argv("ffmpeg", ENCODERS["hevc_qsv"])
    assert argv[3:7] == ["-init_hw_device", "qsv=hw", "-filter_hw_device", "hw"]
    assert argv[argv.index("-vf") + 1] == "format=nv12,hwupload=extra_hw_frames=64,format=qsv"


#: The ``detect_*`` captures made with :func:`hardware_test_argv` (``detect_h264_amf_10bit`` is not:
#: h264_amf has no 10-bit pixel format in the definitions).
HARDWARE_CAPTURES = sorted(
    n
    for n in ft.captures()
    if n.startswith("detect_") and n != "detect_h264_amf_10bit" and "libplacebo" not in n
)
FILTER_CAPTURES = sorted(n for n in ft.captures() if n.startswith("detect_libplacebo"))


def test_there_are_hardware_and_filter_captures() -> None:
    assert len(HARDWARE_CAPTURES) == 9
    assert FILTER_CAPTURES == ["detect_libplacebo_no_vulkan", "detect_libplacebo_ok"]


@pytest.mark.parametrize("name", FILTER_CAPTURES)
def test_the_filter_captures_ran_the_current_command(name: str) -> None:
    assert list(ft.captures()[name].command) == filter_test_argv("ffmpeg", "libplacebo")


def test_filter_command() -> None:
    assert filter_test_argv("ffmpeg", "libplacebo") == [
        *HEAD,
        *("-f", "lavfi", "-i", "color=size=640x360", "-frames:v", "1"),
        *("-vf", "libplacebo", "-f", "null", "-"),
    ]


@pytest.mark.parametrize("name", HARDWARE_CAPTURES)
def test_the_hardware_captures_ran_the_current_command(name: str) -> None:
    """If a hardware setup in the definitions changes, capture again
    (``capture_fake_data.py --only detect_…``)."""
    capture = ft.captures()[name]
    command = list(capture.command)
    encoder = ENCODERS[command[command.index("-c:v") + 1]]
    bit_depth: BitDepth = "10" if any("p010le" in arg for arg in command) else "8"
    device = next((a.split(":", 1)[1] for a in command if a.startswith("vaapi=va:")), None)
    kw = {"vaapi_device": device} if device else {}
    assert command == hardware_test_argv("ffmpeg", encoder, bit_depth, **kw)


async def test_run_ok(fake_tools: ft.FakeTools, fake_ffmpeg: ToolInfo) -> None:
    outcome = await run_hardware_test(fake_tools.ffmpeg, ENCODERS["hevc_amf"])
    assert outcome.ok
    assert outcome.failure is None
    assert outcome.argv[-5:] == ("-c:v", "hevc_amf", "-f", "null", "-")
    assert fake_tools.calls() == [outcome.argv[1:]]


async def test_run_known_failure(fake_tools: ft.FakeTools) -> None:
    fake_tools.set_scenario(ft.Scenario([detect_rule("detect_h264_vaapi_no_driver")]))
    outcome = await run_hardware_test(fake_tools.ffmpeg, ENCODERS["h264_vaapi"])
    assert not outcome.ok
    assert outcome.failure is not None
    assert outcome.failure.state is EncoderState.UNAVAILABLE
    assert outcome.failure.reason == (
        "VAAPI driver failed to start on /dev/dri/renderD128 (unknown libva error)"
    )


async def test_run_timeout_kills_the_test(fake_tools: ft.FakeTools) -> None:
    fake_tools.set_scenario(ft.Scenario([ft.Rule(argv_has=["-c:v"], actions=[ft.hang()])]))
    outcome = await run_hardware_test(fake_tools.ffmpeg, ENCODERS["hevc_nvenc"], timeout=0.5)
    assert outcome.failure is not None
    assert outcome.failure.state is EncoderState.ERROR
    assert outcome.failure.reason == "The test encode did not finish within 0.5 s"
    assert fake_tools.kill_leftovers() == []  # the runner killed it


async def test_run_filter_test(fake_tools: ft.FakeTools) -> None:
    ok = await run_filter_test(fake_tools.ffmpeg, "libplacebo")
    assert ok.ok
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
    failed = await run_filter_test(fake_tools.ffmpeg, "libplacebo")
    assert failed.failure is not None
    assert failed.failure.state is EncoderState.UNAVAILABLE
    assert failed.failure.reason == "No working Vulkan driver (VK_ERROR_INCOMPATIBLE_DRIVER)"
    assert failed.failure.detail == (
        "[libplacebo] Failed creating instance: VK_ERROR_INCOMPATIBLE_DRIVER"
    )


async def test_run_missing_binary() -> None:
    outcome = await run_hardware_test("/nonexistent/ffmpeg", ENCODERS["hevc_amf"])
    assert outcome.failure is not None
    assert outcome.failure.state is EncoderState.ERROR
    assert outcome.failure.reason.startswith("FFmpeg could not be started: ")


#: FFmpeg's warning when an encoder does not take the ``-pix_fmt`` it is given; it picks another
#: format and exits 0.
AUTO_SELECTED = (
    "Incompatible pixel format 'p010le' for codec 'hevc_amf', auto-selecting format '{}'\n"
)


@pytest.mark.parametrize("picked", ["nv12", "yuv420p10le"])
async def test_run_10bit_with_another_pixel_format(fake_tools: ft.FakeTools, picked: str) -> None:
    """Exit code 0 is not enough for the 10-bit test: FFmpeg may replace the pixel format."""
    fake_tools.set_scenario(
        ft.Scenario(
            [
                ft.Rule(
                    argv_has=["-c:v", "hevc_amf"], actions=[ft.stderr(AUTO_SELECTED.format(picked))]
                )
            ]
        )
    )
    ten = await run_hardware_test(fake_tools.ffmpeg, ENCODERS["hevc_amf"], "10")
    assert not ten.ok
    assert ten.failure == Failure(
        EncoderState.UNAVAILABLE,
        f"hevc_amf does not take p010le in this FFmpeg build (it got {picked})",
        detail=AUTO_SELECTED.format(picked).strip(),
    )
    # the 8-bit test asks for nv12: a warning about another format does not matter there
    eight = await run_hardware_test(fake_tools.ffmpeg, ENCODERS["hevc_amf"], "8")
    assert eight.ok
