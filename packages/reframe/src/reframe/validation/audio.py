"""Audio track rules: the source stream exists, auto passthru, and the values the encoder
cannot do.

Decision 0024 item 4: a mixdown, bitrate or sample rate the encoder cannot do is snapped by
the command builder to the nearest allowed value, with C-6's helpers
(:meth:`~reframe.definitions.AudioEncoderDef.snap_mixdown`,
:meth:`~reframe.definitions.AudioEncoderDef.snap_samplerate`,
:meth:`~reframe.definitions.AudioBitrateDef.snap`,
:func:`~reframe.definitions.channels_mixdown`). Validation computes the same values
(:func:`~reframe.validation.tracks.encoded_audio`) and shows an **info** issue that says
what will change; it never blocks the queue. A layout is never upmixed (decision 0019 item
3): a mixdown with more channels than the source, or Dolby Pro Logic II on a source that is
not surround, keeps the source layout (``audio.mixdown_upmix``).
"""

from __future__ import annotations

from collections.abc import Iterator

from reframe.definitions import AudioEncoderDef, Definitions
from reframe.models.issues import Fix, ValidationIssue
from reframe.models.job import AudioOutputTrack, Mixdown
from reframe.models.media import AudioStream
from reframe.validation.common import error, fix, info, remove, replace
from reframe.validation.context import JobContext
from reframe.validation.registry import job_rule
from reframe.validation.tracks import (
    EncodedAudio,
    encoded_audio,
    passthru_copies,
    track_encoder,
    track_stream,
)


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
        stream = track_stream(ctx, track)
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


# --------------------------------------------------------------------------- snapped values


def _encoded_tracks(
    ctx: JobContext,
) -> Iterator[tuple[int, AudioOutputTrack, AudioStream, EncodedAudio]]:
    """Every track that an encoder writes, with the values the builder writes for it. Tracks
    without a source stream are ``audio.source_missing``; an unknown encoder is
    ``encoder.unknown``."""
    for index, track in enumerate(ctx.job.audio):
        encoder_id = track_encoder(ctx, track)
        encoder = ctx.definitions.audio_encoders.get(encoder_id) if encoder_id else None
        stream = track_stream(ctx, track)
        if encoder is None or stream is None:
            continue
        yield index, track, stream, encoded_audio(track, stream, encoder, ctx.definitions)


def _label(definitions: Definitions, mixdown: Mixdown) -> str:
    definition = definitions.mixdowns.get(mixdown)
    return definition.label if definition is not None else mixdown


def _source_layout(stream: AudioStream) -> str:
    """``5.1(side)``, ``7.1``; ``6 channels`` when the probe gives no layout name. (A layout
    changes only for a known channel count: the helper keeps an unknown one.)"""
    return stream.channel_layout or f"{stream.channels} channels"


def _written_as(definitions: Definitions, mixdown: Mixdown | None, stream: AudioStream) -> str:
    if mixdown is None:
        return f"keeps the source layout ({_source_layout(stream)})"
    return f"is written as {_label(definitions, mixdown)}"


def _mixdown_fix(ctx: JobContext, index: int, mixdown: Mixdown | None) -> Fix:
    label = (
        "Keep the source layout"
        if mixdown is None
        else f"Mix down to {_label(ctx.definitions, mixdown)}"
    )
    return fix(label, replace(f"audio[{index}].mixdown", mixdown), target=ctx.target)


def _dropped_as_upmix(
    encoder: AudioEncoderDef, requested: Mixdown, channels: int, definitions: Definitions
) -> bool:
    """The helper's no-upmix rule (decision 0019 item 3) drops ``requested``: asked as if the
    encoder could make every layout, it still does not return the request."""
    every_layout = encoder.model_copy(update={"mixdowns": list(definitions.mixdowns)})
    return every_layout.snap_mixdown(requested, channels, definitions.mixdowns) != requested


@job_rule("audio", "audio.mixdown_unsupported", "audio.mixdown_upmix")
def mixdowns(ctx: JobContext) -> Iterator[ValidationIssue]:
    """The layout the builder writes differs from the track's: the encoder cannot make it
    (``audio.mixdown_unsupported``: AC-3 and E-AC-3 have no 7.1, MP3 no 5.1), or it would be
    an upmix (``audio.mixdown_upmix``). Both are info: the builder writes the snapped layout."""
    defs = ctx.definitions
    for index, track, stream, planned in _encoded_tracks(ctx):
        requested, written = track.mixdown, planned.mixdown
        if requested == written:
            continue
        encoder = planned.encoder
        path = f"audio[{index}].mixdown"
        result = _written_as(defs, written, stream)
        if requested is not None and _dropped_as_upmix(
            encoder, requested, planned.source_channels, defs
        ):
            source = _source_layout(stream)
            message = (
                "Dolby Pro Logic II needs a surround source: the source of audio track "
                f"{index + 1} is {source}, so the track {result}."
                if requested == "dpl2"
                else f"No upmix: the source of audio track {index + 1} has "
                f"{planned.source_channels} channels ({source}), so the track {result} "
                f"instead of {_label(defs, requested)}."
            )
            yield info("audio.mixdown_upmix", path, message, _mixdown_fix(ctx, index, written))
            continue
        wanted = _label(defs, requested) if requested is not None else _source_layout(stream)
        yield info(
            "audio.mixdown_unsupported",
            path,
            f"{encoder.label} cannot make {wanted}: audio track {index + 1} {result}.",
            _mixdown_fix(ctx, index, written),
        )


@job_rule("audio", "audio.bitrate_out_of_range")
def bitrates(ctx: JobContext) -> Iterator[ValidationIssue]:
    """A bitrate outside the encoder's range for the layout, or not one of its fixed steps
    (AC-3, E-AC-3, MP3). The builder snaps it down, as HandBrake does (info)."""
    for index, track, _, planned in _encoded_tracks(ctx):
        encoder, kbps, snapped = planned.encoder, track.bitrate, planned.bitrate
        if kbps is None or snapped is None or snapped == kbps or encoder.bitrate is None:
            continue
        limits = encoder.bitrate.by_mixdown[planned.table]
        layout = _label(ctx.definitions, planned.table)
        steps = ", fixed steps" if encoder.bitrate.allowed is not None else ""
        yield info(
            "audio.bitrate_out_of_range",
            f"audio[{index}].bitrate",
            f"{encoder.label} has no {kbps} kb/s for {layout} ({limits.min} to {limits.max} "
            f"kb/s{steps}): audio track {index + 1} is written at {snapped} kb/s.",
            fix(
                f"Use {snapped} kb/s",
                replace(f"audio[{index}].bitrate", snapped),
                target=ctx.target,
            ),
        )


@job_rule("audio", "audio.quality_unsupported")
def qualities(ctx: JobContext) -> Iterator[ValidationIssue]:
    """A VBR quality on an encoder without a VBR mode: the builder writes the encoder's
    default bitrate for the layout instead (info)."""
    for index, track, _, planned in _encoded_tracks(ctx):
        encoder = planned.encoder
        if (
            track.quality is None
            or track.bitrate is not None
            or encoder.quality is not None
            or encoder.bitrate is None
        ):
            continue
        limits = encoder.bitrate.by_mixdown.get(planned.table)
        if limits is None:  # pragma: no cover - every encoder has a range for its layouts
            continue
        yield info(
            "audio.quality_unsupported",
            f"audio[{index}].quality",
            f"{encoder.label} has no VBR quality: audio track {index + 1} is written at "
            f"{limits.default} kb/s, the default for {_label(ctx.definitions, planned.table)}.",
            fix(
                f"Use {limits.default} kb/s",
                replace(f"audio[{index}].quality", None),
                replace(f"audio[{index}].bitrate", limits.default),
                target=ctx.target,
            ),
        )


@job_rule("audio", "audio.samplerate_unsupported")
def samplerates(ctx: JobContext) -> Iterator[ValidationIssue]:
    """A sample rate the encoder does not list: the builder writes the nearest one it lists
    (info). "Same as source" with a rate the encoder does not list is resampled the same way
    without an issue (HandBrake does the same)."""
    for index, track, _, planned in _encoded_tracks(ctx):
        rate, written = track.samplerate, planned.samplerate
        if rate is None or written is None or written == rate:
            continue
        yield info(
            "audio.samplerate_unsupported",
            f"audio[{index}].samplerate",
            f"{planned.encoder.label} has no {rate} Hz: audio track {index + 1} is written at "
            f"{written} Hz.",
            fix(
                f"Use {written} Hz",
                replace(f"audio[{index}].samplerate", written),
                target=ctx.target,
            ),
        )
