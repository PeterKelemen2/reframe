"""Drafting, validating and planning one job."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from reframe.dimensions import compute_geometry, source_geometry
from reframe.models import (
    Container,
    EncodePlan,
    Geometry,
    JobDraft,
    JobSettings,
    JobTemplate,
    JsonPatchOp,
    MediaSource,
    NamingOptions,
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
async def draft(body: DraftRequest, reframe: ReframeDep, registry: SourcesDep) -> JobDraft:
    """The job of a source with a preset, named and validated."""
    source = await registry.get(reframe, body.source_id)
    return unwrap(await reframe.jobs.draft(source, body.preset_id))


@router.post("/jobs/validate")
async def validate(
    body: SingleJobRequest, reframe: ReframeDep, config: ConfigDep
) -> list[ValidationIssue]:
    """Every issue of the job. A source that cannot be probed is a ``source.probe_failed``
    issue."""
    security.jail_job(config, body.job)
    return await reframe.jobs.validate(body.job)


@router.post("/jobs/plan")
async def plan(body: SingleJobRequest, reframe: ReframeDep, config: ConfigDep) -> EncodePlan:
    """The command preview and job type. A job with errors is a 422 ``jobs.invalid`` problem
    with the issues."""
    security.jail_job(config, body.job)
    result = await reframe.jobs.plan(body.job)
    if isinstance(result, EncodePlan):
        return result
    raise ProblemError(422, "jobs.invalid", "The job has errors", issues=result)


@router.post("/jobs/geometry")
async def geometry(body: SingleJobRequest, reframe: ReframeDep, config: ConfigDep) -> JobGeometry:
    """Source size, crop, output size and pixel aspect, as the command builder computes them."""
    security.jail_job(config, body.job)
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
    body: RemuxDraftRequest, reframe: ReframeDep, registry: SourcesDep
) -> JobDraft:
    """A job that copies every track and changes only metadata."""
    source = await registry.get(reframe, body.source_id)
    result = await reframe.jobs.draft_remux(
        source, body.preset_id, edit_in_place=body.edit_in_place
    )
    return unwrap(result)


@router.post("/jobs/dry-run")
async def dry_run(
    body: SingleJobRequest, reframe: ReframeDep, config: ConfigDep
) -> list[ValidationIssue]:
    """Encode one frame with the job's video settings: what FFmpeg refuses (custom encoder
    parameters) comes back as ``error`` issues. Validate the job first."""
    security.jail_job(config, body.job)
    return await reframe.jobs.dry_run(body.job)


@router.post("/jobs/hdr-metadata")
async def hdr_metadata(
    body: SingleJobRequest, reframe: ReframeDep, config: ConfigDep
) -> list[JsonPatchOp]:
    """**Copy HDR metadata from source**: a JSON patch on the job that sets the encoder's HDR
    options. Empty when the source has none or the encoder has no such options."""
    security.jail_job(config, body.job)
    media = await job_source(reframe, body.job)
    return reframe.jobs.hdr_metadata(body.job, media)
