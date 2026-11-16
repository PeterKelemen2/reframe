"""ffprobe JSON → :class:`~reframe.models.MediaSource`. Pure: no I/O.

Expected problems become warnings on the source, not exceptions.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import ValidationError

from reframe import languages
from reframe.models.base import Rational, is_language_tag
from reframe.models.media import (
    AttachedPicture,
    Attachment,
    AudioStream,
    Chapter,
    ColorInfo,
    ContainerInfo,
    DataStream,
    Disposition,
    FieldOrder,
    MediaSource,
    SourceFingerprint,
    SourceRef,
    SubtitleStream,
    VideoStream,
)
from reframe.probe import hdr, names, roles
from reframe.probe.bitrate import (
    StatsCheck,
    check_stats_tags,
    parse_duration_tag,
    positive_int,
    stream_bitrate,
    tag_value,
)
from reframe.probe.matroska import MatroskaFile, TrackKind, tracks_by_kind

__all__ = [
    "PARSER_VERSION",
    "compressed_streams",
    "layout_hash",
    "main_video_index",
    "main_video_stream",
    "parse_ffprobe",
    "parse_rational",
    "vfr_from_timestamps",
    "vfr_undecided",
    "video_bit_depth",
]

#: Bump when the parser changes what it produces: the probe cache drops older entries.
PARSER_VERSION = 2

_UNKNOWN = frozenset({"", "unknown", "unspecified", "reserved", "N/A"})
_PIX_FMT_DEPTH_RE = re.compile(r"(\d{1,2})(?:le|be)$")
_EIGHT_BIT_PIX_FMTS = frozenset(
    {
        "yuv420p",
        "yuvj420p",
        "yuv422p",
        "yuvj422p",
        "yuv444p",
        "yuvj444p",
        "yuv411p",
        "yuv410p",
        "yuv440p",
        "nv12",
        "nv21",
        "nv16",
        "gray",
        "rgb24",
        "bgr24",
        "rgba",
        "bgra",
        "argb",
        "abgr",
        "yuva420p",
        "pal8",
    }
)
_VFR_TOLERANCE = 0.005
#: Statistics frame rate vs ``avg_frame_rate`` (Matroska): more than this is VFR.
_STATS_VFR_TOLERANCE = 0.01
_FIELD_ORDERS: Mapping[str, FieldOrder] = {
    "progressive": FieldOrder.PROGRESSIVE,
    "tt": FieldOrder.TOP_FIRST,
    "tb": FieldOrder.TOP_FIRST,
    "bb": FieldOrder.BOTTOM_FIRST,
    "bt": FieldOrder.BOTTOM_FIRST,
}


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    return None if text in _UNKNOWN else text


def _float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _nonneg(value: Any) -> float | None:
    number = _float(value)
    return number if number is not None and number >= 0 else None


def _int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        number = _float(value)
        return int(number) if number is not None else None


def _tags(raw: Any) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        return {}
    return {str(key): str(value) for key, value in raw.items()}


def parse_rational(value: Any) -> Rational | None:
    """Parse ffprobe's ``num/den`` (or ``num:den``) text; zero, negative and junk give ``None``."""
    text = _text(value)
    if text is None:
        return None
    parts = re.split(r"[/:]", text)
    if len(parts) != 2:
        return None
    try:
        num, den = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if num <= 0 or den <= 0:
        return None
    frac = Fraction(num, den)
    return Rational(num=frac.numerator, den=frac.denominator)


def _language(tags: Mapping[str, str], warnings: list[str], index: int) -> str | None:
    value = tag_value(tags, "language")
    if value is None or not value.strip():
        return None
    value = value.strip()
    if not is_language_tag(value):
        warnings.append(f"Stream {index}: language tag {value!r} is not a language code.")
        return None
    return value


def _bcp47(language: str | None) -> str | None:
    """The BCP 47 tag of an ISO 639 code; ``None`` for ``und`` and for codes without one."""
    tag = languages.normalize(language)
    if tag is None or tag == languages.UNDETERMINED or not is_language_tag(tag):
        return None
    return tag


def _disposition(raw: Any) -> Disposition:
    if not isinstance(raw, Mapping):
        return Disposition()
    known = Disposition.model_fields
    return Disposition.model_validate(
        {key: bool(_int(value)) for key, value in raw.items() if key in known}
    )


def video_bit_depth(stream: Mapping[str, Any]) -> int | None:
    """``bits_per_raw_sample``, else derived from ``pix_fmt`` (``yuv420p10le`` → 10)."""
    depth = positive_int(stream.get("bits_per_raw_sample"))
    if depth is not None:
        return depth
    pix_fmt = _text(stream.get("pix_fmt"))
    if pix_fmt is None:
        return None
    match = _PIX_FMT_DEPTH_RE.search(pix_fmt)
    if match is not None:
        return int(match.group(1))
    return 8 if pix_fmt in _EIGHT_BIT_PIX_FMTS else None


def _color_range(value: Any) -> Literal["tv", "pc"] | None:
    if value == "tv":
        return "tv"
    if value == "pc":
        return "pc"
    return None


def _is_cover_art(stream: Mapping[str, Any]) -> bool:
    disposition = stream.get("disposition")
    return isinstance(disposition, Mapping) and bool(_int(disposition.get("attached_pic")))


def main_video_index(data: Mapping[str, Any]) -> int | None:
    """Absolute index of the first video stream that is not cover art."""
    main = main_video_stream(data)
    return None if main is None else main[0]


def main_video_stream(data: Mapping[str, Any]) -> tuple[int, Mapping[str, Any]] | None:
    """The first video stream that is not cover art, with its absolute index."""
    for stream in _streams(data):
        if stream.get("codec_type") == "video" and not _is_cover_art(stream):
            index = _int(stream.get("index"))
            if index is not None and index >= 0:
                return index, stream
    return None


def _streams(data: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = data.get("streams")
    if not isinstance(raw, list):
        return []
    return [stream for stream in raw if isinstance(stream, Mapping)]


def _first_frame(frames: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if frames is None:
        return None
    raw = frames.get("frames")
    if not isinstance(raw, list):
        return None
    usable = [frame for frame in raw if isinstance(frame, Mapping)]
    for frame in usable:
        if frame.get("side_data_list"):
            return frame
    return usable[0] if usable else None


def _rotation(stream: Mapping[str, Any], tags: Mapping[str, str]) -> Literal[0, 90, 180, 270]:
    degrees: float | None = None
    side_data = stream.get("side_data_list")
    if isinstance(side_data, list):
        for entry in side_data:
            if isinstance(entry, Mapping) and entry.get("side_data_type") == "Display Matrix":
                ccw = _float(entry.get("rotation"))
                if ccw is not None:
                    degrees = -ccw
                break
    if degrees is None:
        degrees = _float(tag_value(tags, "rotate"))
    if degrees is None:
        return 0
    quarter = round(degrees / 90) % 4
    return cast("Literal[0, 90, 180, 270]", quarter * 90)


@dataclass(frozen=True)
class _Context:
    matroska: bool
    stats: StatsCheck
    reference_start: float | None
    """``start_time`` that ``delay`` is relative to."""


def _field_order(stream: Mapping[str, Any]) -> FieldOrder:
    return _FIELD_ORDERS.get(str(stream.get("field_order", "")), FieldOrder.UNKNOWN)


def _is_ratio(ratio: float, target: float, tolerance: float) -> bool:
    return abs(ratio - target) <= target * tolerance


def _vfr_decision(stream: Mapping[str, Any], ctx: _Context) -> bool | None:
    """VFR from the stream's own data; ``None`` when undecided (see :func:`vfr_undecided`)."""
    r_rate = parse_rational(stream.get("r_frame_rate"))
    avg_rate = parse_rational(stream.get("avg_frame_rate"))
    interlaced = _field_order(stream) in (FieldOrder.TOP_FIRST, FieldOrder.BOTTOM_FIRST)
    if r_rate is None:
        return False
    if avg_rate is None:
        return ctx.matroska
    ratio = float(r_rate) / float(avg_rate)
    if not _is_ratio(ratio, 1, _VFR_TOLERANCE):
        return not (interlaced and _is_ratio(ratio, 2, _VFR_TOLERANCE))
    if not ctx.matroska:
        return False
    index = _int(stream.get("index")) or 0
    tags = _tags(stream.get("tags"))
    frames = _int(tag_value(tags, "NUMBER_OF_FRAMES"))
    seconds = parse_duration_tag(tag_value(tags, "DURATION"))
    if not ctx.stats.trusted(index) or not frames or not seconds:
        return None
    stats_ratio = frames / seconds / float(avg_rate)
    if _is_ratio(stats_ratio, 1, _STATS_VFR_TOLERANCE):
        return False
    return not (interlaced and _is_ratio(stats_ratio, 0.5, _STATS_VFR_TOLERANCE))


def compressed_streams(data: Mapping[str, Any], matroska: MatroskaFile | None) -> set[int]:
    """The indexes of the streams whose Matroska track has compressed blocks. The n-th video,
    audio and subtitle track is the n-th stream of that kind (cover art is not a track); when
    the counts differ, none."""
    if matroska is None:
        return set()
    found: dict[TrackKind, list[int]] = {"video": [], "audio": [], "subtitle": []}
    for stream in _streams(data):
        kind = stream.get("codec_type")
        if kind in ("audio", "subtitle") or (kind == "video" and not _is_cover_art(stream)):
            found[cast("TrackKind", kind)].append(_int(stream.get("index")) or 0)
    tracks = tracks_by_kind(matroska)
    if any(len(indexes) != len(tracks[kind]) for kind, indexes in found.items()):
        return set()
    return {
        index
        for kind, indexes in found.items()
        for index, track in zip(indexes, tracks[kind], strict=True)
        if track.compressed
    }


def _context(
    data: Mapping[str, Any], fmt: Mapping[str, Any], matroska: MatroskaFile | None = None
) -> _Context:
    format_name = str(fmt.get("format_name") or "")
    main = main_video_index(data)
    reference: float | None = None
    for stream in _streams(data):
        if main is not None and _int(stream.get("index")) == main:
            reference = _float(stream.get("start_time"))
    if reference is None:
        reference = _float(fmt.get("start_time"))
    stats = check_stats_tags(data, compressed=compressed_streams(data, matroska))
    return _Context(format_name.startswith("matroska"), stats, reference)


def vfr_undecided(data: Mapping[str, Any], *, matroska: MatroskaFile | None = None) -> list[int]:
    """Indexes of the video streams whose VFR state ffprobe's output cannot tell (Matroska
    with a known average frame rate and no usable statistics tags). ``matroska``: the file's
    track headers, as for :func:`parse_ffprobe`."""
    fmt_raw = data.get("format")
    ctx = _context(data, fmt_raw if isinstance(fmt_raw, Mapping) else {}, matroska)
    undecided: list[int] = []
    for stream in _streams(data):
        if stream.get("codec_type") != "video" or _is_cover_art(stream):
            continue
        if _vfr_decision(stream, ctx) is None:
            undecided.append(_int(stream.get("index")) or 0)
    return undecided


def vfr_from_timestamps(pts: Sequence[float]) -> bool | None:
    """VFR from a sample of packet timestamps in seconds (any order); ``None`` when there are
    too few.

    A step is different when it is more than max(2.5 ms, 10 %) away from the median step. VFR
    when more than 5 % of the steps are different, so one dropped frame is not VFR.
    """
    ordered = sorted(pts)
    steps = [b - a for a, b in pairwise(ordered) if b - a > 0]
    if len(steps) < 10:
        return None
    median = sorted(steps)[len(steps) // 2]
    tolerance = max(0.0025, 0.1 * median)
    different = sum(1 for step in steps if abs(step - median) > tolerance)
    return different > 0.05 * len(steps)


def _duration(stream: Mapping[str, Any], tags: Mapping[str, str]) -> float | None:
    duration = _nonneg(stream.get("duration"))
    if duration is None:
        duration = parse_duration_tag(tag_value(tags, "DURATION"))
    return duration


def _frame_count(stream: Mapping[str, Any], tags: Mapping[str, str], trusted: bool) -> int | None:
    count = _int(stream.get("nb_frames"))
    if (count is None or count < 0) and trusted:
        count = _int(tag_value(tags, "NUMBER_OF_FRAMES"))
    return count if count is not None and count >= 0 else None


def _common(
    stream: Mapping[str, Any], type_index: int, warnings: list[str], ctx: _Context
) -> dict[str, Any]:
    index = _int(stream.get("index")) or 0
    tags = _tags(stream.get("tags"))
    start = _float(stream.get("start_time"))
    delay = (
        round(start - ctx.reference_start, 6)
        if start is not None and ctx.reference_start is not None
        else None
    )
    language = _language(tags, warnings, index)
    return {
        "index": index,
        "type_index": type_index,
        "codec": _text(stream.get("codec_name")),
        "codec_long": _text(stream.get("codec_long_name")),
        "profile": _text(stream.get("profile")),
        "language": language,
        "language_ietf": None if ctx.matroska else _bcp47(language),
        "title": _text(tag_value(tags, "title")) or _text(tag_value(tags, "name")),
        "disposition": _disposition(stream.get("disposition")),
        "start_time": start,
        "delay": delay,
        "duration": _duration(stream, tags),
        "frame_count": _frame_count(stream, tags, ctx.stats.trusted(index)),
        "tags": tags,
    }


def _video(
    stream: Mapping[str, Any],
    common: dict[str, Any],
    frame: Mapping[str, Any] | None,
    ctx: _Context,
) -> VideoStream:
    field_order = _field_order(stream)
    r_rate = parse_rational(stream.get("r_frame_rate"))
    avg_rate = parse_rational(stream.get("avg_frame_rate"))
    level = _int(stream.get("level"))
    return VideoStream(
        **common,
        display_codec=names.video_display_name(common["codec"], common["profile"]),
        level=None if level is None or level < 0 else level,
        width=positive_int(stream.get("width")) or 1,
        height=positive_int(stream.get("height")) or 1,
        sar=parse_rational(stream.get("sample_aspect_ratio")),
        dar=parse_rational(stream.get("display_aspect_ratio")),
        pix_fmt=_text(stream.get("pix_fmt")),
        bit_depth=video_bit_depth(stream),
        frame_rate=r_rate,
        avg_frame_rate=avg_rate,
        vfr=bool(_vfr_decision(stream, ctx)),
        field_order=field_order,
        rotation=_rotation(stream, common["tags"]),
        color=ColorInfo(
            primaries=_text(stream.get("color_primaries")),
            transfer=_text(stream.get("color_transfer")),
            matrix=_text(stream.get("color_space")),
            range=_color_range(stream.get("color_range")),
            chroma_location=_text(stream.get("chroma_location")),
        ),
        hdr=hdr.parse_hdr(stream, frame),
        closed_captions=bool(_int(stream.get("closed_captions"))),
        bitrate=stream_bitrate(stream, trust_stats=ctx.stats.trusted(common["index"])),
    )


def _audio(stream: Mapping[str, Any], common: dict[str, Any], ctx: _Context) -> AudioStream:
    codec, profile = common["codec"], common["profile"]
    depth = positive_int(stream.get("bits_per_raw_sample")) or positive_int(
        stream.get("bits_per_sample")
    )
    return AudioStream(
        **common,
        display_codec=names.audio_display_name(codec, profile),
        channels=max(_int(stream.get("channels")) or 0, 0),
        channel_layout=_text(stream.get("channel_layout")),
        sample_rate=positive_int(stream.get("sample_rate")),
        bit_depth=depth,
        sample_fmt=_text(stream.get("sample_fmt")),
        lossless=names.is_lossless_audio(codec, profile),
        bitrate=stream_bitrate(stream, trust_stats=ctx.stats.trusted(common["index"])),
    )


def _subtitle(stream: Mapping[str, Any], common: dict[str, Any], ctx: _Context) -> SubtitleStream:
    codec = common["codec"]
    bitmap = codec in names.BITMAP_SUBTITLE_CODECS
    events = _int(tag_value(common["tags"], "NUMBER_OF_FRAMES"))
    if not ctx.stats.trusted(common["index"]) or (events is not None and events < 0):
        events = None
    return SubtitleStream(
        **common,
        display_codec=names.subtitle_display_name(codec),
        subtitle_kind="bitmap" if bitmap else "text",
        width=positive_int(stream.get("width")) if bitmap else None,
        height=positive_int(stream.get("height")) if bitmap else None,
        event_count=events,
        event_count_source="stats_tag" if events is not None else None,
    )


def _attachment(stream: Mapping[str, Any]) -> Attachment:
    tags = _tags(stream.get("tags"))
    size = _int(stream.get("extradata_size"))
    return Attachment(
        index=_int(stream.get("index")) or 0,
        filename=tag_value(tags, "filename"),
        mimetype=tag_value(tags, "mimetype"),
        size=size if size is not None and size >= 0 else None,
        codec=_text(stream.get("codec_name")),
        tags=tags,
    )


def _cover_art(stream: Mapping[str, Any]) -> AttachedPicture:
    tags = _tags(stream.get("tags"))
    return AttachedPicture(
        index=_int(stream.get("index")) or 0,
        codec=_text(stream.get("codec_name")),
        width=positive_int(stream.get("width")),
        height=positive_int(stream.get("height")),
        filename=tag_value(tags, "filename"),
        title=_text(tag_value(tags, "title")) or _text(tag_value(tags, "comment")),
        tags=tags,
    )


def _data(stream: Mapping[str, Any]) -> DataStream:
    tags = _tags(stream.get("tags"))
    codec_tag = _text(stream.get("codec_tag_string"))
    return DataStream(
        index=_int(stream.get("index")) or 0,
        codec=_text(stream.get("codec_name")),
        codec_tag=None if codec_tag is None or codec_tag.startswith("[0]") else codec_tag,
        title=_text(tag_value(tags, "title")) or _text(tag_value(tags, "handler_name")),
        tags=tags,
    )


def _creation_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _container(fmt: Mapping[str, Any], path: Path, warnings: list[str]) -> ContainerInfo:
    tags = _tags(fmt.get("tags"))
    format_name = _text(fmt.get("format_name"))
    duration = _nonneg(fmt.get("duration"))
    if duration is None:
        warnings.append("The container reports no duration.")
    size = _int(fmt.get("size"))
    return ContainerInfo(
        format_name=format_name,
        format_long_name=_text(fmt.get("format_long_name")),
        display_name=names.container_display_name(format_name, path.name),
        duration=duration,
        size=size if size is not None and size >= 0 else None,
        bitrate=positive_int(fmt.get("bit_rate")),
        start_time=_float(fmt.get("start_time")),
        title=_text(tag_value(tags, "title")),
        creation_time=_creation_time(tag_value(tags, "creation_time")),
        tags=tags,
    )


def _chapters(raw: Any) -> list[Chapter]:
    if not isinstance(raw, list):
        return []
    chapters: list[Chapter] = []
    for chapter in raw:
        if not isinstance(chapter, Mapping):
            continue
        start = max(_float(chapter.get("start_time")) or 0.0, 0.0)
        end = max(_float(chapter.get("end_time")) or start, start)
        tags = _tags(chapter.get("tags"))
        chapters.append(
            Chapter(
                index=len(chapters),
                start=start,
                end=end,
                title=_text(tag_value(tags, "title")),
                tags=tags,
            )
        )
    return chapters


def layout_hash(source: MediaSource) -> str:
    """A short hash of the stream layout (for :attr:`SourceFingerprint.probe_hash`)."""
    layout: list[Sequence[Any]] = []
    for v in source.video:
        layout.append(("v", v.index, v.codec, v.profile, v.width, v.height))
    for a in source.audio:
        layout.append(("a", a.index, a.codec, a.profile, a.channels, a.language, a.title))
    for s in source.subtitles:
        layout.append(("s", s.index, s.codec, s.language, s.title))
    for t in source.attachments:
        layout.append(("t", t.index, t.filename, t.size))
    layout.append(("d", source.container.duration, len(source.chapters)))
    text = json.dumps(layout, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def parse_ffprobe(
    data: Mapping[str, Any],
    path: Path,
    *,
    frames: Mapping[str, Any] | None = None,
    fingerprint: SourceFingerprint | None = None,
    probe_tool: str | None = None,
    probed_at: datetime | None = None,
    warnings: Sequence[str] = (),
    matroska: MatroskaFile | None = None,
) -> MediaSource:
    """Build a :class:`MediaSource` from ffprobe JSON.

    :param frames: ``-show_frames`` JSON of the main video stream (first frame), for HDR side
        data when the stream has none.
    :param matroska: the file's Matroska track headers, if read: a track with compressed
        blocks is left out of the statistics tags' size check.
    :param warnings: problems found before parsing (for example "the frame side data could not
        be read"); the parser adds its own.
    :raises pydantic.ValidationError: only for output that no ffprobe produces.
    """
    notes: list[str] = list(warnings)
    fmt_raw = data.get("format")
    fmt: Mapping[str, Any] = fmt_raw if isinstance(fmt_raw, Mapping) else {}
    container = _container(fmt, path, notes)
    ctx = _context(data, fmt, matroska)
    for index, reason in sorted(ctx.stats.stale.items()):
        notes.append(f"Stream {index}: the statistics tags look stale ({reason}); not used.")
    frame = _first_frame(frames)
    main_index = main_video_index(data)

    source = MediaSource(
        ref=SourceRef(path=path, fingerprint=fingerprint),
        container=container,
        chapters=_chapters(data.get("chapters")),
        probe_tool=probe_tool,
        probed_at=probed_at,
    )
    type_counts: dict[str, int] = {}
    for stream in _streams(data):
        codec_type = str(stream.get("codec_type", ""))
        type_index = type_counts.get(codec_type, 0)
        type_counts[codec_type] = type_index + 1
        try:
            if codec_type == "video" and _is_cover_art(stream):
                source.cover_art.append(_cover_art(stream))
            elif codec_type == "video":
                common = _common(stream, type_index, notes, ctx)
                if positive_int(stream.get("width")) is None or not positive_int(
                    stream.get("height")
                ):
                    notes.append(f"Video stream {common['index']} has no frame size.")
                    source.data.append(_data(stream))
                    continue
                own_frame = frame if common["index"] == main_index else None
                source.video.append(_video(stream, common, own_frame, ctx))
            elif codec_type == "audio":
                source.audio.append(_audio(stream, _common(stream, type_index, notes, ctx), ctx))
            elif codec_type == "subtitle":
                common = _common(stream, type_index, notes, ctx)
                source.subtitles.append(_subtitle(stream, common, ctx))
            elif codec_type == "attachment":
                source.attachments.append(_attachment(stream))
            else:
                source.data.append(_data(stream))
        except ValidationError as exc:
            notes.append(
                f"Stream {stream.get('index')} ({codec_type or 'unknown type'}) could not be "
                f"read: {exc.errors()[0].get('msg', exc)}"
            )
    if not _streams(data):
        notes.append("ffprobe found no streams.")
    roles.assign_audio_roles(source.audio)
    roles.assign_subtitle_roles(source.subtitles)
    source.warnings = notes
    if fingerprint is not None:
        source.ref.fingerprint = fingerprint.model_copy(update={"probe_hash": layout_hash(source)})
    return source
