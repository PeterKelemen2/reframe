"""Track selectors, the relaxation order and the result rows of rule matching."""

from __future__ import annotations

from typing import Any

import pytest

from reframe.batch.selectors import (
    RELAX_ORDER,
    Track,
    candidates,
    describe_kind,
    match_rules,
    relaxation_steps,
    selector_matches,
    title_regex,
)
from reframe.models import (
    AudioOutputSettings,
    AudioStream,
    OutputTrackRule,
    Severity,
    SubtitleOutputSettings,
    SubtitleStream,
    TrackRole,
    TrackSelector,
)


def audio(index: int, **kw: Any) -> AudioStream:
    fields: dict[str, Any] = {"index": index, "codec": "ac3", "channels": 6, "language": "eng"}
    return AudioStream.model_validate({**fields, **kw})


def subtitle(index: int, **kw: Any) -> SubtitleStream:
    return SubtitleStream.model_validate({"index": index, "codec": "ass", "language": "eng", **kw})


STREAMS = [
    audio(1, codec="truehd", language="jpn", title="Japanese", display_codec="TrueHD Atmos",
          profile="Dolby TrueHD + Dolby Atmos", lossless=True),
    audio(2, codec="dts", title="English Dub", profile="DTS-HD MA", display_codec="DTS-HD MA",
          lossless=True, bitrate={"value": 3_000_000, "source": "stream"}),
    audio(3, channels=2, title="Commentary", disposition={"comment": True},
          bitrate={"value": 192_000, "source": "stream"}),
    audio(4, bitrate={"value": 640_000, "source": "stream"}),
    audio(5, codec="aac", language="hun", channels=2),
    audio(6, channels=2, language=None),
]  # fmt: skip
TRACKS = describe_kind(STREAMS)


def picked(selector: TrackSelector, tracks: list[Track] = TRACKS) -> list[int]:
    pattern = title_regex(selector.title_pattern)
    assert not isinstance(pattern, str)
    return [t.descriptor.index for t in candidates(selector, tracks, title=pattern)]


def sel(**kw: Any) -> TrackSelector:
    return TrackSelector.model_validate({"kind": "audio", **kw})


@pytest.mark.parametrize(
    ("selector", "streams"),
    [
        (sel(), [1, 2, 3, 4, 5, 6]),
        (sel(languages=["en"]), [2, 3, 4]),
        (sel(languages=["eng"]), [2, 3, 4]),
        (sel(languages=["hun", "jpn"]), [5, 1]),  # order of preference
        (sel(languages=["und"]), [6]),
        (sel(languages=[]), []),
        (sel(codecs=["ac3"]), [3, 4, 6]),
        (sel(codecs=["AC3", "dts"]), [2, 3, 4, 6]),
        (sel(profiles=["DTS-HD MA"]), [2]),
        (sel(profiles=["trueHD atmos"]), [1]),  # the commercial name, any case
        (sel(profiles=["Dolby TrueHD + Dolby Atmos"]), [1]),  # or ffprobe's profile
        (sel(roles=[TrackRole.COMMENTARY]), [3]),
        (sel(roles=[TrackRole.MAIN, TrackRole.COMMENTARY], languages=["en"]), [2, 3, 4]),
        (sel(exclude_roles=[TrackRole.COMMENTARY], languages=["en"]), [2, 4]),
        (sel(channels=2), [3, 5, 6]),
        (sel(title_pattern="^english dub$"), [2]),  # case-insensitive
        (sel(title_pattern="Comm"), [3]),
        (sel(title_pattern="^$"), [4, 5, 6]),  # untitled
        (TrackSelector(kind="subtitle"), []),
    ],
)
def test_each_filter(selector: TrackSelector, streams: list[int]) -> None:
    assert picked(selector) == streams


def test_sorting() -> None:
    english = {"languages": ["en"], "exclude_roles": [TrackRole.COMMENTARY]}
    assert picked(sel(**english)) == [2, 4]
    assert picked(sel(**english, sort="most_channels", channels=None)) == [2, 4]
    # The highest bit rate is the best quality: lossless first.
    assert picked(sel(languages=["en"], sort="highest_bitrate")) == [2, 4, 3]
    two = describe_kind([audio(1, channels=2), audio(2, channels=6), audio(3, channels=8)])
    assert picked(sel(sort="most_channels"), two) == [3, 2, 1]
    rates = describe_kind(
        [
            audio(1),
            audio(2, bitrate={"value": 448_000, "source": "stream"}),
            audio(3, bitrate={"value": 640_000, "source": "stream"}),
        ]
    )
    # An unknown bit rate comes after every known one.
    assert picked(sel(sort="highest_bitrate"), rates) == [3, 2, 1]


def test_subtitles_sort_full_before_sdh_before_forced() -> None:
    subs = describe_kind(
        [
            subtitle(1, title="Signs", disposition={"forced": True}),
            subtitle(2, title="SDH", disposition={"hearing_impaired": True}),
            subtitle(3, title="Full"),
        ]
    )
    selector = TrackSelector(kind="subtitle", sort="highest_bitrate")
    assert picked(selector, subs) == [3, 2, 1]
    assert picked(selector.model_copy(update={"sort": "source_order"}), subs) == [1, 2, 3]


def test_a_bad_title_pattern() -> None:
    assert isinstance(title_regex("(unclosed"), str)
    assert title_regex(None) is None
    assert not selector_matches(sel(title_pattern="x"), TRACKS[0], None)


def test_the_relaxation_order() -> None:
    """Drop the title, then the profiles (DTS-HD MA → any DTS), then channels, then codecs;
    never the language or the role."""
    assert RELAX_ORDER == ("title_pattern", "profiles", "channels", "codecs")
    full = sel(
        languages=["en"],
        codecs=["dts"],
        profiles=["DTS-HD MA"],
        channels=6,
        roles=[TrackRole.MAIN],
        title_pattern="^English Dub$",
    )
    steps = relaxation_steps(full)
    assert [dropped for dropped, _ in steps] == [
        (),
        ("title_pattern",),
        ("title_pattern", "profiles"),
        ("title_pattern", "profiles", "channels"),
        ("title_pattern", "profiles", "channels", "codecs"),
    ]
    last = steps[-1][1]
    assert (last.languages, last.roles) == (["en"], [TrackRole.MAIN])
    assert (last.codecs, last.profiles, last.channels, last.title_pattern) == (None,) * 4
    # Only the fields a selector sets are steps.
    assert [d for d, _ in relaxation_steps(sel(codecs=["dts"], channels=6))] == [
        (),
        ("channels",),
        ("channels", "codecs"),
    ]


def rule(
    selector: TrackSelector, *, multiple: bool = False, required: bool = True
) -> OutputTrackRule:
    settings = AudioOutputSettings() if selector.kind == "audio" else SubtitleOutputSettings()
    return OutputTrackRule(
        selector=selector, settings=settings, multiple=multiple, required=required
    )


def run(*rules: OutputTrackRule, tracks: list[Track] = TRACKS) -> list[Any]:
    picks, issues = match_rules(
        rules,
        tracks,
        "audio",
        labels=[f"A{n + 1}" for n in range(len(rules))],
        list_path="audio_rules",
    )
    return [picks, issues]


DUB = sel(
    languages=["en"],
    codecs=["dts"],
    profiles=["DTS-HD MA"],
    channels=6,
    roles=[TrackRole.MAIN],
    title_pattern="^English Dub$",
)

#: Every result row: (selector, multiple, required) → status, streams, relaxed fields, severity,
#: message.
RESULTS = [
    ("exact", DUB, False, True, "exact", [2], [], None, ""),
    (
        "relaxed: title",
        DUB.model_copy(update={"title_pattern": "^Dub$"}),
        False,
        True,
        "relaxed",
        [2],
        ["title_pattern"],
        Severity.WARNING,
        "matched without title",
    ),
    (
        "relaxed: title, profile",
        DUB.model_copy(update={"title_pattern": "^Dub$", "profiles": ["DTS-HD HRA"]}),
        False,
        True,
        "relaxed",
        [2],
        ["title_pattern", "profiles"],
        Severity.WARNING,
        "matched without title, profile",
    ),
    (
        "relaxed down to the codec: another eng main track",
        DUB.model_copy(update={"codecs": ["eac3"], "title_pattern": "^Dub$", "channels": 8}),
        False,
        True,
        "relaxed",
        [2],
        ["title_pattern", "profiles", "channels", "codecs"],
        Severity.WARNING,
        "matched without title, profile, channels, codec; 2 candidates, picked #2 (source order)",
    ),
    (
        "ambiguous",
        sel(languages=["en"], codecs=["ac3"], sort="source_order"),
        False,
        True,
        "ambiguous",
        [3],
        [],
        Severity.WARNING,
        "2 candidates, picked #3 (source order)",
    ),
    (
        "nth picks the second",
        sel(languages=["en"], codecs=["ac3"], nth=1),
        False,
        True,
        "exact",
        [4],
        [],
        None,
        "",
    ),
    (
        "missing, required",
        sel(languages=["ger"]),
        False,
        True,
        "missing",
        [],
        [],
        Severity.ERROR,
        "no track matches",
    ),
    (
        "missing, not required",
        sel(languages=["ger"]),
        False,
        False,
        "skipped",
        [],
        [],
        Severity.INFO,
        "no track matches: skipped (the rule is optional)",
    ),
    (
        "multiple",
        sel(languages=["en"], codecs=["ac3"]),
        True,
        True,
        "exact",
        [3, 4],
        [],
        None,
        "",
    ),
]


@pytest.mark.parametrize(
    (
        "case",
        "selector",
        "multiple",
        "required",
        "status",
        "streams",
        "relaxed",
        "severity",
        "message",
    ),
    RESULTS,
    ids=[r[0] for r in RESULTS],
)
def test_result_rows(
    case: str,
    selector: TrackSelector,
    multiple: bool,
    required: bool,
    status: str,
    streams: list[int],
    relaxed: list[str],
    severity: Severity | None,
    message: str,
) -> None:
    (pick,), issues = run(rule(selector, multiple=multiple, required=required))
    match = pick.match
    assert (match.status, match.streams, match.relaxed, match.severity, match.message) == (
        status,
        streams,
        relaxed,
        severity,
        message,
    ), case
    assert [t.descriptor.index for t in pick.tracks] == streams
    codes = {
        "exact": [],
        "relaxed": ["batch.track_relaxed"],
        "ambiguous": ["batch.track_ambiguous"],
        "missing": ["batch.track_missing"],
        "skipped": ["batch.track_skipped"],
    }[status]
    assert [i.code for i in issues] == codes
    for issue in issues:
        assert issue.severity is severity
        assert issue.path == "audio_rules[0]"


def test_a_missing_required_rule_offers_to_make_it_optional() -> None:
    (_pick,), (issue,) = run(rule(sel(languages=["ger"])))
    (fix,) = issue.fixes
    assert fix.target == "template"
    assert [op.model_dump() for op in fix.patch] == [
        {"op": "replace", "path": "/audio_rules/0/required", "value": False}
    ]


def test_relaxing_never_takes_a_track_another_rule_matches_exactly() -> None:
    """Rule 1 (an English AC-3 5.1 track titled "Main") relaxes; the only English AC-3 5.1 is
    rule 2's exact match, so rule 1 takes the next candidate of its relaxed selector."""
    first = sel(
        languages=["en"], codecs=["ac3"], channels=6, roles=[TrackRole.MAIN], title_pattern="^Main$"
    )
    second = sel(languages=["en"], codecs=["ac3"], channels=6, roles=[TrackRole.MAIN])
    picks, _ = run(rule(first), rule(second))
    assert picks[1].match.streams == [4]
    # Without the title, #4 is taken: channels go next (#6 is undetermined, not English),
    # then the codec: #2 (DTS-HD MA).
    assert picks[0].match.status == "relaxed"
    assert picks[0].match.streams == [2]
    assert picks[0].match.relaxed == ["title_pattern", "channels", "codecs"]


def test_two_relaxed_rules_do_not_share_a_track() -> None:
    a = sel(languages=["en"], roles=[TrackRole.MAIN], title_pattern="^x$")
    b = sel(languages=["en"], roles=[TrackRole.MAIN], title_pattern="^y$")
    picks, _ = run(rule(a), rule(b))
    assert [p.match.streams for p in picks] == [[2], [4]]


def test_exact_matches_may_share_a_track() -> None:
    a = sel(languages=["en"], codecs=["dts"])
    picks, _ = run(rule(a), rule(a))
    assert [p.match.streams for p in picks] == [[2], [2]]


def test_a_hand_picked_stream() -> None:
    picks, issues = run(rule(sel(languages=["ger"], stream=5)))
    assert (picks[0].match.status, picks[0].match.streams) == ("exact", [5])
    assert picks[0].match.message == "#5 picked by hand"
    assert issues == []
    picks, issues = run(rule(sel(stream=9)))
    assert picks[0].match.status == "missing"
    assert picks[0].match.message == "the picked track #9 is not an audio track of this file"
    assert [i.code for i in issues] == ["batch.track_missing"]
    picks, issues = run(rule(sel(stream=9), required=False))
    assert picks[0].match.status == "skipped"


def test_rules_that_cannot_match() -> None:
    picks, issues = run(rule(sel(title_pattern="(")), rule(TrackSelector(kind="subtitle")))
    assert [p.match.status for p in picks] == ["missing", "missing"]
    assert [i.code for i in issues] == [
        "batch.bad_title_pattern",
        "batch.rule_kind",
        "batch.track_missing",
        "batch.track_missing",
    ]
    assert issues[0].path == "audio_rules[0].selector.title_pattern"
    assert issues[1].path == "audio_rules[1].selector.kind"
