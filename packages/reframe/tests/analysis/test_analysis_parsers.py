"""The pure parts of the analysis scans: parsing, command lines and the progress throttle."""

from __future__ import annotations

import asyncio
import io
import math
from pathlib import Path

import pytest

from reframe.analysis import bitrate, common, loudness, subtitles
from reframe.mediatask import TaskFailed
from reframe.models import (
    AudioStream,
    ContainerInfo,
    MediaSource,
    SourceRef,
    SubtitleStream,
    VideoStream,
)
from reframe.queue.loudnorm import MeasureError
from reframe.tools import CancelToken, RunResult
from reframe_testing import pgs


def _source() -> MediaSource:
    return MediaSource(
        ref=SourceRef(path=Path("/media/a.mkv")),
        container=ContainerInfo(duration=10.0),
        video=[VideoStream(index=0, width=320, height=180)],
        audio=[AudioStream(index=1, duration=9.5), AudioStream(index=2, duration=0.0)],
        subtitles=[SubtitleStream(index=3)],
    )


def test_find_stream_and_duration() -> None:
    source = _source()
    found = [common.find_stream(source, i) for i in range(5)]
    assert [s.kind if s is not None else None for s in found] == [
        "video",
        "audio",
        "audio",
        "subtitle",
        None,
    ]
    assert common.stream_duration(source, found[1]) == 9.5
    assert common.stream_duration(source, found[2]) == 10.0  # 0 is unknown: the container's
    assert common.stream_duration(source, None) == 10.0
    source.container.duration = None
    assert common.stream_duration(source, found[2]) is None


def test_fields_and_number() -> None:
    assert common.fields("pts_time=1.5|size=10|junk|x = y ") == {
        "pts_time": "1.5",
        "size": "10",
        "x": "y",
    }
    assert common.fields("") == {}
    assert common.number("1.25") == 1.25
    assert [common.number(v) for v in (None, "N/A", "", "inf", "-inf", "nan")] == [None] * 6


def _result(**kw: object) -> RunResult:
    defaults: dict[str, object] = {
        "returncode": 0,
        "stdout": b"",
        "stderr": b"",
        "duration": 0.1,
    }
    defaults.update(kw)
    return RunResult(**defaults)  # type: ignore[arg-type]


def test_check_run() -> None:
    path = Path("/media/a.mkv")
    common.check_run(_result(), "ffprobe", path)
    with pytest.raises(asyncio.CancelledError):
        common.check_run(_result(returncode=-9, cancelled=True), "ffprobe", path)
    with pytest.raises(TaskFailed, match=r"^ffprobe could not be started: FileNotFoundError"):
        common.check_run(_result(returncode=None, error="FileNotFoundError: x"), "ffprobe", path)
    with pytest.raises(TaskFailed, match=r"did not finish in time on a\.mkv"):
        common.check_run(_result(returncode=-9, timed_out=True), "ffmpeg", path)
    stderr = b"first\n\n  a.mkv: Invalid data found when processing input  \n"
    with pytest.raises(
        TaskFailed,
        match=r"^ffprobe failed on a\.mkv \(exit code 1\): a\.mkv: Invalid data found",
    ):
        common.check_run(_result(returncode=1, stderr=stderr), "ffprobe", path)
    with pytest.raises(TaskFailed, match=r"\(exit code 1\)$"):
        common.check_run(_result(returncode=1), "ffprobe", path)


def test_progress_reporter_throttles() -> None:
    now = [0.0]
    calls: list[tuple[float | None, str | None]] = []
    reporter = common.ProgressReporter(
        lambda p, m: calls.append((p, m)), interval=0.5, clock=lambda: now[0]
    )
    reporter.update(0.1, "a")  # the first report always goes out
    reporter.update(0.5, "a")  # same whole percent, too soon
    reporter.update(1.2, "a")  # a new whole percent
    now[0] = 0.4
    reporter.update(1.5, "a")  # too soon
    now[0] = 1.0
    reporter.update(1.6, "b")  # interval passed
    reporter.update(1.0, "b")  # never backwards
    reporter.update(250.0, "c")  # clamped
    reporter.update(-5.0, "c")
    assert calls == [(0.1, "a"), (1.2, "a"), (1.6, "b"), (100.0, "c")]


def test_parse_packet() -> None:
    line = "pts_time=0.011000|dts_time=0.011000|duration_time=0.010000|size=3140"
    assert bitrate.parse_packet(line) == bitrate.Packet(0.011, 0.01, 3140)
    # pts missing: the dts; N/A duration
    assert bitrate.parse_packet("pts_time=N/A|dts_time=2.5|duration_time=N/A|size=7") == (
        bitrate.Packet(2.5, None, 7)
    )
    assert bitrate.parse_packet("pts_time=N/A|dts_time=N/A|size=N/A") == bitrate.Packet(
        None, None, None
    )
    assert bitrate.parse_packet("duration_time=-1|size=-3|pts_time=1") == bitrate.Packet(
        1.0, None, None
    )
    assert bitrate.parse_packet("Exiting with exit code 0") is None
    assert bitrate.parse_packet("") is None


def _stats(*packets: tuple[float | None, float | None, int | None]) -> bitrate.PacketStats:
    stats = bitrate.PacketStats()
    for t, d, size in packets:
        stats.add(bitrate.Packet(t, d, size))
    return stats


def test_covered_time_from_the_packet_ends() -> None:
    # B-frames: decode order, the latest end is not the last packet
    stats = _stats((0.0, 0.04, 100), (0.12, 0.04, 50), (0.04, 0.04, 50), (0.08, 0.04, 50))
    assert stats.packets == 4
    assert stats.bytes == 250
    assert stats.covered() == pytest.approx(0.16)
    assert stats.bitrate() == round(250 * 8 / 0.16)


def test_covered_time_starts_at_the_first_packet() -> None:
    stats = _stats((10.0, 1.0, 1000), (11.0, 1.0, 1000))
    assert stats.covered() == pytest.approx(2.0)
    assert stats.bitrate() == 8000


def test_covered_time_without_durations_adds_one_interval() -> None:
    stats = _stats((0.0, None, 10), (1.0, None, 10), (2.0, None, 10))
    assert stats.covered() == pytest.approx(3.0)
    assert stats.bitrate() == 80


def test_covered_time_falls_back_to_the_probe_duration() -> None:
    one = _stats((5.0, None, 100))
    assert one.covered() is None
    assert one.bitrate() is None
    assert one.covered(4.0) == 4.0
    assert one.bitrate(4.0) == 200
    untimed = _stats((None, None, 100), (None, None, 300))
    assert untimed.packets == 2
    assert untimed.timed == 0
    assert untimed.bitrate(2.0) == 1600
    assert untimed.bitrate(0.0) is None


def test_packets_without_a_size_do_not_count() -> None:
    stats = _stats((0.0, 1.0, None), (1.0, 1.0, 10))
    assert (stats.packets, stats.bytes, stats.first) == (1, 10, 1.0)
    assert bitrate.PacketStats().bitrate(10.0) is None
    empty = _stats((0.0, 1.0, 0), (1.0, 1.0, 0))
    assert (empty.packets, empty.bitrate()) == (2, None)  # 0 b/s is unknown


def test_bitrate_argv() -> None:
    assert bitrate.scan_argv("ffprobe", Path("/m/a b.mkv"), 3) == [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "3",
        "-show_entries",
        "packet=pts_time,dts_time,duration_time,size",
        "-of",
        "compact=p=0",
        "-i",
        str(Path("/m/a b.mkv")),
    ]


def _events(*forced: bool) -> list[pgs.Event]:
    return [
        pgs.Event(1000 * i, 1000 * i + 500, 100 + i % 40, forced=f) for i, f in enumerate(forced)
    ]


def test_read_display_sets() -> None:
    data = pgs.sup(_events(True, False, True, False))
    found = subtitles.read_display_sets(io.BytesIO(data))
    assert (found.count, found.forced) == (8, 2)  # show + clear per event
    assert subtitles.read_display_sets(io.BytesIO(b"")) == subtitles.DisplaySets(0, 0)


def test_read_display_sets_with_a_cropped_object() -> None:
    """A cropped object has 8 more bytes; the forced flag of the next object is still found."""
    pcs = (
        bytes(10)
        + bytes([2])
        + bytes([0, 0, 0, 0x80, 0, 0, 0, 0])
        + bytes(8)  # the crop rectangle
        + bytes([0, 1, 0, 0x40, 0, 0, 0, 0])
    )
    data = pgs.segment(pgs.PCS, pcs, 0) + pgs.segment(pgs.END, b"", 0)
    assert subtitles.read_display_sets(io.BytesIO(data)) == subtitles.DisplaySets(1, 1)
    short = pgs.segment(pgs.PCS, bytes(10) + bytes([3, 0, 0, 0]), 0) + pgs.segment(pgs.END, b"", 0)
    assert subtitles.read_display_sets(io.BytesIO(short)) == subtitles.DisplaySets(1, 0)
    tiny = pgs.segment(pgs.PCS, bytes(4), 0) + pgs.segment(pgs.END, b"", 0)
    assert subtitles.read_display_sets(io.BytesIO(tiny)) == subtitles.DisplaySets(1, 0)


def test_read_display_sets_rejects_junk() -> None:
    with pytest.raises(subtitles.SupError, match="no PGS segment at byte 0"):
        subtitles.read_display_sets(io.BytesIO(b"not a sup file at all"))
    good = pgs.sup(_events(False))
    with pytest.raises(subtitles.SupError, match="no PGS segment"):
        subtitles.read_display_sets(io.BytesIO(good + b"PG"))
    cut = pgs.segment(pgs.PCS, bytes(30), 0)[:-5]
    with pytest.raises(subtitles.SupError, match="cut off"):
        subtitles.read_display_sets(io.BytesIO(cut))


def test_read_display_sets_stops_on_cancel() -> None:
    data = pgs.sup(_events(*([True] * 100)))
    token = CancelToken()
    token.cancel()
    found = subtitles.read_display_sets(io.BytesIO(data), cancel=token)
    assert found.count < 100  # it stopped early (every 64 segments it looks at the token)


def test_subtitle_argv() -> None:
    path = Path("/m/a.mkv")
    assert subtitles.count_argv("ffprobe", path)[1:] == [
        "-v",
        "error",
        "-select_streams",
        "s",
        "-show_entries",
        "packet=stream_index,pts_time,size",
        "-of",
        "compact=p=0",
        "-i",
        str(path),
    ]
    forced = subtitles.forced_argv("ffprobe", path, 4)
    assert forced[forced.index("-forced_subs_only") + 1] == "1"
    assert forced[forced.index("-select_streams") + 1] == "4"
    assert forced[forced.index("-show_entries") + 1] == "subtitle=pts_time"
    extract = subtitles.extract_argv("ffmpeg", path, {3: Path("/t/3.sup"), 5: Path("/t/5.sup")})
    assert extract[-14:] == [
        "-map",
        "0:3",
        "-c",
        "copy",
        "-f",
        "sup",
        str(Path("/t/3.sup")),
        "-map",
        "0:5",
        "-c",
        "copy",
        "-f",
        "sup",
        str(Path("/t/5.sup")),
    ]
    assert extract[extract.index("-progress") + 1] == "pipe:1"
    assert extract.index("-i") < extract.index("-map")


BLOCK = """[Parsed_loudnorm_0 @ 0x55d1c2a3f900]
{
	"input_i" : "-21.75",
	"input_tp" : "-18.06",
	"input_lra" : "0.00",
	"input_thresh" : "-31.75",
	"output_i" : "-24.31",
	"output_tp" : "-20.62",
	"output_lra" : "0.00",
	"output_thresh" : "-34.31",
	"normalization_type" : "dynamic",
	"target_offset" : "0.31"
}
"""
SILENT = BLOCK.replace('"-21.75"', '"-inf"').replace('"-18.06"', '"-inf"')


def test_parse_measurement() -> None:
    assert loudness.parse_measurement("size=N/A\n" + BLOCK + "[out#0/null @ 0x1] video:0KiB") == {
        "integrated": -21.75,
        "true_peak": -18.06,
        "lra": 0.0,
        "threshold": -31.75,
    }
    assert loudness.parse_measurement(SILENT) == {
        "integrated": None,
        "true_peak": None,
        "lra": 0.0,
        "threshold": -31.75,
    }
    # the last block wins
    two = BLOCK + BLOCK.replace('"-21.75"', '"-30.00"')
    assert loudness.parse_measurement(two)["integrated"] == -30.0


def test_parse_measurement_failures() -> None:
    with pytest.raises(MeasureError, match="no measurement"):
        loudness.parse_measurement("Conversion failed!")
    with pytest.raises(MeasureError, match="not a number"):
        loudness.parse_measurement(BLOCK.replace('"-21.75"', '"loud"'))
    missing = loudness.parse_measurement(BLOCK.replace('"input_tp" : "-18.06",', ""))
    assert missing["true_peak"] is None
    negative = loudness.parse_measurement(
        BLOCK.replace('"input_lra" : "0.00"', '"input_lra" : "-1"')
    )
    assert negative["lra"] is None
    nan = loudness.parse_measurement(BLOCK.replace('"-31.75"', '"nan"'))
    assert nan["threshold"] is None


def test_seconds() -> None:
    assert [loudness.seconds(v) for v in (0.0, 3.0, 12.5, 1e-7, 0.000123, 7200.25)] == [
        "0",
        "3",
        "12.5",
        "0",
        "0.000123",
        "7200.25",
    ]
    assert not any("e" in loudness.seconds(v) for v in (1e-9, 1e9, math.pi))


def test_loudness_argv() -> None:
    path = Path("/m/a.mkv")
    whole = loudness.measure_argv("ffmpeg", path, 2, None, None)
    assert "-ss" not in whole
    assert "-t" not in whole
    assert whole[whole.index("-map") + 1] == "0:2"
    assert whole[whole.index("-filter:a") + 1] == "loudnorm=print_format=json"
    assert whole[-3:] == ["-f", "null", "-"]
    assert whole[whole.index("-progress") + 1] == "pipe:1"
    part = loudness.measure_argv("ffmpeg", path, 2, 30.5, 10.0)
    assert part.index("-ss") < part.index("-i") < part.index("-t")  # fast seek, then a limit
    assert part[part.index("-ss") + 1] == "30.5"
    assert part[part.index("-t") + 1] == "10"
    assert "-ss" not in loudness.measure_argv("ffmpeg", path, 2, 0.0, None)
