"""Track name templates of a job: a track name with a ``{variable}`` is expanded for its
track (``{lang_name} {channels} {codec}`` → ``Japanese 5.1 Opus``), with the variables of the
codec rules' name templates.

A name is a template only when it has a brace. It is rendered when it parses and names only
track name variables: ``{{`` and ``}}`` write a brace, and ``<…>`` is an optional group. Any
other name, such as a source title ``Signs {Karaoke}``, is written as it is.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from reframe import languages
from reframe.definitions import ContainerDef, Definitions, load_definitions
from reframe.models.job import (
    AudioOutputTrack,
    ExternalSubtitle,
    JobSettings,
    Mixdown,
    SubtitleOutputTrack,
    TrackMetadata,
)
from reframe.models.media import AudioStream, MediaSource, SubtitleStream, VideoStream
from reframe.naming.context import audio_channels_label
from reframe.naming.template import Template, Value, parse_template, render, template_variables
from reframe.probe.names import codec_name, subtitle_display_name

if TYPE_CHECKING:
    from reframe.command.audio import PlannedAudio

__all__ = [
    "TRACK_NAME_VARIABLES",
    "TrackNames",
    "expand_track_name",
    "expand_track_names",
    "is_track_name_template",
    "track_names",
    "written_audio_values",
]

#: The variables of a track name template.
TRACK_NAME_VARIABLES = frozenset(
    {"lang", "lang_name", "lang_native", "channels", "codec", "bitrate", "title", "source_codec"}
)

#: External subtitle file suffix → its codec name.
_SUBTITLE_SUFFIXES = {
    ".srt": "subrip",
    ".ass": "ass",
    ".ssa": "ssa",
    ".vtt": "webvtt",
    ".sup": "hdmv_pgs_subtitle",
}

_Stream = VideoStream | AudioStream | SubtitleStream


@dataclass(frozen=True, slots=True)
class TrackNames:
    """The names a job writes, by track; ``None`` keeps the source title."""

    video: str | None
    audio: list[str | None]
    subtitles: list[str | None]


def _template(name: str | None) -> Template | None:
    if name is None or not _has_brace(name):
        return None
    template = parse_template(name)
    if template.errors or any(
        var.name not in TRACK_NAME_VARIABLES for var in template_variables(template.nodes)
    ):
        return None
    return template


def is_track_name_template(name: str | None) -> bool:
    """Whether ``name`` is rendered for its track rather than written as it is."""
    return _template(name) is not None


def expand_track_name(name: str | None, values: Mapping[str, Value]) -> str | None:
    """``name`` rendered with ``values`` when it is a template; else ``name`` as it is."""
    template = _template(name)
    if template is None:
        return name
    segments = render(template, values)
    return "/".join("".join(piece.text for piece in segment) for segment in segments).strip()


def track_names(
    job: JobSettings, source: MediaSource, definitions: Definitions | None = None
) -> TrackNames:
    """Each track's name as ``job`` writes it, templates expanded."""
    defs = definitions if definitions is not None else load_definitions()
    container = defs.containers[job.output.container]
    audio_streams = {stream.index: stream for stream in source.audio}
    subtitle_streams = {stream.index: stream for stream in source.subtitles}
    video_stream = source.video[0] if source.video else None

    video = job.video.metadata.name
    if _has_brace(video):
        video = expand_track_name(video, _video_values(job, video_stream, defs))
    audio: list[str | None] = []
    for track in job.audio:
        name = track.metadata.name
        if _has_brace(name):
            stream = (
                audio_streams.get(track.source_stream) if track.source_stream is not None else None
            )
            name = expand_track_name(name, _audio_values(track, stream, container, defs))
        audio.append(name)
    subtitles: list[str | None] = []
    for subtitle in job.subtitles:
        name = subtitle.metadata.name
        if _has_brace(name):
            found = (
                subtitle_streams.get(subtitle.source) if isinstance(subtitle.source, int) else None
            )
            name = expand_track_name(name, _subtitle_values(subtitle, found, container))
        subtitles.append(name)
    return TrackNames(video, audio, subtitles)


def expand_track_names(
    job: JobSettings, source: MediaSource, definitions: Definitions | None = None
) -> JobSettings:
    """``job`` with its track name templates expanded: a copy, or ``job`` itself when no name
    changes."""
    names = track_names(job, source, definitions)
    unchanged = (
        names.video == job.video.metadata.name
        and names.audio == [track.metadata.name for track in job.audio]
        and names.subtitles == [track.metadata.name for track in job.subtitles]
    )
    if unchanged:
        return job
    expanded = job.model_copy(deep=True)
    expanded.video.metadata.name = names.video
    for track, name in zip(expanded.audio, names.audio, strict=True):
        track.metadata.name = name
    for subtitle, name in zip(expanded.subtitles, names.subtitles, strict=True):
        subtitle.metadata.name = name
    return expanded


def _has_brace(name: str | None) -> bool:
    return name is not None and ("{" in name or "}" in name)


def _language_values(language: str | None) -> dict[str, Value]:
    return {
        "lang": language,
        "lang_name": languages.english_name(language),
        "lang_native": languages.native_name(language, capitalize=True),
    }


def _language(
    meta: TrackMetadata, stream: _Stream | None, fallback: str | None = None
) -> str | None:
    """The language the track is written with: its own, else its source's (BCP 47 when valid)."""
    if meta.language:
        return meta.language
    raw = [
        value
        for value in (
            stream.language_ietf if stream is not None else None,
            stream.language if stream is not None else None,
            fallback,
        )
        if value
    ]
    for value in raw:
        canonical = languages.normalize(value)
        if canonical is not None:
            return canonical
    return raw[0] if raw else None


def _codec_label(stream: _Stream | None) -> str | None:
    if stream is None:
        return None
    if stream.display_codec:
        return stream.display_codec
    return codec_name(stream.codec) if stream.codec else None


def _video_values(
    job: JobSettings, stream: VideoStream | None, defs: Definitions
) -> dict[str, Value]:
    if job.video.passthrough:
        codec = _codec_label(stream)
    else:
        encoder = defs.video_encoders.get(job.video.encoder)
        codec = codec_name(encoder.codec) if encoder is not None else job.video.encoder
    return {
        **_language_values(_language(job.video.metadata, stream)),
        "codec": codec,
        "title": stream.title if stream is not None else None,
        "source_codec": _codec_label(stream),
    }


def _planned_audio(
    track: AudioOutputTrack, stream: AudioStream | None, container: ContainerDef, defs: Definitions
) -> PlannedAudio | None:
    """What the builder writes for ``track``; ``None`` without a source stream, or for a track
    that validation refuses."""
    # Imported here: reframe.command's builder imports this module.
    from reframe.command.audio import planned_audio
    from reframe.command.errors import PlanError

    if stream is None:
        return None
    try:
        return planned_audio(track, stream, container, definitions=defs)
    except PlanError:
        return None


def _mixdown_label(mixdown: Mixdown, defs: Definitions) -> str:
    found = defs.mixdowns[mixdown]
    return f"{found.channels - found.lfe}.{found.lfe}"


def written_audio_values(
    track: AudioOutputTrack,
    stream: AudioStream | None,
    container: ContainerDef,
    definitions: Definitions,
) -> dict[str, Value]:
    """``channels``, ``codec`` and ``bitrate`` of ``track`` (read from ``stream``) as the builder
    writes them into ``container``: the snapped layout and bit rate, the fallback encoder of a
    passthru. A track that validation refuses gets the values it asks for."""
    from reframe.command.audio import layout_channels

    defs = definitions
    source_channels = (
        audio_channels_label(stream.channels, stream.channel_layout) if stream is not None else None
    )
    planned = _planned_audio(track, stream, container, defs)
    channels: str | None
    bitrate: int | None
    if planned is None:
        channels = (
            _mixdown_label(track.mixdown, defs) if track.mixdown is not None else source_channels
        )
        encoder = defs.audio_encoders.get(track.encoder or "")
        codec = encoder.label if encoder is not None else track.encoder
        bitrate = track.bitrate
    elif planned.copy:
        channels, codec, bitrate = source_channels, _codec_label(stream), None
    else:
        written = layout_channels(planned.layout)
        if planned.mixdown is not None:
            channels = _mixdown_label(planned.mixdown, defs)
        elif written is not None:
            channels = audio_channels_label(len(written), planned.layout)
        else:
            channels = source_channels
        assert planned.encoder is not None
        codec = defs.audio_encoders[planned.encoder].label
        bitrate = planned.bitrate
    return {"channels": channels, "codec": codec, "bitrate": bitrate}


def _audio_values(
    track: AudioOutputTrack, stream: AudioStream | None, container: ContainerDef, defs: Definitions
) -> dict[str, Value]:
    return {
        **_language_values(_language(track.metadata, stream)),
        **written_audio_values(track, stream, container, defs),
        "title": stream.title if stream is not None else None,
        "source_codec": _codec_label(stream),
    }


def _subtitle_values(
    track: SubtitleOutputTrack, stream: SubtitleStream | None, container: ContainerDef
) -> dict[str, Value]:
    from reframe.command.subtitles import written_subtitle_codec

    external = track.source if isinstance(track.source, ExternalSubtitle) else None
    if external is not None:
        codec = _SUBTITLE_SUFFIXES.get(Path(external.path).suffix.lower())
        source_codec = subtitle_display_name(codec)
        title = external.name
    else:
        codec = stream.codec if stream is not None else None
        source_codec = _codec_label(stream)
        title = stream.title if stream is not None else None
    written = written_subtitle_codec(track, codec, container) if codec else None
    language = _language(track.metadata, stream, external.language if external else None)
    return {
        **_language_values(language),
        "codec": source_codec if written in (None, codec) else subtitle_display_name(written),
        "title": title,
        "source_codec": source_codec,
    }
