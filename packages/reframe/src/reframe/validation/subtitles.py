"""Subtitle rules. Forced only needs a burned-in PGS or VobSub track: a stream copy does not
decode, so FFmpeg's ``forced_subs_only`` decoder option changes nothing there."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path, PurePath

from reframe.models.issues import Fix, ValidationIssue
from reframe.validation.common import (
    containers_for,
    error,
    fix,
    remove,
    replace,
)
from reframe.validation.context import JobContext
from reframe.validation.registry import job_rule
from reframe.validation.tracks import (
    EXTERNAL_FORMATS,
    FORCED_ONLY_CODECS,
    subtitle_input,
    switch_container,
)


def _drop(ctx: JobContext, index: int) -> Fix:
    return fix("Remove this subtitle track", remove(f"subtitles[{index}]"), target=ctx.target)


@job_rule(
    "subtitles", "subtitle.source_missing", "subtitle.external_missing", "subtitle.external_unknown"
)
def sources(ctx: JobContext) -> Iterator[ValidationIssue]:
    for index, track in enumerate(ctx.job.subtitles):
        if isinstance(track.source, int):
            if track.source not in ctx.subtitle_streams:
                yield error(
                    "subtitle.source_missing",
                    f"subtitles[{index}].source",
                    f"Subtitle track {index + 1} reads stream {track.source}, which is not a "
                    "subtitle track of the source.",
                    _drop(ctx, index),
                )
        elif not ctx.fs.exists(Path(track.source.path)):
            yield error(
                "subtitle.external_missing",
                f"subtitles[{index}].source.path",
                f"The subtitle file {track.source.path} does not exist.",
                _drop(ctx, index),
            )
        elif PurePath(track.source.path).suffix.lower() not in EXTERNAL_FORMATS:
            known = ", ".join(EXTERNAL_FORMATS)
            yield error(
                "subtitle.external_unknown",
                f"subtitles[{index}].source.path",
                f"The subtitle file {PurePath(track.source.path).name} has a type Reframe "
                f"cannot read: use a {known} file.",
                _drop(ctx, index),
            )


@job_rule("subtitles", "subtitle.burn_multiple", "subtitle.burn_passthrough")
def burn_in(ctx: JobContext) -> Iterator[ValidationIssue]:
    burned = [i for i, track in enumerate(ctx.job.subtitles) if track.action == "burn"]
    if not burned:
        return
    if ctx.job.video.passthrough:
        for index in burned:
            yield error(
                "subtitle.burn_passthrough",
                f"subtitles[{index}].action",
                "Subtitles cannot be burned in when the video is passed through.",
                fix(
                    "Copy the track",
                    replace(f"subtitles[{index}].action", "copy"),
                    target=ctx.target,
                ),
                fix("Encode the video", replace("video.passthrough", False), target=ctx.target),
            )
        return
    for index in burned[1:]:
        yield error(
            "subtitle.burn_multiple",
            f"subtitles[{index}].action",
            f"Only one subtitle track can be burned in; track {burned[0] + 1} already is.",
            fix("Copy the track", replace(f"subtitles[{index}].action", "copy"), target=ctx.target),
            _drop(ctx, index),
        )


@job_rule("subtitles", "subtitle.bitmap_unsupported")
def bitmap_copy(ctx: JobContext) -> Iterator[ValidationIssue]:
    """A copied bitmap track the container cannot hold. The fixes are burn in, another
    container, or drop."""
    container = ctx.container
    if container is None:
        return
    can_burn = not ctx.job.video.passthrough and not any(
        track.action == "burn" for track in ctx.job.subtitles
    )
    for index, track in enumerate(ctx.job.subtitles):
        source = subtitle_input(ctx, track)
        if (
            track.action != "copy"
            or source is None
            or source.kind != "bitmap"
            or source.codec is None
            or container.subtitles.can_copy(source.codec)
        ):
            continue
        fixes: list[Fix] = []
        if can_burn:
            fixes.append(
                fix("Burn it in", replace(f"subtitles[{index}].action", "burn"), target=ctx.target)
            )
        fixes.extend(
            switch_container(
                ctx, containers_for(ctx.definitions, "subtitles", source.codec, copy=True)
            )
        )
        fixes.append(_drop(ctx, index))
        yield error(
            "subtitle.bitmap_unsupported",
            f"subtitles[{index}].action",
            f"{container.label} cannot hold the bitmap subtitles of {source.label}.",
            *fixes,
        )


@job_rule("subtitles", "subtitle.convert_bitmap", "subtitle.convert_target_missing")
def conversions(ctx: JobContext) -> Iterator[ValidationIssue]:
    container = ctx.container
    for index, track in enumerate(ctx.job.subtitles):
        if track.action != "convert":
            continue
        source = subtitle_input(ctx, track)
        if source is not None and source.kind == "bitmap":
            fixes: list[Fix] = []
            if (
                container is not None
                and source.codec
                and container.subtitles.can_copy(source.codec)
            ):
                fixes.append(
                    fix(
                        "Copy the track",
                        replace(f"subtitles[{index}].action", "copy"),
                        target=ctx.target,
                    )
                )
            if not ctx.job.video.passthrough and not any(
                other.action == "burn" for other in ctx.job.subtitles
            ):
                fixes.append(
                    fix(
                        "Burn it in",
                        replace(f"subtitles[{index}].action", "burn"),
                        target=ctx.target,
                    )
                )
            fixes.append(_drop(ctx, index))
            yield error(
                "subtitle.convert_bitmap",
                f"subtitles[{index}].action",
                f"The bitmap subtitles of {source.label} cannot be converted to text "
                "(FFmpeg has no OCR).",
                *fixes,
            )
        elif track.convert_to is None:
            fixes = []
            if container is not None and container.text_subtitle_target is not None:
                fixes.append(
                    fix(
                        f"Convert to {container.text_subtitle_target}",
                        replace(f"subtitles[{index}].convert_to", container.text_subtitle_target),
                        target=ctx.target,
                    )
                )
            yield error(
                "subtitle.convert_target_missing",
                f"subtitles[{index}].convert_to",
                f"Subtitle track {index + 1} is converted, but no format is chosen.",
                *fixes,
            )


@job_rule("subtitles", "subtitle.forced_only_unsupported")
def forced_only(ctx: JobContext) -> Iterator[ValidationIssue]:
    for index, track in enumerate(ctx.job.subtitles):
        if not track.forced_only:
            continue
        source = subtitle_input(ctx, track)
        if source is None:
            continue  # subtitle.source_missing
        if track.action != "burn":
            reason = (
                "forced-only works only when the track is burned in (a copied or converted "
                "track keeps every event)"
            )
        elif source.codec not in FORCED_ONLY_CODECS:
            reason = f"forced-only needs PGS or VobSub subtitles; {source.label} keeps every event"
        else:
            continue
        yield error(
            "subtitle.forced_only_unsupported",
            f"subtitles[{index}].forced_only",
            f"Subtitle track {index + 1}: {reason}.",
            fix(
                "Keep all events",
                replace(f"subtitles[{index}].forced_only", False),
                target=ctx.target,
            ),
        )
