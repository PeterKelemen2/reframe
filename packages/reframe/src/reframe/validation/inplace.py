"""Rules for in-place metadata edits: Reframe changes the track metadata of an MKV source.

Edit in place (``output.edit_in_place``) needs a job that changes only metadata, with an MKV
source and output. The output rules skip the path checks of a metadata edit, since its output
is the source by design.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path, PurePath

from reframe.command.jobtype import in_place_blockers
from reframe.models.issues import Fix, ValidationIssue
from reframe.validation.common import error, fix, replace, warning
from reframe.validation.context import JobContext
from reframe.validation.fs import FileSystemView
from reframe.validation.output import free_of_source, is_metadata_edit, source_clash
from reframe.validation.registry import job_rule

__all__ = ["is_metadata_edit", "new_output_path", "source_writable", "write_new_file_fix"]


def source_writable(fs: FileSystemView, path: PurePath) -> bool:
    """The existing file ``path`` can be written (the view's
    :meth:`~reframe.validation.fs.FileSystemView.writable_file`)."""
    return fs.writable_file(path)


def _same(a: PurePath, b: PurePath, fs: FileSystemView) -> bool:
    return str(a) == str(b) or fs.same_file(a, b)


def new_output_path(ctx: JobContext) -> PurePath:
    """Where a job that stops editing in place writes its new file: the resolved output name,
    else the source's name with the container's extension, or a free name when that is the
    source."""
    source = Path(ctx.job.source.path)
    candidate: PurePath | None = ctx.name.path
    if candidate is None:
        extension = ctx.container.extensions[0] if ctx.container is not None else ".mkv"
        candidate = source.with_suffix(extension)
    if source_clash(candidate, source, ctx.fs) is not None:
        candidate = free_of_source(candidate, source, ctx.fs)
    return candidate


def write_new_file_fix(ctx: JobContext) -> Fix:
    """Edit in place off and, when the output path is missing or is the source,
    :func:`new_output_path`, so the fix never leaves ``output.same_as_source``."""
    ops = [replace("output.edit_in_place", False)]
    path = ctx.job.output.path
    source = Path(ctx.job.source.path)
    if path is None or _same(path, source, ctx.fs):
        target = new_output_path(ctx)
        ops.append(replace("output.path", str(target)))
        label = f"Write a new file ({target.name})"
    else:
        label = f"Write a new file ({path.name})"
    return fix(label, *ops, target=ctx.target)


@job_rule("output", "inplace.not_possible")
def not_possible(ctx: JobContext) -> Iterator[ValidationIssue]:
    if not ctx.job.output.edit_in_place:
        return
    blockers = in_place_blockers(ctx.job, ctx.source, definitions=ctx.definitions)
    if not blockers:
        return
    more = f" (and {len(blockers) - 1} more)" if len(blockers) > 1 else ""
    yield error(
        "inplace.not_possible",
        "output.edit_in_place",
        f"The source cannot be edited in place: {blockers[0]}{more}. Only languages, names, "
        "flags and the title of an MKV can be changed in place.",
        write_new_file_fix(ctx),
    )


@job_rule("output", "inplace.source_not_writable", "inplace.output_ignored")
def in_place_source(ctx: JobContext) -> Iterator[ValidationIssue]:
    if not is_metadata_edit(ctx):
        return
    source = Path(ctx.job.source.path)
    if not source_writable(ctx.fs, source):
        yield error(
            "inplace.source_not_writable",
            "output.edit_in_place",
            f"{source.name} cannot be written (read-only, or no permission): its metadata "
            "cannot be edited in place.",
            write_new_file_fix(ctx),
        )
    path = ctx.job.output.path
    if path is not None and not _same(path, source, ctx.fs):
        yield warning(
            "inplace.output_ignored",
            "output.path",
            f"The source {source.name} is edited in place: the output path {path} is not used.",
            fix(f"Edit {source.name}", replace("output.path", str(source)), target=ctx.target),
            fix(
                f"Write a new file ({path.name})",
                replace("output.edit_in_place", False),
                target=ctx.target,
            ),
        )
