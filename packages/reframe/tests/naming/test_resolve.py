"""``resolve_output_name``: 03 §Examples, the M2 demo (item 5), job overrides, extensions,
output folders and bad templates."""

from __future__ import annotations

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
from reframe.naming import RealNamingFs, output_extension, resolve_output_name

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


# --------------------------------------------------------------------------- bad templates


def test_bad_template_gives_issues_and_the_file_name(empty_fs: Any) -> None:
    options = NamingOptions(movie_template="{nmae} {year")
    result = resolve_output_name(HACKSAW, options, fs=empty_fs)
    assert result.relative_path == "hacksawridge.2160p.remux-henderson.mkv"
    assert {i.code for i in result.issues} == {"naming.template_syntax", "naming.unknown_variable"}
    assert "The naming template has errors: the source file name is used." in result.notes


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
