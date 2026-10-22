"""Probing files and folders, the probed sources, and the scans of a source."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import Response
from pydantic import BaseModel, ConfigDict, Field

from reframe.models import MediaSource
from reframe.probe import ProbeError, ProbeErrorKind
from reframe.tasks import TaskContext
from reframe_server import security
from reframe_server.api import JsonTextResponse, TaskAccepted, accepted, api_router
from reframe_server.deps import ConfigDep, ReframeDep, SourcesDep
from reframe_server.errors import ProblemError

router = api_router("sources")

PROBES_AT_ONCE = 4


class ProbeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    paths: list[str] = Field(min_length=1)
    """Files and folders. A folder gives its media files (hidden files and partial outputs
    left out)."""
    recursive: bool = False
    """Also the media files in the folders' subfolders."""


class ProbedSource(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    id: str
    """``GET /api/sources/{id}`` gives the source."""
    path: Path


class ProbeFailure(BaseModel):
    """A path that gave no source."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    path: Path
    code: str
    """``probe.<kind>`` (``probe.not_found``, ``probe.failed``, …) or ``sources.no_media``
    (a folder without media files)."""
    message: str
    detail: str | None = None


class ProbeSummary(BaseModel):
    """The result of the task of ``POST /api/sources``; sources in the order of the paths."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    sources: list[ProbedSource]
    errors: list[ProbeFailure]


class SourceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    id: str
    path: Path
    source: MediaSource | None
    """``None``: the file changed or is gone since it was probed; probe it again."""


class SubtitleScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    stream_indexes: list[int] | None = None
    """``None``: every subtitle track."""


class LoudnessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    start: float | None = Field(default=None, ge=0)
    """Seconds from the start of the source. ``None`` with ``duration`` ``None``: the whole
    track."""
    duration: float | None = Field(default=None, gt=0)


@router.post("/sources", status_code=202, response_model=TaskAccepted, name="probe")
async def probe(
    body: ProbeRequest, reframe: ReframeDep, config: ConfigDep, registry: SourcesDep
) -> JsonTextResponse:
    """Probe files and folders as a task whose result is a :class:`ProbeSummary`; each source
    gets an id."""
    paths = [security.jail_read(config, path) for path in body.paths]

    async def work(ctx: TaskContext) -> ProbeSummary:
        found = await reframe.jobs.media_files(paths, recursive=body.recursive)
        total = len(found.files)
        outcomes: dict[int, MediaSource | ProbeError] = {}
        gate = asyncio.Semaphore(PROBES_AT_ONCE)
        done = 0

        async def one(position: int, file: Path) -> None:
            nonlocal done
            async with gate:
                outcomes[position] = await reframe.sources.probe(file)
            done += 1
            ctx.progress(done=done, total=total, message=f"{done}/{total} files")

        async with asyncio.TaskGroup() as group:
            for position, file in enumerate(found.files):
                group.create_task(one(position, file))
        errors = [
            _failure(ProbeError(path, ProbeErrorKind.NOT_FOUND, "The file does not exist."))
            for path in found.missing
        ] + [
            ProbeFailure(
                path=path, code="sources.no_media", message="The folder has no media files."
            )
            for path in found.empty
        ]
        sources: list[ProbedSource] = []
        for _, outcome in sorted(outcomes.items()):
            if isinstance(outcome, MediaSource):
                path = outcome.ref.path
                sources.append(ProbedSource(id=registry.add(path), path=path))
            else:
                errors.append(_failure(outcome))
        return ProbeSummary(sources=sources, errors=errors)

    count = len(paths)
    message = f"Probing {paths[0].name}" if count == 1 else f"Probing {count} paths"
    return accepted(reframe.tasks.start("probe_sources", work, message=message))


def _failure(error: ProbeError) -> ProbeFailure:
    return ProbeFailure(
        path=error.path,
        code=f"probe.{error.kind.value}",
        message=error.message,
        detail=error.detail,
    )


@router.get("/sources", name="list")
async def list_sources(reframe: ReframeDep, registry: SourcesDep) -> list[SourceEntry]:
    """The sources probed since the server started, in the order they were probed."""
    return [
        SourceEntry(id=sid, path=path, source=await reframe.sources.get(path))
        for sid, path in registry.items()
    ]


@router.get("/sources/{source_id}", name="get")
async def get_source(source_id: str, reframe: ReframeDep, registry: SourcesDep) -> MediaSource:
    return await registry.get(reframe, source_id)


@router.delete("/sources/{source_id}", status_code=204, name="remove")
async def remove_source(source_id: str, registry: SourcesDep) -> Response:
    """Forget the source id (the probe cache keeps the file's probe)."""
    if not registry.remove(source_id):
        raise ProblemError(404, "source.unknown", f"No source {source_id}")
    return Response(status_code=204)


@router.post(
    "/sources/{source_id}/streams/{index}/bitrate-scan",
    status_code=202,
    response_model=TaskAccepted,
)
async def bitrate_scan(
    source_id: str, index: int, reframe: ReframeDep, registry: SourcesDep
) -> JsonTextResponse:
    """Measure the stream's bit rate from its packet sizes: a task whose result is a
    ``BitrateScan``; the source then holds the measured value."""
    source = await registry.get(reframe, source_id)
    return accepted(reframe.sources.bitrate_scan(source.ref.path, index))


@router.post("/sources/{source_id}/subtitle-scan", status_code=202, response_model=TaskAccepted)
async def subtitle_scan(
    source_id: str,
    reframe: ReframeDep,
    registry: SourcesDep,
    body: SubtitleScanRequest | None = None,
) -> JsonTextResponse:
    """Count the subtitle events and forced events: a task whose result is a
    ``SubtitleScan``; the source then holds the counts."""
    source = await registry.get(reframe, source_id)
    indexes = body.stream_indexes if body is not None else None
    return accepted(reframe.sources.subtitle_scan(source.ref.path, indexes))


@router.post(
    "/sources/{source_id}/streams/{index}/loudness", status_code=202, response_model=TaskAccepted
)
async def loudness_scan(
    source_id: str,
    index: int,
    reframe: ReframeDep,
    registry: SourcesDep,
    body: LoudnessRequest | None = None,
) -> JsonTextResponse:
    """EBU R128 loudness of an audio track: a task whose result is a
    ``LoudnessMeasurement``."""
    source = await registry.get(reframe, source_id)
    window = body or LoudnessRequest()
    return accepted(
        reframe.sources.loudness_scan(
            source.ref.path, index, start=window.start, duration=window.duration
        )
    )
