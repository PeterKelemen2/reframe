"""Every fixture has what the plan's "Test media" table promises (checked with ffprobe).

Also records FFmpeg behaviour that the plan did not know (see testdata/README.md,
"Verified tool behaviour"). If one of those tests fails after an FFmpeg update, update the
README and tell the authors of C-3 / C-7.
"""

from __future__ import annotations

import itertools
import re
import subprocess
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from reframe_testing import media

pytestmark = pytest.mark.needs_ffmpeg

Probe = dict[str, Any]


@pytest.fixture(scope="session")
def all_media() -> Path:
    media.generate()
    return media.DEFAULT_MEDIA_DIR


@pytest.fixture(scope="session")
def probe(all_media: Path) -> Callable[..., Probe]:
    cache: dict[tuple[str, tuple[str, ...]], Probe] = {}

    def get(rel: str, *extra: str) -> Probe:
        key = (rel, extra)
        if key not in cache:
            cache[key] = media.probe(all_media / rel, *extra)
        return cache[key]

    return get


def streams(p: Probe, kind: str) -> list[dict[str, Any]]:
    return [s for s in p["streams"] if s["codec_type"] == kind]


def flags(s: dict[str, Any]) -> set[str]:
    return {k for k, v in s["disposition"].items() if v}


def tags(s: dict[str, Any]) -> dict[str, str]:
    t: dict[str, str] = s.get("tags", {})
    return t


def layout(p: Probe) -> list[tuple[str, str | None, str | None, frozenset[str]]]:
    return [
        (s["codec_type"], tags(s).get("language"), tags(s).get("title"), frozenset(flags(s)))
        for s in p["streams"]
    ]


def test_fixture_media_fixture_returns_paths(fixture_media: Callable[[str], Path]) -> None:
    assert fixture_media("multitrack").name == "multitrack.mkv"
    assert fixture_media("season").is_dir()
    assert fixture_media("text-subs-srt").read_text(encoding="utf-8").startswith("1\n")


def test_all_fixtures_are_small_and_short(all_media: Path, probe: Callable[..., Probe]) -> None:
    for recipe in media.build_recipes().values():
        for output in recipe.outputs:
            if not output.endswith((".mkv", ".mp4")):
                continue
            p = probe(output)
            assert float(p["format"]["duration"]) <= 5.1, output
            assert (all_media / output).stat().st_size < 2 * 2**20, output
            for v in streams(p, "video"):
                assert v["width"] <= 720, output
                assert v["height"] <= 480, output


MULTITRACK_LAYOUT = [
    ("video", None, None, frozenset({"default"})),
    ("audio", "jpn", "Japanese 5.1", frozenset({"default"})),
    ("audio", "eng", "English Stereo", frozenset()),
    ("audio", "eng", "Director's Commentary", frozenset({"comment"})),
    ("subtitle", "eng", "English", frozenset({"default"})),
    ("subtitle", "eng", "English SDH", frozenset({"hearing_impaired"})),
    ("subtitle", "eng", "Signs & Songs", frozenset({"forced"})),
]


def test_multitrack(probe: Callable[..., Probe]) -> None:
    p = probe("multitrack.mkv")
    assert layout(p) == MULTITRACK_LAYOUT
    v, a0, a1, a2, *subs = p["streams"]
    assert v["codec_name"] == "h264"
    assert (v["width"], v["height"]) == (320, 180)
    assert (a0["codec_name"], a0["channels"], a0["channel_layout"]) == ("ac3", 6, "5.1(side)")
    assert (a1["codec_name"], a1["channels"]) == ("aac", 2)
    assert (a2["codec_name"], a2["channels"]) == ("aac", 2)
    # Verified: no per-stream bit_rate for AAC in Matroska (AC-3 has one, from its header).
    assert "bit_rate" not in a2
    assert all(s["codec_name"] == "subrip" for s in subs)
    assert p["format"]["tags"]["title"] == "Reframe multi-track fixture"


def _dominant_frequency(path: Path, stream: int) -> float:
    """Zero crossings of the first second of an audio stream, as a frequency."""
    ffmpeg = media.find_ffmpeg()
    assert ffmpeg
    raw = subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            f"0:a:{stream}",
            "-t",
            "1",
            "-ac",
            "1",
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-",
        ],
        capture_output=True,
        check=True,
        timeout=60,
    ).stdout
    samples = memoryview(raw).cast("h")
    crossings = sum(1 for i in range(1, len(samples)) if (samples[i - 1] < 0) != (samples[i] < 0))
    return crossings / 2 * 48000 / len(samples)


def test_multitrack_has_a_different_tone_per_track(all_media: Path) -> None:
    freqs = [_dominant_frequency(all_media / "multitrack.mkv", i) for i in range(3)]
    for got, want in zip(freqs, (440, 660, 880), strict=True):
        assert abs(got - want) < 15, freqs


def test_text_subs(all_media: Path, probe: Callable[..., Probe]) -> None:
    p = probe("text-subs.mkv")
    subs = streams(p, "subtitle")
    assert [(s["codec_name"], tags(s)["language"], tags(s)["title"]) for s in subs] == [
        ("subrip", "eng", "English (SRT)"),
        ("ass", "eng", "English (ASS)"),
    ]
    assert flags(subs[0]) == {"default"}
    (att,) = streams(p, "attachment")
    font = media.find_font()
    assert att["codec_name"] == "ttf"
    assert tags(att) == {"filename": font.file_name, "mimetype": "application/x-truetype-font"}
    ass_text = (all_media / "text-subs.en.ass").read_text(encoding="utf-8")
    assert f"Style: Default,{font.family}," in ass_text
    assert "Árvíztűrő" in ass_text
    assert (all_media / "text-subs.en.srt").read_text(encoding="utf-8").count(" --> ") == 2


def test_text_subs_font_renders_with_libass(all_media: Path, tmp_path: Path) -> None:
    """The attached font (system or generated) is usable: libass draws the ASS text with it."""
    ffmpeg = media.find_ffmpeg()
    assert ffmpeg
    filters = subprocess.run(
        [ffmpeg, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=30
    ).stdout
    if not re.search(r"^\s*\S+\s+ass\s", filters, re.M):
        pytest.skip("this ffmpeg has no libass")
    font = media.find_font()
    (tmp_path / "fonts").mkdir()
    (tmp_path / "fonts" / font.file_name).write_bytes(font.data)
    (tmp_path / "t.ass").write_text(
        media.ass(font.family, [(0, 5, "Default", "Hello")]), encoding="utf-8"
    )
    frame = subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=black:size=320x180:duration=1",
            "-vf",
            "ass=t.ass:fontsdir=fonts",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-",
        ],
        capture_output=True,
        check=True,
        cwd=tmp_path,
        timeout=60,
    ).stdout
    assert len(frame) == 320 * 180
    assert sum(1 for b in frame if b > 128) > 100


def test_vobsub(probe: Callable[..., Probe]) -> None:
    p = probe("vobsub.mkv", "-count_packets")
    subs = streams(p, "subtitle")
    assert [(s["codec_name"], tags(s)["language"], frozenset(flags(s))) for s in subs] == [
        ("dvd_subtitle", "eng", frozenset({"default"})),
        ("dvd_subtitle", "fre", frozenset({"forced"})),
    ]
    assert [int(s["nb_read_packets"]) for s in subs] == [
        len(e) for e in media.VOBSUB_EVENTS.values()
    ]
    assert all((s["width"], s["height"]) == (720, 480) for s in subs)
    assert tags(subs[0])["ENCODER"].endswith("dvdsub")


def _cropdetect(path: Path, start: float) -> str:
    ffmpeg = media.find_ffmpeg()
    assert ffmpeg
    err = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-ss",
            str(start),
            "-t",
            "1",
            "-i",
            str(path),
            "-vf",
            "cropdetect=round=2:reset=1",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    ).stderr
    found = re.findall(r"crop=(\d+:\d+:\d+:\d+)", err)
    assert found
    return str(found[-1])


def test_letterbox_changes_aspect(all_media: Path, probe: Callable[..., Probe]) -> None:
    v = streams(probe("letterbox.mkv"), "video")[0]
    assert (v["width"], v["height"]) == (320, 180)
    assert _cropdetect(all_media / "letterbox.mkv", 0.5) == "320:134:0:22"  # 2.39:1 letterbox
    assert _cropdetect(all_media / "letterbox.mkv", 2.5) == "240:180:40:0"  # 4:3 pillarbox


def test_anamorphic(probe: Callable[..., Probe]) -> None:
    v = streams(probe("anamorphic.mkv"), "video")[0]
    assert (v["width"], v["height"]) == (720, 480)
    assert v["sample_aspect_ratio"] == "32:27"
    assert v["display_aspect_ratio"] == "16:9"


def test_interlaced(probe: Callable[..., Probe]) -> None:
    v = streams(probe("interlaced.mkv"), "video")[0]
    # Top field first. FFmpeg writes "tb" (not "tt") for TFF encodes, see the README.
    assert v["field_order"] in ("tt", "tb")
    assert v["r_frame_rate"] == "30000/1001"


def _frame_intervals(path: Path) -> tuple[float, float]:
    """Shortest and longest interval between video packet timestamps."""
    ffprobe = media.find_ffprobe()
    assert ffprobe
    out = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "packet=pts_time",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    ).stdout
    pts = sorted(float(line) for line in out.split() if line.strip())
    deltas = [b - a for a, b in itertools.pairwise(pts)]
    return min(deltas), max(deltas)


def test_vfr_mp4(all_media: Path, probe: Callable[..., Probe]) -> None:
    v = streams(probe("vfr.mp4"), "video")[0]
    assert v["r_frame_rate"] != v["avg_frame_rate"]
    assert Fraction(v["avg_frame_rate"]) > 0
    shortest, longest = _frame_intervals(all_media / "vfr.mp4")
    assert shortest < 0.02
    assert longest > 0.04


def test_vfr_mkv(all_media: Path, probe: Callable[..., Probe]) -> None:
    v = streams(probe("vfr.mkv"), "video")[0]
    assert v["r_frame_rate"] != v["avg_frame_rate"]
    # Verified behaviour: Matroska written by FFmpeg has no frame count, so ffprobe reports
    # avg_frame_rate 0/0 (unknown), not a real average.
    assert v["avg_frame_rate"] == "0/0"
    shortest, longest = _frame_intervals(all_media / "vfr.mkv")
    assert shortest < 0.02
    assert longest > 0.04


def test_hdr10(probe: Callable[..., Probe]) -> None:
    v = streams(probe("hdr10.mkv"), "video")[0]
    assert (v["codec_name"], v["profile"], v["pix_fmt"]) == ("hevc", "Main 10", "yuv420p10le")
    assert (v["color_primaries"], v["color_transfer"], v["color_space"]) == (
        "bt2020",
        "smpte2084",
        "bt2020nc",
    )
    side = {d["side_data_type"]: d for d in v["side_data_list"]}
    mdm = side["Mastering display metadata"]
    assert Fraction(mdm["max_luminance"]) == 1000
    assert Fraction(mdm["min_luminance"]) == Fraction(1, 10000)
    assert Fraction(mdm["green_x"]) == Fraction(13250, 50000)
    cll = side["Content light level metadata"]
    assert (cll["max_content"], cll["max_average"]) == (1000, 400)
    frames = probe(
        "hdr10.mkv", "-show_frames", "-read_intervals", "%+#1", "-select_streams", "v:0"
    )["frames"]
    frame_side = {d["side_data_type"] for d in frames[0]["side_data_list"]}
    assert {"Mastering display metadata", "Content light level metadata"} <= frame_side


def test_chapters(probe: Callable[..., Probe]) -> None:
    p = probe("chapters.mkv")
    got = [
        (
            round(float(c["start_time"]) * 1000),
            round(float(c["end_time"]) * 1000),
            c["tags"]["title"],
        )
        for c in p["chapters"]
    ]
    assert got == list(media.CHAPTERS)
    assert p["format"]["tags"]["title"] == "Reframe chapters fixture"


def test_season_set(all_media: Path, probe: Callable[..., Probe]) -> None:
    files = sorted(p.name for p in (all_media / "season").glob("*.mkv"))
    assert files == [media.season_file_name(n) for n in range(1, 13)]
    extra = ("audio", "eng", "Commentary", frozenset({"comment"}))
    for n in range(1, 13):
        p = probe(f"season/{media.season_file_name(n)}")
        assert p["format"]["tags"]["title"] == f"Show - S01E{n:02d}"
        got = layout(p)
        if n == media.SEASON_EXTRA_COMMENTARY_EPISODE:
            assert got == [*MULTITRACK_LAYOUT[:4], extra, *MULTITRACK_LAYOUT[4:]]
            assert streams(p, "audio")[3]["codec_name"] == "ac3"
            assert streams(p, "audio")[3]["channels"] == 2
        elif n == media.SEASON_MISSING_AUDIO_EPISODE:
            assert got == [MULTITRACK_LAYOUT[i] for i in (0, 1, 3, 4, 5, 6)]
        else:
            assert got == MULTITRACK_LAYOUT


# -------------------------------------------------------------------- verified tool behaviour


def test_matroska_muxer_writes_no_statistics_tags(probe: Callable[..., Probe]) -> None:
    """FFmpeg writes only DURATION (and ENCODER) per track, no BPS / NUMBER_OF_FRAMES /
    NUMBER_OF_BYTES (mkvmerge writes those). C-3's bitrate chain must cope."""
    for s in probe("multitrack.mkv")["streams"]:
        keys = set(tags(s))
        assert "DURATION" in keys
        assert not keys & {
            "BPS",
            "BPS-eng",
            "NUMBER_OF_FRAMES",
            "NUMBER_OF_BYTES",
            "_STATISTICS_TAGS",
        }


#: disposition -> (stream type, written by the Matroska muxer and read back by ffprobe as itself)
DISPOSITIONS = {
    "default": ("audio", True),
    "forced": ("subtitle", True),
    "comment": ("audio", True),
    "hearing_impaired": ("subtitle", True),
    "visual_impaired": ("audio", True),
    "original": ("audio", True),
    "dub": ("audio", True),  # stored as FlagOriginal=0
    "descriptions": ("subtitle", True),  # FlagTextDescriptions
    "captions": ("subtitle", False),
    "lyrics": ("subtitle", False),
    "karaoke": ("audio", False),
    "metadata": ("audio", False),
}


@pytest.mark.parametrize("disposition", sorted(DISPOSITIONS))
def test_matroska_disposition_round_trip(disposition: str, tmp_path: Path) -> None:
    kind, written = DISPOSITIONS[disposition]
    ffmpeg = media.find_ffmpeg()
    assert ffmpeg
    (tmp_path / "a.srt").write_text("1\n00:00:00,000 --> 00:00:00,500\nx\n", encoding="utf-8")
    source = ["-f", "lavfi", "-i", "sine=duration=0.5"] if kind == "audio" else ["-i", "a.srt"]
    codec = ["-c:a", "aac"] if kind == "audio" else ["-c:s", "srt"]
    spec = "a:0" if kind == "audio" else "s:0"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-y",
            *source,
            *codec,
            f"-disposition:{spec}",
            disposition,
            "t.mkv",
        ],
        check=True,
        cwd=tmp_path,
        capture_output=True,
        timeout=60,
    )
    got = flags(media.probe(tmp_path / "t.mkv")["streams"][0])
    assert (got == {disposition}) is written, got
    if not written:
        assert got == set()


def test_single_streams_get_no_default_flag(tmp_path: Path) -> None:
    """With no -disposition, FFmpeg sets "default" only when a type has 2+ streams; a single
    video or audio stream is written with FlagDefault=0 (mkvmerge would write 1)."""
    ffmpeg = media.find_ffmpeg()
    assert ffmpeg
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=64x64:duration=0.2",
            "-f",
            "lavfi",
            "-i",
            "sine=duration=0.2",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "t.mkv",
        ],
        check=True,
        cwd=tmp_path,
        capture_output=True,
        timeout=60,
    )
    assert [flags(s) for s in media.probe(tmp_path / "t.mkv")["streams"]] == [set(), set()]
