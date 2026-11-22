"""The built-in presets: read-only package data in ``presets/data/builtin.json``. They are
HandBrake 1.11.2 presets adapted to the FFmpeg encoders of the definitions.
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources

from reframe.models.migrations import migrate
from reframe.models.preset import Preset, PresetFile

__all__ = ["BUILTIN_FILE", "DEFAULT_BUILTIN_ID", "builtin_presets"]

# See decision 0015 for each id's HandBrake origin and its differences.
BUILTIN_FILE = "builtin.json"
#: The default when the user has not chosen one: an H.265 MKV preset, not HandBrake's x264
#: default. ``builtin.json`` names the same id in ``default_preset_id``.
DEFAULT_BUILTIN_ID = "h265-mkv-1080p"


@cache
def _load() -> tuple[Preset, ...]:
    text = (resources.files("reframe.presets") / "data" / BUILTIN_FILE).read_text("utf-8")
    data = migrate("preset_file", json.loads(text))
    data["presets"] = [migrate("preset", entry) for entry in data.get("presets", [])]
    file = PresetFile.model_validate(data)
    return tuple(preset.model_copy(update={"built_in": True}) for preset in file.presets)


def builtin_presets() -> list[Preset]:
    """The built-in presets, in display order (copies: changing them changes nothing)."""
    return [preset.model_copy(deep=True) for preset in _load()]
