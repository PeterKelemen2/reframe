"""The live preview of output naming."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from reframe.models import Container, JobSettings, NameResult, NamingOptions, OutputOptions, Preset
from reframe_server import security
from reframe_server.api import api_router
from reframe_server.deps import ConfigDep, ReframeDep, SourcesDep
from reframe_server.routers.jobs import jail_naming, sources_of

router = api_router("naming")


class NamingPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    naming: NamingOptions | None = None
    """The naming options to try; ``null``: the job's preset's, else the settings' output
    naming."""
    source_ids: list[str]
    job: JobSettings | None = None
    """Name each source as this job would be named (its own template, name source, per-file
    overrides, container and output size). Without it a source is named from its path alone:
    the media variables are empty."""
    container: Container = "mkv"
    """The container that gives the extension when there is no job."""


@router.post("/naming/preview")
async def preview(
    body: NamingPreviewRequest, reframe: ReframeDep, registry: SourcesDep, config: ConfigDep
) -> list[NameResult]:
    """Each source's output name, in the order of ``source_ids``: the name source and why, the
    parsed fields with their positions, the rendered path, and the template's issues."""
    jail_naming(config, body.naming)
    if body.job is not None:
        security.jail_job(config, body.job)
    sources = await sources_of(reframe, registry, body.source_ids)
    if body.job is not None:
        job = body.job
        return [
            (await reframe.jobs.name_job(job, source, naming=body.naming))[1] for source in sources
        ]
    # Reframe.jobs.name takes naming options and a container only as a preset's.
    preset = Preset(
        id="naming-preview",
        name="Naming preview",
        naming=body.naming,
        output=OutputOptions(container=body.container),
    )
    return [await reframe.jobs.name(source.ref.path, preset=preset) for source in sources]
