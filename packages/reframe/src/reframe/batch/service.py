"""``Reframe.batch`` (05 §C-15; 04-batch-mode.md): group files, derive and merge templates,
resolve a template in every file, save a group template as a preset.

The rest of :mod:`reframe.batch` is pure; this module is the one place that probes, names
and validates (through the other services of the facade). It is not imported by
``reframe.batch`` itself, so the pure engine never depends on the facade.

:meth:`BatchService.resolve` gives the resolution matrix: for every file in episode order the
pure :func:`~reframe.batch.resolve` (the job and its match report, with the file's override),
then the output name (C-16, through ``Reframe.jobs.name_job``: the template's naming options,
else Settings → Output) and validation (C-8, ``Reframe.jobs.validate``). Batch-level checks
(04 §Output naming: "Name collisions within the batch, or with existing files, are errors"):

- ``batch.name_collision`` (error): two files of the batch get the same output path;
- ``batch.output_is_source`` (error): a file's output is another file of the batch;
- ``batch.output_exists`` (error): the output exists and the collision setting would rename it
  (C-8's ``output.renamed``). With the setting *ask*, C-8's ``output.exists`` error says it
  already; with *overwrite* the user chose to replace it, and C-8's warning stays.

A near member of the group (``resolve(…, group=…)``) gets the warning ``batch.near_match`` with
its differences (04: "E05 ⚠ 1 extra track"). Decision 0040.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Collection, Mapping, Sequence
from pathlib import Path
from typing import Protocol, cast

from reframe.batch.derive import derive_template, merge_template
from reframe.batch.grouping import episode_key, episode_label, group_sources
from reframe.batch.resolve import matrix_columns, resolve, row_status
from reframe.definitions import Definitions, load_definitions
from reframe.models.batch import (
    BatchGroup,
    BatchGrouping,
    BatchResolution,
    MatchLevel,
    Resolution,
)
from reframe.models.batch import TemplateSection as Section
from reframe.models.issues import JsonPatchOp, Severity, ValidationIssue
from reframe.models.job import JobSettings
from reframe.models.media import MediaSource
from reframe.models.naming import NameResult, NamingOptions
from reframe.models.preset import Preset
from reframe.models.settings import AppSettings
from reframe.models.template import JobTemplate
from reframe.probe import ProbeError

__all__ = ["PROBE_CONCURRENCY", "BatchService"]

#: Files probed at the same time by :meth:`BatchService.group` and
#: :meth:`BatchService.resolve` (each probe is one ffprobe; the probe cache makes a second
#: one cheap).
PROBE_CONCURRENCY = 4


class _Sources(Protocol):
    async def probe(self, path: str | os.PathLike[str]) -> MediaSource | ProbeError: ...


class _Presets(Protocol):
    def find(self, name_or_id: str) -> Preset | None: ...

    def default(self) -> Preset: ...

    async def create(
        self, template: JobTemplate, name: str, *, category: str = "Custom", description: str = ""
    ) -> Preset | ValidationIssue: ...


class _Jobs(Protocol):
    """What the batch service needs from ``Reframe.jobs`` (:class:`~reframe.jobs.JobService`)."""

    async def name_job(
        self,
        job: JobSettings,
        source: MediaSource,
        *,
        naming: NamingOptions | None = None,
        output: Path | None = None,
    ) -> tuple[JobSettings, NameResult, list[str]]: ...

    async def validate(
        self,
        job: JobSettings,
        source: MediaSource | None = None,
        *,
        naming: NamingOptions | None = None,
    ) -> list[ValidationIssue]: ...


def _key(path: str | os.PathLike[str]) -> str:
    """One spelling of a path for comparisons: absolute, case-folded where the OS does."""
    return os.path.normcase(os.path.abspath(path))


def _near_issue(differences: Sequence[str]) -> ValidationIssue:
    """A near member of the group (04: "E05 ⚠ 1 extra track …"): the user checks that the
    group's rules suit it."""
    return ValidationIssue(
        severity=Severity.WARNING,
        code="batch.near_match",
        path="source",
        message=f"Near match of the group: {'; '.join(differences)}.",
    )


def _probe_issue(error: ProbeError) -> ValidationIssue:
    detail = f" ({error.detail})" if error.detail else ""
    return ValidationIssue(
        severity=Severity.ERROR,
        code="source.probe_failed",
        path="source",
        message=f"{error.path.name} cannot be read: {error.message}{detail}",
    )


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
        self._jobs = cast(_Jobs, jobs)
        self._settings = settings
        self._definitions = definitions

    @property
    def definitions(self) -> Definitions:
        if self._definitions is None:
            self._definitions = load_definitions()
        return self._definitions

    # ------------------------------------------------------------------ probing

    async def _probe_all(
        self, sources: Sequence[str | os.PathLike[str] | MediaSource]
    ) -> list[tuple[Path, MediaSource | ProbeError]]:
        """Each source probed (a :class:`MediaSource` is taken as it is), in the given order;
        a file given twice is probed once."""
        gate = asyncio.Semaphore(PROBE_CONCURRENCY)
        seen: set[str] = set()
        unique: list[str | os.PathLike[str] | MediaSource] = []
        for item in sources:
            path = item.ref.path if isinstance(item, MediaSource) else Path(item)
            key = _key(path)
            if key not in seen:
                seen.add(key)
                unique.append(item)

        async def one(
            item: str | os.PathLike[str] | MediaSource,
        ) -> tuple[Path, MediaSource | ProbeError]:
            if isinstance(item, MediaSource):
                return item.ref.path, item
            async with gate:
                found = await self._sources.probe(item)
            path = found.ref.path if isinstance(found, MediaSource) else found.path
            return path, found

        return list(await asyncio.gather(*(one(item) for item in unique)))

    # ------------------------------------------------------------------ grouping

    async def group(
        self,
        sources: Sequence[str | os.PathLike[str] | MediaSource],
        *,
        level: MatchLevel = "standard",
    ) -> BatchGrouping:
        """Probe the files (a path that is not probed yet) and group them by fingerprint at
        ``level`` (04 §Grouping): files that differ a little from a group are ``near``
        members with their differences; a file that cannot be probed is an issue."""
        probed = await self._probe_all(sources)
        media = [found for _, found in probed if isinstance(found, MediaSource)]
        issues = [_probe_issue(found) for _, found in probed if isinstance(found, ProbeError)]
        groups = await asyncio.to_thread(group_sources, media, level)
        return BatchGrouping(groups=groups, issues=issues)

    # ------------------------------------------------------------------ templates

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
        if base is None:
            found = self._presets.find(job.preset_id) if job.preset_id else None
            base = found if found is not None else self._presets.default()
        return derive_template(job, source, sections, base=base)

    def merge(
        self, base: JobTemplate, incoming: JobTemplate, sections: Collection[Section]
    ) -> JobTemplate:
        """``base`` with ``incoming``'s ``sections`` (04: *Apply to group…*)."""
        return merge_template(base, incoming, sections)

    def _template(
        self, template: JobTemplate | str | None
    ) -> tuple[JobTemplate, list[ValidationIssue]]:
        if isinstance(template, JobTemplate):
            return template, []
        if template is None:
            return self._presets.default(), []
        found = self._presets.find(template)
        if found is not None:
            return found, []
        fallback = self._presets.default()
        return fallback, [
            ValidationIssue(
                severity=Severity.ERROR,
                code="preset.not_found",
                path="preset_id",
                message=(
                    f'There is no preset "{template}". The files were resolved with the default '
                    f'preset "{fallback.name}" so that their other issues can be shown.'
                ),
            )
        ]

    # ------------------------------------------------------------------ resolving

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
        chosen, template_issues = self._template(template)
        settings = self._settings()
        naming = chosen.naming if chosen.naming is not None else settings.output.naming
        patches = {_key(path): ops for path, ops in (overrides or {}).items()}
        probed = await self._probe_all(sources)
        members = group.members if group is not None else []
        rank = {_key(m.path): n for n, m in enumerate(members)}
        near = {_key(m.path): m.differences for m in members if m.match == "near"}
        probed.sort(key=lambda item: (rank.get(_key(item[0]), len(rank)), episode_key(item[0])))
        rows: list[Resolution] = []
        for path, found in probed:
            if isinstance(found, ProbeError):
                issues = [*template_issues, _probe_issue(found)]
                rows.append(Resolution(path=path, issues=issues, status="error"))
                continue
            first = list(template_issues)
            if _key(path) in near:
                first.append(_near_issue(near[_key(path)]))
            rows.append(await self._row(chosen, found, patches.get(_key(path)), naming, first))
        rows, batch_issues = _collisions(rows)
        columns = await asyncio.to_thread(
            matrix_columns, chosen, definitions=self.definitions, languages=settings.languages
        )
        return BatchResolution(
            group=group,
            columns=columns,
            rows=rows,
            issues=[*template_issues, *batch_issues],
        )

    async def _row(
        self,
        template: JobTemplate,
        source: MediaSource,
        override: Sequence[JsonPatchOp] | None,
        naming: NamingOptions,
        template_issues: Sequence[ValidationIssue],
    ) -> Resolution:
        """One file: the pure resolution, then its name and validation."""
        resolution = await asyncio.to_thread(
            resolve,
            template,
            source,
            override,
            definitions=self.definitions,
            languages=self._settings().languages,
        )
        assert resolution.job is not None  # resolve always makes a job
        job, name, notes = await self._jobs.name_job(resolution.job, source, naming=naming)
        checks = await self._jobs.validate(job, source, naming=naming)
        issues = [*template_issues, *resolution.issues, *checks]
        return resolution.model_copy(
            update={
                "job": job,
                "naming": name,
                "issues": issues,
                "notes": [*resolution.notes, *notes],
                "status": row_status(resolution.matches, issues),
            }
        )

    # ------------------------------------------------------------------ presets

    async def save_preset(
        self,
        template: JobTemplate,
        name: str,
        *,
        category: str = "Custom",
        description: str = "",
    ) -> Preset | ValidationIssue:
        """Save a group template as a user preset (04 §Save as preset)."""
        return await self._presets.create(
            template, name, category=category, description=description
        )


def _collisions(rows: list[Resolution]) -> tuple[list[Resolution], list[ValidationIssue]]:
    """The batch-level name checks (see the module doc): an issue on each row concerned, and
    one batch issue per shared output path."""
    added: dict[int, list[ValidationIssue]] = {}
    batch: list[ValidationIssue] = []
    sources = {_key(row.path): n for n, row in enumerate(rows)}
    outputs: dict[str, list[int]] = {}
    for n, row in enumerate(rows):
        if row.job is not None and row.job.output.path is not None:
            outputs.setdefault(_key(row.job.output.path), []).append(n)

    def label(n: int) -> str:
        return episode_label(rows[n].path, season=True)

    for key, numbers in outputs.items():
        path = rows[numbers[0]].job.output.path  # type: ignore[union-attr]
        assert path is not None
        if len(numbers) > 1:
            names = ", ".join(label(n) for n in numbers)
            batch.append(
                ValidationIssue(
                    severity=Severity.ERROR,
                    code="batch.name_collision",
                    path="output.path",
                    message=f"{len(numbers)} files get the output name {path.name}: {names}.",
                )
            )
            for n in numbers:
                others = ", ".join(label(m) for m in numbers if m != n)
                added.setdefault(n, []).append(
                    ValidationIssue(
                        severity=Severity.ERROR,
                        code="batch.name_collision",
                        path="output.path",
                        message=(
                            f"{path.name} is also the output name of {others} in this batch. "
                            "Use a naming template with the episode ({episode_code} or "
                            "{episode}) or another name for this file."
                        ),
                    )
                )
        owner = sources.get(key)
        if owner is not None:
            for n in numbers:
                if n == owner:
                    continue  # C-8's output.same_as_source says it
                added.setdefault(n, []).append(
                    ValidationIssue(
                        severity=Severity.ERROR,
                        code="batch.output_is_source",
                        path="output.path",
                        message=(
                            f"The output {path.name} is the source file of {label(owner)} in "
                            "this batch."
                        ),
                    )
                )
    for n, row in enumerate(rows):
        if row.job is None or row.job.output.path is None:
            continue
        if any(issue.code == "output.renamed" for issue in row.issues):
            added.setdefault(n, []).append(
                ValidationIssue(
                    severity=Severity.ERROR,
                    code="batch.output_exists",
                    path="output.path",
                    message=(
                        f"{row.job.output.path.name} already exists. In a batch an existing "
                        "output is an error (04 §Output naming): remove it, or set the "
                        "collision setting to overwrite."
                    ),
                )
            )
    if not added:
        return rows, batch
    fixed = list(rows)
    for n, issues in added.items():
        row = fixed[n]
        all_issues = [*row.issues, *issues]
        fixed[n] = row.model_copy(
            update={"issues": all_issues, "status": row_status(row.matches, all_issues)}
        )
    return fixed, batch
