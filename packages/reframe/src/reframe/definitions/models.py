"""Definition schemas, validated by Pydantic when the TOML data is loaded.

Other modules read these fields by name: keep their names, types and meanings. Argument lists
hold ``{name}`` placeholders that the caller resolves. Option mappings name the bare FFmpeg
option (``-bf``); the command builder adds the output stream specifier (``-bf:v:0``).
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping
from typing import Annotated, Literal, get_args

from pydantic import Field, computed_field

from reframe.models.base import ReframeModel
from reframe.models.defaults import PassthruCodec
from reframe.models.job import Container, FilterConfig, Mixdown, OptionValue, SubtitleFormat

EncoderFamily = Literal["software", "nvenc", "qsv", "amf", "vaapi"]
"""The picker group of an encoder. Only ``software`` is not hardware."""
Vendor = Literal["nvidia", "intel", "amd"]
VideoCodec = Literal["h264", "hevc", "av1", "vp9", "mpeg2", "mpeg4"]
AudioCodec = Literal["aac", "ac3", "eac3", "opus", "flac", "mp3"]
OperatingSystem = Literal["linux", "windows", "macos"]
_ALL_PLATFORMS: list[OperatingSystem] = ["linux", "windows"]

BitDepth = Literal["8", "10"]
"""Bit depth as a TOML key (``VideoSettings.bit_depth`` as a string)."""
OptionType = Literal["int", "float", "bool", "enum", "string"]
OPTION_CATEGORIES: tuple[str, ...] = (
    "Basic",
    "Rate control",
    "Frame types / GOP",
    "Motion / analysis",
    "Psycho-visual",
    "Loop filters",
    "HDR / colour",
    "Performance",
)
"""The categories of the advanced panel, in panel order. Custom parameters are not one of them:
they are ``VideoSettings.custom_params``."""
SpeedCost = Literal["low", "medium", "high"]
TrackFlag = Literal[
    "default", "forced", "commentary", "hearing_impaired", "visual_impaired", "original"
]
"""The track flags, the same names as the fields of ``reframe.models.job.TrackFlags``."""
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
"""Stages of the fixed filter order that are not filters: crop, scale and the final pixel format
(``HardwareSetup.filter_tail`` adds the hardware upload)."""


class Choice(ReframeModel):
    """One value of a choice list (preset, tune, profile, level or enum option)."""

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
    """Written into the params argument of the encoder (:attr:`VideoEncoderDef.params_arg`) as
    ``name=value``.

    ``part`` makes the option one part of a composite value. The command builder joins the parts
    of the options with the same ``name`` with ``,``, in part order, and fills a part the user
    did not change with that option's default.
    """

    kind: Literal["x26x_param"] = "x26x_param"
    name: str
    part: int | None = None


class FfmpegArg(ReframeModel):
    """A generic FFmpeg codec option, such as ``-bf``. Every encoder has it."""

    kind: Literal["ffmpeg_arg"] = "ffmpeg_arg"
    arg: str
    """With the leading dash: ``-bf``."""


class PrivateOpt(ReframeModel):
    """A private option of this encoder (``ffmpeg -h encoder=<id>``), written ``-<name>``.

    A build that does not list it leaves it out.
    """

    kind: Literal["private_opt"] = "private_opt"
    name: str
    """Without the dash: ``b_ref_mode``."""


OptionMapping = Annotated[X26xParam | FfmpegArg | PrivateOpt, Field(discriminator="kind")]
"""How a value reaches FFmpeg: one of the three mapping kinds."""


class ChoiceSetting(ReframeModel):
    """A choice of a video encoder: speed preset, tune, profile or level."""

    choices: list[Choice]
    default: str | None = None
    """The value used when none is given. ``None``: the encoder decides."""
    default_by_depth: dict[BitDepth, str] = Field(default_factory=dict)
    """Overrides ``default`` per bit depth, keyed by ``"8"`` or ``"10"``."""
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


class FixedDefault(ReframeModel):
    kind: Literal["fixed"] = "fixed"
    value: OptionValue


class PresetDefault(ReframeModel):
    """The default depends on the speed preset.

    A preset that is missing from ``values`` does not use the option.
    """

    kind: Literal["preset"] = "preset"
    values: dict[str, OptionValue]
    tunes: list[str] = Field(default_factory=list)
    """Tunes that change this option's default."""


class EncoderDefault(ReframeModel):
    """The encoder decides: the value depends on the content, the hardware or other settings."""

    kind: Literal["encoder"] = "encoder"
    note: str = ""


OptionDefault = Annotated[
    FixedDefault | PresetDefault | EncoderDefault, Field(discriminator="kind")
]


class Condition(ReframeModel):
    """When an option applies, e.g. ``rate_control == "bitrate"``."""

    field: str
    """A rule field such as ``rate_control``, or ``option:<key>`` for another option of the same
    encoder."""
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
    """One advanced encoder option."""

    key: str
    """The key in ``VideoSettings.advanced`` (``bframes``)."""
    label: str
    category: str
    """One of :data:`OPTION_CATEGORIES`: the panel group of this option."""
    type: OptionType
    min: float | None = None
    max: float | None = None
    step: float | None = None
    choices: list[Choice] | None = None
    default: OptionDefault
    help: str
    """What it does, the typical range, and the quality and speed effect."""
    mapping: OptionMapping
    requires: list[Condition] = Field(default_factory=list)
    unit: str | None = None
    """``frames``, ``kb/s``."""


class DerivedValue(ReframeModel):
    """A value computed from the quality value (HandBrake's QP offsets for P and B frames).

    ``value · factor + offset``; when ``ramp_below`` is set and the value is at or below it, the
    offset is scaled by ``value / ramp_below``. Clamped to ``min`` and ``max``; ``integer`` rounds
    (half up). ``factor`` converts to the scale of another FFmpeg option.
    """

    factor: float = 1.0
    offset: float = 0.0
    ramp_below: float | None = None
    min: float | None = None
    max: float | None = None
    integer: bool = False

    def compute(self, value: float) -> float:
        offset = self.offset
        if self.ramp_below is not None and value <= self.ramp_below:
            offset = offset * value / self.ramp_below
        result = value * self.factor + offset
        if self.min is not None:
            result = max(self.min, result)
        if self.max is not None:
            result = min(self.max, result)
        return float(round_half_up(result)) if self.integer else result


class QualityBand(ReframeModel):
    """A recommended quality range for outputs up to ``max_height`` lines."""

    max_height: int
    low: float
    high: float


class QualityMode(ReframeModel):
    """Constant quality, on the encoder's own scale (``ConstantQuality.value``)."""

    kind: Literal["crf", "cq", "qp", "icq"]
    label: str
    """The name shown for the scale (HandBrake's name where it has one)."""
    min: float
    max: float
    step: float
    default: float
    """The suggested starting value."""
    direction: Literal["lower_is_better", "higher_is_better"] = "lower_is_better"
    args: list[str] = Field(default_factory=list)
    """FFmpeg arguments; placeholders ``{value}`` and the ``derived`` names."""
    params: dict[str, str] = Field(default_factory=dict)
    """Entries for the params argument (same placeholders)."""
    derived: dict[str, DerivedValue] = Field(default_factory=dict)
    scale: list[tuple[float, float]]
    """Conversion table to the x264 RF scale: ``(value, RF equivalent)`` points, increasing in
    both and joined piecewise linearly. The conversion is approximate."""
    recommended: list[QualityBand] = Field(default_factory=list)
    help: str = ""


class TwoPassDef(ReframeModel):
    """Two-pass average bitrate.

    ``two_runs``: FFmpeg runs twice; pass 1 writes to the null muxer. ``single_run``: the encoder
    does both passes in one FFmpeg run (NVENC ``-multipass``).
    """

    mode: Literal["two_runs", "single_run"]
    args: list[str] = Field(default_factory=list)
    """Every pass; placeholders ``{pass}`` and ``{passlog}``."""
    params: dict[str, str] = Field(default_factory=dict)
    turbo_args: list[str] = Field(default_factory=list)
    """Pass 1 (``two_runs``) or the run (``single_run``) when ``turbo_first_pass`` is on."""
    turbo_params: dict[str, str] = Field(default_factory=dict)
    full_args: list[str] = Field(default_factory=list)
    """Pass 1, or the run, when ``turbo_first_pass`` is off."""
    full_params: dict[str, str] = Field(default_factory=dict)


class BitrateMode(ReframeModel):
    """Average bitrate, in kb/s."""

    min_kbps: int = 100
    max_kbps: int = 200_000
    args: list[str]
    """Placeholder ``{kbps}``: the bitrate in kb/s."""
    params: dict[str, str] = Field(default_factory=dict)
    two_pass: TwoPassDef | None = None
    """``None``: this encoder has no 2-pass; validation reports a 2-pass job."""
    help: str = ""


class RateControlDef(ReframeModel):
    quality: QualityMode | None = None
    bitrate: BitrateMode | None = None


class FastDecodeDef(ReframeModel):
    """The fast-decode setting: a tune value, or arguments."""

    tune: str | None = None
    """Written as (part of) the tune: ``fastdecode``."""
    combines_with_tune: bool = False
    """x264 accepts ``fastdecode`` next to another tune; x265 takes only one tune."""
    args: list[str] = Field(default_factory=list)
    params: dict[str, str] = Field(default_factory=dict)


#: ``{vaapi_device}`` when no render node is known.
DEFAULT_VAAPI_DEVICE = "/dev/dri/renderD128"


def fill_placeholders(text: str, values: Mapping[str, str]) -> str:
    """Replace each ``{name}`` of ``values`` in ``text``. The definitions linter refuses a
    placeholder that no caller fills."""
    for name, value in values.items():
        text = text.replace("{" + name + "}", value)
    return text


class HardwareSetup(ReframeModel):
    """How to drive a hardware encoder from FFmpeg."""

    init_args: list[str] = Field(default_factory=list)
    """Global arguments before ``-i``."""
    filter_tail: list[str] = Field(default_factory=list)
    """Filters appended to the end of the video filter chain."""

    def resolve(self, values: Mapping[str, str]) -> tuple[list[str], list[str]]:
        """``init_args`` and ``filter_tail`` with their placeholders filled."""
        return (
            [fill_placeholders(a, values) for a in self.init_args],
            [fill_placeholders(f, values) for f in self.filter_tail],
        )


class VideoEncoderDef(ReframeModel):
    """One FFmpeg video encoder that Reframe knows."""

    id: str
    """The FFmpeg encoder name: ``libx265``, ``hevc_nvenc``."""
    label: str
    """The display name."""
    codec: VideoCodec
    codec_label: str
    """The video format name for the ``{codec}`` placeholder of labels."""
    handbrake_key: str
    """The short key for the ``{encoder}`` placeholder, in HandBrake's style."""
    family: EncoderFamily
    vendor: Vendor | None = None
    platforms: list[OperatingSystem] = Field(default_factory=lambda: _ALL_PLATFORMS.copy())
    pix_fmts: dict[Literal["8", "10"], str] = Field(default_factory=dict)
    """Pixel format fed to the encoder per bit depth (TOML keys are strings). A missing key
    means the encoder does not support that bit depth."""
    hardware_setup: HardwareSetup | None = None
    fallback: list[str] = Field(default_factory=list)
    """Encoder ids to try, in order, when this one is unavailable. The chain ends with a software
    encoder."""

    help: str = ""
    params_arg: str | None = None
    """The FFmpeg option that carries the ``x26x_param`` options (for example ``-x265-params``),
    joined with ``:``. ``None``: the encoder has no params argument."""
    rate_control: RateControlDef = Field(default_factory=RateControlDef)
    presets: ChoiceSetting | None = None
    """Speed presets, fastest first (the slider order)."""
    tunes: ChoiceSetting | None = None
    profiles: ChoiceSetting | None = None
    levels: ChoiceSetting | None = None
    fast_decode: FastDecodeDef | None = None
    extra_args: list[str] = Field(default_factory=list)
    """Always written after the codec."""
    options: list[EncoderOption] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def hardware(self) -> bool:
        return self.family != "software"

    def option(self, key: str) -> EncoderOption | None:
        return next((o for o in self.options if o.key == key), None)


class BitrateLimits(ReframeModel):
    min: int
    max: int
    default: int


class AudioBitrateDef(ReframeModel):
    """Bitrates in kb/s, for 44.1 and 48 kHz output; the ranges shrink at lower sample rates."""

    by_mixdown: dict[Mixdown, BitrateLimits]
    """Missing mixdown = the encoder cannot produce that layout."""
    allowed: list[int] | None = None
    """Fixed steps in kb/s; ``None``: any value from ``min`` to ``max``."""

    def snap(
        self, kbps: int, mixdown: Mixdown, direction: Literal["down", "up"] = "down"
    ) -> int | None:
        """A valid bitrate for ``mixdown`` near ``kbps``, clamped to the range; ``None`` when
        the mixdown is not supported.

        ``down`` takes the largest allowed value at or below ``kbps`` (a maximum bitrate, as
        HandBrake snaps); ``up`` takes the smallest allowed value at or above it.
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
    """VBR quality of an audio encoder."""

    arg: str
    """``-q:a``; the builder adds the output stream index (``-q:a:0``)."""
    min: float
    max: float
    step: float
    default: float
    direction: Literal["lower_is_better", "higher_is_better"]
    help: str = ""


def drop_upmix(
    requested: Mixdown | None, source_channels: int, mixdowns: Mapping[Mixdown, MixdownDef]
) -> Mixdown | None:
    """``requested``, or ``None`` when it would upmix a source of ``source_channels`` (0:
    unknown, never dropped). Dolby Pro Logic II needs more than two source channels."""
    if requested is not None and source_channels > 0:
        wanted = mixdowns[requested].channels
        if source_channels < wanted or (requested == "dpl2" and source_channels <= wanted):
            return None
    return requested


class AudioEncoderDef(ReframeModel):
    """One FFmpeg audio encoder that Reframe knows."""

    id: str
    """The FFmpeg encoder name: ``aac``, ``libopus``."""
    label: str
    """The display name, also used for the ``{acodec}`` placeholder."""
    codec: AudioCodec

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
    """The passthru codec that this encoder's output is, for when the source already fits."""
    in_gpl_builds: bool = True
    """Whether every GPL build has this encoder (``libfdk_aac`` does not)."""
    fallback: list[str] = Field(default_factory=list)
    """Audio encoder ids to try, in order, when this one is unavailable. The chain ends with an
    encoder that every GPL build has; it is empty for encoders that are always there."""

    def snap_mixdown(
        self,
        requested: Mixdown | None,
        source_channels: int,
        mixdowns: Mapping[Mixdown, MixdownDef],
    ) -> Mixdown | None:
        """The layout this encoder really produces; ``None`` keeps the source layout.

        ``requested`` is the track's mixdown (``None``: keep the source layout), and
        ``source_channels`` the source track's channel count (0: unknown). Never an upmix of a
        known source. Dolby Pro Logic II is a matrix encoding, not a channel count, so it is
        never a fallback layout.
        """
        requested = drop_upmix(requested, source_channels, mixdowns)
        if requested is not None:
            if not self.mixdowns or requested in self.mixdowns:
                return requested
            limit = mixdowns[requested].channels
        else:
            if source_channels == 0 or source_channels <= self.max_channels:
                return None
            limit = source_channels
        plain = [m for m in self.mixdowns if m != "dpl2" and m in mixdowns]
        below = [m for m in plain if mixdowns[m].channels <= limit]
        if below:
            return max(below, key=lambda m: mixdowns[m].channels)
        if not plain:
            return None
        smallest = min(plain, key=lambda m: mixdowns[m].channels)
        if 0 < source_channels < mixdowns[smallest].channels:
            return None  # still never an upmix of a known source
        return smallest

    def snap_samplerate(self, rate: int | None, source_rate: int | None = None) -> int | None:
        """The output sample rate in Hz: ``rate``, or ``source_rate`` when ``rate`` is ``None``,
        moved to the nearest rate in :attr:`samplerates`. A tie goes to the higher rate. An
        encoder that lists no rates keeps the rate. ``None`` when neither rate is known (FFmpeg
        then picks one itself).
        """
        wanted = rate if rate is not None else source_rate
        if wanted is None or not self.samplerates or wanted in self.samplerates:
            return wanted
        return min(self.samplerates, key=lambda r: (abs(r - wanted), -r))


class MixdownDef(ReframeModel):
    """How a mixdown is produced."""

    label: str
    channels: int
    lfe: int = 0
    layout: str
    """FFmpeg channel layout, such as ``stereo``."""
    matrix_encoding: str | None = None
    """FFmpeg matrix encoding (``dplii``, Dolby Pro Logic II), or ``None``."""


class PassthruCodecDef(ReframeModel):
    """A codec that a source track can be passed through as, matched on the source track."""

    label: str
    codec_name: str
    """ffprobe ``codec_name``."""
    profiles: list[str] | None = None
    """Only these ffprobe profiles; ``None``: any."""
    exclude_profiles: list[str] = Field(default_factory=list)


class CodecSupport(ReframeModel):
    """What a container holds for one track type."""

    copy_codecs: list[str] = Field(default_factory=list, alias="copy")
    """ffprobe codec names that can be stream-copied in; ``["*"]`` means any codec except
    :attr:`copy_except`."""
    copy_except: list[str] = Field(default_factory=list)
    """With ``copy = ["*"]``: codecs the muxer refuses. They are encoded instead of copied."""
    encode: list[str] = Field(default_factory=list)
    """Codecs (``VideoCodec``, ``AudioCodec``) or subtitle formats (``SubtitleFormat``) that can
    be encoded into the container."""
    copy_args: dict[str, list[str]] = Field(default_factory=dict)
    """Extra arguments needed to copy a codec, by codec name."""

    def can_copy(self, codec_name: str) -> bool:
        if codec_name in self.copy_except:
            return False
        return "*" in self.copy_codecs or codec_name in self.copy_codecs


class TrackFlagDef(ReframeModel):
    """How a track flag is written: its FFmpeg disposition."""

    disposition: str


class ContainerDef(ReframeModel):
    """One output container."""

    id: Container
    label: str
    muxer: str
    """The FFmpeg muxer name, as passed to ``-f``."""
    extensions: list[str]
    """The first extension is the default one."""
    video: CodecSupport
    audio: CodecSupport
    subtitles: CodecSupport
    text_subtitle_target: SubtitleFormat | None = None
    """The format a text subtitle is converted to when the container cannot hold it. ``None``:
    the container takes the text formats it lists."""
    codec_tags: dict[str, str] = Field(default_factory=dict)
    """The ``-tag:v`` value per codec, as HandBrake writes it."""
    chapters: bool
    attachments: bool
    flags: list[TrackFlag]
    """Flags the FFmpeg muxer writes (and ffprobe reads back)."""
    language_format: Literal["iso639_2b", "iso639_2t"]
    """The language tag format: ISO 639-2/B for MKV, ISO 639-2/T for MP4."""
    format_flags: dict[str, list[str]] = Field(default_factory=dict)
    """Arguments for output options: ``web_optimized`` → ``-movflags +faststart``."""
    help: str = ""


class FilterHelp(ReframeModel):
    """The help panel of a filter."""

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
    """A preset of one implementation. Names follow HandBrake where HandBrake has a preset."""

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
    """The HandBrake setting this preset maps from, for reference."""

    def chain_for(self, tune: str | None = None) -> str | None:
        """The chain for ``tune``, or the plain chain when ``tune`` is ``None`` or has no chain
        of its own."""
        if tune is not None and tune in self.tune_chains:
            return self.tune_chains[tune]
        return self.chain


class FilterImplementation(ReframeModel):
    """An FFmpeg implementation of a filter, with its own presets and tunes."""

    id: str
    label: str
    filters: list[str]
    """FFmpeg filters the build must have (``CapabilitySnapshot.has_filter``)."""
    note: str = ""
    requires_tagged_input: bool = False
    """The filter needs the input's colour properties (primaries, transfer, matrix). For an
    untagged source the builder prepends ``setparams`` with the probed or assumed values."""
    combed_only: str | None = None
    """Option appended to the chain when interlace detection is on, so that only the frames it
    flags are processed (``deint=interlaced``)."""
    needs_vulkan: bool = False
    """Listed by ``ffmpeg -filters``, but it fails without a working Vulkan driver. Check it with
    a test run before choosing it."""
    presets: list[FilterPreset]
    tunes: list[FilterTune] = Field(default_factory=list)
    default_preset: str

    def preset(self, preset_id: str) -> FilterPreset | None:
        return next((p for p in self.presets if p.id == preset_id), None)

    def runs_with(self, available: Mapping[str, bool] | None) -> bool:
        """All of ``filters`` are ``available`` (``None``: assume they are)."""
        return available is None or all(available.get(f, False) for f in self.filters)


class FilterDef(ReframeModel):
    """One filter, with its implementations and help text."""

    id: FilterId
    label: str
    analysis: bool = False
    """Interlace detection: it marks frames for deinterlacing and changes no pixels."""
    implementations: list[FilterImplementation]
    """In order of preference: the first is the default when no implementation is chosen."""
    help: FilterHelp

    def implementation(self, implementation_id: str) -> FilterImplementation | None:
        return next((i for i in self.implementations if i.id == implementation_id), None)

    def implementation_for(
        self, config: FilterConfig | None = None, available: Mapping[str, bool] | None = None
    ) -> FilterImplementation | None:
        """The implementation that ``config`` uses.

        With ``config.implementation`` set, that implementation, if it is known and its filters
        are ``available`` (``None``: assume all are). Otherwise the first implementation that
        runs and has ``config.preset``. ``None`` when nothing fits.
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
        """The FFmpeg chain for ``config``, with ``{custom}`` filled in. ``None`` when the
        implementation, preset or tune does not resolve. ``combed_only`` is not added."""
        impl = self.implementation_for(config, available)
        preset = impl.preset(config.preset) if impl is not None else None
        if preset is None:
            return None
        chain = preset.chain_for(config.tune)
        if chain is None:
            return None
        return chain.replace("{custom}", config.custom or "") if preset.custom else chain


class Definitions(ReframeModel):
    """Everything in ``definitions/data``."""

    video_encoders: dict[str, VideoEncoderDef] = Field(default_factory=dict)
    audio_encoders: dict[str, AudioEncoderDef] = Field(default_factory=dict)

    mixdowns: dict[Mixdown, MixdownDef] = Field(default_factory=dict)
    passthru_codecs: dict[PassthruCodec, PassthruCodecDef] = Field(default_factory=dict)
    # Every Container has one (the definitions lint checks it), so callers index it.
    containers: dict[Container, ContainerDef] = Field(default_factory=dict)
    track_flags: dict[TrackFlag, TrackFlagDef] = Field(default_factory=dict)
    filters: dict[FilterId, FilterDef] = Field(default_factory=dict)
    filter_order: list[str] = Field(default_factory=list)
    """The fixed filter order: the filter ids plus :data:`FILTER_STAGES`."""


def interpolate(points: list[tuple[float, float]], x: float) -> float:
    """Piecewise-linear interpolation through increasing ``points``; extrapolates with the end
    segments (callers clamp)."""
    if len(points) < 2:
        raise ValueError("need at least two points")
    for (x0, y0), (x1, y1) in itertools.pairwise(points):
        if x <= x1 or (x1, y1) == points[-1]:
            if math.isclose(x1, x0):
                return y0
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    raise AssertionError("unreachable")  # pragma: no cover


def round_half_up(value: float) -> int:
    """``value`` rounded to the nearest integer, with halves rounded up (``26.5`` → ``27``).
    Unlike :func:`round`, which rounds halves to even. Float noise below 1e-9 is ignored."""
    return math.floor(round(value, 9) + 0.5)


def channels_mixdown(channels: int) -> Mixdown:
    """The mixdown whose bitrate table fits a kept source layout of ``channels`` channels:
    1 mono, 2 stereo, 3 to 6 5.1, 7 and more 7.1; unknown (0) stereo."""
    if channels == 1:
        return "mono"
    if channels <= 2:
        return "stereo"
    if channels <= 6:
        return "5.1"
    return "7.1"
