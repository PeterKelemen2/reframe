"""Batch / season mode (04-batch-mode.md; C-12, M7): descriptors, fingerprints, groups, the
resolution of a template in each file, and the match report.

Runtime models, never stored as documents: a group template is a
:class:`~reframe.models.JobTemplate` (saved as a preset), and per-file overrides are JSON
patches (:data:`~reframe.models.JsonPatch`) that the client keeps (02 §State model).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field

from reframe.models.base import NonNegativeInt, PositiveInt, ReframeModel
from reframe.models.issues import JsonPatchOp, Severity, ValidationIssue
from reframe.models.job import JobSettings, TrackFlags
from reframe.models.media import HdrFormat, TrackRole
from reframe.models.naming import NameResult

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

#: 04 §Grouping: what two files must share to be in one group.
MatchLevel = Literal["strict", "standard", "loose"]
#: 04 §Three ways to edit → Apply from file: the sections a template can take from a file.
TemplateSection = Literal[
    "dimensions", "filters", "video", "audio", "subtitles", "chapters", "tags", "naming"
]
#: 04 §Resolving rules: ✓ exact, ≈ relaxed, ≈ ambiguous, ✗ missing, "skipped".
MatchStatus = Literal["exact", "relaxed", "ambiguous", "missing", "skipped"]


class TrackDescriptor(ReframeModel):
    """The normalised summary of one stream (04 §Concepts)."""

    kind: Literal["video", "audio", "subtitle"]
    index: NonNegativeInt
    """Absolute stream index."""
    position: NonNegativeInt
    """Position among the streams of its kind (0-based)."""
    codec: str | None = None
    """ffprobe codec name (``truehd``, ``dts``, ``ass``)."""
    codec_family: str | None = None
    """What the loose level compares (``dts`` for DTS and DTS-HD, ``ac3`` for AC-3 and
    E-AC-3, …)."""
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
    label: str = ""
    """For messages: ``eng AC-3 2.0 "Commentary"``."""


class Fingerprint(ReframeModel):
    """The ordered track descriptors of a file plus the video resolution and HDR type, at one
    strictness level (04 §Concepts); ``digest`` is the hash two files compare."""

    level: MatchLevel
    tracks: list[TrackDescriptor] = Field(default_factory=list)
    width: PositiveInt | None = None
    height: PositiveInt | None = None
    hdr: HdrFormat | None = None
    digest: str


class GroupMember(ReframeModel):
    """One file of a group. ``near``: it differs from the group (04: "E05 ⚠ 1 extra track")."""

    path: Path
    match: Literal["exact", "near"] = "exact"
    differences: list[str] = Field(default_factory=list)
    """One line per difference: ``1 extra track (eng AC-3 2.0 "Commentary")``."""


class BatchGroup(ReframeModel):
    """Files that share a fingerprint at ``level`` (04 §Grouping)."""

    id: str
    name: str
    """``Show S01`` (from the parsed file names)."""
    level: MatchLevel
    representative: Path
    """The file the editor shows (the first one by default)."""
    fingerprint: Fingerprint
    """The group's fingerprint (the representative's)."""
    members: list[GroupMember] = Field(default_factory=list)
    """In episode order."""


class BatchGrouping(ReframeModel):
    """``Reframe.batch.group(...)``: the groups, and the files that could not be read."""

    groups: list[BatchGroup] = Field(default_factory=list)
    issues: list[ValidationIssue] = Field(default_factory=list)
    """A file that could not be probed (``source.probe_failed``) is not in any group."""


class TrackMatch(ReframeModel):
    """One cell of the resolution matrix: how one track rule matched in one file
    (04 §Resolving rules in another file)."""

    kind: Literal["audio", "subtitle"]
    rule: NonNegativeInt
    """Index of the rule in ``JobTemplate.audio_rules`` / ``subtitle_rules``."""
    status: MatchStatus
    streams: list[NonNegativeInt] = Field(default_factory=list)
    """The source stream(s) the rule took (several for a ``multiple`` rule)."""
    candidates: list[NonNegativeInt] = Field(default_factory=list)
    """Every stream that matched after the relaxing steps."""
    relaxed: list[str] = Field(default_factory=list)
    """The selector fields that were dropped, in order (``title_pattern``, ``profiles``,
    ``channels``, ``codecs``)."""
    severity: Severity | None = None
    """``None`` for an exact match; warning (relaxed, ambiguous), error (missing, required),
    info (skipped)."""
    message: str = ""
    """``matched without title, profile``, ``2 candidates, picked #3 (source order)``."""


class MatrixColumn(ReframeModel):
    """A column of the resolution matrix (04 §Resolution matrix)."""

    kind: Literal["video", "audio", "subtitle", "name"]
    rule: NonNegativeInt | None = None
    """The rule of an audio / subtitle column."""
    label: str
    """``A1 jpn TrueHD→Opus 5.1``, ``S2 eng Full``, ``Output name``."""


class Resolution(ReframeModel):
    """A template applied to one file: the concrete job, the match report and the issues
    (04 §Concepts)."""

    path: Path
    job: JobSettings | None = None
    """``None`` when the file could not be resolved (it could not be probed)."""
    matches: list[TrackMatch] = Field(default_factory=list)
    naming: NameResult | None = None
    issues: list[ValidationIssue] = Field(default_factory=list)
    status: Literal["ok", "warning", "error"] = "ok"
    """The row's mark: ✓ / ⚠ / ✗ (the worst match or issue)."""
    override: list[JsonPatchOp] = Field(default_factory=list)
    """The per-file override that was applied (04 §Per-file overrides)."""


class BatchResolution(ReframeModel):
    """``Reframe.batch.resolve(...)``: the resolution matrix."""

    group: BatchGroup | None = None
    columns: list[MatrixColumn] = Field(default_factory=list)
    rows: list[Resolution] = Field(default_factory=list)
    """In episode order."""
    issues: list[ValidationIssue] = Field(default_factory=list)
    """Batch-level problems: output name collisions within the batch (04 §Output naming)."""
