"""Version parsing (C-1), from real captured outputs and from the real binaries."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from reframe.tools.versions import (
    lib_major_to_series,
    parse_ffmpeg_version,
    parse_mediainfo_version,
    parse_mkvpropedit_version,
)
from reframe_testing import fake_tools as ft
from reframe_testing import media

DATA = Path(__file__).parent / "data"

# file, tool, version token, release, series, avcodec, avformat, meets 7.0, "Exiting" line
CASES = [
    (
        ft.DATA_DIR / "ffmpeg_version.stdout.txt",
        "ffmpeg",
        "n9.0.2-17-g2a571b6068-20260930",
        (9, 0, 2),
        (9, 0),
        (63, 1, 102),
        (63, 1, 102),
        True,
        True,
    ),
    (
        ft.DATA_DIR / "ffprobe_version.stdout.txt",
        "ffprobe",
        "n9.0.2-17-g2a571b6068-20260930",
        (9, 0, 2),
        (9, 0),
        (63, 1, 102),
        (63, 1, 102),
        True,
        False,
    ),
    (
        DATA / "ffmpeg-arch-n9.0.2.txt",
        "ffmpeg",
        "n9.0.2",
        (9, 0, 2),
        (9, 0),
        (63, 1, 102),
        (63, 1, 102),
        True,
        True,
    ),
    (
        DATA / "ffprobe-arch-n9.0.2.txt",
        "ffprobe",
        "n9.0.2",
        (9, 0, 2),
        (9, 0),
        (63, 1, 102),
        (63, 1, 102),
        True,
        False,
    ),
    (
        DATA / "ffmpeg-btbn-n8.1.3.txt",
        "ffmpeg",
        "n8.1.3-9-g29e619e767-20260930",
        (8, 1, 3),
        (8, 1),
        (62, 28, 103),
        (62, 12, 103),
        True,
        True,
    ),
    (
        DATA / "ffprobe-btbn-n8.1.3.txt",
        "ffprobe",
        "n8.1.3-9-g29e619e767-20260930",
        (8, 1, 3),
        (8, 1),
        (62, 28, 103),
        (62, 12, 103),
        True,
        False,
    ),
    (
        DATA / "ffmpeg-btbn-n7.1.txt",
        "ffmpeg",
        "n7.1-184-gdc07f98934-20250131",
        (7, 1, 0),
        (7, 1),
        (61, 19, 101),
        (61, 7, 100),
        True,
        False,
    ),
    (
        DATA / "ffmpeg-btbn-n6.1.2.txt",
        "ffmpeg",
        "n6.1.2-21-gac60bc2bb0-20250131",
        (6, 1, 2),
        (6, 1),
        (60, 31, 102),
        (60, 16, 100),
        False,
        False,
    ),
    (
        DATA / "ffmpeg-btbn-master-N-127032.txt",
        "ffmpeg",
        "N-127032-g6ae491a26c-20260930",
        None,
        (9, 0),
        (63, 15, 100),
        (63, 7, 100),
        True,
        True,
    ),
]


@pytest.mark.parametrize(
    ("path", "tool", "token", "release", "series", "avcodec", "avformat", "meets", "exiting"),
    CASES,
    ids=[c[0].name for c in CASES],
)
def test_real_version_outputs(
    path: Path,
    tool: str,
    token: str,
    release: tuple[int, int, int] | None,
    series: tuple[int, int],
    avcodec: tuple[int, int, int],
    avformat: tuple[int, int, int],
    meets: bool,
    exiting: bool,
) -> None:
    text = path.read_text(encoding="utf-8")
    assert ("Exiting with exit code 0" in text) is exiting  # FFmpeg 8+ prints it; it is ignored
    parsed = parse_ffmpeg_version(text)
    assert parsed is not None
    assert parsed.tool == tool
    assert parsed.version == token
    assert parsed.release == release
    assert parsed.is_git_build is (release is None)
    assert parsed.series == series
    assert parsed.libraries["libavcodec"] == avcodec
    assert parsed.libraries["libavformat"] == avformat
    assert set(parsed.libraries) == {
        "libavutil",
        "libavcodec",
        "libavformat",
        "libavdevice",
        "libavfilter",
        "libswscale",
        "libswresample",
    }
    assert parsed.meets_minimum() is meets
    assert parsed.configuration[0].startswith("--prefix=")
    assert all(flag.startswith(("--enable-", "--disable-")) for flag in parsed.build_flags)


def test_build_flags_of_the_pinned_build() -> None:
    parsed = parse_ffmpeg_version((ft.DATA_DIR / "ffmpeg_version.stdout.txt").read_text("utf-8"))
    assert parsed is not None
    for flag in (
        "--enable-gpl",
        "--enable-libx264",
        "--enable-libx265",
        "--enable-libsvtav1",
        "--enable-libopus",
        "--enable-libplacebo",
        "--enable-vulkan",
        "--enable-libvpl",
        "--enable-ffnvcodec",
        "--enable-amf",
        "--enable-vaapi",
    ):
        assert flag in parsed.build_flags
    assert "--disable-libfdk-aac" in parsed.build_flags
    # shlex keeps quoted arguments together.
    assert "--extra-libs=-lgomp -ldl" in parsed.configuration


@pytest.mark.parametrize(
    ("first_line", "token", "release", "series"),
    [
        ("ffmpeg version 7.1.1-1+b1 Copyright (c) 2000-2025", "7.1.1-1+b1", (7, 1, 1), (7, 1)),
        (
            "ffmpeg version 7.0.2-static https://johnvansickle.com/ffmpeg/  Copyright (c) 2000",
            "7.0.2-static https://johnvansickle.com/ffmpeg/",
            (7, 0, 2),
            (7, 0),
        ),
        (
            "ffmpeg version 7.1-full_build-www.gyan.dev Copyright (c) 2000-2024",
            "7.1-full_build-www.gyan.dev",
            (7, 1, 0),
            (7, 1),
        ),
        (
            "ffmpeg version 4.4.2-0ubuntu0.22.04.1 Copyright",
            "4.4.2-0ubuntu0.22.04.1",
            (4, 4, 2),
            (4, 4),
        ),
        ("ffmpeg version n10.0 Copyright", "n10.0", (10, 0, 0), (10, 0)),
        (
            "ffmpeg version 2024-10-10-git-0f5592cfc7-full_build-www.gyan.dev Copyright",
            "2024-10-10-git-0f5592cfc7-full_build-www.gyan.dev",
            None,
            None,
        ),
        ("ffmpeg version N-127271-gba987fe24d", "N-127271-gba987fe24d", None, None),
    ],
)
def test_version_tokens(
    first_line: str,
    token: str,
    release: tuple[int, int, int] | None,
    series: tuple[int, int] | None,
) -> None:
    parsed = parse_ffmpeg_version(first_line + "\n")
    assert parsed is not None
    assert parsed.version == token
    assert parsed.release == release
    assert parsed.series == series  # no library lines: a master build has no known series
    assert parsed.meets_minimum() is (None if series is None else series >= (7, 0))


def test_master_build_series_comes_from_the_library_majors() -> None:
    text = (
        "ffmpeg version N-120000-gabcdef0123\n"
        "libavcodec     61.  3.100 / 61.  3.100\n"
        "libavformat    60. 16.100 / 60. 16.100\n"
    )
    parsed = parse_ffmpeg_version(text)
    assert parsed is not None
    assert parsed.series == (6, 0)  # the older of the two decides
    assert parsed.meets_minimum() is False


# 60 and 63 are also pinned by the master-build tests (the series from the library majors).
@pytest.mark.parametrize(("major", "series"), [(58, 4), (61, 7), (62, 8), (64, 10)])
def test_lib_major_to_series(major: int, series: int) -> None:
    assert lib_major_to_series(major) == series


@pytest.mark.parametrize(
    "text",
    ["", "\n\n", "ffprobe: command not found\n", "mkvpropedit v101.0\n"],
)
def test_not_ffmpeg_output(text: str) -> None:
    assert parse_ffmpeg_version(text) is None


def test_crlf_output() -> None:
    text = (ft.DATA_DIR / "ffmpeg_version.stdout.txt").read_text("utf-8").replace("\n", "\r\n")
    parsed = parse_ffmpeg_version(text)
    assert parsed is not None
    assert parsed.release == (9, 0, 2)
    assert parsed.configuration[-1] == "--extra-version=20260930"


def test_unbalanced_quotes_in_configuration() -> None:
    parsed = parse_ffmpeg_version("ffmpeg version n9.0\nconfiguration: --a='b --enable-x\n")
    assert parsed is not None
    assert parsed.configuration == ["--a='b", "--enable-x"]


def test_mkvpropedit_version() -> None:
    parsed = parse_mkvpropedit_version((DATA / "mkvpropedit-v101.0.txt").read_text("utf-8"))
    assert parsed is not None
    assert parsed.version == "101.0"
    assert parsed.parts == (101, 0)
    assert parse_mkvpropedit_version("mkvmerge v101.0") is None


def test_mediainfo_version() -> None:
    # MediaInfo CLI output format (``mediainfo --Version``); mediainfo is not installed here.
    parsed = parse_mediainfo_version("MediaInfo Command line, \nMediaInfoLib - v24.06\n")
    assert parsed is not None
    assert parsed.version == "24.06"
    assert parse_mediainfo_version("nothing") is None


@pytest.mark.needs_ffmpeg
def test_real_ffmpeg_and_ffprobe_versions_parse() -> None:
    for tool, path in (("ffmpeg", media.find_ffmpeg()), ("ffprobe", media.find_ffprobe())):
        assert path is not None
        out = subprocess.run(
            [path, "-version"], capture_output=True, text=True, timeout=60, check=True
        )
        parsed = parse_ffmpeg_version(out.stdout)
        assert parsed is not None, out.stdout[:200]
        assert parsed.tool == tool
        assert parsed.meets_minimum() is True
        assert "libavcodec" in parsed.libraries
