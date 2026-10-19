"""A job drafted from a preset.

:class:`JobDraft` is a runtime model, never stored: the job settings that a source and a
preset give, with the decisions and the output name that made them, and the validation issues
of the result.
"""

from __future__ import annotations

from pydantic import Field

from reframe.models.base import ReframeModel
from reframe.models.defaults import TrackDecision
from reframe.models.issues import ValidationIssue
from reframe.models.job import JobSettings
from reframe.models.naming import NameResult
from reframe.models.text import DisplayText

__all__ = ["JobDraft"]


class JobDraft(ReframeModel):
    """The job drafted from a preset: why its tracks and name are what they are, and its
    issues."""

    job: JobSettings
    """Filled from the preset (output options, dimensions, filters, video, chapters, tags),
    the source (tracks, the video track's metadata) and the output name."""
    decisions: list[TrackDecision] = Field(default_factory=list)
    """One per source audio track, in source order."""
    subtitle_decisions: list[TrackDecision] = Field(default_factory=list)
    """One per source subtitle track, in source order."""
    naming: NameResult
    """The output name of the source: from the template, or the manual name given with ``-o``."""
    issues: list[ValidationIssue] = Field(default_factory=list)
    """Issues of the drafted job, and the errors of the track stage (no track for a required
    language: a template path); an ``error`` keeps it out of the queue."""
    notes: list[DisplayText] = Field(default_factory=list)
    """What the draft changed or left out, in one line each: an output name that was the
    source file itself, preset options the draft does not apply."""
