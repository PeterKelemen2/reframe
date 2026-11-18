"""``reframe encode`` on the real queue and FFmpeg: foreign waiting jobs in the shared store
are left alone. Each test has its own config, data and cache folders; the tool paths come
from the environment (``REFRAME_FFMPEG`` / ``REFRAME_FFPROBE``, else discovery), as in CI."""

from __future__ import annotations

import asyncio
import functools
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from reframe.cli import EXIT_INTERRUPTED, EXIT_OK
from reframe.models import JobDraft, JobState, MediaSource
from reframe.service import Reframe
from reframe_testing import media
from reframe_testing.cli import invoke

pytestmark = [pytest.mark.needs_ffmpeg, pytest.mark.slow]

Media = Callable[[str], Path]
SEASON = "Show.S01.1080p.BluRay.x264-GRP"


def probe(path: Path) -> MediaSource:
    async def run() -> MediaSource:
        async with await Reframe.create() as app:
            source = await app.sources.probe(path)
        assert isinstance(source, MediaSource), source
        return source

    return asyncio.run(run())


def add_foreign_job(file: Path, output: Path | None = None) -> str:
    """A waiting job of "another front end" in the shared store."""

    async def run() -> str:
        async with await Reframe.create() as app:
            draft = await app.jobs.draft(file, output=output)
            assert isinstance(draft, JobDraft)
            job = await app.queue.add(draft.job)
            assert job.state is JobState.WAITING
            return job.id

    return asyncio.run(run())


def queue_states() -> dict[str, tuple[JobState, Path | None]]:
    async def run() -> dict[str, tuple[JobState, Path | None]]:
        async with await Reframe.create() as app:
            return {job.id: (job.state, job.settings.output.path) for job in app.queue.list()}

    return asyncio.run(run())


def test_encode_a_fixture(dirs: dict[str, Path], fixture_media: Media, tmp_path: Path) -> None:
    folder = tmp_path / "media"
    folder.mkdir()
    source = folder / "multitrack.mkv"
    shutil.copy2(fixture_media("multitrack"), source)
    original = probe(source)

    result = invoke("encode", str(source), "--preset", "H.265 MKV 1080p")
    assert result.exit_code == EXIT_OK, result.output
    out = result.stdout.splitlines()
    output = folder / "multitrack (1).mkv"  # the template name is the source itself
    assert out[1] == f"[1/1] multitrack.mkv → {output}"
    assert "[1/1] running" in out
    progress = [line for line in out if line.startswith("[1/1] ") and "% · " in line]
    assert progress, result.stdout
    assert any("ETA " in line and " fps · " in line for line in progress)
    assert any(line.startswith("[1/1] done in ") and line.endswith(str(output)) for line in out)
    assert out[-1] == "Summary: 1 done, 0 failed, 0 cancelled, 0 not queued."
    assert sorted(p.name for p in folder.iterdir()) == ["multitrack (1).mkv", "multitrack.mkv"]

    encoded = probe(output)
    assert encoded.video[0].codec == "hevc"
    assert encoded.video[0].disposition.default
    assert len(encoded.audio) == len(original.audio)
    assert {a.codec for a in encoded.audio} == {"aac"}
    assert [a.language for a in encoded.audio] == [a.language for a in original.audio]
    assert len(encoded.subtitles) == len(original.subtitles)
    assert encoded.container.duration == pytest.approx(original.container.duration, abs=0.2)


def test_encode_a_season_folder(
    dirs: dict[str, Path], fixture_media: Media, tmp_path: Path
) -> None:
    """A season folder encoded end to end, each output named by the template (the file name:
    a season pack)."""
    episodes = sorted(fixture_media("season").glob("*.mkv"))[:3]
    folder = tmp_path / "media" / SEASON
    folder.mkdir(parents=True)
    names = []
    for n, episode in enumerate(episodes, start=1):
        name = f"Show.S01E{n:02d}.Episode.{n}.1080p.BluRay.x264-GRP.mkv"
        shutil.copy2(episode, folder / name)
        names.append(name)
    # Another output: a job that would write the output of a waiting job is not queued.
    foreign = add_foreign_job(tmp_path / "media" / SEASON / names[0], tmp_path / "foreign.mkv")

    result = invoke("encode", str(folder), "--preset", "H.265 MKV 1080p")
    assert result.exit_code == EXIT_OK, result.output
    assert result.stdout.splitlines()[-1] == "Summary: 3 done, 0 failed, 0 cancelled, 0 not queued."
    expected = [f"Show.S01E{n:02d}.Episode.{n}.mkv" for n in (1, 2, 3)]
    assert sorted(p.name for p in folder.iterdir()) == sorted([*names, *expected])
    for name in expected:
        assert probe(folder / name).video[0].codec == "hevc"
    # The foreign job is still waiting: encode took only its own jobs.
    states = queue_states()
    assert states[foreign][0] is JobState.WAITING
    assert sum(1 for state, _ in states.values() if state is JobState.DONE) == 3


def long_source(path: Path, seconds: int = 60) -> Path:
    ffmpeg = media.find_ffmpeg()
    assert ffmpeg is not None
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size=1280x720:rate=25:duration={seconds}",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            str(path),
        ],
        check=True,
        timeout=120,
    )
    return path


# In the child, before ``exec``: SIGINT back to its default disposition. A C callable, so a
# coverage run has none of this module's code to trace in the forked child
# (see ``childproc.linux_preexec``).
_default_sigint = functools.partial(signal.signal, signal.SIGINT, signal.SIG_DFL)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX SIGINT; Windows: the mocked tests")
def test_ctrl_c_cancels_only_its_own_jobs(dirs: dict[str, Path], tmp_path: Path) -> None:
    folder = tmp_path / "media" / "Long.Movie.2020.720p-GRP"
    folder.mkdir(parents=True)
    source = long_source(folder / "long.mkv")
    other = tmp_path / "media" / "other.mkv"
    shutil.copy2(source, other)
    foreign = add_foreign_job(other)

    env = {**os.environ, "PYTHONUNBUFFERED": "1", "COLUMNS": "200"}
    process = subprocess.Popen(
        [sys.executable, "-m", "reframe.cli", "encode", str(source)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
        encoding="utf-8",
        # A background job (``pytest … &``) inherits SIGINT as ignored, and Python keeps an
        # inherited "ignore". The command under test gets the default, as in a terminal.
        preexec_fn=_default_sigint,
    )
    lines: list[str] = []
    try:
        assert process.stdout is not None
        deadline = time.monotonic() + 120
        for line in process.stdout:
            lines.append(line.rstrip("\n"))
            if line.startswith("[1/1] ") and "% · " in line and not line.startswith("[1/1] 0.0%"):
                break
            assert time.monotonic() < deadline, lines
        assert list(folder.glob("*.part.mkv")), lines  # the encode is writing
        process.send_signal(signal.SIGINT)
        rest, err = process.communicate(timeout=60)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    lines += rest.splitlines()
    assert process.returncode == EXIT_INTERRUPTED, (lines, err)
    assert "Interrupted: cancelling the jobs" in err
    assert "[1/1] cancelled" in lines or lines[-1].endswith("1 cancelled, 0 not queued.")
    assert lines[-1] == "Summary: 0 done, 0 failed, 1 cancelled, 0 not queued."
    assert sorted(p.name for p in folder.iterdir()) == ["long.mkv"]  # no .part, no output
    states = queue_states()
    assert states[foreign][0] is JobState.WAITING
    assert not any(p.name.endswith(".part.mkv") for p in other.parent.iterdir())
