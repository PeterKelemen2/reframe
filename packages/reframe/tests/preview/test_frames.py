"""The ``frames`` task with the real FFmpeg (C-10): sample frames, the cache, fast seek, output
frames of a job, HDR for display, colour, rotation, missing pictures."""

from __future__ import annotations

import asyncio
import os
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from reframe.dimensions import compute_geometry, source_geometry
from reframe.mediatask import sample_timestamps
from reframe.models import (
    AppSettings,
    CropRect,
    FrameSet,
    MediaSource,
    PreviewSettings,
    TaskState,
)
from reframe.preview import cache_size, clear_cache, frame_path, start_frames
from reframe.preview.cache import PreviewCache, is_frame_key
from reframe.preview.graph import source_recipe

from .helpers import DEFS, caps, job_for, make_env, rgb_pixels, run_ffmpeg

pytestmark = [pytest.mark.anyio, pytest.mark.needs_ffmpeg]

Media = Callable[[str], Path]


async def frames_of(env_cache: Path, path: Path, **kwargs: object) -> tuple[object, FrameSet]:
    env = make_env(env_cache)
    done, value = await env.finish(
        start_frames(
            env.ctx,
            path,
            count=kwargs.pop("count", None),  # type: ignore[arg-type]
            timestamps=kwargs.pop("timestamps", None),  # type: ignore[arg-type]
            job=kwargs.pop("job", None),  # type: ignore[arg-type]
        )
    )
    assert done.state is TaskState.DONE, done.error
    assert isinstance(value, FrameSet)
    return done, value


# --------------------------------------------------------------------------- source frames


async def test_sample_frames_and_the_cache(tmp_path: Path, fixture_media: Media) -> None:
    src = fixture_media("letterbox")
    env = make_env(tmp_path / "cache")
    info = start_frames(env.ctx, src, count=3, timestamps=None, job=None)
    assert info.kind == "frames"
    assert info.message == "Frames of letterbox.mkv"
    done, fs = await env.finish(info)
    assert done.state is TaskState.DONE, done.error
    assert done.progress == 100.0
    assert isinstance(fs, FrameSet)
    probed = env.sources.known[str(src)]
    duration = probed.video[0].duration or probed.container.duration
    assert [f.timestamp for f in fs.frames] == sample_timestamps(duration, 3)
    assert fs.path == src
    assert fs.notes == []
    for frame in fs.frames:
        assert frame.kind == "source"
        assert (frame.width, frame.height) == (320, 180)
        assert not frame.cached
        assert is_frame_key(frame.key)
        assert frame.path == tmp_path / "cache" / "frames" / f"{frame.key}.png"
        assert frame.path.is_file()
        assert frame_path(env.ctx, frame.key) == frame.path
    assert done.result == fs.model_dump(mode="json")

    again_done, again = await env.finish(
        start_frames(env.ctx, src, count=3, timestamps=None, job=None)
    )
    assert again_done.state is TaskState.DONE
    assert isinstance(again, FrameSet)
    assert [f.key for f in again.frames] == [f.key for f in fs.frames]
    assert all(f.cached for f in again.frames)
    assert frame_path(env.ctx, "../frames/x") is None
    assert frame_path(env.ctx, fs.frames[0].key.replace("-", "_")) is None
    leftovers = [
        p.name for p in (tmp_path / "cache" / "frames").iterdir() if p.name.startswith(".")
    ]
    assert leftovers == []


async def test_the_default_count_comes_from_the_settings(
    tmp_path: Path, fixture_media: Media
) -> None:
    settings = AppSettings(preview=PreviewSettings(sample_frames=4))
    env = make_env(tmp_path / "cache", settings=settings)
    done, fs = await env.finish(
        start_frames(env.ctx, fixture_media("letterbox"), count=None, timestamps=None, job=None)
    )
    assert done.state is TaskState.DONE, done.error
    assert isinstance(fs, FrameSet)
    assert len(fs.frames) == 4


async def test_fast_seek_gives_the_frame_of_a_slow_seek(
    tmp_path: Path, fixture_media: Media
) -> None:
    """``-ss`` before ``-i`` decodes from the keyframe before T and starts at the first frame
    at or after T: the same picture as decoding everything (``-ss`` after ``-i``)."""
    src = fixture_media("letterbox")
    _, fs = await frames_of(tmp_path / "cache", src, timestamps=[0.2, 1.52, 2.0, 3.96])
    env = make_env(tmp_path / "other")
    probed = await env.sources.probe(src)
    assert isinstance(probed, MediaSource)
    recipe = source_recipe(probed.video[0], caps(), DEFS)
    chain = ",".join([*recipe.prefix, *recipe.chain])
    for frame in fs.frames:
        slow = tmp_path / f"slow-{frame.timestamp}.png"
        run_ffmpeg(
            "-i", str(src), "-ss", str(frame.timestamp), "-frames:v", "1", "-vf", chain, str(slow)
        )
        assert rgb_pixels(frame.path) == rgb_pixels(slow), frame.timestamp


async def test_a_time_without_a_picture_is_left_out(tmp_path: Path, fixture_media: Media) -> None:
    src = fixture_media("letterbox")
    _, fs = await frames_of(tmp_path / "cache", src, timestamps=[99.0, 1.0])
    assert [f.timestamp for f in fs.frames] == [1.0]
    assert fs.notes == [
        "No frame at 99.000 s: FFmpeg gave no picture at this time (after the last frame?)."
    ]
    env = make_env(tmp_path / "cache")
    done, _ = await env.finish(start_frames(env.ctx, src, count=None, timestamps=[99.0], job=None))
    assert done.state is TaskState.FAILED
    assert done.error is not None
    assert done.error.endswith(
        "No frame of letterbox.mkv could be made: "
        "FFmpeg gave no picture at this time (after the last frame?)."
    )
    leftovers = [
        p.name for p in (tmp_path / "cache" / "frames").iterdir() if p.name.startswith(".")
    ]
    assert leftovers == []


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"timestamps": [-1.0]}, "-1.0 is not a time in letterbox.mkv (seconds from 0)."),
        ({"count": 0}, "The number of frames must be 1 to 1000, not 0."),
    ],
)
async def test_bad_requests_fail_the_task(
    tmp_path: Path, fixture_media: Media, kwargs: dict[str, object], error: str
) -> None:
    env = make_env(tmp_path / "cache")
    done, _ = await env.finish(
        start_frames(
            env.ctx,
            fixture_media("letterbox"),
            count=kwargs.get("count"),  # type: ignore[arg-type]
            timestamps=kwargs.get("timestamps"),  # type: ignore[arg-type]
            job=None,
        )
    )
    assert done.state is TaskState.FAILED
    assert done.error is not None
    assert done.error.endswith(error)


async def test_a_file_that_is_not_media(tmp_path: Path) -> None:
    bad = tmp_path / "bad.mkv"
    bad.write_bytes(b"not a video" * 100)
    env = make_env(tmp_path / "cache")
    done, _ = await env.finish(start_frames(env.ctx, bad, count=2, timestamps=None, job=None))
    assert done.state is TaskState.FAILED
    assert done.error is not None
    assert "bad.mkv" in done.error


async def test_a_file_without_video(tmp_path: Path) -> None:
    audio = tmp_path / "tone.mka"
    run_ffmpeg("-f", "lavfi", "-i", "sine=duration=1", "-c:a", "flac", str(audio))
    env = make_env(tmp_path / "cache")
    done, _ = await env.finish(start_frames(env.ctx, audio, count=2, timestamps=None, job=None))
    assert done.state is TaskState.FAILED
    assert done.error is not None
    assert done.error.endswith("tone.mka has no video stream.")


async def test_without_ffmpeg(tmp_path: Path, fixture_media: Media) -> None:
    from .helpers import real_tools, tool

    tools = real_tools().model_copy(update={"ffmpeg": tool("ffmpeg", None)})
    env = make_env(tmp_path / "cache", tools=tools)
    done, _ = await env.finish(
        start_frames(env.ctx, fixture_media("letterbox"), count=1, timestamps=None, job=None)
    )
    assert done.state is TaskState.FAILED
    assert done.error is not None
    assert done.error.endswith("ffmpeg cannot be used: ffmpeg was not found.")


async def test_two_tasks_make_the_same_frames(tmp_path: Path, fixture_media: Media) -> None:
    src = fixture_media("letterbox")
    env = make_env(tmp_path / "cache")
    first = start_frames(env.ctx, src, count=4, timestamps=None, job=None)
    second = start_frames(env.ctx, src, count=4, timestamps=None, job=None)
    (a_done, a), (b_done, b) = await asyncio.gather(env.finish(first), env.finish(second))
    assert a_done.state is b_done.state is TaskState.DONE
    assert isinstance(a, FrameSet)
    assert isinstance(b, FrameSet)
    assert [f.key for f in a.frames] == [f.key for f in b.frames]
    assert all(f.path.is_file() for f in a.frames)
    names = sorted(p.name for p in (tmp_path / "cache" / "frames").iterdir())
    assert names == sorted(f"{f.key}.png" for f in a.frames)


async def test_the_cache_keeps_its_size_limit(tmp_path: Path, fixture_media: Media) -> None:
    cache = PreviewCache(tmp_path / "cache")
    cache.frames.mkdir(parents=True)
    old = cache.frame("0123456789abcdef-1000-0123456789abcdef")
    old.write_bytes(b"x" * 1000)
    hour_ago = time.time() - 3600
    os.utime(old, (hour_ago, hour_ago))
    settings = AppSettings(preview=PreviewSettings(cache_size_mb=0))
    env = make_env(tmp_path / "cache", settings=settings)
    done, fs = await env.finish(
        start_frames(env.ctx, fixture_media("letterbox"), count=2, timestamps=None, job=None)
    )
    assert done.state is TaskState.DONE, done.error
    assert isinstance(fs, FrameSet)
    assert not old.exists()  # least recently used, over the limit
    assert all(f.path.exists() for f in fs.frames)  # the task's own results stay


# --------------------------------------------------------------------------- output frames


async def test_output_frames_follow_the_job(tmp_path: Path, fixture_media: Media) -> None:
    src = fixture_media("letterbox")
    _, plain = await frames_of(tmp_path / "cache", src, count=2)
    job = job_for(src)
    job.dimensions.crop.mode = "manual"
    job.dimensions.crop.rect = CropRect(top=22, bottom=24)
    _, fs = await frames_of(tmp_path / "cache", src, count=2, job=job)
    sources = [f for f in fs.frames if f.kind == "source"]
    outputs = [f for f in fs.frames if f.kind == "output"]
    assert [f.key for f in sources] == [f.key for f in plain.frames]
    assert all(f.cached for f in sources)
    assert [f.timestamp for f in outputs] == [f.timestamp for f in sources]
    env = make_env(tmp_path / "x")
    probed = await env.sources.probe(src)
    assert isinstance(probed, MediaSource)
    geometry = compute_geometry(source_geometry(probed.video[0]), job.dimensions)
    for frame in outputs:
        assert (frame.width, frame.height) == (geometry.scaled_width, geometry.scaled_height)
        assert (frame.width, frame.height) == (320, 134)
        assert not frame.cached
        assert frame.key not in {f.key for f in sources}
    job.dimensions.crop.rect = CropRect(top=0, bottom=0, left=40, right=40)
    _, other = await frames_of(tmp_path / "cache", src, count=2, job=job)
    new_outputs = [f for f in other.frames if f.kind == "output"]
    assert {f.key for f in new_outputs}.isdisjoint({f.key for f in outputs})
    assert [(f.width, f.height) for f in new_outputs] == [(240, 180)] * 2
    assert [f.key for f in other.frames if f.kind == "source"] == [f.key for f in sources]


async def test_a_copied_video_reuses_the_source_frames(
    tmp_path: Path, fixture_media: Media
) -> None:
    src = fixture_media("letterbox")
    _, fs = await frames_of(tmp_path / "cache", src, count=2, job=job_for(src, passthrough=True))
    sources = [f for f in fs.frames if f.kind == "source"]
    outputs = [f for f in fs.frames if f.kind == "output"]
    assert [(f.key, f.path) for f in outputs] == [(f.key, f.path) for f in sources]
    assert fs.notes == ["The video is copied: the output frames are the source picture."]


async def test_a_job_that_cannot_be_planned_gives_source_frames(
    tmp_path: Path, fixture_media: Media
) -> None:
    src = fixture_media("letterbox")
    _, fs = await frames_of(tmp_path / "cache", src, count=2, job=job_for(src, encoder="nope"))
    assert {f.kind for f in fs.frames} == {"source"}
    assert fs.notes == [
        "No output frames: the job's filters cannot be applied (unknown video encoder 'nope' "
        "(validation reports it))."
    ]


async def test_a_job_of_another_file(tmp_path: Path, fixture_media: Media) -> None:
    env = make_env(tmp_path / "cache")
    job = job_for(fixture_media("anamorphic"))
    done, _ = await env.finish(
        start_frames(env.ctx, fixture_media("letterbox"), count=1, timestamps=None, job=job)
    )
    assert done.state is TaskState.FAILED
    assert done.error is not None
    assert done.error.endswith("The job is for another file (anamorphic.mkv).")


# --------------------------------------------------------------------------- picture


async def test_an_anamorphic_frame_keeps_the_source_pixels(
    tmp_path: Path, fixture_media: Media
) -> None:
    _, fs = await frames_of(tmp_path / "cache", fixture_media("anamorphic"), count=1)
    assert [(f.width, f.height) for f in fs.frames] == [(720, 480)]


async def test_hdr_frames_are_tone_mapped_for_display(tmp_path: Path, fixture_media: Media) -> None:
    src = fixture_media("hdr10")
    job = job_for(src, encoder="libx265", bit_depth=10)
    _, fs = await frames_of(tmp_path / "cache", src, count=2, job=job)
    assert fs.notes == [
        "The source is HDR10: a PNG cannot hold HDR, so the frames are tone mapped to SDR for "
        "display with zscale + tonemap.",
        "The output stays HDR: the output frames are tone mapped to SDR for display with "
        "zscale + tonemap, like the source frames.",
    ]
    assert [f.kind for f in fs.frames] == ["source", "source", "output", "output"]
    source, output = fs.frames[0], fs.frames[2]
    assert len(rgb_pixels(source.path)) == 320 * 180 * 3
    # The output of an HDR-keeping x265 job is the source picture: the same pixels.
    assert rgb_pixels(output.path) == rgb_pixels(source.path)


@pytest.mark.needs_gpu
async def test_hdr_frames_with_libplacebo(tmp_path: Path, fixture_media: Media) -> None:
    src = fixture_media("hdr10")
    env = make_env(tmp_path / "cache", snapshot=caps(libplacebo=True))
    done, fs = await env.finish(start_frames(env.ctx, src, count=2, timestamps=None, job=None))
    assert done.state is TaskState.DONE, done.error
    assert isinstance(fs, FrameSet)
    assert fs.notes[0].endswith("tone mapped to SDR for display with libplacebo.")
    assert len(fs.frames) == 2


async def test_an_untagged_hd_source_is_shown_with_bt709(tmp_path: Path) -> None:
    """FFmpeg converts an untagged frame to RGB with BT.601; a player (and C-7's graph)
    assumes BT.709 for HD, so the frames are tagged first, and converted by an explicit
    ``scale`` after the tagging."""
    src = tmp_path / "untagged.mkv"
    run_ffmpeg(
        "-f", "lavfi", "-i", "color=c=0x3080C0:size=1280x720:duration=1:rate=25",
        "-vf", "format=yuv420p", "-c:v", "libx264", "-preset", "ultrafast", "-qp", "0", str(src),
    )  # fmt: skip
    _, fs = await frames_of(tmp_path / "cache", src, timestamps=[0.5])
    ours = rgb_pixels(fs.frames[0].path)[:3]
    flags = "flags=bicubic+accurate_rnd+full_chroma_int"

    def pixel(name: str, chain: str, *seek: str) -> bytes:
        out = tmp_path / f"{name}.png"
        run_ffmpeg(*seek, "-i", str(src), "-frames:v", "1", "-vf", chain, str(out))
        return rgb_pixels(out)[:3]

    as709 = pixel("709", f"scale=in_color_matrix=bt709:{flags},format=rgb24")
    as601 = pixel("601", f"scale=in_color_matrix=bt601:{flags},format=rgb24")
    assert ours == as709
    assert ours != as601
    assert pixel("untagged", f"scale={flags},format=rgb24") == as601
    # FFmpeg n9.0.2: after an input seek, the automatic conversion comes before setparams.
    tagged_late = "setparams=colorspace=bt709,format=rgb24"
    assert pixel("seek", tagged_late, "-ss", "0.5") != pixel("noseek", tagged_late)


@pytest.fixture
def rotated(tmp_path: Path, fixture_media: Media) -> Path:
    """``letterbox.mkv`` with a 90° display matrix (stream copy into MP4)."""
    out = tmp_path / "rotated.mp4"
    run_ffmpeg(
        "-display_rotation:v:0", "90", "-i", str(fixture_media("letterbox")),
        "-c", "copy", str(out),
    )  # fmt: skip
    return out


async def test_a_display_matrix_is_applied(tmp_path: Path, rotated: Path) -> None:
    """Decision 0009: frames (and crop detection) see the picture with the display matrix
    applied by FFmpeg's automatic rotation."""
    _, fs = await frames_of(tmp_path / "cache", rotated, count=1)
    assert [(f.width, f.height) for f in fs.frames] == [(180, 320)]


async def test_a_source_in_a_folder_with_special_characters(
    tmp_path: Path, fixture_media: Media
) -> None:
    folder = tmp_path / "it's [a] film, 50% ; done"
    folder.mkdir()
    src = folder / "Film: part 1.mkv"
    shutil.copyfile(fixture_media("letterbox"), src)
    _, fs = await frames_of(tmp_path / "cache", src, count=1)
    assert len(fs.frames) == 1


async def test_clear_the_cache(tmp_path: Path, fixture_media: Media) -> None:
    """Settings → Preview: the cache size and Clear cache."""
    env = make_env(tmp_path / "cache")
    done, fs = await env.finish(
        start_frames(env.ctx, fixture_media("letterbox"), count=2, timestamps=None, job=None)
    )
    assert done.state is TaskState.DONE, done.error
    assert isinstance(fs, FrameSet)
    size = sum(f.path.stat().st_size for f in fs.frames)
    assert cache_size(env.ctx) == size
    assert clear_cache(env.ctx) == size
    assert cache_size(env.ctx) == 0
    assert [frame_path(env.ctx, f.key) for f in fs.frames] == [None, None]


@pytest.mark.parametrize(
    ("fixture", "video", "filters"),
    [
        ("letterbox", {}, {"denoise": {"implementation": "hqdn3d"}, "sharpen": {}}),
        ("interlaced", {}, {"deinterlace": {"preset": "bob"}}),
        ("hdr10", {"encoder": "libx265", "bit_depth": 10}, {}),
        ("hdr10", {}, {"tonemap": {}}),
    ],
)
async def test_one_run_for_both_kinds_gives_the_pixels_of_two_runs(
    tmp_path: Path,
    fixture_media: Media,
    fixture: str,
    video: dict[str, Any],
    filters: dict[str, dict[str, object]],
) -> None:
    """The source and the output frame of a timestamp come from one decode (``split``); the
    formats are negotiated across the split, so check that each picture is the one of a run
    that makes only that kind."""
    src = fixture_media(fixture)
    job = job_for(src, **video)
    job.filters = job.filters.model_validate(filters)
    job.dimensions.crop.mode = "manual"
    job.dimensions.crop.rect = CropRect(top=20, bottom=20, left=8, right=8)
    _, both = await frames_of(tmp_path / "cache", src, timestamps=[1.0], job=job)
    assert [f.cached for f in both.frames] == [False, False]
    first = {f.kind: rgb_pixels(f.path) for f in both.frames}
    for kind in ("source", "output"):
        for frame in both.frames:
            if frame.kind == kind:
                frame.path.unlink()
        _, alone = await frames_of(tmp_path / "cache", src, timestamps=[1.0], job=job)
        made = {f.kind: f for f in alone.frames}
        assert not made[kind].cached
        assert made["output" if kind == "source" else "source"].cached
        assert rgb_pixels(made[kind].path) == first[kind], kind


async def test_a_frame_made_meanwhile_by_another_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows refuses to replace a PNG that a reader has open: when another task has just made
    the same frame, its file counts."""
    from reframe.preview.frames import _place

    from .test_common import png

    temp = tmp_path / ".tmp-1-a.png"
    final = tmp_path / "a.png"
    temp.write_bytes(png(4, 4))

    def refuse(src: object, dst: object) -> None:
        raise PermissionError(dst)

    monkeypatch.setattr("reframe.preview.frames.os.replace", refuse)
    assert not await _place(temp, final)
    final.write_bytes(png(4, 4))
    assert await _place(temp, final)
    monkeypatch.undo()
    assert await _place(temp, final)
    assert not temp.exists()
