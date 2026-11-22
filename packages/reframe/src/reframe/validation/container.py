"""Container rules: a codec the container cannot hold, track flags it cannot write, and a copied
track that Align A/V start cannot pad.

A passthru audio track that the container cannot hold is encoded with the fallback encoder, so
only that encoder's codec is checked here (``audio.passthru_fallback``, info).
"""

from __future__ import annotations

from collections.abc import Iterator

from reframe.definitions import ContainerDef, Definitions
from reframe.definitions.models import TRACK_FLAGS
from reframe.models.capabilities import CapabilitySnapshot
from reframe.models.issues import Fix, ValidationIssue
from reframe.models.job import AudioOutputTrack, Container
from reframe.models.media import AudioStream
from reframe.validation.common import (
    SwitchContainer,
    containers_for,
    drop_track,
    error,
    fix,
    info,
    replace,
    switch_container_fixes,
    usable_encoder,
    warning,
)
from reframe.validation.context import JobContext, TemplateContext
from reframe.validation.encoder import template_audio_encoder_ids
from reframe.validation.metadata import metadata_blocks
from reframe.validation.registry import job_rule, template_rule
from reframe.validation.tracks import (
    passthru_copies,
    subtitle_input,
    switch_audio_encoder,
    switch_container,
    track_encoder,
    track_stream,
)
from reframe.validation.video import video_container_issues

UNSUPPORTED = "container.codec_unsupported"
#: Encoders a "convert" fix prefers, in order (HandBrake's defaults: AAC, then the others).
_AUDIO_PREFERENCE = ("aac", "libopus", "ac3", "eac3", "flac", "libmp3lame", "libfdk_aac")


def _audio_convert_encoder(
    container: ContainerDef, caps: CapabilitySnapshot, definitions: Definitions
) -> str | None:
    ordered = [*_AUDIO_PREFERENCE, *definitions.audio_encoders]
    for encoder_id in ordered:
        encoder = definitions.audio_encoders.get(encoder_id)
        if (
            encoder is not None
            and encoder.codec in container.audio.encode
            and usable_encoder(encoder_id, caps)
        ):
            return encoder_id
    return None


def _audio_codec_issue(
    path: str,
    encoder_id: str,
    container_id: Container,
    ctx: JobContext | TemplateContext,
    *,
    drop: int | None,
    track: AudioOutputTrack | None = None,
    stream: AudioStream | None = None,
    switch: SwitchContainer | None = None,
) -> list[ValidationIssue]:
    """``container.codec_unsupported`` for the audio encoder at ``path``."""
    definitions = ctx.definitions
    container = definitions.containers[container_id]
    encoder = definitions.audio_encoders.get(encoder_id)
    if encoder is None or encoder.codec in container.audio.encode:
        return []
    fixes: list[Fix] = []
    convert = _audio_convert_encoder(container, ctx.caps, definitions)
    if convert is not None:
        ops = switch_audio_encoder(
            path, definitions.audio_encoders[convert], definitions, track=track, stream=stream
        )
        fixes.append(fix(f"Use {convert}", *ops))
    allowed = containers_for(definitions, "audio", encoder.codec)
    fixes.extend(
        switch(allowed)
        if switch is not None
        else switch_container_fixes(allowed, container_id, definitions)
    )
    if drop is not None:
        fixes.append(drop_track("audio", drop))
    return [
        error(
            UNSUPPORTED,
            path,
            f"{container.label} cannot hold {encoder.label} audio ({encoder_id}).",
            *fixes,
        )
    ]


@job_rule("container", UNSUPPORTED)
def video_codec(ctx: JobContext) -> list[ValidationIssue]:
    stream = ctx.video_stream
    if ctx.job.video.passthrough and stream is None:
        return []
    return video_container_issues(
        ctx.job.video,
        ctx.job.output.container,
        ctx.caps,
        ctx.definitions,
        source_codec=stream.codec if stream is not None else None,
        switch=lambda allowed: switch_container(ctx, allowed),
    )


@job_rule("container", UNSUPPORTED)
def audio_codecs(ctx: JobContext) -> Iterator[ValidationIssue]:
    for index, track in enumerate(ctx.job.audio):
        encoder_id = track_encoder(ctx, track)
        if encoder_id is None:
            continue
        yield from _audio_codec_issue(
            f"audio[{index}].encoder",
            encoder_id,
            ctx.job.output.container,
            ctx,
            drop=index,
            track=track,
            stream=track_stream(ctx, track),
            switch=lambda allowed: switch_container(ctx, allowed),
        )


@job_rule("container", UNSUPPORTED)
def subtitle_codecs(ctx: JobContext) -> Iterator[ValidationIssue]:
    """Text subtitles: a converted format the container cannot hold, or a copied text format
    it can neither hold nor convert automatically. (Bitmap: ``subtitle.bitmap_unsupported``.)"""
    container = ctx.container
    for index, track in enumerate(ctx.job.subtitles):
        drop = drop_track("subtitles", index)
        if track.action == "convert" and track.convert_to is not None:
            if track.convert_to in container.subtitles.encode:
                continue
            fixes: list[Fix] = []
            if container.text_subtitle_target is not None:
                fixes.append(
                    fix(
                        f"Convert to {container.text_subtitle_target}",
                        replace(f"subtitles[{index}].convert_to", container.text_subtitle_target),
                    )
                )
            fixes.extend(
                switch_container(
                    ctx, containers_for(ctx.definitions, "subtitles", track.convert_to)
                )
            )
            yield error(
                UNSUPPORTED,
                f"subtitles[{index}].convert_to",
                f"{container.label} cannot hold {track.convert_to} subtitles.",
                *fixes,
                drop,
            )
        elif track.action == "copy":
            source = subtitle_input(ctx, track)
            if (
                source is None
                or source.kind != "text"
                or source.codec is None
                or container.subtitles.can_copy(source.codec)
                or container.text_subtitle_target is not None
            ):
                continue
            yield error(
                UNSUPPORTED,
                f"subtitles[{index}].action",
                f"{container.label} cannot hold the {source.codec} subtitles of {source.label}.",
                *switch_container(
                    ctx, containers_for(ctx.definitions, "subtitles", source.codec, copy=True)
                ),
                drop,
            )


@job_rule("container", "container.flag_unsupported")
def track_flags(ctx: JobContext) -> Iterator[ValidationIssue]:
    """A flag the muxer cannot write is lost, so it is a warning."""
    container = ctx.container
    for prefix, metadata in metadata_blocks(ctx, written_only=True):
        for flag in TRACK_FLAGS:
            if not getattr(metadata, flag) or flag in container.flags:
                continue
            path = f"{prefix}.{flag}"
            clear = fix(f"Clear the {flag} flag", replace(path, False))
            label = flag.replace("_", " ")
            others = [
                c
                for c, definition in ctx.definitions.containers.items()
                if flag in definition.flags
            ]
            yield warning(
                "container.flag_unsupported",
                path,
                f"{container.label} cannot store the {label} flag: it will be lost.",
                clear,
                *switch_container(ctx, others),
            )


#: Seconds a copied stream may start after the others before Align A/V start says it stays so.
ALIGN_TOLERANCE = 0.05


@job_rule("container", "container.align_copied_track")
def align_copied_tracks(ctx: JobContext) -> Iterator[ValidationIssue]:
    """Align A/V start pads the start of what is encoded; a copied track keeps its own. Without
    a range only: after ``-ss`` the source's start times no longer apply."""
    job = ctx.job
    video = ctx.video_stream
    if not job.output.align_av_start or job.range.kind != "full" or video is None:
        return
    starts: list[float] = [] if video.start_time is None else [video.start_time]
    copied: list[tuple[str, str, float]] = []
    if job.video.passthrough and video.start_time is not None:
        copied.append(("video.passthrough", "The copied video", video.start_time))
    for index, track in enumerate(job.audio):
        stream = track_stream(ctx, track)
        if stream is None or stream.start_time is None:
            continue
        starts.append(stream.start_time)
        if passthru_copies(ctx, track):
            copied.append((f"audio[{index}].action", f"Audio track {index + 1}", stream.start_time))
    if not starts:
        return
    first = min(starts)
    for path, what, start in copied:
        late = start - first
        if late > ALIGN_TOLERANCE:
            yield info(
                "container.align_copied_track",
                path,
                f"{what} starts {late:.2f} s after the others and is copied: Align A/V start "
                "cannot pad a copied track, so it keeps that start.",
            )


@template_rule("container", UNSUPPORTED)
def template_video_codec(ctx: TemplateContext) -> list[ValidationIssue]:
    if ctx.template.video.passthrough:
        return []  # no source to check the copied codec against
    return video_container_issues(
        ctx.template.video,
        ctx.template.output.container,
        ctx.caps,
        ctx.definitions,
    )


@template_rule("container", UNSUPPORTED)
def template_audio_codecs(ctx: TemplateContext) -> Iterator[ValidationIssue]:
    for path, encoder_id in template_audio_encoder_ids(ctx):
        yield from _audio_codec_issue(
            path, encoder_id, ctx.template.output.container, ctx, drop=None
        )
