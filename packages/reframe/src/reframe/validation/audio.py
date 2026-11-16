"""Audio track rules: the source stream exists, auto passthru, and values the encoder cannot do.

The command builder snaps a mixdown, bitrate or sample rate that the encoder cannot do to an
allowed value (a bitrate goes down). These rules show the change as an **info** issue; it never
blocks the queue. A layout is never upmixed: an upmix only adds silent channels.
"""

from __future__ import annotations

from collections.abc import Iterator

from pydantic import JsonValue

from reframe.command.audio import layout_channels
from reframe.definitions import AudioEncoderDef, Definitions
from reframe.models.issues import Fix, ValidationIssue
from reframe.models.job import AudioOutputTrack, Mixdown
from reframe.models.media import AudioStream
from reframe.validation.common import (
    DEFAULT_AUDIO_ENCODER,
    error,
    fix,
    info,
    remove,
    replace,
    warning,
)
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
            fix("Remove this audio track", remove(f"audio[{index}]")),
        )


@job_rule("audio", "audio.passthru_fallback")
def auto_passthru(ctx: JobContext) -> Iterator[ValidationIssue]:
    """A passthru track whose codec the container cannot hold is encoded with the fallback
    encoder. Info: nothing is wrong."""
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


@job_rule("audio", "audio.passthru_settings_ignored")
def passthru_settings(ctx: JobContext) -> Iterator[ValidationIssue]:
    """Gain, DRC and loudness normalisation need a decode, which a copied passthru track skips.
    Warning."""
    for index, track in enumerate(ctx.job.audio):
        if not passthru_copies(ctx, track):
            continue
        # (label, field, the value that turns it off)
        found: list[tuple[str, str, JsonValue]] = []
        if track.gain != 0:
            found.append(("gain", "gain", 0.0))
        if track.drc != 0:
            found.append(("DRC", "drc", 0.0))
        if track.loudness != "off":
            found.append(("loudness normalisation", "loudness", "off"))
        if not found:
            continue
        names = [label for label, _, _ in found]
        encoder = track.encoder or DEFAULT_AUDIO_ENCODER
        what = " and ".join([", ".join(names[:-1]), names[-1]] if len(names) > 1 else names)
        yield warning(
            "audio.passthru_settings_ignored",
            f"audio[{index}].action",
            f"Audio track {index + 1} is passed through (copied), so its {what} cannot be applied.",
            fix(
                f"Encode the track ({encoder})",
                replace(f"audio[{index}].action", "encode"),
                *([] if track.encoder else [replace(f"audio[{index}].encoder", encoder)]),
            ),
            fix(
                f"Remove the {what}",
                *(replace(f"audio[{index}].{field}", off) for _, field, off in found),
            ),
        )


def _encoded_tracks(
    ctx: JobContext,
) -> Iterator[tuple[int, AudioOutputTrack, AudioStream, EncodedAudio]]:
    """Every track an encoder writes, with the values the builder writes for it."""
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
    """The probe's layout name, or ``N channels`` when it gives none. A layout changes only
    for a known channel count: the helper keeps an unknown one."""
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
    return fix(label, replace(f"audio[{index}].mixdown", mixdown))


def _layout_downmix(planned: EncodedAudio) -> bool:
    """No mixdown, but the builder writes fewer channels than the source has, because the
    encoder refuses the source layout."""
    written = layout_channels(planned.layout)
    return (
        planned.mixdown is None and written is not None and len(written) < planned.source_channels
    )


def _layout_mixdown(definitions: Definitions, layout: str) -> Mixdown | None:
    """The mixdown that writes ``layout``, or ``None`` when no mixdown makes it."""
    return next(
        (
            mixdown
            for mixdown, definition in definitions.mixdowns.items()
            if definition.layout == layout and definition.matrix_encoding is None
        ),
        None,
    )


def _dropped_as_upmix(
    encoder: AudioEncoderDef, requested: Mixdown, channels: int, definitions: Definitions
) -> bool:
    """The no-upmix rule drops ``requested``: asked as if the encoder made every layout, the
    helper still does not return it. An upmix only adds silent channels."""
    every_layout = encoder.model_copy(update={"mixdowns": list(definitions.mixdowns)})
    return every_layout.snap_mixdown(requested, channels, definitions.mixdowns) != requested


@job_rule("audio", "audio.mixdown_unsupported", "audio.mixdown_upmix")
def mixdowns(ctx: JobContext) -> Iterator[ValidationIssue]:
    """The layout the builder writes differs from the track's: the encoder cannot make it
    (``audio.mixdown_unsupported``), or it would be an upmix (``audio.mixdown_upmix``). Both
    are info: the builder writes the snapped layout."""
    defs = ctx.definitions
    for index, track, stream, planned in _encoded_tracks(ctx):
        requested, written = track.mixdown, planned.mixdown
        downmixed = _layout_downmix(planned)
        if requested == written and not downmixed:
            continue
        encoder = planned.encoder
        path = f"audio[{index}].mixdown"
        result = _written_as(defs, written, stream)
        fixes = [_mixdown_fix(ctx, index, written)]
        if downmixed and planned.layout is not None:
            result = f"is written as {planned.layout}"
            same = _layout_mixdown(defs, planned.layout)
            fixes = [_mixdown_fix(ctx, index, same)] if same is not None else []
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
            yield info("audio.mixdown_upmix", path, message, *fixes)
            continue
        what = (
            f"make {_label(defs, requested)}"
            if requested is not None
            else f"keep {_source_layout(stream)}"
        )
        yield info(
            "audio.mixdown_unsupported",
            path,
            f"{encoder.label} cannot {what}: audio track {index + 1} {result}.",
            *fixes,
        )


@job_rule("audio", "audio.bitrate_out_of_range")
def bitrates(ctx: JobContext) -> Iterator[ValidationIssue]:
    """A bitrate outside the encoder's range for the layout, or not one of its fixed steps:
    the builder snaps it down, as HandBrake does. A bitrate on a lossless encoder: the builder
    writes none. Both info."""
    for index, track, _, planned in _encoded_tracks(ctx):
        encoder, kbps, snapped = planned.encoder, track.bitrate, planned.bitrate
        if kbps is not None and encoder.bitrate is None:
            yield info(
                "audio.bitrate_out_of_range",
                f"audio[{index}].bitrate",
                f"{encoder.label} is lossless and has no bitrate: audio track {index + 1} is "
                f"written without one ({kbps} kb/s is not used).",
                fix("Remove the bitrate", replace(f"audio[{index}].bitrate", None)),
            )  # fmt: skip
            continue
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
            ),
        )


@job_rule("audio", "audio.quality_unsupported")
def qualities(ctx: JobContext) -> Iterator[ValidationIssue]:
    """A VBR quality on an encoder without a VBR mode: the builder writes the encoder's
    default bitrate for the layout instead, or nothing for a lossless encoder (info)."""
    for index, track, _, planned in _encoded_tracks(ctx):
        encoder = planned.encoder
        if track.quality is None or track.bitrate is not None or encoder.quality is not None:
            continue
        if encoder.bitrate is None:
            yield info(
                "audio.quality_unsupported",
                f"audio[{index}].quality",
                f"{encoder.label} is lossless and has no VBR quality: audio track {index + 1} "
                "is written without one.",
                fix("Remove the VBR quality", replace(f"audio[{index}].quality", None)),
            )  # fmt: skip
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
            ),
        )
