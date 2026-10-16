"""Resolving a template in one file and in a group (04 §Concepts "Resolution", §Resolution
matrix, §Per-file overrides; 05 §C-12, M7).

:func:`resolve` gives the concrete :class:`~reframe.models.JobSettings` of one source, the
match report (one :class:`~reframe.models.TrackMatch` per track rule) and the issues. It is
the one way a job is made from a template: ``Reframe.jobs.draft`` (a single file and a
preset) goes through it too (``reframe.jobs.draft_from_preset``), so a preset and a batch
group make the same job for the same file.

The template's per-file **policies** (04 §Per-file overrides):

- **Crop** ``detect_per_file`` (default): an automatic or conservative crop has no rectangle
  in the job (each file is detected on its own; the template's rectangle, measured on another
  file, is not used); a manual crop stays. ``fixed``: the template's crop for every file (a
  detected rectangle becomes a manual crop).
- **Chapter names** ``source`` (the file's) or ``generated`` (``Chapter 1``, …).
- **Tags and output name**: templates, rendered per file by C-7 and C-16.
- **Range**: the whole file.

Naming (C-16), validation (C-8) and name collisions read the file system: they are
``Reframe.batch``'s (:mod:`reframe.batch.service`).

Pure: no I/O.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

from reframe import languages
from reframe.batch.overrides import apply_job_override, apply_template_override, split_override
from reframe.batch.rules import TrackResolution, resolve_tracks
from reframe.definitions import Definitions, load_definitions
from reframe.dimensions import compute_geometry, source_geometry
from reframe.models.batch import BatchGroup, MatrixColumn, Resolution, TrackMatch
from reframe.models.defaults import TrackDraft
from reframe.models.geometry import CropSettings, DimensionSettings
from reframe.models.issues import JsonPatchOp, Severity, ValidationIssue
from reframe.models.job import (
    ChapterSettings,
    JobSettings,
    OutputSettings,
    TrackMetadata,
)
from reframe.models.media import MediaSource, VideoStream
from reframe.models.preset import Preset
from reframe.models.settings import LanguageSettings
from reframe.models.template import JobTemplate

__all__ = [
    "NAME_COLUMN",
    "build_job",
    "matrix_columns",
    "output_size",
    "resolve",
    "resolve_group",
    "row_status",
    "video_metadata",
]

#: The last column of the matrix (04 §Output naming: the naming column).
NAME_COLUMN = MatrixColumn(kind="name", label="Output name")
#: The first column: the video track.
VIDEO_COLUMN = MatrixColumn(kind="video", label="V")


def video_metadata(stream: VideoStream) -> TrackMetadata:
    """The source video track's language, title and flags, with the default flag set
    (decision 0024 item 5: what mkvmerge writes; FFmpeg-written sources often have no
    default flag on their only video stream)."""
    value = stream.language_ietf or stream.language
    language = (languages.normalize(value) or value) if value else None
    d = stream.disposition
    return TrackMetadata(
        language=language,
        name=stream.title,
        default=True,
        forced=d.forced,
        commentary=d.comment,
        hearing_impaired=d.hearing_impaired,
        visual_impaired=d.visual_impaired,
        original=d.original,
    )


def output_size(job: JobSettings, source: MediaSource) -> tuple[int, int] | None:
    """C-5's scaled size of the encoded picture (the source size for video passthrough)."""
    if not source.video:
        return None
    stream = source.video[0]
    if job.video.passthrough:
        return (stream.width, stream.height)
    src = source_geometry(stream)
    if "deinterlace" in job.filters.root:
        # Deinterlace runs before the crop: the crop is on the progressive grid, as the
        # command builder (C-7) computes it.
        src = src.model_copy(update={"interlaced": False})
    geometry = compute_geometry(src, job.dimensions)
    return (geometry.scaled_width, geometry.scaled_height)


def _dimensions(template: JobTemplate, notes: list[str]) -> DimensionSettings:
    """The template's dimensions with its crop policy applied (see the module doc)."""
    dims = template.dimensions.model_copy(deep=True)
    crop = dims.crop
    if crop.rect is None or crop.mode not in ("auto", "conservative"):
        return dims
    if template.crop_policy == "fixed":
        dims.crop = CropSettings(mode="manual", rect=crop.rect)
    else:
        dims.crop = CropSettings(mode=crop.mode)
        notes.append(
            "Crop: detected for each file (the template's crop policy); the template's crop "
            "rectangle is not used."
        )
    return dims


def build_job(
    template: JobTemplate, source: MediaSource, tracks: TrackDraft
) -> tuple[JobSettings, list[str]]:
    """The job of ``source`` with ``template`` and the resolved ``tracks`` (without the output
    path: naming is C-16's), and notes on how per-file policies were applied. A
    :class:`~reframe.models.Preset` gives the job its id and name (the *modified* marker,
    ``{preset}``)."""
    notes: list[str] = []
    video = template.video.model_copy(deep=True)
    if source.video:
        video.metadata = video_metadata(source.video[0])
    names: list[str] | None = None
    if template.chapter_name_policy == "generated" and source.chapters:
        names = [f"Chapter {i}" for i in range(1, len(source.chapters) + 1)]
        notes.append("Chapter names: generated (Chapter 1, Chapter 2, …), as the preset says.")
    preset = template if isinstance(template, Preset) else None
    job = JobSettings(
        source=source.ref.model_copy(deep=True),
        preset_id=preset.id if preset is not None else None,
        preset_name=preset.name if preset is not None else None,
        output=OutputSettings.model_validate(template.output.model_dump()),
        dimensions=_dimensions(template, notes),
        filters=template.filters.model_copy(deep=True),
        video=video,
        audio=tracks.audio,
        subtitles=tracks.subtitles,
        chapters=ChapterSettings(
            enabled=template.chapters.enabled,
            names=names,
            generate_every=template.chapters.generate_every,
        ),
        tags=template.tags.model_copy(deep=True),
    )
    return job, notes


RowStatus = Literal["ok", "warning", "error"]


def row_status(matches: Sequence[TrackMatch], issues: Sequence[ValidationIssue]) -> RowStatus:
    """✓ / ⚠ / ✗ of a row: ``error`` when a cell or an issue is an error, ``warning`` for a
    warning, else ``ok`` (info does not count)."""
    severities = {m.severity for m in matches} | {i.severity for i in issues}
    if Severity.ERROR in severities:
        return "error"
    if Severity.WARNING in severities:
        return "warning"
    return "ok"


def resolve(
    template: JobTemplate,
    source: MediaSource,
    override: Sequence[JsonPatchOp] | None = None,
    *,
    definitions: Definitions | None = None,
    languages: LanguageSettings | None = None,
    container_codecs: bool = True,
) -> Resolution:
    """``template`` applied to ``source`` with its per-file ``override`` (04 §Concepts):
    the job (no output path yet), the match report, one decision per source track and the
    issues of the track stage and of the override. ``languages``: Settings → Languages (the
    preferred languages of the defaults). ``container_codecs=False``: without the defaults
    lint's ``defaults.codec_not_in_container``, for a caller that validates the job (C-8
    reports the same codecs; :func:`~reframe.batch.rules.resolve_tracks`)."""
    resolution, _ = resolve_with_tracks(
        template,
        source,
        override,
        definitions=definitions,
        languages=languages,
        container_codecs=container_codecs,
    )
    return resolution


def resolve_with_tracks(
    template: JobTemplate,
    source: MediaSource,
    override: Sequence[JsonPatchOp] | None = None,
    *,
    definitions: Definitions | None = None,
    languages: LanguageSettings | None = None,
    container_codecs: bool = True,
) -> tuple[Resolution, TrackResolution]:
    """:func:`resolve`, with the :class:`~reframe.batch.rules.TrackResolution` (the matrix
    columns of the patched template and the track draft)."""
    defs = definitions or load_definitions()
    template_ops, job_ops, issues = split_override(override)
    patched, found = apply_template_override(template, template_ops)
    issues += found
    tracks = resolve_tracks(
        patched,
        source,
        definitions=defs,
        languages=languages,
        container_codecs=container_codecs,
    )
    job, notes = build_job(patched, source, tracks.draft)
    job, found = apply_job_override(job, job_ops)
    issues = [*tracks.draft.issues, *issues, *found]
    resolution = Resolution(
        path=source.ref.path,
        job=job,
        matches=tracks.matches,
        issues=issues,
        status=row_status(tracks.matches, issues),
        override=list(override or []),
        decisions=tracks.draft.decisions,
        subtitle_decisions=tracks.draft.subtitle_decisions,
        notes=notes,
    )
    return resolution, tracks


def matrix_columns(
    template: JobTemplate,
    *,
    definitions: Definitions | None = None,
    languages: LanguageSettings | None = None,
    source: MediaSource | None = None,
) -> list[MatrixColumn]:
    """The columns of the resolution matrix (04 §Resolution matrix): ``V``, one per audio
    rule, one per subtitle rule (explicit, or compiled from the defaults), ``Output name``.
    They depend on the template and the preferred languages only; ``source`` is any file to
    resolve them on (none: an empty source)."""
    probe = source or MediaSource.model_validate({"ref": {"path": "columns"}})
    tracks = resolve_tracks(template, probe, definitions=definitions, languages=languages)
    return [VIDEO_COLUMN, *tracks.columns, NAME_COLUMN]


def resolve_group(
    group: BatchGroup,
    template: JobTemplate,
    sources: Mapping[Path, MediaSource] | Sequence[MediaSource],
    overrides: Mapping[str, Sequence[JsonPatchOp]] | None = None,
    *,
    definitions: Definitions | None = None,
    languages: LanguageSettings | None = None,
) -> list[Resolution]:
    """:func:`resolve` for every member of ``group``, in the group's (episode) order.
    ``sources``: the probed members (04's ``resolve_group`` has none; the pure engine needs
    them, decision 0040). ``overrides``: per-file JSON patches keyed by the file's path as a
    string. A member without a source is an error row."""
    by_path = (
        dict(sources)
        if isinstance(sources, Mapping)
        else {source.ref.path: source for source in sources}
    )
    patches = {str(Path(key)): value for key, value in (overrides or {}).items()}
    defs = definitions or load_definitions()
    rows: list[Resolution] = []
    for member in group.members:
        source = by_path.get(member.path)
        if source is None:
            issue = ValidationIssue(
                severity=Severity.ERROR,
                code="source.probe_failed",
                path="source",
                message=f"{member.path.name} was not probed: it cannot be resolved.",
            )
            rows.append(Resolution(path=member.path, issues=[issue], status="error"))
            continue
        rows.append(
            resolve(
                template,
                source,
                patches.get(str(member.path)),
                definitions=defs,
                languages=languages,
            )
        )
    return rows
