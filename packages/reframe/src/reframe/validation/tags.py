"""Tag rules: the template errors that ``jobs/tags`` shows, and values that FFmpeg's command
line cannot carry. Each tag is one ``-metadata key=value`` argument."""

from __future__ import annotations

from collections.abc import Iterator

from reframe.command.metadata import TAG_KEYS, render_tag, tag_template_issues
from reframe.models.issues import ValidationIssue
from reframe.validation.common import error, fix, replace
from reframe.validation.context import JobContext, TemplateContext
from reframe.validation.naming import TEMPLATE_CODES
from reframe.validation.registry import job_rule, template_rule

__all__ = ["MAX_TAG_LENGTH"]

#: Characters of a written tag. Linux takes 131 071 bytes in one argument and Windows 32 767
#: characters in the whole command line, so all eight tags at this length still fit.
MAX_TAG_LENGTH = 3000
LABELS = {
    "title": "Title",
    "actors": "Actors",
    "director": "Director",
    "release_date": "Release date",
    "comment": "Comment",
    "genre": "Genre",
    "description": "Description",
    "plot": "Plot",
}
_TEMPLATE_ERRORS = tuple(
    code for code in TEMPLATE_CODES if code not in ("naming.empty_template", "naming.backslash")
)


@job_rule("metadata", *_TEMPLATE_ERRORS, "metadata.nul_character", "metadata.tag_too_long")
def tags(ctx: JobContext) -> Iterator[ValidationIssue]:
    """A template error is written as typed or as an empty value, so it blocks the job, as a
    NUL character (no process argument can hold one) and an over-long value do."""
    yield from tag_template_issues(ctx.job.tags, target=ctx.target)
    for name in TAG_KEYS:
        template = getattr(ctx.job.tags, name)
        if template is None:
            continue
        at, label = f"tags.{name}", LABELS[name]
        value = render_tag(
            template, ctx.job, ctx.source, options=ctx.naming, output_size=ctx.output_size,
            now=None, definitions=ctx.definitions,
        )  # fmt: skip
        if "\0" in value:
            fixes = []
            if "\0" in template:
                fixes.append(
                    fix(
                        "Remove the NUL characters",
                        replace(at, template.replace("\0", "")),
                        target=ctx.target,
                    )
                )
            yield error(
                "metadata.nul_character",
                at,
                f"The {label} tag has a NUL character, which FFmpeg cannot be given: the job "
                "would fail.",
                *fixes,
            )
        elif len(value) > MAX_TAG_LENGTH:
            yield error(
                "metadata.tag_too_long",
                at,
                f"The {label} tag is {len(value)} characters long; a tag can have at most "
                f"{MAX_TAG_LENGTH}, or the FFmpeg command line would be too long. Shorten it.",
            )


@template_rule("metadata", *_TEMPLATE_ERRORS)
def template_tags(ctx: TemplateContext) -> list[ValidationIssue]:
    """A preset's tag templates, which every job made from it gets."""
    return tag_template_issues(ctx.template.tags, target=ctx.target)
