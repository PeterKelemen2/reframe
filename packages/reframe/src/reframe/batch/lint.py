"""The audio defaults lint (05 §C-12; 03 §Audio defaults → How the defaults are applied;
decision 0031).

``validate_template`` (C-8) adds :func:`lint_defaults`' issues to a preset's issues; the draft
(``draft_tracks``, the live preview) adds them with the source-dependent ones. Paths are
template paths (``audio_defaults.codec_rules[1].max_bitrate``); fixes are JSON patches on the
template (``Fix.target = "template"``).

=================================  ========  ==================================================
Code                               Severity  When
=================================  ========  ==================================================
``defaults.rule_unreachable``      warning   A rule can match no track at all: an empty
                                             language list; languages the selection never
                                             takes (explicit languages, other languages
                                             dropped, no listed language: take none); or an
                                             earlier rule takes every track (any language, any
                                             channels, not limited to the first track)
``defaults.rule_shadowed``         warning   An earlier rule matches every track this rule
                                             would (its languages and channels contain this
                                             rule's)
``defaults.bitrate_snapped``       info      The max is outside the encoder's range (or not
                                             an allowed step) for a layout the rule writes;
                                             the note names the written value (C-6's snap,
                                             decision 0025)
``defaults.codec_not_in_container`` error    A rule, extra output or fallback encoder the
                                             container cannot hold; fixes: another encoder,
                                             another container
``defaults.rule_unused``           info      (with a source) no selected track of the source
                                             is encoded by the rule (the catch-all is not
                                             reported)
=================================  ========  ==================================================

Pure: no I/O.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence

from reframe.batch.audio_rules import (
    CHANNEL_CONDITIONS,
    PASSTHRU,
    bitrate_table,
    snap_note,
)
from reframe.batch.explain import audio_stage
from reframe.batch.selection import language_label
from reframe.definitions import AudioEncoderDef, Definitions, load_definitions
from reframe.languages import matches
from reframe.models.defaults import (
    AudioCodecRule,
    AudioDefaults,
    RuleMixdown,
    SourceChannels,
)
from reframe.models.issues import (
    AddOp,
    Fix,
    JsonPatchOp,
    MoveOp,
    RemoveOp,
    ReplaceOp,
    Severity,
    ValidationIssue,
)
from reframe.models.job import Container, Mixdown
from reframe.models.media import AudioStream, MediaSource

__all__ = ["CODES", "describe_rule", "lint_defaults", "lint_rules", "rule_covers"]

#: Every code the lint gives.
CODES = (
    "defaults.rule_unreachable",
    "defaults.rule_shadowed",
    "defaults.bitrate_snapped",
    "defaults.codec_not_in_container",
    "defaults.rule_unused",
)

#: Encoders a "use another encoder" fix tries, in order (HandBrake's defaults first).
_ENCODER_PREFERENCE = ("aac", "libopus", "ac3", "eac3", "flac", "libmp3lame")

#: The source channel counts a channel condition stands for (the layouts a rule can see).
_CHANNELS: dict[SourceChannels, tuple[int, ...]] = {
    "any": (1, 2, 6, 8),
    "mono": (1,),
    "stereo_or_less": (1, 2),
    "5.1_or_more": (6, 8),
    "7.1_or_more": (8,),
}
_LAYOUTS = {1: "mono", 2: "stereo", 6: "5.1", 8: "7.1"}


def _rules_path(index: int) -> str:
    return f"audio_defaults.codec_rules[{index}]"


def _pointer(path: str) -> str:
    """``audio_defaults.codec_rules[1].max_bitrate`` →
    ``/audio_defaults/codec_rules/1/max_bitrate``."""
    return "/" + path.replace("[", ".").replace("]", "").replace(".", "/")


def _issue(severity: Severity, code: str, path: str, message: str, *fixes: Fix) -> ValidationIssue:
    return ValidationIssue(
        severity=severity, code=code, path=path, message=message, fixes=list(fixes)
    )


def _fix(label: str, *ops: JsonPatchOp) -> Fix:
    return Fix(label=label, patch=list(ops), target="template")


# --------------------------------------------------------------------------- rule conditions


def describe_rule(rule: AudioCodecRule) -> str:
    """``Hungarian, 5.1 or more``, ``any language, any channels``,
    ``Hungarian or English, stereo or less, the first track of a language``."""
    if rule.languages is None:
        langs = "any language"
    elif not rule.languages:
        langs = "no language"
    else:
        langs = " or ".join(language_label(tag) for tag in rule.languages)
    text = f"{langs}, {CHANNEL_CONDITIONS[rule.source_channels]}"
    if rule.extras.first_track_of_language_only:
        text += ", the first track of a language"
    return text


def _channels_cover(outer: SourceChannels, inner: SourceChannels) -> bool:
    if outer == "any" or outer == inner:
        return True
    return (outer, inner) in (("stereo_or_less", "mono"), ("5.1_or_more", "7.1_or_more"))


def rule_covers(earlier: AudioCodecRule, later: AudioCodecRule) -> bool:
    """Whether ``earlier`` matches every track that ``later`` would match, so that ``later``
    never applies after it: its languages contain the later rule's
    (:func:`reframe.languages.matches`: ``pt`` contains ``pt-BR``), its channel condition
    contains the later one's, and it is not limited to the first track of a language unless
    the later rule is too."""
    if earlier.extras.first_track_of_language_only and not (
        later.extras.first_track_of_language_only
    ):
        return False
    if not _channels_cover(earlier.source_channels, later.source_channels):
        return False
    if earlier.languages is None:
        return True
    if later.languages is None:
        return False
    return all(any(matches(a, b) for a in earlier.languages) for b in later.languages)


def _takes_everything(rule: AudioCodecRule) -> bool:
    return rule.is_catch_all and not rule.extras.first_track_of_language_only


def _overlaps(a: str, b: str) -> bool:
    """Some track language matches both tags."""
    return matches(a, b) or matches(b, a)


# --------------------------------------------------------------------------- reachability


def _move_fixes(index: int, above: int, rules: Sequence[AudioCodecRule]) -> list[Fix]:
    """Move rule ``index`` above rule ``above``, or remove it (never the catch-all)."""
    base = "/audio_defaults/codec_rules"
    number = index + 1
    fixes: list[Fix] = []
    if index == len(rules) - 1:
        if _takes_everything(rules[above]):
            fixes.append(
                _fix(
                    f"Remove rule {number} and make rule {above + 1} the last rule",
                    RemoveOp(path=f"{base}/{index}"),
                    MoveOp.model_validate(
                        {"from": f"{base}/{above}", "path": f"{base}/{len(rules) - 2}"}
                    ),
                )
            )
        return fixes
    if not rule_covers(rules[index], rules[above]):
        fixes.append(
            _fix(
                f"Move rule {number} above rule {above + 1}",
                MoveOp.model_validate({"from": f"{base}/{index}", "path": f"{base}/{above}"}),
            )
        )
    fixes.append(_fix(f"Remove rule {number}", RemoveOp(path=f"{base}/{index}")))
    return fixes


def _outside_selection(defaults: AudioDefaults, rule: AudioCodecRule) -> list[str] | None:
    """The rule's languages when the selection never takes a track in any of them (explicit
    selection languages, other languages dropped, no listed language: take none)."""
    selection = defaults.selection
    listed = selection.languages
    if (
        not listed
        or rule.languages is None
        or not rule.languages
        or selection.other_languages != "drop"
        or selection.no_match != "none"
    ):
        return None
    if any(_overlaps(tag, other) for tag in rule.languages for other in listed):
        return None
    return list(rule.languages)


def _reachability(defaults: AudioDefaults, index: int) -> ValidationIssue | None:
    rules = defaults.codec_rules
    rule = rules[index]
    number = index + 1
    path = _rules_path(index)
    base = "/audio_defaults/codec_rules"
    if rule.languages is not None and not rule.languages:
        # Never the last rule (the model wants the catch-all there). "Any language" is not
        # offered when it would make an Any / Any rule that hides every later rule.
        anything = rule.model_copy(update={"languages": None})
        any_language = [
            _fix("Match any language", ReplaceOp(path=f"{base}/{index}/languages", value=None))
        ]
        return _issue(
            Severity.WARNING,
            "defaults.rule_unreachable",
            path,
            f"Rule {number} has an empty language list: it matches no track.",
            *([] if _takes_everything(anything) else any_language),
            _fix(f"Remove rule {number}", RemoveOp(path=f"{base}/{index}")),
        )
    outside = _outside_selection(defaults, rule)
    if outside is not None:
        names = " or ".join(language_label(tag) for tag in outside)
        listed = " and ".join(language_label(tag) for tag in defaults.selection.languages or [])
        adds = [AddOp(path="/audio_defaults/selection/languages/-", value=tag) for tag in outside]
        return _issue(
            Severity.WARNING,
            "defaults.rule_unreachable",
            path,
            f"Rule {number} never applies: it is for {names}, and the selection takes only "
            f"{listed} tracks (other languages: drop; no listed language: take none).",
            _fix(f"Also select {names} tracks", *adds),
            _fix(f"Remove rule {number}", RemoveOp(path=f"{base}/{index}")),
        )
    for earlier in range(index):
        if not rule_covers(rules[earlier], rule):
            continue
        fixes = _move_fixes(index, earlier, rules)
        if _takes_everything(rules[earlier]):
            return _issue(
                Severity.WARNING,
                "defaults.rule_unreachable",
                path,
                f"Rule {number} never applies: rule {earlier + 1} ({describe_rule(rules[earlier])})"
                " takes every track before it.",
                *fixes,
            )
        return _issue(
            Severity.WARNING,
            "defaults.rule_shadowed",
            path,
            f"Rule {number} never applies: rule {earlier + 1} "
            f"({describe_rule(rules[earlier])}) matches every track that rule {number} "
            f"({describe_rule(rule)}) would.",
            *fixes,
        )
    return None


# --------------------------------------------------------------------------- bit rates


def _bitrate_issue(
    path: str,
    encoder: AudioEncoderDef,
    maximum: int,
    mixdown: RuleMixdown,
    condition: SourceChannels,
    container: Container,
    defs: Definitions,
) -> ValidationIssue | None:
    """``defaults.bitrate_snapped`` when ``maximum`` is not what C-7 writes for a layout the
    rule makes (the same table as the codec rules, :func:`bitrate_table`).

    The layouts: a rule that downmixes to a fixed layout (mono, stereo, Dolby Pro Logic II,
    5.1) is checked for the sources it downmixes, the layout it was written for; a source
    with fewer channels keeps its own layout (no upmix), and its snap is a note of that
    source's decision. A rule that keeps the layout (``keep``, ``up_to_5.1``) is checked for
    every layout its channel condition allows (mono, stereo, 5.1, 7.1)."""
    if encoder.bitrate is None:
        return None
    counts = _CHANNELS[condition]
    if mixdown != "keep" and mixdown != "up_to_5.1":
        wanted = defs.mixdowns[mixdown].channels
        counts = tuple(c for c in counts if c >= wanted) or counts
    notes: list[str] = []
    written: set[int] = set()
    seen: set[Mixdown] = set()
    for channels in counts:
        stream = AudioStream(index=0, channels=channels, channel_layout=_LAYOUTS[channels])
        table = bitrate_table(encoder, mixdown, stream, container, defs)
        if table in seen:
            continue
        seen.add(table)
        got = encoder.bitrate.snap(maximum, table, "down")
        if got is None or got == maximum:
            continue
        written.add(got)
        notes.append(snap_note(maximum, got, encoder, table, defs))
    if not notes:
        return None
    fixes = []
    if len(written) == 1 and len(notes) == len(seen):
        (value,) = written
        fixes.append(_fix(f"Use {value} kb/s", ReplaceOp(path=_pointer(path), value=value)))
    return _issue(
        Severity.INFO,
        "defaults.bitrate_snapped",
        path,
        "; ".join(notes) + ".",
        *fixes,
    )


# --------------------------------------------------------------------------- containers


def _encoders(defaults: AudioDefaults) -> list[tuple[str, str]]:
    """``(path, encoder id)`` of every encoder the defaults name."""
    found: list[tuple[str, str]] = []
    for index, rule in enumerate(defaults.codec_rules):
        if rule.codec != PASSTHRU:
            found.append((f"{_rules_path(index)}.codec", rule.codec))
        for n, extra in enumerate(rule.extras.extra_outputs):
            if extra.codec != PASSTHRU:
                found.append((f"{_rules_path(index)}.extras.extra_outputs[{n}].codec", extra.codec))
    found.append(("audio_defaults.passthru.fallback_encoder", defaults.passthru.fallback_encoder))
    return found


def _container_issues(
    defaults: AudioDefaults, container: Container, defs: Definitions
) -> list[ValidationIssue]:
    holder = defs.containers.get(container)
    if holder is None:
        return []
    named = [
        (path, defs.audio_encoders.get(encoder_id)) for path, encoder_id in _encoders(defaults)
    ]
    codecs = {encoder.codec for _, encoder in named if encoder is not None}
    replacement = next(
        (
            defs.audio_encoders[e]
            for e in _ENCODER_PREFERENCE
            if e in defs.audio_encoders and defs.audio_encoders[e].codec in holder.audio.encode
        ),
        None,
    )
    switches = [
        _fix(f"Switch to {other.label}", ReplaceOp(path="/output/container", value=other_id))
        for other_id, other in defs.containers.items()
        if other_id != container
        and codecs <= set(other.audio.encode)
        and set(holder.video.encode) <= set(other.video.encode)
    ]
    issues: list[ValidationIssue] = []
    for path, encoder in named:
        if encoder is None or encoder.codec in holder.audio.encode:
            continue
        fixes: list[Fix] = []
        if replacement is not None:
            fixes.append(
                _fix(
                    f"Use {replacement.label}", ReplaceOp(path=_pointer(path), value=replacement.id)
                )
            )
        issues.append(
            _issue(
                Severity.ERROR,
                "defaults.codec_not_in_container",
                path,
                f"{holder.label} cannot hold {encoder.label} audio ({encoder.id}).",
                *fixes,
                *switches,
            )
        )
    return issues


# --------------------------------------------------------------------------- the lint


def lint_rules(
    defaults: AudioDefaults,
    *,
    container: Container = "mkv",
    definitions: Definitions | None = None,
    used: Collection[int] | None = None,
    container_codecs: bool = True,
) -> list[ValidationIssue]:
    """The lint of :func:`lint_defaults`. ``used``: the 1-based numbers of the rules that
    encoded a selected track of a source (``None``: no source, no ``defaults.rule_unused``).
    ``container_codecs``: :func:`lint_defaults`."""
    defs = definitions or load_definitions()
    rules = defaults.codec_rules
    issues: list[ValidationIssue] = []
    dead: set[int] = set()
    for index, rule in enumerate(rules):
        problem = _reachability(defaults, index)
        if problem is not None:
            issues.append(problem)
            dead.add(index)
        encoder_id = defaults.passthru.fallback_encoder if rule.codec == PASSTHRU else rule.codec
        encoder = defs.audio_encoders.get(encoder_id)
        if encoder is not None and rule.max_bitrate is not None:
            found = _bitrate_issue(
                f"{_rules_path(index)}.max_bitrate",
                encoder,
                rule.max_bitrate,
                rule.mixdown,
                rule.source_channels,
                container,
                defs,
            )
            if found is not None:
                issues.append(found)
        for n, extra in enumerate(rule.extras.extra_outputs):
            extra_encoder = defs.audio_encoders.get(extra.codec)
            if extra_encoder is None or extra.bitrate is None:
                continue
            found = _bitrate_issue(
                f"{_rules_path(index)}.extras.extra_outputs[{n}].bitrate",
                extra_encoder,
                extra.bitrate,
                extra.mixdown,
                rule.source_channels,
                container,
                defs,
            )
            if found is not None:
                issues.append(found)
    if container_codecs:
        issues.extend(_container_issues(defaults, container, defs))
    if used is not None:
        for index, rule in enumerate(rules[:-1]):
            if index in dead or index + 1 in used:
                continue
            issues.append(
                _issue(
                    Severity.INFO,
                    "defaults.rule_unused",
                    _rules_path(index),
                    f"Rule {index + 1} ({describe_rule(rule)}) is not used by any track of this "
                    "source.",
                )
            )
    return issues


def lint_defaults(
    defaults: AudioDefaults,
    *,
    container: Container = "mkv",
    source: MediaSource | None = None,
    definitions: Definitions | None = None,
    preferred_languages: Sequence[str] = (),
    container_codecs: bool = True,
) -> list[ValidationIssue]:
    """Problems of the codec rules: a rule shadowed by an earlier rule (warning), an
    unreachable rule (warning), a max bitrate outside the encoder's range (info: snapped, the
    note names the written value), a codec the container cannot hold (error, with fixes); with
    ``source``, a rule that no selected track of that source uses (info; the selection uses
    ``preferred_languages``, Settings → preferred audio languages). Paths are template paths
    (``audio_defaults.codec_rules[1].max_bitrate``); fixes target ``"template"``. Pure.

    ``container_codecs=False`` leaves out ``defaults.codec_not_in_container``: C-8's
    ``container.codec_unsupported`` reports the same encoders of a template (with fixes that
    know which encoders are available), so ``validate_template`` can pass it to give one
    issue per problem (decision 0031)."""
    defs = definitions or load_definitions()
    used: set[int] | None = None
    if source is not None:
        stage = audio_stage(
            defaults,
            source,
            container=container,
            preferred_languages=preferred_languages,
            definitions=defs,
        )
        selected = [d for d in stage.decisions if d.selected]
        used = {d.rule for d in selected if d.rule is not None} if selected else None
    return lint_rules(
        defaults,
        container=container,
        definitions=defs,
        used=used,
        container_codecs=container_codecs,
    )
