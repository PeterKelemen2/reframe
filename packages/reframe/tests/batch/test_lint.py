"""Lint of the audio defaults; every fix removes its issue and adds no error."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from reframe.batch import draft_tracks, lint_defaults
from reframe.batch.lint import CODES, describe_rule, lint_rules, rule_covers
from reframe.jsonpatch import apply_patch
from reframe.models import (
    AudioCodecRule,
    AudioDefaults,
    AudioRuleExtras,
    AudioStream,
    Container,
    ExtraAudioOutput,
    JobTemplate,
    MediaSource,
    OutputOptions,
    PassthruPolicy,
    RemoveOp,
    Severity,
    SourceChannels,
    TrackSelection,
    ValidationIssue,
)
from reframe.presets import builtin_presets


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
source: Callable[..., MediaSource] = T.source

CATCH_ALL = AudioCodecRule(codec="aac", mixdown="up_to_5.1", max_bitrate=256)


def rule(
    languages: list[str] | None = None, channels: SourceChannels = "any", **fields: Any
) -> AudioCodecRule:
    return AudioCodecRule(languages=languages, source_channels=channels, **fields)


def defaults(*rules: AudioCodecRule, **fields: Any) -> AudioDefaults:
    items = list(rules)
    if not items or not items[-1].is_catch_all:
        items.append(CATCH_ALL)
    return AudioDefaults(codec_rules=items, **fields)


def found(issues: list[ValidationIssue]) -> list[tuple[str, str]]:
    return [(i.code, i.path) for i in issues]


def template_of(audio_defaults: AudioDefaults, container: Container = "mkv") -> JobTemplate:
    return JobTemplate(output=OutputOptions(container=container), audio_defaults=audio_defaults)


def check_fixes(template: JobTemplate) -> list[ValidationIssue]:
    """Apply every fix of every issue: its issue is gone and no error is new. A fix that removes
    a rule renumbers the later rules, so it is checked by code: one issue of that code fewer."""
    issues = lint_defaults(template.audio_defaults, container=template.output.container)
    errors = {(i.code, i.path) for i in issues if i.severity is Severity.ERROR}
    for issue in issues:
        assert issue.code in CODES
        for fix in issue.fixes:
            assert fix.target == "template"
            data = apply_patch(template.model_dump(mode="json"), fix.patch)
            fixed = JobTemplate.model_validate(data)
            after = lint_defaults(fixed.audio_defaults, container=fixed.output.container)
            if any(isinstance(op, RemoveOp) for op in fix.patch):
                before = [i for i in issues if i.code == issue.code]
                assert len([i for i in after if i.code == issue.code]) < len(before), fix.label
                new_codes = {i.code for i in after if i.severity is Severity.ERROR}
                assert new_codes <= {code for code, _ in errors}, (fix.label, after)
                continue
            assert (issue.code, issue.path) not in found(after), (fix.label, after)
            new = {(i.code, i.path) for i in after if i.severity is Severity.ERROR} - errors
            assert not new, (fix.label, new)
    return issues


def test_clean_defaults() -> None:
    assert lint_defaults(AudioDefaults()) == []
    example = defaults(
        rule(["hu"], "5.1_or_more", codec="ac3", mixdown="5.1", max_bitrate=320),
        rule(["en"], "5.1_or_more", codec="ac3", mixdown="5.1", max_bitrate=384),
        rule(None, "stereo_or_less", codec="aac", mixdown="stereo", max_bitrate=160),
        rule(None, codec="libopus", mixdown="up_to_5.1", max_bitrate=256, if_fits="reencode"),
    )
    assert lint_defaults(example) == []


@pytest.mark.parametrize("preset", builtin_presets(), ids=lambda p: p.id)
def test_builtin_presets_are_clean(preset: Any) -> None:
    assert lint_defaults(preset.audio_defaults, container=preset.output.container) == []


@pytest.mark.parametrize(
    ("earlier", "later", "shadowed"),
    [
        (rule(["hu"]), rule(["hu"], "5.1_or_more"), True),
        (rule(None, "5.1_or_more"), rule(["hu"], "7.1_or_more"), True),
        (rule(["pt"]), rule(["pt-BR"]), True),  # pt takes pt-BR tracks
        (rule(["pt-BR"]), rule(["pt"]), False),  # pt-PT tracks reach the later rule
        (rule(["hu", "en"]), rule(["en"]), True),
        (rule(["en"]), rule(["hu", "en"]), False),
        (rule(["ger"]), rule(["de"]), True),  # the same language
        (rule(["hu"], "stereo_or_less"), rule(["hu"], "mono"), True),
        (rule(["hu"], "mono"), rule(["hu"], "stereo_or_less"), False),
        (rule(["hu"], "5.1_or_more"), rule(["hu"], "stereo_or_less"), False),
        (rule(["hu"]), rule(None), False),
        # Limited to the first track of a language: the other tracks reach the later rule.
        (
            rule(["hu"], extras=AudioRuleExtras(first_track_of_language_only=True)),
            rule(["hu"], "5.1_or_more"),
            False,
        ),
        (
            rule(["hu"]),
            rule(["hu"], "5.1_or_more", extras=AudioRuleExtras(first_track_of_language_only=True)),
            True,
        ),
    ],
)
def test_shadowed(earlier: AudioCodecRule, later: AudioCodecRule, shadowed: bool) -> None:
    assert rule_covers(earlier, later) is shadowed
    issues = check_fixes(template_of(defaults(earlier, later)))
    expected = [("defaults.rule_shadowed", "audio_defaults.codec_rules[1]")] if shadowed else []
    assert found(issues) == expected


def test_shadowed_message_and_fixes() -> None:
    issues = lint_defaults(defaults(rule(["hu"]), rule(["hu"], "5.1_or_more", codec="ac3")))
    (issue,) = issues
    assert issue.severity is Severity.WARNING
    assert issue.message == (
        "Rule 2 never applies: rule 1 (Hungarian, any channels) matches every track that rule 2 "
        "(Hungarian, 5.1 or more) would."
    )
    assert [f.label for f in issue.fixes] == ["Move rule 2 above rule 1", "Remove rule 2"]
    # The same conditions twice: moving would only swap them.
    (same,) = lint_defaults(defaults(rule(["hu"]), rule(["hu"], codec="ac3")))
    assert [f.label for f in same.fixes] == ["Remove rule 2"]


def test_an_empty_language_list_matches_nothing() -> None:
    template = template_of(defaults(rule([], "5.1_or_more", codec="ac3")))
    (issue,) = check_fixes(template)
    assert found([issue]) == [("defaults.rule_unreachable", "audio_defaults.codec_rules[0]")]
    assert issue.message == "Rule 1 has an empty language list: it matches no track."
    assert [f.label for f in issue.fixes] == ["Match any language", "Remove rule 1"]
    # "Any language, any channels" would hide every later rule: only "Remove" is offered.
    (anything,) = lint_defaults(defaults(rule([], codec="ac3")))
    assert [f.label for f in anything.fixes] == ["Remove rule 1"]


def test_rules_after_an_any_any_rule_never_apply() -> None:
    template = template_of(defaults(rule(None, codec="libopus"), rule(["hu"], codec="ac3")))
    issues = check_fixes(template)
    assert found(issues) == [
        ("defaults.rule_unreachable", "audio_defaults.codec_rules[1]"),
        ("defaults.rule_unreachable", "audio_defaults.codec_rules[2]"),
    ]
    assert issues[0].message == (
        "Rule 2 never applies: rule 1 (any language, any channels) takes every track before it."
    )
    assert [f.label for f in issues[0].fixes] == ["Move rule 2 above rule 1", "Remove rule 2"]
    # The last rule (the catch-all) cannot be moved or removed alone.
    assert [f.label for f in issues[1].fixes] == ["Remove rule 3 and make rule 1 the last rule"]
    fixed = apply_patch(template.model_dump(mode="json"), issues[1].fixes[0].patch)
    rules = JobTemplate.model_validate(fixed).audio_defaults.codec_rules
    assert [(r.languages, r.codec) for r in rules] == [(["hu"], "ac3"), (None, "libopus")]


def test_a_rule_for_a_language_the_selection_never_takes() -> None:
    selection = TrackSelection(languages=["hu", "en"], other_languages="drop", no_match="none")
    template = template_of(
        defaults(rule(["fr"], codec="ac3"), rule(["en-GB"], codec="eac3"), selection=selection)
    )
    issues = check_fixes(template)
    assert found(issues) == [("defaults.rule_unreachable", "audio_defaults.codec_rules[0]")]
    assert issues[0].message == (
        "Rule 1 never applies: it is for French, and the selection takes only Hungarian and "
        "English tracks (other languages: drop; no listed language: take none)."
    )
    assert [f.label for f in issues[0].fixes] == ["Also select French tracks", "Remove rule 1"]
    # Any of these lets a French track through, so the rule is reachable.
    for change in (
        {"other_languages": "keep_first"},
        {"no_match": "default_flagged"},
        {"languages": None},
    ):
        loose = defaults(rule(["fr"]), selection=selection.model_copy(update=change))
        assert lint_defaults(loose) == []


@pytest.mark.parametrize(
    ("bad", "path", "message", "fix"),
    [
        (
            rule(None, "5.1_or_more", codec="ac3", mixdown="5.1", max_bitrate=700),
            "audio_defaults.codec_rules[0].max_bitrate",
            "AC-3 5.1 goes up to 640 kb/s: 700 → 640 kb/s.",
            "Use 640 kb/s",
        ),
        (
            rule(None, "5.1_or_more", codec="ac3", mixdown="5.1", max_bitrate=150),
            "audio_defaults.codec_rules[0].max_bitrate",
            "AC-3 5.1 needs at least 224 kb/s: 150 → 224 kb/s.",
            "Use 224 kb/s",
        ),
        (
            rule(None, "stereo_or_less", codec="ac3", mixdown="stereo", max_bitrate=150),
            "audio_defaults.codec_rules[0].max_bitrate",
            "150 kb/s is not an allowed AC-3 Stereo bit rate: 150 → 128 kb/s.",
            "Use 128 kb/s",
        ),
        (
            # A stereo rule is checked for the sources it downmixes: a mono source keeps its
            # layout (no upmix) and gets AAC Mono's maximum, which its own decision notes.
            rule(None, "stereo_or_less", codec="aac", mixdown="stereo", max_bitrate=600),
            "audio_defaults.codec_rules[0].max_bitrate",
            "AAC Stereo goes up to 512 kb/s: 600 → 512 kb/s.",
            "Use 512 kb/s",
        ),
        (
            # Keep the layout: every layout the condition allows; different values, no fix.
            rule(None, codec="aac", mixdown="keep", max_bitrate=128),
            "audio_defaults.codec_rules[0].max_bitrate",
            "AAC 5.1 needs at least 192 kb/s: 128 → 192 kb/s; AAC 7.1 needs at least 256 kb/s: "
            "128 → 256 kb/s.",
            None,
        ),
        (
            # A passthru rule's max is the fallback encoder's (AC-3 here), for every layout.
            rule(None, codec="passthru", max_bitrate=700),
            "audio_defaults.codec_rules[0].max_bitrate",
            "AC-3 Mono goes up to 640 kb/s: 700 → 640 kb/s; AC-3 Stereo goes up to 640 kb/s: "
            "700 → 640 kb/s; AC-3 5.1 goes up to 640 kb/s: 700 → 640 kb/s.",
            "Use 640 kb/s",
        ),
        (
            rule(
                None,
                codec="ac3",
                mixdown="5.1",
                max_bitrate=448,
                extras=AudioRuleExtras(
                    extra_outputs=[ExtraAudioOutput(codec="aac", mixdown="stereo", bitrate=1000)]
                ),
            ),
            "audio_defaults.codec_rules[0].extras.extra_outputs[0].bitrate",
            "AAC Stereo goes up to 512 kb/s: 1000 → 512 kb/s.",
            "Use 512 kb/s",
        ),
    ],
)
def test_bitrate_snapped(bad: AudioCodecRule, path: str, message: str, fix: str | None) -> None:
    template = template_of(defaults(bad, passthru=PassthruPolicy(fallback_encoder="ac3")))
    issues = check_fixes(template)
    (issue,) = [i for i in issues if i.path == path]
    assert issue.code == "defaults.bitrate_snapped"
    assert issue.severity is Severity.INFO
    assert issue.message == message
    assert [f.label for f in issue.fixes] == ([fix] if fix else [])


def test_no_bitrate_check() -> None:
    for quiet in (
        rule(None, codec="flac", max_bitrate=5000),  # lossless encoder
        rule(None, codec="aac_at", max_bitrate=5000),  # unknown encoder
        rule(None, codec="ac3", max_bitrate=None),  # the encoder's default
        rule(None, codec="aac", mixdown="stereo", max_bitrate=320),  # Creator 1080p60
    ):
        assert lint_defaults(defaults(quiet)) == [], quiet


def test_codec_not_in_container() -> None:
    bad = defaults(
        rule(
            ["hu"],
            codec="ac3",
            extras=AudioRuleExtras(extra_outputs=[ExtraAudioOutput(codec="aac", bitrate=160)]),
        ),
        rule(None, codec="libopus", max_bitrate=256),
        passthru=PassthruPolicy(fallback_encoder="aac"),
    )
    template = template_of(bad, "webm")
    issues = check_fixes(template)
    assert found(issues) == [
        ("defaults.codec_not_in_container", "audio_defaults.codec_rules[0].codec"),
        (
            "defaults.codec_not_in_container",
            "audio_defaults.codec_rules[0].extras.extra_outputs[0].codec",
        ),
        ("defaults.codec_not_in_container", "audio_defaults.passthru.fallback_encoder"),
    ]
    first = issues[0]
    assert first.severity is Severity.ERROR
    assert first.message == "WebM cannot hold AC-3 audio (ac3)."
    assert [f.label for f in first.fixes] == [
        "Use Opus",
        "Switch to Matroska (MKV)",
        "Switch to MP4",
    ]
    assert lint_defaults(bad, container="mkv") == []
    assert lint_defaults(bad, container="webm", container_codecs=False) == []


EXAMPLE = defaults(
    rule(["hu"], "5.1_or_more", codec="ac3", mixdown="5.1", max_bitrate=320),
    rule(["en"], "5.1_or_more", codec="ac3", mixdown="5.1", max_bitrate=384),
    rule(None, "stereo_or_less", codec="aac", mixdown="stereo", max_bitrate=160),
    rule(None, codec="libopus", mixdown="up_to_5.1", max_bitrate=256, if_fits="reencode"),
    selection=TrackSelection(languages=["hu", "en"], tracks_per_language="all"),
)


def test_rules_this_source_does_not_use() -> None:
    media = source([audio(1, "hun", "ac3", 6, 224), audio(2, "eng", "ac3", 2, 192)])
    issues = lint_defaults(EXAMPLE, source=media)
    assert found(issues) == [("defaults.rule_unused", "audio_defaults.codec_rules[1]")]
    assert issues[0].severity is Severity.INFO
    assert issues[0].message == (
        "Rule 2 (English, 5.1 or more) is not used by any track of this source."
    )
    # The draft has the same lint.
    template = JobTemplate(audio_defaults=EXAMPLE)
    assert draft_tracks(media, template).issues == issues
    # The catch-all is never reported (here no track uses it either).
    english = lint_defaults(EXAMPLE, source=source([audio(1, "eng", "ac3", 6, 448)]))
    assert found(english) == [
        ("defaults.rule_unused", "audio_defaults.codec_rules[0]"),
        ("defaults.rule_unused", "audio_defaults.codec_rules[2]"),
    ]
    # No audio at all: nothing is "unused".
    assert lint_defaults(EXAMPLE, source=source()) == []


def test_unused_uses_the_selection_and_settings() -> None:
    """A rule that only a dropped track would use is unused; the Settings languages decide
    what is dropped."""
    plain = defaults(rule(["hu"], codec="ac3", mixdown="5.1", max_bitrate=448))
    media = source([audio(1, "hun"), audio(2, "eng")])
    assert lint_defaults(plain, source=media) == []  # keep everything: both tracks
    issues = lint_defaults(plain, source=media, preferred_languages=["en"])
    assert found(issues) == [("defaults.rule_unused", "audio_defaults.codec_rules[0]")]
    # Every track dropped: no "unused" noise next to the selection's own issue.
    nothing = defaults(
        rule(["de"], codec="ac3"), selection=TrackSelection(languages=["de"], no_match="none")
    )
    assert lint_defaults(nothing) == []
    assert lint_defaults(nothing, source=media) == []
    # A rule that can never apply is reported once, as unreachable.
    dead = defaults(rule(["hu"]), rule(["hu"], "5.1_or_more"))
    assert found(lint_defaults(dead, source=source([audio(1, "eng")]))) == [
        ("defaults.rule_shadowed", "audio_defaults.codec_rules[1]"),
        ("defaults.rule_unused", "audio_defaults.codec_rules[0]"),
    ]


def test_describe_rule() -> None:
    assert describe_rule(rule(None)) == "any language, any channels"
    assert describe_rule(rule(["hu", "en"], "stereo_or_less")) == (
        "Hungarian or English, stereo or less"
    )
    assert describe_rule(rule([])) == "no language, any channels"
    limited = rule(["hu"], extras=AudioRuleExtras(first_track_of_language_only=True))
    assert describe_rule(limited) == "Hungarian, any channels, the first track of a language"
    assert lint_rules(AudioDefaults(), used=set()) == []
