"""Probing media files with ffprobe: one file, a folder, and the cache of the results.

A file or tool problem is reported as a :class:`ProbeError` by :class:`Prober` and
:func:`probe_file`, not raised as an exception.
"""

from reframe.probe.cache import CacheKey, ProbeCache
from reframe.probe.ffprobe import (
    PROBE_TIMEOUT,
    ProbeError,
    ProbeErrorKind,
    ProbeTool,
    frames_argv,
    probe_argv,
)
from reframe.probe.folder import (
    MEDIA_EXTENSIONS,
    FolderProbeResult,
    list_media_files,
    natural_key,
    probe_folder,
)
from reframe.probe.names import (
    audio_display_name,
    container_display_name,
    subtitle_display_name,
    video_display_name,
)
from reframe.probe.parse import PARSER_VERSION, parse_ffprobe
from reframe.probe.prober import ProbeOutcome, Prober, probe_file

__all__ = [
    "MEDIA_EXTENSIONS",
    "PARSER_VERSION",
    "PROBE_TIMEOUT",
    "CacheKey",
    "FolderProbeResult",
    "ProbeCache",
    "ProbeError",
    "ProbeErrorKind",
    "ProbeOutcome",
    "ProbeTool",
    "Prober",
    "audio_display_name",
    "container_display_name",
    "frames_argv",
    "list_media_files",
    "natural_key",
    "parse_ffprobe",
    "probe_argv",
    "probe_file",
    "probe_folder",
    "subtitle_display_name",
    "video_display_name",
]
