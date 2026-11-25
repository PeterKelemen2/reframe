"""Batch / season mode: track descriptors, fingerprints, groups, the resolution of a template in
each file, and the match report.

Runtime models, never stored as documents: a group template is a
:class:`~reframe.models.JobTemplate` (saved as a preset), and per-file overrides are JSON
patches (:data:`~reframe.models.JsonPatch`) that the client keeps.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field

from reframe.models.base import NonNegativeInt, PositiveInt, ReframeModel
from reframe.models.defaults import TrackDecision
from reframe.models.issues import JsonPatchOp, Severity, ValidationIssue
from reframe.models.job import JobSettings, TrackFlags
from reframe.models.media import HdrFormat, TrackRole
from reframe.models.naming import NameResult
from reframe.models.text import DisplayText

__all__ = [
    "BatchGroup",
    "BatchGrouping",
    "BatchResolution",
    "Fingerprint",
    "GroupMember",
    "MatchLevel",
    "MatchStatus",
    "MatrixColumn",
    "Resolution",
    "TemplateSection",
    "TrackDescriptor",
    "TrackMatch",
]

#: How strictly two files must match to share a group.
MatchLevel = Literal["strict", "standard", "loose"]
#: The sections of a template that can be taken from another file.
TemplateSection = Literal[
    "dimensions", "filters", "video", "audio", "subtitles", "chapters", "tags", "naming"
]
#: How one track rule matched in one file.
MatchStatus = Literal["exact", "relaxed", "ambiguous", "missing", "skipped"]


class TrackDescriptor(ReframeModel):
    """The normalised summary of one stream."""

    kind: Literal["video", "audio", "subtitle"]
    index: NonNegativeInt
    """Absolute stream index."""
    position: NonNegativeInt
    """Position among the streams of its kind (0-based)."""
    codec: str | None = None
    """ffprobe codec name (``truehd``, ``dts``, ``ass``)."""
    codec_family: str | None = None
    """What the loose level compares, for example ``dts`` for DTS and DTS-HD."""
    profile: str | None = None
    """The commercial name (``DTS-HD MA``, ``TrueHD Atmos``)."""
    channels: NonNegativeInt | None = None
    language: str | None = None
    """The effective language (BCP 47, normalised)."""
    title: str | None = None
    roles: list[TrackRole] = Field(default_factory=list)
    flags: TrackFlags = Field(default_factory=TrackFlags)
    bitrate: NonNegativeInt | None = None
    """Bits per second, when known."""
    label: DisplayText = ""
    """For messages: ``eng AC-3 2.0 "Commentary"``."""


class Fingerprint(ReframeModel):
    """The ordered track descriptors of a file, plus its video resolution and HDR type, at one
    strictness level. ``digest`` is the hash that two files compare."""

    level: MatchLevel
    tracks: list[TrackDescriptor] = Field(default_factory=list)
    width: PositiveInt | None = None
    height: PositiveInt | None = None
    hdr: HdrFormat | None = None
    digest: str


class GroupMember(ReframeModel):
    """One file of a group. ``near``: it differs from the group."""

    path: Path
    match: Literal["exact", "near"] = "exact"
    differences: list[DisplayText] = Field(default_factory=list)
    """One line per difference: ``1 extra track (eng AC-3 2.0 "Commentary")``."""
    season: NonNegativeInt | None = None
    """The season number from the file name, when there is one."""
    episode: NonNegativeInt | None = None
    """The episode number from the file name, when there is one."""
    sub_title: DisplayText | None = None
    """The episode title from the file name (``{sub_title}``), when there is one."""


class BatchGroup(ReframeModel):
    """Files that share a fingerprint at ``level``."""

    id: str
    name: DisplayText
    """``Show S01`` (from the parsed file names)."""
    level: MatchLevel
    representative: Path
    """The file the editor shows (the first one by default)."""
    fingerprint: Fingerprint
    """The group's fingerprint (the representative's)."""
    members: list[GroupMember] = Field(default_factory=list)
    """In episode order."""


class BatchGrouping(ReframeModel):
    """The groups of a batch, and the files left out of them."""

    groups: list[BatchGroup] = Field(default_factory=list)
    issues: list[ValidationIssue] = Field(default_factory=list)
    """The files that are in no group: one that could not be probed
    (``source.probe_failed``), and one that is the planned output of another file of the
    batch (``batch.already_encoded``, info)."""


class TrackMatch(ReframeModel):
    """One cell of the resolution matrix: how one track rule matched in one file."""

    kind: Literal["audio", "subtitle"]
    rule: NonNegativeInt
    """Index of the rule in ``JobTemplate.audio_rules`` / ``subtitle_rules``."""
    status: MatchStatus
    streams: list[NonNegativeInt] = Field(default_factory=list)
    """The source stream(s) the rule took (several for a ``multiple`` rule)."""
    candidates: list[NonNegativeInt] = Field(default_factory=list)
    """Every stream that matched after the relaxing steps."""
    relaxed: list[str] = Field(default_factory=list)
    """The selector fields that were dropped, in order."""
    severity: Severity | None = None
    """``None`` for an exact match; warning (relaxed, ambiguous), error (missing, required),
    info (skipped)."""
    message: DisplayText = ""
    """``matched without title, profile``, ``2 candidates, picked #3 (source order)``."""
    defaults: bool = False
    """``True``: a rule compiled from the template's audio / subtitle defaults (the template
    has no explicit rules of this kind); ``rule`` is then the index in the compiled rules."""


class MatrixColumn(ReframeModel):
    """A column of the resolution matrix."""

    kind: Literal["video", "audio", "subtitle", "name"]
    rule: NonNegativeInt | None = None
    """The rule of an audio / subtitle column."""
    label: DisplayText
    """``A1 jpn TrueHD→Opus 5.1``, ``S2 eng Full``, ``Output name``."""
    defaults: bool = False
    """``True``: the column of a rule compiled from the template's defaults (see
    :attr:`TrackMatch.defaults`)."""


class Resolution(ReframeModel):
    """A template applied to one file: the concrete job, the match report and the issues."""

    path: Path
    job: JobSettings | None = None
    """``None`` when the file could not be resolved (it could not be probed)."""
    matches: list[TrackMatch] = Field(default_factory=list)
    naming: NameResult | None = None
    issues: list[ValidationIssue] = Field(default_factory=list)
    status: Literal["ok", "warning", "error"] = "ok"
    """The row's mark: ✓ / ⚠ / ✗ (the worst match or issue)."""
    override: list[JsonPatchOp] = Field(default_factory=list)
    """The per-file override that was applied."""
    decisions: list[TrackDecision] = Field(default_factory=list)
    """One per source audio track, in source order: taken by which rule and why, the output
    and the reason (as ``JobDraft.decisions``)."""
    subtitle_decisions: list[TrackDecision] = Field(default_factory=list)
    """One per source subtitle track, in source order."""
    notes: list[DisplayText] = Field(default_factory=list)
    """What the resolution changed or left out, in one line each (generated chapter names,
    a crop that is detected per file, an output name that was the source itself)."""


class BatchResolution(ReframeModel):
    """The resolution matrix."""

    group: BatchGroup | None = None
    columns: list[MatrixColumn] = Field(default_factory=list)
    rows: list[Resolution] = Field(default_factory=list)
    """In episode order."""
    issues: list[ValidationIssue] = Field(default_factory=list)
    """Batch-level problems: output name collisions within the batch."""
