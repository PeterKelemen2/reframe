"""C-12 selection stage (03 §Audio defaults part 1, §Subtitles "Subtitle defaults"; decision
0031): one table test per setting, for audio and for subtitles."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from reframe.batch import effective_languages, select_tracks
from reframe.batch.selection import (
    KEEP_EVERYTHING,
    Selection,
    extra_role,
    is_undetermined,
    language_slot,
    sort_key,
)
from reframe.models import (
    AudioStream,
    SubtitleStream,
    TrackRole,
    TrackSelection,
)


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"_reframe_batch_{name}", Path(__file__).with_name(f"{name}.py")
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


T = _load("defaults_tracks")
audio: Callable[..., AudioStream] = T.audio
subtitle: Callable[..., SubtitleStream] = T.subtitle
role: Callable[..., Any] = T.role


def run[S: (AudioStream, SubtitleStream)](
    streams: Sequence[S], preferred: Sequence[str] = (), **settings: Any
) -> Selection[S]:
    return select_tracks(streams, TrackSelection(**settings), preferred_languages=preferred)


def taken(selection: Selection[Any]) -> list[int]:
    """The selected stream indexes, in output order."""
    return [pick.stream.index for pick in selection.selected]


def why(selection: Selection[Any], index: int) -> str:
    return next(p.why for p in selection.picks if p.stream.index == index)


def check_invariants(selection: Selection[Any], streams: Sequence[Any]) -> None:
    assert [p.stream for p in selection.picks] == list(streams)
    assert sorted(selection.order) == [i for i, p in enumerate(selection.picks) if p.selected]
    assert all(p.why for p in selection.picks)


# =========================================================================== languages


def test_listed_languages_in_order() -> None:
    streams = [audio(1, "jpn"), audio(2, "eng"), audio(3, "hun")]
    selection = run(streams, languages=["hu", "en"])
    check_invariants(selection, streams)
    assert selection.configured
    assert selection.languages == ("hu", "en")
    assert taken(selection) == [3, 2]
    assert why(selection, 3) == "Hungarian: the first matching track"
    assert why(selection, 2) == "English: the first matching track"
    assert why(selection, 1) == "Japanese is not a listed language: dropped"
    assert [p.slot for p in selection.picks] == [None, 1, 0]


@pytest.mark.parametrize(
    ("listed", "language", "ietf", "expected"),
    [
        (["ger"], "de", None, True),  # ISO 639-2/B = ISO 639-1
        (["de"], "ger", None, True),
        (["deu"], "ger", None, True),  # /T = /B
        (["hun"], "hu", None, True),
        (["German"], "ger", None, True),  # a language name
        (["pt"], "por", None, True),
        (["pt"], "por", "pt-BR", True),  # a listed base language takes every region
        (["pt-BR"], "por", "pt-BR", True),
        (["pt-BR"], "por", None, False),  # a listed region takes only that region
        (["pt-BR"], "por", "pt-PT", False),
        (["zh"], "chi", "zh-Hans", True),
        (["zh-Hant"], "chi", "zh-Hans", False),
        (["en"], "eng", None, True),
        (["en"], None, None, False),
        (["en"], "fre", None, False),
    ],
)
def test_language_identity(listed: list[str], language: str, ietf: str, expected: bool) -> None:
    """Languages are compared as languages, not strings; a region or script subtag of the
    listed language must be on the track (decision 0031, ``reframe.languages.matches``)."""
    streams = [audio(1, language, ietf=ietf)]
    selection = run(streams, languages=listed, no_match="none")
    assert taken(selection) == ([1] if expected else [])


def test_languages_from_settings() -> None:
    streams = [audio(1, "eng"), audio(2, "hun")]
    assert taken(run(streams, ["hu"])) == [2]  # languages=None: Settings
    assert taken(run(streams, ["hu"], languages=[])) == [2]  # empty: Settings too
    assert taken(run(streams, ["hu"], languages=["en"])) == [1]  # the preset wins
    assert effective_languages(["hun", "hu", "HU", "ger"]) == ("hu", "de")
    assert effective_languages(None, ["eng", "pt_br"]) == ("en", "pt-BR")
    assert effective_languages([], []) == ()


def test_keep_everything_without_languages() -> None:
    """No language anywhere: every track, in source order, whatever the other settings say
    (decision 0031, as M2 did: decision 0018)."""
    streams = [
        audio(1, "jpn"),
        audio(2, "eng", comment=True),
        audio(3, None),
        audio(4, "eng", "aac", 2, 96),
    ]
    selection = run(streams, tracks_per_language="none", other_languages="drop")
    check_invariants(selection, streams)
    assert not selection.configured
    assert taken(selection) == [1, 2, 3, 4]
    assert {p.why for p in selection.picks} == {KEEP_EVERYTHING["audio"]}
    assert {p.group for p in selection.picks} == {"all"}
    assert not selection.no_listed_language
    subtitles = run([subtitle(5, "eng")])
    assert why(subtitles, 5) == KEEP_EVERYTHING["subtitle"]


def test_no_tracks() -> None:
    selection = select_tracks([], TrackSelection(languages=["hu"]), kind="subtitle")
    assert selection.kind == "subtitle"
    assert selection.picks == ()
    assert not selection.no_listed_language


# =========================================================================== tracks per language

HUN_TWO = [audio(1, "hun", "ac3", 6, 448), audio(2, "hun", "ac3", 2, 192), audio(3, "eng")]


@pytest.mark.parametrize(
    ("setting", "expected", "dropped"),
    [
        ("none", [], {1: "Hungarian: tracks per language is None: dropped"}),
        (
            "first",
            [1, 3],
            {2: "Hungarian: not the first matching track (best quality takes #1): dropped"},
        ),
        ("all", [1, 2, 3], {}),
    ],
)
def test_tracks_per_language(setting: str, expected: list[int], dropped: dict[int, str]) -> None:
    selection = run(HUN_TWO, languages=["hu", "en"], tracks_per_language=setting)
    check_invariants(selection, HUN_TWO)
    assert taken(selection) == expected
    for index, text in dropped.items():
        assert why(selection, index) == text
    if setting == "first":
        assert why(selection, 1) == "Hungarian: the first of 2 matching tracks (best quality)"
    if setting == "all":
        assert why(selection, 2) == "Hungarian: all matching tracks"


# =========================================================================== tie-break

TIE = [
    audio(1, "hun", "ac3", 2, 192),
    audio(2, "hun", "eac3", 6, 640),
    audio(3, "hun", "truehd", 8, None, lossless=True),  # lossless, bit rate unknown
    audio(4, "hun", "aac", 2, None),  # lossy, bit rate unknown
    audio(5, "hun", "dts", 6, 1500, lossless=True),
]


@pytest.mark.parametrize(
    ("tie_break", "order"),
    [
        ("source_order", [1, 2, 3, 4, 5]),
        ("most_channels", [3, 2, 5, 1, 4]),  # then source order
        # Lossless first (a known bit rate before an unknown one), then the highest bit rate,
        # an unknown lossy bit rate last.
        ("best_quality", [5, 3, 2, 1, 4]),
    ],
)
def test_tie_break(tie_break: str, order: list[int]) -> None:
    every = run(TIE, languages=["hu"], tracks_per_language="all", tie_break=tie_break)
    assert taken(every) == order
    first = run(TIE, languages=["hu"], tracks_per_language="first", tie_break=tie_break)
    assert taken(first) == order[:1]


def test_best_quality_ties_go_to_more_channels() -> None:
    streams = [audio(1, "hun", "aac", 2, None), audio(2, "hun", "aac", 6, None)]
    assert taken(run(streams, languages=["hu"], tracks_per_language="all")) == [2, 1]
    assert sort_key(streams[0], 0, "source_order") == (0,)


def test_subtitle_tie_break_prefers_full_subtitles() -> None:
    streams = [
        subtitle(1, "eng", forced=True),
        subtitle(2, "eng", hearing_impaired=True),
        subtitle(3, "eng", title="Signs", roles=[role(TrackRole.SIGNS)]),
        subtitle(4, "eng"),
    ]
    for tie in ("best_quality", "most_channels"):
        selection = run(streams, languages=["en"], tracks_per_language="all", tie_break=tie)
        assert taken(selection) == [4, 2, 1, 3]
    selection = run(streams, languages=["en"], tie_break="source_order")
    assert taken(selection) == [1]
    assert taken(run(streams, languages=["en"])) == [4]


# =========================================================================== undetermined

UND = [audio(1, None), audio(2, "und"), audio(3, "eng"), audio(4, "qaa")]


def test_undetermined_as_the_first_language() -> None:
    selection = run(
        UND, languages=["hu", "en"], undetermined="first_language", tracks_per_language="all"
    )
    check_invariants(selection, UND)
    assert taken(selection) == [1, 2, 3]
    pick = selection.picks[0]
    assert (pick.slot, pick.language, pick.relabelled) == (0, "hu", True)
    assert pick.why == "Undetermined (treated as Hungarian): all matching tracks"
    # qaa (reserved for local use) is a language, not "undetermined".
    assert why(selection, 4).endswith("is not a listed language: dropped")
    assert not selection.picks[2].relabelled


def test_undetermined_as_an_other_language() -> None:
    selection = run(UND, languages=["hu", "en"], undetermined="other")
    assert taken(selection) == [3]
    assert why(selection, 1) == "Undetermined is not a listed language: dropped"
    assert why(selection, 2) == "Undetermined is not a listed language: dropped"
    kept = run(UND, languages=["hu", "en"], other_languages="keep_all")
    assert taken(kept) == [3, 1, 2, 4]
    assert not kept.picks[0].relabelled


def test_a_listed_und_takes_undetermined_tracks() -> None:
    assert taken(run(UND, languages=["und"], tracks_per_language="all")) == [1, 2]
    assert language_slot(None, ["en", "und"]) == 1
    assert language_slot(None, [], "first_language") is None
    assert is_undetermined("zxx") is False
    assert is_undetermined("not a language") is True


# =========================================================================== other languages

OTHERS = [
    audio(1, "jpn", "ac3", 2, 192),
    audio(2, "jpn", "truehd", 8, None, lossless=True),
    audio(3, "fre", "ac3", 6, 448),
    audio(4, "hun", "ac3", 6, 448),
]


@pytest.mark.parametrize(
    ("setting", "expected"),
    [
        ("drop", [4]),
        # The best track (tie-break) of the first other language in source order (Japanese).
        ("keep_first", [4, 2]),
        ("keep_all", [4, 1, 2, 3]),  # source order after the listed languages
    ],
)
def test_other_languages(setting: str, expected: list[int]) -> None:
    selection = run(OTHERS, languages=["hu"], other_languages=setting)
    check_invariants(selection, OTHERS)
    assert taken(selection) == expected
    if setting == "drop":
        assert why(selection, 3) == "French is not a listed language: dropped"
    if setting == "keep_first":
        assert why(selection, 2) == (
            "Japanese is not a listed language: kept (other languages: keep the first track)"
        )
        assert why(selection, 3) == (
            "French is not a listed language: dropped (other languages: keep the first track; "
            "#2 is kept)"
        )
    if setting == "keep_all":
        assert (
            why(selection, 1)
            == "Japanese is not a listed language: kept (other languages: keep all)"
        )
        assert [selection.picks[i].group for i in (0, 3)] == ["other", "language"]


# =========================================================================== no listed language

NO_HUNGARIAN = [audio(1, "jpn"), audio(2, "fre", default=True), audio(3, "ger")]


@pytest.mark.parametrize(
    ("setting", "streams", "expected", "text"),
    [
        (
            "default_flagged",
            NO_HUNGARIAN,
            [2],
            "No listed language found (Hungarian): the default-flagged track",
        ),
        (
            "default_flagged",
            [audio(1, "jpn"), audio(2, "fre")],
            [1],
            "No listed language found (Hungarian): the first track (no track is default-flagged)",
        ),
        ("first_track", NO_HUNGARIAN, [1], "No listed language found (Hungarian): the first track"),
        ("none", NO_HUNGARIAN, [], None),
    ],
)
def test_no_listed_language(
    setting: str, streams: list[AudioStream], expected: list[int], text: str | None
) -> None:
    selection = run(streams, languages=["hu"], no_match=setting)
    check_invariants(selection, streams)
    assert selection.no_listed_language
    assert taken(selection) == expected
    if text is not None:
        assert why(selection, expected[0]) == text
        assert selection.picks[expected[0] - 1].group == "no_match"
    else:
        assert why(selection, 1) == (
            "Japanese is not a listed language: dropped (no listed language found: take none)"
        )


def test_no_listed_language_with_other_languages_kept() -> None:
    """The no-match track counts as the first other-language track; ``keep_all`` adds the
    others after it."""
    first = run(NO_HUNGARIAN, languages=["hu"], other_languages="keep_first")
    assert taken(first) == [2]
    assert why(first, 1) == (
        "Japanese is not a listed language: dropped (other languages: keep the first track; "
        "#2 is kept)"
    )
    every = run(NO_HUNGARIAN, languages=["hu"], other_languages="keep_all")
    assert taken(every) == [2, 1, 3]
    found = run([audio(1, "hun"), audio(2, "jpn")], languages=["hu"])
    assert not found.no_listed_language


def test_a_listed_commentary_counts_as_found() -> None:
    """Only a track in a listed language counts: here the Hungarian commentary."""
    streams = [audio(1, "jpn"), audio(2, "hun", comment=True)]
    selection = run(streams, languages=["hu"], no_match="first_track")
    assert not selection.no_listed_language
    assert taken(selection) == []


# =========================================================================== commentary

EXTRAS = [
    audio(1, "eng"),
    audio(2, "eng", "ac3", 2, 192, comment=True),
    audio(3, "eng", "ac3", 2, 192, visual_impaired=True),
    audio(4, "eng", "ac3", 6, 448, clean_effects=True),
    audio(
        5,
        "jpn",
        "aac",
        2,
        128,
        title="Commentary",
        roles=[role(TrackRole.COMMENTARY, detail='title contains "Commentary"')],
    ),
    audio(
        6, "eng", "ac3", 2, 96, roles=[role(TrackRole.COMMENTARY, "heuristic", "2.0 at 96 kb/s")]
    ),
]


def test_commentary_dropped() -> None:
    selection = run(EXTRAS, languages=["en"], tracks_per_language="all")
    check_invariants(selection, EXTRAS)
    assert taken(selection) == [1]
    assert why(selection, 2) == "Commentary (disposition comment): dropped"
    assert why(selection, 3) == "Audio description (disposition visual_impaired): dropped"
    assert why(selection, 4) == "Music only (disposition clean_effects): dropped"
    assert why(selection, 5) == 'Commentary (title contains "Commentary"): dropped'
    assert why(selection, 6) == "Commentary (2.0 at 96 kb/s): dropped"


def test_commentary_kept_after_the_main_tracks() -> None:
    selection = run(EXTRAS, languages=["en"], commentary="keep_after_main", order="source")
    assert taken(selection) == [1, 2, 3, 4, 6]
    assert why(selection, 2) == "Commentary (disposition comment): kept after the main tracks"
    # The language rules still apply: Japanese is not listed and other languages are dropped.
    assert why(selection, 5) == (
        'Commentary (title contains "Commentary"): Japanese is not a listed language: dropped'
    )
    every = run(EXTRAS, languages=["en"], commentary="keep_after_main", other_languages="keep_all")
    # Extras by language list order: English (2, 3, 4, 6), then the other languages (5).
    assert taken(every) == [1, 2, 3, 4, 6, 5]
    assert {p.group for p in every.selected[1:]} == {"extra"}


def test_extra_roles() -> None:
    assert extra_role(audio(1, "eng")) is None
    assert extra_role(audio(1, "eng", descriptions=True)) == (
        TrackRole.DESCRIPTION,
        "disposition descriptions",
    )
    assert extra_role(subtitle(1, "eng", comment=True)) == (
        TrackRole.COMMENTARY,
        "disposition comment",
    )
    # Music is an audio role only; SDH and forced subtitles are main subtitle tracks.
    assert extra_role(subtitle(1, "eng", clean_effects=True)) is None
    assert extra_role(subtitle(1, "eng", hearing_impaired=True)) is None
    assert extra_role(audio(1, "eng", roles=[role(TrackRole.MUSIC, "title")])) == (
        TrackRole.MUSIC,
        "title",
    )


def test_commentary_subtitles() -> None:
    streams = [subtitle(1, "eng"), subtitle(2, "eng", comment=True)]
    selection = run(streams, languages=["en"], tracks_per_language="all", no_match="none")
    assert taken(selection) == [1]
    kept = run(streams, languages=["en"], tracks_per_language="all", commentary="keep_after_main")
    assert taken(kept) == [1, 2]


# =========================================================================== order

ORDER = [
    audio(1, "eng"),
    audio(2, "hun"),
    audio(3, "jpn"),
    audio(4, "eng", comment=True),
    audio(5, "hun", comment=True),
]


@pytest.mark.parametrize(
    ("order", "expected"),
    [
        # Listed languages in list order, then other languages; extras last, by language.
        ("language_list", [2, 1, 3, 5, 4]),
        ("source", [1, 2, 3, 4, 5]),  # extras after the main tracks
    ],
)
def test_output_order(order: str, expected: list[int]) -> None:
    selection = run(
        ORDER,
        languages=["hu", "en"],
        other_languages="keep_all",
        commentary="keep_after_main",
        order=order,
    )
    assert taken(selection) == expected


def test_extras_follow_the_main_tracks_in_source_order() -> None:
    streams = [audio(1, "eng", comment=True), audio(2, "eng")]
    selection = run(streams, languages=["en"], commentary="keep_after_main", order="source")
    assert taken(selection) == [2, 1]


# =========================================================================== subtitles


def test_subtitle_defaults_take_nothing_without_a_match() -> None:
    """The subtitle selection's own defaults: no match → none (no error for subtitles)."""
    from reframe.models import SubtitleDefaults

    streams = [subtitle(1, "jpn"), subtitle(2, "fre", default=True)]
    selection = select_tracks(streams, SubtitleDefaults().selection, preferred_languages=["hu"])
    assert selection.no_listed_language
    assert taken(selection) == []


@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        ({"tracks_per_language": "none"}, []),
        ({"tracks_per_language": "first"}, [4, 2]),  # the full Hungarian track, not the forced
        ({"tracks_per_language": "all"}, [4, 3, 2]),
        ({"tracks_per_language": "all", "order": "source"}, [2, 3, 4]),
        ({"other_languages": "keep_all"}, [4, 2, 1, 5]),
        ({"undetermined": "first_language", "tracks_per_language": "all"}, [4, 5, 3, 2]),
    ],
)
def test_subtitle_selection(settings: dict[str, Any], expected: list[int]) -> None:
    streams = [
        subtitle(1, "jpn"),
        subtitle(2, "eng"),
        subtitle(3, "hun", forced=True),
        subtitle(4, "hun"),
        subtitle(5, None),
    ]
    selection = run(streams, languages=["hu", "en"], **settings)
    check_invariants(selection, streams)
    assert taken(selection) == expected
