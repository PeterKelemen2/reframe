"""Drafting, validating and planning one job."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from reframe.dimensions import compute_geometry, source_geometry
from reframe.models import (
    AddOp,
    Container,
    EncodePlan,
    Fix,
    Geometry,
    JobDraft,
    JobSettings,
    JobTemplate,
    JsonPatchOp,
    MediaSource,
    NamingOptions,
    ReplaceOp,
    Severity,
    SourceGeometry,
    TrackDraft,
    ValidationIssue,
)
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


def folder_issue(
    config: ServerConfig, output: Path | None, *, job_fix: bool = True
) -> ValidationIssue | None:
    """``output.folder_required`` when the output path is outside every output root (web
    mode), with a settings fix and, with ``job_fix`` and one output root, a fix that moves the
    job's output into it. Another refusal of the write jail is raised."""
    if output is None:
        return None
    try:
        security.jail_write(config, output)
    except ProblemError as exc:
        if exc.problem.code != "path.outside_roots":
            raise
    else:
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


def without_output(job: JobSettings) -> JobSettings:
    return job.model_copy(update={"output": job.output.model_copy(update={"path": None})})


def jail_job(config: ServerConfig, job: JobSettings) -> ValidationIssue | None:
    """:func:`security.jail_job`, except that an output path outside the output roots is the
    returned :func:`folder_issue` instead of a 403."""
    issue = folder_issue(config, job.output.path)
    security.jail_job(config, without_output(job))
    return issue


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
    issue; in web mode an output outside the output roots is ``output.folder_required``."""
    issue = jail_job(config, body.job)
    if issue is None:
        return await reframe.jobs.validate(body.job)
    # The output outside the roots is not looked at; validation reports it as not set.
    issues = await reframe.jobs.validate(without_output(body.job))
    return [*(i for i in issues if i.code != "output.no_path"), issue]


@router.post("/jobs/plan")
async def plan(body: SingleJobRequest, reframe: ReframeDep, config: ConfigDep) -> EncodePlan:
    """The command preview and job type. A job with errors is a 422 ``jobs.invalid`` problem
    with the issues."""
    _refuse(jail_job(config, body.job))
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
    # Deinterlace runs before the crop, so the crop snaps to the frame's grid, not the field's.
    grid = src
    if "deinterlace" in job.filters.root:
        grid = src.model_copy(update={"interlaced": False})
    return JobGeometry(source=src, geometry=compute_geometry(grid, job.dimensions))


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
    output roots is a 422 ``jobs.invalid`` problem."""
    _refuse(jail_job(config, body.job))
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


def _invalid(issues: list[ValidationIssue]) -> ProblemError:
    return ProblemError(422, "jobs.invalid", "The job has errors", issues=issues)


def _refuse(issue: ValidationIssue | None) -> None:
    if issue is not None:
        raise _invalid([issue])


def _checked(config: ServerConfig, draft: JobDraft) -> JobDraft:
    issue = folder_issue(config, draft.job.output.path)
    if issue is None:
        return draft
    return draft.model_copy(update={"issues": [*draft.issues, issue]})
