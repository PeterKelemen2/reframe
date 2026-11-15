"""Sampled bit rates and the stale-tag fix on real tool output: the fixtures, generated FFmpeg
and mkvmerge files, the recorded probes of two real mkvmerge files, and a probe without
``pymediainfo``."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from reframe.models import AudioStream, BitrateSource, MediaSource, VideoStream
from reframe.probe import Prober, ProbeTool
from reframe.probe.matroska import TrackKind, read_matroska, tracks_by_kind
from reframe.tools import discover_tools
from reframe_testing import fake_tools as ft
from reframe_testing import media
from reframe_testing.blockscan import scan_blocks
from reframe_testing.mkvtoolnix import mkvtoolnix_tool

from .test_matroska import element, header, track, tracks

pytestmark = pytest.mark.anyio

Media = Callable[[str], Path]
REAL = Path(__file__).resolve().parents[4] / "testdata" / "probes" / "real"
#: The plan's bounds for an estimate against the exact block scan.
VIDEO_TOLERANCE = 0.03
AUDIO_TOLERANCE = 0.12


@pytest.fixture
async def prober() -> Prober:
    return Prober((await discover_tools()).ffprobe)


async def _probe(prober: Prober, path: Path) -> MediaSource:
    source = await prober.probe(path, use_cache=False)
    assert isinstance(source, MediaSource), source
    return source


def check_against_the_block_scan(source: MediaSource, path: Path) -> int:
    """Every video and audio stream has a rate, and each estimate is within the plan's bounds of
    the exact bytes over the stream's duration. Returns the number of estimates."""
    exact = scan_blocks(path)
    kinds = tracks_by_kind(read_matroska(path))
    estimates = 0
    rated: list[tuple[TrackKind, Sequence[VideoStream | AudioStream], float]] = [
        ("video", source.video, VIDEO_TOLERANCE),
        ("audio", source.audio, AUDIO_TOLERANCE),
    ]
    for kind, streams, tolerance in rated:
        for stream, found in zip(streams, kinds[kind], strict=True):
            assert stream.bitrate.source is not BitrateSource.UNKNOWN, (path.name, stream.index)
            if stream.bitrate.source is not BitrateSource.ESTIMATED:
                continue
            seconds = stream.duration or source.container.duration
            assert seconds
            truth = exact[found.number or 0] * 8 / seconds
            assert stream.bitrate.value == pytest.approx(truth, rel=tolerance), (
                path.name,
                stream.index,
            )
            assert stream.bitrate.samples
            estimates += 1
    return estimates


MKV_FIXTURES = [
    "multitrack", "text-subs", "vobsub", "letterbox", "anamorphic", "interlaced", "vfr-mkv",
    "hdr10", "hdr10-4k", "chapters", "dts-hd-ma", "pgs", "season", "anime-s01", "anime-s02",
]  # fmt: skip


@pytest.mark.needs_ffmpeg
@pytest.mark.parametrize("name", MKV_FIXTURES)
async def test_every_fixture_stream_has_a_rate_close_to_the_block_scan(
    prober: Prober, fixture_media: Media, name: str
) -> None:
    found = fixture_media(name)
    files = sorted(found.glob("*.mkv")) if found.is_dir() else [found]
    estimates = 0
    for path in files:
        estimates += check_against_the_block_scan(await _probe(prober, path), path)
    assert estimates  # FFmpeg writes no statistics tags: every fixture needs the sample


def _generated(tmp_path: Path) -> Path:
    """20 s of 720p MPEG-2 at 6 Mb/s and AAC, in clusters of at most 0.5 s: larger than the
    windows together, so the windows sample."""
    ffmpeg = media.find_ffmpeg()
    assert ffmpeg is not None
    out = tmp_path / "generated.mkv"
    subprocess.run(
        [ffmpeg, "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=25:duration=20",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=20",
         "-c:v", "mpeg2video", "-b:v", "6M", "-g", "25", "-c:a", "aac", "-b:a", "160k",
         "-cluster_time_limit", "500", str(out)],
        check=True,
    )  # fmt: skip
    return out


@pytest.mark.needs_ffmpeg
async def test_a_multi_cluster_ffmpeg_file_is_sampled_at_offsets(
    prober: Prober, tmp_path: Path
) -> None:
    path = _generated(tmp_path)
    assert path.stat().st_size > 8 * 1024 * 1024
    source = await _probe(prober, path)
    assert check_against_the_block_scan(source, path) == 2
    assert 10 <= (source.video[0].bitrate.samples or 0) <= 32


def _remuxed(source: Path, out: Path) -> Path:
    subprocess.run(
        [mkvtoolnix_tool("mkvmerge"), "--quiet", "--timestamp-scale", "100000",
         "--disable-track-statistics-tags", "--cluster-length", "400ms", "-o", str(out),
         str(source)],
        check=True,
    )  # fmt: skip
    return out


@pytest.mark.needs_ffmpeg
@pytest.mark.needs_mkvtoolnix
async def test_a_non_default_timestamp_scale_from_mkvmerge(prober: Prober, tmp_path: Path) -> None:
    """mkvmerge ``--timestamp-scale 100000``: ticks of 0.1 ms, not 1 ms."""
    out = _remuxed(_generated(tmp_path), tmp_path / "scaled.mkv")
    assert read_matroska(out).timestamp_scale == 100_000
    source = await _probe(prober, out)
    assert check_against_the_block_scan(source, out) == 2


def test_content_encodings_are_read(tmp_path: Path) -> None:
    def encoding(*children: bytes) -> bytes:
        return element(0x6D80, element(0x6240, b"".join(children)))

    zlib = encoding(element(0x5034, element(0x4254, b"\x00")))
    implied = encoding(element(0x5033, b"\x00"))  # type 0 = compression, algorithm by default
    encrypted = encoding(element(0x5033, b"\x01"), element(0x5035, b""))
    entries = [
        element(0xAE, element(0xD7, bytes([n])) + element(0x83, b"\x11") + extra)
        for n, extra in enumerate([zlib, implied, encrypted, b""], start=1)
    ]
    path = tmp_path / "e.mkv"
    path.write_bytes(header() + element(0x18538067, tracks(track(9, 1), *entries)))
    found = read_matroska(path)
    assert [t.compressed for t in found.tracks] == [False, True, True, False, False]
    assert (found.timestamp_scale, found.duration) == (1_000_000, None)


@pytest.mark.needs_ffmpeg
@pytest.mark.needs_mkvtoolnix
def test_content_encodings_match_mkvmerge(fixture_media: Media, tmp_path: Path) -> None:
    out = tmp_path / "zlib.mkv"
    subprocess.run(
        [mkvtoolnix_tool("mkvmerge"), "--quiet", "--compression", "4:zlib", "-o", str(out),
         str(fixture_media("multitrack"))],
        check=True,
    )  # fmt: skip
    listed = subprocess.run(
        [mkvtoolnix_tool("mkvmerge"), "-J", str(out)], capture_output=True, text=True, check=True
    )
    theirs = [
        "content_encoding_algorithms" in t["properties"]
        for t in json.loads(listed.stdout)["tracks"]
    ]
    assert (
        [t.compressed for t in read_matroska(out).tracks]
        == theirs
        == [False] * 4
        + [
            True,
            False,
            False,
        ]
    )


# --- the recorded probes of two real mkvmerge files -------------------------------------------

#: name → (the video's BPS tag, the exact block scan of the real file in bit/s).
RECORDED = {
    "mkvmerge15-episode-pgs": (2_731_530, 2_731_531),
    "mkvmerge93-remux-pgs": (34_737_365, 34_737_365),
}


@pytest.mark.parametrize("name", sorted(RECORDED))
async def test_the_real_mkvmerge_files_keep_their_statistics_tags(
    fake_tools: ft.FakeTools, tmp_path: Path, name: str
) -> None:
    """mkvmerge counts a compressed PGS track's bytes before compression, so the tracks'
    NUMBER_OF_BYTES add up to more than the file; the tags are right all the same."""
    probe = json.loads((REAL / f"{name}.json").read_text(encoding="utf-8"))
    total = sum(int(s["tags"]["NUMBER_OF_BYTES"]) for s in probe["streams"])
    assert total > int(probe["format"]["size"])
    media_file = tmp_path / probe["format"]["filename"]
    shutil.copyfile(REAL / f"{name}.tracks.mkv", media_file)
    rule = ft.Rule(
        tool="ffprobe",
        argv_has=["-show_streams"],
        actions=[{"stdout_file": str(REAL / f"{name}.json")}],
    )
    fake_tools.set_scenario(ft.Scenario([rule]))
    source = await Prober(ProbeTool(str(fake_tools.ffprobe))).probe(media_file, use_cache=False)
    assert isinstance(source, MediaSource), source
    bps, exact = RECORDED[name]
    assert (source.video[0].bitrate.source, source.video[0].bitrate.value) == (
        BitrateSource.STATS_TAG,
        bps,
    )
    assert abs(bps - exact) <= 1
    assert all(a.bitrate.source is not BitrateSource.UNKNOWN for a in source.audio)
    assert not any("stale" in w for w in source.warnings)
    assert all(s.event_count is not None for s in source.subtitles)


# --- no pymediainfo ---------------------------------------------------------------------------

_WITHOUT_PYMEDIAINFO = """
import asyncio, importlib.abc, sys

class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] == "pymediainfo":
            raise ImportError("blocked for the test")
        return None

sys.meta_path.insert(0, Block())
import reframe
from reframe.probe import probe_file

source = asyncio.run(probe_file(sys.argv[1], sys.argv[2]))
print(type(source).__name__, source.video[0].bitrate.source.value, "pymediainfo" in sys.modules)
"""


@pytest.mark.needs_ffmpeg
async def test_import_and_probe_without_pymediainfo(fixture_media: Media) -> None:
    ffprobe = (await discover_tools()).ffprobe.path
    assert ffprobe is not None
    out = _without_pymediainfo(fixture_media("multitrack"), Path(ffprobe))
    assert out.split() == ["MediaSource", "estimated", "False"]


def _without_pymediainfo(path: Path, ffprobe: Path) -> str:
    done = subprocess.run(
        [sys.executable, "-c", _WITHOUT_PYMEDIAINFO, str(path), str(ffprobe)],
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout
