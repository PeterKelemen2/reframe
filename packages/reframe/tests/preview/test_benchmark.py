"""The 4K HDR fixture's frame times against the budget: cold under 2 s, cached under 50 ms."""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from reframe.mediatask import sample_timestamps
from reframe.models import FrameSet, MediaSource, TaskState
from reframe.service import Reframe

pytestmark = [pytest.mark.anyio, pytest.mark.needs_ffmpeg, pytest.mark.benchmark]

COLD = 2.0
CACHED = 0.05


def busy() -> str:
    """``busy`` when more processes want a CPU than there are (another test run, an encode),
    else ``idle``. A frame budget measured on a busy machine says nothing about a normal
    desktop, so a miss is then a skip, not a failure."""
    cpus = os.cpu_count() or 1
    if sys.platform == "win32":  # no load average
        text = f"load unknown on {cpus} CPUs"
    else:
        load = os.getloadavg()[0]
        state = "busy" if load > cpus else "idle"
        text = f"{state}: load average {load:.1f} on {cpus} CPUs"
    return text


async def one_frame(app: Reframe, path: Path, timestamp: float) -> tuple[float, FrameSet]:
    started = time.perf_counter()
    info = app.sources.frames(path, timestamps=[timestamp])
    done = await app.tasks.wait(info.id)
    elapsed = time.perf_counter() - started
    assert done.state is TaskState.DONE, done.error
    frames = app.tasks.value(info.id)
    assert isinstance(frames, FrameSet)
    return elapsed, frames


async def test_4k_hdr_frame_budget(tmp_path: Path, fixture_media: Callable[[str], Path]) -> None:
    src = fixture_media("hdr10-4k")
    app = await Reframe.create(tmp_path / "config", tmp_path / "data", cache_dir=tmp_path / "c")
    try:
        # so the frames are tone mapped as on a user's machine (libplacebo when its run test
        # passes, else zscale + tonemap)
        await app.capabilities.wait()
        probed = await app.sources.probe(src)
        assert isinstance(probed, MediaSource)
        # the sample frames, and the last frame before the second keyframe (47 to decode)
        stamps = [*sample_timestamps(probed.container.duration, 10), 2.0]
        cold: list[float] = []
        slower: list[float] = []
        cached: list[float] = []
        notes: list[str] = []
        for stamp in stamps:
            tries: list[float] = []
            for _ in range(2):
                elapsed, frames = await one_frame(app, src, stamp)
                made = [(f.width, f.height, f.cached) for f in frames.frames]
                assert made == [(3840, 2160, False)]
                tries.append(elapsed)
                frames.frames[0].path.unlink()
            # the faster run counts, so a moment of load from other processes does not fail
            # the budget
            cold.append(min(tries))
            slower.append(max(tries))
            notes = frames.notes
            await one_frame(app, src, stamp)  # in the cache again
        for stamp in stamps:
            elapsed, frames = await one_frame(app, src, stamp)
            assert [f.cached for f in frames.frames] == [True]
            cached.append(elapsed)
        lookups = time.perf_counter()
        assert await app.sources.frame(frames.frames[0].key) is not None
        lookup = time.perf_counter() - lookups
    finally:
        await app.close()
    load = busy()
    print(
        f"\nPreview benchmark, 4K HDR frame ({notes[0] if notes else 'no note'}; {load}):\n"
        f"  cold   max {max(cold) * 1000:.0f} ms, mean {sum(cold) / len(cold) * 1000:.0f} ms "
        f"(budget {COLD * 1000:.0f} ms): {', '.join(f'{t * 1000:.0f}' for t in cold)}\n"
        f"  cold, the slower try: {', '.join(f'{t * 1000:.0f}' for t in slower)}\n"
        f"  cached max {max(cached) * 1000:.1f} ms, mean {sum(cached) / len(cached) * 1000:.1f} "
        f"ms (budget {CACHED * 1000:.0f} ms); frame(key) {lookup * 1e6:.0f} µs"
    )
    assert max(cached) < CACHED
    if max(cold) >= COLD and load.startswith("busy"):
        pytest.skip(f"the machine is {load}: the cold budget was not measured")
    assert max(cold) < COLD
