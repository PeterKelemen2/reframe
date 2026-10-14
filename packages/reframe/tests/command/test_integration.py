"""C-7 "Done when", part 2: plans run on fixture media with the real FFmpeg, and the outputs
are probed again (``reframe.probe``) to check the stream layout, languages, titles and flags.

Each test drafts a job for a generated fixture, builds the plan, runs every step as the
queue will (:func:`conftest.run_plan`: plan files written first, ``ArgTemplate`` values
taken from a real ``analyse`` step, ``.part`` renamed at the end) and checks the result.
The hardware encodes are ``needs_gpu`` (VAAPI and AMF on the development machine).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from reframe.command import build_plan, job_type
from reframe.definitions import load_definitions
from reframe.models import (
    AudioOutputTrack,
    AverageBitrate,
    ChapterRange,
    ChapterSettings,
    CropRect,
    CropSettings,
    DimensionSettings,
    EncodePlan,
    ExternalSubtitle,
    FilterConfig,
    FilterSettings,
    FitWithin,
    HdrFormat,
    JobSettings,
    MediaSource,
    SameAsSource,
    SubtitleOutputTrack,
    TagSettings,
    TimeRange,
    TrackMetadata,
)
from reframe.probe import Prober
from reframe_testing import media

from .conftest import caps, draft, ffprobe_json, run_plan, tools

pytestmark = [pytest.mark.needs_ffmpeg, pytest.mark.anyio]

Media = Callable[[str], Path]
FAST_X264 = {"encoder": "libx264", "preset": "ultrafast"}
FAST_X265 = {"encoder": "libx265", "preset": "ultrafast"}


@pytest.fixture(scope="module")
def tool_paths() -> dict[str, str]:
    ffmpeg, ffprobe = media.find_ffmpeg(), media.find_ffprobe()
    assert ffmpeg is not None
    assert ffprobe is not None
    paths = {"ffmpeg": ffmpeg, "ffprobe": ffprobe}
    mkvpropedit = shutil.which("mkvpropedit")
    if mkvpropedit is not None:
        paths["mkvpropedit"] = mkvpropedit
    return paths


@pytest.fixture
def prober(tool_paths: dict[str, str]) -> Prober:
    return Prober(tool_paths["ffprobe"], use_mediainfo=False)


async def probe(prober: Prober, path: Path) -> MediaSource:
    result = await prober.probe(path, use_cache=False)
    assert isinstance(result, MediaSource), result
    return result


async def source_of(prober: Prober, fixture: Path) -> MediaSource:
    return await probe(prober, fixture)


def folder_names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


def subtitle_text(ffmpeg: str, path: Path) -> str:
    """The first subtitle track as SRT text."""
    proc = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(path), "-map", "0:s:0", "-f", "srt", "-"],
        capture_output=True,
        check=True,
    )
    return proc.stdout.decode("utf-8")


def mkvmerge_languages(mkvmerge: str, path: Path) -> list[tuple[str | None, str | None]]:
    """``(language, language_ietf)`` of every track, as mkvmerge reads them."""
    proc = subprocess.run([mkvmerge, "-J", str(path)], capture_output=True, text=True, check=True)
    tracks = json.loads(proc.stdout)["tracks"]
    return [(t["properties"].get("language"), t["properties"].get("language_ietf")) for t in tracks]


def make_truehd_source(ffmpeg: str, path: Path) -> Path:
    """A 1 s H.264 + TrueHD stereo file (FFmpeg's TrueHD encoder is experimental)."""
    subprocess.run(
        [ffmpeg, "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:d=1",
         "-f", "lavfi", "-i", "sine=d=1:r=48000", "-c:v", "libx264", "-preset", "ultrafast",
         "-c:a", "truehd", "-strict", "-2", "-ac", "2", str(path)],
        check=True, capture_output=True,
    )  # fmt: skip
    return path


def make_71_source(ffmpeg: str, path: Path) -> Path:
    """A 1 s H.264 + FLAC 7.1 file at 44.1 kHz (one tone per channel)."""
    tones: list[str] = []
    for i in range(8):
        tones += ["-f", "lavfi", "-i", f"sine=frequency={220 + 110 * i}:sample_rate=44100:d=1"]
    join = "".join(f"[{1 + i}:a]" for i in range(8)) + "join=inputs=8:channel_layout=7.1[a]"
    subprocess.run(
        [ffmpeg, "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:d=1", *tones,
         "-filter_complex", join, "-map", "0:v", "-map", "[a]", "-c:v", "libx264",
         "-preset", "ultrafast", "-c:a", "flac", str(path)],
        check=True, capture_output=True,
    )  # fmt: skip
    return path


def plan_for(job: JobSettings, source: MediaSource, **kwargs: Any) -> EncodePlan:
    return build_plan(job, source, caps(**kwargs.pop("caps", {})), tools(), **kwargs)


def flags(stream: Any) -> set[str]:
    d = stream.disposition
    names = ("default", "forced", "comment", "hearing_impaired", "visual_impaired", "original")
    return {n for n in names if getattr(d, n)}


# --------------------------------------------------------------------------- Matroska


async def test_mkv_languages_titles_and_all_six_flags(
    fixture_media: Media, prober: Prober, tool_paths: dict[str, str], tmp_path: Path
) -> None:
    src = await source_of(prober, fixture_media("multitrack"))
    job = draft(src, output=tmp_path / "out.mkv", video=FAST_X264)
    job.dimensions = DimensionSettings(size=SameAsSource())
    a0, a1, a2 = job.audio
    a0.metadata = TrackMetadata(language="hu", name="Magyar 5.1", default=True, original=True)
    a1.metadata = TrackMetadata(language="de", name="", visual_impaired=True)
    a1.action, a1.mixdown = "encode", "mono"
    a2.metadata = TrackMetadata(commentary=True, hearing_impaired=True)
    s0, s1, s2 = job.subtitles
    s0.metadata = TrackMetadata(language="fr", forced=True, default=True)
    s1.metadata = TrackMetadata(name="SDH", hearing_impaired=True)
    s2.metadata = TrackMetadata()
    job.video.metadata = TrackMetadata(default=True, name="Main video")
    plan = plan_for(job, src)
    assert plan.job_type == "encode"
    run_plan(plan, tool_paths)
    out = await probe(prober, plan.output_final)
    assert [v.codec for v in out.video] == ["h264"]
    assert [(a.codec, a.channels) for a in out.audio] == [("aac", 6), ("aac", 1), ("aac", 2)]
    assert [s.codec for s in out.subtitles] == ["subrip"] * 3
    assert [(a.language, a.title) for a in out.audio] == [
        ("hun", "Magyar 5.1"),
        ("ger", None),
        ("eng", "Director's Commentary"),
    ]
    assert [(s.language, s.title) for s in out.subtitles] == [
        ("fre", "English"),
        ("eng", "SDH"),
        ("eng", "Signs & Songs"),
    ]
    assert out.video[0].title == "Main video"
    assert flags(out.video[0]) == {"default"}
    assert [flags(a) for a in out.audio] == [
        {"default", "original"},
        {"visual_impaired"},
        {"comment", "hearing_impaired"},
    ]
    assert [flags(s) for s in out.subtitles] == [{"default", "forced"}, {"hearing_impaired"}, set()]
    assert not plan.output_tmp.exists()


async def test_single_stream_gets_its_default_flag(
    fixture_media: Media, prober: Prober, tool_paths: dict[str, str], tmp_path: Path
) -> None:
    """FFmpeg's Matroska muxer sets no default flag on a single stream of a type by itself."""
    src = await source_of(prober, fixture_media("multitrack"))
    job = draft(src, output=tmp_path / "single.mkv", video=FAST_X264, subtitles=False)
    job.audio = [job.audio[1]]
    job.audio[0].metadata = TrackMetadata(default=True)
    run_plan(plan_for(job, src), tool_paths)
    out = await probe(prober, tmp_path / "single.mkv")
    assert [flags(a) for a in out.audio] == [{"default"}]


# --------------------------------------------------------------------------- MP4


async def test_mp4_iso639_2t_mov_text_hvc1(
    fixture_media: Media, prober: Prober, tool_paths: dict[str, str], tmp_path: Path
) -> None:
    src = await source_of(prober, fixture_media("multitrack"))
    job = draft(
        src, output=tmp_path / "out.m4v", container="mp4", video=FAST_X265,
        output_settings={"web_optimized": True},
    )  # fmt: skip
    job.audio[0].metadata = TrackMetadata(language="de", default=True)
    job.audio[0].action = "passthru"  # AC-3 can be copied into MP4
    job.subtitles[0].metadata = TrackMetadata(language="hu", name="Magyar", default=True)
    plan = plan_for(job, src)
    run_plan(plan, tool_paths)
    data = ffprobe_json(
        tool_paths["ffprobe"], tmp_path / "out.m4v", "-show_streams", "-show_format"
    )
    streams = data["streams"]
    assert data["format"]["format_name"].startswith("mov,mp4")
    assert [s["codec_name"] for s in streams] == ["hevc", "ac3", "aac", "aac", *["mov_text"] * 3]
    assert streams[0]["codec_tag_string"] == "hvc1"
    assert [s["tags"].get("language") for s in streams[1:]] == [
        "deu",
        "eng",
        "eng",
        "hun",
        "eng",
        "eng",
    ]
    # MP4 track titles read back as "name" (FFmpeg's mov demuxer), not "title".
    assert streams[4]["tags"].get("name") == "Magyar"
    out = await probe(prober, tmp_path / "out.m4v")
    assert out.subtitles[0].title == "Magyar"  # the probe reads "name" as the title (C-3)
    assert [a.language for a in out.audio] == ["deu", "eng", "eng"]
    assert flags(out.audio[2]) >= {"comment"}
    # +faststart: the moov box comes before mdat.
    head = (tmp_path / "out.m4v").read_bytes()[:4096]
    assert head.find(b"moov") != -1
    assert head.find(b"moov") < max(head.find(b"mdat"), 4096)


# --------------------------------------------------------------------------- 2-pass


@pytest.mark.parametrize(
    ("encoder", "extra"),
    [("libx264", {"preset": "ultrafast"}), ("libx265", {"preset": "ultrafast"}),
     ("libsvtav1", {"preset": "11"})],
)  # fmt: skip
async def test_two_pass_and_its_log_files(
    fixture_media: Media,
    prober: Prober,
    tool_paths: dict[str, str],
    tmp_path: Path,
    encoder: str,
    extra: dict[str, str],
) -> None:
    src = await source_of(prober, fixture_media("multitrack"))
    rc = AverageBitrate(kbps=300, two_pass=True, turbo_first_pass=encoder == "libx264")
    job = draft(src, output=tmp_path / "2pass.mkv", subtitles=False,
                video={"encoder": encoder, "rate_control": rc, **extra})  # fmt: skip
    plan = plan_for(job, src)
    assert [s.kind for s in plan.steps] == ["pass1", "pass2", "finalize"]
    result = run_plan(plan, tool_paths)
    # Every file the passes wrote is in temp_files (and nothing else is left in the folder).
    assert result.leftovers, "the passes wrote statistics files"
    assert folder_names(tmp_path) == ["2pass.mkv"]
    out = await probe(prober, tmp_path / "2pass.mkv")
    assert len(out.video) == 1
    assert len(out.audio) == 3


# --------------------------------------------------------------------------- loudness


async def test_two_pass_loudnorm_reaches_the_target(
    fixture_media: Media, prober: Prober, tool_paths: dict[str, str], tmp_path: Path
) -> None:
    src = await source_of(prober, fixture_media("multitrack"))
    job = draft(src, output=tmp_path / "loud.mkv", video=FAST_X264, subtitles=False)
    job.audio = job.audio[:2]
    job.audio[0].loudness = "ebu_r128"
    job.audio[0].mixdown = "dpl2"
    job.audio[1].loudness = "streaming"
    job.audio[1].gain = -3
    plan = plan_for(job, src)
    assert [s.kind for s in plan.steps] == ["analyse", "analyse", "encode", "finalize"]
    result = run_plan(plan, tool_paths)
    assert {"a0.input_i", "a0.target_offset", "a1.input_lra"} <= set(result.measured)
    out = await probe(prober, tmp_path / "loud.mkv")
    assert [(a.channel_layout, a.sample_rate) for a in out.audio] == [
        ("stereo", 48000),
        ("stereo", 48000),
    ]
    for index, target in ((0, -23.0), (1, -16.0)):
        measured = measure_loudness(tool_paths["ffmpeg"], tmp_path / "loud.mkv", index)
        assert abs(measured - target) < 1.0, (index, measured)


def measure_loudness(tool: str, path: Path, index: int) -> float:
    proc = subprocess.run(
        [tool, "-hide_banner", "-nostdin", "-i", str(path), "-map", f"0:a:{index}",
         "-af", "loudnorm=print_format=json", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return float(proc.stderr.split('"input_i" : "')[1].split('"')[0])


# --------------------------------------------------------------------------- audio snapping


async def test_impossible_audio_values_are_snapped(
    fixture_media: Media, prober: Prober, tool_paths: dict[str, str], tmp_path: Path
) -> None:
    """Decision 0024 item 4 on the multi-track fixture (AC-3 5.1, two AAC stereo tracks, all
    48 kHz). Unsnapped, FFmpeg refuses AC-3 at 96 kHz, Opus at 44.1 kHz and Opus stereo at
    600 kb/s (testdata/README.md, "Command builder (C-7)")."""
    src = await source_of(prober, fixture_media("multitrack"))
    job = draft(src, output=tmp_path / "snap.mkv", video=FAST_X264, subtitles=False)
    a0, a1, a2 = job.audio
    a0.encoder, a0.mixdown, a0.bitrate, a0.samplerate = "ac3", "7.1", 700, 96000
    a1.encoder, a1.mixdown = "ac3", "5.1"  # a stereo source: no upmix
    a2.encoder, a2.mixdown, a2.bitrate, a2.samplerate = "libopus", "dpl2", 600, 44100
    plan = plan_for(job, src)
    for written in ("-b:a:0 640k -ar:a:0 48000", "-b:a:1 224k", "-b:a:2 512k -ar:a:2 48000"):
        assert written in plan.display
    run_plan(plan, tool_paths)
    out = await probe(prober, tmp_path / "snap.mkv")
    assert [(a.codec, a.channels, a.sample_rate) for a in out.audio] == [
        ("ac3", 6, 48000),  # 7.1 asked of a 5.1 source: stays 5.1
        ("ac3", 2, 48000),  # 5.1 asked of a stereo source: stays stereo
        ("opus", 2, 48000),  # Dolby Pro Logic II of a stereo source: stays stereo
    ]
    assert [a.bitrate.value for a in out.audio[:2]] == [640_000, 224_000]


async def test_71_source_gets_the_layout_the_encoder_can_make(
    prober: Prober, tool_paths: dict[str, str], tmp_path: Path
) -> None:
    """AC-3 and E-AC-3 make 5.1 of 7.1, MP3 stereo; AAC keeps 7.1. The 44.1 kHz source rate
    is kept where the encoder has it and becomes 48 kHz for Opus. The bit rates are those of
    the 5.1 table: 700 → 640 kb/s, and E-AC-3's 5.1 default (FFmpeg's own is 448 kb/s)."""
    src = await probe(prober, make_71_source(tool_paths["ffmpeg"], tmp_path / "s71.mkv"))
    seven = src.audio[0]
    assert (seven.channels, seven.channel_layout, seven.sample_rate) == (8, "7.1", 44100)
    job = draft(src, output=tmp_path / "out71.mkv", video=FAST_X264, subtitles=False)
    job.audio = [
        AudioOutputTrack(source_stream=seven.index, encoder="ac3", mixdown="7.1", bitrate=700),
        AudioOutputTrack(source_stream=seven.index, encoder="eac3", mixdown="7.1"),
        AudioOutputTrack(source_stream=seven.index, encoder="libmp3lame"),
        AudioOutputTrack(source_stream=seven.index, encoder="aac"),
        AudioOutputTrack(source_stream=seven.index, encoder="libopus"),
    ]
    plan = plan_for(job, src)
    for written in (
        "-filter:a:0 aresample=out_chlayout=5.1 -filter:a:1 aresample=out_chlayout=5.1 "
        "-filter:a:2 aresample=out_chlayout=stereo -c:v:0",
        "-b:a:0 640k -ar:a:0 44100",
        "-b:a:1 1536k -ar:a:1 44100",
        "-ar:a:4 48000",
    ):
        assert written in plan.display
    run_plan(plan, tool_paths)
    out = await probe(prober, tmp_path / "out71.mkv")
    assert [(a.codec, a.channels, a.sample_rate) for a in out.audio] == [
        ("ac3", 6, 44100),
        ("eac3", 6, 44100),
        ("mp3", 2, 44100),
        ("aac", 8, 44100),
        ("opus", 8, 48000),
    ]
    # E-AC-3 at 44.1 kHz reads back as 1 535 231 b/s (whole frames of 44.1 kHz audio).
    rates = [a.bitrate.value for a in out.audio[:2]]
    assert rates == [pytest.approx(640_000, rel=0.001), pytest.approx(1_536_000, rel=0.001)]


# --------------------------------------------------------------------------- ranges, chapters


async def test_time_range_cuts_the_copied_chapters(
    fixture_media: Media, prober: Prober, tool_paths: dict[str, str], tmp_path: Path
) -> None:
    src = await source_of(prober, fixture_media("chapters"))
    job = draft(src, output=tmp_path / "range.mkv", video=FAST_X264)
    job.range = TimeRange(start=1.2, end=3.2)
    plan = plan_for(job, src)
    assert plan.expected_duration == pytest.approx(2.0)
    run_plan(plan, tool_paths)
    out = await probe(prober, tmp_path / "range.mkv")
    assert out.container.duration == pytest.approx(2.0, abs=0.05)
    assert [(c.title, round(c.start, 2), round(c.end, 2)) for c in out.chapters] == [
        ("Part One", 0.0, 1.3),
        ("Part Two", 1.3, 2.0),
    ]


async def test_chapter_range_with_renamed_chapters(
    fixture_media: Media, prober: Prober, tool_paths: dict[str, str], tmp_path: Path
) -> None:
    src = await source_of(prober, fixture_media("chapters"))
    job = draft(src, output=tmp_path / "chapters.mkv", video=FAST_X264)
    job.range = ChapterRange(start=2, end=3)
    job.chapters = ChapterSettings(names=["Intro", "Erste; Teil = 1", "Zweiter #2", "End"])
    plan = plan_for(job, src)
    assert len(plan.files) == 1
    run_plan(plan, tool_paths)
    assert not plan.files[0].path.exists()
    out = await probe(prober, tmp_path / "chapters.mkv")
    assert out.container.duration == pytest.approx(3.0, abs=0.05)
    assert [(c.title, round(c.start, 2), round(c.end, 2)) for c in out.chapters] == [
        ("Erste; Teil = 1", 0.0, 1.5),
        ("Zweiter #2", 1.5, 3.0),
    ]


async def test_generated_chapters_and_tags(
    fixture_media: Media, prober: Prober, tool_paths: dict[str, str], tmp_path: Path
) -> None:
    src = await source_of(prober, fixture_media("multitrack"))
    job = draft(src, output=tmp_path / "gen.mkv", video=FAST_X264, subtitles=False)
    job.chapters = ChapterSettings(generate_every=1 / 60)  # every second
    job.tags = TagSettings(title="{file_name} ({resolution})", director="Somebody", plot="A plot")
    job.output.passthru_metadata = False
    run_plan(plan_for(job, src), tool_paths)
    out = await probe(prober, tmp_path / "gen.mkv")
    assert [c.title for c in out.chapters] == ["Chapter 1", "Chapter 2", "Chapter 3", "Chapter 4"]
    tags = {k.lower(): v for k, v in out.container.tags.items()}
    assert out.container.title == "multitrack (320x180)"
    assert tags["album_artist"] == "Somebody"
    assert tags["synopsis"] == "A plot"


# --------------------------------------------------------------------------- burn-in


def frame_hashes(tool: str, path: Path) -> list[str]:
    proc = subprocess.run(
        [tool, "-v", "error", "-i", str(path), "-map", "0:v:0", "-f", "framemd5", "-"],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return [line.rsplit(",", 1)[-1].strip() for line in proc.stdout.splitlines() if line[:1] != "#"]


def burned_vs_plain(
    src: MediaSource, job: JobSettings, tool_paths: dict[str, str], tmp_path: Path
) -> tuple[list[str], list[str]]:
    burned = job.model_copy(deep=True)
    plain = job.model_copy(deep=True)
    plain.subtitles = [s for s in plain.subtitles if s.action != "burn"]
    plain.output.path = tmp_path / "plain.mkv"
    run_plan(plan_for(burned, src), tool_paths)
    run_plan(plan_for(plain, src), tool_paths)
    assert burned.output.path is not None
    return (
        frame_hashes(tool_paths["ffmpeg"], burned.output.path),
        frame_hashes(tool_paths["ffmpeg"], tmp_path / "plain.mkv"),
    )


async def test_burn_in_text_subtitles_with_a_range(
    fixture_media: Media, prober: Prober, tool_paths: dict[str, str], tmp_path: Path
) -> None:
    """ASS from the source (its Reframe Box font is an attachment). With a range from 1.0 s,
    output frame N must equal frame N + 25 of the same burn-in without a range (lossless
    x264): the subtitles keep the source's timing although ``-ss`` starts the frames at 0."""
    src = await source_of(prober, fixture_media("text-subs"))
    video = {**FAST_X264, "rate_control": {"mode": "quality", "value": 0}}
    job = draft(src, output=tmp_path / "full.mkv", video=video, subtitles=False)
    job.dimensions = DimensionSettings(size=SameAsSource())
    ass = next(s for s in src.subtitles if s.codec == "ass")
    job.subtitles = [SubtitleOutputTrack(source=ass.index, action="burn")]
    burned, plain = burned_vs_plain(src, job, tool_paths, tmp_path)
    assert sum(b != p for b, p in zip(burned, plain, strict=True)) > 50, "subtitles are burned in"
    ranged = job.model_copy(deep=True)
    ranged.range = TimeRange(start=1.0, end=3.5)
    ranged.output.path = tmp_path / "ranged.mkv"
    run_plan(plan_for(ranged, src), tool_paths)
    part = frame_hashes(tool_paths["ffmpeg"], tmp_path / "ranged.mkv")
    assert len(part) == 63  # 2.5 s at 25 fps: the frame at 2.48 s starts inside the range
    assert part == burned[25 : 25 + len(part)]


async def test_burn_in_bitmap_subtitles(
    fixture_media: Media, prober: Prober, tool_paths: dict[str, str], tmp_path: Path
) -> None:
    src = await source_of(prober, fixture_media("vobsub"))
    job = draft(src, output=tmp_path / "vob.mkv", video=FAST_X264, subtitles=False)
    job.dimensions = DimensionSettings(
        size=FitWithin(width=360, height=240),
        crop=CropSettings(mode="manual", rect=CropRect(top=0, bottom=40, left=0, right=0)),
    )
    job.subtitles = [SubtitleOutputTrack(source=src.subtitles[0].index, action="burn")]
    burned, plain = burned_vs_plain(src, job, tool_paths, tmp_path)
    assert any(b != p for b, p in zip(burned, plain, strict=True))
    out = await probe(prober, tmp_path / "vob.mkv")
    assert not out.subtitles


# --------------------------------------------------------------------------- HDR


async def test_hdr10_metadata_passes_through_x265(
    fixture_media: Media, prober: Prober, tool_paths: dict[str, str], tmp_path: Path
) -> None:
    src = await source_of(prober, fixture_media("hdr10"))
    job = draft(src, output=tmp_path / "hdr.mkv", video={**FAST_X265, "bit_depth": 10})
    plan = plan_for(job, src)
    assert "master-display=G(13250,34500)" in plan.display
    run_plan(plan, tool_paths)
    out = await probe(prober, tmp_path / "hdr.mkv")
    v, s = out.video[0], src.video[0]
    assert v.hdr is not None
    assert s.hdr is not None
    assert v.hdr.formats == [HdrFormat.HDR10]
    assert v.hdr.mastering_display == s.hdr.mastering_display
    assert v.hdr.content_light == s.hdr.content_light
    colour = (v.color.primaries, v.color.transfer, v.color.matrix)
    assert colour == ("bt2020", "smpte2084", "bt2020nc")


def libplacebo_runs(tool: str) -> bool:
    proc = subprocess.run(
        [tool, "-v", "error", "-f", "lavfi", "-i", "color=size=64x64", "-frames:v", "1",
         "-vf", "libplacebo", "-f", "null", "-"],
        capture_output=True, check=False,
    )  # fmt: skip
    return proc.returncode == 0


@pytest.mark.parametrize("libplacebo", [False, True])
async def test_hdr_to_sdr_tone_mapping(
    fixture_media: Media,
    prober: Prober,
    tool_paths: dict[str, str],
    tmp_path: Path,
    libplacebo: bool,
) -> None:
    """``libplacebo`` is chosen only when the capability snapshot says it runs (it needs a
    Vulkan driver: the libplacebo case is skipped where the real run test fails)."""
    if libplacebo and not libplacebo_runs(tool_paths["ffmpeg"]):
        pytest.skip("libplacebo does not run here (no Vulkan driver)")
    src = await source_of(prober, fixture_media("hdr10"))
    job = draft(src, output=tmp_path / "sdr.mkv", video=FAST_X264)
    job.filters = FilterSettings({"tonemap": FilterConfig()})
    plan = plan_for(job, src, caps={"libplacebo": libplacebo})
    assert ("libplacebo=" in plan.display) is libplacebo
    run_plan(plan, tool_paths)
    out = await probe(prober, tmp_path / "sdr.mkv")
    v = out.video[0]
    assert v.hdr is None, "no HDR metadata in the SDR output"
    assert (v.color.primaries, v.color.transfer, v.color.matrix) == ("bt709", "bt709", "bt709")
    assert v.pix_fmt == "yuv420p"


# --------------------------------------------------------------------------- remux


async def test_remux_mkv_to_mp4(
    fixture_media: Media, prober: Prober, tool_paths: dict[str, str], tmp_path: Path
) -> None:
    src = await source_of(prober, fixture_media("multitrack"))
    job = draft(src, output=tmp_path / "remux.mp4", container="mp4", audio="passthru")
    job.video.passthrough = True
    assert job_type(job, src)[0] == "remux"
    plan = plan_for(job, src)
    assert plan.job_type == "remux"
    run_plan(plan, tool_paths)
    out = await probe(prober, tmp_path / "remux.mp4")
    assert [v.codec for v in out.video] == ["h264"]
    assert [a.codec for a in out.audio] == ["ac3", "aac", "aac"]
    assert [s.codec for s in out.subtitles] == ["mov_text"] * 3
    assert [a.language for a in out.audio] == ["jpn", "eng", "eng"]


# --------------------------------------------------------------------------- external subtitles


async def test_external_subtitles_with_offset_and_charset(
    fixture_media: Media, prober: Prober, tool_paths: dict[str, str], tmp_path: Path
) -> None:
    fixture = fixture_media("text-subs")
    src = await source_of(prober, fixture)
    srt = fixture.with_name("text-subs.en.srt")
    latin2 = tmp_path / "hungarian.srt"
    latin2.write_bytes(srt.read_text(encoding="utf-8").encode("iso-8859-2"))
    job = draft(src, output=tmp_path / "ext.mkv", video=FAST_X264, subtitles=False)
    job.subtitles = [
        SubtitleOutputTrack(
            source=ExternalSubtitle(path=latin2, offset_ms=500, charset="ISO-8859-2"),
            metadata=TrackMetadata(language="hu", name="Külső", default=True),
        )
    ]
    run_plan(plan_for(job, src), tool_paths)
    out = await probe(prober, tmp_path / "ext.mkv")
    assert [(s.language, s.title, s.codec) for s in out.subtitles] == [("hun", "Külső", "subrip")]
    text = subtitle_text(tool_paths["ffmpeg"], tmp_path / "ext.mkv")
    assert "00:00:01,000 --> 00:00:02,300" in text  # 0.5 s + 0.5 s offset
    assert "Árvíztűrő tükörfúrógép" in text  # decoded from ISO-8859-2, written as UTF-8


# --------------------------------------------------------------------------- LanguageIETF


async def test_bcp47_language_goes_through_mkvpropedit(
    fixture_media: Media, prober: Prober, tool_paths: dict[str, str], tmp_path: Path
) -> None:
    mkvmerge = shutil.which("mkvmerge")
    if "mkvpropedit" not in tool_paths or mkvmerge is None:
        pytest.skip("needs mkvpropedit and mkvmerge")
    src = await source_of(prober, fixture_media("multitrack"))
    job = draft(src, output=tmp_path / "ietf.mkv", video=FAST_X264, subtitles=False)
    job.audio[1].metadata = TrackMetadata(language="pt-BR")
    plan = plan_for(job, src)
    assert [s.kind for s in plan.steps] == ["encode", "mkvpropedit", "finalize"]
    run_plan(plan, tool_paths)
    assert mkvmerge_languages(mkvmerge, tmp_path / "ietf.mkv")[2] == ("por", "pt-BR")
    out = await probe(prober, tmp_path / "ietf.mkv")
    assert out.audio[1].language == "por"


# --------------------------------------------------------------------------- more plan shapes


async def test_every_filter_on_an_untagged_interlaced_source(
    fixture_media: Media, prober: Prober, tool_paths: dict[str, str], tmp_path: Path
) -> None:
    """All filters in one chain; Colorspace (zscale) needs ``setparams`` on this untagged
    source (``zscale`` fails with "no path between colorspaces" otherwise)."""
    src = await source_of(prober, fixture_media("interlaced"))
    assert src.video[0].color.primaries is None
    job = draft(src, output=tmp_path / "filters.mkv", video=FAST_X264)
    job.filters = FilterSettings(
        {
            "detelecine": FilterConfig(),
            "interlace_detection": FilterConfig(),
            "deinterlace": FilterConfig(),
            "denoise": FilterConfig(tune="animation"),
            "deblock": FilterConfig(),
            "custom": FilterConfig(custom="eq=gamma=1.1"),
            "colorspace": FilterConfig(preset="bt709"),
            "sharpen": FilterConfig(implementation="cas"),
            "chroma_smooth": FilterConfig(tune="wide"),
            "grayscale": FilterConfig(),
        }
    )
    plan = plan_for(job, src)
    assert "setparams=" in plan.display
    run_plan(plan, tool_paths)
    v = (await probe(prober, tmp_path / "filters.mkv")).video[0]
    assert (v.color.primaries, v.color.transfer, v.color.matrix) == ("bt709", "bt709", "bt709")
    assert v.field_order.value == "progressive"


async def test_frame_rate_modes(
    fixture_media: Media, prober: Prober, tool_paths: dict[str, str], tmp_path: Path
) -> None:
    """The VFR fixture: 1 s each at 24, 30 and 60 fps (average 38)."""
    src = await source_of(prober, fixture_media("vfr"))
    constant = draft(src, output=tmp_path / "cfr.mkv", video={**FAST_X264,
                     "framerate_mode": "constant"})  # fmt: skip
    thirty = {"num": 30, "den": 1}
    peak = draft(src, output=tmp_path / "peak.mp4", container="mp4",
                 video={**FAST_X264, "framerate_mode": "peak", "framerate": thirty})  # fmt: skip
    for job in (constant, peak):
        run_plan(plan_for(job, src), tool_paths)
    cfr = ffprobe_json(tool_paths["ffprobe"], tmp_path / "cfr.mkv", "-show_streams")
    assert cfr["streams"][0]["r_frame_rate"] == "38/1"
    capped = ffprobe_json(tool_paths["ffprobe"], tmp_path / "peak.mp4", "-show_streams")
    assert capped["streams"][0]["avg_frame_rate"] == "30/1"


async def test_truehd_passthru_into_mp4(
    prober: Prober, tool_paths: dict[str, str], tmp_path: Path
) -> None:
    """TrueHD in MP4 needs ``-strict -2`` (the muxer refuses it otherwise)."""
    source_file = make_truehd_source(tool_paths["ffmpeg"], tmp_path / "truehd.mkv")
    src = await probe(prober, source_file)
    job = draft(src, output=tmp_path / "out.mp4", container="mp4", audio="passthru")
    job.video.passthrough = True
    run_plan(plan_for(job, src), tool_paths)
    out = await probe(prober, tmp_path / "out.mp4")
    assert [a.codec for a in out.audio] == ["truehd"]


async def test_webm_vp9_opus_webvtt(
    fixture_media: Media, prober: Prober, tool_paths: dict[str, str], tmp_path: Path
) -> None:
    src = await source_of(prober, fixture_media("multitrack"))
    job = draft(src, output=tmp_path / "out.webm", container="webm", audio_encoder="libopus",
                video={"encoder": "libvpx-vp9", "preset": "veryfast"})  # fmt: skip
    run_plan(plan_for(job, src), tool_paths)
    out = await probe(prober, tmp_path / "out.webm")
    assert [v.codec for v in out.video] == ["vp9"]
    assert [(a.codec, a.channels) for a in out.audio] == [("opus", 6), ("opus", 2), ("opus", 2)]
    assert [s.codec for s in out.subtitles] == ["webvtt"] * 3
    assert [flags(a) for a in out.audio] == [{"default"}, set(), set()]  # WebM: no comment flag


@pytest.mark.parametrize(
    ("encoder", "settings"),
    [
        ("libx264", {"preset": "veryfast", "tune": "animation", "fast_decode": True,
                     "advanced": {"psy-rd": 0.8, "deblock-alpha": -1, "bframes": 5,
                                  "aq-mode": "2", "aq-strength": 1.2},
                     "custom_params": "nr=100"}),
        ("libx265", {"preset": "ultrafast", "tune": "grain",
                     "advanced": {"deblock-tc": -2, "sao": False, "rd": 4, "psy-rdoq": 2.0},
                     "custom_params": "limit-tu=4"}),
        ("libsvtav1", {"preset": "11", "tune": "0", "level": "4.1", "fast_decode": True,
                       "advanced": {"film-grain": 8, "film-grain-denoise": False,
                                    "enable-qm": True, "qm-min": 2}}),
    ],
)  # fmt: skip
async def test_encoder_options_are_accepted(
    fixture_media: Media,
    prober: Prober,
    tool_paths: dict[str, str],
    tmp_path: Path,
    encoder: str,
    settings: dict[str, Any],
) -> None:
    """The libraries do not fail on a bad parameter; they log it (testdata/README.md
    "Encoder definitions (C-6)"). So the log must be clean."""
    src = await source_of(prober, fixture_media("multitrack"))
    job = draft(src, output=tmp_path / "opts.mkv", subtitles=False,
                video={"encoder": encoder, **settings})  # fmt: skip
    job.audio = []
    result = run_plan(plan_for(job, src), tool_paths)
    log = "\n".join(result.stderr)
    for bad in ("Error parsing option", "Unknown option", "Invalid value", "bad value"):
        assert bad not in log
    assert len((await probe(prober, tmp_path / "opts.mkv")).video) == 1


async def test_hdr10_metadata_passes_through_svtav1(
    fixture_media: Media, prober: Prober, tool_paths: dict[str, str], tmp_path: Path
) -> None:
    src = await source_of(prober, fixture_media("hdr10"))
    job = draft(src, output=tmp_path / "av1.mkv",
                video={"encoder": "libsvtav1", "preset": "11", "bit_depth": 10})  # fmt: skip
    plan = plan_for(job, src)
    assert "mastering-display=G(0.265,0.69)" in plan.display
    result = run_plan(plan, tool_paths)
    assert "Error parsing option" not in "\n".join(result.stderr)
    v = (await probe(prober, tmp_path / "av1.mkv")).video[0]
    assert v.hdr is not None
    assert v.hdr.formats == [HdrFormat.HDR10]
    assert src.video[0].hdr is not None
    assert v.hdr.content_light == src.video[0].hdr.content_light


# --------------------------------------------------------------------------- hardware


def hardware_works(tool: str, encoder: str, bit_depth: int) -> bool:
    """The encoder's own test encode (C-4's command) runs on this machine."""
    enc = load_definitions().video_encoders[encoder]
    pix_fmt = enc.pix_fmts[str(bit_depth)]  # type: ignore[index]
    setup = enc.hardware_setup
    values = {"{vaapi_device}": "/dev/dri/renderD128", "{sw_pix_fmt}": pix_fmt}

    def fill(text: str) -> str:
        for key, value in values.items():
            text = text.replace(key, value)
        return text

    init = [fill(a) for a in setup.init_args] if setup else []
    if setup is not None and setup.filter_tail:
        frames = ["-vf", ",".join(fill(f) for f in setup.filter_tail)]
    else:
        frames = ["-pix_fmt", pix_fmt]
    proc = subprocess.run(
        [tool, "-v", "error", *init, "-f", "lavfi", "-i", "color=size=320x180", "-frames:v", "3",
         *frames, "-c:v", encoder, "-f", "null", "-"],
        capture_output=True, check=False,
    )  # fmt: skip
    return proc.returncode == 0


@pytest.mark.needs_gpu
@pytest.mark.parametrize(
    ("encoder", "fixture", "bit_depth"),
    [("h264_vaapi", "multitrack", 8), ("hevc_vaapi", "hdr10", 10), ("av1_vaapi", "anamorphic", 8),
     ("hevc_amf", "hdr10", 10), ("h264_amf", "multitrack", 8)],
)  # fmt: skip
async def test_hardware_encode(
    fixture_media: Media,
    prober: Prober,
    tool_paths: dict[str, str],
    tmp_path: Path,
    encoder: str,
    fixture: str,
    bit_depth: int,
) -> None:
    if not hardware_works(tool_paths["ffmpeg"], encoder, bit_depth):
        pytest.skip(f"{encoder} ({bit_depth}-bit) does not work on this machine")
    enc = load_definitions().video_encoders[encoder]
    src = await source_of(prober, fixture_media(fixture))
    job = draft(src, output=tmp_path / "hw.mkv", video={"encoder": encoder, "bit_depth": bit_depth})
    plan = plan_for(job, src)
    if enc.hardware_setup is not None and enc.hardware_setup.init_args:
        assert "-init_hw_device" in plan.steps[0].argv
    run_plan(plan, tool_paths)
    out = await probe(prober, tmp_path / "hw.mkv")
    assert [v.codec for v in out.video] == [enc.codec]
    assert out.video[0].bit_depth == bit_depth
    assert len(out.audio) == len(src.audio)
    if fixture == "hdr10":
        hdr = out.video[0].hdr
        assert hdr is not None
        assert hdr.formats == [HdrFormat.HDR10]
