"""Application settings (03 §Settings, C-9): ``<config>/settings.json``.

One section per Settings page: Tools, Encoders, Output, Languages, Preview, Queue,
Appearance. Paths set by environment variables (``REFRAME_FFMPEG`` …) are not stored here:
they win over these values and are shown read-only (02 §Bundled FFmpeg).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from reframe.models.base import DocumentModel, LanguageTag, PositiveInt
from reframe.models.job import Container
from reframe.models.naming import NamingOptions

__all__ = [
    "AppSettings",
    "AppearanceSettings",
    "CollisionPolicy",
    "EncoderSettings",
    "LanguageSettings",
    "OutputDefaults",
    "PartialFilePolicy",
    "PreviewSettings",
    "QueueSettings",
    "ToolPaths",
    "WhenDone",
]

CollisionPolicy = Literal["ask", "auto_rename", "overwrite"]
PartialFilePolicy = Literal["delete", "keep"]
WhenDone = Literal["nothing", "notify", "quit", "sleep", "shutdown"]


class ToolPaths(DocumentModel):
    """Settings → Tools: path overrides (``None`` = no override). A path may name the binary
    or its folder. The "Use bundled" fix removes the key (``{"op": "remove", "path":
    "/tools/ffmpeg"}``)."""

    ffmpeg: Path | None = None
    ffprobe: Path | None = None
    mkvpropedit: Path | None = None
    mediainfo: Path | None = None


class EncoderSettings(DocumentModel):
    hardware_tests: bool = True
    """Run the hardware test encodes (C-4). Off: hardware encoders stay "unknown"."""


class OutputDefaults(DocumentModel):
    """Settings → Output."""

    naming: NamingOptions = Field(default_factory=NamingOptions)
    default_container: Container = "mkv"
    collision: CollisionPolicy = "auto_rename"
    """``ask`` needs a UI: the CLI and the queue treat it as an error with fixes. The default
    never overwrites and never blocks."""
    partial_file: PartialFilePolicy = "delete"
    """What happens to ``<name>.part.<ext>`` when a job fails or is cancelled."""


class LanguageSettings(DocumentModel):
    favourites: list[LanguageTag] = Field(default_factory=list)
    """Shown first in the language picker."""
    preferred_audio: list[LanguageTag] = Field(default_factory=list)
    """Used by preset rules whose language list is empty (``TrackSelection.languages``)."""
    preferred_subtitle: list[LanguageTag] = Field(default_factory=list)


class PreviewSettings(DocumentModel):
    sample_frames: Annotated[int, Field(ge=1, le=60)] = 10
    cache_size_mb: Annotated[int, Field(ge=0)] = 1024


class QueueSettings(DocumentModel):
    parallel_jobs: Annotated[int, Field(ge=1, le=16)] = 1
    when_done: WhenDone = "nothing"
    sleep_inhibit: bool = True
    notifications: bool = True


class AppearanceSettings(DocumentModel):
    theme: Literal["system", "light", "dark"] = "system"
    density: Literal["comfortable", "compact"] = "comfortable"
    ui_language: str = "en"


class AppSettings(DocumentModel):
    """``<config>/settings.json``."""

    schema_version: PositiveInt = 1
    tools: ToolPaths = Field(default_factory=ToolPaths)
    encoders: EncoderSettings = Field(default_factory=EncoderSettings)
    output: OutputDefaults = Field(default_factory=OutputDefaults)
    languages: LanguageSettings = Field(default_factory=LanguageSettings)
    preview: PreviewSettings = Field(default_factory=PreviewSettings)
    queue: QueueSettings = Field(default_factory=QueueSettings)
    appearance: AppearanceSettings = Field(default_factory=AppearanceSettings)
