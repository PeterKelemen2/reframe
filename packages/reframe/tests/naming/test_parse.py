"""Release-name parsing: position-preserving fields, spans and scores (03 §Variables)."""

from __future__ import annotations

import pytest

from reframe.naming import parse as parse_module
from reframe.naming.parse import (
    SCORED_FIELDS,
    clean_tag,
    clean_text,
    detect_separator,
    guess_matches,
    parse_name,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (" - Rose ", "Rose"),
        (".A.Scandal.in.Belgravia", "A.Scandal.in.Belgravia"),
        ("Mad Max Fury Road (", "Mad Max Fury Road"),
        ("] Sousou", "Sousou"),
        ("Show Name (2019) - S01E02", "Show Name (2019) - S01E02"),
        ("Silence)", "Silence"),
        ("(US", "US"),
        ("---", ""),
        ("", ""),
    ],
)
def test_clean_text(text: str, expected: str) -> None:
    assert clean_text(text) == expected


def test_clean_tag() -> None:
    assert clean_tag("[1080p]") == "1080p"
    assert clean_tag("(BD ") == "BD"


@pytest.mark.parametrize(
    ("text", "separator"),
    [
        ("The.Sopranos.S03E02", "."),
        ("Show Name - S01E02", " "),
        ("The_Office_US", "_"),
        ("Mr. Robot", " "),
        ("the-sopranos-s03e02", "-"),
        ("WALL-E", None),
        ("hacksawridge", None),
    ],
)
def test_detect_separator(text: str, separator: str | None) -> None:
    assert detect_separator(text) == separator


def test_movie_fields_and_spans() -> None:
    text = (
        "Hacksaw.Ridge.2016.HYBRID.2160p.UHD.BluRay.REMUX.TrueHD.7.1.Atmos.DoVi.HDR.HEVC."
        "HUN-HenDerson"
    )
    parsed = parse_name(text)
    fields = parsed.fields
    assert fields.kind == "movie"
    assert (fields.main_title, fields.name, fields.year) == ("Hacksaw.Ridge", "Hacksaw.Ridge", 2016)
    assert (fields.source_type, fields.release_group, fields.resolution) == (
        "UHD.BluRay",
        "HenDerson",
        "2160p",
    )
    assert fields.separator == "."
    assert parsed.score == 10
    assert parsed.word_separators
    assert not parsed.has_episode
    by_field = {span.field: span.text for span in parsed.spans}
    assert by_field["name"] == "Hacksaw.Ridge"
    assert by_field["resolution"] == "2160p"
    assert by_field["hdr"] in ("DoVi", "HDR")
    for span in parsed.spans:
        assert text[span.start : span.end] == span.text
    assert [s.start for s in parsed.spans] == sorted(s.start for s in parsed.spans)


def test_episode_fields_and_spans() -> None:
    text = "Doctor.Who.2005.S01E01.Rose.1080p.BluRay.x264-SHORTBREHD"
    parsed = parse_name(text)
    fields = parsed.fields
    assert fields.kind == "episode"
    assert fields.main_title == "Doctor.Who.2005.S01E01.Rose"
    assert (fields.name, fields.year, fields.sub_title) == ("Doctor.Who", 2005, "Rose")
    assert (fields.season, fields.episode, fields.episodes, fields.episode_code) == (
        1,
        1,
        [1],
        "S01E01",
    )
    spans = [(s.field, s.text) for s in parsed.spans]
    assert spans[:5] == [
        ("name", "Doctor.Who"),
        ("year", "2005"),
        ("episode_code", "S01E01"),
        ("sub_title", "Rose"),
        ("resolution", "1080p"),
    ]


def test_year_inside_the_episode_code() -> None:
    """guessit also reports ``S2023E01`` as the year 2023; it is not a tag that cuts."""
    fields = parse_name("Show.Name.S2023E01.Title.1080p.WEB.h264-GRP").fields
    assert (fields.season, fields.year, fields.episode_code) == (2023, 2023, "S2023E01")
    assert fields.main_title == "Show.Name.S2023E01.Title"


def test_season_folder_names() -> None:
    fields = parse_name("Breaking.Bad.Season.5.1080p.BluRay.x264-GRP").fields
    assert (fields.name, fields.season, fields.episode, fields.episode_code) == (
        "Breaking.Bad",
        5,
        None,
        "Season.5",
    )
    fields = parse_name("The.Sopranos.S01-S06.1080p.BluRay.x264-GRP").fields
    assert (fields.season, fields.episode_code) == (1, "S01-S06")


def test_a_name_without_a_title() -> None:
    fields = parse_name("Episode 01").fields
    assert (fields.name, fields.main_title, fields.episode_code) == (
        None,
        "Episode 01",
        "Episode 01",
    )
    assert parse_name("S01E01").score == 0


def test_empty_and_odd_names() -> None:
    assert parse_name("").fields.main_title is None
    assert parse_name("....").fields.main_title is None
    assert parse_name("[]").fields.main_title is None


def test_guessit_failure_is_no_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: object, **kwargs: object) -> object:
        raise RuntimeError("guessit broke")

    monkeypatch.setattr(parse_module, "guessit", broken)
    guess_matches.cache_clear()
    try:
        assert guess_matches("Some.Name.2016") == ()
        fields = parse_name("Some.Name.2016").fields
        assert fields.main_title == "Some.Name.2016"
        assert fields.name == "Some.Name.2016"  # a movie name is its main title
    finally:
        guess_matches.cache_clear()


def test_scored_fields() -> None:
    assert SCORED_FIELDS == (
        "title",
        "year",
        "resolution",
        "source",
        "video_codec",
        "audio_codec",
        "hdr",
        "edition",
        "release_group",
    )
    parsed = parse_name("Avengers.Endgame.2019.IMAX.2160p.WEB-DL.DDP5.1.Atmos.HDR.HEVC-EVO")
    assert parsed.recognised == list(SCORED_FIELDS)
    assert parsed.score == 11


def test_word_separators_need_a_separator_in_the_title() -> None:
    assert not parse_name("hacksawridge.2160p.remux-henderson").word_separators
    assert parse_name("Hacksaw Ridge (2016)").word_separators
    assert not parse_name("sparks-hacksawridge-1080p").word_separators


def test_editions_far_apart_are_joined_with_the_separator() -> None:
    fields = parse_name("Movie.2010.EXTENDED.1080p.BluRay.REMASTERED.x264-GRP").fields
    assert fields.edition == "EXTENDED.REMASTERED"
    assert parse_name("Gladiator.2000.Extended.Remastered.1080p").fields.edition == (
        "Extended.Remastered"
    )
