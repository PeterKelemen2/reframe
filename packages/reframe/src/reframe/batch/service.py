"""``Reframe.batch``: group files, derive and merge templates, resolve a template in every file,
and save a group template as a preset.

The rest of :mod:`reframe.batch` is pure. This module is the one place that probes, names and
validates, through the other services of the facade, so the pure engine never depends on the
facade.

The batch-level name checks run over the files of every group, so a job never writes a file of
another group. A file that is the planned output of another file of the batch is left out: an
earlier run's output is not encoded again.

Files are compared as files, not spellings (:func:`~reframe.jobs.file_key`): a file given twice,
also through a link or a hard link, is probed and resolved once. Messages keep the paths as they
were given.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Collection, Mapping, Sequence
from pathlib import Path
from typing import Protocol, cast

from reframe.batch.derive import derive_template, merge_template
from reframe.batch.grouping import episode_key, episode_labels, group_sources
from reframe.batch.resolve import matrix_columns, resolve, row_status
from reframe.definitions import Definitions, load_definitions
from reframe.jobs import file_key
from reframe.models.batch import (
    BatchGroup,
    BatchGrouping,
    BatchResolution,
    GroupMember,
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


def _near_issue(differences: Sequence[str]) -> ValidationIssue:
    return ValidationIssue(
        severity=Severity.WARNING,
        code="batch.near_match",
        path="source",
        message=f"Near match of the group: {'; '.join(differences)}.",
    )


def _already_encoded(file: Path, owner: Path, output: Path) -> ValidationIssue:
    same = f" (the same file as {output.name})" if output.name != file.name else ""
    return ValidationIssue(
        severity=Severity.INFO,
        code="batch.already_encoded",
        path="source",
        message=(
            f"{file.name} is the planned output of {owner.name} with this preset{same}: it is "
            "left out of the batch (an earlier output is not encoded again)."
        ),
    )


type _Probed = MediaSource | ProbeError
type _Patches = dict[str, Sequence[JsonPatchOp]]


def _patches(overrides: Mapping[str, Sequence[JsonPatchOp]] | None) -> _Patches:
    """The overrides by :func:`~reframe.jobs.file_key`, so a file's patch is found whatever the
    spelling of its path. Blocking."""
    return {file_key(path): ops for path, ops in (overrides or {}).items()}


def _keyed(probed: Sequence[tuple[Path, _Probed]]) -> list[tuple[str, Path, _Probed]]:
    """Each probed file with its :func:`~reframe.jobs.file_key`. Blocking."""
    return [(file_key(path), path, found) for path, found in probed]


def _ordered(
    probed: Sequence[tuple[Path, _Probed]], members: Sequence[GroupMember]
) -> list[tuple[str, Path, _Probed]]:
    """:func:`_keyed` ``probed`` in the group's order (``members``, by file), else in episode
    order. Blocking: the episode parser and the file keys stat the files, so this runs in a
    worker thread."""
    rank = {file_key(m.path): n for n, m in enumerate(members)}
    return sorted(
        _keyed(probed), key=lambda item: (rank.get(item[0], len(rank)), episode_key(item[1]))
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

    async def _probe_all(
        self, sources: Sequence[str | os.PathLike[str] | MediaSource]
    ) -> list[tuple[Path, MediaSource | ProbeError]]:
        """Each source probed (a :class:`MediaSource` is taken as it is), in the given order. A
        file given twice is probed once, in its first spelling."""
        gate = asyncio.Semaphore(PROBE_CONCURRENCY)
        paths = [item.ref.path if isinstance(item, MediaSource) else Path(item) for item in sources]
        keys = await asyncio.to_thread(lambda: [file_key(path) for path in paths])
        seen: set[str] = set()
        unique: list[str | os.PathLike[str] | MediaSource] = []
        for item, key in zip(sources, keys, strict=True):
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

    async def group(
        self,
        sources: Sequence[str | os.PathLike[str] | MediaSource],
        *,
        level: MatchLevel = "standard",
    ) -> BatchGrouping:
        """Probe the files (a path that is not probed yet) and group them by fingerprint at
        ``level``: files that differ a little from a group are ``near`` members with their
        differences; a file that cannot be probed is an issue."""
        probed = await self._probe_all(sources)
        media = [found for _, found in probed if isinstance(found, MediaSource)]
        issues = [_probe_issue(found) for _, found in probed if isinstance(found, ProbeError)]
        groups = await asyncio.to_thread(group_sources, media, level)
        return BatchGrouping(groups=groups, issues=issues)

    def derive(
        self,
        job: JobSettings,
        source: MediaSource,
        sections: Collection[Section],
        *,
        base: JobTemplate | None = None,
    ) -> JobTemplate:
        """The template of ``job``'s ``sections``: the most specific track rules for the chosen
        source tracks, merged into ``base`` (the job's preset or the default when ``None``)."""
        if base is None:
            found = self._presets.find(job.preset_id) if job.preset_id else None
            base = found if found is not None else self._presets.default()
        if "naming" in sections and base.naming is None:
            # A template without naming is named with Settings → Output: a naming edit starts
            # from those options, not from the defaults (another output folder).
            base = base.model_copy(update={"naming": self._settings().output.naming})
        return derive_template(job, source, sections, base=base)

    def merge(
        self, base: JobTemplate, incoming: JobTemplate, sections: Collection[Section]
    ) -> JobTemplate:
        """``base`` with ``incoming``'s ``sections``."""
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

    async def resolve(
        self,
        template: JobTemplate | str | None,
        sources: Sequence[str | os.PathLike[str] | MediaSource],
        *,
        overrides: Mapping[str, Sequence[JsonPatchOp]] | None = None,
        group: BatchGroup | None = None,
        check: Callable[[JobSettings], None] | None = None,
    ) -> BatchResolution:
        """The resolution matrix of ``template`` (a template, a preset name or id; ``None``:
        the default preset) in every file: one :class:`~reframe.models.Resolution` per file
        in episode order (the job with its output name, the track matches, the issues), the
        columns, and the batch-level issues (name collisions). ``overrides``: per-file JSON
        patches, keyed by the file's path as a string (any spelling of the file).

        ``check(job)`` runs on each file's job as resolved (overrides applied), in a worker
        thread, before the job is named or validated: an exception from it propagates and the
        resolution stops. The server jails the paths a patch brings in with it, on the template
        this resolution uses."""
        chosen, template_issues = self._template(template)
        settings = self._settings()
        naming = chosen.naming if chosen.naming is not None else settings.output.naming
        probed = await self._probe_all(sources)
        members = group.members if group is not None else []

        def prepare() -> tuple[_Patches, dict[str, list[str]], list[tuple[str, Path, _Probed]]]:
            near = {file_key(m.path): m.differences for m in members if m.match == "near"}
            return _patches(overrides), near, _ordered(probed, members)

        patches, near, ordered = await asyncio.to_thread(prepare)
        rows: list[Resolution] = []
        for key, path, found in ordered:
            if isinstance(found, ProbeError):
                issues = [*template_issues, _probe_issue(found)]
                rows.append(Resolution(path=path, issues=issues, status="error"))
                continue
            first = list(template_issues)
            if key in near:
                first.append(_near_issue(near[key]))
            rows.append(await self._row(chosen, found, patches.get(key), naming, first, check))
        rows, batch_issues = await asyncio.to_thread(_collisions, rows)
        columns = await asyncio.to_thread(
            matrix_columns, chosen, definitions=self.definitions, languages=settings.languages
        )
        return BatchResolution(
            group=group,
            columns=columns,
            rows=rows,
            issues=[*template_issues, *(issue for _, issue in batch_issues)],
        )

    async def resolve_batch(
        self,
        template: JobTemplate | str | None,
        sources: Sequence[str | os.PathLike[str] | MediaSource],
        *,
        level: MatchLevel = "standard",
        overrides: Mapping[str, Sequence[JsonPatchOp]] | None = None,
        check: Callable[[JobSettings], None] | None = None,
    ) -> tuple[BatchGrouping, list[BatchResolution]]:
        """A whole batch (``reframe batch``): every file resolved with ``template`` (as
        :meth:`resolve`), the files grouped at ``level`` (as :meth:`group`), and one resolution
        matrix per group, in the grouping's order. ``check``: as in :meth:`resolve`.

        A file that is the planned output of another file of the batch is left out: an earlier
        run's output is not grouped, resolved or queued. The batch-level name checks run over the
        files of every group, so a job never writes a file of another group. A batch issue for a
        shared name is in the resolution of the first group concerned.
        """
        chosen, template_issues = self._template(template)
        settings = self._settings()
        naming = chosen.naming if chosen.naming is not None else settings.output.naming
        probed = await self._probe_all(sources)
        patches, keyed = await asyncio.to_thread(lambda: (_patches(overrides), _keyed(probed)))
        files = {key: path for key, path, _ in keyed}
        key_of = {path: key for key, path, _ in keyed}
        rows: dict[str, Resolution] = {}
        for key, _path, found in keyed:
            if isinstance(found, MediaSource):
                rows[key] = await self._row(
                    chosen, found, patches.get(key), naming, template_issues, check
                )
        # An earlier run's output is not encoded again: it is a planned output of another file.
        outputs = await asyncio.to_thread(_output_keys, rows)
        owners: dict[str, Path] = {}
        planned: dict[str, Path] = {}
        for key, (output, out_key) in outputs.items():
            if out_key in rows and out_key != key and out_key not in owners:
                owners[out_key] = rows[key].path
                planned[out_key] = output
        kept = [
            found for key, _, found in keyed if isinstance(found, MediaSource) and key not in owners
        ]
        groups = await asyncio.to_thread(group_sources, kept, level)
        issues = [_probe_issue(found) for _, found in probed if isinstance(found, ProbeError)]
        issues += [
            _already_encoded(files[key], owner, planned[key]) for key, owner in owners.items()
        ]
        grouped: list[list[Resolution]] = []
        for group in groups:
            members: list[Resolution] = []
            for member in group.members:
                row = rows[key_of[member.path]]
                if member.match == "near":
                    at = len(template_issues)
                    near = _near_issue(member.differences)
                    all_issues = [*row.issues[:at], near, *row.issues[at:]]
                    row = row.model_copy(
                        update={
                            "issues": all_issues,
                            "status": row_status(row.matches, all_issues),
                        }
                    )
                members.append(row)
            grouped.append(members)
        flat = [row for members in grouped for row in members]
        checked, batch_issues = await asyncio.to_thread(
            _collisions, flat, files=files, left_out=owners
        )
        columns = await asyncio.to_thread(
            matrix_columns, chosen, definitions=self.definitions, languages=settings.languages
        )
        resolutions: list[BatchResolution] = []
        start = 0
        for group, members in zip(groups, grouped, strict=True):
            end = start + len(members)
            own = [issue for n, issue in batch_issues if start <= n < end]
            resolutions.append(
                BatchResolution(
                    group=group,
                    columns=columns,
                    rows=checked[start:end],
                    issues=[*template_issues, *own],
                )
            )
            start = end
        return BatchGrouping(groups=groups, issues=issues), resolutions

    async def _row(
        self,
        template: JobTemplate,
        source: MediaSource,
        override: Sequence[JsonPatchOp] | None,
        naming: NamingOptions,
        template_issues: Sequence[ValidationIssue],
        check: Callable[[JobSettings], None] | None = None,
    ) -> Resolution:
        """One file: the pure resolution, ``check`` on its job, then its name and validation."""
        languages = self._settings().languages

        def resolved() -> tuple[Resolution, JobSettings]:
            resolution = resolve(
                template,
                source,
                override,
                definitions=self.definitions,
                languages=languages,
                container_codecs=False,  # the validation below reports the codecs
            )
            assert resolution.job is not None  # resolve always makes a job
            if check is not None:
                check(resolution.job)
            return resolution, resolution.job

        resolution, resolved_job = await asyncio.to_thread(resolved)
        job, name, notes = await self._jobs.name_job(resolved_job, source, naming=naming)
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

    async def save_preset(
        self,
        template: JobTemplate,
        name: str,
        *,
        category: str = "Custom",
        description: str = "",
    ) -> Preset | ValidationIssue:
        """Save a group template as a user preset."""
        return await self._presets.create(
            template, name, category=category, description=description
        )


def _output_keys(rows: Mapping[str, Resolution]) -> dict[str, tuple[Path, str]]:
    """Each row's output path with its :func:`~reframe.jobs.file_key` (rows by key; a row
    without an output is left out). Blocking."""
    found: dict[str, tuple[Path, str]] = {}
    for key, row in rows.items():
        output = row.job.output.path if row.job is not None else None
        if output is not None:
            found[key] = (output, file_key(output))
    return found


def _collisions(
    rows: list[Resolution],
    *,
    files: Mapping[str, Path] | None = None,
    left_out: Mapping[str, Path] | None = None,
) -> tuple[list[Resolution], list[tuple[int, ValidationIssue]]]:
    """The batch-level name checks (see the module doc): an issue on each row concerned, and
    one batch issue per shared output path, with the number of the first row concerned.
    ``files``: every file of the batch by its :func:`~reframe.jobs.file_key` (default: the
    rows' files); ``left_out``: the files left out as an earlier run's outputs (by key), each
    with the file whose planned output it is. Blocking (``stat``)."""
    added: dict[int, list[ValidationIssue]] = {}
    batch: list[tuple[int, ValidationIssue]] = []
    sources = {file_key(row.path): n for n, row in enumerate(rows)}
    every = dict(files) if files is not None else {k: rows[n].path for k, n in sources.items()}
    earlier = left_out or {}
    outputs: dict[str, list[int]] = {}
    for n, row in enumerate(rows):
        if row.job is not None and row.job.output.path is not None:
            outputs.setdefault(file_key(row.job.output.path), []).append(n)
    labels = episode_labels([row.path for row in rows], season=True)
    is_source: set[int] = set()

    def add(n: int, code: str, message: str) -> None:
        issue = ValidationIssue(
            severity=Severity.ERROR, code=code, path="output.path", message=message
        )
        added.setdefault(n, []).append(issue)

    for key, numbers in outputs.items():
        path = rows[numbers[0]].job.output.path  # type: ignore[union-attr]
        assert path is not None
        if len(numbers) > 1:
            names = ", ".join(labels[n] for n in numbers)
            batch.append(
                (
                    numbers[0],
                    ValidationIssue(
                        severity=Severity.ERROR,
                        code="batch.name_collision",
                        path="output.path",
                        message=f"{len(numbers)} files get the output name {path.name}: {names}.",
                    ),
                )
            )
            for n in numbers:
                others = ", ".join(labels[m] for m in numbers if m != n)
                add(
                    n,
                    "batch.name_collision",
                    f"{path.name} is also the output name of {others} in this batch. Use a "
                    "naming template with the episode ({episode_code} or {episode}) or another "
                    "name for this file.",
                )
        if key not in every:
            continue
        owner = sources.get(key)
        for n in numbers:
            if n == owner:
                continue  # output.same_as_source says it
            is_source.add(n)
            if owner is not None:
                message = (
                    f"The output {path.name} is the source file of {labels[owner]} in this batch."
                )
            elif key in earlier:
                message = (
                    f"The output {path.name} is a file of this batch, left out as already "
                    "encoded: a file of the batch is never overwritten. Remove it (or move it out "
                    f"of the folder) to encode {labels[n]} again."
                )
            else:
                message = (
                    f"The output {path.name} is a file of this batch: a file of the batch is "
                    "never overwritten."
                )
            add(n, "batch.output_is_source", message)
    for n, row in enumerate(rows):
        if row.job is None or row.job.output.path is None or n in is_source:
            continue
        if any(issue.code == "output.renamed" for issue in row.issues):
            add(
                n,
                "batch.output_exists",
                f"{row.job.output.path.name} already exists. In a batch an existing output is an "
                "error: remove it, or set the collision setting to overwrite.",
            )
    if not added:
        return rows, batch
    fixed = list(rows)
    for n, issues in added.items():
        row = fixed[n]
        # A file of the batch is not replaced, so the overwrite warning would say the opposite
        # of the error.
        kept = [i for i in row.issues if n not in is_source or i.code != "output.overwrite"]
        all_issues = [*kept, *issues]
        fixed[n] = row.model_copy(
            update={"issues": all_issues, "status": row_status(row.matches, all_issues)}
        )
    return fixed, batch
