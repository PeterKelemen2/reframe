"""C-11 "Done when" on real FFmpeg: the queue through the ``Reframe`` facade.

    an integration test queues 3 fixture jobs (parallel = 2) and covers pause, resume,
    cancel, a failure from a fake encoder error, and a restart with an interrupted job.
    All expected events arrive in order.

``REFRAME_FFMPEG`` points at the fake ffmpeg, whose last rule passes every call to the real
ffmpeg (``exec``); a rule per job name puts in what that job needs (a first progress block to
pause or cancel at, the fake encoder error, a hang until Reframe is closed). ffprobe is the
real one, so the runner's output check and this test re-probe real files. Also here: two-pass
loudness normalisation of a silent track (the ``-inf`` clamp) on real FFmpeg.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import psutil
import pytest

from reframe.models import Event, JobSettings, JobState, MediaSource
from reframe.probe import mediainfo
from reframe.service import Reframe
from reframe.tools import ENV_VARS
from reframe_testing import fake_tools as ft
from reframe_testing import media

from .conftest import draft, poll

pytestmark = [pytest.mark.needs_ffmpeg, pytest.mark.anyio]

ENCODER_ERROR = (
    "[vost#0:0/libx264 @ 0x5612] [enc:libx264 @ 0x5613] Error submitting video frame to the "
    "encoder\nConversion failed!\n"
)


@dataclass
class Real:
    tmp: Path
    ffmpeg: str
    ffprobe: str
    fake: ft.FakeTools
    source: Path
    published: list[Event] = field(default_factory=list)

    def scenario(self, *rules: ft.Rule) -> None:
        """``rules``, then every other call to the real ffmpeg."""
        self.fake.set_scenario(
            ft.Scenario([*rules, ft.Rule(actions=[ft.exec_program(self.ffmpeg)])])
        )

    async def create(self) -> Reframe:
        app = await Reframe.create()
        publish = app.events.publish

        def record(event: Event) -> None:
            self.published.append(event)
            publish(event)

        app.events.publish = record  # type: ignore[method-assign]
        return app

    def states(self, job_id: str) -> list[tuple[str | None, str]]:
        return [
            (None if e.previous is None else e.previous.value, e.state.value)
            for e in self.published
            if e.type == "job.state" and e.job_id == job_id
        ]

    def kinds(self, job_id: str) -> list[str]:
        kinds: list[str] = []
        for event in self.published:
            if getattr(event, "job_id", None) != job_id:
                continue
            if kinds and kinds[-1] == event.type and event.type in ("job.progress", "job.log"):
                continue
            kinds.append(event.type)
        return kinds

    async def until(self, condition: Callable[[], bool], limit: float = 60.0) -> None:
        await poll(condition, limit)

    def progressed(self, job_id: str) -> bool:
        return any(
            e.type == "job.progress" and e.job_id == job_id and e.progress.step_kind == "encode"
            for e in self.published
        )


def write_settings(config: Path, **queue: object) -> None:
    config.mkdir(parents=True, exist_ok=True)
    settings = {"encoders": {"hardware_tests": False}, "queue": {"sleep_inhibit": False, **queue}}
    (config / "settings.json").write_text(json.dumps(settings), encoding="utf-8")


@pytest.fixture
def real(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_tools: ft.FakeTools,
    fixture_media: Callable[[str], Path],
) -> Real:
    source = fixture_media("multitrack")
    ffmpeg, ffprobe = media.find_ffmpeg(), media.find_ffprobe()
    assert ffmpeg is not None
    assert ffprobe is not None
    for var in ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    for name in ("config", "data", "cache"):
        monkeypatch.setenv(f"REFRAME_{name.upper()}_DIR", str(tmp_path / name))
    monkeypatch.setenv("REFRAME_FFMPEG", str(fake_tools.ffmpeg))
    monkeypatch.setenv("REFRAME_FFPROBE", ffprobe)
    monkeypatch.setattr(mediainfo, "mediainfo_available", lambda: False)
    write_settings(tmp_path / "config", parallel_jobs=2)
    env = Real(tmp_path, ffmpeg, ffprobe, fake_tools, source)
    env.scenario()
    return env


async def probe(app: Reframe, path: Path) -> MediaSource:
    result = await app.sources.probe(path, use_cache=False)
    assert isinstance(result, MediaSource), result
    return result


def layout(source: MediaSource) -> list[tuple[str, str | None]]:
    return [
        *(("video", s.language) for s in source.video),
        *(("audio", s.language) for s in source.audio),
        *(("subtitle", s.language) for s in source.subtitles),
    ]


def job_for(app_source: MediaSource, out: Path, name: str) -> JobSettings:
    return draft(app_source, out / f"{name}.mkv")


def stopped(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() == psutil.STATUS_STOPPED
    except psutil.Error:
        return False


async def test_done_when_three_jobs_two_slots_pause_resume_cancel_failure_restart(
    real: Real,
) -> None:
    out = real.tmp / "out"
    real.scenario(
        # Alpha: a first block to pause at, then the real encode.
        ft.Rule(argv_contains=["Alpha.part.mkv"], actions=[
            ft.progress(blocks=1, media_seconds=0.2, end=False), ft.sleep(0.2),
            ft.exec_program(real.ffmpeg)]),
        # Bravo: the fake encoder error.
        ft.Rule(argv_contains=["Bravo.part.mkv"], exit_code=1, actions=[
            ft.progress(blocks=2, media_seconds=0.4, end=False), ft.stderr(ENCODER_ERROR)]),
        # Charlie and Delta: a first block, part of an output, then quiet until stopped.
        ft.Rule(argv_contains=["Charlie.part.mkv"], actions=[
            ft.progress(blocks=1, end=False), ft.write_output(100), ft.hang()]),
        ft.Rule(argv_contains=["Delta.part.mkv"], actions=[
            ft.progress(blocks=1, end=False), ft.write_output(100), ft.hang()]),
    )  # fmt: skip
    app = await real.create()
    try:
        source = await probe(app, real.source)
        alpha = await app.queue.add(job_for(source, out, "Alpha"))
        bravo = await app.queue.add(job_for(source, out, "Bravo"))
        charlie = await app.queue.add(job_for(source, out, "Charlie"))
        assert [j.state for j in app.queue.list()] == [JobState.WAITING] * 3
        app.queue.start()

        # Pause Alpha at its first block: its process tree is suspended.
        await real.until(lambda: real.progressed(alpha.id))
        await app.queue.pause(alpha.id)
        assert app.queue.get(alpha.id).state is JobState.PAUSED  # type: ignore[union-attr]
        alpha_pids = [i.pid for i in real.fake.invocations() if "Alpha.part.mkv" in i.argv]
        if sys.platform != "win32":
            await real.until(lambda: all(stopped(pid) for pid in alpha_pids))

        # Bravo fails from the fake encoder error; its slot goes to Charlie.
        await real.until(lambda: ("running", "failed") in real.states(bravo.id))
        failed = app.queue.get(bravo.id)
        assert failed is not None
        assert failed.error == (
            "The encode failed (exit code 1): Error submitting video frame to the encoder"
        )
        assert not (out / "Bravo.part.mkv").exists()

        # Cancel Charlie: its tree is killed and its .part file removed.
        await real.until(lambda: real.progressed(charlie.id))
        await real.until((out / "Charlie.part.mkv").exists)
        await app.queue.cancel(charlie.id)
        assert app.queue.get(charlie.id).state is JobState.CANCELLED  # type: ignore[union-attr]
        assert not (out / "Charlie.part.mkv").exists()

        # Alpha made no progress while paused; resume it and it finishes for real.
        paused_at = len(real.published)
        await asyncio.sleep(0.3)
        assert not [
            e
            for e in real.published[paused_at:]
            if e.type == "job.progress" and e.job_id == alpha.id
        ]
        await app.queue.resume(alpha.id)
        [done] = await app.queue.wait([alpha.id])
        assert done.state is JobState.DONE, done.error
        assert done.output_path == out / "Alpha.mkv"

        # A fourth job runs when Reframe is closed: it ends interrupted.
        delta = await app.queue.add(job_for(source, out, "Delta"))
        await real.until(lambda: real.progressed(delta.id))
    finally:
        await app.close()
    assert app.queue.get(delta.id).state is JobState.INTERRUPTED  # type: ignore[union-attr]
    assert not (out / "Delta.part.mkv").exists()
    assert real.fake.kill_leftovers() == []

    # Restart: the queue comes back; Delta is retried and encodes for real.
    real.scenario()
    again = await real.create()
    try:
        assert [(j.id, j.state) for j in again.queue.list()] == [
            (alpha.id, JobState.DONE),
            (bravo.id, JobState.FAILED),
            (charlie.id, JobState.CANCELLED),
            (delta.id, JobState.INTERRUPTED),
        ]
        await again.queue.retry(delta.id)
        again.queue.start()
        [redone] = await again.queue.wait([delta.id])
        assert redone.state is JobState.DONE, redone.error
        source_layout = layout(source)
        for path in (out / "Alpha.mkv", out / "Delta.mkv"):
            assert layout(await probe(again, path)) == source_layout
        assert sorted(p.name for p in out.iterdir()) == ["Alpha.mkv", "Delta.mkv"]
    finally:
        await again.close()

    # All expected events, in order.
    assert real.states(alpha.id) == [
        (None, "waiting"), ("waiting", "running"), ("running", "paused"),
        ("paused", "running"), ("running", "done"),
    ]  # fmt: skip
    assert real.states(bravo.id) == [
        (None, "waiting"),
        ("waiting", "running"),
        ("running", "failed"),
    ]
    assert real.states(charlie.id) == [
        (None, "waiting"), ("waiting", "running"), ("running", "cancelled"),
    ]  # fmt: skip
    assert real.states(delta.id) == [
        (None, "waiting"), ("waiting", "running"), ("running", "interrupted"),
        ("interrupted", "waiting"), ("waiting", "running"), ("running", "done"),
    ]  # fmt: skip
    for job_id in (alpha.id, bravo.id, charlie.id, delta.id):
        kinds = real.kinds(job_id)
        assert kinds[:4] == ["job.state", "job.state", "job.progress", "job.log"] or kinds[:3] == [
            "job.state", "job.state", "job.progress"]  # fmt: skip
        assert kinds[-1] == "job.state"
        assert kinds[-2] == "job.log"  # the last log batch before the end state
    starts = [
        e.job_id
        for e in real.published
        if e.type == "job.state" and e.state is JobState.RUNNING and e.previous is JobState.WAITING
    ]
    assert starts[:2] in ([alpha.id, bravo.id], [bravo.id, alpha.id])  # two slots
    assert starts[2:] == [charlie.id, delta.id, delta.id]
    changes = [e.job_ids for e in real.published if e.type == "queue.changed"]
    assert changes == [
        [alpha.id], [alpha.id, bravo.id], [alpha.id, bravo.id, charlie.id],
        [alpha.id, bravo.id, charlie.id, delta.id],
    ]  # fmt: skip
    # At most two jobs ran (or were paused) at once.
    active: set[str] = set()
    for event in real.published:
        if event.type == "job.state":
            if event.state in (JobState.RUNNING, JobState.PAUSED):
                active.add(event.job_id)
            else:
                active.discard(event.job_id)
            assert len(active) <= 2


# --------------------------------------------------------------------------- loudness


def make_silent_source(ffmpeg: str, path: Path, seconds: float = 5.0) -> Path:
    """Video, a silent stereo track (digital zero) and a sine tone."""
    subprocess.run(
        [ffmpeg, "-hide_banner", "-v", "error", "-y",
         "-f", "lavfi", "-i", f"testsrc2=size=160x90:rate=25:duration={seconds}",
         "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={seconds}",
         "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}",
         "-map", "0", "-map", "1", "-map", "2", "-c:v", "libx264", "-preset", "ultrafast",
         "-c:a", "aac", "-metadata:s:a:0", "language=eng", "-metadata:s:a:1", "language=hun",
         str(path)],
        check=True, capture_output=True, timeout=60,
    )  # fmt: skip
    return path


def integrated_loudness(ffmpeg: str, path: Path, index: int) -> float:
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostdin", "-i", str(path), "-map", f"0:a:{index}",
         "-af", "loudnorm=print_format=json", "-f", "null", "-"],
        capture_output=True, text=True, check=True, timeout=60,
    )  # fmt: skip
    match = re.search(r'"input_i" : "([^"]+)"', proc.stderr)
    assert match is not None, proc.stderr
    return float(match.group(1))


@pytest.fixture
def plain(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[str, Path]:
    """The real tools through tool discovery (no fake)."""
    ffmpeg, ffprobe = media.find_ffmpeg(), media.find_ffprobe()
    assert ffmpeg is not None
    assert ffprobe is not None
    for var in ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    for name in ("config", "data", "cache"):
        monkeypatch.setenv(f"REFRAME_{name.upper()}_DIR", str(tmp_path / name))
    monkeypatch.setenv("REFRAME_FFMPEG", ffmpeg)
    monkeypatch.setenv("REFRAME_FFPROBE", ffprobe)
    monkeypatch.setattr(mediainfo, "mediainfo_available", lambda: False)
    write_settings(tmp_path / "config")
    return ffmpeg, tmp_path


async def test_two_pass_loudnorm_with_a_silent_track(plain: tuple[str, Path]) -> None:
    ffmpeg, tmp = plain
    source_path = make_silent_source(ffmpeg, tmp / "silent.mkv")
    async with await Reframe.create() as app:
        source = await probe(app, source_path)
        job = draft(source, tmp / "out" / "Normalised.mkv")
        job.subtitles = []
        for track in job.audio:
            track.loudness = "ebu_r128"
        added = await app.queue.add(job)
        app.queue.start()
        [ended] = await app.queue.wait([added.id])
        assert ended.state is JobState.DONE, ended.error
        assert ended.plan is not None
        assert [s.kind for s in ended.plan.steps] == ["analyse", "analyse", "encode", "finalize"]
        log = app.queue.log_path(added.id).read_text(encoding="utf-8")
    assert "Loudness a0: silent or nearly silent, values clamped" in log
    assert "input_i -inf → -99.00" in log
    assert "target_offset inf → 0.00" in log
    assert "measured_I=-99.00:measured_TP=-99.00" in log  # the encode's command line
    output = tmp / "out" / "Normalised.mkv"
    assert integrated_loudness(ffmpeg, output, 1) == pytest.approx(-23.0, abs=1.0)
    silent = integrated_loudness(ffmpeg, output, 0)
    assert silent < -70.0  # still silent (loudnorm prints -inf or a value below its gate)


async def test_a_silent_track_shorter_than_3_seconds_fails_in_ffmpeg(
    plain: tuple[str, Path],
) -> None:
    """loudnorm's first-frame path (an input shorter than 3 s) makes NaN samples from a silent
    track, whatever the measured values (both n9.0.2 builds). The job fails with that
    reason; ``testdata/README.md`` records it. (A 2 s *range* of a longer source is not
    affected: loudnorm reads 3 s of input before the output limit stops it.)"""
    ffmpeg, tmp = plain
    source_path = make_silent_source(ffmpeg, tmp / "silent.mkv", seconds=2.0)
    async with await Reframe.create() as app:
        source = await probe(app, source_path)
        job = draft(source, tmp / "out" / "Short.mkv")
        job.subtitles = []
        job.audio = job.audio[:1]
        job.audio[0].loudness = "ebu_r128"
        added = await app.queue.add(job)
        app.queue.start()
        [ended] = await app.queue.wait([added.id])
    assert ended.state is JobState.FAILED
    assert ended.error is not None
    assert ended.error.startswith("The encode failed (exit code ")
    assert "Input contains (near) NaN/+-Inf" in ended.error
    assert not (tmp / "out" / "Short.part.mkv").exists()
