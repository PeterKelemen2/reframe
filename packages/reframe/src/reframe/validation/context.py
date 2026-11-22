"""What the rules see: the job (or template) and what validation knows around it.

The derived values are computed once per validation and shared by the rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from reframe.definitions import ContainerDef, Definitions
from reframe.dimensions import compute_geometry, job_source_geometry
from reframe.models.capabilities import CapabilitySnapshot
from reframe.models.geometry import Geometry, SourceGeometry
from reframe.models.job import JobSettings
from reframe.models.media import AudioStream, MediaSource, SubtitleStream, VideoStream
from reframe.models.naming import NameResult, NamingOptions
from reframe.models.settings import AppSettings
from reframe.models.template import JobTemplate
from reframe.models.tools import ToolSet
from reframe.naming import resolve_output_name
from reframe.validation.fs import FileSystemView

__all__ = ["JobContext", "TemplateContext"]


@dataclass
class JobContext:
    """The input of a job rule."""

    job: JobSettings
    source: MediaSource
    caps: CapabilitySnapshot
    tools: ToolSet
    fs: FileSystemView
    settings: AppSettings
    definitions: Definitions
    naming: NamingOptions
    """The effective naming options (the preset's, else Settings → Output)."""

    subject: str | None = None

    @property
    def doc(self) -> JobSettings | JobTemplate:
        """What a rule shared with templates checks: the job."""
        return self.job

    @cached_property
    def container(self) -> ContainerDef:
        return self.definitions.containers[self.job.output.container]

    @cached_property
    def video_stream(self) -> VideoStream | None:
        """The main video stream (the first one), which the command builder encodes."""
        return self.source.video[0] if self.source.video else None

    @cached_property
    def audio_streams(self) -> dict[int, AudioStream]:
        return {stream.index: stream for stream in self.source.audio}

    @cached_property
    def subtitle_streams(self) -> dict[int, SubtitleStream]:
        return {stream.index: stream for stream in self.source.subtitles}

    @cached_property
    def geometry(self) -> Geometry | None:
        """The geometry of the encoded picture; ``None`` for video passthrough or a source
        without video."""
        if self.job.video.passthrough or self.source_geometry is None:
            return None
        return compute_geometry(self.source_geometry, self.job.dimensions)

    @cached_property
    def source_geometry(self) -> SourceGeometry | None:
        """The geometry of the main video stream, as the command builder sees it."""
        if self.video_stream is None:
            return None
        return job_source_geometry(self.video_stream, self.job)

    @cached_property
    def output_size(self) -> tuple[int, int] | None:
        if self.geometry is not None:
            return (self.geometry.scaled_width, self.geometry.scaled_height)
        if self.video_stream is not None:
            return (self.video_stream.width, self.video_stream.height)
        return None

    @cached_property
    def duration(self) -> float | None:
        """The source duration in seconds (container, else the main video stream)."""
        if self.source.container.duration is not None:
            return self.source.container.duration
        return self.video_stream.duration if self.video_stream is not None else None

    @cached_property
    def name(self) -> NameResult:
        """The output name of the source, read through :attr:`fs`."""
        return resolve_output_name(
            Path(self.job.source.path),
            self.naming,
            job=self.job,
            source=self.source,
            output_size=self.output_size,
            fs=self.fs,
            definitions=self.definitions,
        )


@dataclass
class TemplateContext:
    """The input of a template rule: what a preset can be checked for without a source."""

    template: JobTemplate
    caps: CapabilitySnapshot
    definitions: Definitions
    subject: str | None = None

    @property
    def doc(self) -> JobSettings | JobTemplate:
        """What a rule shared with jobs checks: the template."""
        return self.template

    @cached_property
    def container(self) -> ContainerDef:
        return self.definitions.containers[self.template.output.container]
