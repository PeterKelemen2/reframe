"""The name source (03 §Where the name comes from): generic folders, season packs, scores."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from reframe.naming.parse import parse_name
from reframe.naming.source import (
    choose_source,
    find_folder,
    is_generic_folder,
    merge_folder_fields,
    split_extension,
)

HACKSAW_DIR = (
    "Hacksaw.Ridge.2016.HYBRID.2160p.UHD.BluRay.REMUX.TrueHD.7.1.Atmos.DoVi.HDR.HEVC.HUN-HenDerson"
)
SOPRANOS_DIR = "The.Sopranos.S03.1080p.BluRay.REMUX-Kataklysm"
SOPRANOS_E02 = "The.Sopranos.S03E02.Proshai.Livushka.1080p.BluRay.REMUX-Kataklysm.mkv"


@pytest.mark.parametrize(
    "name",
    [
        "Season 03", "season.10", "SEASON_1", "S03", "Specials", "Special", "Extras", "extra",
        "Featurettes", "Disc 1", "Disk2", "CD1", "BDMV", "STREAM", "VIDEO_TS",
    ],
)  # fmt: skip
def test_generic_folders(name: str) -> None:
    assert is_generic_folder(name)


@pytest.mark.parametrize(
    "name",
    [
        "Season of the Witch",
        "S03E02",
        "Extras (2005)",
        "BDMV2",
        "Streamers",
        SOPRANOS_DIR,
    ],
)
def test_not_generic(name: str) -> None:
    assert not is_generic_folder(name)


@pytest.mark.parametrize(
    ("name", "stem", "ext"),
    [
        ("movie.MKV", "movie", "mkv"),
        ("VTS_01_1.VOB", "VTS_01_1", "vob"),
        (
            "The.Sopranos.S03.1080p.BluRay.REMUX-Kataklysm",
            "The.Sopranos.S03.1080p.BluRay.REMUX-Kataklysm",
            "",
        ),
        (".mkv", ".mkv", ""),
    ],
)
def test_split_extension(name: str, stem: str, ext: str) -> None:
    assert split_extension(name) == (stem, ext)


# --------------------------------------------------------------------------- generic folders


def test_skip_generic_folders_at_most_two_levels() -> None:
    file = Path("/lib/Movie.2016.1080p.BluRay-GRP/BDMV/STREAM/00800.m2ts")
    assert find_folder(file, None) == (Path("/lib/Movie.2016.1080p.BluRay-GRP"), ["STREAM", "BDMV"])
    deep = Path("/lib/Show/Season 1/Disc 1/CD1/x.mkv")
    assert find_folder(deep, None) == (None, ["CD1", "Disc 1", "Season 1"])


def test_skipping_never_goes_above_the_root() -> None:
    file = Path("/lib/Show/Season 03/x.mkv")
    assert find_folder(file, Path("/lib")) == (Path("/lib/Show"), ["Season 03"])
    # The user opened the generic folder itself: no usable folder name.
    assert find_folder(file, Path("/lib/Show/Season 03")) == (None, ["Season 03"])
    # The opened folder itself can be the name source (a release folder).
    release = Path(f"/lib/{HACKSAW_DIR}/hacksawridge.mkv")
    assert find_folder(release, Path(f"/lib/{HACKSAW_DIR}")) == (Path(f"/lib/{HACKSAW_DIR}"), [])


def test_root_that_does_not_hold_the_file_is_ignored() -> None:
    file = Path("/lib/Show/Season 03/x.mkv")
    assert find_folder(file, Path("/elsewhere")) == (Path("/lib/Show"), ["Season 03"])


def test_no_folder_name() -> None:
    assert find_folder(Path("/x.mkv"), None) == (None, [])
    assert find_folder(Path("x.mkv"), None) == (None, [])
    assert find_folder(Path("/Season 1/x.mkv"), None) == (None, ["Season 1"])


# --------------------------------------------------------------------------- choosing


def test_hacksaw_ridge_picks_the_folder(fake_fs: Any) -> None:
    file = Path(f"/lib/{HACKSAW_DIR}/hacksawridge.2160p.remux-henderson.mkv")
    choice = choose_source(file, "auto", root=None, fs=fake_fs())
    assert choice.kind == "folder"
    assert choice.reason == (
        "Folder name: 8 fields recognised, title with word separators (10 points); "
        "file name: 3 fields recognised (3 points)"
    )
    assert choice.fields.main_title == "Hacksaw.Ridge"
    assert choice.text == HACKSAW_DIR
    assert choice.separator == "."
    assert [c.kind for c in choice.candidates] == ["file", "folder"]
    assert choice.candidates[1].recognised == [
        "title", "year", "resolution", "source", "video_codec", "audio_codec", "hdr",
        "release_group",
    ]  # fmt: skip
    assert choice.candidates[0].recognised == ["title", "resolution", "release_group"]


def test_sopranos_season_pack_picks_the_file(fake_fs: Any) -> None:
    folder = Path(f"/lib/{SOPRANOS_DIR}")
    fs = fake_fs(
        {
            folder: [
                SOPRANOS_E02,
                SOPRANOS_E02.replace("E02.Proshai.Livushka", "E03.Fortunate.Son"),
                "info.nfo",
            ]
        }
    )
    choice = choose_source(folder / SOPRANOS_E02, "auto", root=None, fs=fs)
    assert choice.kind == "file"
    assert choice.season_pack
    assert choice.reason.startswith("Season pack: the folder holds 2 episode files")
    assert choice.fields.main_title == "The.Sopranos.S03E02.Proshai.Livushka"
    assert fs.listed == [folder]


def test_only_the_file_has_an_episode_number(fake_fs: Any) -> None:
    """Decision 0012: the folder cannot be listed (or holds only this file), and only the
    file name has an episode number: the file name is the source, and the folder fills."""
    folder = Path("/lib/Breaking Bad (2008)")
    choice = choose_source(folder / "breaking.bad.s01e01.mkv", "auto", root=None, fs=fake_fs())
    assert choice.kind == "file"
    assert choice.season_pack
    assert choice.reason == "Only the file name has an episode number (s01e01), so it is used"
    assert choice.fields.year == 2008
    assert choice.notes == ["The folder name fills: year."]


def test_tie_goes_to_the_file(fake_fs: Any) -> None:
    file = Path(
        "/lib/Inception.2010.1080p.BluRay.x264-SPARKS/inception.2010.1080p.bluray.x264-sparks.mkv"
    )
    choice = choose_source(file, "auto", root=None, fs=fake_fs())
    assert choice.kind == "file"
    assert choice.reason.endswith("A tie goes to the file name")


def test_file_wins_on_score(fake_fs: Any) -> None:
    file = Path("/lib/The Matrix (1999)/The.Matrix.1999.1080p.BluRay.x264-AMIABLE.mkv")
    choice = choose_source(file, "auto", root=None, fs=fake_fs())
    assert choice.kind == "file"
    assert choice.reason.startswith(
        "File name: 6 fields recognised, title with word separators (8 points)"
    )


def test_forced_modes(fake_fs: Any) -> None:
    file = Path(f"/lib/{HACKSAW_DIR}/hacksawridge.2160p.remux-henderson.mkv")
    forced_file = choose_source(file, "file", root=None, fs=fake_fs())
    assert (forced_file.kind, forced_file.reason) == (
        "file",
        "File name (set in the naming options)",
    )
    assert forced_file.fields.main_title == "hacksawridge"
    forced_folder = choose_source(file, "folder", root=None, fs=fake_fs(), forced_by="this job")
    assert (forced_folder.kind, forced_folder.reason) == ("folder", "Folder name (set in this job)")


def test_forced_folder_without_a_folder(fake_fs: Any) -> None:
    choice = choose_source(Path("/Season 1/x.mkv"), "folder", root=None, fs=fake_fs())
    assert choice.kind == "file"
    assert (
        choice.reason
        == "Folder name is set in the naming options, but the folder is generic: file name"
    )
    choice = choose_source(Path("/x.mkv"), "auto", root=None, fs=fake_fs())
    assert (choice.kind, choice.reason) == ("file", "File name: there is no folder name")
    assert [c.kind for c in choice.candidates] == ["file"]


def test_forced_file_still_merges_a_season_pack(fake_fs: Any) -> None:
    folder = Path("/lib/Breaking.Bad.S01.1080p.BluRay.x264-ROVERS")
    choice = choose_source(
        folder / "S01E01.mkv", "file", root=None, fs=fake_fs({folder: ["S01E01.mkv", "S01E02.mkv"]})
    )
    assert choice.kind == "file"
    assert choice.fields.main_title == "Breaking.Bad.S01E01"


def test_disc_folders_are_not_season_packs(fake_fs: Any) -> None:
    folder = Path("/lib/The.Third.Man.1949.PAL.DVDR-iNTENSiTY/VIDEO_TS")
    fs = fake_fs({folder: ["VTS_01_1.VOB", "VTS_01_2.VOB"]})
    choice = choose_source(folder / "VTS_01_1.VOB", "auto", root=None, fs=fs)
    assert choice.kind == "folder"
    assert not choice.season_pack
    assert choice.skipped == ["VIDEO_TS"]
    assert choice.notes == ["Skipped the generic folder 'VIDEO_TS'."]
    assert fs.listed == []


def test_generic_season_folder_is_listed_for_the_season_pack(fake_fs: Any) -> None:
    season = Path("/lib/Breaking Bad (2008)/Season 05")
    fs = fake_fs(
        {
            season: [
                "Breaking Bad - S05E14 - Ozymandias.mkv",
                "Breaking Bad - S05E15 - Granite State.mkv",
            ]
        }
    )
    choice = choose_source(
        season / "Breaking Bad - S05E14 - Ozymandias.mkv", "auto", root=Path("/lib"), fs=fs
    )
    assert choice.kind == "file"
    assert choice.season_pack
    assert choice.folder == Path("/lib/Breaking Bad (2008)")
    assert choice.fields.year == 2008


def test_one_episode_file_is_not_a_season_pack_when_both_have_an_episode(fake_fs: Any) -> None:
    folder = Path("/lib/Game.of.Thrones.S08E06.1080p.WEB.H264-MEMENTO")
    fs = fake_fs({folder: ["gameofthrones.s08e06.1080p.web.h264-memento.mkv", "memento.nfo"]})
    choice = choose_source(
        folder / "gameofthrones.s08e06.1080p.web.h264-memento.mkv", "auto", root=None, fs=fs
    )
    assert choice.kind == "folder"
    assert not choice.season_pack


# --------------------------------------------------------------------------- merging


def test_merge_fills_missing_fields_only() -> None:
    file = parse_name("doctor.who.s01e01").fields
    folder = parse_name("Doctor.Who.2005.S01.1080p.BluRay.x264-SHORTBREHD").fields
    merged, filled = merge_folder_fields(file, folder)
    assert filled == ["year", "source_type", "release_group", "resolution"]
    assert (merged.year, merged.source_type, merged.release_group) == (2005, "BluRay", "SHORTBREHD")
    assert merged.name == "doctor.who"  # the file's own name stays
    assert merged.main_title == "doctor.who.s01e01"


def test_merge_converts_the_folder_text_to_the_file_separator() -> None:
    file = parse_name("01 - The Crocodile's Dilemma").fields
    folder = parse_name("Fargo.S01.1080p.BluRay.x264-ROVERS").fields
    merged, filled = merge_folder_fields(file, folder)
    assert filled[0] == "name"
    assert merged.name == "Fargo"
    assert merged.main_title == "Fargo - 01 - The Crocodile's Dilemma"
    assert merged.season == 1
    file = parse_name("S01E01").fields
    merged, _ = merge_folder_fields(
        file, parse_name("Breaking.Bad.S01.1080p.BluRay.x264-ROVERS").fields
    )
    assert (merged.name, merged.main_title) == ("Breaking.Bad", "Breaking.Bad.S01E01")
    file = parse_name("Show Name - 01").fields
    merged, _ = merge_folder_fields(file, parse_name("Show.Name.S02.UHD.BluRay-GRP").fields)
    assert merged.source_type == "UHD BluRay"
