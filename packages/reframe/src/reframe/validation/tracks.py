"""What an output track really does: its encoder, mixdown and subtitle format."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePath

from reframe.command import planned_audio
from reframe.command.audio import layout_channels
from reframe.command.subtitles import EXTERNAL_FORMATS
from reframe.definitions import AudioEncoderDef, ContainerDef, Definitions
from reframe.models.issues import Fix, JsonPatchOp
from reframe.models.job import AudioOutputTrack, Container, Mixdown, SubtitleOutputTrack
from reframe.models.media import AudioStream, SubtitleKind
from reframe.naming.context import audio_channels_label
from reframe.validation.common import DEFAULT_AUDIO_ENCODER, replace, switch_container_fixes
from reframe.validation.context import JobContext

__all__ = [
    "EncodedAudio",
    "SubtitleInput",
    "encoded_audio",
    "job_fits",
    "passthru_copies",
    "subtitle_input",
    "switch_audio_encoder",
    "switch_container",
    "track_encoder",
    "track_stream",
    "written_channels",
    "written_layout",
]


@dataclass(frozen=True, slots=True)
class EncodedAudio:
    """What the command builder writes for an encoded audio track: the values snapped to what the
    encoder can do, so an issue names the value that is really written."""

    encoder: AudioEncoderDef
    source_channels: int
    """The source track's channel count (0 = unknown)."""
    mixdown: Mixdown | None
    """:meth:`AudioEncoderDef.snap_mixdown`: the mixdown written; ``None`` = the source
    layout stays (see :attr:`layout`)."""
    layout: str | None
    """The ``out_chlayout`` written (``PlannedAudio.layout``): a mixdown's layout, a lossless
    relabel or, when the encoder refuses the source layout, the layout it is made into;
    ``None`` = the source layout as it is."""
    table: Mixdown
    """The mixdown whose bitrate range applies (``PlannedAudio.bitrate_mixdown``): the
    written layout's."""
    bitrate: int | None
    """The track's bitrate, snapped down; ``None`` when the track sets none or the encoder is
    lossless."""
    samplerate: int | None
    """:meth:`AudioEncoderDef.snap_samplerate` of the track's rate (or the source's)."""


def encoded_audio(
    track: AudioOutputTrack,
    stream: AudioStream,
    encoder: AudioEncoderDef,
    definitions: Definitions,
) -> EncodedAudio:
    """The values the builder writes for ``track`` encoded with ``encoder``
    (:func:`~reframe.command.planned_audio`). The snapped values do not depend on the
    container, so the first container that holds the encoder is used."""
    container = next(
        (c for c in definitions.containers.values() if encoder.codec in c.audio.encode), None
    )
    encode = track.model_copy(update={"action": "encode", "encoder": encoder.id})
    if container is None:  # pragma: no cover - every encoder has a container
        raise ValueError(f"no container holds {encoder.id}")
    planned = planned_audio(encode, stream, container, definitions=definitions)
    assert planned.bitrate_mixdown is not None  # an encoded track always has a table
    return EncodedAudio(
        encoder=encoder,
        source_channels=max(stream.channels, 0),
        mixdown=planned.mixdown,
        layout=planned.layout,
        table=planned.bitrate_mixdown,
        bitrate=planned.bitrate if track.bitrate is not None else None,
        samplerate=planned.samplerate,
    )


def written_channels(definitions: Definitions, planned: EncodedAudio) -> int:
    """The channel count the builder writes (0 = unknown)."""
    if planned.mixdown is not None:
        return definitions.mixdowns[planned.mixdown].channels
    written = layout_channels(planned.layout)
    return len(written) if written is not None else planned.source_channels


def written_layout(definitions: Definitions, planned: EncodedAudio) -> str:
    """The written layout as its mixdown's label (``Stereo``), else as ``N.M``."""
    if planned.mixdown is not None:
        return definitions.mixdowns[planned.mixdown].label
    return audio_channels_label(written_channels(definitions, planned), planned.layout)


def track_stream(ctx: JobContext, track: AudioOutputTrack) -> AudioStream | None:
    """The source stream an audio track reads (``None``: ``audio.source_missing``)."""
    if track.source_stream is None:
        return None
    return ctx.audio_streams.get(track.source_stream)


def passthru_copies(ctx: JobContext, track: AudioOutputTrack) -> bool:
    """A passthru track whose source codec the container can hold (no encoder runs)."""
    if track.action != "passthru":
        return False
    stream = track_stream(ctx, track)
    return (
        stream is not None
        and stream.codec is not None
        and ctx.container.audio.can_copy(stream.codec)
    )


def track_encoder(ctx: JobContext, track: AudioOutputTrack) -> str | None:
    """The audio encoder the track uses: ``None`` for a passthru that the container can hold;
    else the track's encoder (for passthru: the fallback, HandBrake's auto passthru), or
    :data:`DEFAULT_AUDIO_ENCODER` when it names none."""
    if passthru_copies(ctx, track):
        return None
    return track.encoder or DEFAULT_AUDIO_ENCODER


def switch_audio_encoder(
    path: str,
    new: AudioEncoderDef,
    definitions: Definitions,
    *,
    track: AudioOutputTrack | None = None,
    stream: AudioStream | None = None,
) -> list[JsonPatchOp]:
    """Switch the encoder at ``path`` (``audio[2].encoder``) to ``new``; snap the track's
    bitrate to what ``new`` writes for it (:func:`encoded_audio`) and drop a VBR quality it
    does not have. Without a track (a template) only the encoder changes."""
    prefix = path.rsplit(".", 1)[0]
    ops: list[JsonPatchOp] = [replace(path, new.id)]
    if track is None:
        return ops
    if track.bitrate is not None and stream is not None:
        snapped = encoded_audio(track, stream, new, definitions).bitrate
        if snapped is not None and snapped != track.bitrate:
            ops.append(replace(f"{prefix}.bitrate", snapped))
    if track.quality is not None and new.quality is None:
        ops.append(replace(f"{prefix}.quality", None))
    return ops


@dataclass(frozen=True, slots=True)
class SubtitleInput:
    """What an output subtitle track reads: a source stream or an external file."""

    codec: str | None
    kind: SubtitleKind
    label: str
    """``stream 3 (PGS)``, ``file signs.ass``."""


def subtitle_input(ctx: JobContext, track: SubtitleOutputTrack) -> SubtitleInput | None:
    """``None`` when the source stream does not exist. An external file's format comes from
    its extension."""
    if isinstance(track.source, int):
        stream = ctx.subtitle_streams.get(track.source)
        if stream is None:
            return None
        name = stream.display_codec or stream.codec or "unknown format"
        return SubtitleInput(stream.codec, stream.subtitle_kind, f"stream {stream.index} ({name})")
    path = PurePath(track.source.path)
    codec: str | None
    kind: SubtitleKind
    codec, kind = EXTERNAL_FORMATS.get(path.suffix.lower(), (None, "text"))
    return SubtitleInput(codec, kind, f"file {path.name}")


def job_fits(ctx: JobContext, container: ContainerDef) -> bool:
    """``container`` can hold every track of the job as it is. Unknown encoders and missing
    streams count as fitting (other rules report them): a "Switch to" fix must not add an
    error."""
    job = ctx.job
    stream = ctx.video_stream
    if job.video.passthrough:
        if stream is not None and not container.video.can_copy(stream.codec or ""):
            return False
    else:
        encoder = ctx.definitions.video_encoders.get(job.video.encoder)
        if encoder is not None and encoder.codec not in container.video.encode:
            return False
    for track in job.audio:
        source = track_stream(ctx, track)
        if source is None:
            continue
        if track.action == "passthru" and container.audio.can_copy(source.codec or ""):
            continue
        audio = ctx.definitions.audio_encoders.get(track.encoder or DEFAULT_AUDIO_ENCODER)
        if audio is not None and audio.codec not in container.audio.encode:
            return False
    return all(_subtitle_fits(ctx, track, container) for track in job.subtitles)


def switch_container(ctx: JobContext, allowed: Sequence[Container]) -> list[Fix]:
    """The "Switch to …" fixes of a job: only containers that hold every track
    (:func:`job_fits`), and the output's extension changes with the container."""
    return switch_container_fixes(
        allowed,
        ctx.job.output.container,
        ctx.definitions,
        output=ctx.job.output.path,
        holds=lambda container: job_fits(ctx, container),
    )


def _subtitle_fits(ctx: JobContext, track: SubtitleOutputTrack, container: ContainerDef) -> bool:
    if track.action == "burn":
        return True
    if track.action == "convert":
        return track.convert_to is None or track.convert_to in container.subtitles.encode
    found = subtitle_input(ctx, track)
    if found is None or found.codec is None or container.subtitles.can_copy(found.codec):
        return True
    return found.kind == "text" and container.text_subtitle_target is not None
