"""The analysis tasks with a fake task context and fake ffmpeg / ffprobe: expected failures end the
task ``failed`` with a message, results are stored with the source, and the roles that depend on
measured values are worked out again."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from reframe import analysis
from reframe.definitions import load_definitions
from reframe.events import EventBus
from reframe.mediatask import MediaTaskContext
from reframe.models import (
    AppSettings,
    AudioStream,
    BitrateInfo,
    BitrateScan,
    BitrateSource,
    CapabilitySnapshot,
    ContainerInfo,
    Disposition,
    LoudnessMeasurement,
    MediaSource,
    SourceFingerprint,
    SourceRef,
    SubtitleScan,
    SubtitleStream,
    TaskInfo,
    TaskState,
    ToolInfo,
    ToolSet,
    ToolStatus,
    TrackRole,
    VideoStream,
)
from reframe.probe import ProbeError, ProbeErrorKind
from reframe.tasks import TaskContext, TaskManager
from reframe.tools import CancelToken, RunResult, run_streaming
from reframe_testing import fake_tools as ft
from reframe_testing.fake_tools import FakeTools

pytestmark = pytest.mark.anyio


class _Tools:
    def __init__(self, tools: ToolSet) -> None:
        self.tools = tools

    async def status(self) -> ToolSet:
        return self.tools


class _Sources:
    def __init__(self, outcome: MediaSource | ProbeError) -> None:
        self.outcome = outcome
        self.stored: list[MediaSource] = []

    async def probe(
        self,
        path: str | os.PathLike[str],
        *,
        use_cache: bool = True,
        cancel: CancelToken | None = None,
    ) -> MediaSource | ProbeError:
        if isinstance(self.outcome, MediaSource):
            return self.outcome.model_copy(deep=True)
        return self.outcome

    async def store(self, source: MediaSource) -> None:
        self.stored.append(source)

    async def update(
        self, source: MediaSource, change: Callable[[MediaSource], MediaSource]
    ) -> None:
        self.stored.append(change(self.stored[-1] if self.stored else source))


class _Caps:
    @property
    def snapshot(self) -> CapabilitySnapshot:
        return CapabilitySnapshot()

    async def wait(self) -> CapabilitySnapshot:
        return CapabilitySnapshot()


def _info(name: str, path: Path | None, env: dict[str, str] | None = None) -> ToolInfo:
    if path is None:
        return ToolInfo(name=name, status=ToolStatus.MISSING, reason="not found")  # type: ignore[arg-type]
    return ToolInfo(name=name, status=ToolStatus.FOUND, path=path, env=env or {})  # type: ignore[arg-type]


def _context(
    tmp_path: Path,
    sources: _Sources,
    *,
    ffmpeg: Path | None = None,
    ffprobe: Path | None = None,
    env: dict[str, str] | None = None,
) -> MediaTaskContext:
    events = EventBus()
    tools = ToolSet(
        ffmpeg=_info("ffmpeg", ffmpeg, env),
        ffprobe=_info("ffprobe", ffprobe, env),
    )
    return MediaTaskContext(
        tasks=TaskManager(events),
        tools=_Tools(tools),
        sources=sources,
        capabilities=_Caps(),
        settings=AppSettings,
        events=events,
        cache_dir=tmp_path / "cache",
        definitions=load_definitions,
    )


FILE = "movie.mkv"


def _source(tmp_path: Path) -> MediaSource:
    path = tmp_path / FILE
    path.write_bytes(b"not really a film")
    return MediaSource(
        ref=SourceRef(path=path, fingerprint=SourceFingerprint(size=17, mtime=1.0)),
        container=ContainerInfo(duration=4.0),
        video=[VideoStream(index=0, width=320, height=180)],
        audio=[
            AudioStream(
                index=1,
                type_index=0,
                language="eng",
                channels=6,
                disposition=Disposition(default=True),
            ),
            AudioStream(index=2, type_index=1, language="eng", channels=2),
        ],
        subtitles=[
            SubtitleStream(index=3, type_index=0, codec="subrip", language="eng"),
            SubtitleStream(index=4, type_index=1, codec="dvd_subtitle", language="eng"),
            SubtitleStream(index=5, type_index=2, codec="ass", language="hun"),
        ],
    )


async def _finish(ctx: MediaTaskContext, info: TaskInfo) -> TaskInfo:
    return await ctx.tasks.wait(info.id)


def _failed_with(done: TaskInfo, message: str) -> None:
    assert done.state is TaskState.FAILED, done
    assert done.error is not None
    assert message in done.error


@pytest.mark.parametrize(
    ("index", "message"),
    [
        (9, "movie.mkv has no stream 9."),
        (3, "Stream 3 of movie.mkv is a subtitle stream; only audio and video streams"),
    ],
)
async def test_bitrate_scan_of_a_wrong_stream_fails(
    tmp_path: Path, index: int, message: str
) -> None:
    sources = _Sources(_source(tmp_path))
    ctx = _context(tmp_path, sources, ffprobe=tmp_path / "ffprobe")
    done = await _finish(ctx, analysis.start_bitrate_scan(ctx, tmp_path / FILE, index))
    _failed_with(done, message)
    assert done.kind == "bitrate_scan"
    assert sources.stored == []


async def test_scans_fail_without_their_tool(tmp_path: Path) -> None:
    ctx = _context(tmp_path, _Sources(_source(tmp_path)))
    path = tmp_path / FILE
    _failed_with(
        await _finish(ctx, analysis.start_bitrate_scan(ctx, path, 1)),
        "ffprobe cannot be used: not found",
    )
    _failed_with(
        await _finish(ctx, analysis.start_subtitle_scan(ctx, path, None)),
        "ffprobe cannot be used: not found",
    )
    _failed_with(
        await _finish(ctx, analysis.start_loudness_scan(ctx, path, 1, start=None, duration=None)),
        "ffmpeg cannot be used: not found",
    )


async def test_scans_fail_with_the_probe_error(tmp_path: Path) -> None:
    error = ProbeError(tmp_path / FILE, ProbeErrorKind.NOT_FOUND, "movie.mkv does not exist.")
    ctx = _context(
        tmp_path, _Sources(error), ffmpeg=tmp_path / "ffmpeg", ffprobe=tmp_path / "ffprobe"
    )
    path = tmp_path / FILE
    for info in (
        analysis.start_bitrate_scan(ctx, path, 1),
        analysis.start_subtitle_scan(ctx, path, [3]),
        analysis.start_loudness_scan(ctx, path, 1, start=None, duration=None),
    ):
        _failed_with(await _finish(ctx, info), "movie.mkv does not exist.")


@pytest.mark.parametrize(
    ("indexes", "message"),
    [
        ([3, 1], "Stream 1 of movie.mkv is not a subtitle stream."),
        ([42], "Stream 42 of movie.mkv does not exist."),
    ],
)
async def test_subtitle_scan_of_a_wrong_stream_fails(
    tmp_path: Path, indexes: list[int], message: str
) -> None:
    sources = _Sources(_source(tmp_path))
    ctx = _context(tmp_path, sources, ffprobe=tmp_path / "ffprobe")
    done = await _finish(ctx, analysis.start_subtitle_scan(ctx, tmp_path / FILE, indexes))
    _failed_with(done, message)
    assert sources.stored == []


async def test_subtitle_scan_of_no_tracks(tmp_path: Path) -> None:
    source = _source(tmp_path)
    source.subtitles = []
    sources = _Sources(source)
    ctx = _context(tmp_path, sources, ffprobe=tmp_path / "ffprobe")
    done = await _finish(ctx, analysis.start_subtitle_scan(ctx, tmp_path / FILE, None))
    assert done.state is TaskState.DONE
    assert done.result == {"path": str(tmp_path / FILE), "tracks": []}
    assert ctx.tasks.value(done.id) == SubtitleScan(path=tmp_path / FILE)
    assert sources.stored == []


@pytest.mark.parametrize(
    ("index", "start", "duration", "message"),
    [
        (0, None, None, "Stream 0 of movie.mkv is a video stream, not an audio stream."),
        (8, None, None, "movie.mkv has no stream 8."),
        (1, -1.0, None, "The start of the measurement must be 0 or more seconds, not -1.0."),
        (1, float("nan"), None, "must be 0 or more seconds"),
        (1, None, 0.0, "The length of the measurement must be more than 0 s, not 0.0."),
        (1, None, float("inf"), "must be more than 0 s"),
    ],
)
async def test_loudness_with_wrong_arguments_fails(
    tmp_path: Path, index: int, start: float | None, duration: float | None, message: str
) -> None:
    ctx = _context(tmp_path, _Sources(_source(tmp_path)), ffmpeg=tmp_path / "ffmpeg")
    info = analysis.start_loudness_scan(ctx, tmp_path / FILE, index, start=start, duration=duration)
    _failed_with(await _finish(ctx, info), message)


PACKETS = "".join(
    f"pts_time={i * 0.5:.6f}|dts_time={i * 0.5:.6f}|duration_time=0.500000|size=8000\n"
    for i in range(8)
)


@pytest.fixture
def progress(monkeypatch: pytest.MonkeyPatch) -> list[float | None]:
    """Every percent that a task reports (``TaskContext.progress``), in order."""
    calls: list[float | None] = []
    original = TaskContext.progress

    def spy(
        self: TaskContext,
        percent: float | None = None,
        message: str | None = None,
        *,
        done: int | None = None,
        total: int | None = None,
    ) -> None:
        calls.append(percent)
        original(self, percent, message, done=done, total=total)

    monkeypatch.setattr(TaskContext, "progress", spy)
    return calls


async def test_bitrate_scan_stores_the_measured_bit_rate(
    tmp_path: Path, fake_tools: FakeTools, progress: list[float | None]
) -> None:
    fake_tools.set_scenario(
        ft.Scenario([ft.Rule(tool="ffprobe", argv_has=["-select_streams", "2"],
                             actions=[ft.stdout(PACKETS)])])
    )  # fmt: skip
    sources = _Sources(_source(tmp_path))
    ctx = _context(tmp_path, sources, ffprobe=fake_tools.ffprobe)
    done = await _finish(ctx, analysis.start_bitrate_scan(ctx, tmp_path / FILE, 2))
    assert done.state is TaskState.DONE, done.error
    scan = ctx.tasks.value(done.id)
    assert scan == BitrateScan(
        path=tmp_path / FILE,
        stream_index=2,
        bitrate=BitrateInfo(value=128_000, source=BitrateSource.MEASURED),
        packets=8,
        bytes=64_000,
        duration=4.0,
    )
    assert done.result == scan.model_dump(mode="json")
    (stored,) = sources.stored
    assert stored.audio[1].bitrate == scan.bitrate
    assert stored.audio[0].bitrate == BitrateInfo()
    # With a known bit rate, the untitled stereo track after the 5.1 track is a commentary
    # candidate (the role heuristic runs again).
    assert [r.role for r in stored.audio[1].roles] == [TrackRole.COMMENTARY]
    assert progress[:2] == [None, 0.0]  # waiting for the probe, then reading
    assert progress[-1] == pytest.approx(87.5)  # the start of the last packet
    assert done.progress == 100.0
    (call,) = fake_tools.calls("ffprobe")
    assert call[call.index("-show_entries") + 1] == "packet=pts_time,dts_time,duration_time,size"


async def test_bitrate_scan_of_a_stream_without_packets(
    tmp_path: Path, fake_tools: FakeTools
) -> None:
    fake_tools.set_scenario(ft.Scenario([ft.Rule(tool="ffprobe", actions=[ft.stdout("")])]))
    sources = _Sources(_source(tmp_path))
    ctx = _context(tmp_path, sources, ffprobe=fake_tools.ffprobe)
    done = await _finish(ctx, analysis.start_bitrate_scan(ctx, tmp_path / FILE, 0))
    assert done.state is TaskState.DONE
    scan = ctx.tasks.value(done.id)
    assert isinstance(scan, BitrateScan)
    assert (scan.bitrate, scan.packets, scan.bytes) == (BitrateInfo(), 0, 0)
    assert scan.duration == 4.0  # the container's duration
    assert sources.stored == []


async def test_a_failing_ffprobe_fails_the_scan(tmp_path: Path, fake_tools: FakeTools) -> None:
    fake_tools.set_scenario(
        ft.Scenario([ft.Rule(tool="ffprobe", exit_code=1, actions=[
            ft.stderr("movie.mkv: Invalid data found when processing input\n")])])
    )  # fmt: skip
    sources = _Sources(_source(tmp_path))
    ctx = _context(tmp_path, sources, ffprobe=fake_tools.ffprobe)
    for info in (
        analysis.start_bitrate_scan(ctx, tmp_path / FILE, 1),
        analysis.start_subtitle_scan(ctx, tmp_path / FILE, None),
    ):
        _failed_with(
            await _finish(ctx, info),
            "ffprobe failed on movie.mkv (exit code 1): "
            "movie.mkv: Invalid data found when processing input",
        )
    assert sources.stored == []


async def test_subtitle_scan_counts_and_stores(tmp_path: Path, fake_tools: FakeTools) -> None:
    packets = "".join(
        f"stream_index={index}|pts_time={t:.1f}\n"
        for index, times in ((3, (0.5, 1.0, 1.5, 2.0)), (4, (1.0, 3.0)), (5, (0.2,)), (6, (9,)))
        for t in times
    )
    fake_tools.set_scenario(
        ft.Scenario([
            ft.Rule(tool="ffprobe", argv_has=["-forced_subs_only"],
                    actions=[ft.stdout("pts_time=3.000000\n")]),
            ft.Rule(tool="ffprobe", argv_has=["packet=stream_index,pts_time,size"],
                    actions=[ft.stdout(packets)]),
        ])
    )  # fmt: skip
    sources = _Sources(_source(tmp_path))
    ctx = _context(tmp_path, sources, ffprobe=fake_tools.ffprobe)
    done = await _finish(ctx, analysis.start_subtitle_scan(ctx, tmp_path / FILE, [4, 3, 4]))
    assert done.state is TaskState.DONE, done.error
    assert done.result == {
        "path": str(tmp_path / FILE),
        "tracks": [
            {"stream_index": 4, "event_count": 2, "forced_event_count": 1},
            {"stream_index": 3, "event_count": 4, "forced_event_count": None},
        ],
    }
    (stored,) = sources.stored
    counts = [(s.event_count, s.event_count_source, s.forced_event_count) for s in stored.subtitles]
    assert counts == [(4, "measured", None), (2, "measured", 1), (None, None, None)]
    # 2 events are 50 % of the 4 of the other English track: not a forced candidate yet.
    assert [r.role for r in stored.subtitles[1].roles] == [TrackRole.MAIN]
    calls = fake_tools.calls("ffprobe")
    assert len(calls) == 2  # one packet count for both tracks, one forced decode (VobSub)
    assert calls[1][calls[1].index("-select_streams") + 1] == "4"


async def test_subtitle_scan_recomputes_the_forced_heuristic(
    tmp_path: Path, fake_tools: FakeTools
) -> None:
    packets = "stream_index=3|pts_time=1\n" * 40 + "stream_index=5|pts_time=2\n" * 3
    fake_tools.set_scenario(ft.Scenario([ft.Rule(tool="ffprobe", actions=[ft.stdout(packets)])]))
    source = _source(tmp_path)
    source.subtitles[2].language = "eng"
    sources = _Sources(source)
    ctx = _context(tmp_path, sources, ffprobe=fake_tools.ffprobe)
    done = await _finish(ctx, analysis.start_subtitle_scan(ctx, tmp_path / FILE, [3, 5]))
    assert done.state is TaskState.DONE, done.error
    (stored,) = sources.stored
    assert [r.role for r in stored.subtitles[2].roles] == [TrackRole.FORCED]
    assert stored.subtitles[2].roles[0].detail == (
        "3 events, 8 % of the 40 events of track #3 in the same language (eng)"
    )


LOUDNORM = (
    "[Parsed_loudnorm_0 @ 0x1]\n{\n"
    '\t"input_i" : "-23.10",\n\t"input_tp" : "-5.20",\n\t"input_lra" : "6.70",\n'
    '\t"input_thresh" : "-33.40",\n\t"output_i" : "-24.00",\n\t"output_tp" : "-6.10",\n'
    '\t"output_lra" : "6.00",\n\t"output_thresh" : "-34.30",\n'
    '\t"normalization_type" : "dynamic",\n\t"target_offset" : "0.00"\n}\n'
)


async def test_loudness_measure(
    tmp_path: Path, fake_tools: FakeTools, progress: list[float | None]
) -> None:
    fake_tools.set_scenario(
        ft.Scenario([ft.Rule(tool="ffmpeg", argv_contains=["loudnorm=print_format=json"],
                             actions=[ft.progress(blocks=4, media_seconds=2.0,
                                                  na_fields=["bitrate", "total_size"]),
                                      ft.stderr(LOUDNORM)])])
    )  # fmt: skip
    ctx = _context(tmp_path, _Sources(_source(tmp_path)), ffmpeg=fake_tools.ffmpeg)
    info = analysis.start_loudness_scan(ctx, tmp_path / FILE, 2, start=1.0, duration=2.0)
    done = await _finish(ctx, info)
    assert done.state is TaskState.DONE, done.error
    assert done.kind == "loudness"
    assert ctx.tasks.value(done.id) == LoudnessMeasurement(
        path=tmp_path / FILE,
        stream_index=2,
        integrated=-23.1,
        true_peak=-5.2,
        lra=6.7,
        threshold=-33.4,
        start=1.0,
        duration=2.0,
    )
    assert progress[:2] == [None, 0.0]
    assert progress[-1] == 100.0
    (call,) = fake_tools.calls("ffmpeg")
    assert call[call.index("-ss") + 1] == "1"
    assert call[call.index("-t") + 1] == "2"


@pytest.mark.parametrize(
    ("actions", "message"),
    [
        ([ft.progress(blocks=2), ft.stderr("no block here\n")], "could not be measured: "),
        ([ft.progress(blocks=1, na_blocks=1, na_fields=["out_time_us"]), ft.stderr(LOUDNORM)],
         "has no audio in the part to measure"),
    ],
)  # fmt: skip
async def test_loudness_without_a_measurement_fails(
    tmp_path: Path, fake_tools: FakeTools, actions: Sequence[ft.Action], message: str
) -> None:
    fake_tools.set_scenario(ft.Scenario([ft.Rule(tool="ffmpeg", actions=list(actions))]))
    ctx = _context(tmp_path, _Sources(_source(tmp_path)), ffmpeg=fake_tools.ffmpeg)
    info = analysis.start_loudness_scan(ctx, tmp_path / FILE, 1, start=None, duration=None)
    _failed_with(await _finish(ctx, info), message)


async def test_the_scans_run_their_tools_with_the_tool_environment(
    tmp_path: Path, fake_tools: FakeTools, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every process of a scan gets ``ToolInfo.env`` (the bundled FFmpeg's environment, for
    example ``LIBVA_DRIVERS_PATH``)."""
    seen: list[tuple[str, Mapping[str, str] | None]] = []

    async def spy(argv: Sequence[str], **kwargs: Any) -> RunResult:
        extra_env = kwargs.get("extra_env")
        seen.append((" ".join(argv[1:]), extra_env))
        return await run_streaming(argv, **kwargs)

    monkeypatch.setattr("reframe.analysis.common.run_streaming", spy)
    fake_tools.set_scenario(
        ft.Scenario([ft.Rule(tool="ffprobe", actions=[ft.stdout(PACKETS)]),
                     ft.Rule(tool="ffmpeg", exit_code=1)])
    )  # fmt: skip
    source = _source(tmp_path)
    source.subtitles.append(
        SubtitleStream(index=6, type_index=3, codec="hdmv_pgs_subtitle", language="eng")
    )
    env = {"REFRAME_C10_TEST": "bundled"}
    ctx = _context(
        tmp_path, _Sources(source), ffmpeg=fake_tools.ffmpeg, ffprobe=fake_tools.ffprobe, env=env
    )
    path = tmp_path / FILE
    for info in (
        analysis.start_bitrate_scan(ctx, path, 1),  # ffprobe packet listing
        analysis.start_subtitle_scan(ctx, path, [4]),  # ffprobe packet count, VobSub decode
        analysis.start_subtitle_scan(ctx, path, [6]),  # ffmpeg PGS copy (fails here)
        analysis.start_loudness_scan(ctx, path, 1, start=None, duration=None),  # ffmpeg
    ):
        await _finish(ctx, info)
    assert len(seen) == 5, seen
    assert [extra for _, extra in seen] == [env] * 5, seen
