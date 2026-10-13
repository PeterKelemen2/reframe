"""The hardware test encode command (pure) and one run with the fake ffmpeg."""

from __future__ import annotations

import pytest

from reframe.capabilities import hardware_test_argv, run_hardware_test
from reframe.capabilities.hwtest import BitDepth, DefinitionError, resolve_placeholders
from reframe.definitions import HardwareSetup, VideoEncoderDef, load_definitions
from reframe.models import EncoderState, ToolInfo
from reframe_testing import fake_tools as ft
from reframe_testing.capabilities import c4_rule

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


#: The ``c4_*`` captures made with :func:`hardware_test_argv` (``c4_h264_amf_10bit`` is not:
#: h264_amf has no 10-bit pixel format in the definitions).
C4_CAPTURES = sorted(n for n in ft.captures() if n.startswith("c4_") and n != "c4_h264_amf_10bit")


def test_there_are_c4_captures() -> None:
    assert len(C4_CAPTURES) == 9


@pytest.mark.parametrize("name", C4_CAPTURES)
def test_the_c4_captures_ran_the_current_command(name: str) -> None:
    """If a hardware setup in the definitions changes, capture again
    (``capture_fake_data.py --only c4_…``)."""
    capture = ft.captures()[name]
    command = list(capture.command)
    encoder = ENCODERS[command[command.index("-c:v") + 1]]
    bit_depth: BitDepth = "10" if any("p010le" in arg for arg in command) else "8"
    device = next((a.split(":", 1)[1] for a in command if a.startswith("vaapi=va:")), None)
    kw = {"vaapi_device": device} if device else {}
    assert command == hardware_test_argv("ffmpeg", encoder, bit_depth, **kw)


def test_placeholders() -> None:
    assert resolve_placeholders("vaapi=va:{vaapi_device}", {"vaapi_device": "/x"}) == "vaapi=va:/x"
    with pytest.raises(DefinitionError, match=r"\{qsv_device\}"):
        resolve_placeholders("qsv={qsv_device}", {"vaapi_device": "/x"})


def broken(**changes: object) -> VideoEncoderDef:
    return ENCODERS["hevc_vaapi"].model_copy(update=changes)


def test_definition_errors() -> None:
    with pytest.raises(DefinitionError, match="no pixel format for 10-bit"):
        hardware_test_argv("ffmpeg", broken(pix_fmts={"8": "nv12"}), "10")
    setup = HardwareSetup(init_args=["-init_hw_device", "x={unknown}"])
    with pytest.raises(DefinitionError, match="unknown placeholder"):
        hardware_test_argv("ffmpeg", broken(hardware_setup=setup))


async def test_run_ok(fake_tools: ft.FakeTools, fake_ffmpeg: ToolInfo) -> None:
    outcome = await run_hardware_test(fake_tools.ffmpeg, ENCODERS["hevc_amf"])
    assert outcome.ok
    assert outcome.failure is None
    assert outcome.argv[-5:] == ("-c:v", "hevc_amf", "-f", "null", "-")
    assert fake_tools.calls() == [outcome.argv[1:]]


async def test_run_known_failure(fake_tools: ft.FakeTools) -> None:
    fake_tools.set_scenario(ft.Scenario([c4_rule("c4_h264_vaapi_no_driver")]))
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


async def test_run_definition_error_is_data(fake_tools: ft.FakeTools) -> None:
    outcome = await run_hardware_test(fake_tools.ffmpeg, broken(pix_fmts={"8": "nv12"}), "10")
    assert outcome.failure is not None
    assert outcome.failure.state is EncoderState.ERROR
    assert outcome.failure.reason.startswith("The encoder definition is broken: ")
    assert fake_tools.calls() == []


async def test_run_missing_binary(tmp_path: object) -> None:
    outcome = await run_hardware_test("/nonexistent/ffmpeg", ENCODERS["hevc_amf"])
    assert outcome.failure is not None
    assert outcome.failure.state is EncoderState.ERROR
    assert outcome.failure.reason.startswith("FFmpeg could not be started: ")
