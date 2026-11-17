"""Grouping files by fingerprint, near members, episode order and group names."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from reframe.batch import fingerprint, group_sources
from reframe.batch.descriptors import MATCH_LEVELS
from reframe.batch.grouping import (
    NEAR_MAX_DIFFERENCES,
    compare,
    episode_info,
    episode_key,
    episode_labels,
    group_name,
)
from reframe.models import (
    AudioStream,
    HdrFormat,
    HdrInfo,
    MediaSource,
    SourceRef,
    SubtitleStream,
    VideoStream,
)

from . import anime as A


@pytest.mark.parametrize(
    ("path", "name", "season", "episode", "label"),
    [
        (
            "/tv/Anime.Show.S01.BluRay/Anime.Show.S01E05.Echoes.BluRay.mkv",
            "Anime Show",
            1,
            5,
            "E05",
        ),
        ("/tv/Show.S02.1080p/S02E03.mkv", "Show", 2, 3, "E03"),
        ("/tv/Breaking Bad (2008)/breaking.bad.s01e01.mkv", "breaking bad", 1, 1, "E01"),
        ("/tv/[Grp] Anime Show - 07 [1080p].mkv", "Anime Show", None, 7, "E07"),
        ("/movies/Hacksaw.Ridge.2016/movie.mkv", "movie", None, None, "movie.mkv"),
    ],
)
def test_episode_info(
    path: str, name: str, season: int | None, episode: int | None, label: str
) -> None:
    info = episode_info(Path(path))
    assert (info.name, info.season, info.episode) == (name, season, episode)
    assert episode_labels([Path(path)]) == [label]


def test_episode_order() -> None:
    names = [
        "Show.S02E01.mkv",
        "Show.S01E10.mkv",
        "Extras.mkv",
        "Show.S01E02.mkv",
        "Show.S01E01.mkv",
        "Behind.mkv",
    ]
    ordered = sorted((Path("/tv") / n for n in names), key=episode_key)
    assert [p.name for p in ordered] == [
        "Show.S01E01.mkv",
        "Show.S01E02.mkv",
        "Show.S01E10.mkv",
        "Show.S02E01.mkv",
        "Behind.mkv",
        "Extras.mkv",
    ]


def test_group_name() -> None:
    paths = [A.path(1, n) for n in (1, 2, 3)]
    assert group_name(paths) == "Anime Show S01"
    mixed = [Path("/tv/Show.S01E01.mkv"), Path("/tv/Other.S03E01.mkv"), Path("/tv/Show.S01E02.mkv")]
    assert group_name(mixed) == "Show S01"
    assert group_name([Path("/tv/Show - 01.mkv")]) == "Show"
    assert group_name([Path("/tv/My Folder/01.mkv")]) == "My Folder"


def video(width: int = 320, height: int = 180, **kw: object) -> VideoStream:
    return VideoStream.model_validate(
        {"index": 0, "codec": "h264", "width": width, "height": height, **kw}
    )


def media(path: str, *streams: VideoStream | AudioStream | SubtitleStream) -> MediaSource:
    return MediaSource(
        ref=SourceRef(path=Path(path)),
        video=[s for s in streams if isinstance(s, VideoStream)],
        audio=[s for s in streams if isinstance(s, AudioStream)],
        subtitles=[s for s in streams if isinstance(s, SubtitleStream)],
    )


def audio(
    index: int, language: str, codec: str = "ac3", channels: int = 6, **kw: object
) -> AudioStream:
    return AudioStream.model_validate(
        {"index": index, "codec": codec, "language": language, "channels": channels, **kw}
    )


def test_the_example_differences() -> None:
    e01, e05, e11 = (fingerprint(A.recorded(1, n), "standard") for n in (1, 5, 11))
    assert compare(e01, e01).count == 0
    found = compare(e01, e05)
    assert (found.count, found.lines) == (1, ['1 extra track (eng AC-3 2.0 "Commentary")'])
    found = compare(e01, e11)
    assert (found.count, found.lines) == (1, ['1 track missing (eng DTS-HD MA 5.1 "English Dub")'])
    # Strict also compares titles: E11's signs track has another title.
    strict = compare(
        fingerprint(A.recorded(1, 1), "strict"), fingerprint(A.recorded(1, 11), "strict")
    )
    assert strict.count == 2
    assert strict.lines == [
        '1 track missing (eng DTS-HD MA 5.1 "English Dub")',
        '1 track differs (eng ASS "Signs & Songs" → eng ASS "Signs")',
    ]


def test_several_differences_and_the_video() -> None:
    group = fingerprint(media("/a.mkv", video(), audio(1, "jpn"), audio(2, "eng")), "standard")
    other = media(
        "/b.mkv",
        video(1280, 720, hdr=HdrInfo(formats=[HdrFormat.HLG])),
        audio(1, "jpn"),
        audio(2, "hun"),
        audio(3, "ger"),
        audio(4, "fre"),
    )
    found = compare(group, fingerprint(other, "standard"))
    assert found.lines == [
        "2 extra tracks (ger AC-3 5.1; fre AC-3 5.1)",
        "1 track differs (eng AC-3 5.1 → hun AC-3 5.1)",
        "video 1280x720 (the group: 320x180)",
        "HLG (the group: SDR)",
    ]
    assert found.count == 5
    fewer = compare(fingerprint(other, "standard"), group)
    assert fewer.lines[0] == "2 tracks missing (ger AC-3 5.1; fre AC-3 5.1)"


def test_the_loose_level_ignores_the_order() -> None:
    a = media("/a.mkv", video(1920, 1080), audio(1, "jpn"), audio(2, "eng", channels=2))
    b = media(
        "/b.mkv", video(1920, 800), audio(1, "eng", codec="eac3"), audio(2, "jpn", channels=8)
    )
    assert compare(fingerprint(a, "loose"), fingerprint(b, "loose")).count == 0
    c = media("/c.mkv", video(1920, 1080), audio(1, "jpn"), audio(2, "hun"))
    found = compare(fingerprint(a, "loose"), fingerprint(c, "loose"))
    # A track in the place of a missing one of its kind differs: one difference, as at the
    # standard level.
    assert found.lines == ["1 track differs (eng AC-3 2.0 → hun AC-3 5.1)"]
    assert found.count == 1
    assert (
        "video"
        in compare(
            fingerprint(a, "loose"),
            fingerprint(
                media("/d.mkv", video(720, 576), audio(1, "jpn"), audio(2, "eng")), "loose"
            ),
        ).lines[-1]
    )


def test_no_video() -> None:
    a = fingerprint(media("/a.mka", audio(1, "jpn")), "standard")
    b = fingerprint(media("/b.mkv", video(), audio(1, "jpn")), "standard")
    assert compare(a, b).lines[-1] == "video 320x180 (the group: none)"


def test_the_example_season_is_one_group() -> None:
    sources = A.season(1)
    random.Random(7).shuffle(sources)
    (group,) = group_sources(sources, "standard")
    assert group.name == "Anime Show S01"
    assert group.level == "standard"
    assert group.representative == A.path(1, 1)
    assert group.fingerprint == fingerprint(A.recorded(1, 1), "standard")
    assert [m.path for m in group.members] == [A.path(1, n) for n in range(1, 13)]
    assert [(m.season, m.episode) for m in group.members] == [(1, n) for n in range(1, 13)]
    near = {m.episode: m.differences for m in group.members if m.match == "near"}
    assert near == {
        5: ['1 extra track (eng AC-3 2.0 "Commentary")'],
        11: ['1 track missing (eng DTS-HD MA 5.1 "English Dub")'],
    }
    assert all(not m.differences for m in group.members if m.match == "exact")


def test_one_group_at_every_level() -> None:
    groups = [group_sources(A.season(1), level) for level in MATCH_LEVELS]
    assert [[len(g.members) for g in found] for found in groups] == [[12]] * 3
    assert len({found[0].id for found in groups}) == 3


def test_two_seasons_of_one_release_are_one_group_at_the_standard_level() -> None:
    """The same structure: the group is named after the season that most of its files share."""
    groups = group_sources([*A.season(2), *A.season(1)], "standard")
    assert len(groups) == 1
    assert len(groups[0].members) == 15
    assert groups[0].members[0].path == A.path(1, 1)
    assert groups[0].name == "Anime Show S01"
    (fewer,) = group_sources([*A.season(2), *A.season(1)[:2]], "standard")
    assert fewer.members[0].path == A.path(1, 1)
    assert fewer.name == "Anime Show S02"


def test_files_that_differ_more_are_another_group() -> None:
    show = [
        media(f"/tv/Show.S01E0{n}.mkv", video(), audio(1, "jpn"), audio(2, "eng")) for n in (1, 2)
    ]
    movie = media(
        "/tv/Movie.2020.mkv", video(1920, 1080), audio(1, "hun"), audio(2, "ger"), audio(3, "fre")
    )
    groups = group_sources([movie, *show], "standard")
    assert [g.name for g in groups] == ["Show S01", "Movie"]
    assert [len(g.members) for g in groups] == [2, 1]
    assert groups[1].members[0].match == "exact"
    assert NEAR_MAX_DIFFERENCES == 2


def test_a_near_file_joins_the_closest_larger_group() -> None:
    def ep(n: int, *tracks: AudioStream) -> MediaSource:
        return media(f"/tv/Show.S01E{n:02d}.mkv", video(), *tracks)

    a = [ep(n, audio(1, "jpn"), audio(2, "eng")) for n in (1, 2, 3)]
    b = [ep(n, audio(1, "jpn")) for n in (4, 5)]
    c = [ep(6, audio(1, "jpn"), audio(2, "eng"), audio(3, "eng", channels=2))]
    (group,) = group_sources([*b, *c, *a], "standard")
    assert group.representative == Path("/tv/Show.S01E01.mkv")
    assert [m.match for m in group.members] == ["exact"] * 3 + ["near"] * 3
    assert group.members[3].differences == ["1 track missing (eng AC-3 5.1)"]
    assert group.members[5].differences == ["1 extra track (eng AC-3 2.0)"]


def test_equal_groups_the_first_in_episode_order_is_the_anchor() -> None:
    def ep(n: int, *tracks: AudioStream) -> MediaSource:
        return media(f"/tv/Show.S01E{n:02d}.mkv", video(), *tracks)

    late = [ep(n, audio(1, "jpn")) for n in (3, 4)]
    early = [ep(n, audio(1, "jpn"), audio(2, "eng")) for n in (1, 2)]
    (group,) = group_sources([*late, *early], "standard")
    assert group.representative == Path("/tv/Show.S01E01.mkv")
    assert [m.match for m in group.members] == ["exact", "exact", "near", "near"]


def test_no_files() -> None:
    assert group_sources([], "standard") == []


def test_a_changed_track_counts_once_at_every_level() -> None:
    """Each changed track counts 1 at every level, so two German tracks count 2 at each."""
    e01, e03 = A.recorded(1, 1), A.recorded(1, 3)
    e02 = A.recorded(1, 2)
    audio = [e02.audio[0], e02.audio[1].model_copy(update={"language": "ger"})]
    subs = [e02.subtitles[0], e02.subtitles[1].model_copy(update={"language": "ger"})]
    changed = e02.model_copy(update={"audio": audio, "subtitles": subs})
    counts = {}
    for level in MATCH_LEVELS:
        found = compare(fingerprint(e01, level), fingerprint(changed, level))
        counts[level] = found.count
        assert found.lines == [
            '2 tracks differ (eng DTS-HD MA 5.1 "English Dub" → ger DTS-HD MA 5.1 "English Dub"; '
            'eng ASS "Full" → ger ASS "Full")'
        ], level
    assert counts == {"strict": 2, "standard": 2, "loose": 2}
    for level in MATCH_LEVELS[1:]:
        (group,) = group_sources([e01, e03, changed], level)
        assert [m.match for m in group.members] == ["exact", "near", "exact"], level


def test_loose_pairs_changed_tracks_by_kind() -> None:
    """An extra audio track and a missing subtitle are not one changed track."""
    e01 = A.recorded(1, 1)
    other = e01.model_copy(
        update={
            "audio": [*e01.audio, e01.audio[1].model_copy(update={"index": 9, "language": "ger"})],
            "subtitles": e01.subtitles[:1],
        }
    )
    found = compare(fingerprint(e01, "loose"), fingerprint(other, "loose"))
    assert found.count == 2
    assert found.lines == [
        '1 extra track (ger DTS-HD MA 5.1 "English Dub")',
        '1 track missing (eng ASS "Full")',
    ]


def test_episode_labels() -> None:
    folder = Path("/media/Show.S01")
    paths = [
        folder / "Show.S01E01.BluRay.mkv",
        folder / "Show.S01E01.WEB.mkv",
        folder / "Show.S01E02.mkv",
        folder / "movie.mkv",
    ]
    # Two files of one episode: their file names.
    assert episode_labels(paths) == [
        "Show.S01E01.BluRay.mkv",
        "Show.S01E01.WEB.mkv",
        "E02",
        "movie.mkv",
    ]
    assert episode_labels(paths[2:], season=True) == ["S01E02", "movie.mkv"]
    assert episode_labels([A.path(1, 5)], season=True) == ["S01E05"]
    assert episode_labels([Path("/tv/Show - 07.mkv")], season=True) == ["E07"]
    assert episode_labels([Path("/a/Show.S01E01.mkv"), Path("/a/Show.S02E01.mkv")]) == [
        "S01E01",
        "S02E01",
    ]
