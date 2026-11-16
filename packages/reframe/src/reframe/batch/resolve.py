"""Resolving a template in one file and in a group: the job, the match report and the issues.

:func:`resolve` is the one way a job is made from a template. ``reframe.jobs.draft_from_preset``
goes through it too, so a preset and a batch group make the same job for the same file.

Pure: no I/O. Naming and the file-system checks are made elsewhere.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

from reframe import languages
from reframe.batch.overrides import apply_job_override, apply_template_override, split_override
from reframe.batch.rules import (
    CompiledRule,
    Kind,
    compile_defaults,
    resolve_tracks,
)
from reframe.definitions import Definitions, load_definitions
from reframe.dimensions import job_geometry
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
    "compiled_rules_moved",
    "matrix_columns",
    "output_size",
    "resolve",
    "resolve_group",
    "row_status",
    "video_metadata",
]

#: The last column of the matrix: the output name.
NAME_COLUMN = MatrixColumn(kind="name", label="Output name")
#: The first column: the video track.
VIDEO_COLUMN = MatrixColumn(kind="video", label="V")


def video_metadata(stream: VideoStream) -> TrackMetadata:
    """The source video track's language, title and flags. The default flag is always set,
    because FFmpeg's Matroska muxer leaves it off a single stream."""
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
    """The scaled size of the encoded picture, or the source size for video passthrough."""
    if not source.video:
        return None
    stream = source.video[0]
    if job.video.passthrough:
        return (stream.width, stream.height)
    geometry = job_geometry(stream, job)
    return (geometry.scaled_width, geometry.scaled_height)


def _dimensions(template: JobTemplate, notes: list[str]) -> DimensionSettings:
    dims = template.dimensions.model_copy(deep=True)
    crop = dims.crop
    if crop.rect is None or crop.mode not in ("auto", "conservative"):
        return dims
    # A rectangle measured on another file does not fit this one: only a fixed policy keeps it.
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
    """The job of ``source`` with ``template`` and the resolved ``tracks``, with no output path
    yet, and notes on how the per-file policies were applied. A :class:`~reframe.models.Preset`
    gives the job its id and name."""
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
    """The status of a row: ``error`` when a cell or an issue is an error, ``warning`` for a
    warning, else ``ok``. Info does not count."""
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
    """``template`` applied to ``source`` with its per-file ``override``: the job (no output
    path yet), the match report, one decision per source track and the issues. ``languages``:
    the language settings, whose preferred languages the defaults use. ``container_codecs=False``
    leaves out the ``defaults.codec_not_in_container`` lint, for a caller that reports those
    codecs itself."""
    defs = definitions or load_definitions()
    template_ops, job_ops, issues = split_override(override)
    patched, found = apply_template_override(template, template_ops)
    if patched is not template:
        moved = compiled_rules_moved(template, patched, languages=languages)
        if moved is not None:
            patched, found = template, [moved]
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
    return Resolution(
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


def _part(rule: CompiledRule) -> tuple[str, int | None]:
    return rule.group, rule.slot


def _shown(rules: Sequence[CompiledRule]) -> str:
    return ", ".join(rule.label(n).removesuffix(" (defaults)") for n, rule in enumerate(rules))


def compiled_rules_moved(
    template: JobTemplate, patched: JobTemplate, *, languages: LanguageSettings | None = None
) -> ValidationIssue | None:
    """``batch.override_invalid`` when an override changes the rules that a kind's defaults
    compile to. The matrix columns are the template's compiled rules and a cell is keyed by its
    rule's number, so a file whose defaults compile to other rules would show its cells under
    other rules' columns. The list keeps its structure when each rule stands for the same part
    of the selection, so a change of the codec rules, or of a listed language in its place, is
    fine. A kind with explicit rules is not checked: its defaults are not used, and an override
    cannot change an explicit list's structure (see
    :func:`~reframe.batch.overrides.structural_op`). ``languages``: the settings; an empty
    language list compiles to the preferred languages."""
    kinds: tuple[tuple[Kind, bool, Sequence[str]], ...] = (
        ("audio", bool(template.audio_rules), languages.preferred_audio if languages else ()),
        (
            "subtitle",
            bool(template.subtitle_rules),
            languages.preferred_subtitle if languages else (),
        ),
    )
    for kind, explicit, preferred in kinds:
        if explicit:
            continue
        before = compile_defaults(template, kind, preferred=preferred)
        after = compile_defaults(patched, kind, preferred=preferred)
        if [_part(rule) for rule in before] == [_part(rule) for rule in after]:
            continue
        return ValidationIssue(
            severity=Severity.ERROR,
            code="batch.override_invalid",
            path=f"{kind}_defaults.selection",
            message=(
                f"The override changes the rules that the {kind} defaults make "
                f"({_shown(before)} → {_shown(after)}): a file keeps the template's rules (the "
                "matrix columns), so the override's template part is not applied. Change the "
                "selection in the template, or change a codec rule or a listed language in its "
                "place."
            ),
        )
    return None


def matrix_columns(
    template: JobTemplate,
    *,
    definitions: Definitions | None = None,
    languages: LanguageSettings | None = None,
    source: MediaSource | None = None,
) -> list[MatrixColumn]:
    """The columns of the resolution matrix: the video, one per audio and subtitle rule
    (explicit, or compiled from the defaults), then the output name. They depend on the template
    and the preferred languages only; ``source`` is any file to resolve the rules on, and an empty
    source is used without one."""
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
    """:func:`resolve` for every member of ``group``, in the group's order. ``sources``: the
    probed members, by path or as a sequence; this module does not probe. ``overrides``:
    per-file JSON patches keyed by the file's path as a string. A member without a source is an
    error row."""
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
