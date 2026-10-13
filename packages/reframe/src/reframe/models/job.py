"""Job settings: everything needed to encode one source (C-2, 03 §Summary … §Tags).

The client edits a ``JobSettings`` (02 §State model) and sends it to the helper endpoints
(validate, plan, preview). The queue stores it (so it is a document model: unknown fields
are kept). Validation fixes are JSON patches on this document.

Encoder ids (``libx265``, ``hevc_nvenc``), filter ids and option keys are strings here: the
definitions (C-6) list the valid values, and validation (C-8) reports unknown ones as issues
instead of failing to load a saved job.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, RootModel

from reframe.models.base import (
    DocumentModel,
    LanguageTag,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveInt,
    Rational,
)
from reframe.models.geometry import DimensionSettings
from reframe.models.media import SourceRef

__all__ = [
    "AudioAction",
    "AudioOutputTrack",
    "AverageBitrate",
    "ChapterRange",
    "ChapterSettings",
    "ConstantQuality",
    "Container",
    "ExternalSubtitle",
    "FilterConfig",
    "FilterSettings",
    "FrameRange",
    "FramerateMode",
    "FullRange",
    "JobNaming",
    "JobSettings",
    "LoudnessTarget",
    "Mixdown",
    "NameSource",
    "OptionValue",
    "OutputOptions",
    "OutputSettings",
    "Range",
    "RateControl",
    "SubtitleAction",
    "SubtitleFormat",
    "SubtitleOutputTrack",
    "TagSettings",
    "TimeRange",
    "TrackFlags",
    "TrackMetadata",
    "VideoSettings",
]

Container = Literal["mkv", "mp4", "webm"]
#: A value of an advanced encoder option (C-6 ``EncoderOption.type``).
OptionValue = bool | int | float | str
NameSource = Literal["auto", "file", "folder"]


# --------------------------------------------------------------------------- track metadata


class TrackFlags(DocumentModel):
    """The six track flags of 03 §Track metadata (Matroska ``Flag*``, FFmpeg dispositions)."""

    default: bool = False
    forced: bool = False
    commentary: bool = False
    hearing_impaired: bool = False
    visual_impaired: bool = False
    original: bool = False


class TrackMetadata(TrackFlags):
    """mkvtoolnix-style metadata of one output track: language, name and the six flags.

    ``language`` ``None`` keeps the source track's language; ``name`` ``None`` keeps the
    source title, and ``""`` writes no title. The client fills explicit flags when it creates
    a track from a source track.
    """

    language: LanguageTag | None = None
    """BCP 47 (``hu``, ``pt-BR``). MKV gets ISO 639-2/B + ``LanguageIETF``, MP4 ISO 639-2/T."""
    name: str | None = None


# --------------------------------------------------------------------------- range


class FullRange(DocumentModel):
    """The whole source (the default)."""

    kind: Literal["full"] = "full"


class ChapterRange(DocumentModel):
    """Chapters ``start`` … ``end``, 1-based and inclusive (as in HandBrake)."""

    kind: Literal["chapters"] = "chapters"
    start: PositiveInt = 1
    end: PositiveInt = 1


class TimeRange(DocumentModel):
    """Seconds from ``start`` to ``end`` (``None`` = to the end)."""

    kind: Literal["time"] = "time"
    start: NonNegativeFloat = 0.0
    end: NonNegativeFloat | None = None


class FrameRange(DocumentModel):
    """Frames ``start`` (0-based) to ``end`` (exclusive; ``None`` = to the end)."""

    kind: Literal["frames"] = "frames"
    start: NonNegativeInt = 0
    end: NonNegativeInt | None = None


#: The part of the source to encode, discriminated by ``kind``. Ranges outside the source
#: are validation issues (C-8), not model errors.
Range = Annotated[FullRange | ChapterRange | TimeRange | FrameRange, Field(discriminator="kind")]


# --------------------------------------------------------------------------- output


class OutputOptions(DocumentModel):
    """Container options of the Summary tab's Output card (shared by jobs and templates)."""

    container: Container = "mkv"
    web_optimized: bool = False
    """MP4 ``+faststart``."""
    align_av_start: bool = False
    passthru_metadata: bool = True
    """Copy the source's common metadata (``-map_metadata 0``) before the overrides."""


class JobNaming(DocumentModel):
    """Per-job output naming: the template from the preset/Settings, or a manual name.

    ``mode="manual"`` uses ``manual_name`` (*Reset to template* sets ``mode`` back).
    ``template`` and ``name_source`` override the preset's naming options for this job only
    (``None`` = use them). ``field_overrides`` holds the parsed-name fields that the user
    corrected for this file (03 §Naming editor, 04 §Per-file overrides).
    """

    mode: Literal["template", "manual"] = "template"
    manual_name: str | None = None
    """File name without folder; the extension comes from the container."""
    template: str | None = None
    """Used for movies and episodes alike (it replaces both templates of the options)."""
    name_source: NameSource | None = None
    field_overrides: dict[str, str] = Field(default_factory=dict)
    """Parsed-name fields corrected for this file, by variable name: ``name``,
    ``main_title``, ``sub_title``, ``season``, ``episode``, ``episode_code``, ``year``,
    ``edition``, ``source_type``, ``release_group``. They replace what the parser found;
    ``""`` clears a field. Numbers are written as text (``"3"``). Unknown names and bad
    numbers are naming issues, not load errors."""


class OutputSettings(OutputOptions):
    """``JobSettings.output``: container options, the output path and naming."""

    path: Path | None = None
    """The final output path once naming resolved it; ``None`` until then."""
    naming: JobNaming = Field(default_factory=JobNaming)
    edit_in_place: bool = False
    """Remux-only jobs on MKV: edit metadata in place with mkvpropedit (03 §Remux-only)."""


# --------------------------------------------------------------------------- filters


class FilterConfig(DocumentModel):
    """One filter of 03 §Filters: a preset (``default``, ``light``, …), an optional tune, and
    a custom parameter string for the ``custom`` preset. A filter that is off is not in
    :class:`FilterSettings` at all."""

    preset: str = "default"
    """A preset of the chosen implementation (``FilterImplementation.presets`` in C-6)."""
    tune: str | None = None
    custom: str | None = None
    implementation: str | None = None
    """The FFmpeg implementation (C-6 ``FilterImplementation.id``): ``nlmeans`` or
    ``hqdn3d`` for Denoise, ``bwdif`` or ``yadif`` for Deinterlace, ``unsharp`` or ``cas``
    for Sharpen, ``zscale`` or ``libplacebo`` for Colorspace and Tone mapping. ``None`` = the
    filter's default: the first implementation the FFmpeg build can run (HandBrake stores
    this choice separately too, for example ``PictureDenoiseFilter``)."""


class FilterSettings(RootModel[dict[str, FilterConfig]]):
    """Ordered map ``filter_id → FilterConfig``.

    Filter ids are those of the definitions (C-6): ``detelecine``, ``interlace_detection``,
    ``deinterlace``, ``denoise``, ``chroma_smooth``, ``sharpen``, ``deblock``,
    ``colorspace``, ``tonemap``, ``grayscale``, ``custom``. The order in the graph is fixed
    by 03 §Filters; the map order matters only for display.
    """

    root: dict[str, FilterConfig] = Field(default_factory=dict)


# --------------------------------------------------------------------------- video

FramerateMode = Literal["variable", "constant", "peak"]


class ConstantQuality(DocumentModel):
    """CRF / CQ / QP, on the encoder's own scale (the definitions give the range)."""

    mode: Literal["quality"] = "quality"
    value: float = 22.0


class AverageBitrate(DocumentModel):
    mode: Literal["bitrate"] = "bitrate"
    kbps: PositiveInt = 6000
    two_pass: bool = False
    turbo_first_pass: bool = False
    """Faster first pass (2-pass only)."""


#: Rate control, discriminated by ``mode``.
RateControl = Annotated[ConstantQuality | AverageBitrate, Field(discriminator="mode")]


class VideoSettings(DocumentModel):
    """``JobSettings.video``: an encoder, or passthrough (copy the video stream).

    With ``passthrough`` the other fields are kept (so switching back restores them) but not
    used, and dimensions and filters do not apply.
    """

    passthrough: bool = False
    encoder: str = "libx265"
    framerate: Rational | None = None
    """``None`` = same as source."""
    framerate_mode: FramerateMode = "variable"
    rate_control: RateControl = Field(default_factory=ConstantQuality)
    preset: str | None = None
    """Speed preset (``slow``, ``p5``, ``6``); ``None`` = the encoder's default."""
    tune: str | None = None
    profile: str | None = None
    level: str | None = None
    """``4.1``, ``5.1``; ``None`` = auto."""
    bit_depth: Literal[8, 10] = 8
    fast_decode: bool = False
    advanced: dict[str, OptionValue] = Field(default_factory=dict)
    """Advanced encoder options by key (C-6 ``EncoderOption.key``); only changed values."""
    custom_params: str = ""
    """Free ``key=value:…`` text, appended last."""
    metadata: TrackMetadata = Field(default_factory=TrackMetadata)


# --------------------------------------------------------------------------- audio

AudioAction = Literal["passthru", "encode"]
Mixdown = Literal["mono", "stereo", "dpl2", "5.1", "7.1"]
LoudnessTarget = Literal["off", "ebu_r128", "streaming"]
"""``ebu_r128`` = -23 LUFS, ``streaming`` = -16 LUFS (two-pass ``loudnorm``)."""


class _AudioEncoding(DocumentModel):
    """Fields shared by an output audio track and the fixed audio settings of a track rule."""

    action: AudioAction = "encode"
    encoder: str | None = "aac"
    """``aac``, ``ac3``, ``eac3``, ``libopus``, ``flac``, ``libmp3lame``; for ``passthru`` the
    encoder used when the container cannot hold the source codec (HandBrake's auto passthru);
    ``None`` = the preset's fallback encoder."""
    mixdown: Mixdown | None = None
    """``None`` = keep the source layout."""
    samplerate: PositiveInt | None = None
    """Hz; ``None`` = same as source."""
    bitrate: PositiveInt | None = None
    """kb/s; ``None`` = the encoder's default (or ``quality``)."""
    quality: float | None = None
    """VBR quality for encoders that have one; used when ``bitrate`` is ``None``."""
    gain: float = 0.0
    """dB."""
    drc: NonNegativeFloat = 0.0
    """Dynamic range compression, 0 (off) to 4 (HandBrake's scale)."""
    loudness: LoudnessTarget = "off"


class AudioOutputTrack(_AudioEncoding):
    """One output audio track of a job."""

    source_stream: NonNegativeInt | None = None
    """Absolute stream index of the source audio track."""
    metadata: TrackMetadata = Field(default_factory=TrackMetadata)


# --------------------------------------------------------------------------- subtitles

SubtitleAction = Literal["copy", "burn", "convert"]
SubtitleFormat = Literal["srt", "ass", "webvtt", "mov_text"]


class _SubtitleHandling(DocumentModel):
    action: SubtitleAction = "copy"
    convert_to: SubtitleFormat | None = None
    """For ``convert`` (text → text only; FFmpeg cannot make bitmaps from text)."""
    forced_only: bool = False
    """Burn in / keep only forced events (PGS ``forced_subs_only``)."""


class ExternalSubtitle(DocumentModel):
    """An external subtitle file (``.srt``, ``.ass``, ``.ssa``, ``.vtt``, ``.sup``).

    ``language``, ``name`` and ``flags`` describe the file as a source track (what the user
    says it is); the output track's ``metadata`` decides what is written.
    """

    path: Path
    language: LanguageTag | None = None
    name: str | None = None
    flags: TrackFlags = Field(default_factory=TrackFlags)
    offset_ms: int = 0
    """Time offset (``-itsoffset``), milliseconds; may be negative."""
    charset: str | None = None
    """Character encoding (``-sub_charenc``); ``None`` = auto-detected."""


class SubtitleOutputTrack(_SubtitleHandling):
    """One output subtitle track: from a source stream (absolute index) or an external file."""

    source: NonNegativeInt | ExternalSubtitle
    metadata: TrackMetadata = Field(default_factory=TrackMetadata)


# --------------------------------------------------------------------------- chapters, tags


class ChapterSettings(DocumentModel):
    """``JobSettings.chapters``: markers on/off, renamed chapters, generated chapters."""

    enabled: bool = True
    names: list[str] | None = None
    """Chapter names in order; ``None`` = the source names."""
    generate_every: Annotated[float, Field(gt=0)] | None = None
    """Minutes: generate chapters every N minutes when the source has none."""


class TagSettings(DocumentModel):
    """The eight HandBrake tags. Values may use the naming variables (``{name}``, …)."""

    title: str | None = None
    actors: str | None = None
    director: str | None = None
    release_date: str | None = None
    comment: str | None = None
    genre: str | None = None
    description: str | None = None
    plot: str | None = None


# --------------------------------------------------------------------------- the job


class JobSettings(DocumentModel):
    """Everything needed to encode one source (05 §C-2 sketch)."""

    schema_version: PositiveInt = 1
    source: SourceRef
    preset_id: str | None = None
    """The preset this job started from (for the *modified* marker)."""
    preset_name: str | None = None
    """For the ``{preset}`` naming variable."""
    range: Range = Field(default_factory=FullRange)
    output: OutputSettings = Field(default_factory=OutputSettings)
    dimensions: DimensionSettings = Field(default_factory=DimensionSettings)
    filters: FilterSettings = Field(default_factory=FilterSettings)
    video: VideoSettings = Field(default_factory=VideoSettings)
    audio: list[AudioOutputTrack] = Field(default_factory=list)
    subtitles: list[SubtitleOutputTrack] = Field(default_factory=list)
    chapters: ChapterSettings = Field(default_factory=ChapterSettings)
    tags: TagSettings = Field(default_factory=TagSettings)
