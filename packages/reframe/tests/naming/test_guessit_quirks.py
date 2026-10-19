"""The guessit output that ``reframe.naming.parse`` works around.

Each test first shows what guessit itself returns (so a guessit upgrade that changes it is
noticed here), then what Reframe makes of it.
"""

from __future__ import annotations

from typing import Any

from guessit import guessit

from reframe.naming.parse import GUESSIT_OPTIONS, parse_name


def _spans(name: str) -> list[tuple[str, Any, int, int]]:
    """``(property, value, start, end)`` of every guessit match, with Reframe's options
    (advanced mode, no user config files)."""
    result = guessit(name, dict(GUESSIT_OPTIONS))
    out: list[tuple[str, Any, int, int]] = []
    for prop, found in result.items():
        for match in found if isinstance(found, list) else [found]:
            if match.end > match.start:
                out.append((prop, match.value, match.start, match.end))
    return sorted(out, key=lambda m: (m[2], m[0]))


def test_season_and_episode_spans_leave_out_the_letters() -> None:
    name = "The.Sopranos.S03E02.Proshai.Livushka.1080p.BluRay.REMUX-Kataklysm"
    spans = _spans(name)
    assert ("season", 3, 14, 16) in spans
    assert ("episode", 2, 17, 19) in spans
    fields = parse_name(name).fields
    assert fields.episode_code == "S03E02"
    assert fields.main_title == "The.Sopranos.S03E02.Proshai.Livushka"


def test_guessit_normalises_text_but_we_keep_the_original() -> None:
    spans = _spans("Hacksaw.Ridge.2016.HYBRID.2160p")
    assert ("title", "Hacksaw Ridge", 0, 14) in spans
    assert parse_name("Hacksaw.Ridge.2016.HYBRID.2160p").fields.name == "Hacksaw.Ridge"


def test_quirk_title_after_the_episode_number_is_the_episode_title() -> None:
    spans = _spans("01 - Pilot")
    assert ("episode", 1, 0, 2) in spans
    assert ("title", "Pilot", 4, 10) in spans
    fields = parse_name("01 - Pilot").fields
    assert fields.name is None
    assert fields.sub_title == "Pilot"
    assert fields.episode == 1


def test_quirk_bare_absolute_numbers_are_split_into_season_and_episode() -> None:
    """A bare number after `` - `` is an absolute episode number."""
    bleach = "Bleach - 001 - The Day I Became a Shinigami"
    assert ("season", 0, 9, 10) in _spans(bleach)
    assert ("episode", 1, 10, 12) in _spans(bleach)
    one_piece = "One Piece - 1000 - Overwhelming Strength! The Straw Hats Come Together!"
    assert ("season", 10, 12, 14) in _spans(one_piece)
    assert ("episode", 0, 14, 16) in _spans(one_piece)

    fields = parse_name(bleach).fields
    assert (fields.season, fields.episode, fields.episode_code) == (None, 1, "001")
    fields = parse_name(one_piece).fields
    assert (fields.season, fields.episode, fields.episode_code) == (None, 1000, "1000")


def test_scene_numbering_without_dash_stays_season_and_episode() -> None:
    """``The.Office.US.102`` is S01E02 in scene naming; guessit says so, and so do we."""
    name = "The.Office.US.102.Diversity.Day"
    assert ("season", 1, 14, 15) in _spans(name)
    assert ("episode", 2, 15, 17) in _spans(name)
    fields = parse_name(name).fields
    assert (fields.season, fields.episode, fields.episode_code) == (1, 2, "102")


def test_guessit_prefers_absolute_numbers_only_sometimes() -> None:
    """Without a title after it, guessit keeps a bare number whole (``- 101 [1080p]``)."""
    assert ("episode", 101, 19, 22) in _spans("Naruto Shippuden - 101 [1080p]")
    assert parse_name("Naruto Shippuden - 101 [1080p]").fields.episode == 101


def test_quirk_uhd_is_outside_the_source_match() -> None:
    name = "Hacksaw.Ridge.2016.HYBRID.2160p.UHD.BluRay.REMUX"
    assert ("source", "Ultra HD Blu-ray", 36, 42) in _spans(name)
    assert not [s for s in _spans(name) if s[2] <= 32 < s[3]]
    assert parse_name(name).fields.source_type == "UHD.BluRay"


def test_quirk_rip_is_a_separate_match() -> None:
    name = "Movie.2020.1080p.WEBRip.x264-GRP"
    spans = _spans(name)
    assert ("source", "Web", 17, 20) in spans
    assert ("other", "Rip", 20, 23) in spans
    assert parse_name(name).fields.source_type == "WEBRip"
    assert parse_name("Movie.2020.720p.BRRip.x264-GRP").fields.source_type == "BRRip"


def test_quirk_site_tag_glued_to_the_group() -> None:
    name = "Show.Name.S01E01.Episode.Name.1080p.WEB.h264-GRP[rarbg]"
    assert ("release_group", "GRP[rarbg]", 44, 55) in _spans(name)
    assert parse_name(name).fields.release_group == "GRP"


def test_quirk_hdr_tags_guessit_does_not_report() -> None:
    for name in (
        "Movie.2020.2160p.WEB-DL.DDP5.1.HDR10Plus.HEVC-GRP",
        "Movie.2020.2160p.HLG.HEVC-GRP",
    ):
        assert not [s for s in _spans(name) if s[0] == "other"]
        parsed = parse_name(name)
        assert "hdr" in parsed.recognised
        assert any(span.field == "hdr" for span in parsed.spans)


def test_quirk_duplicate_episode_matches() -> None:
    name = "[SubsPlease] Sousou no Frieren - 01 (1080p) [8F2A1B3C]"
    episodes = [s for s in _spans(name) if s[0] == "episode"]
    assert episodes == [("episode", 1, 33, 35), ("episode", 1, 34, 35)]
    assert parse_name(name).fields.episodes == [1]


def test_quirk_episode_title_raw_text_includes_the_dash() -> None:
    name = "Show Name - S01E02 - Episode Title"
    assert ("episode_title", "Episode Title", 18, 34) in _spans(name)
    assert name[18:34] == " - Episode Title"
    assert parse_name(name).fields.sub_title == "Episode Title"


def test_quirk_dvd_title_files_look_like_episodes() -> None:
    """``VTS_01_1`` parses as episode 1: the name source rules ignore it in ``VIDEO_TS``
    (see ``test_source.py``)."""
    assert [s for s in _spans("VTS_01_1") if s[0] == "episode"]
    assert parse_name("VTS_01_1").has_episode


def test_quirk_final_cut_is_an_episode_title_of_a_movie() -> None:
    name = "Apocalypse.Now.1979.Final.Cut.1080p.BluRay.x264-SADPANDA"
    result = guessit(name, {"name_only": True, "no_user_config": True})
    assert result["type"] == "episode"
    assert "season" not in result
    assert "episode" not in result
    fields = parse_name(name).fields
    assert fields.kind == "movie"
    assert fields.sub_title is None
    assert fields.main_title == "Apocalypse.Now"
