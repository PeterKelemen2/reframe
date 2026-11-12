"""Turn a failed hardware test encode into a plain-language reason. Pure.

A known text gives ``unavailable`` with its reason. Anything else gives ``error`` ("the check
itself failed") with the most informative line (:func:`informative_line`). The same mapping
explains a failed filter run test.

The texts that FFmpeg prints are recorded in ``testdata/README.md`` ("Hardware encoder
failures"). The last stderr line is generic, so the reason comes from an earlier line when
there is one.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from reframe.models.capabilities import EncoderState
from reframe.tools.exitcodes import crashed

__all__ = [
    "Failure",
    "TestContext",
    "explain_failure",
    "informative_line",
    "normalise_line",
]

_ADDRESS = re.compile(r" @ 0x[0-9a-fA-F]+\]")
#: Lines that never explain a failure (fftools bookkeeping, progress, Mesa notices).
_NOISE = re.compile(
    r"^(?:Input #|Output #|Stream mapping:|Stream #|Press \[q\]|frame=|size=|video:|"
    r"Conversion failed!|Exiting with exit code|Error parsing global options|radv: |"
    r"\[(?:vf|vost|aost|out|in|dec|enc|sq|mux)#)"
    r"|Nothing was written into output file|Task finished with error code|"
    r"Terminating thread with return code|Could not open encoder before EOF|"
    r"Error sending frames to consumers"
)
#: ``[hevc_nvenc @ 0x…] text`` (as FFmpeg prints it) or ``[hevc_nvenc] text`` (normalised).
_TAG = re.compile(r"^\[(?P<tag>[^\]@]+?)(?: @ [^\]]*)?\]\s*(?P<text>.*)$")
#: Log contexts of hardware devices (libavutil/hwcontext_*.c).
_DEVICE_TAGS = frozenset({"VAAPI", "AMF", "AVHWDeviceContext", "AVHWFramesContext", "CUDA", "QSV"})


@dataclass(frozen=True)
class TestContext:
    """What the reason mapping knows about the test that failed."""

    __test__ = False  # not a pytest test class

    encoder: str
    """The encoder id (the filter name for a filter run test)."""
    family: str = "software"
    """The encoder family (``EncoderFamily`` of the definitions)."""
    codec_label: str = ""
    """The codec's display name, used in the reason texts."""
    device: str | None = None
    """The device the test asked for (VAAPI encoders)."""


@dataclass(frozen=True)
class Failure:
    """Why a test encode failed."""

    state: EncoderState
    """``unavailable`` for a known reason, ``error`` for an unknown one."""
    reason: str
    detail: str | None = None
    """The FFmpeg line the reason comes from (pointer addresses removed)."""


_Reason = Callable[[re.Match[str], TestContext, Sequence[str]], str]


@dataclass(frozen=True)
class _Rule:
    pattern: re.Pattern[str]
    reason: _Reason
    families: frozenset[str] | None = None
    """Only for these encoder families (``None``: any)."""


def _fixed(text: str) -> _Reason:
    return lambda _m, _ctx, _lines: text


def _codec(ctx: TestContext) -> str:
    return ctx.codec_label or "this format"


def _nvenc_too_old(match: re.Match[str], _ctx: TestContext, texts: Sequence[str]) -> str:
    for text in texts:
        minimum = re.search(r"minimum required Nvidia driver for nvenc is (\S+?) or newer", text)
        if minimum is not None:
            return f"NVIDIA driver too old: NVENC needs driver {minimum[1]} or newer"
    return f"NVIDIA driver too old (NVENC API {match['found']}, needs {match['required']})"


def _vaapi_device(match: re.Match[str], ctx: TestContext, _texts: Sequence[str]) -> str:
    device = match.groupdict().get("device") or ctx.device or "/dev/dri"
    return f"No VAAPI device ({device})"


def _vaapi_driver(match: re.Match[str], ctx: TestContext, _texts: Sequence[str]) -> str:
    where = f" on {ctx.device}" if ctx.device else ""
    return f"VAAPI driver failed to start{where} ({match['error']})"


def _device_creation(match: re.Match[str], ctx: TestContext, _texts: Sequence[str]) -> str:
    if ctx.family == "qsv":
        return _NO_QSV
    if ctx.family == "vaapi":
        return f"No VAAPI device ({ctx.device or match['value']})"
    return f"The hardware device could not be created ({match['value']})"


def _with_rest(prefix: str, fallback: str = "") -> _Reason:
    def reason(match: re.Match[str], _ctx: TestContext, _texts: Sequence[str]) -> str:
        rest = match["rest"].strip().rstrip(".")
        if rest:
            return f"{prefix} ({rest})"
        return f"{prefix} ({fallback})" if fallback else prefix

    return reason


_NO_QSV = "No Intel QSV device (needs an Intel GPU with its media driver)"
_NVENC = frozenset({"nvenc"})

#: Known texts, most specific first. The first rule that matches any line wins.
_RULES: tuple[_Rule, ...] = (
    # NVIDIA: libavcodec/nvenc.c and the CUDA loader (compat/cuda, ffnvcodec)
    _Rule(
        re.compile(
            r"Driver does not support the required nvenc API version\. "
            r"Required: (?P<required>[\d.]+) Found: (?P<found>[\d.]+)"
        ),
        _nvenc_too_old,
    ),
    _Rule(
        re.compile(r"Cannot load (?:libcuda\.so[\d.]*|nvcuda\.dll)"),
        _fixed("NVIDIA driver not found"),
    ),
    _Rule(re.compile(r"No CUDA capable devices found"), _fixed("No NVIDIA GPU found")),
    _Rule(
        re.compile(r"^No capable devices found"),
        lambda _m, ctx, _t: f"No NVIDIA GPU that can encode {_codec(ctx)}",
        _NVENC,
    ),
    _Rule(
        re.compile(r"^Codec not supported$"),
        lambda _m, ctx, _t: f"This NVIDIA GPU cannot encode {_codec(ctx)}",
        _NVENC,
    ),
    _Rule(
        re.compile(r"OpenEncodeSessionEx failed:?\s*(?P<rest>.*)$"),
        _with_rest("NVENC could not open an encoding session"),
    ),
    _Rule(
        re.compile(r"^10 bit encode not supported$"),
        _fixed("10-bit is not supported by this GPU"),
        _NVENC,
    ),
    # Intel QSV (oneVPL): libavcodec/qsv.c, libavutil/hwcontext_qsv.c
    _Rule(re.compile(r"Error (?:creating|initializing|querying) an? MFX session"), _fixed(_NO_QSV)),
    # VAAPI: libavutil/hwcontext_vaapi.c
    _Rule(re.compile(r"No VA display found for device (?P<device>\S+?)\.?$"), _vaapi_device),
    _Rule(re.compile(r"No VA display found for any default device"), _vaapi_device),
    _Rule(
        re.compile(r"Failed to initialise VAAPI connection: -?\d+ \((?P<error>.*)\)"),
        _vaapi_driver,
    ),
    _Rule(re.compile(r"Failed to create a VAAPI device"), _vaapi_device),
    # AMD AMF: libavutil/hwcontext_amf.c, libavcodec/amfenc*.c
    _Rule(
        re.compile(r"DLL (?P<lib>\S+) failed to open"),
        lambda m, _ctx, _t: f"AMD AMF runtime not found ({m['lib']})",
    ),
    _Rule(
        re.compile(
            r"10-bit encoder is not supported by AMD GPU drivers versions lower than (\S+?)\.?$"
        ),
        lambda m, _ctx, _t: f"AMD driver too old for 10-bit (needs {m[1]} or newer)",
    ),
    _Rule(
        re.compile(r"10-bit input video is not supported by .+"),
        _fixed("10-bit is not supported by this encoder"),
    ),
    _Rule(
        re.compile(r"Failed to create\s+hardware device context \(AMF\)\s*:\s*(?P<rest>.*)$"),
        _with_rest("AMD AMF could not start", "unknown error"),
    ),
    # Vulkan, for the libplacebo run test (libplacebo, linked into libavfilter)
    _Rule(
        re.compile(r"Failed creating instance: (?P<code>VK_\w+)"),
        lambda m, _ctx, _t: f"No working Vulkan driver ({m['code']})",
    ),
    # Without a Vulkan loader (no vulkan-1.dll / libvulkan.so.1) libplacebo also sees 1.0.
    _Rule(
        re.compile(
            r"Instance API version (?P<have>[\d.]+) is lower than the minimum required "
            r"version of (?P<need>[\d.]+)"
        ),
        lambda m, _ctx, _t: (
            f"No Vulkan runtime, or one too old for libplacebo "
            f"(Vulkan {m['have']}, needs {m['need']})"
        ),
    ),
    _Rule(
        re.compile(
            r"Device API version (?P<have>[\d.]+) is lower than the minimum required "
            r"version of (?P<need>[\d.]+)"
        ),
        lambda m, _ctx, _t: (
            f"The Vulkan driver is too old for libplacebo (Vulkan {m['have']}, needs {m['need']})"
        ),
    ),
    _Rule(
        re.compile(r"Found no suitable device, giving up"),
        _fixed("No Vulkan device that libplacebo can use"),
    ),
    _Rule(
        re.compile(r"Vulkan device does not support all required features"),
        _fixed("The Vulkan device lacks features that libplacebo needs"),
    ),
    _Rule(
        re.compile(r"Failed creating logical device"),
        _fixed("The Vulkan device could not be opened"),
    ),
    # The build loads system libraries (libva, …) at run time through implib-gen stubs, which
    # abort when the system's library lacks a function the build was compiled against.
    _Rule(
        re.compile(r"^implib-gen: (?P<lib>\S+): failed to resolve symbol '(?P<symbol>[^']+)'"),
        lambda m, _ctx, _t: (
            f"The system's {m['lib']} is too old for this FFmpeg build (it has no {m['symbol']})"
        ),
    ),
    _Rule(
        re.compile(r"^implib-gen: (?P<lib>\S+): failed to load library"),
        lambda m, _ctx, _t: f"The system library {m['lib']} is not installed",
    ),
    # A hardware device option failed (fftools) and no device line said why.
    _Rule(
        re.compile(
            r"Failed to set value '(?P<value>[^']*)' for option "
            r"'(?:init_hw_device|vaapi_device|qsv_device)'"
        ),
        _device_creation,
    ),
)


def normalise_line(line: str) -> str:
    """The line without its pointer address: ``[hevc_nvenc @ 0x55…] x`` → ``[hevc_nvenc] x``
    (the address changes on every run)."""
    return _ADDRESS.sub("]", line.strip())


def _top_lines(stderr: str) -> list[str]:
    """Non-empty lines that are not indented (indented lines are stream and metadata dumps)."""
    return [raw.strip() for raw in stderr.splitlines() if raw.strip() and raw[0] not in " \t"]


def _split(line: str) -> tuple[str | None, str]:
    """``(context tag, text)``: ``[hevc_nvenc @ 0x…] Cannot load …`` → ``("hevc_nvenc", …)``."""
    tagged = _TAG.match(line)
    if tagged is None:
        return None, line
    return tagged["tag"].strip(), tagged["text"]


def informative_line(stderr: str, encoder: str) -> str | None:
    """The line of a failed run that says the most, without its pointer address. ``None`` for
    an empty stderr."""
    top = _top_lines(stderr)
    if not top:
        rest = [raw.strip() for raw in stderr.splitlines() if raw.strip()]
        return normalise_line(rest[-1]) if rest else None
    tags = [_split(line)[0] for line in top]
    for line, tag in zip(top, tags, strict=True):
        if tag == encoder:
            return normalise_line(line)
    for line, tag in zip(top, tags, strict=True):
        if tag in _DEVICE_TAGS:
            return normalise_line(line)
    for line in top:
        if line.startswith(("Device creation failed", "Failed to set value")):
            return normalise_line(line)
    for line in top:
        if not _NOISE.search(line):
            return normalise_line(line)
    return normalise_line(top[-1])


def explain_failure(stderr: str, ctx: TestContext, *, returncode: int | None = None) -> Failure:
    """Why a test encode failed: a known text (``unavailable``) or the most informative line
    (``error``). ``returncode`` names a crash when no known text explains it."""
    lines = [(normalise_line(line), _split(line)[1]) for line in _top_lines(stderr)]
    texts = [text for _line, text in lines]
    for rule in _RULES:
        if rule.families is not None and ctx.family not in rule.families:
            continue
        for line, text in lines:
            match = rule.pattern.search(text)
            if match is not None:
                return Failure(EncoderState.UNAVAILABLE, rule.reason(match, ctx, texts), line)
    detail = informative_line(stderr, ctx.encoder)
    test = f"the {ctx.encoder} test" if ctx.family == "filter" else "the test encode"
    crash = _crash(returncode)
    if crash is not None:
        return Failure(EncoderState.ERROR, f"FFmpeg crashed during {test} ({crash})", detail)
    if detail is None:
        code = "" if returncode is None else f" (exit code {returncode})"
        return Failure(EncoderState.ERROR, f"{test.capitalize()} failed with no message{code}")
    return Failure(EncoderState.ERROR, f"{test.capitalize()} failed: {_split(detail)[1]}", detail)


def _crash(returncode: int | None) -> str | None:
    if returncode is None or not crashed(returncode):
        return None
    if returncode < 0:
        return f"signal {-returncode}"
    return f"exit code 0x{returncode:08X}"
