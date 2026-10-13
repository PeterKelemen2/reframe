"""``diff(template, preset)`` for the *modified* marker (03 §Presets, C-9).

The two documents are compared as JSON (``model_dump(mode="json")``), field by field:

- Only the fields of :class:`~reframe.models.JobTemplate` count. The preset's identity (id,
  name, category, description, built-in flag), ``schema_version`` and unknown fields do not.
- Objects are compared key by key; a key that only one side has is ``added`` (only the edited
  template has it) or ``removed`` (only the preset has it). Filters are an object keyed by
  filter id, so a filter switched on is ``filters.denoise`` ``added``.
- Lists are compared item by item (``audio_defaults.codec_rules[1].max_bitrate``); extra items
  at the end are ``added`` / ``removed``.
- A union member that changed its kind (rate control ``quality`` → ``bitrate``, size ``fit`` →
  ``source``) is **one** change of the whole object, not a list of its fields.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import JsonValue

from reframe.models.preset import FieldChange
from reframe.models.template import JobTemplate

__all__ = ["diff", "diff_documents"]

#: Keys that name the member of a discriminated union.
DISCRIMINATORS = ("mode", "kind")
#: ``JobTemplate`` fields that are not settings.
IGNORED_FIELDS = frozenset({"schema_version"})


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
    return changes


def diff_documents(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[FieldChange]:
    """The same comparison for any two JSON objects (used for settings changes)."""
    changes: list[FieldChange] = []
    _walk_object("", before, after, changes)
    return changes


def _join(prefix: str, key: str) -> str:
    return f"{prefix}.{key}" if prefix else key


def _walk(
    path: str, old: Any, new: Any, has_old: bool, has_new: bool, out: list[FieldChange]
) -> None:
    if not has_old:
        out.append(FieldChange(path=path, kind="added", value=_json(new)))
    elif not has_new:
        out.append(FieldChange(path=path, kind="removed", preset_value=_json(old)))
    elif isinstance(old, dict) and isinstance(new, dict):
        if any(key in old and key in new and old[key] != new[key] for key in DISCRIMINATORS):
            out.append(FieldChange(path=path, preset_value=_json(old), value=_json(new)))
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
    elif not _same(old, new):
        out.append(FieldChange(path=path, preset_value=_json(old), value=_json(new)))


def _walk_object(
    prefix: str, old: Mapping[str, Any], new: Mapping[str, Any], out: list[FieldChange]
) -> None:
    keys = list(old) + [key for key in new if key not in old]
    for key in keys:
        _walk(_join(prefix, key), old.get(key), new.get(key), key in old, key in new, out)


def _same(a: Any, b: Any) -> bool:
    """JSON equality: ``1 == 1.0``, but ``True`` is not ``1``."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    return bool(a == b)


def _json(value: Any) -> JsonValue:
    return value  # type: ignore[no-any-return]
