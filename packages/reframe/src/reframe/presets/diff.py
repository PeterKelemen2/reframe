"""Field-by-field JSON diff of two templates, for the *modified* marker. Only ``JobTemplate``
fields count, and a union member that changes its kind is one change of the whole object.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from reframe.jsonpatch import json_equal
from reframe.models.preset import FieldChange
from reframe.models.template import JobTemplate

__all__ = ["diff", "diff_documents"]

#: Keys that name the member of a discriminated union.
DISCRIMINATORS = ("mode", "kind")
#: ``JobTemplate`` fields that are not settings.
IGNORED_FIELDS = frozenset({"schema_version"})
#: Crop modes whose rectangle is a detection result, not a setting.
DETECTED_CROP_MODES = frozenset({"auto", "conservative"})


def diff(template: JobTemplate, preset: JobTemplate) -> list[FieldChange]:
    """What ``template`` (the edited settings) changes against ``preset``. Empty = unmodified.

    ``preset`` may be a :class:`~reframe.models.Preset`: only its template fields count.
    """
    fields = [name for name in JobTemplate.model_fields if name not in IGNORED_FIELDS]
    before = preset.model_dump(mode="json", include=set(fields))
    after = template.model_dump(mode="json", include=set(fields))
    changes: list[FieldChange] = []
    for name in fields:
        _walk(name, before.get(name), after.get(name), name in before, name in after, changes)
    if _crop_mode(after) in DETECTED_CROP_MODES and _crop_mode(after) == _crop_mode(before):
        changes = [c for c in changes if not c.path.startswith("dimensions.crop.rect")]
    return changes


def _crop_mode(template: Mapping[str, Any]) -> Any:
    return (template.get("dimensions") or {}).get("crop", {}).get("mode")


def diff_documents(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[FieldChange]:
    """The same comparison for any two JSON objects."""
    changes: list[FieldChange] = []
    _walk_object("", before, after, changes)
    return changes


def _join(prefix: str, key: str) -> str:
    return f"{prefix}.{key}" if prefix else key


def _walk(
    path: str, old: Any, new: Any, has_old: bool, has_new: bool, out: list[FieldChange]
) -> None:
    if not has_old:
        out.append(FieldChange(path=path, kind="added", value=new))
    elif not has_new:
        out.append(FieldChange(path=path, kind="removed", preset_value=old))
    elif isinstance(old, dict) and isinstance(new, dict):
        if any(key in old and key in new and old[key] != new[key] for key in DISCRIMINATORS):
            out.append(FieldChange(path=path, preset_value=old, value=new))
        else:
            _walk_object(path, old, new, out)
    elif isinstance(old, list) and isinstance(new, list):
        for index in range(max(len(old), len(new))):
            _walk(
                f"{path}[{index}]",
                old[index] if index < len(old) else None,
                new[index] if index < len(new) else None,
                index < len(old),
                index < len(new),
                out,
            )
    elif not json_equal(old, new):
        out.append(FieldChange(path=path, preset_value=old, value=new))


def _walk_object(
    prefix: str, old: Mapping[str, Any], new: Mapping[str, Any], out: list[FieldChange]
) -> None:
    keys = list(old) + [key for key in new if key not in old]
    for key in keys:
        _walk(_join(prefix, key), old.get(key), new.get(key), key in old, key in new, out)
