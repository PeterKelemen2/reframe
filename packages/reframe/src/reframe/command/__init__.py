"""The command builder (C-7): one job → the exact FFmpeg commands (an ``EncodePlan``).

Pure: no I/O, no clock, no subprocess, no environment reads. The queue (C-11) runs the
plan's steps; the CLI (``reframe plan``) and the command preview show ``display``.

- :func:`build_plan`: the plan of a validated job (:class:`PlanError` otherwise).
- :func:`job_type`: ``encode`` or ``remux``, with the reason for the Summary tab.

Modules: ``builder`` (argument order, steps), ``filtergraph`` (fixed filter order,
escaping, burn-in), ``video`` (encoder arguments, 2-pass, HDR), ``audio``, ``subtitles``,
``metadata`` (languages, flags, chapters, tags), ``jobtype``, ``quoting`` (``display``).
Decision record 0013 has the choices the plan does not make.
"""

from reframe.command.builder import build_plan, partial_path
from reframe.command.errors import PlanError
from reframe.command.filtergraph import escape_value, filter_path, quote_value, subtitles_filter
from reframe.command.jobtype import job_type
from reframe.command.quoting import Shell, command_line, quote_posix, quote_windows

__all__ = [
    "PlanError",
    "Shell",
    "build_plan",
    "command_line",
    "escape_value",
    "filter_path",
    "job_type",
    "partial_path",
    "quote_posix",
    "quote_value",
    "quote_windows",
    "subtitles_filter",
]
