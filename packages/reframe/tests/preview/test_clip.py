"""The ``preview_clip`` task with the real FFmpeg: a job's full plan on a range, into the cache."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

import reframe.preview.clip as clip_module
from reframe.metadata import header
from reframe.metadata.header import HeaderEditResult
from reframe.models import (
    AudioOutputTrack,
    AverageBitrate,
    ConstantQuality,
    CropRect,
    EncoderState,
    EncoderStatus,
    FrameSet,
    HeaderEdit,
    JobSettings,
    PreviewClip,
    TaskState,
    TrackMetadata,
)
from reframe.preview import clip_path, start_frames, start_preview_clip
from reframe.preview.cache import is_clip_id
from reframe.tools import RunResult, run_streaming
from reframe_testing import fake_tools as ft
from reframe_testing import media
from reframe_testing.mkvtoolnix import mkvtoolnix_tool

from .helpers import (
    Env,
    caps,
    ffmpeg,
    file_reads_on_this_thread,
    job_for,
    make_env,
    real_tools,
    rgb_pixels,
    run_ffmpeg,
    tool,
)

pytestmark = [pytest.mark.anyio, pytest.mark.needs_ffmpeg]

Media = Callable[[str], Path]


def probe(path: Path) -> dict[str, Any]:
    ffprobe = media.find_ffprobe()
    assert ffprobe is not None
    out = subprocess.run(
        [ffprobe, "-v", "error", "-of", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    data: dict[str, Any] = json.loads(out.stdout)
    return data


def chapter_titles(path: Path) -> list[str]:
    ffprobe = media.find_ffprobe()
    assert ffprobe
    out = subprocess.run(
        [ffprobe, "-v", "error", "-of", "json", "-show_chapters", str(path)],
        capture_output=True, text=True, check=True, timeout=60,
    )  # fmt: skip
    return [c.get("tags", {}).get("title", "") for c in json.loads(out.stdout)["chapters"]]


async def clip(env: Env, job: JobSettings, start: float, seconds: float) -> PreviewClip:
    info = start_preview_clip(env.ctx, job, start=start, seconds=seconds)
    assert info.kind == "preview_clip"
    done, value = await env.finish(info)
    assert done.state is TaskState.DONE, done.error
    assert done.progress == 100.0
    assert isinstance(value, PreviewClip)
    return value


def lossless(path: Path, **video: Any) -> JobSettings:
    """libx264 at quality 0 (lossless), with a 2.39:1 crop of ``letterbox.mkv``."""
    job = job_for(path, rate_control=ConstantQuality(value=0).model_dump(), **video)
    job.dimensions.crop.mode = "manual"
    job.dimensions.crop.rect = CropRect(top=22, bottom=24)
    return job


def no_leftovers(clips: Path) -> list[str]:
    return sorted(p.name for p in clips.iterdir() if ".part" in p.name or p.name.startswith("."))


async def test_a_clip_with_the_jobs_plan(tmp_path: Path, fixture_media: Media) -> None:
    src = fixture_media("letterbox")
    env = make_env(tmp_path / "cache")
    job = lossless(src)
    result = await clip(env, job, start=1.0, seconds=2.0)
    clips = tmp_path / "cache" / "clips"
    assert is_clip_id(result.id)
    assert result.path == clips / f"{result.id}.mkv"
    assert result.path.is_file()
    assert result.source == src
    assert (result.start, result.duration) == (1.0, 2.0)
    assert (result.container, result.video_codec, result.job_type) == ("mkv", "h264", "encode")
    assert result.size == result.path.stat().st_size
    assert clip_path(env.ctx, result.id) == result.path
    assert clip_path(env.ctx, "../" + result.id) is None
    assert no_leftovers(clips) == []
    info = probe(result.path)
    video = info["streams"][0]
    assert (video["codec_name"], video["width"], video["height"]) == ("h264", 320, 134)
    assert float(info["format"]["duration"]) == pytest.approx(2.0, abs=0.05)
    assert job.output.path is None  # the caller's job is not changed


async def test_the_same_request_gives_the_cached_clip(
    tmp_path: Path, fixture_media: Media, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = fixture_media("letterbox")
    env = make_env(tmp_path / "cache")
    first = await clip(env, lossless(src), start=0.5, seconds=1.0)

    async def no_encode(*args: object, **kwargs: object) -> object:
        raise AssertionError("the cached clip must not be encoded again")

    monkeypatch.setattr("reframe.preview.clip.run_streaming", no_encode)
    again = await clip(env, lossless(src), start=0.5, seconds=1.0)
    assert again == first
    other = lossless(src)
    other.dimensions.crop.rect = CropRect(left=40, right=40)
    monkeypatch.undo()
    changed = await clip(env, other, start=0.5, seconds=1.0)
    assert changed.id != first.id


async def test_renamed_chapters_give_a_new_clip(tmp_path: Path, fixture_media: Media) -> None:
    src = fixture_media("chapters")
    env = make_env(tmp_path / "cache")
    first_job = job_for(src)
    first_job.chapters.names = ["Old A", "Old B", "Old C", "Old D", "Old E"]
    first = await clip(env, first_job, start=0.0, seconds=5.0)
    assert chapter_titles(first.path)[0] == "Old A"
    second_job = job_for(src)
    second_job.chapters.names = ["New A", "New B", "New C", "New D", "New E"]
    second = await clip(env, second_job, start=0.0, seconds=5.0)
    assert second.id != first.id
    assert chapter_titles(second.path)[0] == "New A"
    again = await clip(env, first_job, start=0.0, seconds=5.0)  # still cached
    assert (again.id, again.path) == (first.id, first.path)


async def test_two_identical_clips_at_once(tmp_path: Path, fixture_media: Media) -> None:
    """Two runs of the same clip id at once (a raised limit, or two processes on one cache)."""
    env = make_env(tmp_path / "cache", limits={"preview_clip": 2})
    src = fixture_media("hdr10-4k")
    job = job_for(src, encoder="libx265", bit_depth=10, preset="ultrafast")
    a = start_preview_clip(env.ctx, job, start=0.0, seconds=3.0)
    b = start_preview_clip(env.ctx, job, start=0.0, seconds=3.0)
    (done_a, clip_a), (done_b, clip_b) = await env.finish(a), await env.finish(b)
    assert done_a.state is TaskState.DONE, done_a.error
    assert done_b.state is TaskState.DONE, done_b.error
    assert isinstance(clip_a, PreviewClip)
    assert isinstance(clip_b, PreviewClip)
    assert clip_a.id == clip_b.id
    assert clip_a.path == clip_b.path
    clips = tmp_path / "cache" / "clips"
    assert sorted(p.name for p in clips.iterdir()) == [clip_a.path.name]
    assert clip_a.path.stat().st_size == clip_b.size


async def test_a_clip_made_meanwhile_by_another_run(
    tmp_path: Path, fixture_media: Media, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows refuses to replace a clip that a reader has open: when another run has just
    made the same clip, its file is used and ours is removed."""
    env = make_env(tmp_path / "cache")
    src = fixture_media("letterbox")
    job = job_for(src)
    first = await clip(env, job, start=0.0, seconds=1.0)
    replace = os.replace
    refused: list[str] = []

    def refuse_existing(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        if Path(target) == first.path:
            refused.append(Path(source).name)
            raise PermissionError(target)
        replace(source, target)

    monkeypatch.setattr("reframe.preview.cache.PreviewCache.find_clip", lambda *_: None)
    monkeypatch.setattr("reframe.preview.clip.os.replace", refuse_existing)
    again = await clip(env, job, start=0.0, seconds=1.0)
    assert (again.id, again.path) == (first.id, first.path)
    assert len(refused) == 1
    assert refused[0].startswith(".tmp-")
    assert no_leftovers(tmp_path / "cache" / "clips") == []


async def test_the_clip_cache_is_read_off_the_event_loop(
    tmp_path: Path, fixture_media: Media, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cache folder may be slow (a network share, a disk that spins up)."""
    src = fixture_media("letterbox")
    env = make_env(tmp_path / "cache")
    on_loop = file_reads_on_this_thread(monkeypatch, tmp_path / "cache")
    first = await clip(env, lossless(src), start=0.5, seconds=1.0)
    again = await clip(env, lossless(src), start=0.5, seconds=1.0)
    assert again == first
    assert on_loop == [], on_loop


async def test_the_encoded_frames_are_the_output_frames(
    tmp_path: Path, fixture_media: Media
) -> None:
    """With a lossless encode, the clip's frame at t is exactly the output frame of the job at
    start + t."""
    src = fixture_media("letterbox")
    env = make_env(tmp_path / "cache")
    job = lossless(src)
    result = await clip(env, job, start=0.0, seconds=2.0)
    done, clip_frames = await env.finish(
        start_frames(env.ctx, result.path, count=None, timestamps=[0.4, 1.2], job=None)
    )
    assert done.state is TaskState.DONE, done.error
    done, job_frames = await env.finish(
        start_frames(env.ctx, src, count=None, timestamps=[0.4, 1.2], job=job)
    )
    assert done.state is TaskState.DONE, done.error
    assert isinstance(clip_frames, FrameSet)
    assert isinstance(job_frames, FrameSet)
    encoded = [f for f in clip_frames.frames if f.kind == "source"]
    rendered = [f for f in job_frames.frames if f.kind == "output"]
    assert [(f.width, f.height) for f in encoded] == [(320, 134), (320, 134)]
    for a, b in zip(encoded, rendered, strict=True):
        assert rgb_pixels(a.path) == rgb_pixels(b.path), a.timestamp


async def test_the_clip_runs_to_the_end(tmp_path: Path, fixture_media: Media) -> None:
    env = make_env(tmp_path / "cache")
    result = await clip(env, lossless(fixture_media("letterbox")), start=3.0, seconds=60.0)
    assert result.duration == pytest.approx(1.0)
    assert float(probe(result.path)["format"]["duration"]) == pytest.approx(1.0, abs=0.05)


async def test_an_mp4_clip(tmp_path: Path, fixture_media: Media) -> None:
    env = make_env(tmp_path / "cache")
    result = await clip(env, job_for(fixture_media("letterbox"), container="mp4"), 1.0, 1.0)
    assert result.path.suffix == ".mp4"
    assert (result.container, result.video_codec) == ("mp4", "h264")


async def test_a_copied_video(tmp_path: Path, fixture_media: Media) -> None:
    src = fixture_media("letterbox")
    before = src.stat()
    env = make_env(tmp_path / "cache")
    job = job_for(src, passthrough=True)
    job.output.edit_in_place = True  # never for a preview: the clip goes into the cache
    result = await clip(env, job, start=1.0, seconds=1.0)
    assert (result.job_type, result.video_codec) == ("remux", "h264")
    assert result.path.parent == tmp_path / "cache" / "clips"
    after = src.stat()
    assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)


def record_runs(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """The argv of every step the clip task runs (the real runs still happen)."""
    runs: list[list[str]] = []
    real = run_streaming

    async def recording(argv: list[str], **kwargs: Any) -> RunResult:
        runs.append(list(argv))
        return await real(argv, **kwargs)

    monkeypatch.setattr("reframe.preview.clip.run_streaming", recording)
    return runs


async def test_two_pass_runs_both_passes(
    tmp_path: Path, fixture_media: Media, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = make_env(tmp_path / "cache")
    job = job_for(
        fixture_media("letterbox"),
        rate_control=AverageBitrate(kbps=300, two_pass=True).model_dump(),
    )
    runs = record_runs(monkeypatch)
    result = await clip(env, job, start=0.0, seconds=2.0)
    assert result.path.is_file()
    passes = [a[i + 1] for a in runs for i, arg in enumerate(a) if arg.split(":")[0] == "-pass"]
    assert passes == ["1", "2"]
    assert no_leftovers(tmp_path / "cache" / "clips") == []


def portuguese_loudness_job(src: Path) -> JobSettings:
    job = job_for(src)
    job.audio = [
        AudioOutputTrack(
            source_stream=2,
            encoder="aac",
            loudness="ebu_r128",
            metadata=TrackMetadata(language="pt-BR"),
        )
    ]
    return job


class Writer:
    """The header writer, faked: records each edit and the files that existed then."""

    def __init__(self, hold: threading.Event | None = None) -> None:
        self.edits: list[HeaderEdit] = []
        self.existed: list[bool] = []
        self.hold = hold
        self.started = threading.Event()

    def __call__(self, edit: HeaderEdit) -> HeaderEditResult:
        self.edits.append(edit)
        self.existed.append(edit.path.is_file())
        self.started.set()
        if self.hold is not None:
            self.hold.wait(30)
        return HeaderEditResult("written")


async def test_loudness_and_the_bcp47_language_header_edit(
    tmp_path: Path, fixture_media: Media, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The analyse step measures, the encode uses the values. FFmpeg writes the ISO 639-2
    language, and the header edit on the clip's own ``.part`` file the BCP 47 one; no
    MKVToolNix program runs."""
    env = make_env(tmp_path / "cache")
    runs = record_runs(monkeypatch)
    writer = Writer()
    monkeypatch.setattr(header, "apply_header_edit", writer)
    result = await clip(env, portuguese_loudness_job(fixture_media("multitrack")), 1.0, 2.0)
    streams = probe(result.path)["streams"]
    assert [s["codec_type"] for s in streams] == ["video", "audio"]
    assert streams[1]["tags"]["language"] == "por"
    assert [Path(run[0]).name for run in runs] == ["ffmpeg", "ffmpeg"]  # analyse, encode
    [edit] = writer.edits
    assert edit.path.parent == tmp_path / "cache" / "clips"
    assert ".part" in edit.path.name
    assert writer.existed == [True]
    assert [(t.track_type, t.number, t.language, t.language_ietf) for t in edit.tracks] == [
        ("audio", 1, "por", "pt-BR")
    ]


async def test_a_cancel_during_the_header_edit_waits_for_it(
    tmp_path: Path, fixture_media: Media, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The writer's thread cannot be stopped: the clip's ``.part`` file is removed after the
    write, never under it."""
    env = make_env(tmp_path / "cache")
    release = threading.Event()
    writer = Writer(hold=release)
    monkeypatch.setattr(header, "apply_header_edit", writer)
    job = portuguese_loudness_job(fixture_media("multitrack"))
    info = start_preview_clip(env.ctx, job, start=1.0, seconds=2.0)
    try:
        assert await asyncio.to_thread(writer.started.wait, 30)
        assert env.tasks.cancel(info.id)
        await asyncio.sleep(0.2)
        assert writer.edits[0].path.is_file()  # not removed under the write
    finally:
        release.set()
    done = await env.tasks.wait(info.id)
    assert done.state is TaskState.CANCELLED
    assert no_leftovers(tmp_path / "cache" / "clips") == []


async def test_a_cancel_ends_at_once_while_other_threads_hold_the_executor(
    tmp_path: Path, fixture_media: Media, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defect: the header edit waits for a worker of the shared default executor; a cancel
    then waits for whatever holds that worker."""
    loop = asyncio.get_running_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
    gate, busy = threading.Event(), asyncio.Event()

    async def encode_then_busy(*args: Any, **kwargs: Any) -> RunResult:
        result = await run_streaming(*args, **kwargs)
        if not busy.is_set():  # after the last encode: a hung share holds the only worker
            loop.run_in_executor(None, gate.wait, 60)
            busy.set()
        return result

    monkeypatch.setattr(clip_module, "run_streaming", encode_then_busy)
    writer = Writer()
    monkeypatch.setattr(header, "apply_header_edit", writer)
    env = make_env(tmp_path / "cache")
    job = portuguese_loudness_job(fixture_media("multitrack"))
    job.audio[0].loudness = "off"  # one FFmpeg run, then the header edit
    info = start_preview_clip(env.ctx, job, start=1.0, seconds=2.0)
    try:
        await asyncio.wait_for(busy.wait(), 60)
        await asyncio.sleep(0.3)
        assert env.tasks.cancel(info.id)
        done = await asyncio.wait_for(env.tasks.wait(info.id), 5)
        assert done.state is TaskState.CANCELLED
    finally:
        gate.set()


async def test_a_cancel_before_the_header_edit_starts_ends_at_once_and_writes_nothing(
    tmp_path: Path, fixture_media: Media, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defect: a cancel while the writer's thread has not run yet waits for it, and the
    writer then writes a file of a cancelled clip."""
    hold, waiting = threading.Event(), threading.Event()

    class HeldThread(threading.Thread):
        def run(self) -> None:
            waiting.set()
            hold.wait(30)
            super().run()

    from reframe.metadata import own_thread

    monkeypatch.setattr(own_thread, "Thread", HeldThread)
    writer = Writer()
    monkeypatch.setattr(header, "apply_header_edit", writer)
    env = make_env(tmp_path / "cache")
    info = start_preview_clip(
        env.ctx, portuguese_loudness_job(fixture_media("multitrack")), start=1.0, seconds=2.0
    )
    try:
        assert await asyncio.to_thread(waiting.wait, 60)
        assert env.tasks.cancel(info.id)
        done = await asyncio.wait_for(env.tasks.wait(info.id), 5)
        assert done.state is TaskState.CANCELLED
        assert no_leftovers(tmp_path / "cache" / "clips") == []
    finally:
        hold.set()
    await asyncio.sleep(0.2)
    assert writer.edits == []


@pytest.mark.needs_mkvtoolnix
async def test_the_clip_has_the_bcp47_language(tmp_path: Path, fixture_media: Media) -> None:
    env = make_env(tmp_path / "cache")
    result = await clip(env, portuguese_loudness_job(fixture_media("multitrack")), 1.0, 2.0)
    [audio] = [t for t in mkvmerge_tracks(result.path) if t["type"] == "audio"]
    assert (audio["properties"]["language"], audio["properties"]["language_ietf"]) == (
        "por",
        "pt-BR",
    )


def mkvmerge_tracks(path: Path) -> list[dict[str, Any]]:
    out = subprocess.run(
        [mkvtoolnix_tool("mkvmerge"), "-J", str(path)],
        capture_output=True, text=True, check=True, timeout=60,
    )  # fmt: skip
    tracks: list[dict[str, Any]] = json.loads(out.stdout)["tracks"]
    return tracks


@pytest.mark.parametrize(
    ("start", "seconds", "error"),
    [
        (-1.0, 2.0, "The clip start -1.0 is not a time in the source (seconds from 0)."),
        (1.0, 0.0, "The clip length must be more than 0 seconds, not 0.0."),
        (float("nan"), 2.0, "The clip start nan is not a time in the source (seconds from 0)."),
        (4.0, 2.0, "The clip start 4 s is not before the end of letterbox.mkv (4 s)."),
    ],
)
async def test_bad_ranges(
    tmp_path: Path, fixture_media: Media, start: float, seconds: float, error: str
) -> None:
    env = make_env(tmp_path / "cache")
    info = start_preview_clip(
        env.ctx, job_for(fixture_media("letterbox")), start=start, seconds=seconds
    )
    done, _ = await env.finish(info)
    assert done.state is TaskState.FAILED
    assert done.error is not None
    assert done.error.endswith(error)


async def test_a_job_with_errors(tmp_path: Path, fixture_media: Media) -> None:
    env = make_env(tmp_path / "cache")
    job = job_for(fixture_media("letterbox"), profile="main10")
    done, _ = await env.finish(start_preview_clip(env.ctx, job, start=0.0, seconds=1.0))
    assert done.state is TaskState.FAILED
    assert done.error is not None
    assert done.error.endswith("The job has errors: 'main10' is not a profile of x264.")
    assert list((tmp_path / "cache" / "clips").iterdir()) == []


async def test_an_encode_that_fails(
    tmp_path: Path, fixture_media: Media, fake_tools: ft.FakeTools
) -> None:
    fake_tools.set_scenario(
        ft.Scenario(
            [
                ft.Rule(
                    argv_contains=["-progress"],
                    exit_code=1,
                    actions=[
                        ft.write_output(4096),
                        ft.stderr("[vost#0:0/libx264 @ 0x1] Error while opening encoder\n"),
                    ],
                )
            ]
        )
    )
    toolset = real_tools().model_copy(update={"ffmpeg": tool("ffmpeg", str(fake_tools.ffmpeg))})
    env = make_env(tmp_path / "cache", tools=toolset)
    job = job_for(fixture_media("letterbox"))
    done, _ = await env.finish(start_preview_clip(env.ctx, job, start=0.0, seconds=1.0))
    assert done.state is TaskState.FAILED
    assert done.error is not None
    assert done.error.endswith(
        "Encode (x264) failed: FFmpeg failed (exit code 1): Error while opening encoder."
    )
    assert len(fake_tools.calls("ffmpeg")) == 1
    assert list((tmp_path / "cache" / "clips").iterdir()) == []


async def test_validation_waits_for_an_encoder_being_checked(
    tmp_path: Path, fixture_media: Media
) -> None:
    """An ``encoder.checking`` issue waits for the detection, then validates again with its
    result."""
    checking = caps()
    checking.encoders["libx264"] = EncoderStatus(id="libx264", state=EncoderState.CHECKING)
    env = make_env(tmp_path / "cache", snapshot=checking)
    env.caps.detected = caps()
    result = await clip(env, job_for(fixture_media("letterbox")), start=0.0, seconds=0.5)
    assert result.path.is_file()
    assert env.caps.waits == 1


async def test_a_clip_needs_a_video_stream(tmp_path: Path) -> None:
    audio = tmp_path / "tone.mka"
    run_ffmpeg("-f", "lavfi", "-i", "sine=duration=1", "-c:a", "flac", str(audio))
    env = make_env(tmp_path / "cache")
    done, _ = await env.finish(start_preview_clip(env.ctx, job_for(audio), start=0.0, seconds=1.0))
    assert done.state is TaskState.FAILED
    assert done.error is not None
    assert done.error.endswith("tone.mka has no video stream.")


async def test_a_loudness_measurement_that_fails(
    tmp_path: Path, fixture_media: Media, fake_tools: ft.FakeTools
) -> None:
    """The analyse step prints no ``loudnorm`` block: the task fails before the encode."""
    fake_tools.set_scenario(
        ft.Scenario(
            [
                ft.Rule(argv_contains=["loudnorm"], actions=[ft.stderr("nothing measured\n")]),
                ft.Rule(actions=[ft.exec_program(ffmpeg())]),
            ]
        )
    )
    toolset = real_tools().model_copy(update={"ffmpeg": tool("ffmpeg", str(fake_tools.ffmpeg))})
    env = make_env(tmp_path / "cache", tools=toolset)
    job = job_for(fixture_media("multitrack"))
    job.audio = [AudioOutputTrack(source_stream=2, encoder="aac", loudness="ebu_r128")]
    done, _ = await env.finish(start_preview_clip(env.ctx, job, start=0.0, seconds=1.0))
    assert done.state is TaskState.FAILED
    assert done.error is not None
    assert done.error.endswith(
        "Measure the loudness of audio track 1 (English Stereo) printed 0 loudnorm result(s), "
        "1 expected."
    )
    assert len(fake_tools.calls("ffmpeg")) == 1
    assert list((tmp_path / "cache" / "clips").iterdir()) == []
