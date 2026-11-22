"""Reason mapping. The stderr texts are real captures (``fake_data/detect_*`` and ``hw_*``, from the
pinned build); errors that cannot be provoked there use the exact strings of that build
(``library_strings.json``, asserted below).
"""

from __future__ import annotations

import pytest

from reframe.capabilities import TestContext, explain_failure
from reframe.capabilities.reasons import NVENC_BUSY, informative_line
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
            "No Intel QSV device or runtime "
            "(needs an Intel GPU, its media driver and its QSV runtime)",
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
            # the GeForce session limit: busy, so "error" (not checked), never "no GPU"
            "detect_hevc_nvenc_session_limit",
            "hevc_nvenc",
            None,
            ERROR,
            NVENC_BUSY,
            "[hevc_nvenc] OpenEncodeSessionEx failed: incompatible client key (21): (no details)",
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
    assert failure.busy is (reason == NVENC_BUSY)


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
            # another session error: the GPU is skipped, so "No capable devices found" follows
            "hevc_nvenc",
            tagged(
                "hevc_nvenc",
                "OpenEncodeSessionEx failed: out of memory (10): (no details)",
                "No capable devices found",
            ),
            "NVENC could not open an encoding session (out of memory (10): (no details))",
        ),
        (
            "hevc_nvenc",
            tagged("hevc_nvenc", "10 bit encode not supported"),
            "10-bit is not supported by this GPU",
        ),
        (
            # what the 10-bit test of h264_nvenc prints on a GeForce 10 series GPU
            "h264_nvenc",
            tagged("h264_nvenc", "10 bit encode not supported", "No capable devices found"),
            "10-bit is not supported by this GPU",
        ),
        (
            "hevc_qsv",
            tagged("hevc_qsv", "Error initializing an MFX session"),
            "No Intel QSV device or runtime "
            "(needs an Intel GPU, its media driver and its QSV runtime)",
        ),
        (
            "av1_qsv",
            tagged("av1_qsv", "This version of runtime doesn't support AV1 encoding"),
            "This Intel GPU cannot encode AV1",
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
    assert codec in found["incompatible client key"]
    assert codec in found["10-bit input video is not supported by AMF"]
    assert codec in found["10-bit encoder is not supported by AMD GPU drivers"]
    assert codec in found["This version of runtime doesn't support AV1 encoding"]
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
    # FFmpeg's own -22 (EINVAL) as Windows reports it: a failure with its line, not a crash.
    averror = explain_failure("Conversion failed!\n", ctx("hevc_amf"), returncode=0xFFFFFFEA)
    assert averror.reason == "The test encode failed: Conversion failed!"


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


# Real captures of the pinned Linux build: Ubuntu 24.04 in a container without libvulkan1 (the
# Windows VM without vulkan-1.dll prints the same libplacebo lines), and with its libva 2.20.
NO_VULKAN_LOADER = """\
Input #0, lavfi, from 'color=size=640x360':
  Stream #0:0: Video: wrapped_avframe, yuv420p, 640x360 [SAR 1:1 DAR 16:9], 25 fps, 25 tbr, 25 tbn
[libplacebo @ 0x561efe38ff00] Instance API version 1.0.0 is lower than the minimum required \
version of 1.2.0, cannot proceed!
[libplacebo @ 0x561efe38ff00] Failed initializing vulkan instance
[libplacebo @ 0x561efe38ff00] Failed initializing vulkan device
[Parsed_libplacebo_0 @ 0x561efe38fe00] Failed creating Vulkan device!
[AVFilterGraph @ 0x561efe38fcc0] Error initializing filters
Error opening output file -.
Error opening output files: Generic error in an external library
"""
OLD_LIBVA = """\
amdgpu: os_same_file_description couldn't determine if two DRM fds reference the same file \
description.
If they do, bad things may happen!
Input #0, lavfi, from 'color=size=640x360':
  Stream #0:0: Video: wrapped_avframe, yuv420p, 640x360 [SAR 1:1 DAR 16:9], 25 fps, 25 tbr, 25 tbn
Stream mapping:
  Stream #0:0 -> #0:0 (wrapped_avframe (native) -> h264 (h264_vaapi))
implib-gen: libva.so.2: failed to resolve symbol 'vaMapBuffer2' via dlsym: \
/lib/x86_64-linux-gnu/libva.so.2: undefined symbol: vaMapBuffer2
ffmpeg: libva.so.2.init.c:290: _libva_so_2_tramp_resolve: Assertion `0 && "Assertion in \
generated code"' failed.
"""


def test_libplacebo_without_a_vulkan_loader_real() -> None:
    failure = explain_failure(NO_VULKAN_LOADER, FILTER, returncode=187)
    assert (failure.state, failure.reason) == (
        UNAVAILABLE,
        "No Vulkan runtime, or one too old for libplacebo (Vulkan 1.0.0, needs 1.2.0)",
    )


def test_libplacebo_with_a_vulkan_driver_too_old() -> None:
    text = (
        "[libplacebo @ 0x55] Device API version 1.1.0 is lower than the minimum required "
        "version of 1.2.0, cannot proceed!\n"
        "[libplacebo @ 0x55] Failed initializing vulkan device\n"
    )
    failure = explain_failure(text, FILTER, returncode=187)
    assert (failure.state, failure.reason) == (
        UNAVAILABLE,
        "The Vulkan driver is too old for libplacebo (Vulkan 1.1.0, needs 1.2.0)",
    )


def test_a_system_libva_too_old_for_the_build_real() -> None:
    """The stub aborts (SIGABRT): without the rule this reads "FFmpeg crashed"."""
    failure = explain_failure(OLD_LIBVA, ctx("h264_vaapi"), returncode=-6)
    assert (failure.state, failure.reason) == (
        UNAVAILABLE,
        "The system's libva.so.2 is too old for this FFmpeg build (it has no vaMapBuffer2)",
    )


def test_a_missing_system_library_real() -> None:
    """Ubuntu 22.04 without libva: the h264_qsv test encode aborts in the stub."""
    text = (
        "implib-gen: libva-drm.so.2: failed to load library 'libva-drm.so.2' via dlopen: "
        "libva-drm.so.2: cannot open shared object file: No such file or directory\n"
        'ffmpeg: libva-drm.so.2.init.c:122: load_library: Assertion `0 && "Assertion in '
        "generated code\"' failed.\n"
    )
    failure = explain_failure(text, ctx("h264_qsv"), returncode=-6)
    assert (failure.state, failure.reason) == (
        UNAVAILABLE,
        "The system library libva-drm.so.2 is not installed",
    )


def test_a_vaapi_driver_without_the_codec_real() -> None:
    """Debian 12's Mesa 22.3 on an RX 7600 has no AV1 encoder."""
    text = (
        "[av1_vaapi @ 0x55d862b8cdc0] No usable encoding entrypoint found for profile "
        "VAProfileAV1Profile0 (32).\n"
        "[vost#0:0/av1_vaapi @ 0x55d862bf3d40] [enc:av1_vaapi @ 0x55d862be27c0] Error while "
        "opening encoder - maybe incorrect parameters such as bit_rate, rate, width or height.\n"
        "[vf#0:0 @ 0x55d862d658c0] Error sending frames to consumers: Function not implemented\n"
        "Conversion failed!\n"
    )
    failure = explain_failure(text, ctx("av1_vaapi"), returncode=218)
    assert (failure.state, failure.reason) == (
        UNAVAILABLE,
        "The VAAPI driver has no AV1 encoder",
    )


def test_a_vaapi_driver_without_any_profile_of_the_codec_real() -> None:
    """Fedora 45's Mesa 26.2.6 has no H.264 or H.265 encoder."""
    text = (
        "[h264_vaapi @ 0x555a051dfcc0] No usable encoding profile found.\n"
        "[vost#0:0/h264_vaapi @ 0x555a051df880] [enc:h264_vaapi @ 0x555a051dfc40] Error while "
        "opening encoder - maybe incorrect parameters such as bit_rate, rate, width or height.\n"
        "Conversion failed!\n"
    )
    failure = explain_failure(text, ctx("h264_vaapi"), returncode=218)
    assert (failure.state, failure.reason) == (UNAVAILABLE, "The VAAPI driver has no H.264 encoder")


def test_a_missing_library_of_the_bundled_libva_real() -> None:
    """Ubuntu 24.04 without libdrm2: the bundled libva-drm.so.2 loads, its libdrm does not."""
    text = (
        "implib-gen: libva-drm.so.2: failed to load library 'libva-drm.so.2' via dlopen: "
        "libdrm.so.2: cannot open shared object file: No such file or directory\n"
        'ffmpeg: libva-drm.so.2.init.c:122: load_library: Assertion `0 && "Assertion in '
        "generated code\"' failed.\n"
    )
    failure = explain_failure(text, ctx("h264_vaapi"), returncode=-6)
    assert (failure.state, failure.reason) == (
        UNAVAILABLE,
        "The system library libdrm.so.2 is not installed",
    )


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (
            "/lib/x86_64-linux-gnu/libdrm.so.2: version `LIBDRM_2.4.120' not found (required "
            "by /usr/lib/Reframe/tools/ffmpeg/lib/libva-drm.so.2)",
            "The system library libva-drm.so.2 could not be loaded (libdrm.so.2: version "
            "`LIBDRM_2.4.120' not found)",
        ),
        (
            # Real: Fedora 45, the .rpm, a libdrm.so.2 without symbols, LD_BIND_NOW=1.
            "/usr/lib/Reframe/tools/ffmpeg/bin/../lib/libva-drm.so.2: undefined symbol: "
            "drmFreeVersion",
            "The system library libva-drm.so.2 could not be loaded (libva-drm.so.2: undefined "
            "symbol: drmFreeVersion)",
        ),
        (
            "/usr/lib/libva.so.2: undefined symbol: drmGetDevices2",
            "The system library libva-drm.so.2 could not be loaded (libva.so.2: undefined "
            "symbol: drmGetDevices2)",
        ),
    ],
)
def test_a_library_that_is_installed_but_does_not_load(error: str, reason: str) -> None:
    text = (
        "implib-gen: libva-drm.so.2: failed to load library 'libva-drm.so.2' via dlopen: "
        f"{error}\n"
        'ffmpeg: libva-drm.so.2.init.c:122: load_library: Assertion `0 && "Assertion in '
        "generated code\"' failed.\n"
    )
    failure = explain_failure(text, ctx("h264_vaapi"), returncode=-6)
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


# Real: a GeForce GTX 1050 Ti with driver 582.78 and the pinned n9.0.2 build (Windows 10).
NVENC_DRIVER_TOO_OLD = (
    "Driver does not support the required nvenc API version. Required: 13.1 Found: 13.0",
    "The minimum required Nvidia driver for nvenc is 610.00 or newer",
)
MISSING_LIBVA_DRM = (
    "implib-gen: libva-drm.so.2: failed to load library 'libva-drm.so.2' via dlopen: "
    "libva-drm.so.2: cannot open shared object file: No such file or directory\n"
)


@pytest.mark.parametrize("encoder", ["h264_nvenc", "hevc_nvenc", "av1_nvenc"])
def test_an_nvidia_driver_too_old_for_the_build_is_a_build_mismatch_real(encoder: str) -> None:
    failure = explain_failure(tagged(encoder, *NVENC_DRIVER_TOO_OLD), ctx(encoder), returncode=1)
    assert (failure.state, failure.reason, failure.build_mismatch, failure.cause) == (
        UNAVAILABLE,
        "NVIDIA driver too old: NVENC needs driver 610.00 or newer",
        True,
        "driver",
    )
    assert failure.detail == f"[{encoder}] {NVENC_DRIVER_TOO_OLD[0]}"


@pytest.mark.parametrize("line", NVENC_DRIVER_TOO_OLD, ids=["api-version", "driver-requirement"])
def test_either_nvenc_driver_line_alone_is_a_build_mismatch(line: str) -> None:
    failure = explain_failure(tagged("hevc_nvenc", line), ctx("hevc_nvenc"), returncode=1)
    assert failure.state is UNAVAILABLE
    assert failure.reason.startswith("NVIDIA driver too old")
    assert (failure.build_mismatch, failure.cause) == (True, "driver")


@pytest.mark.parametrize("text", [OLD_LIBVA, MISSING_LIBVA_DRM], ids=["too-old", "missing"])
@pytest.mark.parametrize("encoder", ["h264_vaapi", "h264_qsv"])
def test_a_system_library_too_old_or_missing_for_the_build_is_a_build_mismatch(
    text: str, encoder: str
) -> None:
    failure = explain_failure(text, ctx(encoder), returncode=-6)
    assert (failure.state, failure.build_mismatch, failure.cause) == (
        UNAVAILABLE,
        True,
        "system_library",
    )


@pytest.mark.parametrize(
    ("capture", "encoder"),
    [
        ("detect_hevc_nvenc_no_driver", "hevc_nvenc"),  # no NVIDIA driver
        ("hw_hevc_qsv_no_device", "hevc_qsv"),  # no Intel GPU
        ("detect_h264_vaapi_bad_device", "h264_vaapi"),  # no VAAPI device
        ("detect_h264_vaapi_no_driver", "h264_vaapi"),  # no VA driver
        ("detect_hevc_amf_no_runtime", "hevc_amf"),
        ("detect_h264_amf_10bit", "h264_amf"),  # a 10-bit-only limit
    ],
)
def test_a_missing_driver_device_or_10bit_limit_is_no_build_mismatch_real(
    capture: str, encoder: str
) -> None:
    returncode = ft.captures()[capture].exit_code
    failure = explain_failure(stderr(capture), ctx(encoder), returncode=returncode)
    assert failure.state is UNAVAILABLE
    assert (failure.build_mismatch, failure.cause) == (False, None)


@pytest.mark.parametrize(
    ("encoder", "line"),
    [
        (
            "hevc_amf",
            "10-bit encoder is not supported by AMD GPU drivers versions lower than 23.30.",
        ),
        ("hevc_nvenc", "10 bit encode not supported"),
        ("h264_nvenc", "Cannot load nvcuda.dll"),
        ("h264_nvenc", "No CUDA capable devices found"),
        ("av1_nvenc", "No capable devices found"),
    ],
)
def test_the_amd_10bit_driver_text_and_missing_nvidia_parts_are_no_build_mismatch(
    encoder: str, line: str
) -> None:
    failure = explain_failure(tagged(encoder, line), ctx(encoder), returncode=1)
    assert failure.state is UNAVAILABLE
    assert (failure.build_mismatch, failure.cause) == (False, None)


def test_a_driver_without_its_nvenc_library_is_no_build_mismatch() -> None:
    """nvenc.c prints the driver requirement after any failed load of the NVENC library."""
    text = tagged("hevc_nvenc", "Cannot load libnvidia-encode.so.1", NVENC_DRIVER_TOO_OLD[1])
    failure = explain_failure(text, ctx("hevc_nvenc"), returncode=1)
    assert (failure.state, failure.reason, failure.build_mismatch) == (
        UNAVAILABLE,
        "The NVIDIA driver has no NVENC library (libnvidia-encode.so.1)",
        False,
    )


def test_a_filter_is_never_a_build_mismatch() -> None:
    failure = explain_failure(OLD_LIBVA, FILTER, returncode=-6)
    assert failure.state is UNAVAILABLE
    assert (failure.build_mismatch, failure.cause) == (False, None)
