"""Fixture media generator (plan Q-2.1, "Test media").

Small files (at most 5 s, low resolution) made with FFmpeg ``lavfi`` sources, so the repository
holds no media. ``scripts/make-testdata.py`` is the command-line front end; tests use
:func:`ensure_fixture` (or the ``fixture_media`` pytest fixture), which generates a fixture on
demand.

Generation is incremental: each fixture is a :class:`Recipe` (files to write plus FFmpeg
commands). Its hash (recipe, generator version, FFmpeg version) is stored in
``<media dir>/manifest.json``; a fixture whose outputs exist and whose hash did not change is
skipped. Each fixture is built in a temporary folder next to the outputs and moved into place
only when all its steps succeeded.

All FFmpeg commands run with the temporary folder as the working directory and use relative
file names only, so no path ever appears in a filter graph (no quoting problems on Windows),
and the recipe hash does not depend on where the repository is.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from reframe_testing import boxfont, vobsub

#: Bump when the generator changes in a way that the recipe text does not show.
#: 2: the ASS fixture always attaches the generated ReframeBox font (no system font search).
GENERATOR_VERSION = 2
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MEDIA_DIR = REPO_ROOT / "testdata" / "media"
MANIFEST_NAME = "manifest.json"
FFMPEG_ENV = "REFRAME_FFMPEG"
FFPROBE_ENV = "REFRAME_FFPROBE"
STEP_TIMEOUT = 120.0

_COMMON = ("-hide_banner", "-nostdin", "-loglevel", "error", "-y")
_X264 = ("-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-pix_fmt", "yuv420p")
_X265_HDR10 = (
    "log-level=error:hdr10=1:repeat-headers=1:"
    "colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc:"
    "master-display=G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(10000000,1):"
    "max-cll=1000,400"
)


class MediaError(RuntimeError):
    """A fixture could not be generated (FFmpeg missing or a step failed)."""


# --------------------------------------------------------------------------- tool discovery


def find_ffmpeg() -> str | None:
    """``REFRAME_FFMPEG`` if set (and it exists), else ``ffmpeg`` on ``PATH``."""
    env = os.environ.get(FFMPEG_ENV)
    if env:
        return env if Path(env).is_file() else None
    return shutil.which("ffmpeg")


def find_ffprobe() -> str | None:
    """``REFRAME_FFPROBE``, else ``ffprobe`` next to the ffmpeg in use, else ``PATH``."""
    env = os.environ.get(FFPROBE_ENV)
    if env:
        return env if Path(env).is_file() else None
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        ff = Path(ffmpeg)
        sibling = ff.with_name(ff.name.replace("ffmpeg", "ffprobe"))
        if sibling != ff and sibling.is_file():
            return str(sibling)
    return shutil.which("ffprobe")


@functools.cache
def _version_line(ffmpeg: str, size: int, mtime_ns: int) -> str:
    out = subprocess.run(
        [ffmpeg, "-hide_banner", "-version"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if out.returncode != 0 or not out.stdout:
        raise MediaError(f"{ffmpeg} -version failed: {out.stderr.strip()}")
    return out.stdout.splitlines()[0].strip()


def ffmpeg_version(ffmpeg: str) -> str:
    """The first line of ``ffmpeg -version`` (cached per binary path, size and mtime)."""
    st = Path(ffmpeg).stat()
    return _version_line(ffmpeg, st.st_size, st.st_mtime_ns)


def probe(path: Path, *extra: str, ffprobe: str | None = None) -> dict[str, Any]:
    """ffprobe JSON (format, streams, chapters) of ``path``; ``extra`` adds arguments."""
    exe = ffprobe or find_ffprobe()
    if exe is None:
        raise MediaError("ffprobe not found")
    out = subprocess.run(
        [
            exe,
            "-v",
            "error",
            "-of",
            "json",
            "-show_format",
            "-show_streams",
            "-show_chapters",
            *extra,
            str(path),
        ],
        capture_output=True,
        timeout=60,
        check=False,
    )
    if out.returncode != 0:
        raise MediaError(f"ffprobe failed on {path}: {out.stderr.decode(errors='replace').strip()}")
    data: dict[str, Any] = json.loads(out.stdout)
    return data


# --------------------------------------------------------------------------- fonts


@dataclass(frozen=True)
class FontChoice:
    family: str
    """Font family name, used as ``Fontname`` in the ASS styles."""
    file_name: str
    """File name of the attachment in the MKV."""
    data: bytes
    source: str
    """Where it came from: a file path, or ``generated``."""
    licence: str


@functools.cache
def fixture_font() -> FontChoice:
    """The font of the ASS fixture: always the generated "Reframe Box" (``ReframeBox.ttf``).

    No system font is used, so ``text-subs.mkv`` (attachment name and size, ASS ``Fontname``) is
    the same on every machine and runner image. The font is generated by
    :mod:`reframe_testing.boxfont`, is public domain (CC0) and renders in libass.
    """
    return FontChoice(
        boxfont.FAMILY, "ReframeBox.ttf", boxfont.build_font(), "generated", "public domain (CC0)"
    )


# --------------------------------------------------------------------------- recipes


@dataclass(frozen=True)
class WriteFile:
    """Write ``data`` to ``path`` (relative to the work folder)."""

    path: str
    data: bytes

    def fingerprint(self) -> list[str]:
        return ["write", self.path, hashlib.sha256(self.data).hexdigest()]


@dataclass(frozen=True)
class Ffmpeg:
    """Run ``ffmpeg <common options> <args>`` in the work folder."""

    args: tuple[str, ...]

    def fingerprint(self) -> list[str]:
        return ["ffmpeg", *_COMMON, *self.args]


Step = WriteFile | Ffmpeg


@dataclass(frozen=True)
class Recipe:
    name: str
    description: str
    outputs: tuple[str, ...]
    """Output paths relative to the media folder (``/`` separated). The first is the main one."""
    steps: tuple[Step, ...]

    def fingerprint(self, ffmpeg_version_line: str) -> str:
        doc = {
            "generator": GENERATOR_VERSION,
            "ffmpeg": ffmpeg_version_line,
            "outputs": list(self.outputs),
            "steps": [s.fingerprint() for s in self.steps],
        }
        return hashlib.sha256(json.dumps(doc, sort_keys=True).encode("utf-8")).hexdigest()


def _text(path: str, text: str) -> WriteFile:
    return WriteFile(path, text.encode("utf-8"))


def _video(size: str, rate: str, duration: float, source: str = "testsrc2") -> tuple[str, ...]:
    return ("-f", "lavfi", "-i", f"{source}=size={size}:rate={rate}:duration={duration:g}")


def _sine(frequency: int, duration: float) -> tuple[str, ...]:
    return (
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency={frequency}:sample_rate=48000:duration={duration:g}",
    )


def srt(cues: Sequence[tuple[float, float, str]]) -> str:
    """SRT text from ``(start s, end s, text)`` cues."""

    def ts(t: float) -> str:
        ms = round(t * 1000)
        h, ms = divmod(ms, 3_600_000)
        m, ms = divmod(ms, 60_000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    blocks = [f"{i}\n{ts(a)} --> {ts(b)}\n{text}\n" for i, (a, b, text) in enumerate(cues, 1)]
    return "\n".join(blocks)


def ass(font_family: str, events: Sequence[tuple[float, float, str, str]]) -> str:
    """ASS script with ``Default`` and ``Sign`` styles; events: ``(start, end, style, text)``."""

    def ts(t: float) -> str:
        cs = round(t * 100)
        h, cs = divmod(cs, 360_000)
        m, cs = divmod(cs, 6000)
        s, cs = divmod(cs, 100)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    fmt = (
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
    )
    lines = [
        "[Script Info]",
        "; Generated by reframe_testing.media for the Reframe test fixtures.",
        "Title: Reframe ASS fixture",
        "ScriptType: v4.00+",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "PlayResX: 320",
        "PlayResY: 180",
        "",
        "[V4+ Styles]",
        fmt,
        f"Style: Default,{font_family},18,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
        "0,0,0,0,100,100,0,0,1,1.5,0.5,2,10,10,8,1",
        f"Style: Sign,{font_family},14,&H0000FFFF,&H000000FF,&H00400000,&H00000000,"
        "-1,0,0,0,100,100,0,0,1,1,0,8,10,10,8,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    lines += [f"Dialogue: 0,{ts(a)},{ts(b)},{style},,0,0,0,,{text}" for a, b, style, text in events]
    return "\n".join(lines) + "\n"


_FULL_CUES = [
    (0.5, 1.5, "Hello, this is the full subtitle track."),
    (2.0, 3.5, "Second line.\nWith two rows."),
]
_SDH_CUES = [
    (0.2, 1.2, "[upbeat music]"),
    (1.5, 3.0, "NARRATOR: Hello, this is SDH."),
    (3.2, 3.9, "[door creaks]"),
]
_SIGNS_CUES = [(1.0, 2.5, "A SIGN ON THE WALL")]

MULTITRACK_DURATION = 4.0


def _multitrack_steps(out: str, *, extra_commentary: bool) -> tuple[Step, ...]:
    """The multi-track layout (also the base of the season set)."""
    d = MULTITRACK_DURATION
    tones = [440, 660, 880] + ([1100] if extra_commentary else [])
    args: list[str] = [*_video("320x180", "25", d)]
    for tone in tones:
        args += _sine(tone, d)
    first_sub = 1 + len(tones)
    args += ["-i", "full.srt", "-i", "sdh.srt", "-i", "signs.srt"]
    args += ["-map", "0:v"]
    for i in range(len(tones)):
        args += ["-map", f"{1 + i}:a"]
    for i in range(3):
        args += ["-map", f"{first_sub + i}:s"]
    args += [*_X264]
    args += ["-c:a:0", "ac3", "-b:a:0", "192k", "-ac:a:0", "6"]
    args += ["-c:a:1", "aac", "-b:a:1", "96k", "-ac:a:1", "2"]
    args += ["-c:a:2", "aac", "-b:a:2", "64k", "-ac:a:2", "2"]
    if extra_commentary:
        args += ["-c:a:3", "ac3", "-b:a:3", "96k", "-ac:a:3", "2"]
    args += ["-c:s", "srt"]
    args += ["-metadata", "title=Reframe multi-track fixture"]
    meta = [
        ("a:0", "jpn", "Japanese 5.1", "default"),
        ("a:1", "eng", "English Stereo", "0"),
        ("a:2", "eng", "Director's Commentary", "comment"),
        ("s:0", "eng", "English", "default"),
        ("s:1", "eng", "English SDH", "hearing_impaired"),
        ("s:2", "eng", "Signs & Songs", "forced"),
    ]
    if extra_commentary:
        meta.append(("a:3", "eng", "Commentary", "comment"))
    args += ["-disposition:v:0", "default"]
    for spec, lang, title, disposition in meta:
        args += [f"-metadata:s:{spec}", f"language={lang}", f"-metadata:s:{spec}", f"title={title}"]
        args += [f"-disposition:{spec}", disposition]
    args.append(out)
    return (
        _text("full.srt", srt(_FULL_CUES)),
        _text("sdh.srt", srt(_SDH_CUES)),
        _text("signs.srt", srt(_SIGNS_CUES)),
        Ffmpeg(tuple(args)),
    )


SEASON_EPISODES = 12
SEASON_EXTRA_COMMENTARY_EPISODE = 5
SEASON_MISSING_AUDIO_EPISODE = 9


def season_file_name(episode: int) -> str:
    return f"Show.S01E{episode:02d}.Title.mkv"


def _season_recipe() -> Recipe:
    steps: list[Step] = list(_multitrack_steps("season-master.mkv", extra_commentary=True))
    outputs: list[str] = []
    for ep in range(1, SEASON_EPISODES + 1):
        out = f"season/{season_file_name(ep)}"
        maps = ["-map", "0"]
        if ep != SEASON_EXTRA_COMMENTARY_EPISODE:
            maps += ["-map", "-0:a:3"]  # the extra commentary track
        if ep == SEASON_MISSING_AUDIO_EPISODE:
            maps += ["-map", "-0:a:1"]  # the second audio track (English Stereo)
        steps.append(
            Ffmpeg(
                (
                    "-i",
                    "season-master.mkv",
                    *maps,
                    "-c",
                    "copy",
                    "-metadata",
                    f"title=Show - S01E{ep:02d}",
                    out,
                )
            )
        )
        outputs.append(out)
    return Recipe(
        "season",
        f"{SEASON_EPISODES} copies of the multi-track MKV; "
        f"E{SEASON_EXTRA_COMMENTARY_EPISODE:02d} has an extra "
        f"commentary track, E{SEASON_MISSING_AUDIO_EPISODE:02d} has no second audio track",
        tuple(outputs),
        tuple(steps),
    )


def _text_subs_recipe(font: FontChoice) -> Recipe:
    d = 4.0
    srt_text = srt(
        [(0.5, 1.8, "Plain SRT subtitle."), (2.0, 3.6, "Árvíztűrő tükörfúrógép <i>(italic)</i>")]
    )
    ass_text = ass(
        font.family,
        [
            (0.5, 1.8, "Default", "Styled {\\i1}ASS{\\i0} subtitle."),
            (1.0, 3.0, "Sign", "{\\pos(160,20)}A SIGN"),
            (2.0, 3.6, "Default", "Árvíztűrő tükörfúrógép"),
        ],
    )
    args = (
        *_video("320x180", "25", d),
        *_sine(523, d),
        "-i",
        "text-subs.en.srt",
        "-i",
        "text-subs.en.ass",
        "-map",
        "0:v",
        "-map",
        "1:a",
        "-map",
        "2:s",
        "-map",
        "3:s",
        *_X264,
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        "-c:s:0",
        "srt",
        "-c:s:1",
        "ass",
        "-attach",
        font.file_name,
        "-metadata:s:t:0",
        "mimetype=application/x-truetype-font",
        "-metadata:s:a:0",
        "language=eng",
        "-metadata:s:s:0",
        "language=eng",
        "-metadata:s:s:0",
        "title=English (SRT)",
        "-metadata:s:s:1",
        "language=eng",
        "-metadata:s:s:1",
        "title=English (ASS)",
        "-disposition:v:0",
        "default",
        "-disposition:a:0",
        "default",
        "-disposition:s:0",
        "default",
        "text-subs.mkv",
    )
    return Recipe(
        "text-subs",
        "SRT and ASS tracks plus the same files as sidecars; "
        f"ASS with the attached font {font.file_name}",
        ("text-subs.mkv", "text-subs.en.srt", "text-subs.en.ass"),
        (
            _text("text-subs.en.srt", srt_text),
            _text("text-subs.en.ass", ass_text),
            WriteFile(font.file_name, font.data),
            Ffmpeg(args),
        ),
    )


VOBSUB_EVENTS = {
    "eng": [vobsub.Event(500, 1800, 300), vobsub.Event(2200, 3600, 460)],
    "fre": [vobsub.Event(1000, 2500, 200)],
}


def _vobsub_recipe() -> Recipe:
    steps: list[Step] = []
    for lang, idx_lang in (("eng", "en"), ("fre", "fr")):
        idx, sub = vobsub.vobsub(VOBSUB_EVENTS[lang], language=idx_lang)
        steps += [_text(f"{lang}.idx", idx), WriteFile(f"{lang}.sub", sub)]
    args = (
        *_video("720x480", "25", 4),
        "-i",
        "eng.idx",
        "-i",
        "fre.idx",
        "-map",
        "0:v",
        "-map",
        "1:s",
        "-map",
        "2:s",
        *_X264,
        "-c:s",
        "dvdsub",
        "-metadata:s:s:0",
        "language=eng",
        "-metadata:s:s:0",
        "title=English",
        "-metadata:s:s:1",
        "language=fre",
        "-metadata:s:s:1",
        "title=French forced",
        "-disposition:v:0",
        "default",
        "-disposition:s:0",
        "default",
        "-disposition:s:1",
        "forced",
        "vobsub.mkv",
    )
    steps.append(Ffmpeg(args))
    return Recipe(
        "vobsub",
        "two VobSub (dvd_subtitle) tracks, encoded with the dvdsub encoder",
        ("vobsub.mkv",),
        tuple(steps),
    )


LETTERBOX_SEGMENTS = (
    # (content size, pad position) inside 320x180: 2.39:1 letterbox, then 4:3 pillarbox
    ("320x134", "0:23"),
    ("240x180", "40:0"),
)


def _letterbox_recipe() -> Recipe:
    args: list[str] = []
    graph: list[str] = []
    for i, (size, pos) in enumerate(LETTERBOX_SEGMENTS):
        args += _video(size, "25", 2)
        graph.append(f"[{i}:v]pad=320:180:{pos}:black,setsar=1[s{i}]")
    n = len(LETTERBOX_SEGMENTS)
    graph.append("".join(f"[s{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v]")
    args += ["-filter_complex", ";".join(graph), "-map", "[v]", *_X264, "letterbox.mkv"]
    return Recipe(
        "letterbox",
        "2 s of 2.39:1 letterbox, then 2 s of 4:3 pillarbox, in a 320x180 frame",
        ("letterbox.mkv",),
        (Ffmpeg(tuple(args)),),
    )


def _simple(name: str, description: str, out: str, args: Sequence[str]) -> Recipe:
    return Recipe(name, description, (out,), (Ffmpeg((*args, out)),))


def _hdr10_recipe() -> Recipe:
    pass1 = (
        *_video("320x180", "25", 2),
        "-vf",
        "format=yuv420p10le,setparams=range=tv:color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc",
        "-c:v",
        "libx265",
        "-preset",
        "ultrafast",
        "-x265-params",
        _X265_HDR10,
        "hdr10-pass1.mkv",
    )
    # A single libx265 encode writes the HDR10 metadata only as SEI in the bitstream. Encoding the
    # decoded result again carries it as frame side data into the encoder, and then the Matroska
    # muxer also writes the stream-level MasteringMetadata / MaxCLL (see testdata/README.md).
    pass2 = (
        "-i",
        "hdr10-pass1.mkv",
        "-c:v",
        "libx265",
        "-preset",
        "ultrafast",
        "-x265-params",
        _X265_HDR10,
        "hdr10.mkv",
    )
    return Recipe(
        "hdr10",
        "10-bit HEVC (libx265), BT.2020/PQ, mastering display and MaxCLL/MaxFALL "
        "(stream and frame side data)",
        ("hdr10.mkv",),
        (Ffmpeg(pass1), Ffmpeg(pass2)),
    )


def _vfr_args(out: str) -> tuple[str, ...]:
    rates = ("24", "30", "60")
    args: list[str] = []
    for r in rates:
        args += _video("320x180", r, 1)
    n = len(rates)
    graph = "".join(f"[{i}:v]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v]"
    return (*args, "-filter_complex", graph, "-map", "[v]", "-fps_mode", "vfr", *_X264, out)


CHAPTERS = (
    (0, 1000, "Opening"),
    (1000, 2500, "Part One"),
    (2500, 4000, "Part Two"),
    (4000, 5000, "Credits"),
)


def _chapters_recipe() -> Recipe:
    meta = [";FFMETADATA1", "title=Reframe chapters fixture", ""]
    for start, end, title in CHAPTERS:
        meta += [
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={start}",
            f"END={end}",
            f"title={title}",
            "",
        ]
    args = (
        *_video("320x180", "25", 5),
        *_sine(330, 5),
        "-f",
        "ffmetadata",
        "-i",
        "chapters.txt",
        "-map",
        "0:v",
        "-map",
        "1:a",
        "-map_metadata",
        "2",
        "-map_chapters",
        "2",
        *_X264,
        "-c:a",
        "aac",
        "-b:a",
        "64k",
        "-metadata:s:a:0",
        "language=eng",
        "-disposition:v:0",
        "default",
        "-disposition:a:0",
        "default",
        "chapters.mkv",
    )
    return Recipe(
        "chapters",
        f"{len(CHAPTERS)} named chapters from an FFMETADATA file",
        ("chapters.mkv",),
        (_text("chapters.txt", "\n".join(meta)), Ffmpeg(args)),
    )


def build_recipes() -> dict[str, Recipe]:
    """Every fixture recipe, by name."""
    recipes = [
        Recipe(
            "multitrack",
            "H.264 + 3 audio (jpn AC-3 5.1 default, eng AAC stereo, eng AAC commentary) "
            "+ 3 SRT (default, SDH hearing_impaired, forced signs)",
            ("multitrack.mkv",),
            _multitrack_steps("multitrack.mkv", extra_commentary=False),
        ),
        _text_subs_recipe(fixture_font()),
        _vobsub_recipe(),
        _letterbox_recipe(),
        _simple(
            "anamorphic",
            "720x480 with SAR 32:27 (16:9 display)",
            "anamorphic.mkv",
            (*_video("720x480", "30000/1001", 2), "-vf", "setsar=32/27", *_X264),
        ),
        _simple(
            "interlaced",
            "interlaced H.264, top field first (interlace filter + setfield=tff)",
            "interlaced.mkv",
            (
                *_video("320x240", "60000/1001", 2),
                "-vf",
                "interlace=scan=tff,setfield=tff",
                *_X264,
                "-flags",
                "+ildct+ilme",
            ),
        ),
        Recipe(
            "vfr",
            "1 s each at 24, 30 and 60 fps, concatenated (MP4: r_frame_rate != avg_frame_rate)",
            ("vfr.mp4",),
            (Ffmpeg(_vfr_args("vfr.mp4")),),
        ),
        Recipe(
            "vfr-mkv",
            "the VFR clip in Matroska (avg_frame_rate is 0/0 there, see testdata/README.md)",
            ("vfr.mkv",),
            (Ffmpeg(_vfr_args("vfr.mkv")),),
        ),
        _hdr10_recipe(),
        _chapters_recipe(),
        _season_recipe(),
    ]
    return {r.name: r for r in recipes}


#: Extra names for secondary outputs: name -> (recipe, output).
ALIASES: dict[str, tuple[str, str]] = {
    "text-subs-srt": ("text-subs", "text-subs.en.srt"),
    "text-subs-ass": ("text-subs", "text-subs.en.ass"),
}


def fixture_names() -> list[str]:
    """Every name that :func:`fixture_path` and :func:`ensure_fixture` accept."""
    return [*build_recipes(), *ALIASES]


def _resolve(name: str, recipes: dict[str, Recipe]) -> tuple[Recipe, str]:
    if name in ALIASES:
        recipe_name, output = ALIASES[name]
        return recipes[recipe_name], output
    if name not in recipes:
        raise KeyError(f"unknown fixture {name!r}; known: {', '.join(fixture_names())}")
    recipe = recipes[name]
    # A recipe with many outputs in one folder (the season set) resolves to the folder.
    first = recipe.outputs[0]
    if len(recipe.outputs) > 1 and all(
        o.startswith(first.split("/")[0] + "/") for o in recipe.outputs
    ):
        return recipe, first.split("/")[0]
    return recipe, first


def fixture_path(name: str, out_dir: Path | None = None) -> Path:
    """Where fixture ``name`` is (or will be); no generation."""
    _, output = _resolve(name, build_recipes())
    return (out_dir or DEFAULT_MEDIA_DIR) / output


# --------------------------------------------------------------------------- generation


@dataclass(frozen=True)
class Result:
    name: str
    status: Literal["generated", "up-to-date"]
    seconds: float


#: Every read and write of ``manifest.json`` in this process holds this lock: on Windows,
#: reading a file while another thread ``os.replace``-s it fails with ``PermissionError``.
_manifest_lock = threading.RLock()

#: Back-off (seconds) between attempts when Windows reports ``PermissionError`` because another
#: thread or process has the file open (a manifest reader, ffprobe on an output, a virus
#: scanner). About 5 s in total; then the last error is raised.
_RETRY_DELAYS = (0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 1.0, 1.0, 1.0)


def _retry_on_permission_error[T](fn: Callable[[], T]) -> T:
    for delay in _RETRY_DELAYS:
        try:
            return fn()
        except PermissionError:
            time.sleep(delay)
    return fn()


def _replace(src: Path, dst: Path) -> None:
    """``os.replace``, retried while Windows reports ``PermissionError``."""
    _retry_on_permission_error(lambda: os.replace(src, dst))


def _read_manifest(out_dir: Path) -> dict[str, Any]:
    path = out_dir / MANIFEST_NAME
    with _manifest_lock:
        try:
            text = _retry_on_permission_error(lambda: path.read_text(encoding="utf-8"))
            data: dict[str, Any] = json.loads(text)
        except (OSError, ValueError):
            return {"version": 1, "fixtures": {}}
    if not isinstance(data.get("fixtures"), dict):
        return {"version": 1, "fixtures": {}}
    return data


def _update_manifest(out_dir: Path, name: str, entry: dict[str, Any] | None) -> None:
    with _manifest_lock:
        data = _read_manifest(out_dir)
        if entry is None:
            data["fixtures"].pop(name, None)
        else:
            data["fixtures"][name] = entry
        tmp = out_dir / f".{MANIFEST_NAME}.{os.getpid()}.{threading.get_ident()}.tmp"
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        _replace(tmp, out_dir / MANIFEST_NAME)


def is_up_to_date(recipe: Recipe, out_dir: Path, ffmpeg_version_line: str) -> bool:
    with _manifest_lock:
        entry = _read_manifest(out_dir)["fixtures"].get(recipe.name)
    if not entry or entry.get("hash") != recipe.fingerprint(ffmpeg_version_line):
        return False
    return all((out_dir / o).is_file() for o in recipe.outputs)


def _run_ffmpeg(ffmpeg: str, step: Ffmpeg, cwd: Path, recipe: str) -> None:
    argv = [ffmpeg, *_COMMON, *step.args]
    try:
        proc = subprocess.run(argv, cwd=cwd, capture_output=True, timeout=STEP_TIMEOUT, check=False)
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"{recipe}: ffmpeg timed out after {STEP_TIMEOUT:g} s: {argv}") from exc
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise MediaError(f"{recipe}: ffmpeg exited with {proc.returncode}: {argv}\n{err}")


def build(recipe: Recipe, out_dir: Path, ffmpeg: str, version_line: str) -> float:
    """Run ``recipe`` in a temporary folder and move its outputs into ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    work = Path(tempfile.mkdtemp(prefix=f".tmp-{recipe.name}-", dir=out_dir))
    try:
        for output in recipe.outputs:
            (work / output).parent.mkdir(parents=True, exist_ok=True)
        for step in recipe.steps:
            if isinstance(step, WriteFile):
                (work / step.path).write_bytes(step.data)
            else:
                _run_ffmpeg(ffmpeg, step, work, recipe.name)
        for output in recipe.outputs:
            if not (work / output).is_file():
                raise MediaError(f"{recipe.name}: the recipe did not create {output}")
        _update_manifest(out_dir, recipe.name, None)
        for output in recipe.outputs:
            dest = out_dir / output
            dest.parent.mkdir(parents=True, exist_ok=True)
            _replace(work / output, dest)
        seconds = time.monotonic() - started
        _update_manifest(
            out_dir,
            recipe.name,
            {
                "hash": recipe.fingerprint(version_line),
                "outputs": list(recipe.outputs),
                "ffmpeg": version_line,
                "seconds": round(seconds, 3),
            },
        )
        return seconds
    finally:
        shutil.rmtree(work, ignore_errors=True)


def generate(
    names: Iterable[str] | None = None,
    *,
    out_dir: Path | None = None,
    force: bool = False,
    ffmpeg: str | None = None,
    jobs: int | None = None,
    log: Callable[[str], None] | None = None,
) -> list[Result]:
    """Generate the named fixtures (default: all) that are missing or out of date."""
    out_dir = Path(out_dir or DEFAULT_MEDIA_DIR)
    ffmpeg = ffmpeg or find_ffmpeg()
    if ffmpeg is None:
        raise MediaError(f"ffmpeg not found: set {FFMPEG_ENV} or put ffmpeg on PATH")
    version_line = ffmpeg_version(ffmpeg)
    recipes = build_recipes()
    selected: list[Recipe] = []
    for name in names or recipes:
        recipe, _ = _resolve(name, recipes)
        if recipe not in selected:
            selected.append(recipe)

    def one(recipe: Recipe) -> Result:
        if not force and is_up_to_date(recipe, out_dir, version_line):
            result = Result(recipe.name, "up-to-date", 0.0)
        else:
            result = Result(recipe.name, "generated", build(recipe, out_dir, ffmpeg, version_line))
        if log:
            log(f"{result.name:12} {result.status:10} {result.seconds:6.2f} s")
        return result

    workers = max(1, min(jobs or os.cpu_count() or 1, len(selected)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, selected))


def ensure_fixture(name: str, *, out_dir: Path | None = None, ffmpeg: str | None = None) -> Path:
    """Path of fixture ``name``; generates it first if it is missing or out of date."""
    out_dir = Path(out_dir or DEFAULT_MEDIA_DIR)
    recipes = build_recipes()
    recipe, output = _resolve(name, recipes)
    generate([recipe.name], out_dir=out_dir, ffmpeg=ffmpeg, jobs=1)
    return out_dir / output


# --------------------------------------------------------------------------- CLI


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="make-testdata.py",
        description="Generate the Reframe test media fixtures with FFmpeg lavfi sources "
        f"(ffmpeg from ${FFMPEG_ENV}, else PATH).",
    )
    parser.add_argument("--only", nargs="+", metavar="NAME", help="only these fixtures")
    parser.add_argument("--force", action="store_true", help="regenerate even if up to date")
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_MEDIA_DIR, help="output folder (default: %(default)s)"
    )
    parser.add_argument(
        "--jobs", type=int, default=None, help="parallel fixtures (default: CPU count)"
    )
    parser.add_argument("--list", action="store_true", help="list the fixtures and exit")
    args = parser.parse_args(argv)

    if args.list:
        recipes = build_recipes()
        for name, recipe in recipes.items():
            print(f"{name:12} {recipe.description}")
        for alias, (recipe_name, output) in ALIASES.items():
            print(f"{alias:12} {output} (from {recipe_name})")
        return 0
    started = time.monotonic()
    try:
        ffmpeg = find_ffmpeg()
        if ffmpeg is None:
            raise MediaError(f"ffmpeg not found: set {FFMPEG_ENV} or put ffmpeg on PATH")
        font = fixture_font()
        print(f"ffmpeg: {ffmpeg} ({ffmpeg_version(ffmpeg)})")
        print(f"font:   {font.family} ({font.source})")
        print(f"output: {args.out}")
        results = generate(args.only, out_dir=args.out, force=args.force, jobs=args.jobs, log=print)
    except (MediaError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    made = sum(r.status == "generated" for r in results)
    print(f"{made} generated, {len(results) - made} up to date, {time.monotonic() - started:.2f} s")
    return 0
