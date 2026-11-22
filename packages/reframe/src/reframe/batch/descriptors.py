"""Track descriptors and fingerprints. A descriptor is the normalised summary of one track; a
fingerprint is a file's descriptors plus its main video's size and HDR type, compared at one
of three strictness levels.

No level compares bit rates: a lossless or VBR track differs from episode to episode of one
release. Roles count only with flag or title evidence, plus the roles that the disposition
flags give a source built without the prober (:func:`stream_roles`). A role inferred from
statistics varies per episode, so it stays on the stream but is no descriptor role.

Pure: no I/O.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Literal

from reframe import languages
from reframe.batch.metadata import effective_language
from reframe.batch.selection import _EXTRA_ROLES, flag_extra_role, is_undetermined
from reframe.models.batch import Fingerprint, MatchLevel, TrackDescriptor
from reframe.models.job import TrackFlags
from reframe.models.media import (
    AudioStream,
    HdrFormat,
    MediaSource,
    RoleEvidence,
    SubtitleStream,
    TrackRole,
    VideoStream,
)
from reframe.naming.context import audio_channels_label, resolution_label
from reframe.probe.names import BITMAP_SUBTITLE_CODECS, codec_name

__all__ = [
    "MATCH_LEVELS",
    "codec_family",
    "codec_label",
    "describe_stream",
    "describe_tracks",
    "fingerprint",
    "hdr_type",
    "stream_roles",
    "track_key",
    "track_label",
    "video_key",
]

#: The strictness levels, strictest first.
MATCH_LEVELS: tuple[MatchLevel, ...] = ("strict", "standard", "loose")

#: ffprobe codec name → codec family, for the loose level. A codec that is not listed is its
#: own family.
_FAMILIES = {
    "dts": "dts",
    "truehd": "truehd",
    "mlp": "truehd",
    "ac3": "ac3",
    "eac3": "ac3",
    "aac": "aac",
    "aac_latm": "aac",
    "mp1": "mpeg_audio",
    "mp2": "mpeg_audio",
    "mp3": "mpeg_audio",
}

#: The order in which an HDR type is named when a stream has several.
_HDR_ORDER = (HdrFormat.DOLBY_VISION, HdrFormat.HDR10_PLUS, HdrFormat.HDR10, HdrFormat.HLG)

Stream = VideoStream | AudioStream | SubtitleStream


#: Subtitle codecs by family: a release may carry the same subtitles as SRT or as ASS. A codec
#: in neither set is its own family.
_TEXT_SUBTITLES = frozenset({"ass", "ssa", "subrip", "srt", "webvtt", "mov_text", "text"})


def codec_family(stream: Stream) -> str | None:
    """The codec family of ``stream``, or ``None`` without a codec. Only the codec decides, so
    two tracks with one codec are always one family."""
    codec = stream.codec
    if codec is None:
        return None
    if isinstance(stream, SubtitleStream):
        if codec in _TEXT_SUBTITLES:
            return "text"
        if codec in BITMAP_SUBTITLE_CODECS:
            return "bitmap"
        return codec
    if codec.startswith("pcm_"):
        return "pcm"
    return _FAMILIES.get(codec, codec)


def codec_label(stream: Stream) -> str:
    """The commercial name of the codec, else a short codec name."""
    if stream.display_codec:
        return stream.display_codec
    if stream.codec is None:
        return "unknown codec"
    return codec_name(stream.codec)


def stream_roles(stream: AudioStream | SubtitleStream) -> list[TrackRole]:
    """The track's roles: the prober's roles with flag or title evidence (not the heuristic
    ones, which vary per episode), plus the roles that the disposition flags give a source built
    without the prober; ``[main]`` when there is none."""
    found: list[TrackRole] = [
        info.role for info in stream.roles if info.evidence is not RoleEvidence.HEURISTIC
    ]
    extras = _EXTRA_ROLES["audio" if isinstance(stream, AudioStream) else "subtitle"]
    if not any(role in extras for role in found):
        extra = flag_extra_role(stream)
        if extra is not None:
            found.append(extra[0])
    if isinstance(stream, SubtitleStream):
        d = stream.disposition
        if d.forced and TrackRole.FORCED not in found:
            found.append(TrackRole.FORCED)
        if (d.hearing_impaired or d.captions) and TrackRole.SDH not in found:
            found.append(TrackRole.SDH)
    if len(found) > 1 and TrackRole.MAIN in found:
        found.remove(TrackRole.MAIN)
    return found or [TrackRole.MAIN]


def _flags(stream: Stream) -> TrackFlags:
    d = stream.disposition
    return TrackFlags(
        default=d.default,
        forced=d.forced,
        commentary=d.comment,
        hearing_impaired=d.hearing_impaired,
        visual_impaired=d.visual_impaired,
        original=d.original,
    )


def track_label(descriptor: TrackDescriptor) -> str:
    """``eng AC-3 2.0 "Commentary"``, ``eng ASS "Signs & Songs"``, ``H.264 320x180``."""
    parts: list[str] = []
    if descriptor.kind != "video":
        parts.append(languages.to_matroska_legacy(descriptor.language))
    parts.append(
        descriptor.profile
        or (codec_name(descriptor.codec) if descriptor.codec else "unknown codec")
    )
    if descriptor.kind == "audio" and descriptor.channels:
        parts.append(audio_channels_label(descriptor.channels))
    if descriptor.title:
        parts.append(f'"{descriptor.title}"')
    return " ".join(parts)


def describe_stream(stream: Stream, position: int) -> TrackDescriptor:
    """The descriptor of one stream; ``position`` is its place among the streams of its
    kind."""
    kind: Literal["video", "audio", "subtitle"]
    channels: int | None = None
    bitrate: int | None = None
    profile: str | None = None
    roles: list[TrackRole] = []
    language: str | None = None
    if isinstance(stream, VideoStream):
        kind = "video"
        bitrate = stream.bitrate.value
        profile = stream.display_codec
        language = effective_language(stream)
    else:
        language = effective_language(stream)
        if is_undetermined(language):
            language = None
        roles = stream_roles(stream)
        if isinstance(stream, AudioStream):
            kind = "audio"
            channels = stream.channels
            bitrate = stream.bitrate.value
            profile = stream.display_codec or stream.profile
        else:
            kind = "subtitle"
    descriptor = TrackDescriptor(
        kind=kind,
        index=stream.index,
        position=position,
        codec=stream.codec,
        codec_family=codec_family(stream),
        profile=profile,
        channels=channels,
        language=language,
        title=stream.title or None,
        roles=roles,
        flags=_flags(stream),
        bitrate=bitrate,
    )
    if isinstance(stream, VideoStream):
        label = f"{codec_label(stream)} {stream.width}x{stream.height}"
    else:
        label = track_label(descriptor)
    return descriptor.model_copy(update={"label": label})


def describe_tracks(source: MediaSource) -> list[TrackDescriptor]:
    """Every video, audio and subtitle track of ``source``, in stream order. Cover art,
    attachments and data streams are not tracks."""
    found: list[TrackDescriptor] = [
        *(describe_stream(stream, position) for position, stream in enumerate(source.video)),
        *(describe_stream(stream, position) for position, stream in enumerate(source.audio)),
        *(describe_stream(stream, position) for position, stream in enumerate(source.subtitles)),
    ]
    return sorted(found, key=lambda d: d.index)


def hdr_type(source: MediaSource) -> HdrFormat | None:
    """The main video's HDR type (Dolby Vision before HDR10+ before HDR10 before HLG)."""
    if not source.video or source.video[0].hdr is None:
        return None
    formats = source.video[0].hdr.formats
    return next((fmt for fmt in _HDR_ORDER if fmt in formats), None)


def track_key(descriptor: TrackDescriptor, level: MatchLevel) -> tuple[object, ...]:
    """What ``level`` compares of one track."""
    roles = tuple(sorted(role.value for role in descriptor.roles))
    if level == "loose":
        return (descriptor.kind, descriptor.codec_family, descriptor.language, roles)
    if level == "standard":
        return (descriptor.kind, descriptor.codec, descriptor.channels, descriptor.language, roles)
    flags = tuple(descriptor.flags.model_dump().values())
    return (
        descriptor.kind,
        descriptor.codec,
        descriptor.profile,
        descriptor.channels,
        descriptor.language,
        descriptor.title,
        roles,
        flags,
    )


def video_key(fp: Fingerprint) -> tuple[object, ...]:
    """What the fingerprint's level compares of the video: the size (the resolution class at
    the loose level) and the HDR type."""
    size: str | None = None
    if fp.width is not None and fp.height is not None:
        size = (
            resolution_label(fp.width, fp.height)
            if fp.level == "loose"
            else f"{fp.width}x{fp.height}"
        )
    return (size, fp.hdr.value if fp.hdr is not None else None)


def fingerprint(source: MediaSource, level: MatchLevel) -> Fingerprint:
    """The fingerprint of ``source`` at ``level``: its descriptors, the main video's size and
    HDR type, and a digest of what the level compares (equal digests = the same structure)."""
    tracks = describe_tracks(source)
    width = height = None
    if source.video:
        width, height = source.video[0].width, source.video[0].height
    unhashed = Fingerprint(
        level=level, tracks=tracks, width=width, height=height, hdr=hdr_type(source), digest=""
    )
    return unhashed.model_copy(update={"digest": _digest(unhashed)})


def _digest(fp: Fingerprint) -> str:
    keys: Sequence[tuple[object, ...]] = [track_key(d, fp.level) for d in fp.tracks]
    if fp.level == "loose":
        keys = sorted(keys, key=repr)
    text = json.dumps(
        {"level": fp.level, "tracks": keys, "video": video_key(fp)},
        sort_keys=True,
        ensure_ascii=True,
        default=str,
    )
    return hashlib.sha256(text.encode("ascii")).hexdigest()[:16]
