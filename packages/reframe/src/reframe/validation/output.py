"""Output rules (05 §C-8 "Output"): no output path, folder not writable, output = source, name
collision (03 §Queue: ask, auto-rename or overwrite), extension, and free disk space.

The path checks (:func:`output_path_issues`) work on :class:`~pathlib.PurePath`, so they are
tested with Windows paths (drive roots, a case-insensitive file system) on Linux. Every read
goes through the :class:`~reframe.validation.fs.FileSystemView`.

Free disk space is estimated only when the size is known in advance: average bitrate, and
video passthrough (03: "estimate in bitrate mode"). Constant quality has no estimate.

A metadata edit in place (job type ``metadata_edit``, C-13) writes no new file: its output is
the source by design, so the path and disk-space rules do not apply to it
(:func:`is_metadata_edit`; its own rules are in :mod:`reframe.validation.inplace`).
"""

from __future__ import annotations

import ntpath
import posixpath
from collections.abc import Iterator
from pathlib import Path, PurePath, PureWindowsPath
from typing import cast

from reframe.command import job_type, partial_path
from reframe.command.video import pass_log_files
from reframe.definitions import ContainerDef
from reframe.models.issues import Fix, FixTarget, ValidationIssue
from reframe.models.job import AverageBitrate
from reframe.models.settings import CollisionPolicy
from reframe.naming.sanitize import (
    MAX_PART_BYTES,
    Piece,
    is_reserved,
    replace_forbidden,
    sanitize_segments,
)
from reframe.validation.common import error, fix, info, replace, warning
from reframe.validation.context import JobContext
from reframe.validation.fs import FileSystemView, has_nul
from reframe.validation.range import range_duration
from reframe.validation.registry import job_rule
from reframe.validation.tracks import encoded_audio, passthru_copies, track_encoder, track_stream

__all__ = [
    "MUX_OVERHEAD",
    "estimate_output_bytes",
    "existing_ancestor",
    "free_of_source",
    "is_metadata_edit",
    "name_issues",
    "next_free_path",
    "output_path_issues",
    "source_clash",
    "written_paths",
]

#: Container overhead added to the stream bitrates of the estimate.
MUX_OVERHEAD = 1.02
CODES = (
    "output.no_path",
    "output.same_as_source",
    "output.is_folder",
    "output.exists",
    "output.renamed",
    "output.overwrite",
    "output.extension_mismatch",
    "output.folder_missing",
    "output.not_writable",
    "output.name_too_long",
    "output.name_not_portable",
)


def next_free_path[P: PurePath](path: P, fs: FileSystemView, *, limit: int = 9999) -> P:
    """``Name (1).mkv``, ``Name (2).mkv``, … : the first name that does not exist. (The queue's
    auto-rename, C-11, should use the same scheme.)"""
    for number in range(1, limit + 1):
        candidate = path.with_name(f"{path.stem} ({number}){path.suffix}")
        if not fs.exists(candidate):
            return candidate
    return path.with_name(f"{path.stem} ({limit + 1}){path.suffix}")


def existing_ancestor(path: PurePath, fs: FileSystemView) -> PurePath | None:
    """``path`` or its nearest existing parent; ``None`` when not even the root (a drive that
    is not connected, ``E:\\``) exists."""
    current = path
    while True:
        if fs.exists(current):
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def written_paths[P: PurePath](path: P) -> list[P]:
    """Every file a job with the output ``path`` writes, and the queue renames or removes:
    the output, the partial file (``Movie.part.mkv``), the FFMETADATA chapters file, and the
    2-pass statistics files of x264 and x265. Named by the command builder's own functions
    (decision 0027 item 5)."""
    final = cast(Path, path)
    found = [final, partial_path(final), partial_path(final, ".chapters.txt")]
    passlog = partial_path(final, ".passlog")
    found += pass_log_files(passlog, stats_param=True)
    found += pass_log_files(passlog, stats_param=False)
    return cast(list[P], found)


def _same_name(a: PurePath, b: PurePath) -> bool:
    """The same path after ``.``/``..`` and separators are normalised; Windows paths also
    ignore case. (A case-insensitive POSIX file system, APFS, is found by ``fs.same_file``:
    a clashing name always exists, as it is the source.)"""
    if isinstance(a, PureWindowsPath):
        return ntpath.normcase(ntpath.normpath(str(a))) == ntpath.normcase(ntpath.normpath(str(b)))
    return posixpath.normpath(str(a)) == posixpath.normpath(str(b))


def source_clash(path: PurePath, source: PurePath, fs: FileSystemView) -> PurePath | None:
    """The first file the job writes (:func:`written_paths`) that is the source: the same
    file through a link or another spelling (``fs.same_file``), or the same normalised
    name."""
    for candidate in written_paths(path):
        if _same_name(candidate, source) or fs.same_file(candidate, source):
            return candidate
    return None


def free_of_source(path: PurePath, source: PurePath, fs: FileSystemView) -> PurePath:
    """``Name (1).mkv``, … : the first free name whose written files are not the source."""
    candidate = path
    for _ in range(100):
        candidate = next_free_path(candidate, fs)
        if source_clash(candidate, source, fs) is None:
            return candidate
    return candidate  # pragma: no cover - a source cannot clash with 100 names


def _safe_name(path: PurePath) -> str:
    """C-16's safe form of the file name (forbidden characters, reserved names, the 255-byte
    limit with room for ``.part``)."""
    extension = path.suffix.lstrip(".")
    stem = path.name[: -len(path.suffix)] if path.suffix else path.name
    parts, _ = sanitize_segments([[Piece(stem)]], extension=extension, fallback=stem)
    return parts[-1]


def name_issues(path: PurePath, *, target: FixTarget = "job") -> list[ValidationIssue]:
    """A manual output path checked against C-16's file-name rules (``reframe.naming``):
    a path part longer than 255 bytes (the file name with the ``.part`` the queue adds) is an
    error on every OS; a reserved Windows name (``CON.mkv``) or a character Windows does not
    allow is an error for a Windows path and a warning elsewhere (the file may move)."""
    issues: list[ValidationIssue] = []
    safe = _safe_name(path)
    fixes = [
        fix(f"Save as {safe}", replace("output.path", str(path.with_name(safe))), target=target)
    ]
    partial = partial_path(cast(Path, path)).name
    too_long = [p for p in path.parent.parts if len(p.encode("utf-8")) > MAX_PART_BYTES]
    if too_long or len(partial.encode("utf-8")) > MAX_PART_BYTES:
        what = "a folder name" if too_long else f"the partial file name {partial}"
        issues.append(
            error(
                "output.name_too_long",
                "output.path",
                f"The output path has {what} longer than {MAX_PART_BYTES} bytes: the file "
                "cannot be created.",
                *(fixes if not too_long else []),
            )
        )
        return issues
    forbidden = replace_forbidden(path.name)[0] != path.name
    if is_reserved(path.name) or forbidden:
        why = (
            "a reserved device name on Windows"
            if is_reserved(path.name)
            else "characters that Windows does not allow"
        )
        make = error if isinstance(path, PureWindowsPath) else warning
        issues.append(
            make(
                "output.name_not_portable",
                "output.path",
                f"The file name {path.name} has {why}.",
                *fixes,
            )
        )
    return issues


def _size(value: float) -> str:
    gigabytes = value / 1e9
    return f"{gigabytes:.1f} GB" if gigabytes >= 1 else f"{value / 1e6:.0f} MB"


def _nul_issue(path: PurePath, target: FixTarget) -> ValidationIssue:
    """``output.not_writable`` for a path with a NUL character (only the API can send one):
    no file system allows it, so no other check applies (final review RN, decision 0016).
    A NUL in the file name gets C-16's safe name as a fix; one in a folder name gets none
    (without it the path names another folder)."""
    shown = str(path).replace("\0", "\\0")
    fixes: list[Fix] = []
    safe = _safe_name(path)
    if not has_nul(path.parent) and safe and not has_nul(safe):
        fixes.append(
            fix(f"Save as {safe}", replace("output.path", str(path.with_name(safe))), target=target)
        )
    return error(
        "output.not_writable",
        "output.path",
        f"The output path {shown} has a NUL character, which no file system allows: the file "
        "cannot be created. Correct the path.",
        *fixes,
    )


def output_path_issues(
    path: PurePath,
    source: PurePath,
    fs: FileSystemView,
    *,
    container: ContainerDef | None,
    collision: CollisionPolicy,
    target: FixTarget = "job",
) -> list[ValidationIssue]:
    """The checks of one output path (see the module doc). A path with a NUL character is
    one error and no file-system read."""
    issues: list[ValidationIssue] = []

    def save_as(candidate: PurePath) -> Fix:
        return fix(
            f"Save as {candidate.name}", replace("output.path", str(candidate)), target=target
        )

    if has_nul(path):
        return [_nul_issue(path, target)]
    if container is not None and path.suffix.lower() not in container.extensions:
        default = container.extensions[0]
        issues.append(
            warning(
                "output.extension_mismatch",
                "output.path",
                f"{path.name} does not have a {container.label} extension "
                f"({', '.join(container.extensions)}).",
                save_as(path.with_suffix(default)),
            )
        )
    issues.extend(name_issues(path, target=target))
    clash = source_clash(path, source, fs)
    if clash is not None:
        what = "output" if clash == path else "file written during the encode"
        issues.append(
            error(
                "output.same_as_source",
                "output.path",
                f"The {what} {clash} is the source file: it would be overwritten while it is "
                "read, and the queue removes its temporary files.",
                save_as(free_of_source(path, source, fs)),
            )
        )
        return issues

    folder = existing_ancestor(path.parent, fs)
    next_to_source = source.parent / path.name
    fixes: list[Fix] = []
    if (
        next_to_source.parent != path.parent
        and fs.is_dir(source.parent)
        and fs.writable_dir(source.parent)
    ):
        if fs.exists(next_to_source):
            next_to_source = next_free_path(next_to_source, fs)
        fixes.append(
            fix(
                "Save next to the source",
                replace("output.path", str(next_to_source)),
                target=target,
            )
        )
    if folder is None:
        top = path.parents[-1] if len(path.parents) else path
        issues.append(
            error(
                "output.folder_missing",
                "output.path",
                f"The output folder {path.parent} cannot be created: {top} does not exist (is "
                "the drive connected?).",
                *fixes,
            )
        )
        return issues
    if not fs.is_dir(folder):
        issues.append(
            error(
                "output.not_writable",
                "output.path",
                f"The output folder cannot be created: {folder} is a file.",
                *fixes,
            )
        )
        return issues
    if not fs.writable_dir(folder):
        issues.append(
            error(
                "output.not_writable",
                "output.path",
                f"Reframe cannot write to the folder {folder}.",
                *fixes,
            )
        )
        return issues

    if not fs.exists(path):
        return issues
    free = next_free_path(path, fs)
    if fs.is_dir(path):
        issues.append(
            error(
                "output.is_folder",
                "output.path",
                f"The output {path} is a folder.",
                save_as(free),
            )
        )
    elif collision == "ask":
        issues.append(
            error(
                "output.exists",
                "output.path",
                f"{path.name} already exists.",
                save_as(free),
                fix(
                    "Always overwrite (Settings → Output)",
                    replace("output.collision", "overwrite"),
                    target="settings",
                ),
            )
        )
    elif collision == "auto_rename":
        issues.append(
            info(
                "output.renamed",
                "output.path",
                f"{path.name} already exists: the output is saved as {free.name}.",
                save_as(free),
            )
        )
    else:
        issues.append(
            warning(
                "output.overwrite",
                "output.path",
                f"{path.name} already exists and will be replaced.",
                save_as(free),
            )
        )
    return issues


def estimate_output_bytes(ctx: JobContext) -> int | None:
    """The output size, when it can be known before the encode (see the module doc)."""
    seconds = range_duration(ctx)
    if not seconds:
        return None
    video = ctx.job.video
    stream = ctx.video_stream
    if video.passthrough:
        video_bps = stream.bitrate.value if stream is not None else None
        if video_bps is None:
            size, total = ctx.source.container.size, ctx.duration
            return int(size * seconds / total) if size and total else None
    elif isinstance(video.rate_control, AverageBitrate):
        video_bps = video.rate_control.kbps * 1000
    else:
        return None
    audio_bps = 0
    for track in ctx.job.audio:
        source = track_stream(ctx, track)
        source_bps = source.bitrate.value if source is not None else None
        encoder_id = track_encoder(ctx, track)
        encoder = ctx.definitions.audio_encoders.get(encoder_id) if encoder_id else None
        if passthru_copies(ctx, track) or encoder is None or encoder.bitrate is None:
            audio_bps += source_bps or 0
        elif source is not None:
            # What the builder writes: the snapped bitrate, else the default for the layout.
            planned = encoded_audio(track, source, encoder, ctx.definitions)
            limits = encoder.bitrate.by_mixdown.get(planned.table)
            if planned.bitrate is not None:
                audio_bps += planned.bitrate * 1000
            elif limits is not None:
                audio_bps += limits.default * 1000
    return int((video_bps + audio_bps) * seconds / 8 * MUX_OVERHEAD)


def is_metadata_edit(ctx: JobContext) -> bool:
    """The job edits its source in place (job type ``metadata_edit``, C-13)."""
    if not ctx.job.output.edit_in_place:
        return False
    return job_type(ctx.job, ctx.source, definitions=ctx.definitions)[0] == "metadata_edit"


@job_rule("output", *CODES)
def output_path(ctx: JobContext) -> Iterator[ValidationIssue]:
    if is_metadata_edit(ctx):
        return  # the source is edited: no new file (reframe.validation.inplace)
    path = ctx.job.output.path
    if path is None:
        name = ctx.name.path
        fixes: list[Fix] = []
        if name is not None:
            if ctx.fs.exists(name):
                name = next_free_path(name, ctx.fs)
            fixes.append(
                fix(f"Save as {name.name}", replace("output.path", str(name)), target=ctx.target)
            )
        yield error("output.no_path", "output.path", "The output file has no name yet.", *fixes)
        return
    yield from output_path_issues(
        path,
        Path(ctx.job.source.path),
        ctx.fs,
        container=ctx.container,
        collision=ctx.settings.output.collision,
        target=ctx.target,
    )


@job_rule("output", "output.disk_space")
def disk_space(ctx: JobContext) -> Iterator[ValidationIssue]:
    path = ctx.job.output.path
    if path is None or is_metadata_edit(ctx):
        return
    folder = existing_ancestor(path.parent, ctx.fs)
    estimate = estimate_output_bytes(ctx)
    if folder is None or estimate is None:
        return
    free = ctx.fs.free_bytes(folder)
    if free is not None and estimate > free:
        yield warning(
            "output.disk_space",
            "output.path",
            f"The output needs about {_size(estimate)}, but only {_size(free)} is free on the "
            f"drive of {folder}.",
        )
