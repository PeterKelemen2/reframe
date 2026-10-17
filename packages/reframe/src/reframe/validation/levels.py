"""Encoder rules of C-6's options: x265 level limits (M2 review) and the advanced-option rules
(M9, :func:`reframe.validation.video.video_option_rule_issues`, registered here for jobs and
for templates: the three codes need only the video settings, no source).

x265 levels: a level too small for the output size or frame rate validates clean, then x265
refuses to start.

Checked with x265 in FFmpeg n9.0.2 (both builds; testdata/README.md "Validation (C-8)",
``tests/validation/test_levels_ffmpeg.py``): with ``-x265-params level-idc=L`` x265 exits
with "picture dimensions are out of range for specified level" when the picture has more
luma samples than the level's MaxLumaPs, or a side longer than ``sqrt(8 * MaxLumaPs)``, and
with "frame rate is out of range for specified level" when samples x frame rate exceed
MaxLumaSr. The limits are those of H.265 table A.8, measured on the picture padded to the
minimum coding unit: the job's ``min-cu-size``, else the preset's (16 for ``ultrafast``, 8 for
the others). At level 4, 1920x1160 passes with ``medium`` and fails with ``ultrafast``;
``medium`` with ``min-cu-size=16`` fails and ``ultrafast`` with ``min-cu-size=8`` passes
(core-complete review R5-4, decision 0014).
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from fractions import Fraction

from reframe.definitions import VideoEncoderDef, option_default
from reframe.models.issues import Fix, ValidationIssue
from reframe.models.job import VideoSettings
from reframe.validation.common import error, fix, replace
from reframe.validation.context import JobContext, TemplateContext
from reframe.validation.registry import job_rule, template_rule
from reframe.validation.video import (
    CUSTOM_PARAM_CODES,
    OPTION_RULE_CODES,
    video_custom_param_issues,
    video_option_rule_issues,
)

__all__ = ["X265_LEVELS", "x265_level_fits", "x265_min_cu_size"]

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
    speed preset's default (C-6's per-preset table); ``None`` when not known."""
    if encoder is None:
        return None
    option = encoder.option("min-cu-size")
    if option is None:
        return None
    value = video.advanced.get("min-cu-size")
    if value is None:
        preset = video.preset or (encoder.presets.default if encoder.presets else None)
        value = option_default(option, preset)
    if isinstance(value, bool) or value is None:
        return None
    try:
        size = int(value)
    except ValueError:
        return None
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
def x265_level(ctx: JobContext) -> Iterator[ValidationIssue]:
    video = ctx.job.video
    size = ctx.output_size
    if video.passthrough or video.encoder != "libx265" or video.level is None or size is None:
        return
    encoder = ctx.definitions.video_encoders.get(video.encoder)
    levels = encoder.levels if encoder is not None else None
    if levels is None or levels.get(video.level) is None:
        return  # encoder.level_unsupported
    preset = video.preset or (encoder.presets.default if encoder and encoder.presets else None)
    min_cu = x265_min_cu_size(video, encoder)
    rate = _rate(ctx)
    width, height = size
    why = x265_level_fits(video.level, width, height, rate, preset, min_cu=min_cu)
    if why is None:
        return
    fixes: list[Fix] = []
    fitting = next(  # the smallest level that fits (the choices are in ascending order)
        (
            choice.value
            for choice in levels.choices
            if choice.value in X265_LEVELS
            and x265_level_fits(choice.value, width, height, rate, preset, min_cu=min_cu) is None
        ),
        None,
    )
    if fitting is not None:
        fixes.append(
            fix(f"Use level {fitting}", replace("video.level", fitting), target=ctx.target)
        )
    fixes.append(fix("Let x265 choose the level", replace("video.level", None), target=ctx.target))
    shown = f" at {float(rate):.3g} fps" if rate is not None else ""
    yield error(
        "encoder.level_too_low",
        "video.level",
        f"x265 level {video.level} is too low for {width}x{height}{shown}: {why}, and x265 "
        "would refuse to encode.",
        *fixes,
    )


# --------------------------------------------------------------------------- option rules (M9)


@job_rule("encoder", *OPTION_RULE_CODES)
def advanced_option_rules(ctx: JobContext) -> list[ValidationIssue]:
    return video_option_rule_issues(ctx.job.video, ctx.caps, ctx.definitions, target=ctx.target)


@job_rule("encoder", *CUSTOM_PARAM_CODES)
def custom_params(ctx: JobContext) -> list[ValidationIssue]:
    """Custom parameters that name a file, or that FFmpeg would read as its own options
    (decision 0035 "Follow-up (core-complete review)")."""
    return video_custom_param_issues(ctx.job.video, ctx.caps, ctx.definitions, target=ctx.target)


@template_rule("encoder", *OPTION_RULE_CODES, *CUSTOM_PARAM_CODES)
def template_advanced_option_rules(ctx: TemplateContext) -> list[ValidationIssue]:
    """A preset's video settings: the same rules (the option rules and the custom
    parameters), fixes on the template."""
    video = ctx.template.video
    return [
        *video_option_rule_issues(video, ctx.caps, ctx.definitions, target=ctx.target),
        *video_custom_param_issues(video, ctx.caps, ctx.definitions, target=ctx.target),
    ]
