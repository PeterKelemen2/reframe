"""The built-in presets: ``presets/data/builtin.json`` inside the package (read-only).

The file is a :class:`~reframe.models.PresetFile`. Each preset is modelled on the HandBrake
1.11.2 built-in preset of the same name (``preset/preset_builtin.json`` at tag ``1.11.2``)
and adapted to the FFmpeg encoders of the definitions. Decision 0015 has the mapping, field by
field, and the differences:

========================== ============================== ====================================
Reframe id                 HandBrake 1.11.2 preset         Difference
========================== ============================== ====================================
very-fast-1080p30          Very Fast 1080p30
fast-1080p30               Fast 1080p30                    HandBrake's default
fast-720p30                Fast 720p30
hq-1080p30-surround        HQ 1080p30 Surround
super-hq-1080p30-surround  Super HQ 1080p30 Surround
fast-2160p60-4k-hevc       Fast 2160p60 4K HEVC
creator-1080p60            Creator 1080p60
social-25-mb-1-minute-...  Social 25 MB 1 Minute 720p60
android-1080p30            Android 1080p30
apple-1080p30-surround     Apple 1080p30 Surround
chromecast-1080p30-sur...  Chromecast 1080p30 Surround
h265-mkv-1080p             H.265 MKV 1080p30               default (0024), source fps
h265-mkv-720p              H.265 MKV 720p30                source frame rate, name without 30
h265-mkv-2160p-4k          H.265 MKV 2160p60 4K            source frame rate, name without 60
h264-mkv-1080p             H.264 MKV 1080p30               source frame rate, name without 30
av1-mkv-2160p-4k           AV1 MKV 2160p60 4K              source frame rate, name without 60
vp9-mkv-1080p              VP9 MKV 1080p30                 source frame rate, name without 30
h265-nvenc-1080p           H.265 NVENC 1080p
h265-nvenc-2160p-4k        H.265 NVENC 2160p 4K
h265-qsv-1080p             H.265 QSV 1080p
av1-qsv-2160p-4k           AV1 QSV 2160p 4K
h265-vcn-1080p             H.265 VCN 1080p
av1-vcn-2160p-4k           AV1 VCN 2160p 4K
h265-vaapi-1080p           (H.265 VCN 1080p)               VAAPI: not in HandBrake
production-standard        Production Standard
production-proxy-1080p     Production Proxy 1080p
========================== ============================== ====================================
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources

from reframe.models.migrations import migrate
from reframe.models.preset import Preset, PresetFile

__all__ = ["BUILTIN_FILE", "DEFAULT_BUILTIN_ID", "builtin_ids", "builtin_presets"]

BUILTIN_FILE = "builtin.json"
#: The default preset when the user has not chosen one (decision 0024; HandBrake's default is
#: Fast 1080p30). ``builtin.json`` names the same id in ``default_preset_id``.
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


def builtin_ids() -> frozenset[str]:
    return frozenset(preset.id for preset in _load())
