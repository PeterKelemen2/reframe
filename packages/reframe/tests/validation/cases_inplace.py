"""Rule cases of remux-only and in-place metadata-edit jobs
(C-13, ``reframe.validation.inplace``), added to ``test_rules.CASES`` (see ``EXTRA_CASE_FILES``
there).

Each case: an issue code and path, a change of the clean scenario that must produce it
(positive), and a close change that must not (negative). ``h`` is a namespace with the helpers
of ``test_rules.py`` (``h.Case``, ``h.ERR`` / ``h.WARN`` / ``h.INFO``, ``h.video``, ``h.both``, …).

``in_place`` turns the scenario's job into the in-place edit that ``Reframe.jobs.draft_remux``
drafts (``reframe.metadata.remux_job``): the clean MKV source of the scenario, edited in place.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from reframe.metadata import remux_job


def in_place(s: Any) -> None:
    s.job = remux_job(s.job, s.source, edit_in_place=True)


def encode_first_audio(s: Any) -> None:
    s.job.audio[0].action = "encode"


def read_only_source(s: Any) -> None:
    s.fs.writable_file = lambda path: False


def writable_source(s: Any) -> None:
    s.fs.writable_file = lambda path: True


def other_output(s: Any) -> None:
    s.job.output.path = Path("/out/Movie (2019).mkv")


def cases(h: Any) -> list[Any]:
    case, both, err, warn = h.Case, h.both, h.ERR, h.WARN
    return [
        case(
            "inplace_encoded_track", "inplace.not_possible", "output.edit_in_place", err,
            both(in_place, encode_first_audio), in_place,
        ),
        case(
            "inplace_mp4_output", "inplace.not_possible", "output.edit_in_place", err,
            both(in_place, h.container("mp4")), both(in_place, h.video(passthrough=True)),
        ),
        case(
            "inplace_read_only_source", "inplace.source_not_writable", "output.edit_in_place",
            err, both(in_place, read_only_source), both(in_place, writable_source),
        ),
        case(
            "inplace_mkvpropedit_missing", "tool.mkvpropedit_missing", "output.edit_in_place",
            err, both(in_place, h.mkvpropedit(h.ToolStatus.MISSING)), in_place,
        ),
        case(
            "inplace_output_ignored", "inplace.output_ignored", "output.path", warn,
            both(in_place, other_output), in_place,
        ),
    ]  # fmt: skip
