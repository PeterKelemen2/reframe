"""Encoder detection with the real FFmpeg. CI runs the ``needs_ffmpeg`` tests, which test no GPU
encoder; ``needs_gpu`` tests never run there and expect what this machine's PCI ids and drivers
give.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from reframe.capabilities import (
    DetectionOptions,
    detect_capabilities,
    render_nodes,
    run_filter_test,
    run_hardware_test,
)
from reframe.definitions import load_definitions
from reframe.models import CapabilitySnapshot, EncoderState, ToolInfo, ToolStatus
from reframe.service import Reframe
from reframe.tools import discover_tools

pytestmark = [pytest.mark.needs_ffmpeg, pytest.mark.anyio]

DEFS = load_definitions()
HARDWARE = [enc for enc in DEFS.video_encoders.values() if enc.hardware]
FINAL = {EncoderState.AVAILABLE, EncoderState.UNAVAILABLE, EncoderState.ERROR}


async def real_ffmpeg() -> ToolInfo:
    tools = await discover_tools()
    assert tools.ffmpeg.status is ToolStatus.FOUND, tools.ffmpeg.reason
    return tools.ffmpeg


def listed_filter(ffmpeg: ToolInfo, name: str) -> bool:
    """Whether ``ffmpeg -filters`` lists ``name``, read without the parser under test (not every
    build has every filter)."""
    assert ffmpeg.path is not None
    out = subprocess.run(
        [str(ffmpeg.path), "-hide_banner", "-filters"],
        capture_output=True, text=True, check=True, timeout=60, env={**os.environ, **ffmpeg.env},
    )  # fmt: skip
    return any(line.split()[1:2] == [name] for line in out.stdout.splitlines())


async def test_real_detection_without_hardware_tests() -> None:
    ffmpeg = await real_ffmpeg()
    snap = await detect_capabilities(ffmpeg, DEFS, DetectionOptions(hardware_tests=False))
    for encoder in ("libx264", "libx265", "libsvtav1", "libvpx-vp9", "aac", "ac3", "libopus"):
        assert snap.status(encoder).state is EncoderState.AVAILABLE, encoder
    x265 = snap.status("libx265")
    assert "x265-params" in x265.private_options
    assert x265.supports_10bit is True
    assert snap.status("libsvtav1").presets  # the integer range of -preset
    assert snap.has_filter("scale") is True
    assert snap.has_filter("zscale") is listed_filter(ffmpeg, "zscale")
    # hardware tests off: libplacebo is not run, so it is not known to work
    if snap.has_filter("libplacebo"):
        assert snap.usable_filter("libplacebo") is None
        assert snap.untested_filters == ["libplacebo"]
    for hardware in HARDWARE:
        status = snap.status(hardware.id)
        assert status.state in (EncoderState.UNKNOWN, EncoderState.UNAVAILABLE), status
        if status.state is EncoderState.UNKNOWN:
            assert status.in_build is True
            assert status.private_options


async def test_a_replaced_pixel_format_fails_the_10bit_test() -> None:
    """FFmpeg replaces a ``-pix_fmt`` that the encoder does not take ("Incompatible
    pixel format 'p010le' for codec 'libx264', auto-selecting format 'yuv420p10le'") and exits
    0. libx264 does not take p010le: the 10-bit test of a definition that asks for it fails."""
    ffmpeg = await real_ffmpeg()
    assert ffmpeg.path is not None
    x264 = DEFS.video_encoders["libx264"].model_copy(
        update={"pix_fmts": {"8": "yuv420p", "10": "p010le"}, "hardware_setup": None}
    )
    ten = await run_hardware_test(ffmpeg.path, x264, "10")
    assert ten.failure is not None, "FFmpeg did not replace p010le"
    assert ten.failure.reason == (
        "libx264 does not take p010le in this FFmpeg build (it got yuv420p10le)"
    )
    assert (await run_hardware_test(ffmpeg.path, x264, "8")).ok


DRM = Path("/sys/class/drm")


def pci_vendors() -> set[str]:
    vendors = set()
    for vendor in DRM.glob("*/device/vendor"):
        with contextlib.suppress(OSError):
            vendors.add(vendor.read_text(encoding="utf-8").strip())
    return vendors


def exists(path: str) -> bool:
    return Path(path).exists()


@pytest.fixture(scope="module")
async def hardware_snapshot() -> CapabilitySnapshot:
    ffmpeg = await real_ffmpeg()
    started = time.monotonic()
    snap = await detect_capabilities(ffmpeg, DEFS)
    took = time.monotonic() - started
    assert took < 30, f"detection took {took:.1f} s"
    return snap


@pytest.fixture(scope="module")
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.needs_gpu
async def test_every_hardware_encoder_gets_a_final_state(
    hardware_snapshot: CapabilitySnapshot,
) -> None:
    for encoder in HARDWARE:
        status = hardware_snapshot.status(encoder.id)
        assert status.state in FINAL, status
        if status.state is not EncoderState.AVAILABLE:
            assert status.reason, status
            assert "Conversion failed" not in status.reason
    assert any(hardware_snapshot.status(e.id).state is EncoderState.AVAILABLE for e in HARDWARE), (
        "a GPU machine has at least one working hardware encoder"
    )


@pytest.mark.needs_gpu
@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux driver paths")
async def test_nvenc_without_the_nvidia_driver(hardware_snapshot: CapabilitySnapshot) -> None:
    if exists("/proc/driver/nvidia/version"):
        pytest.skip("the NVIDIA driver is loaded")
    for encoder in ("h264_nvenc", "hevc_nvenc", "av1_nvenc"):
        status = hardware_snapshot.status(encoder)
        assert (status.state, status.reason) == (
            EncoderState.UNAVAILABLE,
            "NVIDIA driver not found",
        ), status


@pytest.mark.needs_gpu
@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux driver paths")
async def test_qsv_without_an_intel_gpu(hardware_snapshot: CapabilitySnapshot) -> None:
    if "0x8086" in pci_vendors():
        pytest.skip("this machine has an Intel GPU")
    for encoder in ("h264_qsv", "hevc_qsv", "av1_qsv"):
        status = hardware_snapshot.status(encoder)
        assert status.state is EncoderState.UNAVAILABLE, status
        assert status.reason is not None
        assert status.reason.startswith("No Intel QSV device"), status


@pytest.mark.needs_gpu
@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="VAAPI is Linux only")
async def test_qsv_and_vaapi_on_an_intel_gpu(hardware_snapshot: CapabilitySnapshot) -> None:
    """H.264 and H.265 work on every Intel GPU with a media driver; AV1 only on newer ones,
    so its answer must be definite, never a failed check."""
    if "0x8086" not in pci_vendors():
        pytest.skip("no Intel GPU")
    for encoder in ("h264_qsv", "hevc_qsv", "h264_vaapi", "hevc_vaapi"):
        assert hardware_snapshot.status(encoder).state is EncoderState.AVAILABLE, encoder
    for encoder in ("av1_qsv", "av1_vaapi"):
        status = hardware_snapshot.status(encoder)
        assert status.state in (EncoderState.AVAILABLE, EncoderState.UNAVAILABLE), status


@pytest.mark.needs_gpu
@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="VAAPI is Linux only")
async def test_vaapi_and_amf_on_an_amd_gpu(hardware_snapshot: CapabilitySnapshot) -> None:
    if "0x1002" not in pci_vendors() or not exists("/dev/dri/renderD128"):
        pytest.skip("no AMD GPU at /dev/dri/renderD128")
    nodes = render_nodes()
    for encoder in ("h264_vaapi", "hevc_vaapi"):
        status = hardware_snapshot.status(encoder)
        assert status.state is EncoderState.AVAILABLE, encoder
        assert status.device in nodes, status  # the node it works on
    assert hardware_snapshot.status("hevc_vaapi").supports_10bit is True
    assert hardware_snapshot.status("h264_vaapi").supports_10bit is False  # no 10-bit format
    amf = hardware_snapshot.status("hevc_amf")
    if amf.state is not EncoderState.AVAILABLE:
        assert amf.reason is not None
        assert amf.reason.startswith("AMD AMF"), amf
    else:
        assert amf.supports_10bit is True
        assert hardware_snapshot.status("h264_amf").supports_10bit is False


@pytest.mark.needs_gpu
async def test_the_facade_caches_the_real_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("REFRAME_CACHE_DIR", str(tmp_path / "cache"))
    async with await Reframe.create() as app:
        first = await app.capabilities.wait()
    states = {key: status.state for key, status in first.encoders.items()}
    async with await Reframe.create() as app:
        deadline = time.monotonic() + 10
        while not app.capabilities.snapshot.from_cache:
            if time.monotonic() > deadline:
                break
            await asyncio.sleep(0.005)
        cached = app.capabilities.snapshot
        assert cached.from_cache, "the second start shows the cached result first"
        assert {key: status.state for key, status in cached.encoders.items()} == states
        second = await app.capabilities.wait()
    assert not second.from_cache
    assert {key: status.state for key, status in second.encoders.items()} == states


@pytest.mark.needs_gpu
async def test_libplacebo_run_test(hardware_snapshot: CapabilitySnapshot) -> None:
    """The real libplacebo test gives a definite answer; with a Vulkan driver and a GPU
    (RADV) it works."""
    if not hardware_snapshot.has_filter("libplacebo"):
        pytest.skip("this FFmpeg has no libplacebo")
    usable = hardware_snapshot.usable_filter("libplacebo")
    assert usable is not None
    if not usable:
        assert hardware_snapshot.filter_failures["libplacebo"]
    elif "0x1002" in pci_vendors():
        assert usable is True


@pytest.mark.needs_gpu
async def test_libplacebo_without_a_vulkan_driver() -> None:
    """``VK_ICD_FILENAMES`` pointing to nothing: the real failure and its reason."""
    ffmpeg = await real_ffmpeg()
    assert ffmpeg.path is not None
    outcome = await run_filter_test(
        ffmpeg.path,
        "libplacebo",
        extra_env={**ffmpeg.env, "VK_ICD_FILENAMES": "/nonexistent/icd.json"},
    )
    assert outcome.failure is not None
    assert outcome.failure.state is EncoderState.UNAVAILABLE
    assert outcome.failure.reason == "No working Vulkan driver (VK_ERROR_INCOMPATIBLE_DRIVER)"
