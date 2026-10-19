"""The values of the template variables for one file.

Built from the parsed name, the job settings and the probed source. Every input except the
name is optional: a variable whose data is missing is empty (``None``), and an optional group
``<…>`` around it drops it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from reframe import languages
from reframe.definitions import Definitions
from reframe.models.job import (
    ChapterRange,
    ConstantQuality,
    Container,
    FullRange,
    JobSettings,
)
from reframe.models.media import AudioStream, HdrFormat, MediaSource, SubtitleStream
from reframe.models.naming import NamingOptions, ParsedName
from reframe.naming.clean import clean_name_text
from reframe.naming.fs import NamingFs
from reframe.naming.sanitize import replace_undecodable
from reframe.naming.template import Value

__all__ = [
    "CONTAINER_LABELS",
    "NameContext",
    "audio_channels_label",
    "build_values",
    "hdr_label",
    "resolution_label",
]

CONTAINER_LABELS: dict[Container, str] = {"mkv": "MKV", "mp4": "MP4", "webm": "WebM"}

#: Named resolutions, largest first: :func:`resolution_label` returns the first one that fits.
_RESOLUTIONS = (
    ("2160p", 3840, 2160),
    ("1080p", 1920, 1080),
    ("720p", 1280, 720),
    ("576p", 1024, 576),
    ("480p", 854, 480),
)

#: ffprobe codec name → definitions ``VideoCodec`` (for ``{codec}`` of a video passthrough).
_SOURCE_CODECS = {"mpeg2video": "mpeg2", "h264": "h264", "hevc": "hevc", "av1": "av1", "vp9": "vp9"}

_HDR_LABELS = (
    (HdrFormat.DOLBY_VISION, "DV"),
    (HdrFormat.HDR10_PLUS, "HDR10+"),
    (HdrFormat.HDR10, "HDR10"),
    (HdrFormat.HLG, "HLG"),
)


def resolution_label(width: int, height: int) -> str:
    """The ``{resolution}`` label: the first named class that the size fits, else ``WxH``.

    A size fits a class when it is at most 1/14 wider (DCI) and not taller than the class's
    frame, and its width or height is within 1/32 of the frame's. So cropped scope (1920x800)
    is ``1080p``, and a cropped DVD (720x432) is ``WxH``.
    """
    for label, frame_w, frame_h in _RESOLUTIONS:
        fits = width <= frame_w + frame_w // 14 and height <= frame_h
        if fits and (width >= frame_w - frame_w // 32 or height >= frame_h - frame_h // 32):
            return label
    return f"{width}x{height}"


def hdr_label(formats: list[HdrFormat]) -> str | None:
    """The ``{hdr}`` label of the highest-ranked HDR format in ``formats``, or None."""
    for fmt, label in _HDR_LABELS:
        if fmt in formats:
            return label
    return None


def audio_channels_label(channels: int, layout: str | None = None) -> str:
    """The ``N.M`` channel label from an ffprobe layout, or else from the channel count."""
    if layout:
        head = layout.split("(", 1)[0]
        named = {"mono": "1.0", "stereo": "2.0", "quad": "4.0", "hexagonal": "6.0"}
        if head in named:
            return named[head]
        if head.replace(".", "").isdigit() and "." in head:
            return head
    return {1: "1.0", 2: "2.0", 3: "2.1", 4: "4.0", 5: "5.0", 6: "5.1", 7: "6.1", 8: "7.1"}.get(
        channels, str(channels)
    )


_MIXDOWN_LABELS = {"mono": "1.0", "stereo": "2.0", "dpl2": "2.0", "5.1": "5.1", "7.1": "7.1"}


@dataclass(frozen=True, slots=True)
class NameContext:
    """Everything the variables are built from."""

    fields: ParsedName
    source_text: str
    """The chosen name source's text (``{source}``)."""
    source_separator: str | None
    file: Path
    file_stem: str
    options: NamingOptions
    container: Container
    now: datetime
    fs: NamingFs
    definitions: Definitions
    job: JobSettings | None = None
    source: MediaSource | None = None
    output_size: tuple[int, int] | None = None
    title_index: int = 1


def _local(value: datetime) -> datetime:
    return value.astimezone() if value.tzinfo is not None else value


def _audio_track(source: MediaSource | None, index: int | None) -> AudioStream | None:
    if source is None or index is None:
        return None
    return next((a for a in source.audio if a.index == index), None)


def _subtitle_track(source: MediaSource | None, index: int) -> SubtitleStream | None:
    if source is None:
        return None
    return next((s for s in source.subtitles if s.index == index), None)


def _effective_language(language: str | None, ietf: str | None = None) -> str | None:
    value = ietf or language
    if value is None or languages.base_language(value) == "und":
        return None
    return value


def _langs(values: list[str | None]) -> str | None:
    known = [v for v in values if v is not None]
    return languages.join_short_codes(known) if known else None


def build_values(ctx: NameContext) -> dict[str, Value]:
    """The value of every variable (``None`` when the data is missing)."""
    fields = ctx.fields
    options = ctx.options

    def text(value: str | None) -> str | None:
        if value is None:
            return None
        return clean_name_text(value, fields.separator, options) or None

    values: dict[str, Value] = {
        "source": clean_name_text(ctx.source_text, ctx.source_separator, options) or None,
        "title": ctx.title_index,
        "date": ctx.now,
        "time": ctx.now,
        "main_title": text(fields.main_title),
        "name": text(fields.name),
        "sub_title": text(fields.sub_title),
        "season": fields.season,
        "episode": fields.episode,
        "episode_code": fields.episode_code,
        "year": fields.year,
        "edition": text(fields.edition),
        "source_type": text(fields.source_type),
        "release_group": fields.release_group,
        "file_name": replace_undecodable(ctx.file_stem) or None,
        "folder_name": replace_undecodable(ctx.file.parent.name) or None,
        "container": CONTAINER_LABELS[ctx.container],
    }
    values.update(_times(ctx))
    values.update(_job_values(ctx))
    return values


def _times(ctx: NameContext) -> dict[str, Value]:
    times = ctx.fs.file_times(ctx.file)
    created: datetime | None = None
    if ctx.source is not None and ctx.source.container.creation_time is not None:
        created = _local(ctx.source.container.creation_time)
    elif times is not None:
        created = times.created
    modified = times.modified if times is not None else None
    return {
        "creation-date": created,
        "creation-time": created,
        "modification-date": modified,
        "modification-time": modified,
        "container_title": (ctx.source.container.title or None) if ctx.source else None,
    }


def _job_values(ctx: NameContext) -> dict[str, Value]:
    job, source, defs = ctx.job, ctx.source, ctx.definitions
    video_stream = source.video[0] if source is not None and source.video else None
    values: dict[str, Value] = {}

    # {chapters}
    chapters: str | None = None
    if job is not None and isinstance(job.range, ChapterRange):
        start, end = job.range.start, job.range.end
        chapters = str(start) if start == end else f"{start}-{end}"
    elif (job is None or isinstance(job.range, FullRange)) and source and source.chapters:
        count = len(source.chapters)
        chapters = "1" if count == 1 else f"1-{count}"
    values["chapters"] = chapters

    passthrough = job is not None and job.video.passthrough
    # {width} {height} {resolution}
    size = ctx.output_size
    if size is None and passthrough and video_stream is not None:
        size = (video_stream.width, video_stream.height)
    values["width"] = size[0] if size else None
    values["height"] = size[1] if size else None
    values["resolution"] = resolution_label(*size) if size else None

    values["preset"] = (job.preset_name or None) if job is not None else None

    # {codec} {encoder} {encoder_bit_depth} {quality_bitrate} {quality_type}
    codec = encoder = quality_type = None
    bit_depth: int | None = None
    quality: float | int | None = None
    if job is not None and not passthrough:
        encoder_def = defs.video_encoders.get(job.video.encoder)
        codec = encoder_def.codec_label if encoder_def else None
        encoder = encoder_def.handbrake_key if encoder_def else job.video.encoder
        bit_depth = job.video.bit_depth
        rate = job.video.rate_control
        if isinstance(rate, ConstantQuality):
            quality, quality_type = rate.value, "Q"
        else:
            quality, quality_type = rate.kbps, "kbps"
    elif passthrough and video_stream is not None:
        family = _SOURCE_CODECS.get(video_stream.codec or "")
        labels = [e.codec_label for e in defs.video_encoders.values() if e.codec == family]
        codec = labels[0] if labels else (video_stream.codec or "").upper() or None
        bit_depth = video_stream.bit_depth
    values.update(
        codec=codec,
        encoder=encoder,
        encoder_bit_depth=bit_depth,
        quality_bitrate=quality,
        quality_type=quality_type,
    )

    # {hdr}: the source's HDR survives a passthrough, or a 10-bit encode without tone mapping.
    hdr: str | None = None
    if video_stream is not None and video_stream.hdr is not None:
        keeps = passthrough or (
            job is not None and job.video.bit_depth == 10 and "tonemap" not in job.filters.root
        )
        if keeps:
            hdr = hdr_label(video_stream.hdr.formats)
    values["hdr"] = hdr

    # {acodec} {audio_channels} {audio_langs} {sub_langs}
    acodec = channels = audio_langs = sub_langs = None
    if job is not None:
        if job.audio:
            first = job.audio[0]
            track = _audio_track(source, first.source_stream)
            if first.action == "passthru" and track is not None:
                acodec = track.display_codec or (track.codec or "").upper() or None
            elif first.action == "encode" and first.encoder is not None:
                audio_def = defs.audio_encoders.get(first.encoder)
                acodec = audio_def.label if audio_def else first.encoder
            if first.mixdown is not None and first.action == "encode":
                channels = _MIXDOWN_LABELS[first.mixdown]
            elif track is not None and track.channels:
                channels = audio_channels_label(track.channels, track.channel_layout)
        audio_langs = _langs(
            [
                t.metadata.language
                or _effective_language(*_stream_language(_audio_track(source, t.source_stream)))
                for t in job.audio
            ]
        )
        subs: list[str | None] = []
        for sub in job.subtitles:
            if sub.action == "burn":
                continue  # burned in: not a track of the output
            if sub.metadata.language:
                subs.append(sub.metadata.language)
            elif isinstance(sub.source, int):
                subs.append(
                    _effective_language(*_stream_language(_subtitle_track(source, sub.source)))
                )
            else:
                subs.append(sub.source.language)
        sub_langs = _langs(subs)
    values.update(
        acodec=acodec, audio_channels=channels, audio_langs=audio_langs, sub_langs=sub_langs
    )
    return values


def _stream_language(stream: AudioStream | SubtitleStream | None) -> tuple[str | None, str | None]:
    if stream is None:
        return None, None
    return stream.language, stream.language_ietf
