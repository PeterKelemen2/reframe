"""C-12 M7: the one rule engine for presets and batch mode (04 §Track rules; 03 §Audio
defaults → "How the defaults are applied")."""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from reframe.batch import (
    compile_defaults,
    draft_tracks,
    resolve_tracks,
    rule_label,
)
from reframe.batch.explain import audio_stage, subtitle_stage
from reframe.batch.lint import lint_rules
from reframe.batch.rules import literal_title, title_text
from reframe.definitions import load_definitions
from reframe.models import (
    AudioCodecRule,
    AudioCodecRules,
    AudioDefaults,
    AudioOutputSettings,
    AudioStream,
    JobTemplate,
    LanguageSettings,
    MediaSource,
    OutputTrackRule,
    SourceFingerprint,
    SubtitleDefaults,
    SubtitleOutputSettings,
    SubtitleStream,
    TrackMetadataTemplate,
    TrackRole,
    TrackSelection,
    TrackSelector,
)
from reframe.presets import builtin_presets
from reframe.probe import parse_ffprobe

DEFS = load_definitions()
PROBES = Path(__file__).resolve().parents[4] / "testdata" / "probes"


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


A = _load("anime")
T = _load("defaults_tracks")


def selector(kind: str = "audio", **kw: Any) -> TrackSelector:
    return TrackSelector.model_validate({"kind": kind, **kw})


def audio_rule(settings: Any = None, metadata: Any = None, **kw: Any) -> OutputTrackRule:
    return OutputTrackRule(
        selector=selector("audio", **kw),
        settings=settings if settings is not None else AudioOutputSettings(),
        metadata=metadata if metadata is not None else TrackMetadataTemplate(),
    )


def sub_rule(settings: Any = None, metadata: Any = None, **kw: Any) -> OutputTrackRule:
    return OutputTrackRule(
        selector=selector("subtitle", **kw),
        settings=settings if settings is not None else SubtitleOutputSettings(),
        metadata=metadata if metadata is not None else TrackMetadataTemplate(),
    )


# --------------------------------------------------------------------------- labels


def test_labels() -> None:
    """04 §Resolution matrix: ``A1 jpn TrueHD→Opus 5.1``, ``S1 eng Signs``."""
    opus = AudioOutputSettings(encoder="libopus", mixdown="5.1", bitrate=448)
    a1 = audio_rule(opus, languages=["ja"], codecs=["truehd"], profiles=["TrueHD"])
    assert rule_label("audio", 0, a1, DEFS) == "A1 jpn TrueHD→Opus 5.1"
    ac3 = AudioOutputSettings(encoder="ac3", mixdown="stereo")
    assert rule_label("audio", 1, audio_rule(ac3, codecs=["dts"]), DEFS) == "A2 any DTS→AC-3 2.0"
    passthru = audio_rule(AudioOutputSettings(action="passthru"), languages=["en", "hu"])
    assert rule_label("audio", 2, passthru, DEFS) == "A3 eng/hun→passthru"
    rules = audio_rule(AudioCodecRules(), languages=["hu"])
    assert rule_label("audio", 0, rules, DEFS) == "A1 hun→codec rules"
    unknown = audio_rule(AudioOutputSettings(encoder="nope"))
    assert rule_label("audio", 0, unknown, DEFS) == "A1 any→nope"
    signs = sub_rule(languages=["en"], title_pattern=literal_title("Signs & Songs"))
    assert rule_label("subtitle", 0, signs, DEFS) == "S1 eng Signs & Songs"
    burn = sub_rule(SubtitleOutputSettings(action="burn"), roles=[TrackRole.FORCED])
    assert rule_label("subtitle", 1, burn, DEFS) == "S2 any forced (burn in)"
    srt = sub_rule(SubtitleOutputSettings(action="convert", convert_to="srt"), codecs=["ass"])
    assert rule_label("subtitle", 2, srt, DEFS) == "S3 any ASS (SRT)"
    tx3g = sub_rule(SubtitleOutputSettings(action="convert", convert_to="mov_text"))
    assert rule_label("subtitle", 3, tx3g, DEFS) == "S4 any (mov_text)"


def test_literal_titles() -> None:
    assert literal_title("Signs & Songs") == "^Signs & Songs$"
    assert literal_title("A (2.0) [x]") == r"^A \(2\.0\) \[x\]$"
    assert title_text(literal_title("A (2.0) [x]")) == "A (2.0) [x]"
    assert title_text("Signs|Songs") == "Signs|Songs"
    assert title_text("^a.b$") == "^a.b$"  # not a literal: the dot is a wildcard


# --------------------------------------------------------------------------- explicit rules


def example() -> MediaSource:
    """E05: jpn TrueHD, eng DTS-HD MA, eng AC-3 commentary, two subtitles."""
    source: MediaSource = A.recorded(1, 5)
    return source


def template(
    *, audio: Sequence[OutputTrackRule] = (), subtitles: Sequence[OutputTrackRule] = ()
) -> JobTemplate:
    return JobTemplate(audio_rules=list(audio), subtitle_rules=list(subtitles))


def test_fixed_settings_and_metadata() -> None:
    opus = AudioOutputSettings(encoder="libopus", mixdown="5.1", bitrate=448)
    meta = TrackMetadataTemplate(
        name_template="{lang_name} {channels} {codec} {bitrate}", default=True
    )
    rules = [
        audio_rule(opus, meta, languages=["ja"]),
        audio_rule(
            AudioOutputSettings(action="passthru", encoder="ac3"),
            TrackMetadataTemplate(language="hu", name_template="{lang_native} {codec} {channels}"),
            languages=["en"],
            roles=[TrackRole.COMMENTARY],
        ),
    ]
    result = resolve_tracks(template(audio=rules), example(), definitions=DEFS)
    first, second = result.draft.audio
    assert (first.action, first.encoder, first.mixdown, first.bitrate) == (
        "encode",
        "libopus",
        "5.1",
        448,
    )
    assert first.source_stream == 1
    assert first.metadata.name == "Japanese 5.1 Opus 448"
    assert first.metadata.default
    assert (second.action, second.source_stream) == ("passthru", 3)
    assert second.metadata.language == "hu"
    assert second.metadata.name == "Magyar AC-3 2.0"
    assert second.metadata.commentary  # from the source
    assert not second.metadata.default
    decisions = result.draft.decisions
    assert [(d.source_stream, d.selected) for d in decisions] == [(1, True), (2, False), (3, True)]
    assert decisions[0].reason == "Fixed settings of rule A1 jpn→Opus 5.1: Opus 5.1 · 448 kb/s"
    assert decisions[0].selection == "Rule A1 jpn→Opus 5.1: exact match"
    assert decisions[0].notes == ["The default audio track"]
    assert decisions[1].reason == decisions[1].selection == "No track rule takes this track"
    assert decisions[2].reason == "Fixed settings of rule A2 eng→passthru: Passthru"
    assert [m.status for m in result.matches[:2]] == ["exact", "exact"]
    assert [c.label for c in result.columns[:2]] == ["A1 jpn→Opus 5.1", "A2 eng→passthru"]
    assert result.draft.issues == []


def test_codec_rules_are_evaluated_for_each_matched_track() -> None:
    """A rule with ``AudioCodecRules`` (the defaults' kind of settings) runs 03's codec rules
    on the track it takes: here the 03 example's rule 1 on a DTS-HD MA track."""
    english = AudioCodecRule(
        languages=["en"], source_channels="5.1_or_more", codec="ac3", mixdown="5.1", max_bitrate=320
    )
    extras = {"extra_outputs": [{"codec": "aac", "mixdown": "stereo", "bitrate": 128}]}
    catch_all = AudioCodecRule.model_validate(
        {"codec": "aac", "mixdown": "stereo", "max_bitrate": 160, "extras": extras}
    )
    rules = AudioCodecRules(rules=[english, catch_all])
    result = resolve_tracks(
        template(audio=[audio_rule(rules, languages=["en"], codecs=["dts"])]),
        example(),
        definitions=DEFS,
    )
    assert [(t.encoder, t.mixdown, t.bitrate) for t in result.draft.audio] == [("ac3", "5.1", 320)]
    decision = result.draft.decisions[1]
    assert decision.rule == 1
    assert decision.reason == "Lossless source → encode at the max"
    assert decision.measure
    # The commentary (2.0) gets rule 2 and its extra output, which is never the default.
    both = audio_rule(rules, languages=["en"], roles=[TrackRole.COMMENTARY])
    result = resolve_tracks(template(audio=[both]), example(), definitions=DEFS)
    main, extra = result.draft.audio
    # AC-3 96 kb/s fits rule 2 (passthru); the extra AAC output is never bigger than its
    # source: 128 → 96 kb/s.
    assert (main.action, extra.encoder, extra.bitrate) == ("passthru", "aac", 96)
    assert not extra.metadata.default


def test_default_flags() -> None:
    """A rule's explicit default wins; without one, the first output whose source track is
    default keeps it (at most one)."""
    keep = audio_rule(languages=["ja"])
    dub = audio_rule(languages=["en"], codecs=["dts"])
    source = example()
    jpn_default = resolve_tracks(template(audio=[dub, keep]), source, definitions=DEFS)
    assert [t.metadata.default for t in jpn_default.draft.audio] == [False, True]
    explicit = OutputTrackRule(
        selector=dub.selector,
        settings=AudioOutputSettings(),
        metadata=TrackMetadataTemplate(default=True),
    )
    result = resolve_tracks(template(audio=[keep, explicit]), source, definitions=DEFS)
    assert [t.metadata.default for t in result.draft.audio] == [False, True]
    twice = resolve_tracks(template(audio=[keep, keep]), source, definitions=DEFS)
    assert [t.metadata.default for t in twice.draft.audio] == [True, False]
    off = OutputTrackRule(
        selector=keep.selector,
        settings=AudioOutputSettings(),
        metadata=TrackMetadataTemplate(default=False),
    )
    assert (
        not resolve_tracks(template(audio=[off]), source, definitions=DEFS)
        .draft.audio[0]
        .metadata.default
    )


def test_subtitle_rules() -> None:
    signs = sub_rule(
        SubtitleOutputSettings(action="burn", forced_only=True),
        TrackMetadataTemplate(default=True, name_template="{lang_name} {title} ({codec})"),
        roles=[TrackRole.FORCED],
    )
    full = sub_rule(
        SubtitleOutputSettings(action="convert", convert_to="srt"), title_pattern="^Full$"
    )
    result = resolve_tracks(template(subtitles=[signs, full]), example(), definitions=DEFS)
    burned, converted = result.draft.subtitles
    assert (burned.source, burned.action, burned.forced_only) == (4, "burn", True)
    assert burned.metadata.name == "English Signs & Songs (ASS)"
    assert not burned.metadata.default  # a burned track is not a track: never the default
    assert (converted.source, converted.action, converted.convert_to) == (5, "convert", "srt")
    assert converted.metadata.default  # from the source
    reasons = [d.reason for d in result.draft.subtitle_decisions]
    assert reasons == [
        "Burn in, forced events only (rule S1 any forced (burn in))",
        "Convert to srt (rule S2 any Full (SRT))",
    ]
    # Copy into MP4: the container note.
    mp4 = template(subtitles=[sub_rule(title_pattern="^Full$")]).model_copy(
        update={"output": JobTemplate().output.model_copy(update={"container": "mp4"})}
    )
    copied = resolve_tracks(mp4, example(), definitions=DEFS).draft.subtitle_decisions[1]
    assert copied.reason == "Copy (rule S1 any Full)"
    assert copied.notes == ["MP4: converted to mov_text"]
    assert (
        resolve_tracks(mp4, example(), definitions=DEFS).draft.subtitle_decisions[0].selected
        is False
    )


def test_settings_of_the_other_kind_are_an_error() -> None:
    wrong_audio = OutputTrackRule(
        selector=selector("audio", languages=["ja"]), settings=SubtitleOutputSettings()
    )
    wrong_sub = OutputTrackRule(
        selector=selector("subtitle", title_pattern="^Full$"), settings=AudioOutputSettings()
    )
    result = resolve_tracks(
        template(audio=[wrong_audio], subtitles=[wrong_sub]), example(), definitions=DEFS
    )
    assert result.draft.audio == []
    assert result.draft.subtitles == []
    assert [(i.code, i.path) for i in result.draft.issues] == [
        ("batch.rule_settings", "audio_rules[0].settings"),
        ("batch.rule_settings", "subtitle_rules[0].settings"),
    ]


def test_explicit_audio_with_subtitle_defaults_hears_the_explicit_audio() -> None:
    """The subtitle defaults' foreign audio search hears the explicit rules' audio: English
    audio + English subtitles → the forced English track is found."""
    preset = JobTemplate(
        audio_rules=[
            audio_rule(
                metadata=TrackMetadataTemplate(default=True), languages=["en"], codecs=["dts"]
            )
        ],
        subtitle_defaults=SubtitleDefaults(
            selection=TrackSelection(languages=["en"], no_match="none", default_track="none"),
            foreign_audio_search=True,
        ),
    )
    result = resolve_tracks(preset, example(), definitions=DEFS)
    assert result.draft.subtitles[0].source == 4
    assert result.draft.subtitles[0].metadata.forced
    fas = [m for m in result.matches if m.kind == "subtitle"]
    assert [m.status for m in fas] == ["exact", "exact"]
    assert fas[1].streams == [4]
    assert "Foreign audio search" in fas[1].message


# --------------------------------------------------------------------------- compiled defaults


def test_compiled_defaults_without_languages() -> None:
    (rule,) = compile_defaults(JobTemplate(), "audio")
    assert rule.group == "all"
    assert rule.rule.multiple
    assert not rule.rule.required
    assert isinstance(rule.rule.settings, AudioCodecRules)
    assert rule.label(0) == "A1 every track (defaults)"


def test_compiled_defaults_with_every_part() -> None:
    selection = TrackSelection(
        languages=["hu", "en"],
        tracks_per_language="all",
        undetermined="first_language",
        other_languages="keep_first",
        no_match="first_track",
        commentary="keep_after_main",
        tie_break="best_quality",
    )
    preset = JobTemplate(
        audio_defaults=AudioDefaults(selection=selection),
        subtitle_defaults=SubtitleDefaults(selection=selection, foreign_audio_search=True),
    )
    audio = compile_defaults(preset, "audio")
    assert [r.label(n) for n, r in enumerate(audio)] == [
        "A1 hun (defaults)",
        "A2 eng (defaults)",
        "A3 no listed language (defaults)",
        "A4 other languages (defaults)",
        "A5 commentary (defaults)",
    ]
    hun = audio[0].rule
    assert hun.selector.languages == ["hu", "und"]
    assert hun.selector.sort == "highest_bitrate"
    assert hun.multiple
    assert set(hun.selector.exclude_roles or []) == {
        TrackRole.COMMENTARY,
        TrackRole.DESCRIPTION,
        TrackRole.MUSIC,
    }
    assert audio[1].rule.selector.languages == ["en"]
    assert audio[4].rule.selector.roles is not None
    subs = compile_defaults(preset, "subtitle")
    assert subs[-1].label(len(subs) - 1) == "S6 foreign audio search (defaults)"
    none = TrackSelection(languages=["hu"], tracks_per_language="none", no_match="none")
    assert (
        compile_defaults(JobTemplate(audio_defaults=AudioDefaults(selection=none)), "audio") == []
    )
    # Settings → preferred languages fill an empty selection.
    (pref,) = compile_defaults(JobTemplate(), "subtitle", preferred=["de"])
    assert pref.words == "ger"


def test_every_selected_track_is_in_its_compiled_column() -> None:
    selection = TrackSelection(
        languages=["hu", "en"], commentary="keep_after_main", other_languages="keep_all"
    )
    preset = JobTemplate(audio_defaults=AudioDefaults(selection=selection))
    source = T.source(
        [
            T.audio(1, "hun", "dts", 6, lossless=True),
            T.audio(2, "hun", "ac3", 6, 640),
            T.audio(3, "eng", "ac3", 2, 192, comment=True),
            T.audio(4, "ger", "ac3", 6, 448),
        ]
    )
    result = resolve_tracks(preset, source, definitions=DEFS)
    cells = [(m.status, m.streams, m.candidates) for m in result.matches if m.kind == "audio"]
    assert cells == [
        ("exact", [1], [1, 2]),  # Hungarian: the best of two
        ("skipped", [], []),  # English: only a commentary, which is an extra track
        ("skipped", [], []),  # no listed language: Hungarian was found
        ("exact", [4], [4]),  # other languages: keep all
        ("exact", [3], [3]),  # commentary: kept after the main tracks
    ]
    english = result.matches[1]
    assert english.severity is not None
    assert english.message == "no English track"
    assert english.defaults
    assert result.matches[2].message == "a main track of a listed language was found"
    assert [c.label for c in result.columns if c.kind == "audio"] == [
        "A1 hun (defaults)",
        "A2 eng (defaults)",
        "A3 no listed language (defaults)",
        "A4 other languages (defaults)",
        "A5 commentary (defaults)",
    ]


def test_no_match_column() -> None:
    selection = TrackSelection(languages=["fr"], no_match="default_flagged")
    preset = JobTemplate(audio_defaults=AudioDefaults(selection=selection))
    result = resolve_tracks(preset, example(), definitions=DEFS)
    language, no_match = (m for m in result.matches if m.kind == "audio")
    assert (language.status, no_match.status, no_match.streams) == ("skipped", "exact", [1])
    found = resolve_tracks(preset, T.source([T.audio(1, "fre")]), definitions=DEFS)
    assert [m.message for m in found.matches if m.kind == "audio"][
        1
    ] == "a main track of a listed language was found"


# --------------------------------------------------------------------------- one engine


def _recorded(path: Path) -> MediaSource:
    data = json.loads(path.read_text(encoding="utf-8"))
    frames = path.with_name(path.name.removesuffix(".json") + ".frames.json")
    return parse_ffprobe(
        data,
        Path("/media", path.name),
        frames=json.loads(frames.read_text(encoding="utf-8")) if frames.exists() else None,
        fingerprint=SourceFingerprint(size=0, mtime=0.0),
    )


_NOT_PROBES = ("index.json", "confirmed_strings.json")
SOURCES = sorted(
    p
    for p in PROBES.rglob("*.json")
    if not p.name.endswith(".frames.json") and p.name not in _NOT_PROBES
)


@pytest.mark.parametrize(
    "languages", [None, LanguageSettings(preferred_audio=["ja", "en"], preferred_subtitle=["en"])]
)
def test_presets_resolve_as_the_selection_stage(languages: LanguageSettings | None) -> None:
    """One rule engine: a preset without explicit rules gives exactly the tracks, decisions
    and issues of 1a's selection stage (decisions 0018, 0031) for every recorded probe."""
    for path in SOURCES:
        source = _recorded(path)
        for preset in builtin_presets():
            container = preset.output.container
            audio = audio_stage(
                preset.audio_defaults,
                source,
                container=container,
                preferred_languages=languages.preferred_audio if languages else (),
                definitions=DEFS,
            )
            subtitles = subtitle_stage(
                preset.subtitle_defaults,
                source,
                container=container,
                preferred_languages=languages.preferred_subtitle if languages else (),
                audio=audio.outputs,
                definitions=DEFS,
            )
            selected = [d for d in audio.decisions if d.selected]
            used = {d.rule for d in selected if d.rule is not None} if selected else None
            issues = [
                *audio.issues,
                *subtitles.issues,
                *lint_rules(
                    preset.audio_defaults, container=container, definitions=DEFS, used=used
                ),
            ]
            draft = draft_tracks(source, preset, definitions=DEFS, languages=languages)
            assert draft.audio == audio.outputs, (path.name, preset.id)
            assert draft.subtitles == subtitles.outputs, (path.name, preset.id)
            assert draft.decisions == audio.decisions
            assert draft.subtitle_decisions == subtitles.decisions
            assert draft.issues == issues


def test_a_streams_of_the_wrong_kind_list_is_fine() -> None:
    """``AudioStream`` / ``SubtitleStream`` type check of the helpers."""
    assert isinstance(example().audio[0], AudioStream)
    assert isinstance(example().subtitles[0], SubtitleStream)
