"""What an output track really does: its encoder, mixdown and subtitle format."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath

from reframe.definitions import AudioEncoderDef, Definitions, channels_mixdown
from reframe.models.issues import JsonPatchOp
from reframe.models.job import AudioOutputTrack, Mixdown, SubtitleOutputTrack
from reframe.models.media import AudioStream, SubtitleKind
from reframe.validation.common import DEFAULT_AUDIO_ENCODER, replace
from reframe.validation.context import JobContext

__all__ = [
    "BITMAP_CODECS",
    "EXTERNAL_FORMATS",
    "FORCED_ONLY_CODECS",
    "EncodedAudio",
    "SubtitleInput",
    "encoded_audio",
    "passthru_copies",
    "subtitle_input",
    "switch_audio_encoder",
    "track_encoder",
    "track_stream",
]

#: ffprobe codec names of bitmap subtitles.
BITMAP_CODECS = frozenset({"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "xsub"})
#: Subtitle decoders that have ``forced_subs_only`` in FFmpeg n9.0.2 (``ffmpeg -h
#: decoder=pgssub``, ``decoder=dvdsub``; not ``dvbsub`` and no text decoder;
#: testdata/README.md "Validation (C-8)").
FORCED_ONLY_CODECS = frozenset({"hdmv_pgs_subtitle", "dvd_subtitle"})
#: External subtitle files by extension: (ffprobe codec name, kind). The command builder reads
#: these (``reframe.command.subtitles.EXTERNAL_CODECS``); any other file is refused.
EXTERNAL_FORMATS: dict[str, tuple[str, SubtitleKind]] = {
    ".srt": ("subrip", "text"),
    ".ass": ("ass", "text"),
    ".ssa": ("ass", "text"),
    ".vtt": ("webvtt", "text"),
    ".sup": ("hdmv_pgs_subtitle", "bitmap"),
}


@dataclass(frozen=True, slots=True)
class EncodedAudio:
    """What the command builder writes for an encoded audio track. Decision 0024: the builder
    snaps every value the encoder cannot do with C-6's helpers, and validation uses the same
    helpers, so an issue text names the value that is really written."""

    encoder: AudioEncoderDef
    source_channels: int
    """The source track's channel count (0 = unknown)."""
    mixdown: Mixdown | None
    """:meth:`AudioEncoderDef.snap_mixdown`: the layout written; ``None`` = the source
    layout stays."""
    table: Mixdown
    """The mixdown whose bitrate range applies: :attr:`mixdown`, else
    :func:`~reframe.definitions.channels_mixdown` of the source channels."""
    bitrate: int | None
    """The track's bitrate snapped down (:meth:`AudioBitrateDef.snap`); ``None`` when the
    track sets none or the encoder has no bitrate for :attr:`table`."""
    samplerate: int | None
    """:meth:`AudioEncoderDef.snap_samplerate` of the track's rate (or the source's)."""


def encoded_audio(
    track: AudioOutputTrack,
    stream: AudioStream,
    encoder: AudioEncoderDef,
    definitions: Definitions,
) -> EncodedAudio:
    """The values the builder writes for ``track`` encoded with ``encoder``."""
    channels = max(stream.channels, 0)
    mixdown = encoder.snap_mixdown(track.mixdown, channels, definitions.mixdowns)
    table = mixdown if mixdown is not None else channels_mixdown(channels)
    bitrate = (
        encoder.bitrate.snap(track.bitrate, table, "down")
        if track.bitrate is not None and encoder.bitrate is not None
        else None
    )
    return EncodedAudio(
        encoder=encoder,
        source_channels=channels,
        mixdown=mixdown,
        table=table,
        bitrate=bitrate,
        samplerate=encoder.snap_samplerate(track.samplerate, stream.sample_rate),
    )


def track_stream(ctx: JobContext, track: AudioOutputTrack) -> AudioStream | None:
    """The source stream an audio track reads (``None``: ``audio.source_missing``)."""
    if track.source_stream is None:
        return None
    return ctx.audio_streams.get(track.source_stream)


def passthru_copies(ctx: JobContext, track: AudioOutputTrack) -> bool:
    """A passthru track whose source codec the container can hold (no encoder runs)."""
    if track.action != "passthru" or ctx.container is None:
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
