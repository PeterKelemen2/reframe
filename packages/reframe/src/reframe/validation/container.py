"""Container rules: a codec the container cannot hold, and track flags it cannot write.

A passthru audio track that the container cannot hold is encoded with the fallback encoder, so
only that encoder's codec is checked here (``audio.passthru_fallback``, info).
"""

from __future__ import annotations

from collections.abc import Iterator

from reframe.definitions import ContainerDef, Definitions
from reframe.definitions.models import TRACK_FLAGS
from reframe.models.capabilities import CapabilitySnapshot
from reframe.models.issues import Fix, ValidationIssue
from reframe.models.job import AudioOutputTrack, Container, TrackMetadata
from reframe.models.media import AudioStream
from reframe.validation.common import (
    SwitchContainer,
    containers_for,
    error,
    fix,
    remove,
    replace,
    switch_container_fixes,
    usable_encoder,
    warning,
)
from reframe.validation.context import JobContext, TemplateContext
from reframe.validation.encoder import template_audio_encoder_ids
from reframe.validation.registry import job_rule, template_rule
from reframe.validation.tracks import (
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
    drop: str | None,
    track: AudioOutputTrack | None = None,
    stream: AudioStream | None = None,
    switch: SwitchContainer | None = None,
) -> list[ValidationIssue]:
    """``container.codec_unsupported`` for the audio encoder at ``path``."""
    definitions = ctx.definitions
    container = definitions.containers.get(container_id)
    encoder = definitions.audio_encoders.get(encoder_id)
    if container is None or encoder is None or encoder.codec in container.audio.encode:
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
        fixes.append(fix("Remove this audio track", remove(drop)))
    return [
        error(
            UNSUPPORTED,
            path,
            f"{container.label} cannot hold {encoder.label} audio ({encoder_id}).",
            *fixes,
        )
    ]


@job_rule("container", "container.unknown")
def known_container(ctx: JobContext) -> list[ValidationIssue]:
    """A container the definitions do not have (a hand-edited or newer job file)."""
    if ctx.container is not None:
        return []
    current = ctx.job.output.container
    return [
        error(
            "container.unknown",
            "output.container",
            f"Unknown container {current!r}.",
            *switch_container(ctx, list(ctx.definitions.containers)),
        )
    ]


@job_rule("container", UNSUPPORTED)
def video_codec(ctx: JobContext) -> list[ValidationIssue]:
    stream = ctx.video_stream
    return video_container_issues(
        ctx.job.video,
        ctx.job.output.container,
        ctx.caps,
        ctx.definitions,
        source_codec=stream.codec if stream is not None else None,
        switch=lambda allowed: switch_container(ctx, allowed),
        passthrough_known=stream is not None,
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
            drop=f"audio[{index}]",
            track=track,
            stream=track_stream(ctx, track),
            switch=lambda allowed: switch_container(ctx, allowed),
        )


@job_rule("container", UNSUPPORTED)
def subtitle_codecs(ctx: JobContext) -> Iterator[ValidationIssue]:
    """Text subtitles: a converted format the container cannot hold, or a copied text format
    it can neither hold nor convert automatically. (Bitmap: ``subtitle.bitmap_unsupported``.)"""
    container = ctx.container
    if container is None:
        return
    for index, track in enumerate(ctx.job.subtitles):
        drop = fix("Remove this subtitle track", remove(f"subtitles[{index}]"))
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


def _metadata_blocks(ctx: JobContext) -> Iterator[tuple[str, TrackMetadata]]:
    yield "video.metadata", ctx.job.video.metadata
    for index, audio in enumerate(ctx.job.audio):
        yield f"audio[{index}].metadata", audio.metadata
    for index, subtitle in enumerate(ctx.job.subtitles):
        if subtitle.action != "burn":
            yield f"subtitles[{index}].metadata", subtitle.metadata


@job_rule("container", "container.flag_unsupported")
def track_flags(ctx: JobContext) -> Iterator[ValidationIssue]:
    """A flag the muxer cannot write is lost, so it is a warning."""
    container = ctx.container
    if container is None:
        return
    for prefix, metadata in _metadata_blocks(ctx):
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


@template_rule("container", UNSUPPORTED)
def template_video_codec(ctx: TemplateContext) -> list[ValidationIssue]:
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
