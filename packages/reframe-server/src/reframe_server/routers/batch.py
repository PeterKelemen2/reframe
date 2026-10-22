"""Batch mode: group sources, derive a template from a job, resolve a template in every file,
save a group template as a preset."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from fastapi import Response
from pydantic import BaseModel, ConfigDict, Field

from reframe.models import (
    BatchGrouping,
    BatchResolution,
    JobSettings,
    JobTemplate,
    JsonPatchOp,
    MatchLevel,
    MediaSource,
    Preset,
    TemplateSection,
)
from reframe.service import Reframe
from reframe_server import security
from reframe_server.api import api_router
from reframe_server.config import ServerConfig
from reframe_server.deps import ConfigDep, ReframeDep, SourcesDep
from reframe_server.errors import ProblemError
from reframe_server.routers.jobs import jail_template, sources_of
from reframe_server.routers.presets import created
from reframe_server.sources import SourceRegistry

router = api_router("batch")

type Overrides = dict[str, list[JsonPatchOp]]


class BatchGroupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    source_ids: list[str]
    level: MatchLevel = "standard"


class BatchDeriveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    job: JobSettings
    source_id: str
    """The job's source."""
    sections: list[TemplateSection]
    base: JobTemplate | None = None
    """The template the sections go into, such as the group's; ``null``: the job's preset, else
    the default preset."""


class BatchResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    template: JobTemplate | str | None = None
    """A template, or a preset id or name; ``null``: the default preset."""
    source_ids: list[str]
    overrides: Overrides = Field(default_factory=dict)
    """Per-file JSON patches on the job, by ``source_id``."""


class BatchRunRequest(BatchResolveRequest):
    level: MatchLevel = "standard"


class BatchRun(BaseModel):
    """A whole batch: the groups, and one resolution matrix per group in the same order."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    grouping: BatchGrouping
    resolutions: list[BatchResolution]


class BatchSavePresetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    template: JobTemplate
    name: str
    category: str = "Custom"
    description: str = ""


def _by_path(
    registry: SourceRegistry, overrides: Mapping[str, Sequence[JsonPatchOp]]
) -> dict[str, Sequence[JsonPatchOp]]:
    """The overrides keyed by file path, as the core finds them."""
    keyed: dict[str, Sequence[JsonPatchOp]] = {}
    for sid, ops in overrides.items():
        path = registry.path(sid)
        if path is None:
            raise ProblemError(404, "source.unknown", f"No source {sid}")
        keyed[str(path)] = ops
    return keyed


async def _inputs(
    reframe: Reframe, registry: SourceRegistry, config: ServerConfig, body: BatchResolveRequest
) -> tuple[list[MediaSource], dict[str, Sequence[JsonPatchOp]]]:
    jail_template(config, body.template)
    overrides = _by_path(registry, body.overrides)
    return await sources_of(reframe, registry, body.source_ids), overrides


@router.post("/batch/group")
async def group(
    body: BatchGroupRequest, reframe: ReframeDep, registry: SourcesDep
) -> BatchGrouping:
    """The sources grouped by fingerprint at ``level``; near members list their differences.
    Members are named by path, as in ``GET /api/sources``."""
    sources = await sources_of(reframe, registry, body.source_ids)
    return await reframe.batch.group(sources, level=body.level)


@router.post("/batch/derive")
async def derive(
    body: BatchDeriveRequest, reframe: ReframeDep, registry: SourcesDep, config: ConfigDep
) -> JobTemplate:
    """*Apply to group*: the template of the job's ``sections``, merged into ``base``."""
    security.jail_job(config, body.job)
    jail_template(config, body.base)
    source = await registry.get(reframe, body.source_id)
    return reframe.batch.derive(body.job, source, body.sections, base=body.base)


@router.post("/batch/resolve")
async def resolve(
    body: BatchResolveRequest, reframe: ReframeDep, registry: SourcesDep, config: ConfigDep
) -> BatchResolution:
    """The resolution matrix of the template in every source: one row per file in episode
    order (the job with its output name, the track matches, the issues), and the name
    collisions."""
    sources, overrides = await _inputs(reframe, registry, config, body)
    return await reframe.batch.resolve(body.template, sources, overrides=overrides)


@router.post("/batch/resolve-run")
async def resolve_run(
    body: BatchRunRequest, reframe: ReframeDep, registry: SourcesDep, config: ConfigDep
) -> BatchRun:
    """A whole batch: the sources grouped at ``level`` and resolved per group, with the name
    checks over every group. A source that is the planned output of another is left out."""
    sources, overrides = await _inputs(reframe, registry, config, body)
    grouping, resolutions = await reframe.batch.resolve_batch(
        body.template, sources, level=body.level, overrides=overrides
    )
    return BatchRun(grouping=grouping, resolutions=resolutions)


@router.post("/batch/save-preset", status_code=201)
async def save_preset(
    body: BatchSavePresetRequest, reframe: ReframeDep, config: ConfigDep, response: Response
) -> Preset:
    """Save a group template as a user preset."""
    jail_template(config, body.template)
    result = await reframe.batch.save_preset(
        body.template, body.name, category=body.category, description=body.description
    )
    return created(response, result)
