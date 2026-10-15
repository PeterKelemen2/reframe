"""Shared helpers of the preview tasks (C-10) and the ``cropdetect`` log parser. Pure."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from reframe.mediatask import TaskFailed
from reframe.models import ContainerInfo, CropRect, MediaSource, ToolInfo, ToolStatus, VideoStream
from reframe.preview.common import (
    MAX_FRAMES,
    displayed_size,
    failure_text,
    png_size,
    sample_duration,
    sample_times,
    tool_identity,
)
from reframe.preview.crop import parse_cropdetect
from reframe.tools import RunResult

from .helpers import recorded

# --------------------------------------------------------------------------- timestamps


def source_of(duration: float | None, video_duration: float | None = None) -> MediaSource:
    src = recorded("letterbox.mkv")
    video = src.video[0].model_copy(update={"duration": video_duration})
    return src.model_copy(update={"video": [video], "container": ContainerInfo(duration=duration)})


def test_the_video_duration_comes_first() -> None:
    src = source_of(10.0, 8.0)
    assert sample_duration(src, src.video[0]) == 8.0
    src = source_of(10.0)
    assert sample_duration(src, src.video[0]) == 10.0


def test_sample_times_are_the_mediatask_timestamps() -> None:
    src = source_of(200.0)
    times = sample_times(src, src.video[0], count=10)
    assert times[0] == 10.0
    assert times[-1] == 190.0
    assert len(times) == 10


def test_given_timestamps_are_sorted_rounded_and_unique() -> None:
    src = source_of(None)
    times = sample_times(src, src.video[0], count=10, timestamps=[3.0, 1.0004, 1.0, 0.0, 2.5])
    assert times == [0.0, 1.0, 2.5, 3.0]


@pytest.mark.parametrize("value", [-0.001, float("nan"), float("inf")])
def test_a_time_that_is_not_in_the_source(value: float) -> None:
    src = source_of(10.0)
    with pytest.raises(TaskFailed, match=r"is not a time in letterbox\.mkv"):
        sample_times(src, src.video[0], count=1, timestamps=[1.0, value])


def test_no_timestamps() -> None:
    src = source_of(10.0)
    with pytest.raises(TaskFailed, match="No timestamps were given"):
        sample_times(src, src.video[0], count=1, timestamps=[])


@pytest.mark.parametrize("count", [0, -1, MAX_FRAMES + 1])
def test_a_count_out_of_range(count: int) -> None:
    src = source_of(10.0)
    with pytest.raises(TaskFailed, match=f"must be 1 to {MAX_FRAMES}"):
        sample_times(src, src.video[0], count=count)


def test_too_many_timestamps() -> None:
    src = source_of(10.0)
    with pytest.raises(TaskFailed, match=f"At most {MAX_FRAMES} frames"):
        sample_times(src, src.video[0], count=1, timestamps=[i / 1000 for i in range(1001)])


def test_an_unknown_duration_needs_timestamps() -> None:
    src = source_of(None)
    with pytest.raises(TaskFailed, match=r"duration of letterbox\.mkv is not known"):
        sample_times(src, src.video[0], count=10)


# --------------------------------------------------------------------------- tools and runs


def test_tool_identity() -> None:
    info = ToolInfo(
        name="ffmpeg",
        status=ToolStatus.FOUND,
        path=Path("/usr/bin/ffmpeg"),
        version="n9.0.2",
        library_versions={"libavfilter": "11.4.100", "libavcodec": "62.11.100"},
    )
    assert tool_identity(info) == [
        "/usr/bin/ffmpeg",
        "n9.0.2",
        [("libavcodec", "62.11.100"), ("libavfilter", "11.4.100")],
    ]


def result(**fields: object) -> RunResult:
    base: dict[str, object] = {"returncode": 0, "stdout": b"", "stderr": b"", "duration": 0.1}
    return RunResult(**{**base, **fields})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("run", "text"),
    [
        (result(returncode=None, error="FileNotFoundError: x"), "FFmpeg could not start: Fil"),
        (result(returncode=-9, timed_out=True), "FFmpeg took too long and was stopped"),
        (result(), "FFmpeg gave no picture at this time (after the last frame?)"),
        (
            result(returncode=1, stderr=b"[in#0 @ 0x1] Error opening input: Invalid data\n"),
            "FFmpeg failed (exit code 1): Error opening input: Invalid data",
        ),
        (result(returncode=1, stderr=b""), "FFmpeg failed (exit code 1)"),
    ],
)
def test_failure_text(run: RunResult, text: str) -> None:
    assert failure_text(run).startswith(text)


def test_failure_text_of_given_lines() -> None:
    run = result(returncode=1, stderr=b"ignored\n")
    assert failure_text(run, ["Conversion failed!", "x: No such file or directory"]) == (
        "FFmpeg failed (exit code 1): x: No such file or directory"
    )


# --------------------------------------------------------------------------- PNG and sizes


def png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)


def test_png_size(tmp_path: Path) -> None:
    good = tmp_path / "a.png"
    good.write_bytes(png(3840, 2160))
    assert png_size(good) == (3840, 2160)
    for name, data in [
        ("short.png", png(10, 10)[:20]),
        ("jpeg.png", b"\xff\xd8\xff" + b"0" * 30),
        ("empty.png", png(0, 10)),
    ]:
        (tmp_path / name).write_bytes(data)
        assert png_size(tmp_path / name) is None
    assert png_size(tmp_path / "missing.png") is None


def test_displayed_size_follows_the_display_matrix() -> None:
    video = VideoStream(index=0, width=1920, height=1080)
    assert displayed_size(video) == (1920, 1080)
    assert displayed_size(video.model_copy(update={"rotation": 90})) == (1080, 1920)
    assert displayed_size(video.model_copy(update={"rotation": 180})) == (1920, 1080)
    assert displayed_size(video.model_copy(update={"rotation": 270})) == (1080, 1920)


# --------------------------------------------------------------------------- cropdetect


def line(crop: str, n: int = 0) -> str:
    return (
        f"[Parsed_cropdetect_0 @ 0x7f8758003440] x1:0 x2:319 y1:22 y2:155 w:320 h:134 x:0 "
        f"y:22 pts:{n} t:0.000000 limit:0.094118 crop={crop}"
    )


def test_parse_the_first_result() -> None:
    """The real log lines of ``letterbox.mkv`` (FFmpeg n9.0.2): one frame through the filter
    can print two lines; the first is the sample frame."""
    log = "\n".join(["Input #0, matroska", line("320:134:0:22"), line("320:180:0:0", 40)])
    assert parse_cropdetect(log, 320, 180) == (True, CropRect(top=22, bottom=24))


def test_parse_a_pillarbox() -> None:
    log = line("240:180:40:0")
    assert parse_cropdetect(log, 320, 180) == (True, CropRect(left=40, right=40))


def test_parse_a_black_frame() -> None:
    log = (
        "[Parsed_cropdetect_0 @ 0x7fe500003440] x1:319 x2:0 y1:179 y2:0 w:-318 h:-178 x:320 "
        "y:180 pts:0 t:0.000000 limit:0.094118 crop=-318:-178:320:180"
    )
    assert parse_cropdetect(log, 320, 180) == (True, None)


def test_parse_nothing() -> None:
    assert parse_cropdetect("", 320, 180) == (False, None)
    other = "[Parsed_scale_0 @ 0x1] crop=1:1:0:0"
    assert parse_cropdetect(other, 320, 180) == (False, None)


def test_parse_clamps_to_the_picture() -> None:
    assert parse_cropdetect(line("330:134:0:22"), 320, 180) == (True, CropRect(top=22, bottom=24))


def test_parse_a_rotated_picture() -> None:
    """``letterbox.mkv`` with a 90° display matrix: cropdetect sees the 180x320 picture."""
    log = line("134:320:22:0")
    assert parse_cropdetect(log, 180, 320) == (True, CropRect(left=22, right=24))
