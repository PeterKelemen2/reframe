"""Presets: the built-in presets (read-only package data), the user preset store and
:func:`diff`."""

from reframe.presets.builtin import DEFAULT_BUILTIN_ID, builtin_presets
from reframe.presets.diff import diff, diff_documents
from reframe.presets.store import (
    CUSTOM_CATEGORY,
    PRESETS_FILE,
    ConflictPolicy,
    ImportResult,
    PresetExport,
    PresetStore,
    normalise_name,
)

__all__ = [
    "CUSTOM_CATEGORY",
    "DEFAULT_BUILTIN_ID",
    "PRESETS_FILE",
    "ConflictPolicy",
    "ImportResult",
    "PresetExport",
    "PresetStore",
    "builtin_presets",
    "diff",
    "diff_documents",
    "normalise_name",
]
