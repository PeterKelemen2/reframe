"""Declarative definitions (C-6): encoders, options, filters, containers.

The data lives in ``definitions/data/*.toml`` and is validated by Pydantic at load time
(``load_definitions()``, cached). Pure: package data only.

How the other steps use it:

- **Video (C-7)**: ``Definitions.video_encoders[id]`` (:class:`VideoEncoderDef`).
  Rate control: ``rate_control.quality`` (:class:`QualityMode`: ``args`` / ``params`` with
  ``{value}`` and the ``derived`` names, :meth:`DerivedValue.compute`) or
  ``rate_control.bitrate`` (:class:`BitrateMode`: ``{kbps}``; ``two_pass`` with
  ``{pass}`` / ``{passlog}`` and the turbo / full first-pass arguments). Speed preset, tune,
  profile and level: :class:`ChoiceSetting` (``mapping`` + ``Choice.written``). Advanced
  options: ``options`` (:class:`EncoderOption`, ``mapping``). ``x26x_param`` values are
  joined with ``:`` into ``params_arg`` (composite parts with ``,``). ``extra_args`` are
  always written. The builder adds stream specifiers (``-preset:v:0``).
- **Audio (C-7 / C-12)**: ``audio_encoders[id]`` (:class:`AudioEncoderDef`):
  ``bitrate.by_mixdown`` limits and :meth:`AudioBitrateDef.snap`, ``quality.arg``,
  ``samplerates``, ``mixdowns``; ``Definitions.mixdowns`` (layout, ``matrix_encoding``);
  ``Definitions.passthru_codecs`` (source matching).
- **Containers (C-7 / C-8)**: ``containers[id]`` (:class:`ContainerDef`):
  ``video`` / ``audio`` / ``subtitles`` (:meth:`CodecSupport.can_copy`, ``encode``,
  ``copy_args``), ``text_subtitle_target``, ``flags`` / ``mkvpropedit_flags`` with
  ``Definitions.track_flags`` (disposition and mkvpropedit names), ``codec_tags``,
  ``format_flags`` (``web_optimized``), ``language_format``, ``chapters``, ``attachments``.
- **Filters (C-7)**: ``filters[id]`` (:class:`FilterDef`) in ``filter_order``;
  :meth:`FilterDef.implementation_for` picks the implementation the build has,
  :meth:`FilterPreset.chain` the chain (``{custom}`` = ``FilterConfig.custom``).
- :func:`convert_quality`, :func:`supported_options`, :func:`lint_definitions`.
"""

from reframe.definitions.lint import lint_definitions
from reframe.definitions.loader import load_definitions
from reframe.definitions.models import (
    AudioBitrateDef,
    AudioCodec,
    AudioEncoderDef,
    AudioQualityDef,
    BitrateLimits,
    BitrateMode,
    Choice,
    ChoiceSetting,
    CodecSupport,
    Condition,
    ContainerDef,
    Definitions,
    DerivedValue,
    EncoderDefault,
    EncoderFamily,
    EncoderOption,
    FastDecodeDef,
    FfmpegArg,
    FilterDef,
    FilterHelp,
    FilterId,
    FilterImplementation,
    FilterPreset,
    FilterTune,
    FixedDefault,
    HardwareSetup,
    MixdownDef,
    OperatingSystem,
    OptionDefault,
    OptionMapping,
    PassthruCodecDef,
    PresetDefault,
    PrivateOpt,
    QualityBand,
    QualityMode,
    RateControlDef,
    TrackFlag,
    TrackFlagDef,
    TwoPassDef,
    Vendor,
    VideoCodec,
    VideoEncoderDef,
    X26xParam,
)
from reframe.definitions.quality import convert_quality
from reframe.definitions.support import mapping_supported, supported_options, supported_presets

__all__ = [
    "AudioBitrateDef",
    "AudioCodec",
    "AudioEncoderDef",
    "AudioQualityDef",
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
    "PassthruCodecDef",
    "PresetDefault",
    "PrivateOpt",
    "QualityBand",
    "QualityMode",
    "RateControlDef",
    "TrackFlag",
    "TrackFlagDef",
    "TwoPassDef",
    "Vendor",
    "VideoCodec",
    "VideoEncoderDef",
    "X26xParam",
    "convert_quality",
    "lint_definitions",
    "load_definitions",
    "mapping_supported",
    "supported_options",
    "supported_presets",
]
