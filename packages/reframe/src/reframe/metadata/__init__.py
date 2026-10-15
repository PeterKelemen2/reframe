"""Metadata edit and remux (05 §C-13): the ``metadata_edit`` job type, the mkvpropedit builder,
the post-mux fix-up, the re-probe check.

Contract stub: built by the C-13 task (wave 1d). ``Reframe.jobs.draft_remux`` calls
:func:`remux_job`; the signature is the contract of ``docs/core-breakdown.md``.
"""

from __future__ import annotations

from reframe.definitions import Definitions
from reframe.models.job import JobSettings
from reframe.models.media import MediaSource

__all__ = ["remux_job"]


def remux_job(
    job: JobSettings,
    source: MediaSource,
    *,
    edit_in_place: bool = True,
    definitions: Definitions | None = None,
) -> JobSettings:
    """``job`` turned into a remux-only job (03 §Remux-only jobs): video passthrough, every
    source audio and subtitle track copied in source order with its metadata, and
    ``output.edit_in_place`` = ``edit_in_place``. Pure. The output path and naming of ``job``
    are kept, except what an in-place edit needs. A metadata change on the result then gives
    the job type ``metadata_edit`` (MKV source, edit in place) or ``remux``."""
    raise NotImplementedError("C-13 remux job")
