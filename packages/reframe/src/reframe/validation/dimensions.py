"""Dimension rules: the crop and size checks of the geometry, reported as issues.

``compute_geometry`` never fails: it applies what it can and notes each change. These rules
turn the notes that matter into issues (the note is the message). Odd sizes for 4:2:0 cannot
happen: the geometry rounds every size to a multiple of the modulus and of the chroma step.
"""

from __future__ import annotations

from collections.abc import Iterator
from fractions import Fraction

from reframe.dimensions import TIMES, compute_geometry, oriented_box
from reframe.models.geometry import (
    CropRect,
    DimensionSettings,
    FitWithin,
    Geometry,
    SourceGeometry,
)
from reframe.models.issues import Fix, FixTarget, ValidationIssue
from reframe.validation.common import error, fix, info, replace, warning
from reframe.validation.context import JobContext, TemplateContext
from reframe.validation.registry import job_rule, template_rule


def _notes(geometry: Geometry, *starts: str) -> list[str]:
    return [note for note in geometry.notes if note.startswith(starts)]


def _axes(src: SourceGeometry) -> tuple[tuple[int, int], tuple[int, int]]:
    """Width and height of the picture the crop is measured on, with the display rotation
    applied, each with its chroma step."""
    steps = (src.chroma_step_x, src.chroma_step_y * (2 if src.interlaced else 1))
    if src.rotation in (90, 270):
        return ((src.height, steps[1]), (src.width, steps[0]))
    return ((src.width, steps[0]), (src.height, steps[1]))


def _invalid_axes(rect: CropRect, geometry: Geometry, src: SourceGeometry) -> list[str]:
    """The crop axes the geometry did not apply, although the rect asks for a crop on them."""
    (width, step_x), (height, step_y) = _axes(src)
    crop = geometry.crop
    invalid: list[str] = []
    for name, near, far, size, step, applied in (
        ("horizontal", rect.left, rect.right, width, step_x, (crop.left, crop.right)),
        ("vertical", rect.top, rect.bottom, height, step_y, (crop.top, crop.bottom)),
    ):
        snapped = (near // step * step, far // step * step)
        if near + far >= size or (any(snapped) and applied == (0, 0)):
            invalid.append(name)
    return invalid


@job_rule(
    "dimensions",
    "dimensions.crop_invalid",
    "dimensions.crop_snapped",
    "dimensions.crop_not_detected",
    "dimensions.crop_missing",
)
def crop(ctx: JobContext) -> Iterator[ValidationIssue]:
    geometry, src = ctx.geometry, ctx.source_geometry
    if geometry is None or src is None:
        return
    settings = ctx.job.dimensions.crop
    no_crop = fix("Do not crop", replace("dimensions.crop.mode", "none"), target=ctx.target)
    if settings.mode == "none":
        return
    rect = settings.rect
    if rect is None:
        if settings.mode == "manual":
            yield warning(
                "dimensions.crop_missing",
                "dimensions.crop.rect",
                "Manual crop has no values: no crop is applied.",
                no_crop,
            )
        else:
            # No detected rectangle is not a user error, so this is info, not a warning.
            name = "automatic" if settings.mode == "auto" else "conservative"
            yield info(
                "dimensions.crop_not_detected",
                "dimensions.crop",
                f"Crop detection did not run for this job, so {name} crop has no values: "
                "the picture is not cropped.",
                no_crop,
            )
        return
    invalid = _invalid_axes(rect, geometry, src)
    if invalid:
        reset: dict[str, int] = {}
        if "horizontal" in invalid:
            reset |= {"left": 0, "right": 0}
        if "vertical" in invalid:
            reset |= {"top": 0, "bottom": 0}
        notes = _notes(geometry, "Crop ", "The width", "The height")
        detail = " ".join(n for n in notes if "no " in n and "crop is applied" in n)
        yield error(
            "dimensions.crop_invalid",
            "dimensions.crop.rect",
            detail or f"The {' and '.join(invalid)} crop is not valid: it is not applied.",
            fix(
                f"Remove the {' and '.join(invalid)} crop",
                *(replace(f"dimensions.crop.rect.{edge}", value) for edge, value in reset.items()),
                target=ctx.target,
            ),
        )
        return
    if geometry.crop != rect:
        notes = [n for n in _notes(geometry, "Crop ") if "→" in n]
        yield info(
            "dimensions.crop_snapped",
            "dimensions.crop.rect",
            " ".join(notes) or "The crop was changed to fit the chroma grid.",
            fix(
                "Use the adjusted crop",
                replace("dimensions.crop.rect", geometry.crop.model_dump(mode="json")),
                target=ctx.target,
            ),
        )


def _with(settings: DimensionSettings, **changes: object) -> DimensionSettings:
    return settings.model_copy(update=changes)


@job_rule("dimensions", "dimensions.upscaled", "dimensions.outside_box")
def size(ctx: JobContext) -> Iterator[ValidationIssue]:
    geometry, src = ctx.geometry, ctx.source_geometry
    if geometry is None or src is None:
        return
    dims = ctx.job.dimensions
    if geometry.upscaled:
        fixes: list[Fix] = []
        if (
            dims.allow_upscaling
            and not compute_geometry(src, _with(dims, allow_upscaling=False)).upscaled
        ):
            fixes.append(
                fix(
                    "Turn off upscaling",
                    replace("dimensions.allow_upscaling", False),
                    target=ctx.target,
                )
            )
        notes = _notes(geometry, "Upscaled", "One modulus step")
        yield warning(
            "dimensions.upscaled",
            "dimensions.size",
            " ".join(notes)
            or f"The output ({geometry.scaled_width}{TIMES}{geometry.scaled_height}) is "
            "larger than the picture: it is upscaled.",
            *fixes,
        )
    if isinstance(dims.size, FitWithin):
        box = oriented_box(
            dims.size.width,
            dims.size.height,
            Fraction(geometry.scaled_width, geometry.scaled_height),
        )
        if geometry.scaled_width > box[0] or geometry.scaled_height > box[1]:
            fixes = []
            if dims.modulus != 2:
                smaller = compute_geometry(src, _with(dims, modulus=2))
                if smaller.scaled_width <= box[0] and smaller.scaled_height <= box[1]:
                    fixes.append(
                        fix("Use modulus 2", replace("dimensions.modulus", 2), target=ctx.target)
                    )
            yield warning(
                "dimensions.outside_box",
                "dimensions.size",
                f"The output ({geometry.scaled_width}{TIMES}{geometry.scaled_height}) does not fit "
                f"within {box[0]}{TIMES}{box[1]}: one modulus step ({dims.modulus}) is larger than "
                "the box allows.",
                *fixes,
            )


def _custom_par_issue(dims: DimensionSettings, target: FixTarget) -> list[ValidationIssue]:
    par = dims.custom_par
    if dims.pixel_aspect != "custom" or (par is not None and par.num > 0):
        return []
    return [
        error(
            "dimensions.custom_par_missing",
            "dimensions.custom_par",
            "Custom pixel aspect is chosen, but no valid pixel aspect is set: square pixels "
            "would be used.",
            fix(
                "Use square pixels",
                replace("dimensions.pixel_aspect", "square"),
                target=target,
            ),
        )
    ]


@job_rule("dimensions", "dimensions.custom_par_missing")
def custom_par(ctx: JobContext) -> list[ValidationIssue]:
    if ctx.job.video.passthrough:
        return []
    return _custom_par_issue(ctx.job.dimensions, ctx.target)


@template_rule("dimensions", "dimensions.custom_par_missing")
def template_custom_par(ctx: TemplateContext) -> list[ValidationIssue]:
    if ctx.template.video.passthrough:
        return []
    return _custom_par_issue(ctx.template.dimensions, ctx.target)
