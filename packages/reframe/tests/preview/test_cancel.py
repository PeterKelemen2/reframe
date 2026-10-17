"""Cancelling a preview task stops its FFmpeg process within 1 s (05 §C-10 "Done when"), with
a real FFmpeg on work that runs long enough: a 4K output frame through a slow denoiser, crop
detection on many 4K HDR samples, a 4K x265 preview clip."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from pathlib import Path

import psutil
import pytest

from reframe.models import FilterConfig, TaskInfo, TaskState
from reframe.preview import start_cropdetect, start_frames, start_preview_clip

from .helpers import Env, ffmpeg_children, job_for, make_env

pytestmark = [pytest.mark.anyio, pytest.mark.needs_ffmpeg, pytest.mark.slow]

Media = Callable[[str], Path]
#: 05 §C-10: "cancelling a scan stops its FFmpeg process within 1 s".
LIMIT = 1.0


def alive(proc: psutil.Process) -> bool:
    try:
        return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


#: Seconds to wait for the task's FFmpeg to start.
START = 60.0


async def running_ffmpeg(marker: str) -> psutil.Process:
    """The FFmpeg process of the task (``marker`` in its argv), once it runs."""
    deadline = time.monotonic() + START
    while time.monotonic() < deadline:
        found = ffmpeg_children(lambda argv: any(marker in arg for arg in argv))
        if found:
            return found[0]
        await asyncio.sleep(0.01)
    raise AssertionError(f"no FFmpeg with {marker!r} started")


async def cancel_and_time(env: Env, info: TaskInfo, proc: psutil.Process) -> float:
    """Cancel the task; seconds until its FFmpeg process is gone."""
    started = time.perf_counter()
    assert env.tasks.cancel(info.id)
    while alive(proc):
        if time.perf_counter() - started > 10 * LIMIT:
            break
        await asyncio.sleep(0.005)
    return time.perf_counter() - started


async def test_cancel_frames(tmp_path: Path, fixture_media: Media) -> None:
    src = fixture_media("hdr10-4k")
    env = make_env(tmp_path / "cache")
    job = job_for(src)
    job.filters.root["denoise"] = FilterConfig(
        preset="custom", custom="s=10:p=15:r=31", implementation="nlmeans"
    )
    info = start_frames(env.ctx, src, count=None, timestamps=[2.5], job=job)
    try:
        proc = await running_ffmpeg("nlmeans")
        await asyncio.sleep(0.3)  # well into the frame
        assert alive(proc)
        elapsed = await cancel_and_time(env, info, proc)
        done = await env.tasks.wait(info.id)
    finally:
        await env.tasks.close()
    print(f"\nframes: FFmpeg gone {elapsed * 1000:.0f} ms after the cancel")
    assert elapsed < LIMIT
    assert done.state is TaskState.CANCELLED
    frames = tmp_path / "cache" / "frames"
    assert [p.name for p in frames.iterdir() if p.name.startswith(".tmp-")] == []


async def test_cancel_crop_detection(tmp_path: Path, fixture_media: Media) -> None:
    src = fixture_media("hdr10-4k")
    env = make_env(tmp_path / "cache")
    info = start_cropdetect(env.ctx, src, count=60)
    try:
        proc = await running_ffmpeg("cropdetect")
        elapsed = await cancel_and_time(env, info, proc)
        done = await env.tasks.wait(info.id)
        await asyncio.sleep(0.5)
        later = ffmpeg_children(lambda argv: any("cropdetect" in arg for arg in argv))
    finally:
        await env.tasks.close()
    print(f"\ncropdetect: FFmpeg gone {elapsed * 1000:.0f} ms after the cancel")
    assert elapsed < LIMIT
    assert done.state is TaskState.CANCELLED
    assert [p for p in later if alive(p)] == []  # no next sample was started


async def test_cancel_a_preview_clip(tmp_path: Path, fixture_media: Media) -> None:
    src = fixture_media("hdr10-4k")
    env = make_env(tmp_path / "cache")
    job = job_for(src, encoder="libx265", bit_depth=10, preset="slow")
    info = start_preview_clip(env.ctx, job, start=0.0, seconds=5.0)
    try:
        proc = await running_ffmpeg("-progress")
        await asyncio.sleep(0.3)
        assert alive(proc)
        elapsed = await cancel_and_time(env, info, proc)
        done = await env.tasks.wait(info.id)
    finally:
        await env.tasks.close()
    print(f"\npreview clip: FFmpeg gone {elapsed * 1000:.0f} ms after the cancel")
    assert elapsed < LIMIT
    assert done.state is TaskState.CANCELLED
    assert list((tmp_path / "cache" / "clips").iterdir()) == []  # the partial clip is removed
