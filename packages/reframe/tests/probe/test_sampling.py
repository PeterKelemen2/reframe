"""The sampled bit rates of Matroska streams: the cluster sample, the estimate and the prober.

Synthetic files have known block bytes and cluster times, so the sample is checked exactly;
generated and real-tool files are checked against the exact block scan
(:mod:`reframe_testing.blockscan`).
"""

from __future__ import annotations

import asyncio
import json
import struct
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from reframe.models import BitrateInfo, BitrateSource, MediaSource, RoleEvidence, TrackRole
from reframe.probe import (
    ProbeError,
    ProbeErrorKind,
    Prober,
    ProbeTool,
    matroska,
    parse_ffprobe,
    sampling,
)
from reframe.probe import prober as prober_mod
from reframe.probe.cache import ProbeCache
from reframe.probe.folder import probe_folder
from reframe.probe.matroska import MatroskaFile, MatroskaTrack, read_matroska
from reframe.probe.sampling import ClusterSample, estimate_bitrates, sample_clusters
from reframe.tools import CancelToken
from reframe_testing import fake_tools as ft
from reframe_testing.blockscan import scan_blocks

from .test_matroska import element, header, track, tracks

_SEGMENT = 0x18538067
_CLUSTER = 0x1F43B675
_MB = 1024 * 1024

#: One cluster: its timestamp in ticks and the payload bytes of each block ``(track, bytes)``.
Cluster = tuple[int, Sequence[tuple[int, int]]]


def uint(element_id: int, value: int) -> bytes:
    return element(element_id, value.to_bytes(max(1, (value.bit_length() + 7) // 8), "big"))


def simple_block(track_number: int, size: int) -> bytes:
    return element(0xA3, bytes([0x80 | track_number, 0, 0, 0x80]) + b"\xab" * size)


def block_group(track_number: int, size: int) -> bytes:
    block = element(0xA1, bytes([0x80 | track_number, 0, 0, 0]) + b"\xcd" * size)
    return element(0xA0, block + uint(0xFB, 0))  # with a ReferenceBlock


def cluster(timestamp: int, blocks: Sequence[tuple[int, int]], *, groups: bool = False) -> bytes:
    make = block_group if groups else simple_block
    return element(_CLUSTER, uint(0xE7, timestamp) + b"".join(make(t, n) for t, n in blocks))


def info(scale: int | None, duration_ticks: float | None, *, float_size: int = 8) -> bytes:
    body = b"" if scale is None else uint(0x2AD7B1, scale)
    if duration_ticks is not None:
        body += element(0x4489, struct.pack(">d" if float_size == 8 else ">f", duration_ticks))
    return element(0x1549A966, body)


def mkv(
    clusters: Sequence[bytes],
    *,
    scale: int | None = 1_000_000,
    duration_ticks: float | None = None,
    trailer: bytes = b"",
    unknown_segment: bool = False,
) -> bytes:
    head = info(scale, duration_ticks) + tracks(track(1, 1), track(2, 2))
    return header() + element(
        _SEGMENT, head + b"".join(clusters) + trailer, unknown=unknown_segment
    )


def write(tmp_path: Path, data: bytes, name: str = "s.mkv") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def sample_of(path: Path, **kw: Any) -> ClusterSample | None:
    return sample_clusters(path, read_matroska(path), **kw)


def big_file(scale: int = 1_000_000, ticks_per_second: int = 1000) -> bytes:
    """120 clusters of 60 to 180 KB (each window holds a cluster start), more than the windows
    together, so the windows sample. Cluster ``i`` covers ``i % 3 + 1`` seconds; its blocks
    hold 60 KB of video and 1 KB of audio per second it covers."""
    clusters, t = [], 0
    for i in range(120):
        seconds = i % 3 + 1
        clusters.append(cluster(t, [(1, 60_000 * seconds), (2, 1_000 * seconds)]))
        t += seconds * ticks_per_second
    cues = element(0x1C53BB6B, b"\0" * 64)
    return mkv(clusters, scale=scale, duration_ticks=t, trailer=cues)


# --- the sample ---------------------------------------------------------------------------


def test_a_large_file_is_sampled_at_32_offsets_with_each_clusters_own_span(
    tmp_path: Path,
) -> None:
    """Pairing a cluster with the wrong span, or counting one twice, changes the rate."""
    path = write(tmp_path, big_file())
    assert path.stat().st_size > sampling.SAMPLES * sampling.WINDOW
    sample = sample_of(path)
    assert sample is not None
    assert sample.clusters == 32
    assert not sample.complete
    assert sample.track_bytes[1] * 8 / sample.seconds == pytest.approx(480_000)
    assert sample.track_bytes[2] * 8 / sample.seconds == pytest.approx(8_000)
    assert 32 <= sample.seconds <= 96


@pytest.mark.parametrize("scale", [100_000, 10_000_000])
def test_the_files_timestamp_scale_is_used(tmp_path: Path, scale: int) -> None:
    """The same file with another TimestampScale: 1 ms ticks assumed would be 10 times off."""
    path = write(tmp_path, big_file(scale=scale, ticks_per_second=1_000_000_000 // scale))
    sample = sample_of(path)
    assert sample is not None
    assert read_matroska(path).timestamp_scale == scale
    assert sample.track_bytes[2] * 8 / sample.seconds == pytest.approx(8_000)


def test_a_small_file_is_read_whole_and_the_last_cluster_ends_at_the_duration(
    tmp_path: Path,
) -> None:
    clusters = [cluster(0, [(1, 900), (2, 100)]), cluster(2000, [(1, 1800), (2, 200)])]
    path = write(tmp_path, mkv(clusters, duration_ticks=5000))
    sample = sample_of(path)
    assert sample == ClusterSample(2, 5.0, {1: 2700, 2: 300}, complete=True)
    assert sample.track_bytes == scan_blocks(path)


def test_an_element_between_two_clusters_does_not_end_the_first_at_the_duration(
    tmp_path: Path,
) -> None:
    void = element(0xEC, b"\0" * 100)
    clusters = [
        cluster(0, [(1, 100)]),
        void,
        cluster(1000, [(1, 100)]),
        cluster(2000, [(1, 100)]),
    ]
    path = write(tmp_path, mkv(clusters, duration_ticks=3000))
    assert sample_of(path) == ClusterSample(3, 3.0, {1: 300}, complete=True)


def test_each_cluster_counts_once_when_windows_overlap(tmp_path: Path) -> None:
    """The last cluster is damaged, so the small file is not read whole: the 32 windows of
    the windows pass all find the same two clusters."""
    clusters = [
        cluster(0, [(1, 100)]),
        cluster(1000, [(1, 100)]),
        element(_CLUSTER, uint(0xE7, 2000) + b"\xff" * 50),
    ]
    path = write(tmp_path, mkv(clusters, duration_ticks=3000))
    assert sample_of(path) == ClusterSample(2, 2.0, {1: 200}, complete=False)


def test_a_span_over_a_minute_is_not_used(tmp_path: Path) -> None:
    clusters = [cluster(0, [(1, 100)]), cluster(61_000, [(1, 100)])]
    path = write(tmp_path, mkv(clusters, duration_ticks=62_000))
    assert sample_of(path) == ClusterSample(1, 1.0, {1: 100}, complete=False)


def test_block_groups_count_and_a_four_byte_duration_is_read(tmp_path: Path) -> None:
    head = info(1_000_000, 3000.0, float_size=4) + tracks(track(1, 1), track(2, 2))
    body = cluster(0, [(1, 500), (2, 50)], groups=True)
    path = write(tmp_path, header() + element(_SEGMENT, head + body))
    assert read_matroska(path).duration == pytest.approx(3.0)
    assert sample_of(path) == ClusterSample(1, 3.0, {1: 500, 2: 50}, complete=True)


def test_a_file_of_few_large_clusters_is_walked_from_the_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No window lands on a cluster start: the clusters are read in a row instead."""
    clusters = [cluster(i * 5000, [(1, 3 * _MB), (2, 40_000)]) for i in range(4)]
    path = write(tmp_path, mkv(clusters, duration_ticks=20_000))
    monkeypatch.setattr(sampling, "WINDOW", 8)
    data = path.read_bytes()
    starts = [i for i in range(len(data)) if data.startswith(b"\x1f\x43\xb6\x75", i)]
    offsets = [int(len(data) * (0.02 + 0.96 * k / 31)) for k in range(32)]
    assert not any(0 <= start - offset < 8 for start in starts for offset in offsets)
    sample = sample_of(path)
    assert sample is not None
    assert (sample.clusters, sample.seconds, sample.complete) == (4, 20.0, True)
    assert sample.track_bytes == scan_blocks(path)


@pytest.mark.parametrize("small", [True, False])
def test_unknown_size_clusters_only_give_no_sample(tmp_path: Path, small: bool) -> None:
    count = 3 if small else 120
    clusters = [
        element(_CLUSTER, uint(0xE7, i * 1000) + simple_block(1, 100_000), unknown=True)
        for i in range(count)
    ]
    path = write(tmp_path, mkv(clusters, duration_ticks=count * 1000, unknown_segment=True))
    assert sample_of(path) is None


@pytest.mark.parametrize("small", [True, False])
def test_damaged_clusters_give_no_sample(tmp_path: Path, small: bool) -> None:
    """Each cluster's payload is garbage of the right length."""
    count = 3 if small else 120
    clusters = [element(_CLUSTER, bytes([0x5A]) * 100_000) for _ in range(count)]
    path = write(tmp_path, mkv(clusters, duration_ticks=count * 1000))
    assert sample_of(path) is None


@pytest.mark.parametrize(
    "body",
    [
        simple_block(1, 10) + uint(0xE7, 0),  # a block before the Timestamp
        uint(0xE7, 0) + element(0xA3, b"\x81\x00"),  # a block shorter than its header
        uint(0xE7, 0) + uint(0xE7, 5) + simple_block(1, 10),  # two Timestamps
        uint(0xE7, 0) + simple_block(1, 10)[:-3],  # the last child overruns the cluster
        simple_block(1, 10),  # no Timestamp
    ],
)
def test_a_cluster_that_does_not_parse_cleanly_is_not_used(tmp_path: Path, body: bytes) -> None:
    path = write(tmp_path, mkv([element(_CLUSTER, body)], duration_ticks=1000))
    assert sample_of(path) is None


def test_a_truncated_file_gives_what_its_whole_clusters_hold(tmp_path: Path) -> None:
    data = mkv([cluster(0, [(1, 1000)]), cluster(1000, [(1, 1000)])], duration_ticks=2000)
    path = write(tmp_path, data[:-500])
    assert sample_of(path) == ClusterSample(1, 1.0, {1: 1000}, complete=False)
    assert sample_clusters(path, MatroskaFile("matroska", timestamp_scale=0)) is None


@settings(max_examples=150, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.lists(st.tuples(st.integers(0, 2000), st.integers(0, 255)), max_size=20))
def test_a_corrupted_file_never_raises(tmp_path: Path, flips: list[tuple[int, int]]) -> None:
    clusters = [cluster(i * 1000, [(1, 300), (2, 20)]) for i in range(5)]
    data = bytearray(mkv(clusters, duration_ticks=5000))
    info = read_matroska(write(tmp_path, bytes(data), "fuzz.mkv"))
    for pos, value in flips:
        data[pos % len(data)] = value
    path = write(tmp_path, bytes(data), "fuzz.mkv")
    result = sample_clusters(path, info)
    assert result is None or (result.clusters > 0 and result.seconds > 0)


def test_a_cluster_over_the_size_cap_is_not_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write(tmp_path, big_file())
    monkeypatch.setattr(sampling, "MAX_CLUSTER", 50_000)
    assert sample_of(path) is None


def test_a_cluster_over_the_element_limit_is_not_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write(tmp_path, mkv([cluster(0, [(1, 10)] * 50)], duration_ticks=1000))
    info = read_matroska(path)
    assert sample_clusters(path, info) is not None
    monkeypatch.setattr(matroska, "MAX_ELEMENTS", 40)
    assert sample_clusters(path, info) is None


def test_the_read_budget_ends_the_sample(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = write(tmp_path, big_file())
    monkeypatch.setattr(sampling, "MAX_SAMPLE_READ", 10 * sampling.WINDOW)
    sample = sample_of(path)
    assert sample is not None
    assert 1 <= sample.clusters <= 10


def test_stop_ends_the_sample_before_the_next_read(tmp_path: Path) -> None:
    path = write(tmp_path, big_file())
    calls = [0]

    def stop() -> bool:
        calls[0] += 1
        return calls[0] > 3

    sample = sample_of(path, stop=stop)
    assert sample is not None
    assert 1 <= sample.clusters <= 3
    assert sample_of(path, stop=lambda: True) is None


# --- the estimate --------------------------------------------------------------------------


def _source(*streams: dict[str, Any], rate: int = 5_000_000) -> MediaSource:
    data = {
        "streams": list(streams),
        "format": {
            "format_name": "matroska,webm",
            "duration": "100",
            "size": str(rate * 100 // 8),
            "bit_rate": str(rate),
        },
    }
    return parse_ffprobe(data, Path("/m/x.mkv"))


def _video(index: int, **extra: Any) -> dict[str, Any]:
    return {"index": index, "codec_type": "video", "codec_name": "h264", "width": 64,
            "height": 64, **extra}  # fmt: skip


def _audio(index: int, channels: int = 2, **extra: Any) -> dict[str, Any]:
    return {"index": index, "codec_type": "audio", "codec_name": "aac", "channels": channels,
            "tags": {"language": "eng"}, **extra}  # fmt: skip


def _tracks(*kinds: str) -> MatroskaFile:
    return MatroskaFile(
        "matroska",
        tracks=[MatroskaTrack(number=n, kind=k) for n, k in enumerate(kinds, start=1)],  # type: ignore[arg-type]
    )


def _estimated(value: int, samples: int = 8) -> BitrateInfo:
    return BitrateInfo(value=value, source=BitrateSource.ESTIMATED, samples=samples)


def test_audio_per_second_and_the_single_video_by_subtraction() -> None:
    source = _source(
        _video(0),
        _audio(1),
        _audio(2, bit_rate="640000"),
        {"index": 3, "codec_type": "subtitle", "codec_name": "hdmv_pgs_subtitle"},
    )
    # 10 s sampled: audio 1 at 200 kb/s, subtitles at 40 kb/s, video bytes say 1 Mb/s.
    sample = ClusterSample(8, 10.0, {1: 1_250_000, 2: 250_000, 3: 800_000, 4: 50_000})
    assert estimate_bitrates(source, _tracks("video", "audio", "audio", "subtitle"), sample) == [
        1,
        0,
    ]
    assert source.audio[0].bitrate == _estimated(200_000)
    assert source.audio[1].bitrate.source is BitrateSource.STREAM
    assert source.video[0].bitrate == _estimated(5_000_000 - 200_000 - 640_000 - 40_000)


def test_a_track_the_file_has_but_ffprobe_does_not_map_is_subtracted() -> None:
    source = _source(_video(0))
    sample = ClusterSample(4, 10.0, {1: 100, 2: 125_000})
    estimate_bitrates(source, _tracks("video", "other"), sample)
    assert source.video[0].bitrate == _estimated(5_000_000 - 100_000, samples=4)


@pytest.mark.parametrize("complete", [True, False])
def test_two_videos_or_a_complete_sample_give_bytes_per_second(complete: bool) -> None:
    streams = [_video(0)] if complete else [_video(0), _video(1)]
    source = _source(*streams)
    kinds = ["video"] * len(streams)
    sample = ClusterSample(3, 2.0, {1: 250_000, 2: 500_000}, complete=complete)
    estimate_bitrates(source, _tracks(*kinds), sample)
    expected = [1_000_000, 2_000_000][: len(streams)]
    assert [v.bitrate for v in source.video] == [_estimated(v, samples=3) for v in expected]


def test_a_subtraction_at_or_below_zero_falls_back_to_bytes_per_second() -> None:
    source = _source(_video(0), _audio(1, bit_rate="6000000"))
    estimate_bitrates(source, _tracks("video", "audio"), ClusterSample(2, 1.0, {1: 1000}))
    assert source.video[0].bitrate == _estimated(8000, samples=2)


def test_no_file_rate_gives_bytes_per_second() -> None:
    source = _source(_video(0))
    source.container.bitrate = None
    source.container.size = None
    estimate_bitrates(source, _tracks("video"), ClusterSample(2, 1.0, {1: 1000}))
    assert source.video[0].bitrate == _estimated(8000, samples=2)


def test_a_track_without_sampled_bytes_stays_unknown() -> None:
    source = _source(_video(0, bit_rate="1000"), _audio(1))
    assert estimate_bitrates(source, _tracks("video", "audio"), ClusterSample(1, 1.0, {1: 9})) == []
    assert source.audio[0].bitrate == BitrateInfo()


def test_tracks_that_do_not_match_the_streams_give_no_estimate() -> None:
    source = _source(_video(0), _audio(1))
    sample = ClusterSample(1, 1.0, {1: 1000, 2: 1000})
    assert estimate_bitrates(source, _tracks("video", "audio", "audio"), sample) == []
    assert source.video[0].bitrate == source.audio[0].bitrate == BitrateInfo()


# --- the prober ----------------------------------------------------------------------------


def _probe_json(tmp_path: Path, path: Path, *streams: dict[str, Any], duration: float) -> Path:
    size = path.stat().st_size
    data = {
        "streams": list(streams),
        "format": {
            "filename": path.name,
            "format_name": "matroska,webm",
            "duration": f"{duration:.6f}",
            "size": str(size),
            "bit_rate": str(round(size * 8 / duration)),
        },
    }
    out = tmp_path / "probe.json"
    out.write_text(json.dumps(data), encoding="utf-8")
    return out


def _fake_prober(fake: ft.FakeTools, probe: Path) -> Prober:
    rule = ft.Rule(
        tool="ffprobe", argv_has=["-show_streams"], actions=[{"stdout_file": str(probe)}]
    )
    fake.set_scenario(ft.Scenario([rule]))
    return Prober(ProbeTool(str(fake.ffprobe), version="n-fake"))


def _two_audio_file(tmp_path: Path) -> tuple[Path, Path]:
    """A 5.1 and a 2.0 track in one language, neither with a rate: once the rates are known,
    the 2.0 one at a fifth of the rate is a possible commentary."""
    head = info(1_000_000, 4000) + tracks(track(1, 1), track(2, 2), track(3, 2))
    clusters = [cluster(i * 1000, [(1, 50_000), (2, 80_000), (3, 8_000)]) for i in range(4)]
    path = write(tmp_path, header() + element(_SEGMENT, head + b"".join(clusters)))
    probe = _probe_json(tmp_path, path, _video(0), _audio(1, channels=6), _audio(2), duration=4.0)
    return path, probe


@pytest.mark.anyio
async def test_the_prober_estimates_and_reruns_the_commentary_heuristic(
    fake_tools: ft.FakeTools, tmp_path: Path
) -> None:
    path, probe = _two_audio_file(tmp_path)
    source = await _fake_prober(fake_tools, probe).probe(path, use_cache=False)
    assert isinstance(source, MediaSource), source
    assert [a.bitrate for a in source.audio] == [_estimated(640_000, 4), _estimated(64_000, 4)]
    assert source.video[0].bitrate.source is BitrateSource.ESTIMATED
    assert source.video[0].bitrate.samples == 4
    assert [(r.role, r.evidence) for r in source.audio[1].roles] == [
        (TrackRole.COMMENTARY, RoleEvidence.HEURISTIC)
    ]
    assert source.warnings == []


@pytest.mark.anyio
async def test_the_prober_samples_only_matroska_with_a_missing_rate(
    fake_tools: ft.FakeTools, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Path] = []

    def spy(path: Path, info: MatroskaFile, **kw: Any) -> ClusterSample | None:
        calls.append(path)
        return None

    monkeypatch.setattr(sampling, "sample_clusters", spy)
    path, _ = _two_audio_file(tmp_path)
    known = _probe_json(
        tmp_path, path, _video(0, bit_rate="1"), _audio(1, 6, bit_rate="1"),
        _audio(2, bit_rate="1"), duration=4.0,
    )  # fmt: skip
    assert isinstance(await _fake_prober(fake_tools, known).probe(path), MediaSource)
    assert calls == []
    other = json.loads(known.read_text())
    other["format"]["format_name"] = "mov,mp4,m4a,3gp,3g2,mj2"
    other["streams"][1].pop("bit_rate")
    known.write_text(json.dumps(other), encoding="utf-8")
    source = await _fake_prober(fake_tools, known).probe(path, use_cache=False)
    assert isinstance(source, MediaSource)
    assert calls == []
    assert source.audio[0].bitrate == BitrateInfo()


@pytest.mark.anyio
async def test_a_sample_over_the_time_limit_leaves_the_rates_unknown(
    fake_tools: ft.FakeTools, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stops: list[Callable[[], bool]] = []
    release = threading.Event()

    def slow(path: Path, info: MatroskaFile, *, stop: Callable[[], bool]) -> None:
        stops.append(stop)
        release.wait(5)

    monkeypatch.setattr(sampling, "sample_clusters", slow)
    monkeypatch.setattr(prober_mod, "SAMPLE_TIMEOUT", 0.05)
    path, probe = _two_audio_file(tmp_path)
    try:
        source = await _fake_prober(fake_tools, probe).probe(path, use_cache=False)
        assert isinstance(source, MediaSource), source
        assert [a.bitrate for a in source.audio] == [BitrateInfo(), BitrateInfo()]
        assert source.warnings == []
        assert stops[0]()  # the worker is told to stop at its next read
    finally:
        release.set()


@pytest.mark.anyio
async def test_cancel_during_the_sample_cancels_the_probe(
    fake_tools: ft.FakeTools, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stops: list[Callable[[], bool]] = []
    started, release = threading.Event(), threading.Event()

    def slow(path: Path, info: MatroskaFile, *, stop: Callable[[], bool]) -> None:
        stops.append(stop)
        started.set()
        release.wait(60)

    monkeypatch.setattr(sampling, "sample_clusters", slow)
    path, probe = _two_audio_file(tmp_path)
    token = CancelToken()
    prober = _fake_prober(fake_tools, probe)
    try:
        task = asyncio.create_task(prober.probe(path, cancel=token, use_cache=False))
        await asyncio.to_thread(started.wait, 10)
        token.cancel()
        cancelled_at = time.monotonic()
        result = await asyncio.wait_for(task, 5)
        assert time.monotonic() - cancelled_at < 2  # the probe does not wait for the worker
        assert isinstance(result, ProbeError)
        assert result.kind is ProbeErrorKind.CANCELLED
        assert stops[0]()
    finally:
        release.set()


@pytest.mark.anyio
async def test_a_sample_that_cannot_read_the_file_leaves_the_rates_unknown(
    fake_tools: ft.FakeTools, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(path: Path, info: MatroskaFile, **kw: Any) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(sampling, "sample_clusters", fail)
    path, probe = _two_audio_file(tmp_path)
    source = await _fake_prober(fake_tools, probe).probe(path, use_cache=False)
    assert isinstance(source, MediaSource), source
    assert source.audio[0].bitrate == BitrateInfo()


@pytest.mark.anyio
@pytest.mark.parametrize("error", [OverflowError, ZeroDivisionError, ValueError])
async def test_an_error_in_the_sample_leaves_the_rates_unknown(
    fake_tools: ft.FakeTools, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: type
) -> None:
    def fail(path: Path, info: MatroskaFile, **kw: Any) -> None:
        raise error("a value the arithmetic cannot take")

    monkeypatch.setattr(sampling, "sample_clusters", fail)
    path, probe = _two_audio_file(tmp_path)
    source = await _fake_prober(fake_tools, probe).probe(path, use_cache=False)
    assert isinstance(source, MediaSource), source
    assert [a.bitrate for a in source.audio] == [BitrateInfo(), BitrateInfo()]
    assert source.video[0].bitrate == BitrateInfo()


def _huge_timestamp_scale_file(tmp_path: Path, name: str = "huge.mkv") -> Path:
    """A ``TimestampScale`` of 130 bytes and no ``Duration``: a float of the cluster spans
    overflows."""
    clusters = [cluster(i * 1000, [(1, 50_000), (2, 8_000)]) for i in range(4)]
    return write(tmp_path, mkv(clusters, scale=1 << (8 * 130 - 1)), name)


@pytest.mark.anyio
async def test_a_huge_timestamp_scale_keeps_the_rates_unknown(
    fake_tools: ft.FakeTools, tmp_path: Path
) -> None:
    path = _huge_timestamp_scale_file(tmp_path)
    probe = _probe_json(tmp_path, path, _video(0), _audio(1), duration=4.0)
    source = await _fake_prober(fake_tools, probe).probe(path, use_cache=False)
    assert isinstance(source, MediaSource), source
    assert [source.video[0].bitrate, source.audio[0].bitrate] == [BitrateInfo(), BitrateInfo()]


@pytest.mark.anyio
async def test_a_huge_timestamp_scale_does_not_fail_the_folder(
    fake_tools: ft.FakeTools, tmp_path: Path
) -> None:
    folder = tmp_path / "season"
    folder.mkdir()
    damaged = _huge_timestamp_scale_file(folder, "e01.mkv")
    good = write(folder, mkv([cluster(i * 1000, [(1, 50_000), (2, 8_000)]) for i in range(4)]),
                 "e02.mkv")  # fmt: skip
    probe = _probe_json(tmp_path, good, _video(0), _audio(1), duration=4.0)
    result = await probe_folder(_fake_prober(fake_tools, probe), folder)
    assert result.errors == []
    assert [s.ref.path.name for s in result.sources] == [damaged.name, good.name]
    assert result.sources[1].audio[0].bitrate.source is BitrateSource.ESTIMATED


def _first_sample_times_out(path: Path, info: MatroskaFile, *, stop: Callable[[], bool]) -> None:
    while not stop():
        time.sleep(0.01)


def _first_sample_cannot_read(path: Path, info: MatroskaFile, **kw: Any) -> None:
    raise OSError("the share went away")


def _first_sample_finds_no_cluster(path: Path, info: MatroskaFile, **kw: Any) -> None:
    return None


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("first", "sampled_again"),
    [
        (_first_sample_times_out, True),
        (_first_sample_cannot_read, True),
        (_first_sample_finds_no_cluster, False),
    ],
    ids=["timed-out", "unreadable", "no-cluster"],
)
async def test_a_sample_that_could_not_run_is_not_cached(
    fake_tools: ft.FakeTools,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    first: Callable[..., ClusterSample | None],
    sampled_again: bool,
) -> None:
    """A slow or unreachable share is not the file: the next probe samples again. A file
    without a usable cluster stays cached."""
    real = sampling.sample_clusters
    calls: list[str] = []

    def sample(path: Path, info: MatroskaFile, **kw: Any) -> ClusterSample | None:
        calls.append(path.name)
        return first(path, info, **kw) if len(calls) == 1 else real(path, info, **kw)

    monkeypatch.setattr(sampling, "sample_clusters", sample)
    monkeypatch.setattr(prober_mod, "SAMPLE_TIMEOUT", 0.2)
    path, probe = _two_audio_file(tmp_path)
    prober = _fake_prober(fake_tools, probe)
    prober.cache = ProbeCache(tmp_path / "cache")
    once = await prober.probe(path)
    assert isinstance(once, MediaSource), once
    assert once.audio[0].bitrate == BitrateInfo()
    again = await prober.probe(path)
    assert isinstance(again, MediaSource), again
    assert len(calls) == (2 if sampled_again else 1)
    assert (again.audio[0].bitrate.source is BitrateSource.ESTIMATED) is sampled_again


@pytest.mark.anyio
async def test_track_headers_that_timed_out_are_not_cached(
    fake_tools: ft.FakeTools, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = matroska.read_matroska
    release = threading.Event()
    calls: list[Path] = []

    def read(path: Path) -> MatroskaFile:
        calls.append(path)
        if len(calls) == 1:
            release.wait(5)
        return real(path)

    monkeypatch.setattr(matroska, "read_matroska", read)
    monkeypatch.setattr(prober_mod, "MATROSKA_TIMEOUT", 0.05)
    path, probe = _two_audio_file(tmp_path)
    prober = _fake_prober(fake_tools, probe)
    prober.cache = ProbeCache(tmp_path / "cache")
    try:
        once = await prober.probe(path)
    finally:
        release.set()
    assert isinstance(once, MediaSource), once
    assert once.audio[0].bitrate == BitrateInfo()
    again = await prober.probe(path)
    assert isinstance(again, MediaSource), again
    assert len(calls) == 2
    assert again.audio[0].bitrate.source is BitrateSource.ESTIMATED
