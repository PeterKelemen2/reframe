"""Presets: a job template with an id, a name and a category.

Built-in presets ship as JSON inside the package (read-only); user presets are stored in
``<config>/presets.json`` as a :class:`PresetFile`. Export and import use the same format.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, JsonValue

from reframe.models.base import DocumentModel, PositiveInt, ReframeModel
from reframe.models.template import JobTemplate

__all__ = ["BUILT_IN_CATEGORIES", "FieldChange", "Preset", "PresetFile"]

#: Categories of the built-in presets (HandBrake's, adapted). User presets may use any.
BUILT_IN_CATEGORIES = ("General", "Web", "Devices", "Matroska", "Hardware", "Production")


class Preset(JobTemplate):
    """A job template saved as a preset."""

    id: Annotated[str, Field(min_length=1)]
    """Stable identifier (built-ins: a slug such as ``h265-mkv-1080p``; user presets: a
    UUID)."""
    name: Annotated[str, Field(min_length=1)]
    category: str = "Custom"
    description: str = ""
    built_in: bool = False


class PresetFile(DocumentModel):
    """``<config>/presets.json`` and the export format (one preset or all)."""

    schema_version: PositiveInt = 1
    presets: list[Preset] = Field(default_factory=list)
    default_preset_id: str | None = None


class FieldChange(ReframeModel):
    """One difference between edited settings and the preset they started from, for the
    *modified* marker."""

    path: str
    """Dotted field path, as in ``ValidationIssue.path``: ``video.encoder``,
    ``audio_defaults.codec_rules[0].max_bitrate``."""
    kind: Literal["changed", "added", "removed"] = "changed"
    """``added``: only the edited settings have the field (or list item); ``removed``: only
    the preset has it."""
    preset_value: JsonValue = None
    """The preset's value (``None`` for ``added``)."""
    value: JsonValue = None
    """The edited value (``None`` for ``removed``)."""
