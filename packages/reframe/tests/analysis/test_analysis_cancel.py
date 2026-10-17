"""C-10 "Done when": "cancelling a scan stops its FFmpeg process within 1 s", for the bitrate
scan, the subtitle scan (both of its process kinds) and the loudness measure, with the real
ffmpeg / ffprobe on a 2-hour file. The file is made in a few seconds by looping a 4 s file
with ``-stream_loop`` and stream copy; its subtitle tracks have an event every 25 ms, so the
subtitle passes (which only read packets) still run for more than a second on a fast machine.
Uncancelled on the reference machine (n9.0.2, load average about 7): bitrate scan 2.3 s,
subtitle packet count 3.4 s, PGS copy and read 3.0 s; cancelled, every process was gone 6 to
25 ms after ``TaskManager.cancel`` (``testdata/README.md`` "Analysis scans").
"""

from __future__ import annotations

import asyncio
import subprocess
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import psutil
import pytest

from reframe.models import MediaSource, TaskInfo, TaskState
from reframe.service import Reframe
from reframe_testing import media, pgs

pytestmark = [pytest.mark.anyio, pytest.mark.needs_ffmpeg, pytest.mark.slow]

#: The C-10 limit, from the cancel to the process being gone.
LIMIT = 1.0
#: Loops of the 4 s file: 2 hours, 225 000 audio packets, 288 000 SRT and 576 000 PGS packets.
LOOPS = 1800
#: Milliseconds between two subtitle events.
EVENT_STEP = 25


@pytest.fixture(scope="module")
def long_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("long")
    starts = range(0, 4000, EVENT_STEP)
    cues = [(t / 1000, (t + EVENT_STEP // 2) / 1000, "x") for t in starts]
    (folder / "a.srt").write_text(media.srt(cues), encoding="utf-8")
    events = [pgs.Event(t, t + EVENT_STEP // 2, 20, forced=t % 1000 == 0) for t in starts]
    (folder / "a.sup").write_bytes(pgs.sup(events, bar_height=4))
    ffmpeg = media.find_ffmpeg()
    assert ffmpeg
    common = [ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-y"]
    subprocess.run(
        [*common, "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=4",
         "-i", "a.srt", "-i", "a.sup", "-map", "0:a", "-map", "1:s", "-map", "2:s",
         "-c:a", "ac3", "-b:a", "32k", "-ac", "1", "-c:s:0", "srt", "-c:s:1", "copy",
         "small.mkv"],
        cwd=folder, check=True, capture_output=True, timeout=60,
    )  # fmt: skip
    subprocess.run(
        [*common, "-stream_loop", str(LOOPS - 1), "-i", "small.mkv", "-map", "0", "-c", "copy",
         "long.mkv"],
        cwd=folder, check=True, capture_output=True, timeout=120,
    )  # fmt: skip
    return folder / "long.mkv"


@pytest.fixture
async def app(tmp_path: Path, long_file: Path) -> AsyncIterator[Reframe]:
    reframe = await Reframe.create(
        tmp_path / "config", tmp_path / "data", cache_dir=tmp_path / "cache"
    )
    try:
        probed = await reframe.sources.probe(long_file)  # the scan starts at once
        assert isinstance(probed, MediaSource)
        assert probed.container.duration == pytest.approx(4 * LOOPS, rel=0.01)
        assert [s.codec for s in probed.subtitles] == ["subrip", "hdmv_pgs_subtitle"]
        yield reframe
    finally:
        await reframe.close()


def _running(proc: psutil.Process) -> bool:
    try:
        return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


def _find(marker: str, path: Path) -> psutil.Process | None:
    for proc in psutil.Process().children(recursive=True):
        try:
            cmdline = proc.cmdline()
        except psutil.Error:
            continue
        if any(marker in arg for arg in cmdline) and str(path) in cmdline:
            return proc
    return None


async def _scan_process(marker: str, path: Path) -> psutil.Process:
    """The child process whose command line has ``marker`` and ``path`` (waits up to 20 s)."""
    for _ in range(2000):
        proc = _find(marker, path)
        if proc is not None:
            return proc
        await asyncio.sleep(0.01)
    raise AssertionError(f"no process with {marker!r} started")


async def _cancel_stops_the_process(app: Reframe, info: TaskInfo, marker: str, path: Path) -> None:
    proc = await _scan_process(marker, path)
    await asyncio.sleep(0.3)  # let it work for a moment
    assert _running(proc), "the scan finished before the cancel: make the input longer"
    assert app.tasks.get(info.id).state is TaskState.RUNNING  # type: ignore[union-attr]
    started = time.monotonic()
    assert app.tasks.cancel(info.id)
    for _ in range(500):  # up to 5 s
        if not _running(proc):
            break
        await asyncio.sleep(0.01)
    elapsed = time.monotonic() - started
    assert not _running(proc), "the process still runs 5 s after the cancel"
    assert elapsed < LIMIT, f"the process stopped {elapsed:.2f} s after the cancel"
    done = await asyncio.wait_for(app.tasks.wait(info.id), 10.0)
    assert done.state is TaskState.CANCELLED
    assert done.error is None


Start = Callable[[Reframe, Path], TaskInfo]


@pytest.mark.parametrize(
    ("start", "marker"),
    [
        (lambda app, path: app.sources.bitrate_scan(path, 0), "packet=pts_time,dts_time"),
        (lambda app, path: app.sources.subtitle_scan(path), "packet=stream_index,pts_time"),
        (lambda app, path: app.sources.loudness_scan(path, 0), "loudnorm=print_format=json"),
    ],
    ids=["bitrate", "subtitle-count", "loudness"],
)
async def test_cancel_stops_the_process_within_a_second(
    app: Reframe, long_file: Path, start: Start, marker: str
) -> None:
    await _cancel_stops_the_process(app, start(app, long_file), marker, long_file)


async def test_cancel_removes_the_temporary_pgs_copy(
    app: Reframe, long_file: Path, tmp_path: Path
) -> None:
    info = app.sources.subtitle_scan(long_file, [2])
    await _cancel_stops_the_process(app, info, "-f", long_file)
    assert list((tmp_path / "cache" / "scans").iterdir()) == []
