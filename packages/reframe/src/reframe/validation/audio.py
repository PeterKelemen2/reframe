"""Audio track rules: the source stream exists, auto passthru, and the encoder's mixdowns,
bitrates (per mixdown, snapped to the allowed values) and sample rates."""

from __future__ import annotations

from collections.abc import Iterator

from reframe.definitions import AudioEncoderDef
from reframe.models.issues import ValidationIssue
from reframe.models.job import AudioOutputTrack, Mixdown
from reframe.validation.common import error, fix, info, remove, replace
from reframe.validation.context import JobContext
from reframe.validation.registry import job_rule
from reframe.validation.tracks import effective_mixdown, passthru_copies, track_encoder

_MIXDOWN_ORDER: tuple[Mixdown, ...] = ("7.1", "5.1", "dpl2", "stereo", "mono")


@job_rule("audio", "audio.source_missing")
def source_streams(ctx: JobContext) -> Iterator[ValidationIssue]:
    for index, track in enumerate(ctx.job.audio):
        stream = track.source_stream
        if stream is not None and stream in ctx.audio_streams:
            continue
        what = (
            "has no source track"
            if stream is None
            else f"reads stream {stream}, which is not an audio track of the source"
        )
        yield error(
            "audio.source_missing",
            f"audio[{index}].source_stream",
            f"Audio track {index + 1} {what}.",
            fix("Remove this audio track", remove(f"audio[{index}]"), target=ctx.target),
        )


@job_rule("audio", "audio.passthru_fallback")
def auto_passthru(ctx: JobContext) -> Iterator[ValidationIssue]:
    """03 §Audio: "Passthru falls back to an encoder when the container cannot hold the codec"
    (HandBrake's auto passthru). Info: nothing is wrong, but the track is encoded."""
    container = ctx.container
    if container is None:
        return
    for index, track in enumerate(ctx.job.audio):
        if track.action != "passthru" or passthru_copies(ctx, track):
            continue
        stream = (
            ctx.audio_streams.get(track.source_stream) if track.source_stream is not None else None
        )
        if stream is None:
            continue  # audio.source_missing
        encoder_id = track_encoder(ctx, track)
        codec = stream.display_codec or stream.codec or "this codec"
        yield info(
            "audio.passthru_fallback",
            f"audio[{index}].action",
            f"{container.label} cannot hold {codec}: audio track {index + 1} is encoded with "
            f"the fallback encoder {encoder_id} instead of passed through.",
        )


def _supported_mixdown(encoder: AudioEncoderDef, wanted: Mixdown) -> Mixdown | None:
    """The richest mixdown the encoder has that is not richer than ``wanted``."""
    start = _MIXDOWN_ORDER.index(wanted)
    return next((m for m in _MIXDOWN_ORDER[start:] if m in encoder.mixdowns), None)


def _label(ctx: JobContext, mixdown: Mixdown) -> str:
    definition = ctx.definitions.mixdowns.get(mixdown)
    return definition.label if definition is not None else mixdown


def _encoded_tracks(
    ctx: JobContext,
) -> Iterator[tuple[int, AudioOutputTrack, AudioEncoderDef, Mixdown | None]]:
    for index, track in enumerate(ctx.job.audio):
        encoder_id = track_encoder(ctx, track)
        encoder = ctx.definitions.audio_encoders.get(encoder_id) if encoder_id else None
        if encoder is None:
            continue
        stream = (
            ctx.audio_streams.get(track.source_stream) if track.source_stream is not None else None
        )
        yield index, track, encoder, effective_mixdown(track, stream)


@job_rule("audio", "audio.mixdown_unsupported")
def mixdowns(ctx: JobContext) -> Iterator[ValidationIssue]:
    for index, track, encoder, mixdown in _encoded_tracks(ctx):
        if mixdown is None or mixdown in encoder.mixdowns:
            continue
        label = _label(ctx, mixdown)
        what = f"the source layout ({label})" if track.mixdown is None else label
        fixes = []
        best = _supported_mixdown(encoder, mixdown)
        if best is not None:
            fixes.append(
                fix(
                    f"Mix down to {_label(ctx, best)}",
                    replace(f"audio[{index}].mixdown", best),
                    target=ctx.target,
                )
            )
        yield error(
            "audio.mixdown_unsupported",
            f"audio[{index}].mixdown",
            f"{encoder.label} ({encoder.id}) cannot encode {what}.",
            *fixes,
        )


@job_rule("audio", "audio.bitrate_out_of_range")
def bitrates(ctx: JobContext) -> Iterator[ValidationIssue]:
    """A bitrate outside the encoder's range for the mixdown, or not one of its fixed steps
    (AC-3, E-AC-3, MP3). The fix snaps it (down, as HandBrake does)."""
    for index, track, encoder, mixdown in _encoded_tracks(ctx):
        if track.bitrate is None or encoder.bitrate is None or mixdown is None:
            continue
        snapped = encoder.bitrate.snap(track.bitrate, mixdown)
        if snapped is None or snapped == track.bitrate:
            continue  # an unsupported mixdown is audio.mixdown_unsupported
        limits = encoder.bitrate.by_mixdown[mixdown]
        steps = encoder.bitrate.values(mixdown)
        allowed = (
            f"one of {', '.join(str(s) for s in steps)} kb/s"
            if steps is not None
            else f"{limits.min} to {limits.max} kb/s"
        )
        yield error(
            "audio.bitrate_out_of_range",
            f"audio[{index}].bitrate",
            f"{track.bitrate} kb/s is not a valid {encoder.label} bitrate for {mixdown}: "
            f"use {allowed}.",
            fix(
                f"Use {snapped} kb/s",
                replace(f"audio[{index}].bitrate", snapped),
                target=ctx.target,
            ),
        )


@job_rule("audio", "audio.samplerate_unsupported")
def samplerates(ctx: JobContext) -> Iterator[ValidationIssue]:
    for index, track, encoder, _ in _encoded_tracks(ctx):
        rate = track.samplerate
        if rate is None or not encoder.samplerates or rate in encoder.samplerates:
            continue
        closest = min(encoder.samplerates, key=lambda r: (abs(r - rate), -r))
        yield error(
            "audio.samplerate_unsupported",
            f"audio[{index}].samplerate",
            f"{encoder.label} ({encoder.id}) cannot encode at {rate} Hz.",
            fix(
                f"Use {closest} Hz",
                replace(f"audio[{index}].samplerate", closest),
                target=ctx.target,
            ),
        )
