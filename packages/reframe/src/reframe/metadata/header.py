"""Reframe's own Matroska header writer: track languages, names and flags, and the segment
title, written into an existing file in place.

A refused edit leaves the file byte for byte unchanged. Once the first byte is written, every
state a crash or kill can leave is a file with all the old values or all the new ones.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from reframe.models.plan import HeaderEdit

__all__ = ["HeaderEditResult", "HeaderEditStatus", "apply_header_edit"]

HeaderEditStatus = Literal["written", "refused", "failed"]


@dataclass(frozen=True, slots=True)
class HeaderEditResult:
    """The outcome of :func:`apply_header_edit`.

    ``written``: every edit is in the file. ``refused``: nothing was written, the file is
    unchanged. ``failed``: an OS error after the first write; the file holds the old or the new
    values.
    """

    status: HeaderEditStatus
    code: str | None = None
    """``header.<reason>`` for ``refused`` and ``failed``."""
    reason: str | None = None
    """One sentence for the user."""

    @property
    def ok(self) -> bool:
        return self.status == "written"


def apply_header_edit(edit: HeaderEdit) -> HeaderEditResult:
    """Write ``edit`` into ``edit.path``. Blocking: run it in a worker thread.

    Never raises for a file it cannot edit (a refusal) or an OS error (a failure).
    """
    raise NotImplementedError
