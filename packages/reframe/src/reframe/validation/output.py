"""Output rules (05 §C-8 "Output"): no output path, folder not writable, output = source, name
collision (03 §Queue: ask, auto-rename or overwrite), extension, and free disk space.

The path checks (:func:`output_path_issues`) work on :class:`~pathlib.PurePath`, so they are
tested with Windows paths (drive roots, a case-insensitive file system) on Linux. Every read
goes through the :class:`~reframe.validation.fs.FileSystemView`.

Free disk space is estimated only when the size is known in advance: average bitrate, and
video passthrough (03: "estimate in bitrate mode"). Constant quality has no estimate.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path, PurePath

from reframe.definitions import ContainerDef
from reframe.models.issues import Fix, FixTarget, ValidationIssue
from reframe.models.job import AverageBitrate
from reframe.models.settings import CollisionPolicy
from reframe.validation.common import error, fix, info, replace, warning
from reframe.validation.context import JobContext
from reframe.validation.fs import FileSystemView
from reframe.validation.range import range_duration
from reframe.validation.registry import job_rule
from reframe.validation.tracks import encoded_audio, passthru_copies, track_encoder, track_stream

__all__ = [
    "MUX_OVERHEAD",
    "estimate_output_bytes",
    "existing_ancestor",
    "next_free_path",
    "output_path_issues",
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


def _size(value: float) -> str:
    gigabytes = value / 1e9
    return f"{gigabytes:.1f} GB" if gigabytes >= 1 else f"{value / 1e6:.0f} MB"


def output_path_issues(
    path: PurePath,
    source: PurePath,
    fs: FileSystemView,
    *,
    container: ContainerDef | None,
    collision: CollisionPolicy,
    target: FixTarget = "job",
) -> list[ValidationIssue]:
    """The checks of one output path (see the module doc)."""
    issues: list[ValidationIssue] = []

    def save_as(candidate: PurePath) -> Fix:
        return fix(
            f"Save as {candidate.name}", replace("output.path", str(candidate)), target=target
        )

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
    if fs.same_file(path, source):
        issues.append(
            error(
                "output.same_as_source",
                "output.path",
                f"The output {path} is the source file: it would be overwritten while it is read.",
                save_as(next_free_path(path, fs)),
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


@job_rule("output", *CODES)
def output_path(ctx: JobContext) -> Iterator[ValidationIssue]:
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
    if path is None:
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
