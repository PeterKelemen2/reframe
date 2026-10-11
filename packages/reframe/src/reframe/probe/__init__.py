"""Probe and track analysis (C-3).

Entry points:

- :class:`Prober` / :func:`probe_file`: one file → :class:`~reframe.models.MediaSource` or a
  :class:`ProbeError` (never an exception for file or tool problems).
- :func:`probe_folder` / :func:`start_probe_folder`: every media file of a folder, 4 at a time,
  directly or as a background task (:mod:`reframe.tasks`).
- :class:`ProbeCache`: memory + JSON files in ``<cache dir>/probe/``, keyed by path + size +
  mtime and the ffprobe build.
- :func:`parse_ffprobe`: the pure parser (ffprobe JSON → ``MediaSource``), used by the
  snapshot tests with the recorded JSON in ``testdata/probes/``.

Modules: ``ffprobe`` (commands, errors), ``parse``, ``hdr``, ``names`` (commercial codec
names), ``bitrate`` (the bitrate chain), ``mediainfo`` (optional chain step), ``roles`` (role
heuristics), ``cache``, ``prober``, ``folder``.
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
    start_probe_folder,
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
    "start_probe_folder",
    "subtitle_display_name",
    "video_display_name",
]
