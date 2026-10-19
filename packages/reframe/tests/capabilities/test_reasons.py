"""Reason mapping. The stderr texts are real captures (``fake_data/detect_*`` and ``hw_*``, from the
pinned build); errors that cannot be provoked there use the exact strings of that build
(``library_strings.json``, asserted below).
"""

from __future__ import annotations

import pytest

from reframe.capabilities import TestContext, explain_failure
from reframe.capabilities.reasons import informative_line
from reframe.models import EncoderState
from reframe_testing import fake_tools as ft

UNAVAILABLE = EncoderState.UNAVAILABLE
ERROR = EncoderState.ERROR


def stderr(name: str) -> str:
    return (ft.DATA_DIR / f"{name}.stderr.txt").read_text(encoding="utf-8")


def ctx(encoder: str, device: str | None = None) -> TestContext:
    family = {"nvenc": "nvenc", "qsv": "qsv", "amf": "amf", "vaapi": "vaapi"}
    fam = next((f for key, f in family.items() if encoder.endswith(key)), "software")
    label = {"h264": "H.264", "hevc": "H.265", "av1": "AV1"}[encoder.split("_")[0]]
    if fam == "vaapi" and device is None:
        device = "/dev/dri/renderD128"
    return TestContext(encoder=encoder, family=fam, codec_label=label, device=device)


@pytest.mark.parametrize(
    ("capture", "encoder", "device", "state", "reason", "detail"),
    [
        (
            "detect_hevc_nvenc_no_driver",
            "hevc_nvenc",
            None,
            UNAVAILABLE,
            "NVIDIA driver not found",
            "[hevc_nvenc] Cannot load libcuda.so.1",
        ),
        (
            "hw_h264_nvenc_no_driver.v_error",
            "h264_nvenc",
            None,
            UNAVAILABLE,
            "NVIDIA driver not found",
            "[h264_nvenc] Cannot load libcuda.so.1",
        ),
        (
            "detect_hevc_qsv_no_device",
            "hevc_qsv",
            None,
            UNAVAILABLE,
            "No Intel QSV device (needs an Intel GPU with its media driver)",
            "Failed to set value 'qsv=hw' for option 'init_hw_device': "
            "Generic error in an external library",
        ),
        (
            # QSV without the setup arguments: the encoder opens the MFX session itself
            "hw_hevc_qsv_no_device",
            "hevc_qsv",
            None,
            UNAVAILABLE,
            "No Intel QSV device (needs an Intel GPU with its media driver)",
            "[hevc_qsv] Error creating a MFX session: -9.",
        ),
        (
            "detect_h264_vaapi_bad_device",
            "h264_vaapi",
            "/dev/dri/renderD999",
            UNAVAILABLE,
            "No VAAPI device (/dev/dri/renderD999)",
            "[VAAPI] No VA display found for device /dev/dri/renderD999.",
        ),
        (
            "detect_h264_vaapi_no_driver",
            "h264_vaapi",
            None,
            UNAVAILABLE,
            "VAAPI driver failed to start on /dev/dri/renderD128 (unknown libva error)",
            "[VAAPI] Failed to initialise VAAPI connection: -1 (unknown libva error).",
        ),
        (
            "hw_h264_vaapi_not_drm",
            "h264_vaapi",
            "/dev/null",
            UNAVAILABLE,
            "No VAAPI device (/dev/null)",
            "Failed to set value '/dev/null' for option 'vaapi_device': "
            "Generic error in an external library",
        ),
        (
            "detect_hevc_amf_no_runtime",
            "hevc_amf",
            None,
            UNAVAILABLE,
            "AMD AMF runtime not found (libamfrt64.so.1)",
            "[AMF] DLL libamfrt64.so.1 failed to open",
        ),
        (
            "detect_h264_amf_10bit",
            "h264_amf",
            None,
            UNAVAILABLE,
            "10-bit is not supported by this encoder",
            "[h264_amf] 10-bit input video is not supported by AMF H264 encoder",
        ),
        (
            # a command-builder mistake (no hwupload): not a known reason, so "error" with the
            # most informative line, never the generic last line
            "hw_h264_vaapi_no_hwupload",
            "h264_vaapi",
            None,
            ERROR,
            "The test encode failed: Impossible to convert between the formats supported by "
            "the filter 'Parsed_null_0' and the filter 'auto_scale_0'",
            "Impossible to convert between the formats supported by the filter 'Parsed_null_0' "
            "and the filter 'auto_scale_0'",
        ),
    ],
)
def test_real_failures(
    capture: str,
    encoder: str,
    device: str | None,
    state: EncoderState,
    reason: str,
    detail: str,
) -> None:
    failure = explain_failure(
        stderr(capture), ctx(encoder, device), returncode=ft.captures()[capture].exit_code
    )
    assert (failure.state, failure.reason, failure.detail) == (state, reason, detail)


def test_the_last_line_is_never_the_reason() -> None:
    text = stderr("detect_hevc_nvenc_no_driver")
    assert text.strip().splitlines()[-1] == "Conversion failed!"
    assert "Conversion failed" not in explain_failure(text, ctx("hevc_nvenc")).reason


NVENC_API = "Driver does not support the required nvenc API version. Required: 13.0 Found: 12.1"


def tagged(encoder: str, *lines: str) -> str:
    """Stderr as FFmpeg prints an encoder's errors, plus the generic fftools tail."""
    body = "".join(f"[{encoder} @ 0x5600deadbeef] {line}\n" for line in lines)
    return (
        body + f"[vost#0:0/{encoder} @ 0x56] [enc:{encoder} @ 0x57] Error while opening encoder - "
        "maybe incorrect parameters such as bit_rate, rate, width or height.\nConversion failed!\n"
    )


@pytest.mark.parametrize(
    ("encoder", "text", "reason"),
    [
        (
            "hevc_nvenc",
            tagged(
                "hevc_nvenc",
                NVENC_API,
                "The minimum required Nvidia driver for nvenc is 570.0 or newer",
            ),
            "NVIDIA driver too old: NVENC needs driver 570.0 or newer",
        ),
        (
            "hevc_nvenc",
            tagged(
                "hevc_nvenc",
                NVENC_API,
            ),
            "NVIDIA driver too old (NVENC API 12.1, needs 13.0)",
        ),
        ("h264_nvenc", tagged("h264_nvenc", "Cannot load nvcuda.dll"), "NVIDIA driver not found"),
        (
            "h264_nvenc",
            tagged("h264_nvenc", "No CUDA capable devices found"),
            "No NVIDIA GPU found",
        ),
        (
            "av1_nvenc",
            tagged("av1_nvenc", "No capable devices found"),
            "No NVIDIA GPU that can encode AV1",
        ),
        (
            "av1_nvenc",
            tagged("av1_nvenc", "Codec not supported"),
            "This NVIDIA GPU cannot encode AV1",
        ),
        (
            "hevc_nvenc",
            tagged(
                "hevc_nvenc",
                "OpenEncodeSessionEx failed: incompatible client key (21): (no details)",
            ),
            "NVENC could not open an encoding session (incompatible client key (21): (no details))",
        ),
        (
            "hevc_nvenc",
            tagged("hevc_nvenc", "10 bit encode not supported"),
            "10-bit is not supported by this GPU",
        ),
        (
            "hevc_qsv",
            tagged("hevc_qsv", "Error initializing an MFX session"),
            "No Intel QSV device (needs an Intel GPU with its media driver)",
        ),
        (
            "h264_vaapi",
            "[VAAPI @ 0x55] No VA display found for any default device.\n",
            "No VAAPI device (/dev/dri/renderD128)",
        ),
        (
            "hevc_amf",
            tagged("hevc_amf", "Failed to create  hardware device context (AMF) : Generic error"),
            "AMD AMF could not start (Generic error)",
        ),
        (
            "hevc_amf",
            tagged(
                "hevc_amf",
                "10-bit encoder is not supported by AMD GPU drivers versions lower than 23.30.",
            ),
            "AMD driver too old for 10-bit (needs 23.30 or newer)",
        ),
    ],
)
def test_texts_confirmed_in_the_build(encoder: str, text: str, reason: str) -> None:
    failure = explain_failure(text, ctx(encoder), returncode=1)
    assert failure.state is UNAVAILABLE
    assert failure.reason == reason
    assert failure.detail is not None
    assert "0x" not in failure.detail


def test_the_mapped_texts_are_in_the_pinned_build() -> None:
    found = {text: {e["file"] for e in hits} for text, hits in ft.library_strings().items()}
    codec = "lib/libavcodec.so.63.1.102"
    util = "lib/libavutil.so.61.1.102"
    assert codec in found["10 bit encode not supported"]
    assert codec in found["Codec not supported"]
    assert codec in found["10-bit input video is not supported by AMF"]
    assert codec in found["10-bit encoder is not supported by AMD GPU drivers"]
    assert util in found["DLL %s failed to open"]
    assert util in found["libamfrt64.so.1"]
    assert "bin/ffmpeg" in found["Failed to set value '%s' for option '%s': %s"]


def test_nvenc_only_texts_need_an_nvenc_encoder() -> None:
    failure = explain_failure(tagged("libx265", "Codec not supported"), ctx("hevc_amf"))
    assert failure.state is ERROR


def test_unknown_failure_keeps_the_encoders_own_line() -> None:
    text = tagged("hevc_amf", "Something new went wrong (code 42)")
    failure = explain_failure(text, ctx("hevc_amf"), returncode=1)
    assert failure.state is ERROR
    assert failure.reason == "The test encode failed: Something new went wrong (code 42)"
    assert failure.detail == "[hevc_amf] Something new went wrong (code 42)"


def test_unknown_failure_prefers_a_device_line() -> None:
    text = "[AVHWDeviceContext @ 0x1] Cannot open the X display.\nConversion failed!\n"
    failure = explain_failure(text, ctx("h264_vaapi"))
    assert failure.detail == "[AVHWDeviceContext] Cannot open the X display."


def test_crash_without_a_known_text() -> None:
    failure = explain_failure("", ctx("hevc_amf"), returncode=-11)
    assert failure.state is ERROR
    assert failure.reason == "FFmpeg crashed during the test encode (signal 11)"
    windows = explain_failure("Conversion failed!\n", ctx("hevc_amf"), returncode=0xC0000005)
    assert windows.reason == "FFmpeg crashed during the test encode (exit code 0xC0000005)"


def test_no_message_at_all() -> None:
    failure = explain_failure("", ctx("hevc_amf"), returncode=1)
    assert (failure.state, failure.reason, failure.detail) == (
        ERROR,
        "The test encode failed with no message (exit code 1)",
        None,
    )


def test_informative_line_order() -> None:
    assert informative_line("", "x") is None
    assert informative_line("  indented only\n", "x") == "indented only"
    assert informative_line("Conversion failed!\n", "x") == "Conversion failed!"
    text = "Input #0, lavfi\nDevice creation failed: -22.\nError parsing global options: x\n"
    assert informative_line(text, "x") == "Device creation failed: -22."


FILTER = TestContext(encoder="libplacebo", family="filter")


def test_libplacebo_without_vulkan_real() -> None:
    failure = explain_failure(stderr("detect_libplacebo_no_vulkan"), FILTER, returncode=187)
    assert (failure.state, failure.reason, failure.detail) == (
        UNAVAILABLE,
        "No working Vulkan driver (VK_ERROR_INCOMPATIBLE_DRIVER)",
        "[libplacebo] Failed creating instance: VK_ERROR_INCOMPATIBLE_DRIVER",
    )


@pytest.mark.parametrize(
    ("line", "reason"),
    [
        ("Found no suitable device, giving up.", "No Vulkan device that libplacebo can use"),
        (
            "Vulkan device does not support all required features!",
            "The Vulkan device lacks features that libplacebo needs",
        ),
        ("Failed creating logical device!", "The Vulkan device could not be opened"),
    ],
)
def test_vulkan_texts_confirmed_in_the_build(line: str, reason: str) -> None:
    text = f"[libplacebo @ 0x55] {line}\n[libplacebo @ 0x55] Failed initializing vulkan device\n"
    failure = explain_failure(text, FILTER, returncode=187)
    assert (failure.state, failure.reason) == (UNAVAILABLE, reason)


def test_the_vulkan_texts_are_in_the_pinned_build() -> None:
    found = {text: {e["file"] for e in hits} for text, hits in ft.library_strings().items()}
    for text in (
        "Failed creating instance: %s",
        "Found no suitable device, giving up.",
        "Vulkan device does not support all required features",
        "Failed creating logical device",
        "Failed initializing vulkan device",
    ):
        assert "lib/libavfilter.so.12.1.102" in found[text], text


def test_unknown_filter_failure() -> None:
    text = "[libplacebo @ 0x55] Something else\n[AVFilterGraph @ 0x56] Error initializing filters\n"
    failure = explain_failure(text, FILTER, returncode=1)
    assert (failure.state, failure.reason, failure.detail) == (
        ERROR,
        "The libplacebo test failed: Something else",
        "[libplacebo] Something else",
    )
    crash = explain_failure("", FILTER, returncode=-11)
    assert crash.reason == "FFmpeg crashed during the libplacebo test (signal 11)"
