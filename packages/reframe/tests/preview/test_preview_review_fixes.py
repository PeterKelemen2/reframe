"""Fixes of the core-complete review (R3) for the C-10 picture tasks, with the real FFmpeg.

- R3-3: the clip id covers the plan's files (the FFMETADATA chapter file holds the names).
- R3-4: an output chain that fails when FFmpeg runs it keeps the source frames (0033 §2, §4).
- R3-6: a timestamp that a frame key cannot hold fails the task with a message.
- R3-7: two runs of the same clip at once each write their own temporary files.
- R3-8: the ``cropdetect`` rounding example of ``testdata/README.md``.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from reframe.mediatask import TaskFailed
from reframe.models import FilterConfig, FrameSet, JobSettings, PreviewClip, TaskState
from reframe.preview import start_frames, start_preview_clip
from reframe.preview.cache import frame_key, is_frame_key
from reframe.preview.common import sample_times
from reframe.preview.crop import CROPDETECT, parse_cropdetect
from reframe_testing import media

from .helpers import Env, ffmpeg, job_for, make_env, recorded

pytestmark = [pytest.mark.anyio]

Media = Callable[[str], Path]


async def clip(env: Env, job: JobSettings, start: float, seconds: float) -> PreviewClip:
    info = start_preview_clip(env.ctx, job, start=start, seconds=seconds)
    done, value = await env.finish(info)
    assert done.state is TaskState.DONE, done.error
    assert isinstance(value, PreviewClip)
    return value


def chapter_titles(path: Path) -> list[str]:
    ffprobe = media.find_ffprobe()
    assert ffprobe
    out = subprocess.run(
        [ffprobe, "-v", "error", "-of", "json", "-show_chapters", str(path)],
        capture_output=True, text=True, check=True, timeout=60,
    )  # fmt: skip
    return [c.get("tags", {}).get("title", "") for c in json.loads(out.stdout)["chapters"]]


def leftovers(clips: Path) -> list[str]:
    return sorted(p.name for p in clips.iterdir() if ".part" in p.name or p.name.startswith("."))


# --------------------------------------------------------------------------- R3-3


@pytest.mark.needs_ffmpeg
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


# --------------------------------------------------------------------------- R3-4


@pytest.mark.needs_ffmpeg
async def test_a_bad_custom_filter_keeps_the_source_frames(
    tmp_path: Path, fixture_media: Media
) -> None:
    """0033 §4: the output frames that cannot be made are left out with a note, the source
    frames are still made. Here the plan accepts the chain and FFmpeg refuses it when it runs
    (``eq=gamma=nonsense``)."""
    src = fixture_media("letterbox")
    env = make_env(tmp_path / "cache")
    job = job_for(src)
    job.filters.root["custom"] = FilterConfig.model_validate({"custom": "eq=gamma=nonsense"})
    done, value = await env.finish(
        start_frames(env.ctx, src, count=None, timestamps=[1.0, 3.0], job=job)
    )
    assert done.state is TaskState.DONE, done.error
    assert isinstance(value, FrameSet)
    assert [(f.kind, f.timestamp) for f in value.frames] == [("source", 1.0), ("source", 3.0)]
    assert all(f.path.is_file() for f in value.frames)
    output_notes = [n for n in value.notes if n.startswith("No output frame at ")]
    assert [n.split(":")[0] for n in output_notes] == [
        "No output frame at 1.000 s",
        "No output frame at 3.000 s",
    ]
    assert all("FFmpeg failed" in n for n in output_notes), output_notes
    assert sorted(p.name for p in (tmp_path / "cache" / "frames").iterdir()) == sorted(
        f.path.name for f in value.frames
    )  # no temporary file is left


# --------------------------------------------------------------------------- R3-6


@pytest.mark.parametrize("value", [1e9, 1e10, 1e308, 999_999_999.9996])
def test_a_time_a_frame_key_cannot_hold(value: float) -> None:
    src = recorded("letterbox.mkv")
    with pytest.raises(TaskFailed, match=r"is not a time in letterbox\.mkv \(frames can be"):
        sample_times(src, src.video[0], count=1, timestamps=[1.0, value])


def test_the_last_time_a_frame_key_holds() -> None:
    from reframe.preview.cache import MAX_TIMESTAMP_MS

    src = recorded("letterbox.mkv")
    assert MAX_TIMESTAMP_MS == 999_999_999_999  # 12 digits, the key's limit
    (time,) = sample_times(src, src.video[0], count=1, timestamps=[999_999_999.999])
    assert is_frame_key(frame_key("0" * 16, time, "f" * 16))


@pytest.mark.needs_ffmpeg
async def test_a_time_far_after_the_end(tmp_path: Path, fixture_media: Media) -> None:
    env = make_env(tmp_path / "cache")
    src = fixture_media("letterbox")
    done, _ = await env.finish(start_frames(env.ctx, src, count=None, timestamps=[1e10], job=None))
    assert done.state is TaskState.FAILED
    assert done.error == (
        "1e+10 is not a time in letterbox.mkv (frames can be taken up to 999999999.999 s)."
    )


# --------------------------------------------------------------------------- R3-7


@pytest.mark.needs_ffmpeg
async def test_two_identical_clips_at_once(tmp_path: Path, fixture_media: Media) -> None:
    """Two runs of the same clip id at once (a raised limit, or two processes on one cache)."""
    env = make_env(tmp_path / "cache")
    env.tasks.set_limit("preview_clip", 2)
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


@pytest.mark.needs_ffmpeg
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
    assert leftovers(tmp_path / "cache" / "clips") == []


# --------------------------------------------------------------------------- R3-8


def _cropdetect(chain: str, size: str, round_to: int) -> str:
    """The first ``cropdetect`` line of FFmpeg's log (with its ``[Parsed_cropdetect_0 @ …]``
    prefix)."""
    proc = subprocess.run(
        [ffmpeg(), "-hide_banner", "-nostdin", "-loglevel", "info", "-f", "lavfi",
         "-i", f"color=c={'white' if 'pad' in chain else 'black'}:s={size}:d=1,format=yuv420p",
         "-vf", f"{chain},cropdetect=round={round_to}:skip=0", "-frames:v", "1", "-f", "null", "-"],
        capture_output=True, text=True, timeout=60, check=True,
    )  # fmt: skip
    (line,) = [x for x in proc.stderr.splitlines() if "crop=" in x][:1]
    return line


@pytest.mark.needs_ffmpeg
def test_cropdetect_rounding_example() -> None:
    """``testdata/README.md``: a 300x150 picture at 9,13 in 320x181. ``drawbox`` puts it there;
    ``pad`` on 4:2:0 puts it at 8,12 (the chroma grid)."""
    box = "drawbox=x=9:y=13:w=300:h=150:color=white:t=fill"
    at_9_13 = _cropdetect(box, "320x181", 2)
    assert "] x1:9 x2:308 y1:13 y2:162 w:298 h:148 x:10 y:14 " in at_9_13
    assert at_9_13.endswith(" crop=298:148:10:14")
    assert _cropdetect(box, "320x181", 1).endswith(" crop=288:144:16:16")
    padded = _cropdetect("pad=320:181:9:13:black", "300x150", 2)
    assert "] x1:8 x2:307 y1:12 y2:161 w:300 h:150 x:8 y:12 " in padded
    assert padded.endswith(" crop=300:150:8:12")
    assert _cropdetect("pad=320:181:9:13:black", "300x150", 1).endswith(" crop=288:144:14:16")
    # What the crop task makes of it (round=2 is the task's value).
    assert "round=2" in CROPDETECT
    found, rect = parse_cropdetect(at_9_13, 320, 181)
    assert found
    assert rect is not None
    assert (rect.top, rect.bottom, rect.left, rect.right) == (14, 19, 10, 12)
