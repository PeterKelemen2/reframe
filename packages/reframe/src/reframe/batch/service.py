"""``Reframe.batch``: group files, derive templates, resolve a template in every file,
and save a group template as a preset.

The rest of :mod:`reframe.batch` is pure. This module is the one place that probes, detects
crops, names and validates, through the other services of the facade, so the pure engine never
depends on the facade.

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

from reframe.batch.derive import derive_template
from reframe.batch.grouping import episode_key, episode_labels, group_sources
from reframe.batch.resolve import matrix_columns, resolve, row_status
from reframe.jobs import file_key, probe_issue
from reframe.mediatask import MediaTaskContext, TaskFailed
from reframe.models.batch import (
    BatchGrouping,
    BatchResolution,
    MatchLevel,
    Resolution,
)
from reframe.models.batch import TemplateSection as Section
from reframe.models.geometry import CropRect, CropSettings
from reframe.models.issues import JsonPatchOp, Severity, ValidationIssue
from reframe.models.job import JobSettings
from reframe.models.media import MediaSource
from reframe.models.naming import NameResult, NamingOptions
from reframe.models.preset import Preset
from reframe.models.preview import CropDetection
from reframe.models.settings import AppSettings
from reframe.models.template import JobTemplate
from reframe.preview.crop import detect_crop
from reframe.probe import ProbeError
from reframe.tools import CancelToken

__all__ = ["PROBE_CONCURRENCY", "BatchService", "CropProgress"]

#: Files probed at the same time by :meth:`BatchService.group` and
#: :meth:`BatchService.resolve` (each probe is one ffprobe; the probe cache makes a second
#: one cheap).
PROBE_CONCURRENCY = 4
#: Crop detections kept by :class:`BatchService`, so that a group queued again does not
#: measure its files again.
CROP_CACHE_SIZE = 256

type CropProgress = Callable[[Path, int, int], None]
"""Called before a file's crop is detected: the file, its number and the number of files."""


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


class _CropTask:
    """The task of one crop detection in a batch: the batch reports per file, not per frame."""

    def __init__(self, cancel: CancelToken) -> None:
        self._cancel = cancel

    @property
    def cancel(self) -> CancelToken:
        return self._cancel

    def progress(
        self,
        percent: float | None = None,
        message: str | None = None,
        *,
        done: int | None = None,
        total: int | None = None,
    ) -> None:
        del percent, message, done, total


def _needs_crop(job: JobSettings, source: MediaSource) -> bool:
    """The job's crop is automatic or conservative without a rectangle, and it encodes video."""
    crop = job.dimensions.crop
    return (
        crop.mode in ("auto", "conservative")
        and crop.rect is None
        and not job.video.passthrough
        and bool(source.video)
    )


def _measured(row: Resolution, source: MediaSource) -> bool:
    """The crop of the row's file is detected: its job needs one and can be queued."""
    return row.status != "error" and row.job is not None and _needs_crop(row.job, source)


def _edges(rect: CropRect) -> str:
    return f"top {rect.top}, bottom {rect.bottom}, left {rect.left}, right {rect.right}"


class _CropRun:
    """Crop detection for the files of one resolution: each job with an automatic or
    conservative crop and no rectangle (the template's per-file policy) gets its file's."""

    def __init__(
        self,
        media: MediaTaskContext,
        cache: dict[str, CropDetection],
        *,
        files: int,
        cancel: CancelToken | None,
        progress: CropProgress | None,
    ) -> None:
        self._media = media
        self._cache = cache
        self._files = files
        self._cancel = cancel if cancel is not None else CancelToken()
        self._progress = progress

    def _key(self, source: MediaSource) -> str | None:
        fingerprint = source.ref.fingerprint
        if fingerprint is None:
            return None
        count = self._media.settings().preview.sample_frames
        return f"{source.ref.path}\0{fingerprint.model_dump_json()}\0{count}"

    async def apply(
        self, job: JobSettings, source: MediaSource, number: int
    ) -> tuple[list[str], list[ValidationIssue]]:
        """Fill in the crop of ``job`` (made from ``source``, file ``number`` of the run); the
        notes and the issues of the row. Raises :class:`asyncio.CancelledError` when the run is
        cancelled."""
        if not _needs_crop(job, source):
            return [], []
        mode = job.dimensions.crop.mode
        if self._progress is not None:
            self._progress(source.ref.path, number, self._files)
        key = self._key(source)
        detection = self._cache.get(key) if key is not None else None
        if detection is None:
            try:
                detection = await detect_crop(
                    _CropTask(self._cancel), self._media, source.ref.path, count=None
                )
            except TaskFailed as failure:
                if self._cancel.cancelled:  # a cancelled probe or run fails the task
                    raise asyncio.CancelledError from None
                return [], [_crop_failed(str(failure))]
            if key is not None:
                self._cache[key] = detection
                while len(self._cache) > CROP_CACHE_SIZE:
                    del self._cache[next(iter(self._cache))]
        rect = detection.auto if mode == "auto" else detection.conservative
        job.dimensions.crop = CropSettings(mode=mode, rect=rect)
        name = "automatic" if mode == "auto" else "conservative"
        return [f"Crop: detected in this file ({name}): {_edges(rect)}."], []


def _crop_failed(reason: str) -> ValidationIssue:
    return ValidationIssue(
        severity=Severity.WARNING,
        code="batch.crop_not_detected",
        path="dimensions.crop",
        message=f"The crop of this file could not be detected, so it is not cropped: {reason}",
    )


class BatchService:
    """Batch / season mode.

    :param sources: probes the files (``Reframe.sources``; probes are cached), and its
        ``media`` runs crop detection.
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
    ) -> None:
        self._sources = sources
        self._presets = presets
        self._jobs = cast(_Jobs, jobs)
        self._settings = settings
        self._crops: dict[str, CropDetection] = {}

    def _crop_run(
        self,
        detect: bool,
        files: int,
        cancel: CancelToken | None,
        progress: CropProgress | None,
    ) -> _CropRun | None:
        if not detect:
            return None
        media: MediaTaskContext | None = getattr(self._sources, "media", None)
        if media is None:
            raise RuntimeError("crop detection needs the sources' media context (the facade's)")
        return _CropRun(media, self._crops, files=files, cancel=cancel, progress=progress)

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
        issues = [probe_issue(found) for _, found in probed if isinstance(found, ProbeError)]
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
        own = job.output.naming
        sets_naming = own.template is not None or own.name_source is not None
        if "naming" in sections and base.naming is None and sets_naming:
            # A template without naming is named with Settings → Output: a naming edit starts
            # from those options, not from the defaults (another output folder). A job without
            # naming of its own leaves the template following the settings.
            base = base.model_copy(update={"naming": self._settings().output.naming})
        return derive_template(job, source, sections, base=base)

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
        check: Callable[[JobSettings], None] | None = None,
        detect_crop: bool = False,
        cancel: CancelToken | None = None,
        progress: CropProgress | None = None,
    ) -> BatchResolution:
        """The resolution matrix of ``template`` (a template, a preset name or id; ``None``:
        the default preset) in every file: one :class:`~reframe.models.Resolution` per file
        in episode order (the job with its output name, the track matches, the issues), the
        columns, and the batch-level issues (name collisions). ``overrides``: per-file JSON
        patches, keyed by the file's path as a string (any spelling of the file).

        ``check(job)`` runs on each file's job as resolved (overrides applied), in a worker
        thread, before the job is named or validated: an exception from it propagates and the
        resolution stops. The server jails the paths a patch brings in with it, on the template
        this resolution uses.

        ``detect_crop``: a job with an automatic or conservative crop and no rectangle, in a row
        without errors, gets the crop that detection finds in its file, and is named and
        validated again (for queueing; a detection is kept for the next run while the file is
        unchanged). ``progress`` is told of each file measured; cancelling ``cancel`` (or this
        task) stops the detection with :class:`asyncio.CancelledError`."""
        chosen, template_issues = self._template(template)
        settings = self._settings()
        naming = chosen.naming if chosen.naming is not None else settings.output.naming
        probed = await self._probe_all(sources)
        # The episode parser and the file keys stat the files.
        patches, ordered = await asyncio.to_thread(
            lambda: (_patches(overrides), sorted(_keyed(probed), key=lambda i: episode_key(i[1])))
        )
        rows: list[Resolution] = []
        for key, path, found in ordered:
            if isinstance(found, ProbeError):
                issues = [*template_issues, probe_issue(found)]
                rows.append(Resolution(path=path, issues=issues, status="error"))
                continue
            row, _ = await self._row(
                chosen, found, patches.get(key), naming, template_issues, check
            )
            rows.append(row)
        crops = self._crop_run(detect_crop, len(ordered), cancel, progress)
        if crops is not None:
            for index, (key, _path, found) in enumerate(ordered):
                if isinstance(found, MediaSource) and _measured(rows[index], found):
                    rows[index], _ = await self._row(
                        chosen, found, patches.get(key), naming, template_issues, check,
                        crops=crops, number=index + 1,
                    )  # fmt: skip
        rows, batch_issues = await asyncio.to_thread(_collisions, rows)
        columns = await asyncio.to_thread(matrix_columns, chosen, languages=settings.languages)
        return BatchResolution(
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
        detect_crop: bool = False,
        cancel: CancelToken | None = None,
        progress: CropProgress | None = None,
    ) -> tuple[BatchGrouping, list[BatchResolution]]:
        """A whole batch (``reframe batch``): every file resolved with ``template`` (as
        :meth:`resolve`), the files grouped at ``level`` (as :meth:`group`), and one resolution
        matrix per group, in the grouping's order. ``check``, ``detect_crop``, ``cancel`` and
        ``progress``: as in :meth:`resolve` (the files are numbered in the given order).

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
        planned_rows: dict[str, Resolution] = {}
        for key, _path, found in keyed:
            if isinstance(found, MediaSource):
                rows[key], own_path = await self._row(
                    chosen, found, patches.get(key), naming, template_issues, check
                )
                if not own_path:
                    planned_rows[key] = rows[key]
        # An earlier run's output is not encoded again: it is a planned output of another file.
        # A path that a file's override chose is no plan of the preset: it is checked below.
        outputs = await asyncio.to_thread(_output_keys, planned_rows)
        owners: dict[str, Path] = {}
        planned: dict[str, Path] = {}
        for key, (output, out_key) in outputs.items():
            if out_key in rows and out_key != key and out_key not in owners:
                owners[out_key] = rows[key].path
                planned[out_key] = output
        kept = [
            found for key, _, found in keyed if isinstance(found, MediaSource) and key not in owners
        ]
        # Measured once the left-out files are known, so that they are not measured.
        crops = self._crop_run(detect_crop, len(kept), cancel, progress)
        if crops is not None:
            measured = [
                (key, found)
                for key, _, found in keyed
                if isinstance(found, MediaSource) and key not in owners
            ]
            for number, (key, found) in enumerate(measured, start=1):
                if not _measured(rows[key], found):
                    continue
                rows[key], _ = await self._row(
                    chosen, found, patches.get(key), naming, template_issues, check,
                    crops=crops, number=number,
                )  # fmt: skip
        groups = await asyncio.to_thread(group_sources, kept, level)
        issues = [probe_issue(found) for _, found in probed if isinstance(found, ProbeError)]
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
        columns = await asyncio.to_thread(matrix_columns, chosen, languages=settings.languages)
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
        *,
        crops: _CropRun | None = None,
        number: int = 0,
    ) -> tuple[Resolution, bool]:
        """One file: the pure resolution, ``check`` on its job, its crop when ``crops`` (file
        ``number``), then its name and validation; and whether its override chose the output
        path (naming then gives only the name fields)."""
        languages = self._settings().languages

        def resolved() -> tuple[Resolution, JobSettings]:
            resolution = resolve(template, source, override, languages=languages)
            assert resolution.job is not None  # resolve always makes a job
            if check is not None:
                check(resolution.job)
            return resolution, resolution.job

        resolution, resolved_job = await asyncio.to_thread(resolved)
        crop_notes: list[str] = []
        crop_issues: list[ValidationIssue] = []
        if crops is not None:
            crop_notes, crop_issues = await crops.apply(resolved_job, source, number)
        job, name, notes = await self._jobs.name_job(resolved_job, source, naming=naming)
        # A resolved job has no output path, so one here is the override's.
        chosen = resolved_job.output.path
        if chosen is not None:
            job.output.path = chosen
            notes = []  # they are about the path that naming gave
        checks = await self._jobs.validate(job, source, naming=naming)
        issues = [*template_issues, *resolution.issues, *crop_issues, *checks]
        row = resolution.model_copy(
            update={
                "job": job,
                "naming": name,
                "issues": issues,
                "notes": [*resolution.notes, *crop_notes, *notes],
                "status": row_status(resolution.matches, issues),
            }
        )
        return row, chosen is not None

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
