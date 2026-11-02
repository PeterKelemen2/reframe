"""Frames, crop detection, preview clips and the preview cache. An answer never holds a path
of the cache folder: frames and clips are reached by signed URLs."""

from __future__ import annotations

import asyncio
from typing import Self

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field, NonNegativeFloat, PositiveFloat, model_validator

from reframe.models import FrameKind, FrameSet, JobSettings, TaskInfo, TaskState
from reframe.models.text import DisplayText
from reframe.service import Reframe, ReframeClosedError
from reframe_server import security
from reframe_server.api import JsonTextResponse, TaskAccepted, accepted, api_router
from reframe_server.config import ServerConfig
from reframe_server.deps import ConfigDep, ReframeDep, SourcesDep
from reframe_server.errors import ProblemError

router = api_router("preview")

FRAME_URL = "/api/preview/frames/{key}.png"
CLIP_URL = "/api/preview/clips/{clip_id}"
CLIP_LINK_TTL = 3600.0
"""Seconds a clip URL works: a ``<video>`` asks for byte ranges again while it plays."""

SampleCount = Field(default=None, ge=1, le=60)


class FramesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    source_id: str
    count: int | None = SampleCount
    """Evenly spaced frames; ``None`` with no ``timestamps``: the ``preview.sample_frames``
    setting."""
    timestamps: list[NonNegativeFloat] | None = Field(default=None, min_length=1, max_length=60)
    """Seconds from the start of the source."""

    @model_validator(mode="after")
    def _one_of(self) -> Self:
        if self.count is not None and self.timestamps is not None:
            raise ValueError("give count or timestamps, not both")
        return self


class RenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    job: JobSettings
    timestamp: NonNegativeFloat
    """Seconds from the start of the source."""


class CropDetectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    source_id: str
    count: int | None = SampleCount
    """Sample frames; ``None``: the ``preview.sample_frames`` setting."""


class ClipRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    job: JobSettings
    start: NonNegativeFloat
    """Seconds from the start of the source."""
    seconds: PositiveFloat


class ClipFramesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    timestamps: list[NonNegativeFloat] = Field(min_length=1, max_length=60)
    """Seconds from the start of the clip: its frame at ``t`` is the source frame at
    ``start + t``."""


class FrameLink(BaseModel):
    """One PNG frame."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    key: str
    kind: FrameKind
    timestamp: float
    """Seconds from the start of the source."""
    width: int
    height: int
    cached: bool
    """It came from the cache (no FFmpeg run)."""
    url: str
    """A signed URL for an ``<img>``; it expires after a few minutes."""


class Frames(BaseModel):
    """The source frames, then (``render``) the output frames, each in timestamp order."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    frames: list[FrameLink]
    notes: list[DisplayText]
    """How the frames were made, and timestamps without a picture."""


class MediaLink(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    url: str
    """A signed URL for a ``<video>``; it works for an hour."""


class CacheSize(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    size: int
    """Bytes of cached frames and clips."""


class CacheCleared(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    freed: int
    """Bytes removed. Files of running tasks stay."""


@router.post("/preview/frames")
async def frames(
    body: FramesRequest,
    request: Request,
    reframe: ReframeDep,
    config: ConfigDep,
    registry: SourcesDep,
) -> Frames:
    """Source frames: waits for the frames task. A client that goes away cancels it."""
    source = await registry.get(reframe, body.source_id)
    task = reframe.sources.frames(source.ref.path, count=body.count, timestamps=body.timestamps)
    return _links(config, await _wait(request, reframe, task))


@router.post("/preview/render")
async def render(
    body: RenderRequest, request: Request, reframe: ReframeDep, config: ConfigDep
) -> Frames:
    """The source and the output frame of ``job`` (crop, scale, filters) at ``timestamp``:
    waits for the frames task. A client that goes away cancels it."""
    security.jail_job(config, body.job)
    task = reframe.sources.frames(body.job.source.path, timestamps=[body.timestamp], job=body.job)
    return _links(config, await _wait(request, reframe, task))


@router.post("/preview/cropdetect", status_code=202, response_model=TaskAccepted)
async def cropdetect(
    body: CropDetectRequest, reframe: ReframeDep, registry: SourcesDep
) -> JsonTextResponse:
    """Crop detection on the sample frames: a task whose result is a ``CropDetection``."""
    source = await registry.get(reframe, body.source_id)
    return accepted(reframe.sources.cropdetect(source.ref.path, count=body.count))


@router.post("/preview/clip", status_code=202, response_model=TaskAccepted)
async def clip(body: ClipRequest, reframe: ReframeDep, config: ConfigDep) -> JsonTextResponse:
    """Encode ``seconds`` from ``start`` with the job's settings: a task whose result is a
    ``PreviewClip``. ``GET /api/preview/clips/{id}/link`` then gives its URL."""
    security.jail_job(config, body.job)
    return accepted(reframe.jobs.preview_clip(body.job, start=body.start, seconds=body.seconds))


@router.get("/preview/clips/{clip_id}/link")
async def clip_link(clip_id: str, reframe: ReframeDep, config: ConfigDep) -> MediaLink:
    """A signed URL of a cached clip, for a ``<video>``."""
    if await reframe.jobs.preview_clip_path(clip_id) is None:
        raise ProblemError(404, "preview.unknown_clip", "The clip is not in the cache")
    url = CLIP_URL.format(clip_id=clip_id)
    return MediaLink(url=security.sign_media_url(config, url, ttl=CLIP_LINK_TTL))


@router.post("/preview/clips/{clip_id}/frames")
async def clip_frames(
    clip_id: str, body: ClipFramesRequest, request: Request, reframe: ReframeDep, config: ConfigDep
) -> Frames:
    """Frames decoded from a cached clip, for the encoded frame compare when a ``<video>``
    cannot play it: waits for the frames task. A client that goes away cancels it."""
    path = await reframe.jobs.preview_clip_path(clip_id)
    if path is None:
        raise ProblemError(404, "preview.unknown_clip", "The clip is not in the cache")
    task = reframe.sources.frames(path, timestamps=body.timestamps)
    return _links(config, await _wait(request, reframe, task))


@router.get("/preview/cache")
async def cache_size(reframe: ReframeDep) -> CacheSize:
    return CacheSize(size=await reframe.sources.preview_cache_size())


@router.delete("/preview/cache")
async def clear_cache(reframe: ReframeDep) -> CacheCleared:
    """Remove every cached frame and clip."""
    return CacheCleared(freed=await reframe.sources.clear_preview_cache())


async def _wait(request: Request, reframe: Reframe, task: TaskInfo) -> FrameSet:
    """The task's frames once it is done; cancels it when the client goes away first or this
    request is cancelled."""
    finished = asyncio.ensure_future(reframe.tasks.wait(task.id))
    gone = asyncio.ensure_future(_disconnect(request))
    try:
        done, _ = await asyncio.wait({finished, gone}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        gone.cancel()
        if not finished.done():
            finished.cancel()
            reframe.tasks.cancel(task.id, "the client went away")
    if finished not in done:
        raise ProblemError(409, "preview.cancelled", "The client went away")
    info = finished.result()
    if info.state is TaskState.DONE:
        result: FrameSet = reframe.tasks.value(task.id)
        return result
    if info.state is TaskState.FAILED:
        raise ProblemError(422, "preview.failed", info.error or "The frames cannot be made")
    if reframe.closed:
        raise ReframeClosedError
    raise ProblemError(409, "preview.cancelled", "The frames task was cancelled")


async def _disconnect(request: Request) -> None:
    # The body has been read: the next message is the client going away.
    await request.receive()


def _links(config: ServerConfig, found: FrameSet) -> Frames:
    return Frames(
        frames=[
            FrameLink(
                key=frame.key,
                kind=frame.kind,
                timestamp=frame.timestamp,
                width=frame.width,
                height=frame.height,
                cached=frame.cached,
                url=security.sign_media_url(config, FRAME_URL.format(key=frame.key)),
            )
            for frame in found.frames
        ],
        notes=found.notes,
    )
