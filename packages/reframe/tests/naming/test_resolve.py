"""``resolve_output_name``: 03 §Examples, the M2 demo (item 5), job overrides, extensions,
output folders and bad templates."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from reframe.models import (
    AudioOutputTrack,
    AudioStream,
    Chapter,
    ChapterSettings,
    JobNaming,
    JobSettings,
    MediaSource,
    NameResult,
    NamingOptions,
    OutputSettings,
    Severity,
    SourceRef,
    SubtitleOutputTrack,
    SubtitleStream,
)
from reframe.naming import RealNamingFs, check_template, output_extension, resolve_output_name

HACKSAW = Path(
    "/media/Hacksaw.Ridge.2016.HYBRID.2160p.UHD.BluRay.REMUX.TrueHD.7.1.Atmos.DoVi.HDR.HEVC."
    "HUN-HenDerson/hacksawridge.2160p.remux-henderson.mkv"
)
SOPRANOS = Path(
    "/media/The.Sopranos.S03.1080p.BluRay.REMUX-Kataklysm/"
    "The.Sopranos.S03E02.Proshai.Livushka.1080p.BluRay.REMUX-Kataklysm.mkv"
)

#: 03 §Examples, "Output to MKV at 1080p": template, separator, Hacksaw Ridge, Sopranos.
EXAMPLES = [
    ("{main_title}", "keep", "Hacksaw.Ridge.mkv", "The.Sopranos.S03E02.Proshai.Livushka.mkv"),
    (
        "{main_title}.{resolution}",
        "keep",
        "Hacksaw.Ridge.1080p.mkv",
        "The.Sopranos.S03E02.Proshai.Livushka.1080p.mkv",
    ),
    (
        "{name}< ({year})>< - S{season:02}E{episode:02}>< - {sub_title}>",
        "space",
        "Hacksaw Ridge (2016).mkv",
        "The Sopranos - S03E02 - Proshai Livushka.mkv",
    ),
    (
        "{name}/<Season {season:02}/>{main_title}",
        "keep",
        "Hacksaw.Ridge/Hacksaw.Ridge.mkv",
        "The.Sopranos/Season 03/The.Sopranos.S03E02.Proshai.Livushka.mkv",
    ),
    (
        "{source}-{title}",
        "keep",
        "Hacksaw.Ridge.2016.HYBRID.2160p.UHD.BluRay.REMUX.TrueHD.7.1.Atmos.DoVi.HDR.HEVC.HUN-HenDerson-1.mkv",
        "The.Sopranos.S03E02.Proshai.Livushka.1080p.BluRay.REMUX-Kataklysm-1.mkv",
    ),
]


@pytest.mark.parametrize(("template", "separator", "hacksaw", "sopranos"), EXAMPLES)
def test_examples_of_03(
    template: str, separator: Any, hacksaw: str, sopranos: str, empty_fs: Any, now: datetime
) -> None:
    options = NamingOptions(
        movie_template=template, episode_template=template, word_separator=separator
    )
    for file, expected in ((HACKSAW, hacksaw), (SOPRANOS, sopranos)):
        result = resolve_output_name(file, options, output_size=(1920, 1080), fs=empty_fs, now=now)
        assert result.relative_path == expected
        assert result.path == file.parent / expected
        assert result.issues == []


def test_demo_hacksaw_ridge(empty_fs: Any, now: datetime) -> None:
    """M2 demo item 5: the folder name, ``Hacksaw.Ridge``."""
    result = resolve_output_name(HACKSAW, NamingOptions(), fs=empty_fs, now=now)
    assert result.source == "folder"
    assert result.fields.main_title == "Hacksaw.Ridge"
    assert result.relative_path == "Hacksaw.Ridge.mkv"
    assert result.template_kind == "movie"
    assert result.season_pack is False


def test_demo_sopranos(fake_fs: Any, now: datetime) -> None:
    """M2 demo item 5: ``The.Sopranos.S03E02.Proshai.Livushka``, from the file name — with
    the season pack listed, and with the folder not readable."""
    other = SOPRANOS.name.replace("E02.Proshai.Livushka", "E01.Mr.Ruggerios.Neighborhood")
    for fs in (fake_fs({SOPRANOS.parent: [SOPRANOS.name, other]}), fake_fs()):
        result = resolve_output_name(SOPRANOS, NamingOptions(), fs=fs, now=now)
        assert result.source == "file"
        assert result.season_pack is True
        assert result.fields.main_title == "The.Sopranos.S03E02.Proshai.Livushka"
        assert result.relative_path == "The.Sopranos.S03E02.Proshai.Livushka.mkv"
        assert result.template_kind == "episode"


def test_result_round_trips(empty_fs: Any, now: datetime) -> None:
    result = resolve_output_name(HACKSAW, NamingOptions(), fs=empty_fs, now=now)
    assert NameResult.model_validate_json(result.model_dump_json()) == result
    spans = {span.field: span.text for span in result.candidates[1].spans}
    assert spans["name"] == "Hacksaw.Ridge"
    assert spans["year"] == "2016"
    assert spans["source_type"] == "UHD.BluRay"
    assert spans["release_group"] == "HenDerson"
    text = result.candidates[1].text
    assert all(text[s.start : s.end] == s.text for s in result.candidates[1].spans)


def test_movie_and_episode_templates(empty_fs: Any) -> None:
    options = NamingOptions(movie_template="M {name}", episode_template="E {name}")
    assert resolve_output_name(HACKSAW, options, fs=empty_fs).relative_path == "M Hacksaw.Ridge.mkv"
    assert resolve_output_name(SOPRANOS, options, fs=empty_fs).relative_path == "E The.Sopranos.mkv"


# --------------------------------------------------------------------------- the job's naming


def _job(**naming: Any) -> JobSettings:
    return JobSettings(
        source=SourceRef(path=HACKSAW), output=OutputSettings(naming=JobNaming(**naming))
    )


def test_job_template_replaces_both_templates(empty_fs: Any) -> None:
    result = resolve_output_name(
        HACKSAW, NamingOptions(), job=_job(template="{name} ({year})"), fs=empty_fs
    )
    assert result.relative_path == "Hacksaw.Ridge (2016).mkv"
    assert result.template == "{name} ({year})"


def test_job_name_source(empty_fs: Any) -> None:
    result = resolve_output_name(
        HACKSAW, NamingOptions(), job=_job(name_source="file"), fs=empty_fs
    )
    assert result.source == "file"
    assert result.reason == "File name (set in this job)"
    assert result.relative_path == "hacksawridge.mkv"


def test_manual_name(empty_fs: Any) -> None:
    job = _job(mode="manual", manual_name="My Movie: Final")
    result = resolve_output_name(HACKSAW, NamingOptions(), job=job, fs=empty_fs)
    assert result.template_kind == "manual"
    assert result.relative_path == "My Movie - Final.mkv"
    # A typed extension is not doubled; a slash is not a folder.
    job = _job(mode="manual", manual_name="a/b.MKV")
    assert (
        resolve_output_name(HACKSAW, NamingOptions(), job=job, fs=empty_fs).relative_path
        == "a-b.mkv"
    )


def test_empty_manual_name_uses_the_template(empty_fs: Any) -> None:
    result = resolve_output_name(HACKSAW, NamingOptions(), job=_job(mode="manual"), fs=empty_fs)
    assert result.relative_path == "Hacksaw.Ridge.mkv"
    [issue] = result.issues
    assert (issue.code, issue.severity) == ("naming.manual_name_empty", Severity.WARNING)


def test_field_overrides(empty_fs: Any) -> None:
    job = _job(field_overrides={"name": "Hacksaw Ridge", "year": "2017", "edition": "IMAX"})
    options = NamingOptions(movie_template="{main_title} ({year}) {edition}")
    result = resolve_output_name(HACKSAW, options, job=job, fs=empty_fs)
    assert result.relative_path == "Hacksaw Ridge (2017) IMAX.mkv"
    assert result.notes == ["Edited for this file: name, year, edition."]


def test_field_overrides_change_main_title_parts(empty_fs: Any) -> None:
    job = JobSettings(
        source=SourceRef(path=SOPRANOS),
        output=OutputSettings(
            naming=JobNaming(
                field_overrides={"sub_title": "Proshai, Livushka", "season": "3", "episode": "2"}
            )
        ),
    )
    result = resolve_output_name(SOPRANOS, NamingOptions(), job=job, fs=empty_fs)
    assert result.relative_path == "The.Sopranos.S03E02.Proshai, Livushka.mkv"
    job.output.naming.field_overrides = {"sub_title": "", "main_title": "Sopranos 3x02"}
    result = resolve_output_name(SOPRANOS, NamingOptions(), job=job, fs=empty_fs)
    assert result.relative_path == "Sopranos 3x02.mkv"
    assert result.fields.sub_title is None


def test_bad_field_overrides(empty_fs: Any) -> None:
    job = _job(field_overrides={"year": "twenty", "colour": "red", "season": "4"})
    result = resolve_output_name(HACKSAW, NamingOptions(), job=job, fs=empty_fs)
    assert [i.code for i in result.issues] == ["naming.bad_override", "naming.unknown_override"]
    assert result.issues[0].path == "output.naming.field_overrides.year"
    assert result.issues[0].fixes[0].patch[0].path == "/output/naming/field_overrides/year"
    assert result.fields.year == 2016
    assert (result.fields.season, result.fields.kind, result.template_kind) == (
        4,
        "episode",
        "episode",
    )


@pytest.mark.parametrize(
    ("key", "number"),
    [
        # str.isdigit() is True, int() fails:
        pytest.param("season", "²", id="superscript-two"),
        pytest.param("episode", "1²", id="one-superscript-two"),
        # str.isdigit() is True, int() accepts them:
        pytest.param("year", "\u0663", id="arabic-indic-three"),
        pytest.param("season", "\u06f3", id="extended-arabic-indic-three"),
        pytest.param("episode", "\uff13", id="full-width-three"),
        pytest.param("year", "1" * 10, id="10-digits"),
        # int() refuses more than 4300 digits
        pytest.param("season", "9" * 5000, id="5000-digits"),
        pytest.param("episode", "+3", id="plus"),
        pytest.param("year", "-3", id="minus"),
        pytest.param("season", "3.0", id="decimal"),
        pytest.param("episode", " 3 4", id="two-numbers"),
    ],
)
def test_number_overrides_take_only_ascii_digits(key: str, number: str, empty_fs: Any) -> None:
    """A number override is 1 to 9 ASCII digits; anything else is a warning, never an
    exception, and the parsed value stays."""
    job = _job(field_overrides={key: number})
    result = resolve_output_name(SOPRANOS, NamingOptions(), job=job, fs=empty_fs)
    [issue] = result.issues
    assert (issue.code, issue.severity) == ("naming.bad_override", Severity.WARNING)
    assert issue.path == f"output.naming.field_overrides.{key}"
    assert (result.fields.season, result.fields.episode, result.fields.year) == (3, 2, None)
    assert result.relative_path == "The.Sopranos.S03E02.Proshai.Livushka.mkv"


def test_number_overrides_strip_spaces_and_keep_leading_zeros(empty_fs: Any) -> None:
    job = _job(field_overrides={"season": " 007 ", "episode": "123456789", "year": ""})
    result = resolve_output_name(SOPRANOS, NamingOptions(), job=job, fs=empty_fs)
    assert not result.issues
    assert (result.fields.season, result.fields.episode, result.fields.year) == (7, 123456789, None)


# --------------------------------------------------------------------------- bad templates


def test_bad_template_gives_issues_and_the_file_name(empty_fs: Any) -> None:
    options = NamingOptions(movie_template="{nmae} {year")
    result = resolve_output_name(HACKSAW, options, fs=empty_fs)
    assert result.relative_path == "hacksawridge.2160p.remux-henderson.mkv"
    assert {i.code for i in result.issues} == {"naming.template_syntax", "naming.unknown_variable"}
    assert "The naming template has errors: the source file name is used." in result.notes


def test_huge_format_spec_gives_an_issue_and_the_file_name(empty_fs: Any) -> None:
    """``reframe name --template "{season:999999999999}"`` printed a ``MemoryError``."""
    result = resolve_output_name(
        SOPRANOS, NamingOptions(), job=_job(template="{season:999999999999}"), fs=empty_fs
    )
    assert result.relative_path == (
        "The.Sopranos.S03E02.Proshai.Livushka.1080p.BluRay.REMUX-Kataklysm.mkv"
    )
    assert [i.code for i in result.issues] == ["naming.bad_format_spec"]


def test_empty_template_falls_back_to_the_file_name(empty_fs: Any) -> None:
    result = resolve_output_name(HACKSAW, NamingOptions(movie_template=""), fs=empty_fs)
    assert result.relative_path == "hacksawridge.2160p.remux-henderson.mkv"
    assert [i.code for i in result.issues] == ["naming.empty_template"]


def test_empty_render_falls_back_to_the_file_name(empty_fs: Any) -> None:
    result = resolve_output_name(
        HACKSAW, NamingOptions(movie_template="<{sub_title}>"), fs=empty_fs
    )
    assert result.relative_path == "hacksawridge.2160p.remux-henderson.mkv"
    assert result.notes[-1].startswith("The file name was empty")


# --------------------------------------------------------------------------- folders, extensions


def test_fixed_output_folder(empty_fs: Any) -> None:
    options = NamingOptions(output_folder_mode="fixed", output_folder=Path("/out"))
    result = resolve_output_name(HACKSAW, options, fs=empty_fs)
    assert result.path == Path("/out/Hacksaw.Ridge.mkv")
    options = NamingOptions(output_folder_mode="fixed")
    result = resolve_output_name(HACKSAW, options, fs=empty_fs)
    assert result.path is None
    assert [i.code for i in result.issues] == ["naming.no_output_folder"]


def test_container_extension(empty_fs: Any) -> None:
    assert (
        resolve_output_name(HACKSAW, NamingOptions(), container="webm", fs=empty_fs).extension
        == "webm"
    )
    assert (
        resolve_output_name(HACKSAW, NamingOptions(), container="mp4", fs=empty_fs).relative_path
        == "Hacksaw.Ridge.mp4"
    )
    m4v = NamingOptions(mp4_extension="m4v")
    assert (
        resolve_output_name(HACKSAW, m4v, container="mp4", fs=empty_fs).relative_path
        == "Hacksaw.Ridge.m4v"
    )
    assert resolve_output_name(HACKSAW, m4v, container="mkv", fs=empty_fs).extension == "mkv"


def _mp4_job(**kwargs: Any) -> JobSettings:
    return JobSettings(
        source=SourceRef(path=HACKSAW),
        output=OutputSettings(container="mp4"),
        **{"chapters": ChapterSettings(enabled=False), **kwargs},
    )


def test_mp4_auto_extension() -> None:
    """HandBrake's rule: ``.m4v`` with AC-3 audio, chapter markers or 3GPP subtitles."""
    auto = NamingOptions(mp4_extension="auto")
    source = MediaSource(
        ref=SourceRef(path=HACKSAW),
        audio=[AudioStream(index=1, codec="ac3"), AudioStream(index=2, codec="aac")],
        subtitles=[
            SubtitleStream(index=3, codec="mov_text"),
            SubtitleStream(index=4, codec="subrip"),
        ],
        chapters=[Chapter(index=0, start=0, end=10)],
    )
    assert output_extension("mp4", auto) == "mp4"  # no job
    assert output_extension("mp4", auto, _mp4_job(), source) == "mp4"
    assert (
        output_extension("mp4", auto, _mp4_job(audio=[AudioOutputTrack(encoder="ac3")]), source)
        == "m4v"
    )
    aac = _mp4_job(audio=[AudioOutputTrack(source_stream=2, encoder="aac")])
    assert output_extension("mp4", auto, aac, source) == "mp4"
    passthru = _mp4_job(audio=[AudioOutputTrack(source_stream=1, action="passthru")])
    assert output_extension("mp4", auto, passthru, source) == "m4v"
    assert output_extension("mp4", auto, passthru, None) == "mp4"  # codec unknown
    chapters = _mp4_job(chapters=ChapterSettings(enabled=True))
    assert output_extension("mp4", auto, chapters, source) == "m4v"
    assert output_extension("mp4", auto, chapters, None) == "mp4"
    generated = _mp4_job(chapters=ChapterSettings(enabled=True, generate_every=5))
    assert output_extension("mp4", auto, generated, None) == "m4v"
    tx3g = _mp4_job(
        subtitles=[SubtitleOutputTrack(source=4, action="convert", convert_to="mov_text")]
    )
    assert output_extension("mp4", auto, tx3g, source) == "m4v"
    copied = _mp4_job(subtitles=[SubtitleOutputTrack(source=3)])
    assert output_extension("mp4", auto, copied, source) == "m4v"
    srt = _mp4_job(subtitles=[SubtitleOutputTrack(source=4)])
    assert output_extension("mp4", auto, srt, source) == "mp4"
    assert output_extension("mkv", auto, chapters, source) == "mkv"


def test_job_container_wins(empty_fs: Any) -> None:
    job = JobSettings(source=SourceRef(path=HACKSAW), output=OutputSettings(container="webm"))
    result = resolve_output_name(HACKSAW, NamingOptions(), job=job, container="mp4", fs=empty_fs)
    assert result.relative_path == "Hacksaw.Ridge.webm"


# --------------------------------------------------------------------------- the real file system


def test_real_file_system(tmp_path: Path) -> None:
    """Without ``fs``, naming lists the real folder and reads the real file times."""
    folder = tmp_path / "Breaking.Bad.S01.1080p.BluRay.x264-ROVERS"
    folder.mkdir()
    for name in ("S01E01.mkv", "S01E02.mkv"):
        (folder / name).write_bytes(b"")
    (folder / "Subs").mkdir()
    options = NamingOptions(episode_template="{main_title} {modification-date}")
    result = resolve_output_name(folder / "S01E01.mkv", options, root=tmp_path)
    assert result.season_pack
    expected = datetime.fromtimestamp((folder / "S01E01.mkv").stat().st_mtime).strftime("%Y-%m-%d")
    assert result.relative_path == f"Breaking.Bad.S01E01 {expected}.mkv"


posix_only = pytest.mark.skipif(
    sys.platform == "win32", reason="Windows file names are UTF-16: no name holds the byte 0xFF"
)


@posix_only
def test_a_file_name_that_is_not_utf8(tmp_path: Path) -> None:
    """``reframe name DIR`` with a real file ``bad\\xffname.mkv``: the byte becomes ``�``
    (0012 follow-up) in the output name and in every text of the result; only the real paths
    keep it."""
    media = tmp_path / "media"
    media.mkdir()
    file = media / os.fsdecode(b"bad\xffname.mkv")
    file.write_bytes(b"placeholder")
    assert file.name == "bad\udcffname.mkv"
    result = resolve_output_name(file, NamingOptions(), root=media, fs=RealNamingFs())
    assert result.source == "file"
    assert result.relative_path == "bad�name.mkv"
    assert result.path == media / "bad�name.mkv"
    assert os.fsencode(result.path).endswith("bad�name.mkv".encode())
    assert result.fields.main_title == "bad�name"
    assert result.variables["file_name"] == "bad�name"
    assert result.candidates[0].text == "bad�name"
    assert result.candidates[0].path == file  # the real file
    assert result.notes[0].startswith("Replaced bytes that are not UTF-8 with '�'")
    assert not result.issues
    result.fields.model_dump_json()  # no surrogates left in the parsed text
    json.dumps(result.variables, ensure_ascii=False).encode("utf-8")
    # A template of other variables, and the file name as the fallback.
    job = _job(template="<{sub_title}>")
    assert resolve_output_name(file, NamingOptions(), job=job, root=media).relative_path == (
        "bad�name.mkv"
    )


@posix_only
def test_a_folder_name_that_is_not_utf8(tmp_path: Path) -> None:
    """The folder wins: its name gives the output name; the output stays in the real folder."""
    folder = tmp_path / os.fsdecode(b"Movie.2016.1080p.BluRay.x264-GR\xffP")
    folder.mkdir()
    file = folder / "movie.mkv"
    file.write_bytes(b"placeholder")
    options = NamingOptions(movie_template="{main_title} [{release_group}] {folder_name}")
    result = resolve_output_name(file, options, root=tmp_path, fs=RealNamingFs())
    assert result.source == "folder"
    assert result.relative_path == ("Movie [GR�P] Movie.2016.1080p.BluRay.x264-GR�P.mkv")
    assert result.path is not None
    assert result.path.parent == folder
    assert b"\xff" in os.fsencode(result.path.parent)
    assert result.notes[0].startswith("Replaced bytes that are not UTF-8")


def test_check_template_and_names_with_surrogates() -> None:
    """Lone surrogates in a template or a manual name (text from the API can hold them) are
    never an exception, and never reach the output name."""
    assert check_template("{name}\udcff<{date:%Y\ud800}>") == []
    job = _job(template="{main_title}\udcff\ud800")
    result = resolve_output_name(HACKSAW, NamingOptions(), job=job, fs=RealNamingFs())
    assert result.relative_path == "Hacksaw.Ridge��.mkv"
    job = _job(mode="manual", manual_name="My\udcffMovie")
    result = resolve_output_name(HACKSAW, NamingOptions(), job=job, fs=RealNamingFs())
    assert result.relative_path == "My�Movie.mkv"


def test_real_file_system_errors(tmp_path: Path) -> None:
    fs = RealNamingFs()
    assert fs.list_files(tmp_path / "missing") is None
    assert fs.file_times(tmp_path / "missing.mkv") is None
    (tmp_path / "a.mkv").write_bytes(b"")
    (tmp_path / "dir").mkdir()
    assert fs.list_files(tmp_path) == ["a.mkv"]
    times = fs.file_times(tmp_path / "a.mkv")
    assert times is not None
    assert times.modified.tzinfo is not None
