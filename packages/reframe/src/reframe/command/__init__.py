"""The command builder (C-7): one job → the exact FFmpeg commands (an ``EncodePlan``).

Pure: no I/O, no clock, no subprocess, no environment reads. The queue (C-11) runs the
plan's steps; the CLI (``reframe plan``) and the command preview show ``display``.

- :func:`build_plan`: the plan of a validated job (:class:`PlanError` otherwise).
- :func:`job_type`: ``encode``, ``remux`` or ``metadata_edit``, with the reason for the Summary
  tab; :func:`in_place_blockers`: why a job cannot edit its source in place (C-13).
- :func:`planned_audio`: what the plan writes for one audio track (copy, or the encoder with
  the mixdown, bitrate and sample rate snapped to what it can do: decision 0024).

Modules: ``builder`` (argument order, steps), ``filtergraph`` (fixed filter order,
escaping, burn-in), ``video`` (encoder arguments, 2-pass, HDR), ``audio``, ``subtitles``,
``metadata`` (languages, flags, chapters, tags), ``mkvpropedit`` (the in-place edit and the
post-mux fix-up, C-13), ``jobtype``, ``quoting`` (``display``).
Decision record 0013 has the choices the plan does not make.
"""

from reframe.command.audio import PlannedAudio, planned_audio
from reframe.command.builder import build_plan, partial_path
from reframe.command.errors import PlanError
from reframe.command.filtergraph import escape_value, filter_path, quote_value, subtitles_filter
from reframe.command.jobtype import in_place_blockers, is_matroska_source, job_type
from reframe.command.quoting import Shell, command_line, quote_posix, quote_windows

__all__ = [
    "PlanError",
    "PlannedAudio",
    "Shell",
    "build_plan",
    "command_line",
    "escape_value",
    "filter_path",
    "in_place_blockers",
    "is_matroska_source",
    "job_type",
    "partial_path",
    "planned_audio",
    "quote_posix",
    "quote_value",
    "quote_windows",
    "subtitles_filter",
]
