"""Role heuristics (C-3 ``probe/roles.py``): flags, title keywords, structure."""

from __future__ import annotations

from typing import Any

import pytest

from reframe.models import (
    AudioStream,
    BitrateInfo,
    BitrateSource,
    Disposition,
    RoleEvidence,
    SubtitleStream,
    TrackRole,
)
from reframe.probe import roles


def audio(
    index: int,
    *,
    lang: str | None = "eng",
    channels: int = 2,
    kbps: int | None = None,
    title: str | None = None,
    **flags: bool,
) -> AudioStream:
    bitrate = (
        BitrateInfo(value=kbps * 1000, source=BitrateSource.STREAM)
        if kbps is not None
        else BitrateInfo()
    )
    return AudioStream(
        index=index,
        language=lang,
        channels=channels,
        bitrate=bitrate,
        title=title,
        disposition=Disposition(**flags),
    )


def sub(
    index: int,
    *,
    lang: str | None = "eng",
    events: int | None = None,
    title: str | None = None,
    **flags: bool,
) -> SubtitleStream:
    return SubtitleStream(
        index=index,
        language=lang,
        event_count=events,
        title=title,
        disposition=Disposition(**flags),
    )


def role_set(stream: Any) -> set[tuple[TrackRole, RoleEvidence]]:
    return {(r.role, r.evidence) for r in stream.roles}


# --------------------------------------------------------------------------- flags


@pytest.mark.parametrize(
    ("flag", "role"),
    [
        ("comment", TrackRole.COMMENTARY),
        ("visual_impaired", TrackRole.DESCRIPTION),
        ("descriptions", TrackRole.DESCRIPTION),
        ("clean_effects", TrackRole.MUSIC),
    ],
)
def test_audio_flags(flag: str, role: TrackRole) -> None:
    stream = audio(1)
    stream.disposition = Disposition.model_validate({flag: True})
    roles.assign_audio_roles([stream])
    assert role_set(stream) == {(role, RoleEvidence.FLAG)}
    assert stream.roles[0].detail == f"disposition {flag}"


@pytest.mark.parametrize(
    ("flag", "role"),
    [
        ("forced", TrackRole.FORCED),
        ("hearing_impaired", TrackRole.SDH),
        ("captions", TrackRole.SDH),
        ("comment", TrackRole.COMMENTARY),
        ("descriptions", TrackRole.DESCRIPTION),
    ],
)
def test_subtitle_flags(flag: str, role: TrackRole) -> None:
    stream = sub(1)
    stream.disposition = Disposition.model_validate({flag: True})
    roles.assign_subtitle_roles([stream])
    assert role_set(stream) == {(role, RoleEvidence.FLAG)}


def test_flag_wins_over_title_for_the_same_role() -> None:
    stream = audio(1, title="Commentary", comment=True)
    roles.assign_audio_roles([stream])
    assert [(r.role, r.evidence) for r in stream.roles] == [
        (TrackRole.COMMENTARY, RoleEvidence.FLAG)
    ]


def test_flag_and_title_give_different_roles() -> None:
    stream = sub(1, title="Signs & Songs", forced=True)
    roles.assign_subtitle_roles([stream])
    assert [(r.role, r.evidence) for r in stream.roles] == [
        (TrackRole.FORCED, RoleEvidence.FLAG),
        (TrackRole.SIGNS, RoleEvidence.TITLE),
    ]


# --------------------------------------------------------------------------- title keywords

AUDIO_TITLES = [
    ("Director's Commentary", TrackRole.COMMENTARY),
    ("Commentaries", TrackRole.COMMENTARY),
    ("Kommentar", TrackRole.COMMENTARY),
    ("Commentaire audio", TrackRole.COMMENTARY),
    ("Comentario del director", TrackRole.COMMENTARY),
    ("Commento", TrackRole.COMMENTARY),
    ("Rendezői kommentár", TrackRole.COMMENTARY),
    ("KOMMENTÁR", TrackRole.COMMENTARY),
    ("監督コメンタリー", TrackRole.COMMENTARY),
    ("Audio Description", TrackRole.DESCRIPTION),
    ("English audio-description", TrackRole.DESCRIPTION),
    ("Descriptive Video Service", TrackRole.DESCRIPTION),
    ("English (AD)", TrackRole.DESCRIPTION),
    ("AD", TrackRole.DESCRIPTION),
    ("Music Only", TrackRole.MUSIC),
    ("Isolated Score", TrackRole.MUSIC),
]

AUDIO_NOT = [
    "Leader",  # "AD" inside a word
    "Ad Astra",  # "AD" must be upper case
    "Headphones mix",
    "Commentator's cut",  # not a keyword
    "Descriptions",  # not "descriptive"
    "English 5.1",
    "",
]


@pytest.mark.parametrize(("title", "role"), AUDIO_TITLES)
def test_audio_title_keywords(title: str, role: TrackRole) -> None:
    found = roles.title_roles(title, roles.AUDIO_KEYWORDS)
    assert [(r.role, r.evidence) for r in found] == [(role, RoleEvidence.TITLE)]
    assert (found[0].detail or "").startswith("title contains")


@pytest.mark.parametrize("title", AUDIO_NOT)
def test_audio_title_no_keyword(title: str) -> None:
    assert roles.title_roles(title, roles.AUDIO_KEYWORDS) == []


SUB_TITLES = [
    ("English [Forced]", TrackRole.FORCED),
    ("FORCED", TrackRole.FORCED),
    ("Foreign parts", TrackRole.FORCED),
    ("Signs", TrackRole.SIGNS),
    ("Songs only", TrackRole.SIGNS),
    ("English SDH", TrackRole.SDH),
    ("english.sdh", TrackRole.SDH),
    ("English CC", TrackRole.SDH),
    ("Hearing Impaired", TrackRole.SDH),
    ("hearing-impaired", TrackRole.SDH),
    ("Commentary", TrackRole.COMMENTARY),
]

SUB_NOT = ["Forcedly", "Designs", "cc", "Accent", "English", "Full Subtitles", "Songbird"]


@pytest.mark.parametrize(("title", "role"), SUB_TITLES)
def test_subtitle_title_keywords(title: str, role: TrackRole) -> None:
    found = roles.title_roles(title, roles.SUBTITLE_KEYWORDS)
    assert [(r.role, r.evidence) for r in found] == [(role, RoleEvidence.TITLE)]


@pytest.mark.parametrize("title", SUB_NOT)
def test_subtitle_title_no_keyword(title: str) -> None:
    assert roles.title_roles(title, roles.SUBTITLE_KEYWORDS) == []


def test_signs_and_songs_is_one_role() -> None:
    found = roles.title_roles("Signs & Songs", roles.SUBTITLE_KEYWORDS)
    assert [r.role for r in found] == [TrackRole.SIGNS]
    assert found[0].detail == 'title contains "Signs"'


# --------------------------------------------------------------------------- structure: audio


def test_low_bitrate_stereo_after_multichannel_is_possible_commentary() -> None:
    main = audio(1, channels=6, kbps=640, default=True)
    stereo = audio(2, channels=2, kbps=192)
    roles.assign_audio_roles([main, stereo])
    assert role_set(stereo) == {(TrackRole.COMMENTARY, RoleEvidence.HEURISTIC)}
    assert stereo.roles[0].detail == (
        "2.0 at 192 kb/s after the 6-channel track #1 in the same language (eng)"
    )
    assert role_set(main) == {(TrackRole.MAIN, RoleEvidence.FLAG)}


def test_mono_commentary_and_case_insensitive_language() -> None:
    main = audio(1, lang="ENG", channels=8)
    mono = audio(2, lang="eng", channels=1, kbps=96)
    roles.assign_audio_roles([main, mono])
    assert role_set(mono) == {(TrackRole.COMMENTARY, RoleEvidence.HEURISTIC)}
    assert (mono.roles[0].detail or "").startswith("mono at 96 kb/s")


@pytest.mark.parametrize(
    "stereo",
    [
        audio(2, kbps=224),  # not low
        audio(2),  # bit rate unknown
        audio(2, kbps=128, default=True),  # the default track
        audio(2, kbps=128, lang="ger"),  # another language
        audio(2, kbps=128, lang="und"),
        audio(2, kbps=128, lang=None),
        audio(2, kbps=128, channels=6),  # multichannel itself
    ],
)
def test_no_commentary_heuristic(stereo: AudioStream) -> None:
    main = audio(1, channels=6, kbps=640)
    roles.assign_audio_roles([main, stereo])
    assert role_set(stereo) <= {
        (TrackRole.MAIN, RoleEvidence.HEURISTIC),
        (TrackRole.MAIN, RoleEvidence.FLAG),
    }


def test_commentary_heuristic_needs_the_multichannel_track_before() -> None:
    stereo = audio(1, kbps=128)
    main = audio(2, channels=6, kbps=640)
    roles.assign_audio_roles([stereo, main])
    assert role_set(stereo) == {(TrackRole.MAIN, RoleEvidence.HEURISTIC)}


def test_commentary_heuristic_ignores_a_multichannel_track_with_a_role() -> None:
    described = audio(1, channels=6, kbps=640, visual_impaired=True)
    stereo = audio(2, kbps=128)
    roles.assign_audio_roles([described, stereo])
    assert role_set(stereo) == {(TrackRole.MAIN, RoleEvidence.HEURISTIC)}


def test_assignment_is_repeatable() -> None:
    streams = [audio(1, channels=6, kbps=640), audio(2, kbps=128)]
    roles.assign_audio_roles(streams)
    first = [s.roles for s in streams]
    roles.assign_audio_roles(streams)
    assert [s.roles for s in streams] == first


# --------------------------------------------------------------------------- structure: subs


def test_low_event_count_is_possible_forced() -> None:
    full, forced = sub(1, events=900), sub(2, events=40)
    roles.assign_subtitle_roles([full, forced])
    assert role_set(forced) == {(TrackRole.FORCED, RoleEvidence.HEURISTIC)}
    assert forced.roles[0].detail == (
        "40 events, 4 % of the 900 events of track #1 in the same language (eng)"
    )
    assert role_set(full) == {(TrackRole.MAIN, RoleEvidence.HEURISTIC)}


def test_forced_heuristic_adds_to_other_roles() -> None:
    full, sdh_short = sub(1, events=900), sub(2, events=10, hearing_impaired=True)
    roles.assign_subtitle_roles([full, sdh_short])
    assert role_set(sdh_short) == {
        (TrackRole.SDH, RoleEvidence.FLAG),
        (TrackRole.FORCED, RoleEvidence.HEURISTIC),
    }


@pytest.mark.parametrize(
    "other",
    [
        sub(2, events=300),  # 33 %: not low
        sub(2, events=None),  # unknown
        sub(2, events=10, lang="hun"),  # another language
        sub(2, events=10, lang="und"),
        sub(2, events=10, forced=True),  # already forced (flag)
        sub(2, events=10, title="Signs"),  # signs track
        sub(2, events=0),  # an empty track (core-complete review R1-6)
    ],
)
def test_no_forced_heuristic(other: SubtitleStream) -> None:
    full = sub(1, events=900)
    roles.assign_subtitle_roles([full, other])
    assert (TrackRole.FORCED, RoleEvidence.HEURISTIC) not in role_set(other)


def test_forced_heuristic_needs_another_track_with_a_count() -> None:
    alone = sub(1, events=3)
    roles.assign_subtitle_roles([alone, sub(2, events=None)])
    assert role_set(alone) == {(TrackRole.MAIN, RoleEvidence.HEURISTIC)}
    zero = sub(3, events=0)
    roles.assign_subtitle_roles([zero, sub(4, events=0)])
    assert role_set(zero) == {(TrackRole.MAIN, RoleEvidence.HEURISTIC)}


# --------------------------------------------------------------------------- review fixes (M1)


@pytest.mark.parametrize("title", ["Non-Forced", "Not Forced", "Full (not forced)", "non forced"])
def test_not_forced_is_not_forced(title: str) -> None:
    assert roles.title_roles(title, roles.SUBTITLE_KEYWORDS) == []


@pytest.mark.parametrize(
    ("title", "role"),
    [
        ("Audiokommentar", TrackRole.COMMENTARY),
        ("Regiekommentar mit dem Regisseur", TrackRole.COMMENTARY),
        ("Kommentar", TrackRole.COMMENTARY),
        ("Audiodeskription", TrackRole.DESCRIPTION),
        ("Deutsch (Hörfilmfassung)", TrackRole.DESCRIPTION),
        ("Described Video", TrackRole.DESCRIPTION),
    ],
)
def test_german_compounds_and_described(title: str, role: TrackRole) -> None:
    found = roles.title_roles(title, roles.AUDIO_KEYWORDS)
    assert [(r.role, r.evidence) for r in found] == [(role, RoleEvidence.TITLE)]


@pytest.mark.parametrize(
    ("title", "kbps"),
    [("English Stereo (compatibility)", 160), ("Original Mono Mix", 192), ("Stereo", 128)],
)
def test_commentary_heuristic_only_for_untitled_tracks(title: str, kbps: int) -> None:
    main = audio(1, channels=6, kbps=640)
    stereo = audio(2, kbps=kbps, title=title, channels=1 if "Mono" in title else 2)
    roles.assign_audio_roles([main, stereo])
    assert role_set(stereo) == {(TrackRole.MAIN, RoleEvidence.HEURISTIC)}
