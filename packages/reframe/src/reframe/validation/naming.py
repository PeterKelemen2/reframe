"""Naming rules (C-16's issues): the job's name through ``resolve_output_name`` (template,
manual name, per-file overrides, output folder), and a template's naming options through
``check_template``."""

from __future__ import annotations

from collections.abc import Iterator

from reframe.models.issues import ValidationIssue
from reframe.naming import check_template
from reframe.validation.common import warning
from reframe.validation.context import JobContext, TemplateContext
from reframe.validation.registry import job_rule, template_rule

TEMPLATE_CODES = (
    "naming.empty_template",
    "naming.template_syntax",
    "naming.unknown_variable",
    "naming.bad_format_spec",
    "naming.backslash",
)
JOB_CODES = (
    *TEMPLATE_CODES,
    "naming.bad_override",
    "naming.unknown_override",
    "naming.manual_name_empty",
    "naming.no_output_folder",
)


@job_rule("naming", *JOB_CODES)
def output_name(ctx: JobContext) -> list[ValidationIssue]:
    return list(ctx.name.issues)


@template_rule("naming", *TEMPLATE_CODES, "naming.no_output_folder")
def template_naming(ctx: TemplateContext) -> Iterator[ValidationIssue]:
    naming = ctx.template.naming
    if naming is None:
        return
    for field in ("movie_template", "episode_template"):
        yield from check_template(
            getattr(naming, field), field=f"naming.{field}", target=ctx.target
        )
    if naming.output_folder_mode == "fixed" and naming.output_folder is None:
        yield warning(
            "naming.no_output_folder",
            "naming.output_folder",
            "The output folder is set to a fixed folder, but no folder is chosen.",
        )
