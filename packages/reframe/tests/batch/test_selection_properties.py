"""Property tests of the audio and subtitle defaults (C-12, decision 0031): for any source
and any settings, every source track has exactly one decision, at most one track per kind is
the default, outputs come only from selected tracks, at most one subtitle is burned in, and
the output order follows the ``order`` setting."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from reframe.batch import draft_tracks, effective_language, effective_languages
from reframe.batch.selection import extra_role, language_slot
from reframe.definitions import load_definitions
from reframe.models import (
    AudioCodecRule,
    AudioDefaults,
    AudioRuleExtras,
    AudioStream,
    ExtraAudioOutput,
    JobTemplate,
    LanguageSettings,
    MediaSource,
    OutputOptions,
    SubtitleDefaults,
    SubtitleStream,
    TrackDraft,
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
make_audio: Callable[..., AudioStream] = T.audio
make_subtitle: Callable[..., SubtitleStream] = T.subtitle
make_source: Callable[..., MediaSource] = T.source

DEFS = load_definitions()

TRACK_LANGUAGES = [None, "und", "hun", "eng", "jpn", "ger", "por", "fre"]
LISTED = ["hu", "en", "ja", "de", "pt", "pt-BR", "und"]
AUDIO_CODECS = [
    ("ac3", False),
    ("eac3", False),
    ("aac", False),
    ("dts", True),
    ("truehd", True),
    ("flac", True),
]
SUBTITLE_CODECS = ["subrip", "ass", "hdmv_pgs_subtitle", "dvd_subtitle"]

RULE_SETS = [
    [AudioCodecRule(codec="aac", mixdown="up_to_5.1", max_bitrate=256)],
    [
        AudioCodecRule(
            languages=["hu"], source_channels="5.1_or_more", codec="ac3", mixdown="5.1",
            max_bitrate=320,
            extras=AudioRuleExtras(extra_outputs=[ExtraAudioOutput(codec="aac", bitrate=160)]),
        ),
        AudioCodecRule(
            languages=["en"], codec="ac3", mixdown="5.1", max_bitrate=384,
            extras=AudioRuleExtras(first_track_of_language_only=True),
        ),
        AudioCodecRule(codec="libopus", mixdown="up_to_5.1", max_bitrate=256, if_fits="reencode"),
    ],
]  # fmt: skip


@st.composite
def audio_tracks(draw: st.DrawFn, start: int) -> list[AudioStream]:
    count = draw(st.integers(0, 6))
    tracks: list[AudioStream] = []
    for n in range(count):
        codec, lossless = draw(st.sampled_from(AUDIO_CODECS))
        kbps = draw(st.none() | st.integers(64, 4000))
        tracks.append(
            make_audio(
                start + n,
                draw(st.sampled_from(TRACK_LANGUAGES)),
                codec,
                draw(st.sampled_from([1, 2, 6, 8])),
                kbps,
                lossless=lossless,
                default=draw(st.booleans()),
                comment=draw(st.booleans()),
                visual_impaired=draw(st.booleans()),
                forced=draw(st.booleans()),
            )
        )
    return tracks


@st.composite
def subtitle_tracks(draw: st.DrawFn, start: int) -> list[SubtitleStream]:
    count = draw(st.integers(0, 6))
    tracks: list[SubtitleStream] = []
    for n in range(count):
        events = draw(st.none() | st.integers(0, 2000))
        forced_events = draw(st.none() | st.integers(0, events or 0))
        tracks.append(
            make_subtitle(
                start + n,
                draw(st.sampled_from(TRACK_LANGUAGES)),
                draw(st.sampled_from(SUBTITLE_CODECS)),
                events=events,
                forced_events=forced_events,
                default=draw(st.booleans()),
                forced=draw(st.booleans()),
                hearing_impaired=draw(st.booleans()),
                comment=draw(st.booleans()),
            )
        )
    return tracks


def selections() -> st.SearchStrategy[TrackSelection]:
    return st.builds(
        TrackSelection,
        languages=st.none() | st.lists(st.sampled_from(LISTED), max_size=3),
        tracks_per_language=st.sampled_from(["none", "first", "all"]),
        tie_break=st.sampled_from(["source_order", "most_channels", "best_quality"]),
        undetermined=st.sampled_from(["first_language", "other"]),
        other_languages=st.sampled_from(["drop", "keep_first", "keep_all"]),
        no_match=st.sampled_from(["default_flagged", "first_track", "none"]),
        commentary=st.sampled_from(["drop", "keep_after_main"]),
        order=st.sampled_from(["language_list", "source"]),
        default_track=st.sampled_from(
            ["first_output", "first_in_first_language", "forced", "none"]
        ),
    )


@st.composite
def cases(draw: st.DrawFn) -> tuple[MediaSource, JobTemplate, LanguageSettings]:
    audio = draw(audio_tracks(1))
    subtitles = draw(subtitle_tracks(1 + len(audio)))
    template = JobTemplate(
        output=OutputOptions(container=draw(st.sampled_from(["mkv", "mp4"]))),
        audio_defaults=AudioDefaults(
            selection=draw(selections()), codec_rules=draw(st.sampled_from(RULE_SETS))
        ),
        subtitle_defaults=SubtitleDefaults(
            selection=draw(selections()),
            foreign_audio_search=draw(st.booleans()),
            burn_in=draw(
                st.sampled_from(["none", "foreign_audio", "first", "foreign_audio_then_first"])
            ),
        ),
    )
    languages = LanguageSettings(
        preferred_audio=draw(st.lists(st.sampled_from(LISTED), max_size=2)),
        preferred_subtitle=draw(st.lists(st.sampled_from(LISTED), max_size=2)),
    )
    return make_source(audio, subtitles), template, languages


def _first_positions(sources: list[int]) -> list[int]:
    """The source streams in output order, one entry per track (extra outputs of the same
    track are adjacent)."""
    seen: list[int] = []
    for index in sources:
        if index not in seen:
            seen.append(index)
    return seen


def _check_order(
    streams: list[Any],
    order: list[int],
    selection: TrackSelection,
    listed: tuple[str, ...],
) -> None:
    by_index = {s.index: s for s in streams}
    if not listed:  # keep everything: source order
        assert order == sorted(order)
        return
    main = [i for i in order if extra_role(by_index[i]) is None]
    extras = [i for i in order if extra_role(by_index[i]) is not None]
    assert order == [*main, *extras]  # extra tracks always come last
    if selection.order == "source":
        assert main == sorted(main)
        assert extras == sorted(extras)
        return
    slots = [
        language_slot(effective_language(by_index[i]), listed, selection.undetermined) for i in main
    ]
    listed_part = [s for s in slots if s is not None]
    assert slots[: len(listed_part)] == listed_part  # listed languages first …
    assert listed_part == sorted(listed_part)  # … in list order
    if selection.tracks_per_language == "first":
        assert len(listed_part) == len(set(listed_part))


def _check(draft: TrackDraft, media: MediaSource, template: JobTemplate, langs: Any) -> None:
    # One decision per source track, in source order.
    assert [d.source_stream for d in draft.decisions] == [s.index for s in media.audio]
    assert [d.source_stream for d in draft.subtitle_decisions] == [s.index for s in media.subtitles]
    assert {d.kind for d in draft.decisions} <= {"audio"}
    assert {d.kind for d in draft.subtitle_decisions} <= {"subtitle"}
    for d in [*draft.decisions, *draft.subtitle_decisions]:
        assert d.reason
        if not d.selected:
            assert (d.outputs, d.subtitle_outputs, d.rule) == ([], [], None)
            assert d.reason == d.selection
    # At most one default track per kind.
    assert sum(t.metadata.default for t in draft.audio) <= 1
    assert sum(t.metadata.default for t in draft.subtitles) <= 1
    # Outputs only from selected tracks, and every output is in its track's decision.
    selected_audio = {d.source_stream for d in draft.decisions if d.selected}
    assert {t.source_stream for t in draft.audio} <= selected_audio
    assert sorted(t.model_dump_json() for t in draft.audio) == sorted(
        t.model_dump_json() for d in draft.decisions for t in d.outputs
    )
    selected_subtitles = {d.source_stream for d in draft.subtitle_decisions if d.selected}
    assert {t.source for t in draft.subtitles} == selected_subtitles
    assert draft.subtitles == sorted(
        (t for d in draft.subtitle_decisions for t in d.subtitle_outputs),
        key=draft.subtitles.index,
    )
    # At most one burned-in subtitle; extra outputs are never default.
    assert sum(t.action == "burn" for t in draft.subtitles) <= 1
    for d in draft.decisions:
        assert not any(t.metadata.default for t in d.outputs[1:])
    # The output order.
    audio_selection = template.audio_defaults.selection
    listed = effective_languages(audio_selection.languages, langs.preferred_audio)
    order = _first_positions([t.source_stream for t in draft.audio if t.source_stream])
    _check_order(media.audio, order, audio_selection, listed)
    if not listed:
        assert selected_audio == {s.index for s in media.audio}
    sub_selection = template.subtitle_defaults.selection
    sub_listed = effective_languages(sub_selection.languages, langs.preferred_subtitle)
    sub_order = [t.source for t in draft.subtitles if isinstance(t.source, int)]
    if not sub_listed:
        assert sub_order == [s.index for s in media.subtitles]
        assert {t.action for t in draft.subtitles} <= {"copy"}
    else:
        # The foreign audio search track goes first; the rest follow the setting.
        fas = [
            d.source_stream
            for d in draft.subtitle_decisions
            if d.selection and "Foreign audio search: #" in d.selection
        ]
        rest = [i for i in sub_order if i not in fas]
        assert sub_order[: len(fas)] == fas
        _check_order(media.subtitles, rest, sub_selection, sub_listed)


@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(cases())
def test_defaults_properties(case: tuple[MediaSource, JobTemplate, LanguageSettings]) -> None:
    media, template, langs = case
    draft = draft_tracks(media, template, definitions=DEFS, languages=langs)
    _check(draft, media, template, langs)
