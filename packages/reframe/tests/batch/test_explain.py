"""C-12 ``explain``, ``explain_subtitles`` and ``draft_tracks`` with the selection stage (05
§C-12; 03 §Audio defaults, §Subtitles; decision 0031): the example of 03 row by row, M6 demo
item 5, the default track, the foreign audio search, burn-in, and the keep-everything mode."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, Literal

import pytest

from reframe.batch import draft_tracks, explain, explain_subtitles, foreign_audio_search
from reframe.batch.explain import audio_language, forced_evidence, subtitle_stage
from reframe.batch.selection import KEEP_EVERYTHING
from reframe.jsonpatch import apply_patch
from reframe.models import (
    AudioCodecRule,
    AudioDefaults,
    AudioOutputTrack,
    AudioRuleExtras,
    AudioStream,
    BurnInBehaviour,
    ExtraAudioOutput,
    JobTemplate,
    LanguageSettings,
    MediaSource,
    OutputOptions,
    Severity,
    SubtitleDefaults,
    SubtitleOutputTrack,
    SubtitleStream,
    TrackMetadata,
    TrackRole,
    TrackSelection,
)
from reframe.probe import ProbeError
from reframe.service import Reframe


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
source: Callable[..., MediaSource] = T.source
role: Callable[..., Any] = T.role

type DefaultTrack = Literal["first_output", "first_in_first_language", "forced", "none"]


def summary(track: AudioOutputTrack) -> tuple[str, str | None, str | None, int | None]:
    return (track.action, track.encoder, track.mixdown, track.bitrate)


def defaults_flags(tracks: list[AudioOutputTrack] | list[SubtitleOutputTrack]) -> list[bool]:
    return [t.metadata.default for t in tracks]


# =========================================================================== 03's example

#: The four rules of 03 §Audio defaults (the same as tests/batch/test_audio_rules.py).
EXAMPLE_RULES = [
    AudioCodecRule(
        languages=["hu"], source_channels="5.1_or_more", codec="ac3", mixdown="5.1",
        max_bitrate=320, if_fits="passthru",
    ),
    AudioCodecRule(
        languages=["en"], source_channels="5.1_or_more", codec="ac3", mixdown="5.1",
        max_bitrate=384, if_fits="passthru",
    ),
    AudioCodecRule(
        languages=None, source_channels="stereo_or_less", codec="aac", mixdown="stereo",
        max_bitrate=160, if_fits="passthru",
    ),
    AudioCodecRule(
        languages=None, source_channels="any", codec="libopus", mixdown="up_to_5.1",
        max_bitrate=256, if_fits="reencode",
    ),
]  # fmt: skip

#: Hungarian, English; every matching track, so that all four rows of 03 are selected.
EXAMPLE_DEFAULTS = AudioDefaults(
    selection=TrackSelection(languages=["hu", "en"], tracks_per_language="all"),
    codec_rules=EXAMPLE_RULES,
)

EXAMPLE_SOURCE = source(
    [
        audio(1, "hun", "dts", 6, 2104, lossless=True),
        audio(2, "hun", "ac3", 6, 224),
        audio(3, "eng", "truehd", 8, None, lossless=True),  # 03 gives no bit rate
        audio(4, "eng", "ac3", 2, 192, title="English Stereo"),
    ]
)

#: (stream, rule, output, reason, measure): the "With your setup" table of 03, row by row.
EXAMPLE_ROWS = [
    (1, 1, ("encode", "ac3", "5.1", 320), "Lossless source → encode at the max", False),
    (2, 1, ("passthru", "ac3", None, None), "AC-3, 5.1, 224 ≤ 320: passthru", False),
    (
        3, 2, ("encode", "ac3", "5.1", 384),
        "Downmix 7.1 → 5.1. Lossless source → encode at the max", True,
    ),
    (
        4, 3, ("passthru", "aac", None, None),
        "Rule 2 needs 5.1 or more. Rule 3 matches, and the source fits (a lossy source is kept "
        "above the max)",
        False,
    ),
]  # fmt: skip


def test_example_of_03_row_by_row_through_draft_and_explain() -> None:
    """C-12 "Done when": Hungarian 5.1 → 320, English 5.1 → 384, AC-3 224 passthru, stereo
    passthru (decision 0023), now through the selection stage."""
    template = JobTemplate(audio_defaults=EXAMPLE_DEFAULTS)
    draft = draft_tracks(EXAMPLE_SOURCE, template)
    decisions = explain(EXAMPLE_DEFAULTS, EXAMPLE_SOURCE)
    assert decisions == draft.decisions
    got = [(d.source_stream, d.rule, summary(d.outputs[0]), d.reason, d.measure) for d in decisions]
    assert got == EXAMPLE_ROWS
    assert all(d.selected and d.kind == "audio" for d in decisions)
    assert [d.selection for d in decisions] == [
        "Hungarian: all matching tracks",
        "Hungarian: all matching tracks",
        "English: all matching tracks",
        "English: all matching tracks",
    ]
    # Output order: Hungarian then English, each best quality first (lossless first).
    assert [t.source_stream for t in draft.audio] == [1, 2, 3, 4]
    assert defaults_flags(draft.audio) == [True, False, False, False]
    assert decisions[0].notes == ["The default audio track (the first output track)"]
    assert draft.issues == []


def test_m6_demo_item_5() -> None:
    """08 §M6 demo item 5: "Audio defaults `Hungarian 5.1 or more → AC-3 5.1, max 320` and
    `English 5.1 or more → AC-3 5.1, max 384`: the live preview shows that DTS-HD MA becomes
    AC-3 320, an AC-3 224 kb/s source is passed through, and a stereo track falls to the next
    rule. Each row has a reason." """
    media = source(
        [
            audio(1, "hun", "dts", 6, 2104, lossless=True),
            audio(2, "hun", "ac3", 6, 224),
            audio(3, "eng", "ac3", 2, 192, title="English Stereo"),
            audio(4, "jpn", "aac", 2, 128),  # not selected: a row with a reason too
        ]
    )
    rows = explain(EXAMPLE_DEFAULTS, media)
    preview = [
        (d.source_stream, d.selected, d.selection, d.rule, [summary(t) for t in d.outputs])
        for d in rows
    ]
    assert preview == [
        (1, True, "Hungarian: all matching tracks", 1, [("encode", "ac3", "5.1", 320)]),
        (2, True, "Hungarian: all matching tracks", 1, [("passthru", "ac3", None, None)]),
        (3, True, "English: all matching tracks", 3, [("passthru", "aac", None, None)]),
        (4, False, "Japanese is not a listed language: dropped", None, []),
    ]
    assert rows[0].reason == "Lossless source → encode at the max"
    assert rows[1].reason == "AC-3, 5.1, 224 ≤ 320: passthru"
    assert rows[2].reason.startswith("Rule 2 needs 5.1 or more. Rule 3 matches")
    assert rows[3].reason == "Japanese is not a listed language: dropped"
    assert all(d.reason for d in rows)


@pytest.mark.anyio
async def test_m6_demo_item_5_through_the_facade(tmp_path: Path) -> None:
    """``Reframe.jobs.explain`` with the languages of Settings (the selection has none)."""
    app = await Reframe.create(tmp_path / "config", tmp_path / "data", cache_dir=tmp_path / "c")
    try:
        result = await app.settings.update(
            [
                {"op": "replace", "path": "/languages/preferred_audio", "value": ["hu", "en"]},
                {"op": "replace", "path": "/languages/preferred_subtitle", "value": ["hu"]},
            ]
        )
        assert result.ok
        template = JobTemplate(
            audio_defaults=AudioDefaults(
                selection=TrackSelection(tracks_per_language="all"), codec_rules=EXAMPLE_RULES
            ),
            subtitle_defaults=SubtitleDefaults(
                selection=TrackSelection(tracks_per_language="first", no_match="none")
            ),
        )
        media = source(
            [*EXAMPLE_SOURCE.audio, audio(5, "jpn", "aac", 2, 128)],
            [subtitle(6, "eng"), subtitle(7, "hun")],
        )
        draft = await app.jobs.explain(media, template)
        assert not isinstance(draft, ProbeError)
        got = [(d.source_stream, d.rule, d.reason, d.measure) for d in draft.decisions[:4]]
        assert got == [(s, r, reason, m) for s, r, _, reason, m in EXAMPLE_ROWS]
        assert not draft.decisions[4].selected
        assert [(d.source_stream, d.selected) for d in draft.subtitle_decisions] == [
            (6, False),
            (7, True),
        ]
        assert [t.source for t in draft.subtitles] == [7]
    finally:
        await app.close()


# =========================================================================== audio: default track

DEFAULT_SOURCE = source(
    [
        audio(1, "eng", "ac3", 6, 448, default=True),
        audio(2, "hun", "ac3", 6, 448),
        audio(3, "hun", "ac3", 2, 192, forced=True),
    ]
)


@pytest.mark.parametrize(
    ("policy", "expected", "note"),
    [
        ("first_output", [True, False, False], "the first output track"),
        ("first_in_first_language", [False, True, False], "the first track in the first language"),
        ("forced", [False, False, True], "the forced track"),
        ("none", [False, False, False], None),
    ],
)
def test_audio_default_track(policy: DefaultTrack, expected: list[bool], note: str | None) -> None:
    """Only the ``default`` flag is overridden (the source's flag on track 1 is cleared when
    another track is the default); at most one default track."""
    defaults = AudioDefaults(
        selection=TrackSelection(
            languages=["hu", "en"], tracks_per_language="all", order="source", default_track=policy
        )
    )
    draft = draft_tracks(DEFAULT_SOURCE, JobTemplate(audio_defaults=defaults))
    assert [t.source_stream for t in draft.audio] == [1, 2, 3]
    assert defaults_flags(draft.audio) == expected
    notes = [n for d in draft.decisions for n in d.notes if n.startswith("The default")]
    assert notes == ([f"The default audio track ({note})"] if note else [])
    # Every other flag stays the source's.
    assert [t.metadata.forced for t in draft.audio] == [False, False, True]


def test_first_in_first_language_falls_back_to_the_first_output() -> None:
    defaults = AudioDefaults(
        selection=TrackSelection(
            languages=["de", "en"], default_track="first_in_first_language", order="source"
        )
    )
    draft = draft_tracks(DEFAULT_SOURCE, JobTemplate(audio_defaults=defaults))
    assert [t.source_stream for t in draft.audio] == [1]
    assert defaults_flags(draft.audio) == [True]


def test_extra_outputs_are_never_the_default_track() -> None:
    rule = AudioCodecRule(
        codec="ac3",
        mixdown="5.1",
        max_bitrate=448,
        extras=AudioRuleExtras(extra_outputs=[ExtraAudioOutput(codec="aac", bitrate=160)]),
    )
    defaults = AudioDefaults(selection=TrackSelection(languages=["en"]), codec_rules=[rule])
    draft = draft_tracks(DEFAULT_SOURCE, JobTemplate(audio_defaults=defaults))
    assert [(t.source_stream, t.action) for t in draft.audio] == [(1, "passthru"), (1, "encode")]
    assert defaults_flags(draft.audio) == [True, False]


def test_first_track_of_language_follows_the_selection() -> None:
    """``first_track_of_language_only`` = the first selected track of its language in the
    output order (best quality puts the lossless track 2 first), not in source order."""
    first_only = AudioCodecRule(
        languages=["hu"],
        codec="ac3",
        mixdown="5.1",
        max_bitrate=640,
        extras=AudioRuleExtras(first_track_of_language_only=True),
    )
    defaults = AudioDefaults(
        selection=TrackSelection(languages=["hu"], tracks_per_language="all"),
        codec_rules=[first_only, AudioCodecRule(codec="aac", mixdown="stereo", max_bitrate=128)],
    )
    media = source([audio(1, "hun", "ac3", 2, 192), audio(2, "hun", "dts", 6, 1500, lossless=True)])
    rows = explain(defaults, media)
    assert [(d.source_stream, d.rule) for d in rows] == [(1, 2), (2, 1)]
    assert rows[0].reason.startswith("Rule 1 is only for the first track of a language")


def test_an_undetermined_track_is_treated_as_the_first_language() -> None:
    """``undetermined = first_language``: selected as Hungarian, matched by the Hungarian
    rule, and written as Hungarian (decision 0031)."""
    defaults = AudioDefaults(
        selection=TrackSelection(languages=["hu"], undetermined="first_language"),
        codec_rules=[EXAMPLE_RULES[0], EXAMPLE_RULES[3]],
    )
    media = source([audio(1, None, "dts", 6, 2104, lossless=True)])
    (row,) = explain(defaults, media)
    assert row.rule == 1
    assert row.outputs[0].metadata.language == "hu"
    assert row.notes[0] == (
        "Undetermined language: treated and written as Hungarian, the first listed language"
    )
    assert row.selection == "Undetermined (treated as Hungarian): the first matching track"


def test_dropped_tracks_have_a_reason_and_no_output() -> None:
    defaults = AudioDefaults(selection=TrackSelection(languages=["hu"]))
    media = source([audio(1, "hun"), audio(2, "jpn"), audio(3, "hun", comment=True)])
    rows = explain(defaults, media)
    dropped = [d for d in rows if not d.selected]
    assert [d.source_stream for d in dropped] == [2, 3]
    for d in dropped:
        assert d.reason == d.selection
        assert d.outputs == []
        assert d.rule is None
        assert d.kind == "audio"
    assert dropped[1].reason == "Commentary (disposition comment): dropped"


def test_no_listed_language_take_none_is_an_error_with_fixes() -> None:
    defaults = AudioDefaults(selection=TrackSelection(languages=["hu", "de"], no_match="none"))
    template = JobTemplate(audio_defaults=defaults)
    media = source([audio(1, "jpn", default=True), audio(2, "eng")])
    draft = draft_tracks(media, template)
    assert draft.audio == []
    (issue,) = [i for i in draft.issues if i.code == "defaults.no_listed_language"]
    assert issue.severity is Severity.ERROR
    assert issue.path == "audio_defaults.selection.no_match"
    assert issue.message == (
        "This source has no audio track in Hungarian or German, and the audio defaults take no "
        "track when no listed language is found."
    )
    assert [f.label for f in issue.fixes] == [
        "Take the default-flagged track",
        "Take the first track",
    ]
    for fix, stream in zip(issue.fixes, (1, 1), strict=True):
        assert fix.target == "template"
        fixed = JobTemplate.model_validate(apply_patch(template.model_dump(mode="json"), fix.patch))
        again = draft_tracks(media, fixed)
        assert [t.source_stream for t in again.audio] == [stream]
        assert not [i for i in again.issues if i.code == "defaults.no_listed_language"]
    # A source without audio is not an error.
    assert draft_tracks(source(), template).issues == []


def test_the_draft_has_the_lint_for_this_source() -> None:
    """``defaults.rule_unused`` for a rule no selected track uses (C-12 lint with a source)."""
    template = JobTemplate(audio_defaults=EXAMPLE_DEFAULTS)
    media = source([audio(1, "hun", "ac3", 6, 224)])
    draft = draft_tracks(media, template)
    assert [(i.code, i.path) for i in draft.issues] == [
        ("defaults.rule_unused", "audio_defaults.codec_rules[1]"),
        ("defaults.rule_unused", "audio_defaults.codec_rules[2]"),
    ]


# =========================================================================== keep everything


def test_keep_everything_keeps_the_source_flags_with_one_default() -> None:
    """No language set: every track in source order with its source flags (M2), but at most
    one default track per kind (mkvmerge writes ``FlagDefault=1`` on every track it is not
    told otherwise: testdata/README.md)."""
    media = source(
        [audio(1, "jpn", default=True), audio(2, "eng", default=True, comment=True)],
        [subtitle(3, "eng", default=True), subtitle(4, "eng", default=True, forced=True)],
    )
    template = JobTemplate(
        subtitle_defaults=SubtitleDefaults(foreign_audio_search=True, burn_in="first")
    )
    draft = draft_tracks(media, template)
    assert [t.source_stream for t in draft.audio] == [1, 2]
    assert defaults_flags(draft.audio) == [True, False]
    assert [t.metadata.commentary for t in draft.audio] == [False, True]
    # Every subtitle copied: no foreign audio search, no burn-in.
    assert [(t.source, t.action) for t in draft.subtitles] == [(3, "copy"), (4, "copy")]
    assert defaults_flags(draft.subtitles) == [True, False]
    assert [t.metadata.forced for t in draft.subtitles] == [False, True]
    assert {d.selection for d in draft.decisions} == {KEEP_EVERYTHING["audio"]}
    assert {d.selection for d in draft.subtitle_decisions} == {KEEP_EVERYTHING["subtitle"]}
    assert {d.reason for d in draft.subtitle_decisions} == {"Copy"}
    assert all(d.notes == [] for d in draft.decisions)


def test_settings_languages_switch_the_selection_on() -> None:
    media = source([audio(1, "jpn"), audio(2, "eng")], [subtitle(3, "eng"), subtitle(4, "hun")])
    template = JobTemplate(
        subtitle_defaults=SubtitleDefaults(selection=TrackSelection(no_match="none"))
    )
    plain = draft_tracks(media, template)
    assert len(plain.audio) == 2
    assert len(plain.subtitles) == 2
    languages = LanguageSettings(preferred_audio=["en"], preferred_subtitle=["hu"])
    chosen = draft_tracks(media, template, languages=languages)
    assert [t.source_stream for t in chosen.audio] == [2]
    assert [t.source for t in chosen.subtitles] == [4]
    only_audio = draft_tracks(media, template, languages=LanguageSettings(preferred_audio=["en"]))
    assert len(only_audio.audio) == 1
    assert len(only_audio.subtitles) == 2  # no subtitle language: every subtitle


# =========================================================================== foreign audio search

ENGLISH_AUDIO = [
    AudioOutputTrack(
        action="passthru",
        encoder="aac",
        source_stream=1,
        metadata=TrackMetadata(language="en", default=True),
    )
]


def fas_defaults(burn_in: BurnInBehaviour = "none", **selection: Any) -> SubtitleDefaults:
    settings: dict[str, Any] = {"languages": ["en"], "no_match": "none", "default_track": "none"}
    return SubtitleDefaults(
        selection=TrackSelection(**(settings | selection)),
        foreign_audio_search=True,
        burn_in=burn_in,
    )


def fas_source(*forced: SubtitleStream) -> MediaSource:
    return source(
        [audio(1, "eng")],
        [subtitle(2, "eng", events=900), subtitle(3, "eng", events=950, hearing_impaired=True),
         *forced, subtitle(9, "hun", events=800)],
    )  # fmt: skip


@pytest.mark.parametrize(
    ("forced", "evidence"),
    [
        (subtitle(4, "eng", forced=True, events=20), "forced flag"),
        (
            subtitle(4, "eng", title="English [Forced]", roles=[
                role(TrackRole.FORCED, "title", 'title contains "Forced"')]),
            'title contains "Forced"',
        ),
        (
            subtitle(4, "eng", "hdmv_pgs_subtitle", events=30, forced_events=30),
            "all 30 events are forced",
        ),
        (
            subtitle(4, "eng", "ass", title="Signs & Songs", roles=[
                role(TrackRole.SIGNS, "title", 'title contains "Signs"')]),
            'Signs & Songs, title contains "Signs"',
        ),
        (
            subtitle(4, "eng", events=20, roles=[
                role(TrackRole.FORCED, "heuristic", "20 events, 2 % of the 950 events")]),
            "20 events, 2 % of the 950 events",
        ),
        # Counts measured after the probe (no role yet): compared here too.
        (subtitle(4, "eng", events=20), "20 events, 2 % of the 950 events of track #3"),
    ],
)  # fmt: skip
def test_foreign_audio_search_finds_the_forced_track(forced: SubtitleStream, evidence: str) -> None:
    media = fas_source(forced)
    stage = subtitle_stage(fas_defaults(), media, audio=ENGLISH_AUDIO)
    assert stage.foreign_audio is not None
    assert stage.foreign_audio.track is not None
    assert media.subtitles[stage.foreign_audio.track].index == 4
    assert stage.foreign_audio.evidence == evidence
    # Put first and flagged forced; the language selection's full track follows.
    assert [(t.source, t.action, t.metadata.forced) for t in stage.outputs] == [
        (4, "copy", True),
        (2, "copy", False),
    ]
    row = next(d for d in stage.decisions if d.source_stream == 4)
    assert row.selected
    assert row.selection == (
        f"Foreign audio search: #4 is the forced English track ({evidence}) for the English audio"
    )
    assert row.reason == "Copy, flagged forced (foreign audio search)"
    assert row.kind == "subtitle"


def test_foreign_audio_search_takes_the_strongest_evidence() -> None:
    media = fas_source(
        subtitle(4, "eng", events=20),  # few events (rank 3)
        subtitle(5, "eng", "ass", title="Signs", roles=[role(TrackRole.SIGNS)]),  # rank 2
        subtitle(6, "eng", forced=True, events=25),  # the forced flag (rank 0)
        subtitle(7, "eng", events=10, comment=True),  # commentary: never
    )
    stage = subtitle_stage(fas_defaults(), media, audio=ENGLISH_AUDIO)
    assert [t.source for t in stage.outputs] == [6, 2]


def test_forced_events_in_a_full_bitmap_track_need_burn_in() -> None:
    """A full PGS track with some forced events can only show just those when it is burned in
    with forced-only (``forced_subs_only``: decision 0014)."""
    pgs = subtitle(4, "eng", "hdmv_pgs_subtitle", events=900, forced_events=12)
    media = fas_source(pgs)
    copied = subtitle_stage(fas_defaults(), media, audio=ENGLISH_AUDIO)
    assert copied.foreign_audio is not None
    assert copied.foreign_audio.track is None
    assert copied.foreign_audio.note == (
        "Foreign audio search: #4 has 12 forced events in a full track, but only a burned-in "
        "track can show just them (burn-in: none)"
    )
    assert [t.source for t in copied.outputs] == [2]
    assert (
        copied.foreign_audio.note in next(d for d in copied.decisions if d.source_stream == 4).notes
    )
    burned = subtitle_stage(fas_defaults("foreign_audio"), media, audio=ENGLISH_AUDIO)
    assert [(t.source, t.action, t.forced_only) for t in burned.outputs] == [
        (4, "burn", True),
        (2, "copy", False),
    ]
    row = next(d for d in burned.decisions if d.source_stream == 4)
    assert row.reason == "Burn in (foreign audio search, forced events only)"


def test_foreign_audio_search_needs_the_viewers_language() -> None:
    """HandBrake runs the search only when the first audio track is in the first subtitle
    language: the forced track translates the foreign parts of audio the viewer understands."""
    media = source(
        [audio(1, "jpn")],
        [subtitle(2, "jpn", forced=True), subtitle(3, "eng")],
    )
    japanese = [ENGLISH_AUDIO[0].model_copy(update={"metadata": TrackMetadata(language="ja")})]
    stage = subtitle_stage(fas_defaults(), media, audio=japanese)
    assert stage.foreign_audio is not None
    assert not stage.foreign_audio.searched
    assert [t.source for t in stage.outputs] == [3]
    note = (
        "Foreign audio search: not run, the audio is Japanese and the first subtitle language "
        "is English"
    )
    assert stage.decisions[0].notes == [note]
    result = foreign_audio_search(
        media.subtitles, audio_language=None, user_language="en", can_burn=False
    )
    assert result.note == "Foreign audio search: no audio language"
    assert not result.searched


def test_no_forced_track_found() -> None:
    media = fas_source()
    stage = subtitle_stage(fas_defaults(), media, audio=ENGLISH_AUDIO)
    assert stage.foreign_audio is not None
    assert stage.foreign_audio.searched
    assert stage.foreign_audio.track is None
    note = (
        "Foreign audio search: no forced English subtitle track (no forced flag or title, and "
        "no low event count)"
    )
    assert [d.notes for d in stage.decisions] == [[note], [note], []]
    assert forced_evidence(subtitle(5, "eng"), []) is None


def test_the_audio_language() -> None:
    media = source([audio(1, "jpn"), audio(2, "eng", default=True)])
    second_default = [
        AudioOutputTrack(action="passthru", source_stream=1, metadata=TrackMetadata(language="ja")),
        AudioOutputTrack(action="passthru", source_stream=2, metadata=TrackMetadata(default=True)),
    ]
    assert audio_language(second_default, media) == "en"  # the default output, from its source
    assert audio_language(second_default[:1], media) == "ja"
    assert audio_language([], media) == "en"  # the source's default-flagged track
    assert audio_language([], source()) is None
    lost = [AudioOutputTrack(action="passthru", source_stream=7)]
    assert audio_language(lost, media) is None


def test_explain_subtitles_without_audio_uses_the_source_default_audio() -> None:
    media = fas_source(subtitle(4, "eng", forced=True))
    rows = explain_subtitles(fas_defaults(), media)
    assert [(d.source_stream, d.selected) for d in rows] == [
        (2, True),
        (3, False),
        (4, True),
        (9, False),
    ]


# =========================================================================== burn-in

BURN = source(
    [audio(1, "eng")],
    [subtitle(2, "eng", events=900), subtitle(4, "eng", forced=True, events=20)],
)


@pytest.mark.parametrize(
    ("burn_in", "search", "expected", "why"),
    [
        ("none", True, [(4, "copy"), (2, "copy")], None),
        ("foreign_audio", True, [(4, "burn"), (2, "copy")], "foreign audio search"),
        ("first", True, [(4, "burn"), (2, "copy")], "the first subtitle track"),
        ("foreign_audio_then_first", True, [(4, "burn"), (2, "copy")], "foreign audio search"),
        ("foreign_audio", False, [(2, "copy")], None),  # the audio is the viewer's language
        ("first", False, [(2, "burn")], "the first subtitle track"),
        ("foreign_audio_then_first", False, [(2, "burn")], "the first subtitle track"),
    ],
)
def test_burn_in(
    burn_in: BurnInBehaviour, search: bool, expected: list[tuple[int, str]], why: str | None
) -> None:
    defaults = fas_defaults(burn_in).model_copy(update={"foreign_audio_search": search})
    stage = subtitle_stage(defaults, BURN, audio=ENGLISH_AUDIO)
    assert [(t.source, t.action) for t in stage.outputs] == expected
    burned = [
        d
        for d in stage.decisions
        if d.subtitle_outputs[:1] and d.subtitle_outputs[0].action == "burn"
    ]
    assert len(burned) == (0 if why is None else 1)
    if why is not None:
        assert burned[0].reason == f"Burn in ({why})"
        assert burned[0].subtitle_outputs[0].metadata.default is False


def test_burn_in_for_foreign_audio() -> None:
    """The audio is not in the viewer's language: ``foreign_audio`` burns the first selected
    subtitle in that language (HandBrake's "foreign audio subtitle")."""
    media = source([audio(1, "jpn")], [subtitle(2, "eng"), subtitle(3, "hun"), subtitle(4, "hun")])
    japanese = [ENGLISH_AUDIO[0].model_copy(update={"metadata": TrackMetadata(language="ja")})]
    defaults = fas_defaults(
        "foreign_audio", languages=["hu", "en"], tracks_per_language="all", order="source"
    )
    stage = subtitle_stage(defaults, media, audio=japanese)
    assert [(t.source, t.action) for t in stage.outputs] == [(2, "copy"), (3, "burn"), (4, "copy")]
    row = next(d for d in stage.decisions if d.source_stream == 3)
    assert row.reason == "Burn in (foreign audio: the Hungarian subtitles for the Japanese audio)"


# =========================================================================== subtitle default track

POLICY = source(
    [audio(1, "eng")],
    [subtitle(2, "eng"), subtitle(3, "eng", forced=True), subtitle(5, "hun")],
)


@pytest.mark.parametrize(
    ("languages", "policy", "default"),
    [
        (["hu", "en"], "none", None),
        (["hu", "en"], "first_output", 5),
        (["hu", "en"], "forced", 3),
        (["hu", "en"], "first_in_first_language", 5),
        (["de", "en"], "first_in_first_language", 2),  # no German: the first output
    ],
)
def test_subtitle_default_track(
    languages: list[str], policy: DefaultTrack, default: int | None
) -> None:
    defaults = SubtitleDefaults(
        selection=TrackSelection(
            languages=languages, tracks_per_language="all", default_track=policy, no_match="none"
        )
    )
    stage = subtitle_stage(defaults, POLICY, audio=ENGLISH_AUDIO)
    flagged = [t.source for t in stage.outputs if t.metadata.default]
    assert flagged == ([] if default is None else [default])
    if default is not None:
        row = next(d for d in stage.decisions if d.source_stream == default)
        assert "the default subtitle track" in row.reason


def test_subtitle_order_and_container_notes() -> None:
    media = source(
        [audio(1, "eng")],
        [subtitle(2, "eng", "hdmv_pgs_subtitle"), subtitle(3, "eng", "subrip")],
    )
    defaults = SubtitleDefaults(
        selection=TrackSelection(languages=["en"], tracks_per_language="all")
    )
    rows = explain_subtitles(defaults, media, container="mp4", audio=ENGLISH_AUDIO)
    assert [d.notes for d in rows] == [
        [
            "MP4 cannot hold hdmv_pgs_subtitle subtitles: validation offers burn-in or another "
            "container"
        ],
        ["MP4: converted to mov_text"],
    ]
    assert explain_subtitles(defaults, media, container="mkv", audio=ENGLISH_AUDIO)[0].notes == []
    draft = draft_tracks(
        media,
        JobTemplate(output=OutputOptions(container="mp4"), subtitle_defaults=defaults),
        languages=LanguageSettings(preferred_audio=["en"]),
    )
    assert [d.notes for d in draft.subtitle_decisions] == [d.notes for d in rows]


def test_undetermined_subtitles_are_written_as_the_first_language() -> None:
    media = source([audio(1, "hun")], [subtitle(2, None)])
    defaults = SubtitleDefaults(
        selection=TrackSelection(languages=["hu"], undetermined="first_language")
    )
    stage = subtitle_stage(defaults, media)
    assert stage.outputs[0].metadata.language == "hu"
    assert stage.decisions[0].notes == [
        "Undetermined language: treated and written as Hungarian, the first listed language"
    ]
