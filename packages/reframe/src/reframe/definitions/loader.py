"""Load and validate ``definitions/data/*.toml`` (C-6). Pure: reads package data only."""

from __future__ import annotations

import tomllib
from functools import cache
from importlib import resources
from typing import Any

from reframe.definitions.models import Definitions, VideoEncoderDef

__all__ = ["load_definitions"]


def _read(name: str) -> dict[str, Any]:
    data = resources.files("reframe.definitions") / "data" / name
    if not data.is_file():
        return {}
    with data.open("rb") as f:
        return tomllib.load(f)


@cache
def load_definitions() -> Definitions:
    """The validated definitions. Cached; raises ``pydantic.ValidationError`` on bad data."""
    raw = _read("video_encoders.toml")
    encoders = {
        key: VideoEncoderDef.model_validate({"id": key, **value})
        for key, value in raw.get("encoder", {}).items()
    }
    return Definitions(video_encoders=encoders)
