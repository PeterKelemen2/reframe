"""Drafting, validating and planning one job."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from reframe.chapters import chapter_export
from reframe.dimensions import job_geometry, source_geometry
from reframe.models import (
    AddOp,
    ChapterExport,
    ChapterFormat,
    Container,
    EncodePlan,
    Fix,
    Geometry,
    JobDraft,
    JobSettings,
    JobTemplate,
    JobTypeInfo,
    JsonPatchOp,
    MediaSource,
    NamingOptions,
    OutputChapters,
    RenderedTags,
    ReplaceOp,
    Severity,
    SourceGeometry,
    TrackDraft,
    ValidationIssue,
)
from reframe.naming.track_names import track_names
from reframe.probe import ProbeError
from reframe.service import Reframe
from reframe_server import security
from reframe_server.api import api_router
from reframe_server.config import ServerConfig
from reframe_server.deps import ConfigDep, ReframeDep, SourcesDep
from reframe_server.errors import ProblemError, probe_problem
from reframe_server.sources import SourceRegistry

router = api_router("jobs")

FOLDER_REQUIRED = "output.folder_required"
IN_PLACE_NOT_ALLOWED = "inplace.not_allowed"


def _outside(config: ServerConfig, path: Path) -> bool:
    """The write jail refuses ``path`` as outside the roots; another refusal is raised."""
    try:
        security.jail_write(config, path)
    except ProblemError as exc:
        if exc.problem.code != "path.outside_roots":
            raise
        return True
    return False


def folder_issue(
    config: ServerConfig, output: Path | None, *, job_fix: bool = True
) -> ValidationIssue | None:
    """``output.folder_required`` when the output path is outside every output root (web
    mode), with a settings fix and, with ``job_fix`` and one output root, a fix that moves the
    job's output into it. Another refusal of the write jail is raised."""
    if output is None or not _outside(config, output):
        return None
    fixes: list[Fix] = []
    if config.output_roots:
        root = config.output_roots[0]
        fixes.append(
            Fix(
                label=f"Save outputs in {root}",
                target="settings",
                patch=[
                    AddOp(path="/output/naming/output_folder_mode", value="fixed"),
                    AddOp(path="/output/naming/output_folder", value=str(root)),
                ],
            )
        )
        if job_fix and len(config.output_roots) == 1:
            fixes.append(
                Fix(
                    label=f"Save it in {root}",
                    patch=[ReplaceOp(path="/output/path", value=str(root / output.name))],
                )
            )
    return ValidationIssue(
        severity=Severity.ERROR,
        code=FOLDER_REQUIRED,
        path="output.path",
        message=(
            f"{output.name} would be saved outside the output folders of this server. Set a "
            "fixed output folder inside one of them in Settings → Output."
        ),
        fixes=fixes,
    )


def in_place_issue(config: ServerConfig, job: JobSettings) -> ValidationIssue | None:
    """``inplace.not_allowed`` when ``job`` edits a source that the write jail refuses (web
    mode: a media root outside the output roots), with a fix that writes a new file into the
    first output root. The naming options cannot help: an in-place edit writes its source."""
    if not job.output.edit_in_place or not _outside(config, job.source.path):
        return None
    source = job.source.path
    fixes: list[Fix] = []
    if config.output_roots:
        root = config.output_roots[0]
        fixes.append(
            Fix(
                label=f"Write a new file in {root}",
                patch=[
                    ReplaceOp(path="/output/edit_in_place", value=False),
                    ReplaceOp(path="/output/path", value=str(root / source.name)),
                ],
            )
        )
    return ValidationIssue(
        severity=Severity.ERROR,
        code=IN_PLACE_NOT_ALLOWED,
        path="output.edit_in_place",
        message=(
            f"{source.name} is in a folder that this server may only read, so it cannot be "
            "edited in place. Write a new file into an output folder instead."
        ),
        fixes=fixes,
    )


def job_issue(config: ServerConfig, job: JobSettings) -> ValidationIssue | None:
    """What keeps this server from writing the job's output, as an issue; an in-place edit
    writes its source, so its output path does not count."""
    return in_place_issue(config, job) or folder_issue(config, job.output.path)


def jail_job(config: ServerConfig, job: JobSettings) -> tuple[ValidationIssue | None, JobSettings]:
    """:func:`security.jail_job`, except that an output the server may not write is the
    returned :func:`job_issue` instead of a 403. Also returns the job the facade may look at:
    without the refused output, and not in place when the in-place edit is refused."""
    issue = job_issue(config, job)
    seen = job
    if issue is not None:
        output: dict[str, object] = {"path": None}
        if issue.code == IN_PLACE_NOT_ALLOWED:
            output["edit_in_place"] = False
        seen = job.model_copy(update={"output": job.output.model_copy(update=output)})
    security.jail_job(config, seen)
    return issue, seen


def jail_naming(config: ServerConfig, naming: NamingOptions | None) -> None:
    """The naming options' output folder must pass the write jail."""
    if naming is not None and naming.output_folder is not None:
        security.jail_write(config, naming.output_folder)


def jail_template(config: ServerConfig, template: JobTemplate | str | None) -> None:
    """A template's only path is its naming folder; a preset name or id has none."""
    if isinstance(template, JobTemplate):
        jail_naming(config, template.naming)


async def sources_of(
    reframe: Reframe, registry: SourceRegistry, ids: Sequence[str]
) -> list[MediaSource]:
    return [await registry.get(reframe, sid) for sid in ids]


async def job_source(reframe: Reframe, job: JobSettings) -> MediaSource:
    """The job's source, from the probe cache when it is there. Call after the jail."""
    return unwrap(await reframe.sources.probe(job.source.path))


def unwrap[T](result: T | ProbeError) -> T:
    """``result``, or the problem of a file that could not be probed."""
    if isinstance(result, ProbeError):
        raise probe_problem(result)
    return result


class DraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    source_id: str
    preset_id: str | None = None
    """A preset id or name; ``null``: the default preset. An unknown one drafts with the
    default and adds a ``preset.not_found`` issue."""


class SingleJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    job: JobSettings


class ExplainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    source_id: str
    template: JobTemplate | str | None = None
    """A template, or a preset id or name; ``null``: the default preset."""
    container: Container | None = None
    """Replaces the template's container."""


class ChapterExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    job: JobSettings
    format: ChapterFormat


class RemuxDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    source_id: str
    preset_id: str | None = None
    edit_in_place: bool = True
    """Allow a ``metadata_edit`` job (an MKV whose changes are only metadata)."""


class JobGeometry(BaseModel):
    """The pipeline header: the source picture and what the job makes of it."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    source: SourceGeometry | None
    """``null`` for a source without video."""
    geometry: Geometry | None
    """``null`` when the video is copied or the source has no video."""


class TrackNames(BaseModel):
    """The name each track of a job is written with: a name template filled in."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    video: str | None
    """``null`` keeps the source title; ``""`` writes no title."""
    audio: list[str | None]
    """In the order of the job's audio tracks."""
    subtitles: list[str | None]
    """In the order of the job's subtitle tracks."""


@router.post("/jobs/draft")
async def draft(
    body: DraftRequest, reframe: ReframeDep, registry: SourcesDep, config: ConfigDep
) -> JobDraft:
    """The job of a source with a preset, named and validated."""
    source = await registry.get(reframe, body.source_id)
    return _checked(config, unwrap(await reframe.jobs.draft(source, body.preset_id)))


@router.post("/jobs/validate")
async def validate(
    body: SingleJobRequest, reframe: ReframeDep, config: ConfigDep
) -> list[ValidationIssue]:
    """Every issue of the job. A source that cannot be probed is a ``source.probe_failed``
    issue; in web mode an output outside the output roots is ``output.folder_required``, an
    in-place edit of a source in a media root ``inplace.not_allowed``."""
    issue, seen = jail_job(config, body.job)
    issues = await reframe.jobs.validate(seen)
    if issue is None:
        return issues
    # The refused output is not looked at; validation reports it as not set.
    return [*(i for i in issues if i.code != "output.no_path"), issue]


@router.post("/jobs/plan")
async def plan(body: SingleJobRequest, reframe: ReframeDep, config: ConfigDep) -> EncodePlan:
    """The command preview and job type. A job with errors is a 422 ``jobs.invalid`` problem
    with the issues."""
    _refuse(jail_job(config, body.job)[0])
    result = await reframe.jobs.plan(body.job)
    if isinstance(result, EncodePlan):
        return result
    raise _invalid(result)


@router.post("/jobs/geometry")
async def geometry(body: SingleJobRequest, reframe: ReframeDep, config: ConfigDep) -> JobGeometry:
    """Source size, crop, output size and pixel aspect, as the command builder computes them."""
    jail_job(config, body.job)
    job = body.job
    media = await job_source(reframe, job)
    if not media.video:
        return JobGeometry(source=None, geometry=None)
    src = source_geometry(media.video[0])
    if job.video.passthrough:
        return JobGeometry(source=src, geometry=None)
    return JobGeometry(source=src, geometry=job_geometry(media.video[0], job))


@router.post("/jobs/explain")
async def explain(
    body: ExplainRequest, reframe: ReframeDep, registry: SourcesDep, config: ConfigDep
) -> TrackDraft:
    """Why each source track was selected or dropped, and the rule that made each output."""
    jail_template(config, body.template)
    source = await registry.get(reframe, body.source_id)
    return unwrap(await reframe.jobs.explain(source, body.template, container=body.container))


@router.post("/jobs/draft-remux")
async def draft_remux(
    body: RemuxDraftRequest, reframe: ReframeDep, registry: SourcesDep, config: ConfigDep
) -> JobDraft:
    """A job that copies every track and changes only metadata."""
    source = await registry.get(reframe, body.source_id)
    result = await reframe.jobs.draft_remux(
        source, body.preset_id, edit_in_place=body.edit_in_place
    )
    return _checked(config, unwrap(result))


@router.post("/jobs/dry-run")
async def dry_run(
    body: SingleJobRequest, reframe: ReframeDep, config: ConfigDep
) -> list[ValidationIssue]:
    """Encode one frame with the job's video settings: what FFmpeg refuses (custom encoder
    parameters) comes back as ``error`` issues. Validate the job first. An output outside the
    output roots, or a refused in-place edit, is a 422 ``jobs.invalid`` problem."""
    _refuse(jail_job(config, body.job)[0])
    return await reframe.jobs.dry_run(body.job)


@router.post("/jobs/hdr-metadata")
async def hdr_metadata(
    body: SingleJobRequest, reframe: ReframeDep, config: ConfigDep
) -> list[JsonPatchOp]:
    """**Copy HDR metadata from source**: a JSON patch on the job that sets the encoder's HDR
    options. Empty when the source has none or the encoder has no such options."""
    jail_job(config, body.job)
    media = await job_source(reframe, body.job)
    return reframe.jobs.hdr_metadata(body.job, media)


@router.post("/jobs/type", name="type")
async def job_type(body: SingleJobRequest, reframe: ReframeDep, config: ConfigDep) -> JobTypeInfo:
    """The job type (encode, remux, metadata edit) and why, and why the job could not edit its
    source in place, also when *Edit in place* is off. An in-place edit is not refused here
    (validation reports ``inplace.*``); in web mode a source the server may not write is one
    more blocker."""
    jail_job(config, body.job)
    media = await job_source(reframe, body.job)
    write_blocker = None
    if _outside(config, body.job.source.path):
        write_blocker = f"{body.job.source.path.name} is in a folder that this server may only read"
    return reframe.jobs.job_type(body.job, media, write_blocker=write_blocker)


@router.post("/jobs/chapters", name="chapters")
async def output_chapters(
    body: SingleJobRequest, reframe: ReframeDep, config: ConfigDep
) -> OutputChapters:
    """The chapters the output gets, in output time, as the encode writes them: the range,
    renamed and generated chapters, the container and *Create chapter markers* applied."""
    jail_job(config, body.job)
    media = await job_source(reframe, body.job)
    return await asyncio.to_thread(reframe.jobs.output_chapters, body.job, media)


@router.post("/jobs/chapters/export", name="export_chapters")
async def export_chapters(
    body: ChapterExportRequest, reframe: ReframeDep, config: ConfigDep
) -> ChapterExport:
    """The output's chapters (as ``/jobs/chapters``) as the text of a chapter file. A job
    whose output gets no chapters is a 422 ``chapters.none`` problem with the reason."""
    jail_job(config, body.job)
    media = await job_source(reframe, body.job)
    chapters = await asyncio.to_thread(reframe.jobs.output_chapters, body.job, media)
    if not chapters.chapters:
        raise ProblemError(422, "chapters.none", "The output has no chapters", chapters.reason)
    named_after = body.job.output.path or body.job.source.path
    return chapter_export(chapters.chapters, body.format, named_after)


@router.post("/jobs/tags", name="tags")
async def rendered_tags(
    body: SingleJobRequest, reframe: ReframeDep, config: ConfigDep
) -> RenderedTags:
    """Each tag as it will be written (the naming variables filled in), the source's value of
    each, and the tags' template errors."""
    jail_job(config, body.job)
    media = await job_source(reframe, body.job)
    return reframe.jobs.rendered_tags(body.job, media)


@router.post("/jobs/track-names", name="track_names")
async def written_track_names(
    body: SingleJobRequest, reframe: ReframeDep, config: ConfigDep
) -> TrackNames:
    """Each track's name as it will be written: a name with a track name variable
    (``{lang_name} {channels} {codec}``) is filled in for its track."""
    jail_job(config, body.job)
    media = await job_source(reframe, body.job)
    names = track_names(body.job, media, reframe.jobs.definitions)
    return TrackNames(video=names.video, audio=names.audio, subtitles=names.subtitles)


def _invalid(issues: list[ValidationIssue]) -> ProblemError:
    return ProblemError(422, "jobs.invalid", "The job has errors", issues=issues)


def _refuse(issue: ValidationIssue | None) -> None:
    if issue is not None:
        raise _invalid([issue])


def _checked(config: ServerConfig, draft: JobDraft) -> JobDraft:
    issue = job_issue(config, draft.job)
    if issue is None:
        return draft
    return draft.model_copy(update={"issues": [*draft.issues, issue]})
