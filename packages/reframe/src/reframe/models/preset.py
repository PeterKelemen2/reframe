"""Presets (03 §Presets, C-9): a job template with an id, a name and a category.

Built-in presets ship as JSON inside the package (read-only); user presets are stored in
``<config>/presets.json`` as a :class:`PresetFile`. Export and import use the same format.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from reframe.models.base import DocumentModel, PositiveInt
from reframe.models.template import JobTemplate

__all__ = ["BUILT_IN_CATEGORIES", "Preset", "PresetFile"]

#: Categories of the built-in presets (HandBrake's, adapted). User presets may use any.
BUILT_IN_CATEGORIES = ("General", "Web", "Devices", "Matroska", "Hardware", "Production")


class Preset(JobTemplate):
    """``Preset`` = ``JobTemplate`` + id, name, category, description, built-in flag."""

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
