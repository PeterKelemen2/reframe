"""Encoder rules of C-6's options: x265 level limits (M2 review) and the advanced-option rules
(M9, :func:`reframe.validation.video.video_option_rule_issues`, registered here for jobs; a
template rule needs a case in ``tests/validation/test_template.py``, which another task owns).

x265 levels: a level too small for the output size or frame rate validates clean, then x265
refuses to start.

Checked with x265 in FFmpeg n9.0.2 (both builds; testdata/README.md "Validation (C-8)",
``tests/validation/test_levels_ffmpeg.py``): with ``-x265-params level-idc=L`` x265 exits
with "picture dimensions are out of range for specified level" when the picture has more
luma samples than the level's MaxLumaPs, or a side longer than ``sqrt(8 * MaxLumaPs)``, and
with "frame rate is out of range for specified level" when samples x frame rate exceed
MaxLumaSr. The limits are those of H.265 table A.8, measured on the picture padded to the
minimum coding unit: 16 for the ``ultrafast`` preset, 8 for the others (at level 4,
1920x1160 passes with ``medium`` and fails with ``ultrafast``).
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from fractions import Fraction

from reframe.models.issues import Fix, ValidationIssue
from reframe.validation.common import error, fix, replace
from reframe.validation.context import JobContext
from reframe.validation.registry import job_rule
from reframe.validation.video import OPTION_RULE_CODES, video_option_rule_issues

__all__ = ["X265_LEVELS", "x265_level_fits"]

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


def _padded(size: int, preset: str | None) -> int:
    unit = 16 if preset == "ultrafast" else 8
    return -(-size // unit) * unit


def x265_level_fits(
    level: str, width: int, height: int, rate: Fraction | None, preset: str | None
) -> str | None:
    """Why x265 refuses ``level`` for this picture (``None``: it fits, or the level is not
    in the table)."""
    limits = X265_LEVELS.get(level)
    if limits is None:
        return None
    max_samples, max_rate = limits
    w, h = _padded(width, preset), _padded(height, preset)
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
    rate = _rate(ctx)
    width, height = size
    why = x265_level_fits(video.level, width, height, rate, preset)
    if why is None:
        return
    fixes: list[Fix] = []
    fitting = next(  # the smallest level that fits (the choices are in ascending order)
        (
            choice.value
            for choice in levels.choices
            if choice.value in X265_LEVELS
            and x265_level_fits(choice.value, width, height, rate, preset) is None
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
