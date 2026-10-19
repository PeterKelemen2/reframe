"""The ``cropdetect`` task with the real FFmpeg: sample frames, the crop and the black levels."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import pytest

from reframe.dimensions import compute_geometry, source_geometry
from reframe.models import (
    AppSettings,
    CropDetection,
    CropRect,
    CropSettings,
    DimensionSettings,
    MediaSource,
    PreviewSettings,
    SameAsSource,
    TaskState,
)
from reframe.preview import start_cropdetect, start_frames
from reframe.preview.crop import CROPDETECT
from reframe_testing import fake_tools as ft

from .helpers import ffmpeg, make_env, real_tools, run_ffmpeg, tool

pytestmark = [pytest.mark.anyio, pytest.mark.needs_ffmpeg]

Media = Callable[[str], Path]
LETTERBOX = CropRect(top=22, bottom=24)
PILLARBOX = CropRect(left=40, right=40)


async def detect(cache: Path, path: Path, count: int | None = None, **env: object) -> CropDetection:
    e = make_env(cache, **env)  # type: ignore[arg-type]
    info = start_cropdetect(e.ctx, path, count=count)
    assert info.kind == "cropdetect"
    done, value = await e.finish(info)
    assert done.state is TaskState.DONE, done.error
    assert done.progress == 100.0
    assert isinstance(value, CropDetection)
    return value


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("cropdetect-media")


@pytest.fixture(scope="module")
def pq_letterbox(made: Path) -> Path:
    """640x360 10-bit HEVC, BT.2020 PQ, a 640x268 picture between black bars of 46 lines."""
    out = made / "pq-letterbox.mkv"
    run_ffmpeg(
        "-f", "lavfi", "-i", "testsrc2=size=640x268:rate=24:duration=1",
        "-vf", "pad=640:360:0:46:black,format=yuv420p10le,setparams=range=tv:"
        "color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc",
        "-c:v", "libx265", "-preset", "ultrafast", "-x265-params", "log-level=error", str(out),
    )  # fmt: skip
    return out


@pytest.fixture(scope="module")
def fade_in(made: Path) -> Path:
    """1 s of black, then 1 s of a 2.39:1 letterboxed picture (320x180)."""
    out = made / "fade-in.mkv"
    run_ffmpeg(
        "-f", "lavfi", "-i", "color=black:size=320x180:rate=25:duration=1",
        "-f", "lavfi", "-i", "testsrc2=size=320x134:rate=25:duration=1",
        "-filter_complex", "[1:v]pad=320:180:0:22:black[p];[0:v][p]concat=n=2:v=1:a=0,"
        "format=yuv420p[v]",
        "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20", str(out),
    )  # fmt: skip
    return out


async def test_automatic_and_conservative_differ_on_changing_aspect_ratios(
    tmp_path: Path, fixture_media: Media
) -> None:
    """2 s of 2.39:1 letterbox, then 2 s of 4:3 pillarbox."""
    src = fixture_media("letterbox")
    result = await detect(tmp_path / "cache", src)
    assert result.path == src
    assert len(result.samples) == 10
    assert [s.crop for s in result.samples] == [LETTERBOX] * 5 + [PILLARBOX] * 5
    # A tie (5 : 5) goes to the crop that removes fewer edge pixels: 22 + 24 < 40 + 40.
    assert result.auto == LETTERBOX
    assert result.auto_frames == 5
    assert result.conservative == CropRect()
    assert result.auto != result.conservative
    assert result.notes == [
        "The frames disagree: automatic 22 / 24 / 0 / 0, conservative 0 / 0 / 0 / 0 "
        "(top / bottom / left / right)."
    ]


async def test_the_samples_are_the_frames_of_the_strip(
    tmp_path: Path, fixture_media: Media
) -> None:
    src = fixture_media("letterbox")
    settings = AppSettings(preview=PreviewSettings(sample_frames=7))
    result = await detect(tmp_path / "cache", src, settings=settings)
    env = make_env(tmp_path / "cache", settings=settings)
    _, frames = await env.finish(start_frames(env.ctx, src, count=None, timestamps=None, job=None))
    assert [s.timestamp for s in result.samples] == [f.timestamp for f in frames.frames]
    three = await detect(tmp_path / "cache", src, count=3)
    assert [s.crop for s in three.samples] == [LETTERBOX, PILLARBOX, PILLARBOX]
    assert (three.auto, three.auto_frames) == (PILLARBOX, 2)


async def test_no_crop_on_a_full_picture(tmp_path: Path, fixture_media: Media) -> None:
    result = await detect(tmp_path / "cache", fixture_media("anamorphic"), count=4)
    assert [s.crop for s in result.samples] == [CropRect()] * 4
    assert (result.auto, result.auto_frames, result.conservative) == (CropRect(), 4, CropRect())
    assert result.notes == []


async def test_black_frames_do_not_vote(tmp_path: Path, fade_in: Path) -> None:
    result = await detect(tmp_path / "cache", fade_in, count=4)
    crops = [s.crop for s in result.samples]
    assert crops[:2] == [None, None]
    assert crops[2:] == [LETTERBOX, LETTERBOX]
    assert (result.auto, result.auto_frames, result.conservative) == (LETTERBOX, 2, LETTERBOX)
    assert result.notes == ["2 of 4 frames are black: they do not count."]


async def test_an_anamorphic_crop_is_in_stored_pixels(tmp_path: Path) -> None:
    """The rect counts the stored pixels of an anamorphic picture, and the geometry takes it as
    it is."""
    src = tmp_path / "anamorphic-letterbox.mkv"
    run_ffmpeg(
        "-f", "lavfi", "-i", "testsrc2=size=720x360:rate=25:duration=1",
        "-vf", "pad=720:480:0:60:black,setsar=32/27,format=yuv420p",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", str(src),
    )  # fmt: skip
    result = await detect(tmp_path / "cache", src, count=2)
    assert result.auto == CropRect(top=60, bottom=60)
    env = make_env(tmp_path / "x")
    probed = await env.sources.probe(src)
    assert isinstance(probed, MediaSource)
    settings = DimensionSettings(
        crop=CropSettings(mode="auto", rect=result.auto),
        size=SameAsSource(),
        pixel_aspect="keep",
    )
    geometry = compute_geometry(source_geometry(probed.video[0]), settings)
    assert geometry.crop == result.auto
    assert (geometry.cropped_width, geometry.cropped_height) == (720, 360)


async def test_all_black(tmp_path: Path) -> None:
    black = tmp_path / "black.mkv"
    run_ffmpeg(
        "-f", "lavfi", "-i", "color=black:size=320x180:rate=25:duration=1",
        "-vf", "format=yuv420p", "-c:v", "libx264", "-preset", "ultrafast", str(black),
    )  # fmt: skip
    result = await detect(tmp_path / "cache", black, count=3)
    assert [s.crop for s in result.samples] == [None, None, None]
    assert (result.auto, result.auto_frames, result.conservative) == (CropRect(), 0, CropRect())
    assert result.notes == [
        "3 of 3 frames are black: they do not count.",
        "No frame has a picture to measure: no crop.",
    ]


async def test_a_display_matrix_is_applied(tmp_path: Path, fixture_media: Media) -> None:
    rotated = tmp_path / "rotated.mp4"
    run_ffmpeg(
        "-display_rotation:v:0", "90", "-i", str(fixture_media("letterbox")),
        "-c", "copy", str(rotated),
    )  # fmt: skip
    result = await detect(tmp_path / "cache", rotated, count=2)
    assert [s.crop for s in result.samples] == [
        CropRect(left=22, right=24),
        CropRect(top=40, bottom=40),
    ]


def cropdetect_line(path: Path, vf: str) -> str:
    proc = run_ffmpeg("-loglevel", "info", "-ss", "0.5", "-i", str(path), "-frames:v", "1",
                      "-vf", vf, "-f", "null", "-")  # fmt: skip
    lines = [line for line in proc.stderr.splitlines() if "Parsed_cropdetect" in line]
    assert lines, proc.stderr
    return lines[0]


async def test_pq_black_bars_are_found(tmp_path: Path, pq_letterbox: Path) -> None:
    result = await detect(tmp_path / "cache", pq_letterbox, count=3)
    assert [s.crop for s in result.samples] == [CropRect(top=46, bottom=46)] * 3


def test_an_absolute_limit_finds_no_bars_in_10_bit(pq_letterbox: Path) -> None:
    ours = cropdetect_line(pq_letterbox, CROPDETECT)
    assert "limit:0.094118" in ours
    assert ours.endswith("crop=640:268:0:46")
    absolute = cropdetect_line(pq_letterbox, "cropdetect=limit=24:round=2:skip=0")
    assert absolute.endswith("crop=640:360:0:0")


def test_a_single_frame_needs_skip_0(fixture_media: Media) -> None:
    proc = run_ffmpeg("-loglevel", "info", "-ss", "1", "-i", str(fixture_media("letterbox")),
                      "-frames:v", "1", "-vf", "cropdetect=round=2", "-f", "null", "-")  # fmt: skip
    assert "Parsed_cropdetect" not in proc.stderr


def _y_average(path: Path, crop: str) -> float:
    stats = f"{crop},signalstats,metadata=mode=print"
    proc = run_ffmpeg("-loglevel", "info", "-ss", "0.5", "-i", str(path), "-frames:v", "1",
                      "-vf", stats, "-f", "null", "-")  # fmt: skip
    match = re.search(r"lavfi\.signalstats\.YAVG=([0-9.]+)", proc.stderr)
    assert match is not None, proc.stderr
    return float(match.group(1))


def test_black_levels(fixture_media: Media, pq_letterbox: Path) -> None:
    sdr = _y_average(fixture_media("letterbox"), "crop=320:20:0:0")
    pq = _y_average(pq_letterbox, "crop=640:40:0:0")
    assert 15.5 < sdr < 17.0
    assert 63.0 < pq < 65.0


async def test_a_file_without_video(tmp_path: Path) -> None:
    audio = tmp_path / "tone.mka"
    run_ffmpeg("-f", "lavfi", "-i", "sine=duration=1", "-c:a", "flac", str(audio))
    env = make_env(tmp_path / "cache")
    done, _ = await env.finish(start_cropdetect(env.ctx, audio, count=2))
    assert done.state is TaskState.FAILED
    assert done.error is not None
    assert done.error.endswith("tone.mka has no video stream.")


async def test_a_missing_file(tmp_path: Path) -> None:
    env = make_env(tmp_path / "cache")
    done, _ = await env.finish(start_cropdetect(env.ctx, tmp_path / "gone.mkv", count=2))
    assert done.state is TaskState.FAILED
    assert done.error is not None
    assert done.error.endswith("The file does not exist.")


async def test_ffmpeg_that_fails_on_every_frame(
    tmp_path: Path, fixture_media: Media, fake_tools: ft.FakeTools
) -> None:
    fake_tools.set_scenario(
        ft.Scenario(
            [
                ft.Rule(
                    argv_contains=["cropdetect"],
                    exit_code=1,
                    actions=[ft.stderr("[hevc @ 0x1] Error decoding the frame\n")],
                )
            ]
        )
    )
    toolset = real_tools().model_copy(update={"ffmpeg": tool("ffmpeg", str(fake_tools.ffmpeg))})
    env = make_env(tmp_path / "cache", tools=toolset)
    done, _ = await env.finish(start_cropdetect(env.ctx, fixture_media("letterbox"), count=2))
    assert done.state is TaskState.FAILED
    assert done.error is not None
    assert done.error.endswith(
        "Crop detection failed on every frame: 0.200 s: FFmpeg failed (exit code 1): "
        "Error decoding the frame."
    )
    assert len(fake_tools.calls("ffmpeg")) == 2


async def test_one_failed_sample_is_a_note(
    tmp_path: Path, fixture_media: Media, fake_tools: ft.FakeTools
) -> None:
    fake_tools.set_scenario(
        ft.Scenario(
            [
                ft.Rule(
                    argv_has=["0.2"],
                    exit_code=1,
                    actions=[ft.stderr("[hevc @ 0x1] Error decoding the frame\n")],
                ),
                ft.Rule(actions=[ft.exec_program(ffmpeg())]),
            ]
        )
    )
    toolset = real_tools().model_copy(update={"ffmpeg": tool("ffmpeg", str(fake_tools.ffmpeg))})
    result = await detect(tmp_path / "cache", fixture_media("letterbox"), count=2, tools=toolset)
    assert [s.crop for s in result.samples] == [None, PILLARBOX]
    assert (result.auto, result.auto_frames) == (PILLARBOX, 1)
    assert result.notes == [
        "No result at 0.200 s: FFmpeg failed (exit code 1): Error decoding the frame."
    ]
