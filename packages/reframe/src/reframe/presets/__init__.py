"""Presets (C-9): the built-ins (package data, read-only), the user preset store
(``<config>/presets.json``) and ``diff`` for the *modified* marker.

- :func:`builtin_presets` — HandBrake's built-in presets adapted to FFmpeg (decision 0015).
- :class:`PresetStore` — list, get, find, create, save, rename, delete, duplicate,
  set_default, default, export, import_ (name-conflict handling: ``rename`` / ``replace`` /
  ``skip``).
- :func:`diff` — ``diff(template, preset) -> list[FieldChange]``.

The facade (``Reframe.presets``) wraps the store; UIs use that.
"""

from reframe.presets.builtin import DEFAULT_BUILTIN_ID, builtin_ids, builtin_presets
from reframe.presets.diff import diff, diff_documents
from reframe.presets.store import (
    CUSTOM_CATEGORY,
    PRESETS_FILE,
    ConflictPolicy,
    ImportResult,
    PresetStore,
    normalise_name,
)

__all__ = [
    "CUSTOM_CATEGORY",
    "DEFAULT_BUILTIN_ID",
    "PRESETS_FILE",
    "ConflictPolicy",
    "ImportResult",
    "PresetStore",
    "builtin_ids",
    "builtin_presets",
    "diff",
    "diff_documents",
    "normalise_name",
]
