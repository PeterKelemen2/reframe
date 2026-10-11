"""Declarative definitions (C-6): encoders, options, filters, containers.

The data lives in ``definitions/data/*.toml`` and is validated by Pydantic at load time.
"""

from reframe.definitions.loader import load_definitions
from reframe.definitions.models import (
    Definitions,
    EncoderFamily,
    HardwareSetup,
    OperatingSystem,
    Vendor,
    VideoCodec,
    VideoEncoderDef,
)

__all__ = [
    "Definitions",
    "EncoderFamily",
    "HardwareSetup",
    "OperatingSystem",
    "Vendor",
    "VideoCodec",
    "VideoEncoderDef",
    "load_definitions",
]
