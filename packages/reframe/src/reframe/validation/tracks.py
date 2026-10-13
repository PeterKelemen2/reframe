"""What an output track really does: its encoder, mixdown and subtitle format."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath

from reframe.definitions import AudioEncoderDef
from reframe.models.issues import JsonPatchOp
from reframe.models.job import AudioOutputTrack, Mixdown, SubtitleOutputTrack
from reframe.models.media import AudioStream, SubtitleKind
from reframe.validation.common import DEFAULT_AUDIO_ENCODER, replace
from reframe.validation.context import JobContext

__all__ = [
    "BITMAP_CODECS",
    "FORCED_ONLY_CODECS",
    "SubtitleInput",
    "channels_mixdown",
    "effective_mixdown",
    "passthru_copies",
    "subtitle_input",
    "switch_audio_encoder",
    "track_encoder",
]

#: ffprobe codec names of bitmap subtitles.
BITMAP_CODECS = frozenset({"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "xsub"})
#: Subtitle decoders that have ``forced_subs_only`` in FFmpeg n9.0.2 (``ffmpeg -h
#: decoder=pgssub``, ``decoder=dvdsub``; not ``dvbsub`` and no text decoder;
#: testdata/README.md "Validation (C-8)").
FORCED_ONLY_CODECS = frozenset({"hdmv_pgs_subtitle", "dvd_subtitle"})
#: External subtitle files by extension: (ffprobe codec name, kind).
_EXTERNAL: dict[str, tuple[str, SubtitleKind]] = {
    ".srt": ("subrip", "text"),
    ".ass": ("ass", "text"),
    ".ssa": ("ass", "text"),
    ".vtt": ("webvtt", "text"),
    ".sup": ("hdmv_pgs_subtitle", "bitmap"),
}


def channels_mixdown(channels: int) -> Mixdown:
    """The mixdown that keeps a layout of ``channels`` channels (for bitrate ranges)."""
    if channels <= 1:
        return "mono"
    if channels <= 2:
        return "stereo"
    if channels <= 6:
        return "5.1"
    return "7.1"


def effective_mixdown(track: AudioOutputTrack, stream: AudioStream | None) -> Mixdown | None:
    """The track's mixdown; for "keep the source layout" the source's (``None`` when the
    source stream is unknown)."""
    if track.mixdown is not None:
        return track.mixdown
    if stream is None or stream.channels <= 0:
        return None
    return channels_mixdown(stream.channels)


def passthru_copies(ctx: JobContext, track: AudioOutputTrack) -> bool:
    """A passthru track whose source codec the container can hold (no encoder runs)."""
    if track.action != "passthru" or ctx.container is None:
        return False
    stream = ctx.audio_streams.get(track.source_stream) if track.source_stream is not None else None
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
    bitrate: int | None,
    quality: float | None,
    mixdown: Mixdown | None,
    new: AudioEncoderDef,
) -> list[JsonPatchOp]:
    """Switch the encoder at ``path`` (``audio[2].encoder``) to ``new``; snap the bitrate to
    its allowed values and drop a VBR quality it does not have."""
    prefix = path.rsplit(".", 1)[0]
    ops: list[JsonPatchOp] = [replace(path, new.id)]
    if bitrate is not None and new.bitrate is not None and mixdown is not None:
        snapped = new.bitrate.snap(bitrate, mixdown)
        if snapped is not None and snapped != bitrate:
            ops.append(replace(f"{prefix}.bitrate", snapped))
    if quality is not None and new.quality is None:
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
    codec, kind = _EXTERNAL.get(path.suffix.lower(), (None, "text"))
    return SubtitleInput(codec, kind, f"file {path.name}")
