"""``Reframe.batch`` (05 §C-15; 04-batch-mode.md): group files, derive and merge templates,
resolve a template in every file, save a group template as a preset.

The rest of :mod:`reframe.batch` is pure; this module is the one place that probes, names
and validates (through the other services of the facade). It is not imported by
``reframe.batch`` itself, so the pure engine never depends on the facade.

Contract skeleton (docs/core-breakdown.md, wave 2): built by the C-12 batch task (2a).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Collection, Mapping, Sequence
from typing import Protocol

from reframe.definitions import Definitions
from reframe.models.batch import BatchGroup, BatchGrouping, BatchResolution, MatchLevel
from reframe.models.batch import TemplateSection as Section
from reframe.models.issues import JsonPatchOp, ValidationIssue
from reframe.models.job import JobSettings
from reframe.models.media import MediaSource
from reframe.models.preset import Preset
from reframe.models.settings import AppSettings
from reframe.models.template import JobTemplate
from reframe.probe import ProbeError

__all__ = ["BatchService"]


class _Sources(Protocol):
    async def probe(self, path: str | os.PathLike[str]) -> MediaSource | ProbeError: ...


class _Presets(Protocol):
    def find(self, name_or_id: str) -> Preset | None: ...

    def default(self) -> Preset: ...

    async def create(
        self, template: JobTemplate, name: str, *, category: str = "Custom", description: str = ""
    ) -> Preset | ValidationIssue: ...


class BatchService:
    """Batch / season mode.

    :param sources: probes the files (``Reframe.sources``; probes are cached).
    :param presets: finds templates by preset name or id and saves group templates
        (``Reframe.presets``).
    :param jobs: names and validates the resolved jobs (``Reframe.jobs``).
    :param settings: the current settings (preferred languages, naming, collisions).
    """

    def __init__(
        self,
        *,
        sources: _Sources,
        presets: _Presets,
        jobs: object,
        settings: Callable[[], AppSettings],
        definitions: Definitions | None = None,
    ) -> None:
        self._sources = sources
        self._presets = presets
        self._jobs = jobs
        self._settings = settings
        self._definitions = definitions

    async def group(
        self,
        sources: Sequence[str | os.PathLike[str] | MediaSource],
        *,
        level: MatchLevel = "standard",
    ) -> BatchGrouping:
        """Probe the files (a path that is not probed yet) and group them by fingerprint at
        ``level`` (04 §Grouping): files that differ a little from a group are ``near``
        members with their differences; a file that cannot be probed is an issue."""
        raise NotImplementedError("C-12 batch: group")

    def derive(
        self,
        job: JobSettings,
        source: MediaSource,
        sections: Collection[Section],
        *,
        base: JobTemplate | None = None,
    ) -> JobTemplate:
        """The template of ``job``'s ``sections`` (04 §Deriving rules from a manual
        selection): the most specific track rules for the chosen source tracks, merged into
        ``base`` (``None``: the job's preset, else the default preset)."""
        raise NotImplementedError("C-12 batch: derive")

    def merge(
        self, base: JobTemplate, incoming: JobTemplate, sections: Collection[Section]
    ) -> JobTemplate:
        """``base`` with ``incoming``'s ``sections`` (04: *Apply to group…*)."""
        raise NotImplementedError("C-12 batch: merge")

    async def resolve(
        self,
        template: JobTemplate | str | None,
        sources: Sequence[str | os.PathLike[str] | MediaSource],
        *,
        overrides: Mapping[str, Sequence[JsonPatchOp]] | None = None,
        group: BatchGroup | None = None,
    ) -> BatchResolution:
        """The resolution matrix of ``template`` (a template, a preset name or id; ``None``:
        the default preset) in every file: one :class:`~reframe.models.Resolution` per file
        in episode order (the job with its output name, the track matches, the issues), the
        columns, and the batch-level issues (name collisions). ``overrides``: per-file JSON
        patches, keyed by the file's path as a string."""
        raise NotImplementedError("C-12 batch: resolve")

    async def save_preset(
        self,
        template: JobTemplate,
        name: str,
        *,
        category: str = "Custom",
        description: str = "",
    ) -> Preset | ValidationIssue:
        """Save a group template as a user preset (04 §Save as preset)."""
        raise NotImplementedError("C-12 batch: save as preset")
