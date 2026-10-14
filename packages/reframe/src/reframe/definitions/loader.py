"""Load and validate ``definitions/data/*.toml`` (C-6). Pure: reads package data only.

Files:

- ``video_encoders.toml``: ``[encoder.<id>]`` tables. ``extends = "<base>"`` (or a list)
  merges ``[base.<name>]`` tables under the encoder's own keys (tables merge key by key, other
  values are replaced). ``option_sets = ["<set>", …]`` prepends the options of
  ``options/<file>.toml`` ``[[set.<set>]]`` arrays to the encoder's own ``options``.
- ``audio_encoders.toml``: ``[encoder.<id>]``, ``[mixdown.<id>]``, ``[passthru.<id>]``.
- ``containers.toml``: ``[container.<id>]``, ``[flag.<id>]``.
- ``filters.toml``: ``filter_order`` and ``[filter.<id>]``.
"""

from __future__ import annotations

import copy
import tomllib
from functools import cache
from importlib import resources
from importlib.resources.abc import Traversable
from typing import Any

from reframe.definitions.models import Definitions

__all__ = ["load_definitions", "load_raw", "resolve_video_encoders"]


def _data() -> Traversable:
    return resources.files("reframe.definitions") / "data"


def _read(name: str) -> dict[str, Any]:
    data = _data() / name
    if not data.is_file():
        return {}
    with data.open("rb") as f:
        return tomllib.load(f)


def _option_sets() -> dict[str, list[dict[str, Any]]]:
    folder = _data() / "options"
    sets: dict[str, list[dict[str, Any]]] = {}
    if not folder.is_dir():
        return sets
    for entry in sorted(folder.iterdir(), key=lambda e: e.name):
        if not entry.name.endswith(".toml"):
            continue
        with entry.open("rb") as f:
            for name, options in tomllib.load(f).get("set", {}).items():
                if name in sets:
                    raise ValueError(f"option set {name!r} is defined twice")
                sets[name] = options
    return sets


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def resolve_video_encoders(
    raw: dict[str, Any], option_sets: dict[str, list[dict[str, Any]]]
) -> dict[str, dict[str, Any]]:
    """Apply ``extends`` and ``option_sets`` to the raw ``video_encoders.toml`` data."""
    bases: dict[str, dict[str, Any]] = raw.get("base", {})
    resolved: dict[str, dict[str, Any]] = {}
    for key, table in raw.get("encoder", {}).items():
        value = copy.deepcopy(table)
        extends = value.pop("extends", [])
        merged: dict[str, Any] = {}
        for name in [extends] if isinstance(extends, str) else extends:
            if name not in bases:
                raise ValueError(f"encoder {key!r} extends unknown base {name!r}")
            merged = _merge(merged, copy.deepcopy(bases[name]))
        merged = _merge(merged, value)
        sets = merged.pop("option_sets", [])
        options: list[dict[str, Any]] = []
        for name in sets:
            if name not in option_sets:
                raise ValueError(f"encoder {key!r} uses unknown option set {name!r}")
            options.extend(copy.deepcopy(option_sets[name]))
        merged["options"] = [*options, *merged.get("options", [])]
        resolved[key] = {"id": key, **merged}
    return resolved


def load_raw() -> dict[str, Any]:
    """The definitions as plain data, ready for ``Definitions.model_validate``."""
    video_raw = _read("video_encoders.toml")
    audio_raw = _read("audio_encoders.toml")
    containers_raw = _read("containers.toml")
    filters_raw = _read("filters.toml")
    return {
        "video_encoders": resolve_video_encoders(video_raw, _option_sets()),
        "audio_encoders": {
            key: {"id": key, **value} for key, value in audio_raw.get("encoder", {}).items()
        },
        "mixdowns": audio_raw.get("mixdown", {}),
        "passthru_codecs": audio_raw.get("passthru", {}),
        "containers": {
            key: {"id": key, **value} for key, value in containers_raw.get("container", {}).items()
        },
        "track_flags": containers_raw.get("flag", {}),
        "filters": {
            key: {"id": key, **value} for key, value in filters_raw.get("filter", {}).items()
        },
        "filter_order": filters_raw.get("filter_order", []),
    }


@cache
def load_definitions() -> Definitions:
    """The validated definitions. Cached; raises ``pydantic.ValidationError`` on bad data."""
    return Definitions.model_validate(load_raw())
