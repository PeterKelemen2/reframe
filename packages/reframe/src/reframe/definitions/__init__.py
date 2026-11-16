"""Declarative definitions: encoders, options, filters and containers.

The data lives in ``definitions/data/*.toml``. Pydantic validates it when
:func:`load_definitions` loads it (cached). Only package data is read.
"""

from reframe.definitions.hdr import hdr_options
from reframe.definitions.loader import load_definitions
from reframe.definitions.models import (
    DEFAULT_VAAPI_DEVICE,
    OPTION_CATEGORIES,
    AudioBitrateDef,
    AudioEncoderDef,
    BitrateLimits,
    ChoiceSetting,
    CodecSupport,
    Condition,
    ContainerDef,
    Definitions,
    DerivedValue,
    EncoderOption,
    FilterDef,
    FilterImplementation,
    FixedDefault,
    HardwareSetup,
    OperatingSystem,
    OptionMapping,
    PresetDefault,
    QualityMode,
    RateControlDef,
    VideoEncoderDef,
    X26xParam,
    channels_mixdown,
    fill_placeholders,
)
from reframe.definitions.options import (
    describe_condition,
    effective_option,
    option_context,
    option_default,
    unmet_conditions,
)
from reframe.definitions.quality import convert_quality
from reframe.definitions.search import search_options
from reframe.definitions.support import mapping_supported, supported_presets

__all__ = [
    "DEFAULT_VAAPI_DEVICE",
    "OPTION_CATEGORIES",
    "AudioBitrateDef",
    "AudioEncoderDef",
    "BitrateLimits",
    "ChoiceSetting",
    "CodecSupport",
    "Condition",
    "ContainerDef",
    "Definitions",
    "DerivedValue",
    "EncoderOption",
    "FilterDef",
    "FilterImplementation",
    "FixedDefault",
    "HardwareSetup",
    "OperatingSystem",
    "OptionMapping",
    "PresetDefault",
    "QualityMode",
    "RateControlDef",
    "VideoEncoderDef",
    "X26xParam",
    "channels_mixdown",
    "convert_quality",
    "describe_condition",
    "effective_option",
    "fill_placeholders",
    "hdr_options",
    "load_definitions",
    "mapping_supported",
    "option_context",
    "option_default",
    "search_options",
    "supported_presets",
    "unmet_conditions",
]
