"""Encoder rules for levels (x265 and NVENC), the picture size of AMF's pre-analysis, and for
the advanced options and custom parameters.

Without the level and picture-size rules, a level too small for the picture or the bitrate, or
a picture too small for the pre-analysis, would validate, and the encoder would then refuse to
start. The bitrate, option and custom-parameter rules also run for templates, since they need
only the video settings.
"""

from __future__ import annotations

import math
import re
from collections.abc import Collection, Iterator
from fractions import Fraction

from reframe.command.video import sets_rate_buffer
from reframe.definitions import VideoEncoderDef, effective_option
from reframe.definitions.custom_params import CustomParam, split_custom_params
from reframe.definitions.options import effective_preset
from reframe.models.issues import Fix, ValidationIssue
from reframe.models.job import VideoSettings
from reframe.validation.common import error, fix, replace
from reframe.validation.context import JobContext, TemplateContext
from reframe.validation.registry import job_rule, shared_rule
from reframe.validation.video import (
    CUSTOM_PARAM_CODES,
    OPTION_RULE_CODES,
    OVERRIDE_CODE,
    option_int,
    remove_param_fix,
    video_custom_param_issues,
    video_custom_param_override_issues,
    video_option_rule_issues,
)

__all__ = [
    "AMF_PREANALYSIS_MIN_SIZE",
    "H264_LEVELS",
    "X265_LEVELS",
    "h264_level_fits",
    "nvenc_level_kbps",
    "x265_level_fits",
    "x265_min_cu_size",
]

#: level → (MaxLumaPs, MaxLumaSr), H.265 table A.8 (the same for both tiers).
X265_LEVELS: dict[str, tuple[int, int]] = {
    "1.0": (36_864, 552_960),
    "2.0": (122_880, 3_686_400),
    "2.1": (245_760, 7_372_800),
    "3.0": (552_960, 16_588_800),
    "3.1": (983_040, 33_177_600),
    "4.0": (2_228_224, 66_846_720),
    "4.1": (2_228_224, 133_693_440),
    "5.0": (8_912_896, 267_386_880),
    "5.1": (8_912_896, 534_773_760),
    "5.2": (8_912_896, 1_069_547_520),
    "6.0": (35_651_584, 1_069_547_520),
    "6.1": (35_651_584, 2_139_095_040),
    "6.2": (35_651_584, 4_278_190_080),
}


def _padded(size: int, unit: int) -> int:
    return -(-size // unit) * unit


def x265_min_cu_size(video: VideoSettings, encoder: VideoEncoderDef | None) -> int | None:
    """The minimum coding unit x265 uses for ``video``: the job's ``min-cu-size``, else the
    speed preset's default; ``None`` when not known."""
    if encoder is None:
        return None
    size = option_int(effective_option(encoder, video, "min-cu-size"))
    return size if size in (8, 16, 32) else None


def x265_level_fits(
    level: str,
    width: int,
    height: int,
    rate: Fraction | None,
    preset: str | None,
    *,
    min_cu: int | None = None,
) -> str | None:
    """Why x265 refuses ``level`` for this picture (``None``: it fits, or the level is not
    in the table). The picture is padded to ``min_cu`` (default: the preset's minimum coding
    unit, 16 for ``ultrafast`` and 8 otherwise)."""
    limits = X265_LEVELS.get(level)
    if limits is None:
        return None
    max_samples, max_rate = limits
    unit = min_cu if min_cu is not None else (16 if preset == "ultrafast" else 8)
    w, h = _padded(width, unit), _padded(height, unit)
    longest = math.isqrt(8 * max_samples)
    if w * h > max_samples or w > longest or h > longest:
        return "the picture is too large"
    if rate is not None and w * h * rate > max_rate:
        return "the frame rate is too high for the picture size"
    return None


#: level → (MaxMBPS, MaxFS) in 16x16 macroblocks, H.264 table A-1. NVENC refuses a level that
#: the picture size or frame rate exceeds (checked with h264_nvenc).
H264_LEVELS: dict[str, tuple[int, int]] = {
    "1.0": (1_485, 99),
    "1b": (1_485, 99),
    "1.1": (3_000, 396),
    "1.2": (6_000, 396),
    "1.3": (11_880, 396),
    "2.0": (11_880, 396),
    "2.1": (19_800, 792),
    "2.2": (20_250, 1_620),
    "3.0": (40_500, 1_620),
    "3.1": (108_000, 3_600),
    "3.2": (216_000, 5_120),
    "4.0": (245_760, 8_192),
    "4.1": (245_760, 8_192),
    "4.2": (522_240, 8_704),
    "5.0": (589_824, 22_080),
    "5.1": (983_040, 36_864),
    "5.2": (2_073_600, 36_864),
    "6.0": (4_177_920, 139_264),
    "6.1": (8_355_840, 139_264),
    "6.2": (16_711_680, 139_264),
}


def h264_level_fits(level: str, width: int, height: int, rate: Fraction | None) -> str | None:
    """Why an H.264 encoder refuses ``level`` for this picture (``None``: it fits, or the level
    is not in the table)."""
    limits = H264_LEVELS.get(level)
    if limits is None:
        return None
    max_rate, max_blocks = limits
    blocks = -(-width // 16) * -(-height // 16)
    longest = math.isqrt(8 * max_blocks) * 16
    if blocks > max_blocks or width > longest or height > longest:
        return "the picture is too large"
    if rate is not None and blocks * rate > max_rate:
        return "the frame rate is too high for the picture size"
    return None


def _rate(ctx: JobContext) -> Fraction | None:
    """The frame rate x265 gets: the chosen one, else the source's average (or its frame
    rate)."""
    video = ctx.job.video
    stream = ctx.video_stream
    chosen = video.framerate
    if chosen is None and stream is not None:
        chosen = stream.avg_frame_rate or stream.frame_rate
    if chosen is None or chosen.num <= 0 or chosen.den <= 0:
        return None
    return Fraction(chosen.num, chosen.den)


@job_rule("encoder", "encoder.level_too_low")
def level_fits(ctx: JobContext) -> Iterator[ValidationIssue]:
    video = ctx.job.video
    size = ctx.output_size
    fits_checks = {"libx265", "hevc_nvenc", "h264_nvenc"}
    if video.passthrough or video.encoder not in fits_checks or video.level is None or size is None:
        return
    encoder = ctx.definitions.video_encoders.get(video.encoder)
    levels = encoder.levels if encoder is not None else None
    if encoder is None or levels is None or levels.get(video.level) is None:
        return  # encoder.level_unsupported
    rate = _rate(ctx)
    width, height = size
    if encoder.id == "libx265":
        preset = effective_preset(encoder, video)
        min_cu = x265_min_cu_size(video, encoder)

        def why_not(level: str) -> str | None:
            return x265_level_fits(level, width, height, rate, preset, min_cu=min_cu)

        table: Collection[str] = X265_LEVELS
        name = "x265"
    else:
        h264 = encoder.id == "h264_nvenc"

        def why_not(level: str) -> str | None:
            if h264:
                return h264_level_fits(level, width, height, rate)
            return x265_level_fits(level, width, height, rate, None, min_cu=8)

        table = H264_LEVELS if h264 else X265_LEVELS
        name = encoder.label
    why = why_not(video.level)
    if why is None:
        return
    fixes: list[Fix] = []
    fitting = next(  # the smallest level that fits (the choices are in ascending order)
        (
            choice.value
            for choice in levels.choices
            if choice.value in table and why_not(choice.value) is None
        ),
        None,
    )
    if fitting is not None:
        fixes.append(fix(f"Use level {fitting}", replace("video.level", fitting)))
    fixes.append(fix(f"Let {name} choose the level", replace("video.level", None)))
    shown = f" at {float(rate):.3g} fps" if rate is not None else ""
    yield error(
        "encoder.level_too_low",
        "video.level",
        f"{name} level {video.level} is too low for {width}x{height}{shown}: {why}, and "
        f"{name} would refuse to encode.",
        *fixes,
    )


#: The highest average bitrate (kb/s) NVENC takes at an H.264 level, for Baseline and Main /
#: for High. Measured: it is min(MaxBR, MaxCPB / 2) times the NAL factor, because FFmpeg gives
#: NVENC a buffer of twice the bitrate and NVENC checks both against the level.
NVENC_H264_LEVEL_KBPS: dict[str, tuple[int, int]] = {
    "1.0": (76, 96),
    "1b": (153, 192),
    "1.1": (230, 288),
    "1.2": (460, 576),
    "1.3": (921, 1152),
    "2.0": (1200, 1500),
    "2.1": (2400, 3000),
    "2.2": (2400, 3000),
    "3.0": (6000, 7500),
    "3.1": (8400, 10500),
    "3.2": (12000, 15000),
    "4.0": (15000, 18750),
    "4.1": (37500, 46875),
    "4.2": (37500, 46875),
    "5.0": (81000, 101250),
    "5.1": (144000, 180000),
    "5.2": (144000, 180000),
    "6.0": (144000, 180000),
    "6.1": (288000, 360000),
    "6.2": (480000, 600000),
}
#: The same for H.265 (Main and Main 10 alike), Main tier / High tier. ``None``: the level has
#: no High tier, and NVENC then checks no bitrate.
NVENC_HEVC_LEVEL_KBPS: dict[str, tuple[int, int | None]] = {
    "1.0": (140, None),
    "2.0": (825, None),
    "2.1": (1650, None),
    "3.0": (3300, None),
    "3.1": (5500, None),
    "4.0": (6600, 16500),
    "4.1": (11000, 27500),
    "5.0": (13750, 55000),
    "5.1": (22000, 88000),
    "5.2": (33000, 132000),
    "6.0": (33000, 132000),
    "6.1": (66000, 264000),
    "6.2": (132000, 440000),
}


def nvenc_level_kbps(encoder: str, level: str, profile: str | None, tier: str | None) -> int | None:
    """The highest bitrate NVENC takes at ``level`` in bitrate mode; ``None``: not known."""
    if encoder == "h264_nvenc":
        limits = NVENC_H264_LEVEL_KBPS.get(level)
        if limits is None or profile not in ("baseline", "main", "high"):
            return None  # High 10: not measured (no GPU at hand encodes 10-bit H.264)
        return limits[1] if profile == "high" else limits[0]
    if encoder == "hevc_nvenc":
        tiers = NVENC_HEVC_LEVEL_KBPS.get(level)
        if tiers is None:
            return None
        return tiers[1] if tier == "high" else tiers[0]
    return None


@shared_rule("encoder", "encoder.level_bitrate_too_high")
def nvenc_level_bitrate(ctx: JobContext | TemplateContext) -> list[ValidationIssue]:
    video = ctx.doc.video
    rc = video.rate_control
    encoder = ctx.definitions.video_encoders.get(video.encoder)
    if video.passthrough or encoder is None or video.level is None or rc.mode != "bitrate":
        return []
    if sets_rate_buffer(video.custom_params):
        return []  # the user's own rate buffer: NVENC checks that instead
    profile = video.profile
    if profile is None and encoder.profiles is not None:
        profile = encoder.profiles.default_for(video.bit_depth)
    tier = video.advanced.get("tier")
    limit = nvenc_level_kbps(
        encoder.id, video.level, profile, tier if isinstance(tier, str) else None
    )
    if limit is None or rc.kbps <= limit:
        return []
    return [
        error(
            "encoder.level_bitrate_too_high",
            "video.rate_control.kbps",
            f"{encoder.label} refuses level {video.level} at {rc.kbps} kb/s: at that level it "
            f"takes at most {limit} kb/s (FFmpeg gives it a rate buffer of twice the bitrate).",
            fix(f"Use {limit} kb/s", replace("video.rate_control.kbps", limit)),
            fix("Let the encoder choose the level", replace("video.level", None)),
        )
    ]


#: The smallest picture (width, height) that AMF's pre-analysis takes, the same for the three
#: AMF encoders. Below it the encoder does not start (exit 190).
AMF_PREANALYSIS_MIN_SIZE = (320, 200)
#: AMF rate controls that start the pre-analysis without the ``preanalysis`` option, by name
#: and by number.
_AMF_PREANALYSIS_RATE_CONTROLS: dict[str, int] = {"qvbr": 4, "hqvbr": 5, "hqcbr": 6}
#: FFmpeg's boolean words (any case); ``auto`` (this case only) and ``-1`` leave it to the
#: driver.
_TRUE = frozenset({"true", "y", "yes", "enable", "enabled", "on"})
_FALSE = frozenset({"false", "n", "no", "disable", "disabled", "off"})
_INTEGER = re.compile(r"[+-]?\d+")


def _ffmpeg_int(value: str) -> int | None:
    return int(value) if _INTEGER.fullmatch(value) else None


def _ffmpeg_bool(value: str) -> int | None:
    """An option value as FFmpeg reads a boolean: 1, 0, -1 (auto); ``None`` when it refuses it."""
    if value == "auto":
        return -1
    if value.casefold() in _TRUE:
        return 1
    if value.casefold() in _FALSE:
        return 0
    number = _ffmpeg_int(value)
    return number if number is not None and -1 <= number <= 1 else None


def _preanalysis_params(custom_params: str) -> tuple[list[CustomParam], list[CustomParam]]:
    """All custom parameters, and those that turn AMF's pre-analysis on."""
    params = split_custom_params(custom_params)
    on: list[CustomParam] = []
    rate_controls = set(_AMF_PREANALYSIS_RATE_CONTROLS.values())
    for param in params:
        name = param.name.lstrip("-").casefold()
        value = param.value.strip()
        rc = _AMF_PREANALYSIS_RATE_CONTROLS.get(value, _ffmpeg_int(value))
        if (name == "preanalysis" and _ffmpeg_bool(value) == 1) or (
            name == "rc" and rc in rate_controls
        ):
            on.append(param)
    return params, on


@job_rule("encoder", "encoder.preanalysis_picture_too_small")
def amf_preanalysis_size(ctx: JobContext) -> Iterator[ValidationIssue]:
    video = ctx.job.video
    size = ctx.output_size
    encoder = ctx.definitions.video_encoders.get(video.encoder)
    if video.passthrough or encoder is None or encoder.family != "amf" or size is None:
        return
    width, height = size
    min_width, min_height = AMF_PREANALYSIS_MIN_SIZE
    if width >= min_width and height >= min_height:
        return
    why = (
        f"AMF's pre-analysis needs a picture of at least {min_width}x{min_height}, and the "
        f"output is {width}x{height}: {encoder.label} would not start."
    )
    if video.advanced.get("preanalysis") is True:
        yield error(
            "encoder.preanalysis_picture_too_small",
            "video.advanced.preanalysis",
            why,
            fix("Turn pre-analysis off", replace("video.advanced.preanalysis", False)),
        )
    params, on = _preanalysis_params(video.custom_params)
    if on:
        yield error(
            "encoder.preanalysis_picture_too_small",
            "video.custom_params",
            f"The custom parameter {on[0].raw.strip()} turns the pre-analysis on. {why}",
            remove_param_fix(params, on[0]),
        )


@shared_rule("encoder", *OPTION_RULE_CODES)
def advanced_option_rules(ctx: JobContext | TemplateContext) -> list[ValidationIssue]:
    return video_option_rule_issues(ctx.doc.video, ctx.caps, ctx.definitions)


@shared_rule("encoder", *CUSTOM_PARAM_CODES)
def custom_params(ctx: JobContext | TemplateContext) -> list[ValidationIssue]:
    """Custom parameters that name a file, or that FFmpeg would read as its own options."""
    return video_custom_param_issues(ctx.doc.video, ctx.caps, ctx.definitions)


@shared_rule("encoder", OVERRIDE_CODE)
def custom_param_overrides(ctx: JobContext | TemplateContext) -> list[ValidationIssue]:
    return video_custom_param_override_issues(ctx.doc.video, ctx.definitions)
