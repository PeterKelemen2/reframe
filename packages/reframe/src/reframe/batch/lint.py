"""The lint of a template's rules: problems of the audio defaults' codec rules and of the track
rules, each with fixes that are JSON patches on the template. Pure: no I/O.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence

from reframe.batch.audio_rules import (
    CHANNEL_CONDITIONS,
    PASSTHRU,
    bitrate_table,
    snap_note,
)
from reframe.batch.selection import TrackKind
from reframe.definitions import AudioEncoderDef, Definitions, load_definitions
from reframe.languages import english_name, matches
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
from reframe.models.media import AudioStream
from reframe.models.template import JobTemplate, OutputTrackRule, SubtitleOutputSettings

__all__ = [
    "describe_rule",
    "lint_defaults",
    "lint_track_rules",
    "rule_covers",
]

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


def describe_rule(rule: AudioCodecRule) -> str:
    """The rule's languages, channel condition and first-track limit, in words."""
    if rule.languages is None:
        langs = "any language"
    elif not rule.languages:
        langs = "no language"
    else:
        langs = " or ".join(english_name(tag) for tag in rule.languages)
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
    """The rule's languages when the selection never takes a track in any of them, else
    ``None``."""
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
        # Never the last rule: the model keeps the catch-all there, so the removal is safe.
        # "Any language" is not offered when it would make a rule that takes every track, which
        # hides every later rule.
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
        names = " or ".join(english_name(tag) for tag in outside)
        listed = " and ".join(english_name(tag) for tag in defaults.selection.languages or [])
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


def _bitrate_issue(
    path: str,
    encoder: AudioEncoderDef,
    maximum: int,
    mixdown: RuleMixdown,
    condition: SourceChannels,
    container: Container,
    defs: Definitions,
) -> ValidationIssue | None:
    """``defaults.bitrate_snapped`` when ``maximum`` is not what the command builder writes for
    a layout the rule makes (the same table as the codec rules, :func:`bitrate_table`).

    A rule that downmixes to a fixed layout is checked for the sources it downmixes. A source
    with fewer channels keeps its own layout (no upmix), and its snap is a note of that source's
    decision. A rule that keeps the layout (``keep``, ``up_to_5.1``) is checked for every layout
    its channel condition allows."""
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


def lint_defaults(
    defaults: AudioDefaults,
    *,
    container: Container = "mkv",
    definitions: Definitions | None = None,
    used: Collection[int] | None = None,
    container_codecs: bool = True,
) -> list[ValidationIssue]:
    """Problems of the codec rules: shadowed or unreachable rules (warning), a max bitrate that
    the encoder snaps (info; the note names the written value), an encoder the container cannot
    hold (error, with fixes), and the rules that no selected track of a source uses (info).
    Paths are template paths; fixes target ``"template"``.

    ``used``: the 1-based numbers of the rules that encoded a selected track of a source
    (``None``: no source, so no ``defaults.rule_unused``). ``container_codecs=False`` leaves out
    ``defaults.codec_not_in_container``, for a caller whose own check reports the same encoders.
    """
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


def _may_be_default(rule: OutputTrackRule, kind: TrackKind) -> bool:
    """The rule makes output tracks that its ``default`` applies to: a selector or settings of
    the other kind, or an empty language list, take no track; a burned-in subtitle is none."""
    selector = rule.selector
    if selector.kind != kind or (selector.languages == [] and selector.stream is None):
        return False
    if kind == "audio":
        return not isinstance(rule.settings, SubtitleOutputSettings)
    return isinstance(rule.settings, SubtitleOutputSettings) and rule.settings.action != "burn"


def lint_track_rules(template: JobTemplate) -> list[ValidationIssue]:
    """Track rules that mark several output tracks of one kind default: a ``multiple`` rule
    with ``default: true`` marks every track it takes, and every rule with ``default: true``
    marks its own (a warning: allowed, but usually one track is the default)."""
    issues: list[ValidationIssue] = []
    lists: tuple[tuple[str, TrackKind, Sequence[OutputTrackRule]], ...] = (
        ("audio_rules", "audio", template.audio_rules),
        ("subtitle_rules", "subtitle", template.subtitle_rules),
    )
    for field, kind, rules in lists:
        prefix = "A" if kind == "audio" else "S"
        marking = [
            n
            for n, rule in enumerate(rules)
            if rule.metadata.default is True and _may_be_default(rule, kind)
        ]
        for n in marking:
            # A hand pick (``stream``) takes one track, even in a ``multiple`` rule.
            if not rules[n].multiple or rules[n].selector.stream is not None:
                continue
            path = f"{field}[{n}].metadata.default"
            issues.append(
                _issue(
                    Severity.WARNING,
                    "metadata.several_defaults",
                    path,
                    f"Rule {prefix}{n + 1} takes every matching {kind} track and marks each one "
                    "default.",
                    _fix(
                        "Take the default flag from the source (one track at most)",
                        ReplaceOp(path=_pointer(path), value=None),
                    ),
                )
            )
        if len(marking) < 2:
            continue
        first, *others = marking
        numbers = [f"{prefix}{n + 1}" for n in marking]
        names = ", ".join(numbers[:-1]) + " and " + numbers[-1]
        issues.append(
            _issue(
                Severity.WARNING,
                "metadata.several_defaults",
                f"{field}[{others[0]}].metadata.default",
                f"Rules {names} {'both' if len(marking) == 2 else 'all'} set default: every "
                f"{kind} track they make is marked default.",
                _fix(
                    f"Mark only the tracks of rule {prefix}{first + 1} default",
                    *(
                        ReplaceOp(path=_pointer(f"{field}[{n}].metadata.default"), value=False)
                        for n in others
                    ),
                ),
            )
        )
    return issues
