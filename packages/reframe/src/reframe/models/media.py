"""A probed source file (C-3): container, streams, chapters, attachments.

``MediaSource`` is what ``reframe probe FILE --json`` prints and what the probe cache stores
(so these are document models with ``schema_version``). C-3 fills it from
``ffprobe -show_format -show_streams -show_chapters -show_programs`` plus enrichment.

Conventions:

- ``index`` is the **absolute stream index** in the file (ffprobe ``index``, the number in
  ``-map 0:3``). ``type_index`` is the index among streams of the same type (``0:a:1``).
- Times are seconds (float). Bit rates are bits per second.
- ``start_time`` is ffprobe's raw ``start_time``: the timestamp of the stream's first packet
  (an M2TS or a Blu-ray stream can start at 1.4 s or 600 s). ``delay`` is the start relative
  to the main video stream (else the container start): this is the audio delay that the UI
  shows, as mkvmerge and HandBrake do. Both are ``None`` when ffprobe does not say.
- Attached pictures (cover art, ``disposition.attached_pic``) are **not** video tracks: they
  are in :attr:`MediaSource.cover_art`, never in :attr:`MediaSource.video`.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from reframe.models.base import (
    DocumentModel,
    LanguageTag,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveInt,
    Rational,
)

__all__ = [
    "AttachedPicture",
    "Attachment",
    "AudioStream",
    "BitrateInfo",
    "BitrateSource",
    "Chapter",
    "ColorInfo",
    "ContainerInfo",
    "ContentLightLevel",
    "DataStream",
    "Disposition",
    "DolbyVisionInfo",
    "FieldOrder",
    "HdrFormat",
    "HdrInfo",
    "MasteringDisplay",
    "MediaSource",
    "RoleEvidence",
    "SourceFingerprint",
    "SourceRef",
    "SourceStream",
    "SubtitleKind",
    "SubtitleStream",
    "TrackRole",
    "TrackRoleInfo",
    "VideoStream",
]


# --------------------------------------------------------------------------- source identity


class SourceFingerprint(DocumentModel):
    """Identifies one version of a file: a change in size or mtime means "probe again".

    ``mtime`` is seconds as a float (not nanoseconds): a JavaScript client keeps a float
    exactly, but not an integer above 2**53.
    """

    size: NonNegativeInt
    mtime: float
    probe_hash: str | None = None
    """A hash of the probe result (stream layout); ``None`` before the file is probed."""


class SourceRef(DocumentModel):
    """A reference from a job to its source file."""

    path: Path
    """Absolute path of the source file."""
    fingerprint: SourceFingerprint | None = None
    """``None`` when the job was created without probing (for example from the CLI)."""


# --------------------------------------------------------------------------- flags and roles


class Disposition(DocumentModel):
    """Every ffprobe disposition flag (FFmpeg n9.0.2 prints exactly these 19).

    Which flags survive a Matroska mux is recorded in ``testdata/README.md`` ("Verified tool
    behaviour"): ``captions``, ``lyrics``, ``karaoke``, ``metadata``, ``dependent`` and
    ``still_image`` are lost; ``descriptions`` only on subtitle tracks.
    """

    default: bool = False
    dub: bool = False
    original: bool = False
    comment: bool = False
    lyrics: bool = False
    karaoke: bool = False
    forced: bool = False
    hearing_impaired: bool = False
    visual_impaired: bool = False
    clean_effects: bool = False
    attached_pic: bool = False
    timed_thumbnails: bool = False
    non_diegetic: bool = False
    captions: bool = False
    descriptions: bool = False
    metadata: bool = False
    dependent: bool = False
    still_image: bool = False
    multilayer: bool = False


class TrackRole(StrEnum):
    """What a track is for. One vocabulary for audio and subtitles.

    Reconciles the badges of 03 §Audio (``Main``, ``Commentary``, ``Audio description``,
    ``Music only``) and 03 §Subtitles (``Forced``, ``SDH``, ``Signs & Songs``, ``Commentary``)
    with 04's ``TrackSelector.roles`` (main, commentary, description, sdh, forced, signs).
    """

    MAIN = "main"
    COMMENTARY = "commentary"
    DESCRIPTION = "description"
    """Audio description for the visually impaired (or text descriptions on subtitles)."""
    MUSIC = "music"
    """Music only / isolated score."""
    SDH = "sdh"
    """Subtitles for the deaf and hard of hearing (``hearing_impaired``)."""
    FORCED = "forced"
    """Forced subtitles (foreign parts only)."""
    SIGNS = "signs"
    """Signs & Songs."""


class RoleEvidence(StrEnum):
    """Why a role was given. The UI shows a solid badge for ``flag``, outlined otherwise."""

    FLAG = "flag"
    """A disposition flag in the file (for example ``comment``)."""
    TITLE = "title"
    """A keyword in the track title (``Commentary``, ``SDH``, ``Signs``…)."""
    HEURISTIC = "heuristic"
    """The structure (for example a low-bitrate 2.0 track next to a 5.1 main track)."""


class TrackRoleInfo(DocumentModel):
    role: TrackRole
    evidence: RoleEvidence
    detail: str | None = None
    """For the tooltip: ``disposition comment``, ``title contains "Commentary"``…"""


# --------------------------------------------------------------------------- bit rate


class BitrateSource(StrEnum):
    """Where a bit rate came from (C-3 bitrate chain, then a measurement on request)."""

    STREAM = "stream"
    """ffprobe stream ``bit_rate``."""
    STATS_TAG = "stats_tag"
    """Matroska statistics tags (``BPS``, ``NUMBER_OF_BYTES`` / ``DURATION``)."""
    MEDIAINFO = "mediainfo"
    MEASURED = "measured"
    """A packet-size scan (C-10)."""
    UNKNOWN = "unknown"


class BitrateInfo(DocumentModel):
    """A bit rate and its source. ``value`` is ``None`` exactly when ``source`` is ``unknown``
    (C-12 treats an unknown bit rate as above every maximum)."""

    value: NonNegativeInt | None = None
    """Bits per second."""
    source: BitrateSource = BitrateSource.UNKNOWN

    @model_validator(mode="after")
    def _value_matches_source(self) -> BitrateInfo:
        if (self.value is None) != (self.source is BitrateSource.UNKNOWN):
            raise ValueError("value must be None exactly when source is 'unknown'")
        return self


# --------------------------------------------------------------------------- colour and HDR


class ColorInfo(DocumentModel):
    """Colour properties with ffprobe's names (``bt2020``, ``smpte2084``, ``bt2020nc``)."""

    primaries: str | None = None
    transfer: str | None = None
    matrix: str | None = None
    """ffprobe ``color_space``."""
    range: Literal["tv", "pc"] | None = None
    """``tv`` = limited, ``pc`` = full."""
    chroma_location: str | None = None


class HdrFormat(StrEnum):
    HDR10 = "hdr10"
    HDR10_PLUS = "hdr10plus"
    HLG = "hlg"
    DOLBY_VISION = "dolby_vision"


class MasteringDisplay(DocumentModel):
    """SMPTE ST 2086 mastering display colour volume: CIE 1931 xy chromaticities and cd/m²."""

    red_x: float
    red_y: float
    green_x: float
    green_y: float
    blue_x: float
    blue_y: float
    white_x: float
    white_y: float
    min_luminance: NonNegativeFloat
    max_luminance: NonNegativeFloat


class ContentLightLevel(DocumentModel):
    """CTA-861.3 content light level, cd/m²."""

    max_cll: NonNegativeInt
    max_fall: NonNegativeInt


class DolbyVisionInfo(DocumentModel):
    """The DOVI configuration record."""

    profile: NonNegativeInt
    """5, 7, 8, …"""
    level: NonNegativeInt | None = None
    rpu_present: bool = True
    el_present: bool = False
    bl_present: bool = True
    bl_signal_compatibility_id: NonNegativeInt | None = None
    """For profile 8: 1 = HDR10, 2 = SDR, 4 = HLG (8.1 / 8.2 / 8.4)."""


class HdrInfo(DocumentModel):
    """HDR metadata of a video stream. ``formats`` may hold several (HDR10 + Dolby Vision 8.1)."""

    formats: list[HdrFormat] = Field(default_factory=list)
    mastering_display: MasteringDisplay | None = None
    content_light: ContentLightLevel | None = None
    dolby_vision: DolbyVisionInfo | None = None
    source: Literal["stream", "frame"] = "stream"
    """Where the side data was read: stream side data, or the first frame's (C-3 fallback)."""


# --------------------------------------------------------------------------- streams


class FieldOrder(StrEnum):
    """ffprobe ``field_order``: ``tt`` and ``tb`` are both top field first, ``bb`` and ``bt``
    bottom field first (FFmpeg writes ``tb`` for TFF H.264; see testdata/README.md)."""

    PROGRESSIVE = "progressive"
    TOP_FIRST = "tff"
    BOTTOM_FIRST = "bff"
    UNKNOWN = "unknown"


class _StreamBase(DocumentModel):
    index: NonNegativeInt
    """Absolute stream index in the file (``-map 0:<index>``)."""
    type_index: NonNegativeInt = 0
    """Index among streams of the same type (``0:a:<type_index>``)."""
    codec: str | None = None
    """ffprobe ``codec_name`` (``hevc``, ``truehd``, ``subrip``)."""
    codec_long: str | None = None
    """ffprobe ``codec_long_name``."""
    profile: str | None = None
    """ffprobe ``profile`` (``Main 10``, ``DTS-HD MA``)."""
    language: LanguageTag | None = None
    """The language tag as ffprobe reports it (``eng``, ``hun``; for Matroska the legacy
    ISO 639-2 ``Language`` element); ``None`` if absent."""
    language_ietf: LanguageTag | None = None
    """The BCP 47 tag as MediaInfo reports it (``pt-BR``, ``zh-Hant``): for Matroska the
    ``LanguageIETF`` element, which ffprobe does not show (after ``mkvpropedit --set
    language=pt-BR`` ffprobe says ``por``). ``None`` when MediaInfo is not available.

    The **effective language** (what C-12 track rules match) is ``language_ietf`` if set, else
    ``language``."""
    title: str | None = None
    disposition: Disposition = Field(default_factory=Disposition)
    start_time: float | None = None
    """ffprobe's raw ``start_time`` in seconds (the first packet's timestamp)."""
    delay: float | None = None
    """Seconds relative to the main video stream's ``start_time`` (or the container's
    ``start_time`` when there is no video); negative = starts earlier. The audio delay of the
    UI."""
    duration: NonNegativeFloat | None = None
    frame_count: NonNegativeInt | None = None
    tags: dict[str, str] = Field(default_factory=dict)
    """All stream tags as ffprobe prints them."""


class VideoStream(_StreamBase):
    kind: Literal["video"] = "video"
    display_codec: str | None = None
    """Commercial name: ``HEVC Main 10``, ``H.264 High``, ``AV1``."""
    level: int | None = None
    """ffprobe ``level`` (H.264 ``41``, HEVC ``150``); ``None`` when unknown (``-99``)."""
    width: PositiveInt
    height: PositiveInt
    sar: Rational | None = None
    """Sample (pixel) aspect ratio; ``None`` when unknown (``0:1``)."""
    dar: Rational | None = None
    pix_fmt: str | None = None
    bit_depth: PositiveInt | None = None
    frame_rate: Rational | None = None
    """ffprobe ``r_frame_rate`` (the base rate); ``None`` for ``0/0``."""
    avg_frame_rate: Rational | None = None
    """ffprobe ``avg_frame_rate``; ``None`` for ``0/0`` (Matroska written by FFmpeg)."""
    vfr: bool = False
    """Variable frame rate: ``r_frame_rate`` ≠ ``avg_frame_rate`` (C-3 decides when the
    average is unknown)."""
    field_order: FieldOrder = FieldOrder.UNKNOWN
    rotation: Literal[0, 90, 180, 270] = 0
    """Clockwise rotation from the display matrix, normalised."""
    color: ColorInfo = Field(default_factory=ColorInfo)
    hdr: HdrInfo | None = None
    """``None`` for SDR."""
    closed_captions: bool = False
    """ffprobe ``closed_captions`` (A/53 captions inside the video stream)."""
    bitrate: BitrateInfo = Field(default_factory=BitrateInfo)


class AudioStream(_StreamBase):
    kind: Literal["audio"] = "audio"
    display_codec: str | None = None
    """Commercial name: ``TrueHD Atmos``, ``DTS-HD MA``, ``DTS:X``, ``E-AC-3 Atmos``, ``AAC-LC``."""
    channels: NonNegativeInt = 0
    channel_layout: str | None = None
    """ffprobe ``channel_layout`` (``5.1(side)``)."""
    sample_rate: PositiveInt | None = None
    bit_depth: PositiveInt | None = None
    sample_fmt: str | None = None
    lossless: bool = False
    """TrueHD, DTS-HD MA, FLAC, PCM, ALAC: encoded at the maximum by codec rules (03)."""
    bitrate: BitrateInfo = Field(default_factory=BitrateInfo)
    roles: list[TrackRoleInfo] = Field(default_factory=list)


SubtitleKind = Literal["text", "bitmap"]


class SubtitleStream(_StreamBase):
    kind: Literal["subtitle"] = "subtitle"
    display_codec: str | None = None
    """``SRT``, ``ASS``, ``PGS``, ``VobSub``, ``WebVTT``, ``mov_text``."""
    subtitle_kind: SubtitleKind = "text"
    width: PositiveInt | None = None
    """Bitmap subtitles: canvas size."""
    height: PositiveInt | None = None
    event_count: NonNegativeInt | None = None
    """Number of subtitle events (``NUMBER_OF_FRAMES`` tag or a scan); ``None`` if unknown."""
    event_count_source: Literal["stats_tag", "measured"] | None = None
    forced_event_count: NonNegativeInt | None = None
    """PGS: events with the forced flag (decode scan, C-10)."""
    roles: list[TrackRoleInfo] = Field(default_factory=list)


class Attachment(DocumentModel):
    """A Matroska attachment (fonts for ASS subtitles)."""

    index: NonNegativeInt
    filename: str | None = None
    mimetype: str | None = None
    size: NonNegativeInt | None = None
    codec: str | None = None
    """ffprobe ``codec_name`` (``ttf``, ``otf``), if any."""
    tags: dict[str, str] = Field(default_factory=dict)


class AttachedPicture(DocumentModel):
    """Cover art: a video stream with ``disposition.attached_pic``. Not a video track."""

    index: NonNegativeInt
    codec: str | None = None
    """``mjpeg``, ``png``."""
    width: PositiveInt | None = None
    height: PositiveInt | None = None
    filename: str | None = None
    title: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)


class DataStream(DocumentModel):
    """A data stream (timecode tracks, ``bin_data``, unknown streams)."""

    index: NonNegativeInt
    codec: str | None = None
    codec_tag: str | None = None
    title: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)


class Chapter(DocumentModel):
    index: NonNegativeInt
    """Position (0-based) in the chapter list."""
    start: NonNegativeFloat
    end: NonNegativeFloat
    title: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)


class ContainerInfo(DocumentModel):
    format_name: str | None = None
    """ffprobe ``format_name`` (``matroska,webm``, ``mov,mp4,m4a,3gp,3g2,mj2``)."""
    format_long_name: str | None = None
    display_name: str | None = None
    """``MKV``, ``MP4``, ``WebM``, ``M2TS``."""
    duration: NonNegativeFloat | None = None
    """``None`` when ffprobe reports no duration."""
    size: NonNegativeInt | None = None
    bitrate: NonNegativeInt | None = None
    """Overall bit rate, bits per second."""
    start_time: float | None = None
    title: str | None = None
    creation_time: AwareDatetime | None = None
    tags: dict[str, str] = Field(default_factory=dict)


class MediaSource(DocumentModel):
    """Everything Reframe knows about one source file.

    Known gap: ``-show_programs`` output (the programs of a multi-program MPEG-TS) has no model
    yet; C-3 reads streams across all programs.
    """

    schema_version: PositiveInt = 1
    ref: SourceRef
    container: ContainerInfo = Field(default_factory=ContainerInfo)
    video: list[VideoStream] = Field(default_factory=list)
    audio: list[AudioStream] = Field(default_factory=list)
    subtitles: list[SubtitleStream] = Field(default_factory=list)
    attachments: list[Attachment] = Field(default_factory=list)
    cover_art: list[AttachedPicture] = Field(default_factory=list)
    data: list[DataStream] = Field(default_factory=list)
    chapters: list[Chapter] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    """Problems found while probing (missing duration, unreadable side data…)."""
    probed_at: AwareDatetime | None = None
    probe_tool: str | None = None
    """The ffprobe version that produced it (``n9.0.2-17-g2a571b6068-20260930``)."""


#: Any stream of a source (audio, video, subtitle), discriminated by ``kind``.
SourceStream = Annotated[VideoStream | AudioStream | SubtitleStream, Field(discriminator="kind")]
