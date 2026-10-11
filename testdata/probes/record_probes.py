"""Record the ffprobe JSON in ``testdata/probes/`` (Q-2.2, C-3 snapshots).

    BIN=$(uv run --no-project python scripts/fetch-tools.py --platform linux-x64 | tail -n 1)
    uv run python testdata/probes/record_probes.py --bin "$BIN"            # everything
    uv run python testdata/probes/record_probes.py --bin "$BIN" --only pgs  # one probe
    uv run python testdata/probes/record_probes.py --bin "$BIN" --fixtures  # fixture JSON only
    uv run python testdata/probes/record_probes.py --bin "$BIN" --strings   # byte search only

Three parts:

1. **Recorded probes** (``<name>.json``): a small file is generated with FFmpeg in a temporary
   folder (the closest real file FFmpeg can make), ``mkvpropedit --add-track-statistics-tags``
   adds real mkvmerge statistics tags to Matroska files, and the real ffprobe JSON is recorded
   with Reframe's own probe command (:func:`reframe.probe.probe_argv`). Fields that FFmpeg
   cannot generate (TrueHD Atmos, DTS-HD MA, DTS:X, E-AC-3 Atmos profiles, PGS, the Dolby
   Vision configuration record) are then edited, and every edit is listed in ``index.json``
   (field, old value, new value, why). Edited probes are marked ``"synthesised": true``.
   When Reframe would read the first frame (HDR), ``<name>.frames.json`` has that output.
2. **Fixture probes** (``fixtures/<file>.json``): the generated test fixtures
   (``reframe_testing.media``), made and probed with the same build, so the parser snapshots
   do not depend on the FFmpeg that runs the tests.
3. **Confirmed strings** (``confirmed_strings.json``): a byte search for every ffprobe
   profile, codec and side-data string that ``reframe.probe`` relies on, in the build's
   libraries and in the system's ``libavcodec``/``libavutil``.

File names inside the JSON are anonymised: files are generated under neutral names
(``movie-truehd-atmos.mkv``) and probed by relative name, so no local path is recorded.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "testing"))

from reframe.probe.ffprobe import frames_argv, probe_argv  # noqa: E402
from reframe.probe.hdr import needs_frame_side_data  # noqa: E402
from reframe.probe.parse import main_video_index, video_bit_depth  # noqa: E402
from reframe_testing import boxfont, media, vobsub  # noqa: E402

COMMON = ("-hide_banner", "-nostdin", "-loglevel", "error", "-y")
X264 = ("-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-pix_fmt", "yuv420p")
X265_HDR10 = (
    "log-level=error:hdr10=1:repeat-headers=1:"
    "colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc:"
    "master-display=G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(10000000,1):"
    "max-cll=1000,400"
)
PQ_PARAMS = "setparams=range=tv:color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc"

DTS_XLL_WHY = (
    "FFmpeg cannot encode DTS-HD MA (its dca encoder writes a DTS core only). libavcodec "
    "dca_xll.c ff_dca_xll_filter_frame() sets these for a lossless (XLL) stream: profile "
    "(AV_PROFILE_DTS_HD_MA{,_X}), sample_fmt S32P for 24-bit storage, bits_per_raw_sample = "
    "storage_bit_res (24) and bit_rate = 0, which ffprobe omits from JSON."
)


# --------------------------------------------------------------------------- recipe model


@dataclass(frozen=True)
class Write:
    path: str
    data: bytes


@dataclass(frozen=True)
class Ffmpeg:
    args: tuple[str, ...]


@dataclass(frozen=True)
class Edit:
    """Set (or with ``delete``, remove) ``field`` of stream ``stream`` (or the format)."""

    stream: int | None
    field: str
    value: Any = None
    why: str = ""
    delete: bool = False
    after: str | None = None
    """When the field is new: insert it after this key (else at the end)."""


@dataclass(frozen=True)
class AddSideData:
    stream: int
    entry: dict[str, Any]
    why: str


@dataclass
class Probe:
    name: str
    file: str
    description: str
    steps: list[Write | Ffmpeg]
    stats_tags: bool = True
    edits: list[Edit | AddSideData] = field(default_factory=list)


def video(size: str, rate: str, duration: float) -> tuple[str, ...]:
    return ("-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}:duration={duration:g}")


def sine(frequency: int, duration: float) -> tuple[str, ...]:
    return (
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency={frequency}:sample_rate=48000:duration={duration:g}",
    )


def meta(spec: str, **values: str) -> list[str]:
    out: list[str] = []
    for key, value in values.items():
        out += [f"-metadata:s:{spec}", f"{key}={value}"]
    return out


def cues(n: int, length: float, text: str) -> list[tuple[float, float, str]]:
    step = length / n
    return [(i * step + 0.05, (i + 1) * step - 0.05, f"{text} {i + 1}") for i in range(n)]


def bitmap_events(n: int, length_ms: int) -> list[vobsub.Event]:
    step = length_ms // n
    return [vobsub.Event(i * step + 20, (i + 1) * step - 20, 200 + 40 * (i % 10)) for i in range(n)]


def ffmetadata(chapters: Sequence[tuple[int, int, str]], title: str | None = None) -> bytes:
    lines = [";FFMETADATA1"] + ([f"title={title}"] if title else []) + [""]
    for start, end, name in chapters:
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={start}", f"END={end}", f"title={name}"]
        lines.append("")
    return "\n".join(lines).encode("utf-8")


def bitmap_tracks(tracks: Sequence[tuple[str, int]], length_ms: int) -> list[Write]:
    steps: list[Write] = []
    for i, (lang, n) in enumerate(tracks):
        idx, sub = vobsub.vobsub(bitmap_events(n, length_ms), language=lang)
        steps += [Write(f"s{i}.idx", idx.encode("utf-8")), Write(f"s{i}.sub", sub)]
    return steps


# --------------------------------------------------------------------------- recipes


def recipes() -> list[Probe]:
    probes: list[Probe] = []

    # ---- TrueHD Atmos (Blu-ray remux layout) --------------------------------------------
    probes.append(
        Probe(
            "truehd-atmos",
            "movie-truehd-atmos.mkv",
            "Blu-ray remux layout: H.264 1080p, TrueHD 5.1 (Atmos), AC-3 5.1 640k, AC-3 2.0 "
            "192k 'Director's Commentary' (title only, no flag)",
            [
                Ffmpeg(
                    (
                        *video("1920x1080", "24000/1001", 2),
                        *sine(440, 2),
                        *sine(550, 2),
                        *sine(660, 2),
                        *("-map", "0:v", "-map", "1:a", "-map", "2:a", "-map", "3:a"),
                        *X264,
                        *("-c:a:0", "truehd", "-strict", "-2"),
                        *("-filter:a:0", "aformat=sample_fmts=s32p:channel_layouts=5.1(side)"),
                        *("-c:a:1", "ac3", "-b:a:1", "640k"),
                        *("-filter:a:1", "aformat=channel_layouts=5.1(side)"),
                        *("-c:a:2", "ac3", "-b:a:2", "192k"),
                        *("-filter:a:2", "aformat=channel_layouts=stereo"),
                        *meta("a:0", language="eng", title="Dolby TrueHD Atmos 5.1"),
                        *meta("a:1", language="eng", title="Dolby Digital 5.1"),
                        *meta("a:2", language="eng", title="Director's Commentary"),
                        *("-disposition:v:0", "default", "-disposition:a:0", "default"),
                        "movie-truehd-atmos.mkv",
                    )
                )
            ],
            edits=[
                Edit(
                    1,
                    "profile",
                    "Dolby TrueHD + Dolby Atmos",
                    "FFmpeg's truehd encoder cannot write the 16-channel (4th substream) Atmos "
                    "presentation. libavcodec mlpdec.c read_major_sync() sets "
                    "AV_PROFILE_TRUEHD_ATMOS for it; nothing else (no bit_rate) changes.",
                    after="codec_long_name",
                )
            ],
        )
    )

    # ---- DTS-HD MA ---------------------------------------------------------------------
    srt_full = media.srt(cues(8, 4.0, "Line"))
    probes.append(
        Probe(
            "dts-hd-ma",
            "movie-dts-hd-ma.mkv",
            "H.264 1080p, DTS-HD MA 5.1 (default), AC-3 2.0 192k in the same language with no "
            "title or flag (commentary heuristic), SRT",
            [
                Write("eng.srt", srt_full.encode("utf-8")),
                Ffmpeg(
                    (
                        *video("1920x1080", "24000/1001", 4),
                        *sine(440, 4),
                        *sine(880, 4),
                        "-i",
                        "eng.srt",
                        *("-map", "0:v", "-map", "1:a", "-map", "2:a", "-map", "3:s"),
                        *X264,
                        *("-c:a:0", "dca", "-strict", "-2"),
                        *("-filter:a:0", "aformat=channel_layouts=5.1(side)"),
                        *("-c:a:1", "ac3", "-b:a:1", "192k"),
                        *("-filter:a:1", "aformat=channel_layouts=stereo"),
                        *("-c:s", "srt"),
                        *meta("a:0", language="eng", title="DTS-HD MA 5.1"),
                        *meta("a:1", language="eng"),
                        *meta("s:0", language="eng"),
                        *("-disposition:v:0", "default", "-disposition:a:0", "default"),
                        "movie-dts-hd-ma.mkv",
                    )
                ),
            ],
            edits=_dts_xll_edits(1, "DTS-HD MA"),
        )
    )

    # ---- DTS:X ---------------------------------------------------------------------------
    probes.append(
        Probe(
            "dts-x",
            "movie-dts-x.mkv",
            "H.264 1080p, DTS:X (DTS-HD MA + DTS:X) 5.1 eng (default), AC-3 5.1 ger",
            [
                Ffmpeg(
                    (
                        *video("1920x1080", "24000/1001", 2),
                        *sine(440, 2),
                        *sine(500, 2),
                        *("-map", "0:v", "-map", "1:a", "-map", "2:a"),
                        *X264,
                        *("-c:a:0", "dca", "-strict", "-2"),
                        *("-filter:a:0", "aformat=channel_layouts=5.1(side)"),
                        *("-c:a:1", "ac3", "-b:a:1", "448k"),
                        *("-filter:a:1", "aformat=channel_layouts=5.1(side)"),
                        *meta("a:0", language="eng", title="DTS:X"),
                        *meta("a:1", language="ger", title="Deutsch AC3 5.1"),
                        *("-disposition:v:0", "default", "-disposition:a:0", "default"),
                        "movie-dts-x.mkv",
                    )
                )
            ],
            edits=_dts_xll_edits(1, "DTS-HD MA + DTS:X"),
        )
    )

    # ---- E-AC-3 Atmos (web release) ------------------------------------------------------
    probes.append(
        Probe(
            "eac3-atmos",
            "show-eac3-atmos.mkv",
            "Web release layout: H.264 1080p, E-AC-3 5.1 640k (Atmos); SRT 'English', "
            "'English [SDH]', 'English [Forced]' (roles from titles only)",
            [
                Write("full.srt", media.srt(cues(8, 4.0, "Line")).encode("utf-8")),
                Write("sdh.srt", media.srt(cues(10, 4.0, "[music] Line")).encode("utf-8")),
                Write("forced.srt", media.srt([(1.0, 2.0, "SIGN")]).encode("utf-8")),
                Ffmpeg(
                    (
                        *video("1920x1080", "24000/1001", 4),
                        *sine(440, 4),
                        *("-i", "full.srt", "-i", "sdh.srt", "-i", "forced.srt"),
                        *("-map", "0:v", "-map", "1:a", "-map", "2:s", "-map", "3:s"),
                        *("-map", "4:s"),
                        *X264,
                        *("-c:a", "eac3", "-b:a", "640k"),
                        *("-filter:a", "aformat=channel_layouts=5.1(side)"),
                        *("-c:s", "srt"),
                        *meta("a:0", language="eng", title="English"),
                        *meta("s:0", language="eng", title="English"),
                        *meta("s:1", language="eng", title="English [SDH]"),
                        *meta("s:2", language="eng", title="English [Forced]"),
                        *("-disposition:v:0", "default", "-disposition:a:0", "default"),
                        "show-eac3-atmos.mkv",
                    )
                ),
            ],
            edits=[
                Edit(
                    1,
                    "profile",
                    "Dolby Digital Plus + Dolby Atmos",
                    "FFmpeg's eac3 encoder cannot write JOC (Atmos) metadata. libavcodec "
                    "ac3dec.c sets AV_PROFILE_EAC3_DDP_ATMOS for a stream with JOC; the other "
                    "fields do not change.",
                    after="codec_long_name",
                )
            ],
        )
    )

    # ---- PGS ---------------------------------------------------------------------------
    pgs_tracks = [("en", 8), ("en", 1), ("en", 9), ("hu", 8)]
    pgs_why = (
        "FFmpeg has no PGS encoder. The tracks were encoded as VobSub (dvdsub) from generated "
        "bitmaps and re-labelled: codec_name/codec_long_name as libavcodec names the PGS "
        "decoder, the 1920x1080 canvas of a Blu-ray, and no extradata (Matroska S_HDMV/PGS "
        "has no CodecPrivate; VobSub keeps its palette there)."
    )
    pgs_edits: list[Edit | AddSideData] = []
    for i in range(len(pgs_tracks)):
        stream = 2 + i
        pgs_edits += [
            Edit(stream, "codec_name", "hdmv_pgs_subtitle", pgs_why),
            Edit(stream, "codec_long_name", "HDMV Presentation Graphic Stream subtitles", pgs_why),
            Edit(stream, "width", 1920, pgs_why),
            Edit(stream, "height", 1080, pgs_why),
            Edit(stream, "extradata_size", why=pgs_why, delete=True),
        ]
    probes.append(
        Probe(
            "pgs",
            "movie-pgs.mkv",
            "H.264 1080p, AC-3 5.1; PGS: eng 'English' default (8 events), eng untitled "
            "(1 event: forced heuristic), eng 'English SDH' hearing_impaired (9), hun (8)",
            [
                *bitmap_tracks(pgs_tracks, 4000),
                Ffmpeg(
                    (
                        *video("1920x1080", "24000/1001", 4),
                        *sine(440, 4),
                        *("-i", "s0.idx", "-i", "s1.idx", "-i", "s2.idx", "-i", "s3.idx"),
                        *("-map", "0:v", "-map", "1:a"),
                        *("-map", "2:s", "-map", "3:s", "-map", "4:s", "-map", "5:s"),
                        *X264,
                        *("-c:a", "ac3", "-b:a", "448k"),
                        *("-filter:a", "aformat=channel_layouts=5.1(side)"),
                        *("-c:s", "dvdsub"),
                        *meta("a:0", language="eng"),
                        *meta("s:0", language="eng", title="English"),
                        *meta("s:1", language="eng"),
                        *meta("s:2", language="eng", title="English SDH"),
                        *meta("s:3", language="hun"),
                        *("-disposition:v:0", "default", "-disposition:a:0", "default"),
                        *("-disposition:s:0", "default", "-disposition:s:1", "0"),
                        *("-disposition:s:2", "hearing_impaired", "-disposition:s:3", "0"),
                        "movie-pgs.mkv",
                    )
                ),
            ],
            edits=pgs_edits,
        )
    )

    # ---- ASS with fonts (anime release) ---------------------------------------------------
    font = boxfont.build_font()
    ass_full = media.ass(
        boxfont.FAMILY, [(a, b, "Default", t) for a, b, t in cues(8, 4.0, "Dialogue")]
    )
    ass_signs = media.ass(
        boxfont.FAMILY,
        [(0.5, 1.5, "Sign", "{\\pos(160,20)}A SIGN"), (2.5, 3.5, "Sign", "♪ A song ♪")],
    )
    probes.append(
        Probe(
            "ass-fonts",
            "anime-ass-fonts.mkv",
            "Anime release layout: H.264 1080p, FLAC 2.0 jpn (default), AAC 2.0 eng; ASS eng "
            "'Signs & Songs' (2 events, no flags), ASS eng 'Full Subtitles' (8, default); two "
            "attached fonts; 2 chapters",
            [
                Write("full.ass", ass_full.encode("utf-8")),
                Write("signs.ass", ass_signs.encode("utf-8")),
                Write("ReframeBox.ttf", font),
                Write("ReframeBox-Alt.ttf", font),
                Write("chapters.txt", ffmetadata([(0, 1500, "Opening"), (1500, 4000, "Part A")])),
                Ffmpeg(
                    (
                        *video("1920x1080", "24000/1001", 4),
                        *sine(440, 4),
                        *sine(660, 4),
                        *("-i", "signs.ass", "-i", "full.ass"),
                        *("-f", "ffmetadata", "-i", "chapters.txt"),
                        *("-map", "0:v", "-map", "1:a", "-map", "2:a", "-map", "3:s"),
                        *("-map", "4:s", "-map_chapters", "5"),
                        *X264,
                        *("-c:a:0", "flac", "-c:a:1", "aac", "-b:a:1", "128k", "-ac", "2"),
                        *("-c:s", "copy"),
                        *("-attach", "ReframeBox.ttf", "-attach", "ReframeBox-Alt.ttf"),
                        *meta("t:0", mimetype="application/x-truetype-font"),
                        *meta("t:1", mimetype="font/ttf"),
                        *meta("a:0", language="jpn", title="Japanese"),
                        *meta("a:1", language="eng", title="English"),
                        *meta("s:0", language="eng", title="Signs & Songs"),
                        *meta("s:1", language="eng", title="Full Subtitles"),
                        *("-disposition:v:0", "default", "-disposition:a:0", "default"),
                        *("-disposition:s:1", "default"),
                        "anime-ass-fonts.mkv",
                    )
                ),
            ],
        )
    )

    # ---- VFR ---------------------------------------------------------------------------
    rates = ("24", "30", "60")
    vfr_inputs: list[str] = []
    for r in rates:
        vfr_inputs += video("1280x720", r, 1)
    graph = "".join(f"[{i}:v]" for i in range(3)) + "concat=n=3:v=1:a=0[v]"
    probes.append(
        Probe(
            "vfr",
            "phone-vfr.mkv",
            "Variable frame rate: 1 s each at 24, 30 and 60 fps (H.264 720p) plus AAC, in "
            "Matroska with statistics tags",
            [
                Ffmpeg(
                    (
                        *vfr_inputs,
                        *sine(440, 3),
                        *("-filter_complex", graph, "-map", "[v]", "-map", "3:a"),
                        *("-fps_mode", "vfr"),
                        *X264,
                        *("-c:a", "aac", "-b:a", "128k", "-ac", "2"),
                        *meta("a:0", language="eng"),
                        *("-disposition:v:0", "default", "-disposition:a:0", "default"),
                        "phone-vfr.mkv",
                    )
                )
            ],
        )
    )

    # ---- Interlaced DVD ------------------------------------------------------------------
    dvd_subs = [("en", 6), ("fr", 5)]
    dvd_inputs = (
        *video("720x480", "60000/1001", 4),
        *sine(440, 4),
        *sine(550, 4),
        *("-i", "s0.idx", "-i", "s1.idx"),
    )
    dvd_video = (
        *("-map", "0:v", "-map", "1:a", "-map", "2:a", "-map", "3:s", "-map", "4:s"),
        *("-vf", "interlace=scan=tff,setfield=tff,setsar=32/27"),
        *("-c:v", "mpeg2video", "-b:v", "5M", "-maxrate", "8M", "-bufsize", "1835k"),
        *("-flags", "+ilme+ildct", "-g", "15"),
        *("-c:a", "ac3", "-b:a", "192k", "-filter:a", "aformat=channel_layouts=stereo"),
        *("-c:s", "dvdsub"),
        *meta("a:0", language="eng"),
        *meta("a:1", language="fre"),
        *meta("s:0", language="eng"),
        *meta("s:1", language="fre"),
        *("-disposition:s:0", "0", "-disposition:s:1", "0"),
    )
    probes.append(
        Probe(
            "dvd-interlaced",
            "dvd-title-interlaced.mkv",
            "DVD rip layout: MPEG-2 720x480 29.97i TFF, SAR 32:27 (16:9), AC-3 2.0 eng + fre, "
            "VobSub eng + fre, 2 chapters, statistics tags",
            [
                *bitmap_tracks(dvd_subs, 4000),
                Write(
                    "chapters.txt",
                    ffmetadata([(0, 2000, "Chapter 01"), (2000, 4000, "Chapter 02")]),
                ),
                Ffmpeg(
                    (
                        *dvd_inputs,
                        *("-f", "ffmetadata", "-i", "chapters.txt", "-map_chapters", "5"),
                        *dvd_video,
                        *("-disposition:v:0", "default", "-disposition:a:0", "default"),
                        "dvd-title-interlaced.mkv",
                    )
                ),
            ],
        )
    )
    probes.append(
        Probe(
            "dvd-interlaced-vob",
            "dvd-title-interlaced.vob",
            "The same DVD title as an MPEG program stream (VOB): stream start offsets, ids",
            [
                *bitmap_tracks(dvd_subs, 4000),
                Ffmpeg((*dvd_inputs, *dvd_video, "-f", "vob", "dvd-title-interlaced.vob")),
            ],
            stats_tags=False,
        )
    )

    # ---- HDR10, HDR10 SEI only, Dolby Vision 8.1, HLG -------------------------------------
    def x265_two_pass(size: str, out: str, extra: Sequence[str] = ()) -> list[Write | Ffmpeg]:
        pass1 = (
            *video(size, "24000/1001", 1),
            *("-vf", f"format=yuv420p10le,{PQ_PARAMS}"),
            *("-c:v", "libx265", "-preset", "ultrafast", "-x265-params", X265_HDR10),
            "pass1.mkv",
        )
        pass2 = (
            *("-i", "pass1.mkv", *extra),
            *("-map", "0:v", *(["-map", "1:a"] if extra else [])),
            *("-c:v", "libx265", "-preset", "ultrafast", "-x265-params", X265_HDR10),
            *(
                [
                    "-c:a",
                    "eac3",
                    "-b:a",
                    "640k",
                    "-filter:a",
                    "aformat=channel_layouts=5.1(side)",
                    *meta("a:0", language="eng"),
                    "-disposition:a:0",
                    "default",
                ]
                if extra
                else []
            ),
            *("-disposition:v:0", "default"),
            out,
        )
        return [Ffmpeg(pass1), Ffmpeg(pass2)]

    probes.append(
        Probe(
            "hdr10",
            "movie-hdr10-2160p.mkv",
            "HEVC Main 10 3840x2160 BT.2020/PQ, mastering display + MaxCLL as stream side data "
            "(two libx265 passes), E-AC-3 5.1",
            x265_two_pass("3840x2160", "movie-hdr10-2160p.mkv", sine(440, 1)),
        )
    )
    probes.append(
        Probe(
            "hdr10-sei-only",
            "movie-hdr10-sei.mkv",
            "HEVC Main 10 1080p BT.2020/PQ from one libx265 pass: the HDR10 metadata is only "
            "in SEI (frame side data), so Reframe reads the first frame",
            [
                Ffmpeg(
                    (
                        *video("1920x1080", "24000/1001", 1),
                        *("-vf", f"format=yuv420p10le,{PQ_PARAMS}"),
                        *("-c:v", "libx265", "-preset", "ultrafast", "-x265-params", X265_HDR10),
                        *("-disposition:v:0", "default"),
                        "movie-hdr10-sei.mkv",
                    )
                )
            ],
        )
    )
    probes.append(
        Probe(
            "dv-p8",
            "movie-dv-p8.mkv",
            "Dolby Vision profile 8.1 (HDR10-compatible base layer): the HDR10 stream of the "
            "'hdr10' recipe (1080p) plus a DOVI configuration record",
            x265_two_pass("1920x1080", "movie-dv-p8.mkv"),
            edits=[
                AddSideData(
                    0,
                    {
                        "side_data_type": "DOVI configuration record",
                        "dv_version_major": 1,
                        "dv_version_minor": 0,
                        "dv_profile": 8,
                        "dv_level": 4,
                        "rpu_present_flag": 1,
                        "el_present_flag": 0,
                        "bl_present_flag": 1,
                        "dv_bl_signal_compatibility_id": 1,
                        "dv_md_compression": 0,
                    },
                    "FFmpeg cannot make a Dolby Vision stream from nothing: libx265 with "
                    "-dolbyvision 1 needs AV_FRAME_DATA_DOVI_METADATA on every input frame "
                    "('Dolby Vision enabled, but received frame without "
                    "AV_FRAME_DATA_DOVI_METADATA'). The entry is what ffprobe prints for a "
                    "Matroska BlockAdditionMapping dvcC of profile 8.1: side_data_type "
                    "(libavcodec) and the field names in ffprobe's order (bin/ffprobe).",
                )
            ],
        )
    )
    probes.append(
        Probe(
            "hlg",
            "broadcast-hlg.mkv",
            "HEVC Main 10 1080p50 BT.2020 / HLG (arib-std-b67), no static metadata",
            [
                Ffmpeg(
                    (
                        *video("1920x1080", "50", 1),
                        *sine(440, 1),
                        *(
                            "-vf",
                            "format=yuv420p10le,setparams=range=tv:color_primaries=bt2020:"
                            "color_trc=arib-std-b67:colorspace=bt2020nc",
                        ),
                        *("-c:v", "libx265", "-preset", "ultrafast"),
                        *("-x265-params", "log-level=error"),
                        *("-c:a", "aac", "-b:a", "128k", "-ac", "2", *meta("a:0", language="eng")),
                        *("-disposition:v:0", "default", "-disposition:a:0", "default"),
                        "broadcast-hlg.mkv",
                    )
                )
            ],
        )
    )

    # ---- cover art, rotation + timecode ----------------------------------------------------
    probes.append(
        Probe(
            "cover-art",
            "song-cover.m4a",
            "AAC in M4A with a PNG cover (attached_pic): cover art is not a video track",
            [
                Ffmpeg(
                    (
                        *sine(440, 2),
                        *video("300x300", "1", 1),
                        *("-map", "0:a", "-map", "1:v", "-frames:v", "1"),
                        *("-c:a", "aac", "-b:a", "128k", "-ac", "2", "-c:v", "png"),
                        *("-disposition:v:0", "attached_pic"),
                        *("-metadata", "title=Test Song", "-metadata", "artist=Reframe"),
                        "song-cover.m4a",
                    )
                )
            ],
            stats_tags=False,
        )
    )
    probes.append(
        Probe(
            "phone-rotated",
            "phone-rotated.mov",
            "Phone recording layout: H.264 1280x720, display matrix 90° clockwise, AAC, "
            "QuickTime timecode (tmcd) data stream, creation_time",
            [
                Ffmpeg(
                    (
                        *("-noautorotate", "-display_rotation:v:0", "-90"),
                        *video("1280x720", "30", 2),
                        *sine(440, 2),
                        *("-map", "0:v", "-map", "1:a"),
                        *X264,
                        *("-c:a", "aac", "-b:a", "128k", "-ac", "2"),
                        *("-timecode", "01:00:00:00"),
                        *("-metadata", "creation_time=2026-05-01T10:20:30.000000Z"),
                        "phone-rotated.mov",
                    )
                )
            ],
            stats_tags=False,
        )
    )
    return probes


def _dts_xll_edits(stream: int, profile: str) -> list[Edit | AddSideData]:
    return [
        Edit(stream, "profile", profile, DTS_XLL_WHY, after="codec_long_name"),
        Edit(stream, "sample_fmt", "s32p", DTS_XLL_WHY),
        Edit(stream, "bits_per_raw_sample", "24", DTS_XLL_WHY, after="start_time"),
        Edit(stream, "bit_rate", why=DTS_XLL_WHY, delete=True),
    ]


# --------------------------------------------------------------------------- running


def run(argv: Sequence[str], cwd: Path) -> str:
    done = subprocess.run(list(argv), cwd=cwd, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise SystemExit(f"failed ({done.returncode}): {' '.join(argv)}\n{done.stderr}")
    return done.stdout


def probe_json(ffprobe: str, cwd: Path, rel: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(run(probe_argv(ffprobe, rel), cwd))
    return data


def frames_json(ffprobe: str, cwd: Path, rel: str, data: dict[str, Any]) -> dict[str, Any] | None:
    index = main_video_index(data)
    if index is None:
        return None
    stream = next(s for s in data["streams"] if s.get("index") == index)
    if not needs_frame_side_data(stream, video_bit_depth(stream)):
        return None
    frames: dict[str, Any] = json.loads(run(frames_argv(ffprobe, rel, index), cwd))
    return frames


def apply_edit(data: dict[str, Any], edit: Edit | AddSideData) -> dict[str, Any]:
    if isinstance(edit, AddSideData):
        stream = data["streams"][edit.stream]
        stream.setdefault("side_data_list", []).append(edit.entry)
        return {
            "stream": edit.stream,
            "field": "side_data_list[+]",
            "old": None,
            "new": edit.entry,
            "why": edit.why,
        }
    target = data["format"] if edit.stream is None else data["streams"][edit.stream]
    old = target.get(edit.field)
    if edit.delete:
        target.pop(edit.field, None)
        new = None
    elif edit.field in target or edit.after is None or edit.after not in target:
        target[edit.field] = edit.value
        new = edit.value
    else:
        items = list(target.items())
        target.clear()
        for key, value in items:
            target[key] = value
            if key == edit.after:
                target[edit.field] = edit.value
        new = edit.value
    return {"stream": edit.stream, "field": edit.field, "old": old, "new": new, "why": edit.why}


def dump(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")


def version_line(tool: str) -> str:
    return run([tool, "-version"], Path.cwd()).splitlines()[0]


def record_probe(
    probe: Probe, ffmpeg: str, ffprobe: str, mkvpropedit: str | None
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="reframe-probe-") as tmp:
        work = Path(tmp)
        commands: list[list[str]] = []
        for step in probe.steps:
            if isinstance(step, Write):
                (work / step.path).write_bytes(step.data)
            else:
                argv = [ffmpeg, *COMMON, *step.args]
                run(argv, work)
                commands.append(["ffmpeg", *COMMON, *step.args])
        if probe.stats_tags:
            if mkvpropedit is None:
                raise SystemExit("mkvpropedit is needed for the statistics tags")
            run([mkvpropedit, "--quiet", "--add-track-statistics-tags", probe.file], work)
            commands.append(["mkvpropedit", "--quiet", "--add-track-statistics-tags", probe.file])
        data = probe_json(ffprobe, work, probe.file)
        frames = frames_json(ffprobe, work, probe.file, data)
    edits = [apply_edit(data, edit) for edit in probe.edits]
    dump(HERE / f"{probe.name}.json", data)
    frames_path = HERE / f"{probe.name}.frames.json"
    if frames is not None:
        dump(frames_path, frames)
    elif frames_path.exists():
        frames_path.unlink()
    return {
        "file": probe.file,
        "description": probe.description,
        "synthesised": bool(edits),
        "commands": commands,
        "probe_command": ["ffprobe", *probe_argv("ffprobe", probe.file)[1:]],
        "frames": frames is not None,
        "edits": edits,
    }


def record_fixtures(ffmpeg: str, ffprobe: str) -> list[str]:
    out_dir = HERE / "fixtures"
    recorded: list[str] = []
    with tempfile.TemporaryDirectory(prefix="reframe-fixtures-") as tmp:
        media_dir = Path(tmp)
        recipes_by_name = media.build_recipes()
        for name, recipe in recipes_by_name.items():
            media.ensure_fixture(name, out_dir=media_dir, ffmpeg=ffmpeg)
            for rel in recipe.outputs:
                data = probe_json(ffprobe, media_dir, rel)
                dump(out_dir / f"{rel}.json", data)
                frames = frames_json(ffprobe, media_dir, rel, data)
                if frames is not None:
                    dump(out_dir / f"{rel}.frames.json", frames)
                recorded.append(rel)
    return recorded


# --------------------------------------------------------------------------- byte search

#: Every ffprobe string that reframe.probe matches on, by where it is used.
STRINGS: dict[str, list[str]] = {
    "aac profiles": ["LC", "HE-AAC", "HE-AACv2", "LD", "ELD", "Main", "SSR", "LTP", "xHE-AAC"],
    "dts profiles": [
        "DTS",
        "DTS-ES",
        "DTS 96/24",
        "DTS-HD HRA",
        "DTS-HD MA",
        "DTS-HD MA + DTS:X",
        "DTS-HD MA + DTS:X IMAX",
        "DTS Express",
    ],
    "eac3 profiles": ["Dolby Digital Plus + Dolby Atmos"],
    "truehd profiles": ["Dolby TrueHD + Dolby Atmos"],
    "video profiles": [
        "Constrained Baseline",
        "Baseline",
        "Main",
        "High",
        "High 10",
        "High 4:2:2",
        "High 4:4:4 Predictive",
        "Main 10",
        "Main Still Picture",
        "Rext",
        "Professional",
        "Profile 0",
        "Profile 2",
        "Simple",
        "4:2:2",
        "HQ",
    ],
    "codec names": [
        "hdmv_pgs_subtitle",
        "dvd_subtitle",
        "dvb_subtitle",
        "subrip",
        "ass",
        "webvtt",
        "mov_text",
        "truehd",
        "eac3",
        "ac3",
        "dts",
        "aac",
        "flac",
        "opus",
        "pcm_s24le",
        "pcm_bluray",
        "h264",
        "hevc",
        "av1",
        "vp9",
        "mpeg2video",
        "ttf",
        "otf",
    ],
    "codec long names": ["HDMV Presentation Graphic Stream subtitles", "DVD subtitles"],
    "side data types": [
        "Mastering display metadata",
        "Content light level metadata",
        "DOVI configuration record",
        "HDR Dynamic Metadata SMPTE2094-40 (HDR10+)",
        "HDR10+ Dynamic Metadata (SMPTE 2094-40)",
        "Display Matrix",
    ],
    "ffprobe fields": [
        "side_data_type",
        "red_x",
        "white_point_x",
        "min_luminance",
        "max_luminance",
        "max_content",
        "max_average",
        "dv_version_major",
        "dv_version_minor",
        "dv_profile",
        "dv_level",
        "rpu_present_flag",
        "el_present_flag",
        "bl_present_flag",
        "dv_bl_signal_compatibility_id",
        "dv_md_compression",
        "rotation",
        "field_order",
        "closed_captions",
    ],
}


def byte_search(files: Sequence[Path]) -> dict[str, Any]:
    """For each string: the files where it is a NUL-terminated C string (``standalone``: also
    NUL before it; ``suffix``: the tail of a longer string, as linkers merge them)."""
    blobs = {str(f): f.read_bytes() for f in files}
    result: dict[str, Any] = {}
    for group, strings in STRINGS.items():
        result[group] = {}
        for text in strings:
            raw = text.encode("utf-8")
            found: dict[str, str] = {}
            for name, blob in blobs.items():
                if b"\0" + raw + b"\0" in blob:
                    found[name] = "standalone"
                elif raw + b"\0" in blob:
                    found[name] = "suffix"
            result[group][text] = found
    return result


def library_files(bin_dir: Path) -> list[Path]:
    lib = bin_dir.parent / "lib"
    pinned = sorted(lib.glob("libavcodec.so.*.*.*")) + sorted(lib.glob("libavutil.so.*.*.*"))
    pinned.append(bin_dir / "ffprobe")
    system = [
        *sorted(Path("/usr/lib").glob("libavcodec.so.*.*.*")),
        *sorted(Path("/usr/lib").glob("libavutil.so.*.*.*")),
        Path("/usr/bin/ffprobe"),
    ]
    return [p for p in pinned + system if p.is_file()]


def record_strings(bin_dir: Path, ffprobe: str) -> None:
    files = library_files(bin_dir)
    found = byte_search(files)
    names = {
        str(f): (
            f"build: {f.relative_to(bin_dir.parent)}"
            if f.is_relative_to(bin_dir.parent)
            else f"system: {f}"
        )
        for f in files
    }
    renamed = {
        group: {text: {names[k]: v for k, v in hits.items()} for text, hits in texts.items()}
        for group, texts in found.items()
    }
    dump(
        HERE / "confirmed_strings.json",
        {"build": version_line(ffprobe), "files": sorted(names.values()), "strings": renamed},
    )


# --------------------------------------------------------------------------- main


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--bin", type=Path, required=True, help="bin folder of the pinned build")
    parser.add_argument("--mkvpropedit", default=shutil.which("mkvpropedit"))
    parser.add_argument("--only", nargs="+", metavar="NAME", help="only these probes")
    parser.add_argument("--fixtures", action="store_true", help="only the fixture JSON")
    parser.add_argument("--strings", action="store_true", help="only the byte search")
    args = parser.parse_args(argv)
    ffmpeg = str(args.bin / "ffmpeg")
    ffprobe = str(args.bin / "ffprobe")
    everything = not (args.only or args.fixtures or args.strings)

    if args.strings or everything:
        record_strings(args.bin, ffprobe)
        print("confirmed_strings.json")
    if args.fixtures or everything:
        for rel in record_fixtures(ffmpeg, ffprobe):
            print(f"fixtures/{rel}.json")
    if args.only or everything:
        index_path = HERE / "index.json"
        index: dict[str, Any] = (
            json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
        )
        probes = index.setdefault("probes", {})
        wanted: Callable[[Probe], bool] = (
            (lambda p: p.name in args.only) if args.only else (lambda p: True)
        )
        for probe in recipes():
            if wanted(probe):
                probes[probe.name] = record_probe(probe, ffmpeg, ffprobe, args.mkvpropedit)
                print(f"{probe.name}.json")
        index["build"] = version_line(ffprobe)
        if args.mkvpropedit:
            index["mkvpropedit"] = run([args.mkvpropedit, "--version"], Path.cwd()).strip()
        index["probes"] = dict(sorted(probes.items()))
        dump(index_path, index)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
