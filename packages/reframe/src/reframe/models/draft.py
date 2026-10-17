"""A job drafted from a preset (C-15 ``Reframe.jobs.draft``).

:class:`JobDraft` is a runtime model, never stored: the job settings that a source and a
preset give, with the decisions that made them (the audio codec rules of C-12, the output
name of C-16) and the validation issues of the result. The CLI (``reframe plan``,
``reframe encode``) and later the UI's *Open source* use it.
"""

from __future__ import annotations

from pydantic import Field

from reframe.models.base import ReframeModel
from reframe.models.defaults import TrackDecision
from reframe.models.issues import ValidationIssue
from reframe.models.job import JobSettings
from reframe.models.naming import NameResult

__all__ = ["JobDraft"]


class JobDraft(ReframeModel):
    """``JobService.draft(source, preset)``: the job, why its tracks and name are what they
    are, and its issues."""

    job: JobSettings
    """Filled from the preset (output options, dimensions, filters, video, chapters, tags),
    the source (tracks, the video track's metadata) and the output name."""
    decisions: list[TrackDecision] = Field(default_factory=list)
    """One per source audio track, in source order (C-12 ``draft_tracks``; decisions 0018,
    0031)."""
    subtitle_decisions: list[TrackDecision] = Field(default_factory=list)
    """One per source subtitle track, in source order (C-12's subtitle selection)."""
    naming: NameResult
    """C-16's output name of the source (the template, or the manual name of ``-o``)."""
    issues: list[ValidationIssue] = Field(default_factory=list)
    """``validate(job)`` of the drafted job, and the errors of the track stage (no track for a
    required language: a template path); an ``error`` keeps it out of the queue."""
    notes: list[str] = Field(default_factory=list)
    """What the draft changed or left out, in one line each: an output name that was the
    source file itself, preset options that M2 does not apply yet."""
