"""Definition schemas (C-6), validated by Pydantic when the TOML data is loaded.

The M2 contract fields (written by the lead before M2 wave 1, ``docs/m2-breakdown.md``) keep
their names, types and meaning; C-6 only adds:

- C-4 reads ``VideoEncoderDef`` (``id``, ``hardware``, ``family``, ``vendor``,
  ``platforms``, ``pix_fmts``, ``hardware_setup``, ``fallback``) and the ids of
  ``AudioEncoderDef``.
- C-16 reads ``codec_label`` (``{codec}``) and ``handbrake_key`` (``{encoder}``), and the
  audio ``label`` (``{acodec}``).
- C-7 (command builder) and C-8 (validation) read everything else. ``reframe.definitions``
  (the package docstring) explains how they use it.

**Placeholders** in argument lists are ``{name}`` strings that the caller resolves:

- ``{vaapi_device}`` (default ``/dev/dri/renderD128``) and ``{sw_pix_fmt}`` (the software
  pixel format uploaded to a hardware encoder): ``HardwareSetup``.
- ``{value}`` (the quality value) and the names of :attr:`QualityMode.derived`: rate control.
- ``{kbps}`` (average bitrate in kb/s): :class:`BitrateMode`.
- ``{pass}`` (``1`` or ``2``) and ``{passlog}`` (the stats file prefix): :class:`TwoPassDef`.
- ``{custom}`` (the user's parameter string): filter presets with ``custom = true``.

**Stream specifiers**: ``ffmpeg_arg`` and ``private_opt`` mappings and argument lists name
the bare option (``-bf``, ``-preset``, ``-b:v``). The command builder adds the output stream
specifier (``-bf:v:0``) when it writes them; every FFmpeg codec option accepts one.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping
from typing import Annotated, Literal, get_args

from pydantic import Field, model_validator

from reframe.models.base import ReframeModel
from reframe.models.defaults import PassthruCodec
from reframe.models.job import Container, FilterConfig, Mixdown, OptionValue, SubtitleFormat

__all__ = [
    "BITRATE_PLACEHOLDER",
    "FILTER_IDS",
    "FILTER_STAGES",
    "TRACK_FLAGS",
    "AudioBitrateDef",
    "AudioCodec",
    "AudioEncoderDef",
    "AudioQualityDef",
    "BitDepth",
    "BitrateLimits",
    "BitrateMode",
    "Choice",
    "ChoiceSetting",
    "CodecSupport",
    "Condition",
    "ContainerDef",
    "Definitions",
    "DerivedValue",
    "EncoderDefault",
    "EncoderFamily",
    "EncoderOption",
    "FastDecodeDef",
    "FfmpegArg",
    "FilterDef",
    "FilterHelp",
    "FilterId",
    "FilterImplementation",
    "FilterPreset",
    "FilterTune",
    "FixedDefault",
    "HardwareSetup",
    "MixdownDef",
    "OperatingSystem",
    "OptionDefault",
    "OptionMapping",
    "OptionType",
    "PassthruCodecDef",
    "PresetDefault",
    "PrivateOpt",
    "QualityBand",
    "QualityMode",
    "RateControlDef",
    "SpeedCost",
    "TrackFlag",
    "TrackFlagDef",
    "TwoPassDef",
    "Vendor",
    "VideoCodec",
    "VideoEncoderDef",
    "X26xParam",
]

EncoderFamily = Literal["software", "nvenc", "qsv", "amf", "vaapi"]
"""Picker group (03 §Video): Software, NVIDIA NVENC, Intel QSV, AMD AMF, VAAPI."""
Vendor = Literal["nvidia", "intel", "amd"]
VideoCodec = Literal["h264", "hevc", "av1", "vp9", "mpeg2", "mpeg4"]
AudioCodec = Literal["aac", "ac3", "eac3", "opus", "flac", "mp3"]
OperatingSystem = Literal["linux", "windows", "macos"]
_ALL_PLATFORMS: list[OperatingSystem] = ["linux", "windows"]

BitDepth = Literal["8", "10"]
"""Bit depth as a TOML key (``VideoSettings.bit_depth`` as a string)."""
OptionType = Literal["int", "float", "bool", "enum", "string"]
SpeedCost = Literal["low", "medium", "high"]
TrackFlag = Literal[
    "default", "forced", "commentary", "hearing_impaired", "visual_impaired", "original"
]
"""The six flags of 03 §Track metadata (the fields of ``reframe.models.job.TrackFlags``)."""
TRACK_FLAGS: tuple[TrackFlag, ...] = get_args(TrackFlag)

FilterId = Literal[
    "detelecine",
    "interlace_detection",
    "deinterlace",
    "denoise",
    "deblock",
    "custom",
    "tonemap",
    "colorspace",
    "sharpen",
    "chroma_smooth",
    "grayscale",
]
"""Filter ids, as the keys of ``reframe.models.job.FilterSettings``."""
FILTER_IDS: tuple[FilterId, ...] = get_args(FilterId)
FILTER_STAGES = ("crop", "scale", "format")
"""Steps of the fixed filter order that are not filters of the definitions: crop and scale
(C-5 geometry) and the final pixel format / hardware upload (``HardwareSetup.filter_tail``)."""

BITRATE_PLACEHOLDER = "{kbps}"


# =========================================================================== shared pieces


class Choice(ReframeModel):
    """One value of a choice list (preset, tune, profile, level, enum option)."""

    value: str
    """The stored id (``slow``, ``p5``, ``4.1``, ``main10``)."""
    label: str
    help: str = ""
    ffmpeg_value: str | None = None
    """What is written to FFmpeg when it differs from ``value`` (SVT-AV1 level ``4.1`` →
    ``41``)."""
    bit_depths: list[int] | None = None
    """Bit depths this value is valid for (``[10]`` for ``main10``); ``None`` = all."""

    @property
    def written(self) -> str:
        return self.value if self.ffmpeg_value is None else self.ffmpeg_value


class X26xParam(ReframeModel):
    """Written into the encoder's params argument (``-x264-params``, ``-x265-params``,
    ``-svtav1-params``: :attr:`VideoEncoderDef.params_arg`) as ``name=value``.

    ``part`` makes the option one part of a composite value: the builder joins the parts of
    every option with the same ``name`` with ``,`` in part order (``deblock=-1,-1``,
    ``psy-rd=1.00,0.15``), filling a part the user did not change with that option's default.
    """

    kind: Literal["x26x_param"] = "x26x_param"
    name: str
    part: int | None = None


class FfmpegArg(ReframeModel):
    """A generic FFmpeg codec option (``-bf``, ``-refs``, ``-g``): every encoder has it."""

    kind: Literal["ffmpeg_arg"] = "ffmpeg_arg"
    arg: str
    """With the leading dash: ``-bf``."""


class PrivateOpt(ReframeModel):
    """A private option of this encoder (``ffmpeg -h encoder=<id>``), written ``-<name>``.

    Hidden by :func:`reframe.definitions.supported_options` when the build does not list it.
    """

    kind: Literal["private_opt"] = "private_opt"
    name: str
    """Without the dash: ``b_ref_mode``."""


OptionMapping = Annotated[X26xParam | FfmpegArg | PrivateOpt, Field(discriminator="kind")]
"""How a value reaches FFmpeg (05 §C-6): ``x26x_param`` | ``ffmpeg_arg`` | ``private_opt``."""


class ChoiceSetting(ReframeModel):
    """A choice of a video encoder: speed preset, tune, profile or level."""

    choices: list[Choice]
    default: str | None = None
    """The value the encoder uses when none is given (shown as "default"); ``None`` = the
    encoder decides (auto)."""
    default_by_depth: dict[BitDepth, str] = Field(default_factory=dict)
    """Overrides ``default`` per bit depth (profiles: ``main`` / ``main10``)."""
    mapping: OptionMapping
    help: str = ""

    def values(self, bit_depth: int | None = None) -> list[str]:
        """The stored ids, optionally only those valid for ``bit_depth``."""
        return [
            c.value
            for c in self.choices
            if bit_depth is None or c.bit_depths is None or bit_depth in c.bit_depths
        ]

    def get(self, value: str) -> Choice | None:
        return next((c for c in self.choices if c.value == value), None)

    def default_for(self, bit_depth: int) -> str | None:
        key: BitDepth = "10" if bit_depth == 10 else "8"
        return self.default_by_depth.get(key, self.default)


# =========================================================================== options


class FixedDefault(ReframeModel):
    kind: Literal["fixed"] = "fixed"
    value: OptionValue


class PresetDefault(ReframeModel):
    """The default depends on the speed preset (x264 / x265 preset tables).

    A preset that is missing from ``values`` does not use the option (x264 ``ultrafast`` has
    no B-frames, so no ``b-adapt``).
    """

    kind: Literal["preset"] = "preset"
    values: dict[str, OptionValue]
    tunes: list[str] = Field(default_factory=list)
    """Tunes that change this option (the placeholder then says "depends on the tune")."""


class EncoderDefault(ReframeModel):
    """The encoder decides (the value depends on the content, the hardware or other
    settings)."""

    kind: Literal["encoder"] = "encoder"
    note: str = ""


OptionDefault = Annotated[
    FixedDefault | PresetDefault | EncoderDefault, Field(discriminator="kind")
]

ConditionField = str
"""``rate_control`` (``quality`` / ``bitrate``), ``two_pass``, ``bit_depth``, ``preset``,
``tune``, or ``option:<key>`` (the value of another option of the same encoder)."""
CONDITION_FIELDS = ("rate_control", "two_pass", "bit_depth", "preset", "tune")


class Condition(ReframeModel):
    """When an option applies, e.g. ``rate_control == "bitrate"``."""

    field: ConditionField
    op: Literal["eq", "ne", "in", "not_in"] = "eq"
    value: OptionValue | list[OptionValue]

    def matches(self, context: Mapping[str, OptionValue | None]) -> bool:
        """``context`` maps the condition fields to the job's values (``option:<key>`` too)."""
        actual = context.get(self.field)
        if self.op in ("in", "not_in"):
            values = self.value if isinstance(self.value, list) else [self.value]
            found = actual in values
            return found if self.op == "in" else not found
        return (actual == self.value) if self.op == "eq" else (actual != self.value)


class EncoderOption(ReframeModel):
    """One advanced encoder option (05 §C-6, StaxRip style)."""

    key: str
    """The key in ``VideoSettings.advanced`` (``bframes``)."""
    label: str
    category: str
    """``Rate control``, ``Frame types / GOP``, ``Motion / analysis``, ``Psycho-visual``,
    ``Loop filters``, ``HDR / colour``, ``Performance``."""
    type: OptionType
    min: float | None = None
    max: float | None = None
    step: float | None = None
    choices: list[Choice] | None = None
    default: OptionDefault
    help: str
    """What it does, the typical range, and the quality / speed effect."""
    mapping: OptionMapping
    requires: list[Condition] = Field(default_factory=list)
    unit: str | None = None
    """``frames``, ``kb/s``."""


# =========================================================================== rate control


class DerivedValue(ReframeModel):
    """A value computed from the quality value (HandBrake's QP offsets for P/B frames).

    ``value + offset``; when ``ramp_below`` is set and the value is at or below it, the offset
    is scaled by ``value / ramp_below``. Clamped to ``min`` / ``max``; ``integer`` rounds.
    """

    offset: float = 0.0
    ramp_below: float | None = None
    min: float | None = None
    max: float | None = None
    integer: bool = False

    def compute(self, value: float) -> float:
        offset = self.offset
        if self.ramp_below is not None and value <= self.ramp_below:
            offset = offset * value / self.ramp_below
        result = value + offset
        if self.min is not None:
            result = max(self.min, result)
        if self.max is not None:
            result = min(self.max, result)
        return float(round(result)) if self.integer else result


class QualityBand(ReframeModel):
    """A recommended quality range for outputs up to ``max_height`` lines (03 §Video)."""

    max_height: int
    low: float
    high: float


class QualityMode(ReframeModel):
    """Constant quality (``ConstantQuality.value``), on the encoder's own scale."""

    kind: Literal["crf", "cq", "qp", "icq"]
    label: str
    """``RF``, ``CQ``, ``QP``, ``ICQ`` (HandBrake's names where it has them)."""
    min: float
    max: float
    step: float
    default: float
    """Reframe's suggested start value (HandBrake's 1080p presets where they exist)."""
    direction: Literal["lower_is_better", "higher_is_better"] = "lower_is_better"
    args: list[str] = Field(default_factory=list)
    """FFmpeg arguments; placeholders ``{value}`` and the ``derived`` names."""
    params: dict[str, str] = Field(default_factory=dict)
    """Entries for the params argument (same placeholders)."""
    derived: dict[str, DerivedValue] = Field(default_factory=dict)
    scale: list[tuple[float, float]]
    """Quality conversion table: ``(value, x264 RF equivalent)`` points, increasing in both
    (piecewise linear). Approximate by nature (03 §Missing encoder behaviour)."""
    recommended: list[QualityBand] = Field(default_factory=list)
    help: str = ""


class TwoPassDef(ReframeModel):
    """2-pass average bitrate (``AverageBitrate.two_pass``).

    ``two_runs``: FFmpeg runs twice; pass 1 writes to the null muxer. ``single_run``: the
    encoder does both passes internally (NVENC ``-multipass``), in one FFmpeg run.
    """

    mode: Literal["two_runs", "single_run"]
    args: list[str] = Field(default_factory=list)
    """Every pass; placeholders ``{pass}``, ``{passlog}``."""
    params: dict[str, str] = Field(default_factory=dict)
    turbo_args: list[str] = Field(default_factory=list)
    """Pass 1 (``two_runs``) or the run (``single_run``) when ``turbo_first_pass`` is on."""
    turbo_params: dict[str, str] = Field(default_factory=dict)
    full_args: list[str] = Field(default_factory=list)
    """Pass 1 / the run when ``turbo_first_pass`` is off."""
    full_params: dict[str, str] = Field(default_factory=dict)


class BitrateMode(ReframeModel):
    """Average bitrate (``AverageBitrate.kbps``)."""

    min_kbps: int = 100
    max_kbps: int = 200_000
    args: list[str]
    """Placeholder ``{kbps}``: ``["-b:v", "{kbps}k"]``."""
    params: dict[str, str] = Field(default_factory=dict)
    two_pass: TwoPassDef | None = None
    """``None``: no 2-pass for this encoder (validation reports a 2-pass job)."""
    help: str = ""


class RateControlDef(ReframeModel):
    quality: QualityMode | None = None
    bitrate: BitrateMode | None = None


class FastDecodeDef(ReframeModel):
    """``VideoSettings.fast_decode``: a tune value, or arguments."""

    tune: str | None = None
    """Written as (part of) the tune: ``fastdecode``."""
    combines_with_tune: bool = False
    """x264 accepts ``-tune film,fastdecode``; x265 takes only one tune."""
    args: list[str] = Field(default_factory=list)
    params: dict[str, str] = Field(default_factory=dict)


# =========================================================================== video encoders


class HardwareSetup(ReframeModel):
    """How to drive a hardware encoder from FFmpeg."""

    init_args: list[str] = Field(default_factory=list)
    """Global arguments before ``-i``, e.g. ``["-init_hw_device", "vaapi=va:{vaapi_device}",
    "-filter_hw_device", "va"]``."""
    filter_tail: list[str] = Field(default_factory=list)
    """Filters appended at the end of the video filter chain, e.g.
    ``["format={sw_pix_fmt}", "hwupload"]``."""


class VideoEncoderDef(ReframeModel):
    """One FFmpeg video encoder that Reframe knows."""

    id: str
    """The FFmpeg encoder name: ``libx265``, ``hevc_nvenc``."""
    label: str
    """Display name: ``x265``, ``NVIDIA NVENC H.265``."""
    codec: VideoCodec
    codec_label: str
    """Video format for ``{codec}``: ``H.265``."""
    handbrake_key: str
    """HandBrake-style short key for ``{encoder}``: ``x265``, ``nvenc_h265``, ``svt_av1``."""
    family: EncoderFamily
    hardware: bool
    vendor: Vendor | None = None
    platforms: list[OperatingSystem] = Field(default_factory=lambda: _ALL_PLATFORMS.copy())
    pix_fmts: dict[Literal["8", "10"], str] = Field(default_factory=dict)
    """Pixel format fed to the encoder per bit depth (TOML keys are strings). A missing key
    means the encoder does not support that bit depth."""
    hardware_setup: HardwareSetup | None = None
    fallback: list[str] = Field(default_factory=list)
    """Encoder ids to try, in order, when this one is unavailable. Ends with a software
    encoder (the C-6 linter checks it)."""

    # ---- C-6 additions
    help: str = ""
    params_arg: str | None = None
    """``-x264-params`` / ``-x265-params`` / ``-svtav1-params``: where ``x26x_param`` options
    go (joined with ``:``). ``None``: the encoder has no params argument."""
    rate_control: RateControlDef = Field(default_factory=RateControlDef)
    presets: ChoiceSetting | None = None
    """Speed presets, fastest first (the slider order)."""
    tunes: ChoiceSetting | None = None
    profiles: ChoiceSetting | None = None
    levels: ChoiceSetting | None = None
    fast_decode: FastDecodeDef | None = None
    extra_args: list[str] = Field(default_factory=list)
    """Always written after the codec (``-row-mt 1`` for VP9)."""
    options: list[EncoderOption] = Field(default_factory=list)
    """Advanced options (05 §C-6). M2 has the basic set; M9 completes it."""

    def option(self, key: str) -> EncoderOption | None:
        return next((o for o in self.options if o.key == key), None)


# =========================================================================== audio


class BitrateLimits(ReframeModel):
    min: int
    max: int
    default: int


class AudioBitrateDef(ReframeModel):
    """Bitrates in kb/s for 44.1 / 48 kHz output (the ranges shrink at low sample rates)."""

    by_mixdown: dict[Mixdown, BitrateLimits]
    """Missing mixdown = the encoder cannot produce that layout."""
    allowed: list[int] | None = None
    """Fixed steps (AC-3, E-AC-3, MP3); ``None`` = any value from ``min`` to ``max``."""

    def snap(
        self, kbps: int, mixdown: Mixdown, direction: Literal["down", "up"] = "down"
    ) -> int | None:
        """A valid bitrate for ``mixdown`` near ``kbps``, clamped to the range; ``None`` when
        the mixdown is not supported.

        ``down`` (a maximum bitrate, as HandBrake snaps): the largest allowed value at or
        below ``kbps``. ``up`` (03 §Audio: "the smallest allowed bitrate that is at or above
        the source bitrate"): the smallest allowed value at or above it.
        """
        limits = self.by_mixdown.get(mixdown)
        if limits is None:
            return None
        value = min(max(kbps, limits.min), limits.max)
        if self.allowed is None:
            return value
        steps = [s for s in self.allowed if limits.min <= s <= limits.max]
        if direction == "down":
            below = [s for s in steps if s <= value]
            return max(below) if below else min(steps)
        above = [s for s in steps if s >= value]
        return min(above) if above else max(steps)

    def values(self, mixdown: Mixdown) -> list[int] | None:
        """The allowed values for ``mixdown`` (``None`` for a free range)."""
        limits = self.by_mixdown.get(mixdown)
        if limits is None or self.allowed is None:
            return None
        return [s for s in self.allowed if limits.min <= s <= limits.max]


class AudioQualityDef(ReframeModel):
    """VBR quality (``AudioOutputTrack.quality``)."""

    arg: str
    """``-q:a``; the builder adds the output stream index (``-q:a:0``)."""
    min: float
    max: float
    step: float
    default: float
    direction: Literal["lower_is_better", "higher_is_better"]
    help: str = ""


class AudioEncoderDef(ReframeModel):
    """One FFmpeg audio encoder that Reframe knows."""

    id: str
    """The FFmpeg encoder name: ``aac``, ``libopus``."""
    label: str
    """Display name and ``{acodec}``: ``AAC``, ``AC-3``, ``Opus``."""
    codec: AudioCodec

    # ---- C-6 additions
    help: str = ""
    lossless: bool = False
    max_channels: int = 2
    mixdowns: list[Mixdown] = Field(default_factory=list)
    samplerates: list[int] = Field(default_factory=list)
    """Hz. A source rate that is not listed is resampled to the closest listed one."""
    bitrate: AudioBitrateDef | None = None
    """``None`` for lossless encoders."""
    quality: AudioQualityDef | None = None
    passthru: PassthruCodec | None = None
    """The passthru codec this encoder's output is (``ac3`` → ``ac3``), for "the source
    already fits"."""
    in_gpl_builds: bool = True
    """``libfdk_aac`` is not in GPL builds (the bundled FFmpeg)."""
    fallback: list[str] = Field(default_factory=list)
    """Audio encoder ids to try, in order, when this one is unavailable (decision 0020:
    ``libfdk_aac → aac``). Ends with an encoder that every GPL build has (the linter checks
    it); empty for encoders that are always there."""


class MixdownDef(ReframeModel):
    """How a ``Mixdown`` is produced (03 §Audio)."""

    label: str
    channels: int
    lfe: int = 0
    layout: str
    """FFmpeg channel layout: ``stereo``, ``5.1``."""
    matrix_encoding: str | None = None
    """``dplii`` for Dolby Pro Logic II (``aresample=matrix_encoding=dplii``)."""


class PassthruCodecDef(ReframeModel):
    """A codec of 03 §Audio defaults part 3, matched on the source track."""

    label: str
    codec_name: str
    """ffprobe ``codec_name``."""
    profiles: list[str] | None = None
    """Only these ffprobe profiles (DTS-HD); ``None`` = any."""
    exclude_profiles: list[str] = Field(default_factory=list)


# =========================================================================== containers


class CodecSupport(ReframeModel):
    """What a container holds for one track type."""

    copy_codecs: list[str] = Field(default_factory=list, alias="copy")
    """ffprobe codec names that can be stream-copied in; ``["*"]`` = any."""
    encode: list[str] = Field(default_factory=list)
    """Video / audio codecs (``VideoCodec`` / ``AudioCodec``) or subtitle formats
    (``SubtitleFormat``) that can be encoded into it."""
    copy_args: dict[str, list[str]] = Field(default_factory=dict)
    """Extra arguments to copy a codec (``truehd`` in MP4: ``-strict -2``)."""

    def can_copy(self, codec_name: str) -> bool:
        return "*" in self.copy_codecs or codec_name in self.copy_codecs


class TrackFlagDef(ReframeModel):
    """How a track flag is written: FFmpeg disposition and mkvpropedit property."""

    disposition: str
    mkvpropedit: str


class ContainerDef(ReframeModel):
    """One output container (``reframe.models.job.Container``)."""

    id: Container
    label: str
    muxer: str
    """FFmpeg muxer name (``-f``): ``matroska``, ``mp4``, ``webm``."""
    extensions: list[str]
    """The first is the default (``.mkv``)."""
    video: CodecSupport
    audio: CodecSupport
    subtitles: CodecSupport
    text_subtitle_target: SubtitleFormat | None = None
    """A copied text subtitle that the container cannot hold is converted to this
    (MP4: ``mov_text``); ``None`` = the container takes the text formats it lists."""
    codec_tags: dict[str, str] = Field(default_factory=dict)
    """``-tag:v`` per codec (MP4 H.265: ``hvc1``, as HandBrake writes it)."""
    chapters: bool
    attachments: bool
    flags: list[TrackFlag]
    """Flags the FFmpeg muxer writes (and ffprobe reads back)."""
    mkvpropedit_flags: list[TrackFlag] = Field(default_factory=list)
    """Flags the muxer cannot write that a ``mkvpropedit`` step can."""
    default_always_set: bool = False
    """MP4: when no track of a type is default, the muxer marks the first one default."""
    language_format: Literal["iso639_2b", "iso639_2t"]
    """MKV: ISO 639-2/B (``to_matroska_legacy``); MP4: ISO 639-2/T (``to_mp4``)."""
    format_flags: dict[str, list[str]] = Field(default_factory=dict)
    """Arguments for output options: ``web_optimized`` → ``-movflags +faststart``."""
    help: str = ""


# =========================================================================== filters


class FilterHelp(ReframeModel):
    """The help panel of 03 §Filters."""

    what: str
    use_when: str
    avoid_when: str
    speed_cost: SpeedCost
    settings: str
    """Each preset and tune in one line."""


class FilterTune(ReframeModel):
    id: str
    label: str
    help: str = ""


class FilterPreset(ReframeModel):
    """A preset of one implementation (HandBrake's preset names where HandBrake has them)."""

    id: str
    label: str
    help: str = ""
    chain: str | None = None
    """The FFmpeg filter chain with no tune (``None``: the preset needs a tune)."""
    tune_chains: dict[str, str] = Field(default_factory=dict)
    """Tune id → chain."""
    custom: bool = False
    """The chain contains ``{custom}`` (``FilterConfig.custom``)."""
    handbrake: str | None = None
    """The HandBrake settings this preset maps from (documentation of the mapping)."""

    def chain_for(self, tune: str | None = None) -> str | None:
        """The chain for ``tune`` (``None`` or a tune without its own chain: the plain
        chain)."""
        if tune is not None and tune in self.tune_chains:
            return self.tune_chains[tune]
        return self.chain


class FilterImplementation(ReframeModel):
    """An FFmpeg implementation of a filter, with its own presets and tunes
    (``FilterConfig.implementation``; HandBrake: NLMeans or HQDN3D, Yadif or Bwdif …)."""

    id: str
    label: str
    filters: list[str]
    """FFmpeg filters the build must have (``CapabilitySnapshot.has_filter``)."""
    note: str = ""
    requires_tagged_input: bool = False
    """The filter needs the input's colour properties (primaries, transfer, matrix). For an
    untagged source the builder prepends ``setparams`` with the probed or assumed values
    (``zscale`` fails with "no path between colorspaces" otherwise)."""
    combed_only: str | None = None
    """Option appended to the chain when interlace detection is on, so that only the frames
    it flags as interlaced are processed (``deint=interlaced``)."""
    needs_vulkan: bool = False
    """The filter is in the build but fails without a working Vulkan driver (libplacebo:
    "Error initializing filters … Generic error in an external library"). Being listed by
    ``ffmpeg -filters`` is not enough: check it with a test run before choosing it."""
    presets: list[FilterPreset]
    tunes: list[FilterTune] = Field(default_factory=list)
    default_preset: str

    def preset(self, preset_id: str) -> FilterPreset | None:
        return next((p for p in self.presets if p.id == preset_id), None)

    def runs_with(self, available: Mapping[str, bool] | None) -> bool:
        """All of ``filters`` are ``available`` (``None`` = assume they are)."""
        return available is None or all(available.get(f, False) for f in self.filters)


class FilterDef(ReframeModel):
    """One filter of 03 §Filters."""

    id: FilterId
    label: str
    position: int = 0
    """Index in the fixed filter order (``Definitions.filter_order``), set by the loader."""
    analysis: bool = False
    """Interlace detection: it marks frames for deinterlace and changes no pixels."""
    implementations: list[FilterImplementation]
    """In order of preference: the first is the default (``FilterConfig.implementation``
    ``None``)."""
    help: FilterHelp

    def implementation(self, implementation_id: str) -> FilterImplementation | None:
        return next((i for i in self.implementations if i.id == implementation_id), None)

    def implementation_for(
        self, config: FilterConfig | None = None, available: Mapping[str, bool] | None = None
    ) -> FilterImplementation | None:
        """The implementation a filter config uses.

        ``config.implementation`` set: that implementation, if it is known and its filters
        are ``available`` (``None`` = assume all are). Not set: the first implementation that
        runs and has ``config.preset``. ``None`` when nothing fits (the validation reports
        it).
        """
        if config is not None and config.implementation is not None:
            impl = self.implementation(config.implementation)
            return impl if impl is not None and impl.runs_with(available) else None
        for impl in self.implementations:
            if config is not None and impl.preset(config.preset) is None:
                continue
            if impl.runs_with(available):
                return impl
        return None

    def chain_for(
        self, config: FilterConfig, available: Mapping[str, bool] | None = None
    ) -> str | None:
        """The FFmpeg chain for ``config``, with ``{custom}`` filled in (``None`` when the
        implementation, preset or tune does not resolve). ``combed_only`` is not added."""
        impl = self.implementation_for(config, available)
        preset = impl.preset(config.preset) if impl is not None else None
        if preset is None:
            return None
        chain = preset.chain_for(config.tune)
        if chain is None:
            return None
        return chain.replace("{custom}", config.custom or "") if preset.custom else chain


# =========================================================================== everything


class Definitions(ReframeModel):
    """Everything in ``definitions/data``."""

    video_encoders: dict[str, VideoEncoderDef] = Field(default_factory=dict)
    audio_encoders: dict[str, AudioEncoderDef] = Field(default_factory=dict)

    # ---- C-6 additions
    mixdowns: dict[Mixdown, MixdownDef] = Field(default_factory=dict)
    passthru_codecs: dict[PassthruCodec, PassthruCodecDef] = Field(default_factory=dict)
    containers: dict[Container, ContainerDef] = Field(default_factory=dict)
    track_flags: dict[TrackFlag, TrackFlagDef] = Field(default_factory=dict)
    filters: dict[FilterId, FilterDef] = Field(default_factory=dict)
    filter_order: list[str] = Field(default_factory=list)
    """The fixed order of 03 §Filters: filter ids plus the stages ``crop``, ``scale`` and
    ``format`` (:data:`FILTER_STAGES`)."""

    @model_validator(mode="after")
    def _filter_positions(self) -> Definitions:
        for filter_id, definition in self.filters.items():
            if filter_id in self.filter_order:
                definition.position = self.filter_order.index(filter_id)
        return self

    def ordered_filters(self) -> list[FilterDef]:
        return sorted(self.filters.values(), key=lambda f: f.position)


def interpolate(points: list[tuple[float, float]], x: float) -> float:
    """Piecewise-linear interpolation through increasing ``points``; extrapolates with the
    end segments (callers clamp)."""
    if len(points) < 2:
        raise ValueError("need at least two points")
    for (x0, y0), (x1, y1) in itertools.pairwise(points):
        if x <= x1 or (x1, y1) == points[-1]:
            if math.isclose(x1, x0):
                return y0
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    raise AssertionError("unreachable")  # pragma: no cover
