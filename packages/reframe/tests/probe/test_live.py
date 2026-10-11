"""Probing the generated fixtures with the real ffprobe (C-3).

Not exact snapshots (those use the recorded JSON in ``test_snapshots.py``): this must pass with
the pinned n9.0.2 build and the CI override build n8.1.3, so it checks the structure only.
The timing test measures the Q-3 budgets: one local file < 500 ms, a 24-file folder < 5 s.
"""

from __future__ import annotations

import shutil
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from reframe.models import (
    BitrateSource,
    FieldOrder,
    HdrFormat,
    MediaSource,
    Rational,
    RoleEvidence,
    TrackRole,
)
from reframe.probe import FolderProbeResult, ProbeCache, Prober, probe_folder
from reframe.tools import discover_tools

pytestmark = [pytest.mark.anyio, pytest.mark.needs_ffmpeg]

Media = Callable[[str], Path]


@pytest.fixture
async def prober() -> Prober:
    tools = await discover_tools()
    return Prober(tools.ffprobe)


async def probe(prober: Prober, path: Path) -> MediaSource:
    result = await prober.probe(path)
    assert isinstance(result, MediaSource), result
    return result


def roles(stream: object) -> list[tuple[TrackRole, RoleEvidence]]:
    return [(r.role, r.evidence) for r in getattr(stream, "roles", [])]


async def test_multitrack(prober: Prober, fixture_media: Media) -> None:
    source = await probe(prober, fixture_media("multitrack"))
    assert source.container.display_name == "MKV"
    assert source.container.title == "Reframe multi-track fixture"
    assert [v.display_codec for v in source.video] == ["H.264 Constrained Baseline"]
    assert [(a.language, a.title, a.display_codec, a.channels) for a in source.audio] == [
        ("jpn", "Japanese 5.1", "AC-3", 6),
        ("eng", "English Stereo", "AAC-LC", 2),
        ("eng", "Director's Commentary", "AAC-LC", 2),
    ]
    assert source.audio[0].disposition.default
    assert source.audio[0].bitrate.source is BitrateSource.STREAM
    assert roles(source.audio[2]) == [(TrackRole.COMMENTARY, RoleEvidence.FLAG)]
    assert [(s.title, s.display_codec) for s in source.subtitles] == [
        ("English", "SRT"),
        ("English SDH", "SRT"),
        ("Signs & Songs", "SRT"),
    ]
    assert roles(source.subtitles[1]) == [(TrackRole.SDH, RoleEvidence.FLAG)]
    assert roles(source.subtitles[2]) == [
        (TrackRole.FORCED, RoleEvidence.FLAG),
        (TrackRole.SIGNS, RoleEvidence.TITLE),
    ]
    assert source.warnings == []


async def test_text_subs_with_font(prober: Prober, fixture_media: Media) -> None:
    source = await probe(prober, fixture_media("text-subs"))
    assert [s.display_codec for s in source.subtitles] == ["SRT", "ASS"]
    assert [(a.filename, a.size, a.mimetype) for a in source.attachments] == [
        ("ReframeBox.ttf", 1672, "application/x-truetype-font")
    ]
    sidecar = await probe(prober, fixture_media("text-subs").with_name("text-subs.en.ass"))
    assert sidecar.container.display_name == "ASS"
    assert [s.display_codec for s in sidecar.subtitles] == ["ASS"]


async def test_vobsub(prober: Prober, fixture_media: Media) -> None:
    source = await probe(prober, fixture_media("vobsub"))
    assert [(s.language, s.display_codec, s.subtitle_kind) for s in source.subtitles] == [
        ("eng", "VobSub", "bitmap"),
        ("fre", "VobSub", "bitmap"),
    ]
    assert source.subtitles[1].disposition.forced
    assert (source.subtitles[0].width, source.subtitles[0].height) == (720, 480)


async def test_anamorphic(prober: Prober, fixture_media: Media) -> None:
    video = (await probe(prober, fixture_media("anamorphic"))).video[0]
    assert (video.width, video.height) == (720, 480)
    assert video.sar == Rational(num=32, den=27)
    assert video.dar == Rational(num=16, den=9)


async def test_interlaced(prober: Prober, fixture_media: Media) -> None:
    video = (await probe(prober, fixture_media("interlaced"))).video[0]
    assert video.field_order is FieldOrder.TOP_FIRST


@pytest.mark.parametrize("name", ["vfr", "vfr-mkv"])
async def test_vfr(prober: Prober, fixture_media: Media, name: str) -> None:
    video = (await probe(prober, fixture_media(name))).video[0]
    assert video.vfr
    assert video.frame_rate == Rational(num=120)


async def test_hdr10(prober: Prober, fixture_media: Media) -> None:
    video = (await probe(prober, fixture_media("hdr10"))).video[0]
    assert video.display_codec == "HEVC Main 10"
    assert video.bit_depth == 10
    assert video.hdr is not None
    assert video.hdr.formats == [HdrFormat.HDR10]
    assert video.hdr.mastering_display is not None
    assert video.hdr.mastering_display.max_luminance == pytest.approx(1000)
    assert video.hdr.content_light is not None
    assert video.hdr.content_light.max_cll == 1000


async def test_chapters(prober: Prober, fixture_media: Media) -> None:
    source = await probe(prober, fixture_media("chapters"))
    assert [c.title for c in source.chapters] == ["Opening", "Part One", "Part Two", "Credits"]
    assert source.chapters[1].start == pytest.approx(1.0)


async def test_letterbox_is_sdr(prober: Prober, fixture_media: Media) -> None:
    video = (await probe(prober, fixture_media("letterbox"))).video[0]
    assert video.hdr is None
    assert not video.vfr


async def test_season_folder(prober: Prober, fixture_media: Media) -> None:
    result = await probe_folder(prober, fixture_media("season"))
    assert result.errors == []
    names = [s.ref.path.name for s in result.sources]
    assert names == [f"Show.S01E{i:02d}.Title.mkv" for i in range(1, 13)]
    audio_counts = [len(s.audio) for s in result.sources]
    assert audio_counts[4] == 4
    assert audio_counts[8] == 2
    assert {audio_counts[i] for i in range(12) if i not in (4, 8)} == {3}
    e05 = result.sources[4].audio[3]
    assert (e05.display_codec, e05.title) == ("AC-3", "Commentary")
    assert roles(e05) == [(TrackRole.COMMENTARY, RoleEvidence.FLAG)]


async def test_probe_budgets(prober: Prober, fixture_media: Media, tmp_path: Path) -> None:
    """Q-3: one local file < 500 ms; a 24-file folder < 5 s (cold, no cache)."""
    single = fixture_media("multitrack")
    await probe(prober, single)  # warm up (MediaInfo library load, page cache)
    started = time.perf_counter()
    await probe(prober, single)
    one = time.perf_counter() - started

    season = fixture_media("season")
    folder = tmp_path / "season24"
    folder.mkdir()
    for i, src in enumerate(sorted(season.glob("*.mkv")) * 2, start=1):
        shutil.copyfile(src, folder / f"Show.S01E{i:02d}.mkv")
    started = time.perf_counter()
    result: FolderProbeResult = await probe_folder(prober, folder)
    folder_time = time.perf_counter() - started
    assert len(result.sources) == 24
    assert result.errors == []

    cached = Prober(prober.tool, cache=ProbeCache(tmp_path / "cache"))
    await probe_folder(cached, folder)
    started = time.perf_counter()
    await probe_folder(cached, folder)
    cached_time = time.perf_counter() - started

    print(
        f"\nQ-3 probe timing: one file {one * 1000:.0f} ms (budget 500 ms); "
        f"24-file folder {folder_time:.2f} s (budget 5 s); "
        f"cached folder {cached_time * 1000:.0f} ms"
    )
    assert one < 0.5
    assert folder_time < 5.0
