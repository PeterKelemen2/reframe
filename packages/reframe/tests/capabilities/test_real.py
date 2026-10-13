"""Encoder detection with the real FFmpeg of this machine or CI job.

``needs_ffmpeg`` tests run in CI (no GPU there: hardware tests off). ``needs_gpu`` tests run the
hardware test encodes for real; they never run in CI and check what this machine must give,
from its PCI ids and drivers, so they also pass on another GPU machine.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import time
from pathlib import Path

import pytest

from reframe.capabilities import DetectionOptions, detect_capabilities
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
    assert snap.has_filter("zscale") is not None
    for hardware in HARDWARE:
        status = snap.status(hardware.id)
        assert status.state in (EncoderState.UNKNOWN, EncoderState.UNAVAILABLE), status
        if status.state is EncoderState.UNKNOWN:
            assert status.in_build is True
            assert status.private_options


# --------------------------------------------------------------------------- real GPUs

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
async def test_vaapi_and_amf_on_an_amd_gpu(hardware_snapshot: CapabilitySnapshot) -> None:
    if "0x1002" not in pci_vendors() or not exists("/dev/dri/renderD128"):
        pytest.skip("no AMD GPU at /dev/dri/renderD128")
    for encoder in ("h264_vaapi", "hevc_vaapi"):
        assert hardware_snapshot.status(encoder).state is EncoderState.AVAILABLE, encoder
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
