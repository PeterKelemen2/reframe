"""The picture methods of the facade, with the real tools."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest

from reframe.models import CropDetection, CropRect, FrameSet, PreviewClip, TaskState
from reframe.service import Reframe

from .helpers import job_for

pytestmark = [pytest.mark.anyio, pytest.mark.needs_ffmpeg]

Media = Callable[[str], Path]


@pytest.fixture
async def app(tmp_path: Path) -> AsyncIterator[Reframe]:
    app = await Reframe.create(tmp_path / "config", tmp_path / "data", cache_dir=tmp_path / "cache")
    try:
        yield app
    finally:
        await app.close()


async def test_frames_and_a_frame_by_key(
    app: Reframe, tmp_path: Path, fixture_media: Media
) -> None:
    src = fixture_media("letterbox")
    info = app.sources.frames(src, count=2)
    done = await app.tasks.wait(info.id)
    assert done.state is TaskState.DONE, done.error
    frames = app.tasks.value(info.id)
    assert isinstance(frames, FrameSet)
    assert len(frames.frames) == 2
    for frame in frames.frames:
        assert frame.path.parent == tmp_path / "cache" / "frames"
        assert app.sources.frame(frame.key) == frame.path
    assert app.sources.frame("nothing") is None
    job = job_for(src)
    job.dimensions.crop.mode = "manual"
    job.dimensions.crop.rect = CropRect(top=22, bottom=24)
    info = app.sources.frames(src, timestamps=[1.0], job=job)
    done = await app.tasks.wait(info.id)
    assert done.state is TaskState.DONE, done.error
    with_job = app.tasks.value(info.id)
    assert isinstance(with_job, FrameSet)
    assert [(f.kind, f.height) for f in with_job.frames] == [("source", 180), ("output", 134)]


async def test_crop_detection(app: Reframe, fixture_media: Media) -> None:
    info = app.sources.cropdetect(fixture_media("letterbox"))
    done = await app.tasks.wait(info.id)
    assert done.state is TaskState.DONE, done.error
    result = app.tasks.value(info.id)
    assert isinstance(result, CropDetection)
    assert (result.auto, result.auto_frames) == (CropRect(top=22, bottom=24), 5)
    assert result.conservative == CropRect()
    assert done.result == result.model_dump(mode="json")


async def test_a_preview_clip_and_its_frames(app: Reframe, fixture_media: Media) -> None:
    src = fixture_media("letterbox")
    info = app.jobs.preview_clip(job_for(src), start=1.0, seconds=1.0)
    done = await app.tasks.wait(info.id)
    assert done.state is TaskState.DONE, done.error
    clip = app.tasks.value(info.id)
    assert isinstance(clip, PreviewClip)
    assert app.jobs.preview_clip_path(clip.id) == clip.path
    assert app.jobs.preview_clip_path("0" * 32) is None
    info = app.sources.frames(clip.path, timestamps=[0.5])
    done = await app.tasks.wait(info.id)
    assert done.state is TaskState.DONE, done.error
    frames = app.tasks.value(info.id)
    assert isinstance(frames, FrameSet)
    assert len(frames.frames) == 1
