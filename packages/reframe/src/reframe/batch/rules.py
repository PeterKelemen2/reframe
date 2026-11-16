"""The rule engine for presets and batch mode: the audio and subtitle tracks of one source.

Explicit rules (``JobTemplate.audio_rules`` / ``subtitle_rules``) each take the source tracks
their selector finds and make one output per track: fixed settings, or the codec rules evaluated
for that track. A kind without explicit rules compiles its defaults into rules
(:func:`compile_defaults`), and its tracks come from the selection stage. Every selected track is
attributed to its compiled rule, so the matrix has one column per rule.

Explicit rules take precedence over the defaults of their kind. Audio and subtitles are
independent, except that the subtitle defaults' foreign audio search hears the explicit audio.

Pure: no I/O.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from reframe import languages
from reframe.batch.audio_rules import apply_codec_rules, describe_output, layout_label
from reframe.batch.descriptors import codec_label
from reframe.batch.explain import (
    AudioStage,
    ForeignAudio,
    SubtitleStage,
    _container_notes,
    audio_stage,
    subtitle_stage,
)
from reframe.batch.lint import lint_defaults
from reframe.batch.metadata import (
    effective_language,
    language_values,
    render_track_name,
    track_metadata,
)
from reframe.batch.selection import (
    _EXTRA_ROLES,
    Selection,
    effective_languages,
    extra_role,
    language_slot,
)
from reframe.batch.selectors import RulePick, Track, describe_kind, match_rules
from reframe.definitions import Definitions, load_definitions
from reframe.models.batch import MatchStatus, MatrixColumn, TrackMatch
from reframe.models.defaults import AudioDefaults, TrackDecision, TrackDraft
from reframe.models.issues import Severity, ValidationIssue
from reframe.models.job import (
    AudioOutputTrack,
    Container,
    SubtitleOutputTrack,
    TrackMetadata,
)
from reframe.models.media import AudioStream, MediaSource, SubtitleStream, TrackRole
from reframe.models.settings import LanguageSettings
from reframe.models.template import (
    AudioCodecRules,
    AudioOutputSettings,
    JobTemplate,
    OutputTrackRule,
    SubtitleOutputSettings,
    TrackMetadataTemplate,
    TrackSelector,
)
from reframe.naming.context import audio_channels_label
from reframe.naming.template import Value
from reframe.probe.names import codec_name

__all__ = [
    "CompiledRule",
    "TrackResolution",
    "compile_defaults",
    "literal_title",
    "resolve_tracks",
    "rule_label",
    "title_text",
]

Kind = Literal["audio", "subtitle"]
CompiledGroup = Literal["all", "language", "no_match", "other", "extra", "foreign_audio"]
_PREFIX: dict[Kind, str] = {"audio": "A", "subtitle": "S"}
_FLAGS = ("default", "forced", "commentary", "hearing_impaired", "visual_impaired", "original")
_SORT_OF_TIE_BREAK: dict[str, Literal["source_order", "most_channels", "highest_bitrate"]] = {
    "source_order": "source_order",
    "most_channels": "most_channels",
    "best_quality": "highest_bitrate",
}


#: Regex metacharacters outside a character class. ``re.escape`` also escapes spaces, ``&``, ``#``
#: and ``~``, which only verbose mode reads.
_SPECIAL = re.compile(r"([.^$*+?{}\[\]\\|()])")


def literal_title(title: str) -> str:
    """The title pattern that matches exactly ``title``, case-insensitively like every title
    pattern: ``Signs & Songs`` → ``^Signs & Songs$``."""
    escaped = _SPECIAL.sub(r"\\\1", title)
    return f"^{escaped}$"


def title_text(pattern: str) -> str:
    """The title a pattern stands for: ``^Signs & Songs$`` → ``Signs & Songs`` for a literal
    title, else the pattern itself."""
    match = re.fullmatch(r"\^(.*)\$", pattern, re.DOTALL)
    if match is not None:
        literal = re.sub(r"\\(.)", r"\1", match.group(1), flags=re.DOTALL)
        if literal_title(literal) == pattern:
            return literal
    return pattern


def _selector_source(selector: TrackSelector) -> str:
    if selector.languages == []:
        return "no track"
    parts = []
    if selector.languages:
        parts.append("/".join(languages.to_matroska_legacy(tag) for tag in selector.languages))
    else:
        parts.append("any")
    if selector.kind == "audio":
        if selector.profiles:
            parts.append(selector.profiles[0])
        elif selector.codecs:
            parts.append(codec_name(selector.codecs[0]))
    else:
        if selector.title_pattern is not None:
            parts.append(title_text(selector.title_pattern))
        elif selector.roles:
            parts.append("/".join(role.value for role in selector.roles))
        elif selector.codecs:
            parts.append(codec_name(selector.codecs[0]))
    return " ".join(parts)


def _target(rule: OutputTrackRule, defs: Definitions) -> str:
    settings = rule.settings
    if isinstance(settings, AudioCodecRules):
        return "codec rules"
    if isinstance(settings, AudioOutputSettings):
        if settings.action == "passthru":
            return "passthru"
        encoder = defs.audio_encoders.get(settings.encoder or "")
        text = encoder.label if encoder is not None else str(settings.encoder)
        if settings.mixdown is not None:
            text += f" {layout_label(settings.mixdown, defs)}"
        return text
    if settings.action == "burn":
        return "burn in"
    if settings.action == "convert" and settings.convert_to is not None:
        return settings.convert_to.upper() if settings.convert_to != "mov_text" else "mov_text"
    return "copy"


def rule_label(kind: Kind, number: int, rule: OutputTrackRule, definitions: Definitions) -> str:
    """The matrix column of an explicit rule; ``number`` is 0-based."""
    head = f"{_PREFIX[kind]}{number + 1} {_selector_source(rule.selector)}"
    if rule.selector.languages == []:
        return head
    target = _target(rule, definitions)
    if kind == "audio":
        return f"{head}→{target}"
    return head if target == "copy" else f"{head} ({target})"


@dataclass(frozen=True, slots=True)
class CompiledRule:
    """A rule compiled from a template's audio or subtitle defaults."""

    kind: Kind
    group: CompiledGroup
    """Which part of the defaults it stands for (the selection stage's pick groups, and the
    foreign audio search)."""
    rule: OutputTrackRule
    words: str
    """The column text after the rule's number."""
    slot: int | None = None
    """The index of its language in the listed languages (``language`` rules)."""
    language: str | None = None

    def label(self, number: int) -> str:
        return f"{_PREFIX[self.kind]}{number + 1} {self.words} (defaults)"


def compile_defaults(
    template: JobTemplate, kind: Kind, *, preferred: Sequence[str] = ()
) -> list[CompiledRule]:
    """The template's ``kind`` defaults as track rules: one per listed language, with the codec
    rules as settings, plus one rule for each other part of the selection that takes tracks (the
    no-match track, other languages, commentary and descriptions, and for subtitles the foreign
    audio search). ``preferred``: the preferred languages of ``kind``. With no language at all,
    one rule takes every track.

    A selector cannot say everything the selection stage decides (the default-flagged track of
    the no-match rule, "not a listed language", ``und`` as the first language). These rules only
    name the columns and show where each track came from."""
    defaults = template.audio_defaults if kind == "audio" else template.subtitle_defaults
    selection = defaults.selection
    settings: AudioCodecRules | SubtitleOutputSettings
    if kind == "audio":
        audio = template.audio_defaults
        settings = AudioCodecRules(rules=audio.codec_rules, passthru=audio.passthru)
    else:
        settings = SubtitleOutputSettings()
    extras = list(_EXTRA_ROLES[kind])
    sort = _SORT_OF_TIE_BREAK[selection.tie_break]

    def rule(selector: TrackSelector, multiple: bool) -> OutputTrackRule:
        return OutputTrackRule(
            selector=selector, multiple=multiple, settings=settings, required=False
        )

    listed = effective_languages(selection.languages, preferred)
    if not listed:
        return [CompiledRule(kind, "all", rule(TrackSelector(kind=kind), True), "every track")]
    compiled: list[CompiledRule] = []
    if selection.tracks_per_language != "none":
        for slot, tag in enumerate(listed):
            tags = [tag]
            if slot == 0 and selection.undetermined == "first_language":
                tags.append("und")
            selector = TrackSelector(kind=kind, languages=tags, exclude_roles=extras, sort=sort)
            multiple = selection.tracks_per_language == "all"
            compiled.append(
                CompiledRule(
                    kind,
                    "language",
                    rule(selector, multiple),
                    languages.to_matroska_legacy(tag),
                    slot,
                    tag,
                )
            )
    if selection.no_match != "none":
        selector = TrackSelector(kind=kind, exclude_roles=extras)
        compiled.append(CompiledRule(kind, "no_match", rule(selector, False), "no listed language"))
    if selection.other_languages != "drop":
        selector = TrackSelector(kind=kind, exclude_roles=extras, sort=sort)
        multiple = selection.other_languages == "keep_all"
        compiled.append(CompiledRule(kind, "other", rule(selector, multiple), "other languages"))
    if selection.commentary == "keep_after_main":
        selector = TrackSelector(kind=kind, roles=extras)
        compiled.append(CompiledRule(kind, "extra", rule(selector, True), "commentary"))
    if kind == "subtitle" and template.subtitle_defaults.foreign_audio_search:
        selector = TrackSelector(kind=kind, roles=[TrackRole.FORCED, TrackRole.SIGNS])
        compiled.append(
            CompiledRule(kind, "foreign_audio", rule(selector, False), "foreign audio search")
        )
    return compiled


_SKIPPED = {
    "all": "no track",
    "no_match": "a main track of a listed language was found",
    "other": "no track in another language",
    "extra": "no commentary or description track",
}


def _attribute(
    compiled: Sequence[CompiledRule],
    selection: Selection[AudioStream] | Selection[SubtitleStream],
    foreign: ForeignAudio | None,
) -> list[TrackMatch]:
    """One matrix cell per compiled rule: the tracks the selection stage took for it."""
    picks = selection.picks
    selected = [picks[position] for position in selection.order]
    matches: list[TrackMatch] = []
    for number, rule in enumerate(compiled):
        message = ""
        if rule.group == "foreign_audio":
            found = foreign.track if foreign is not None else None
            streams = [picks[found].stream.index] if found is not None else []
            candidates = list(streams)
            message = foreign.note if foreign is not None else ""
        else:
            taken = [
                p
                for p in selected
                if p.group == rule.group and (rule.group != "language" or p.slot == rule.slot)
            ]
            streams = [p.stream.index for p in taken]
            if rule.group == "language":
                listed = selection.languages
                candidates = [
                    p.stream.index
                    for p in picks
                    if extra_role(p.stream) is None and _slot(p.stream, listed, rule) == rule.slot
                ]
            elif rule.group == "all":
                candidates = [p.stream.index for p in picks]
            else:
                candidates = list(streams)
            if len(taken) == 1:
                message = taken[0].why
            elif taken:
                message = f"{len(taken)} tracks"
            elif rule.group == "language":
                message = f"no {languages.english_name(rule.language)} track"
            else:
                message = _SKIPPED[rule.group]
        status: MatchStatus = "exact" if streams else "skipped"
        matches.append(
            TrackMatch(
                kind=rule.kind,
                rule=number,
                status=status,
                streams=streams,
                candidates=candidates,
                severity=None if streams else Severity.INFO,
                message=message,
                defaults=True,
            )
        )
    return matches


def _slot(
    stream: AudioStream | SubtitleStream, listed: Sequence[str], rule: CompiledRule
) -> int | None:
    undetermined: Literal["first_language", "other"] = (
        "first_language" if "und" in (rule.rule.selector.languages or []) else "other"
    )
    return language_slot(effective_language(stream), listed, undetermined)


@dataclass(slots=True)
class _Output[T: (AudioOutputTrack, SubtitleOutputTrack)]:
    rule: int
    track: Track
    output: T
    extra: bool
    """An extra output of a codec rule (never the default track)."""
    explicit_default: bool | None


@dataclass(slots=True)
class _Taken:
    """What the rules did with one source track."""

    how: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    codec_rule: list[int | None] = field(default_factory=list)
    measure: bool = False


def _how(pick: RulePick, label: str) -> str:
    match = pick.match
    detail = (match.message or "exact match") if match.status == "exact" else match.message
    return f"Rule {label}: {detail}"


def _audio_values(
    track: Track, output: AudioOutputTrack, language: str | None, defs: Definitions
) -> dict[str, Value]:
    stream = track.stream
    assert isinstance(stream, AudioStream)
    if output.action == "passthru":
        channels = audio_channels_label(stream.channels, stream.channel_layout)
        codec = codec_label(stream)
        bitrate: int | None = None
    else:
        channels = (
            layout_label(output.mixdown, defs)
            if output.mixdown is not None
            else audio_channels_label(stream.channels, stream.channel_layout)
        )
        encoder = defs.audio_encoders.get(output.encoder or "")
        codec = encoder.label if encoder is not None else str(output.encoder)
        bitrate = output.bitrate
    return {
        **language_values(language),
        "channels": channels,
        "codec": codec,
        "bitrate": bitrate,
        "title": stream.title,
        "source_codec": codec_label(stream),
    }


def _subtitle_values(track: Track, language: str | None) -> dict[str, Value]:
    stream = track.stream
    return {
        **language_values(language),
        "codec": codec_label(stream),
        "title": stream.title,
        "source_codec": codec_label(stream),
    }


def _metadata(
    meta: TrackMetadata,
    template: TrackMetadataTemplate,
    values: dict[str, Value],
    *,
    extra: bool,
) -> TrackMetadata:
    update: dict[str, object] = {}
    if template.language is not None:
        update["language"] = template.language
        values = {
            **values,
            **language_values(template.language),
        }
    if template.name_template is not None:
        update["name"] = render_track_name(template.name_template, values)
    for flag in _FLAGS:
        value = getattr(template, flag)
        if value is not None:
            update[flag] = value
    if extra:
        update["default"] = False
    return meta.model_copy(update=update)


def _defaults_flag[T: (AudioOutputTrack, SubtitleOutputTrack)](
    outputs: list[_Output[T]], *, eligible: Sequence[bool]
) -> list[T]:
    """The default flags: a rule's explicit ``default: true`` wins over the source flags of the
    other outputs; otherwise only the first output with a default source track keeps the flag."""
    explicit = any(
        o.explicit_default is True and not o.extra and ok
        for o, ok in zip(outputs, eligible, strict=True)
    )
    kept = False
    result: list[T] = []
    for output, ok in zip(outputs, eligible, strict=True):
        flag = output.output.metadata.default
        if output.extra or not ok:
            flag = False
        elif output.explicit_default is None:
            flag = flag and not explicit and not kept
        if flag and output.explicit_default is None:
            kept = True
        if flag != output.output.metadata.default:
            meta = output.output.metadata.model_copy(update={"default": flag})
            result.append(output.output.model_copy(update={"metadata": meta}))
        else:
            result.append(output.output)
    return result


def _settings_issue(kind: Kind, n: int, label: str, list_path: str) -> ValidationIssue:
    other = "subtitle" if kind == "audio" else "audio"
    return ValidationIssue(
        severity=Severity.ERROR,
        code="batch.rule_settings",
        path=f"{list_path}[{n}].settings",
        message=f"Rule {label} has {other} settings: it makes no {kind} track.",
    )


def _no_track_cell(match: TrackMatch, kind: Kind) -> TrackMatch:
    other = "subtitle" if kind == "audio" else "audio"
    return match.model_copy(
        update={
            "status": "missing",
            "streams": [],
            "severity": Severity.ERROR,
            "message": f"the rule has {other} settings: it makes no {kind} track",
        }
    )


@dataclass(frozen=True, slots=True)
class _KindResult[T: (AudioOutputTrack, SubtitleOutputTrack)]:
    outputs: list[T]
    decisions: list[TrackDecision]
    matches: list[TrackMatch]
    columns: list[MatrixColumn]
    issues: list[ValidationIssue]


def _explicit_audio(
    rules: Sequence[OutputTrackRule], source: MediaSource, container: Container, defs: Definitions
) -> _KindResult[AudioOutputTrack]:
    tracks = describe_kind(source.audio)
    labels = [rule_label("audio", n, rule, defs) for n, rule in enumerate(rules)]
    picks, issues = match_rules(rules, tracks, "audio", labels=labels, list_path="audio_rules")
    produced: list[_Output[AudioOutputTrack]] = []
    taken: dict[int, _Taken] = {}
    seen: list[str | None] = []
    # Per source track: the first selected track of its language (a track that two rules
    # take is the first for both).
    first_of: dict[int, bool] = {}
    matches = [pick.match for pick in picks]
    for pick in picks:
        rule = rules[pick.rule]
        label = labels[pick.rule]
        settings = rule.settings
        if pick.tracks and isinstance(settings, SubtitleOutputSettings):
            issues.append(_settings_issue("audio", pick.rule, label, "audio_rules"))
            matches[pick.rule] = _no_track_cell(pick.match, "audio")
            continue
        for track in pick.tracks:
            stream = track.stream
            assert isinstance(stream, AudioStream)
            state = taken.setdefault(track.descriptor.index, _Taken())
            state.how.append(_how(pick, label))
            first = first_of.get(stream.index)
            if first is None:
                language = effective_language(stream)
                first = not any(languages.same_language(language, other) for other in seen)
                first_of[stream.index] = first
                if first:
                    seen.append(language)
            outputs: list[AudioOutputTrack]
            if isinstance(settings, AudioCodecRules):
                defaults = AudioDefaults(codec_rules=settings.rules, passthru=settings.passthru)
                outputs, decision = apply_codec_rules(
                    stream, defaults, container, definitions=defs, first_of_language=first
                )
                state.reasons.append(decision.reason)
                state.notes.extend(decision.notes)
                state.codec_rule.append(decision.rule)
                state.measure = state.measure or decision.measure
            else:
                assert isinstance(settings, AudioOutputSettings)
                data = settings.model_dump(exclude={"kind"})
                output = AudioOutputTrack.model_validate(
                    {**data, "source_stream": stream.index, "metadata": track_metadata(stream)}
                )
                outputs = [output]
                described = describe_output(output, defs)
                state.reasons.append(f"Fixed settings of rule {label}: {described}")
                state.codec_rule.append(None)
            for position, output in enumerate(outputs):
                extra = position > 0
                language_out = rule.metadata.language or output.metadata.language
                values = _audio_values(track, output, language_out, defs)
                meta = _metadata(output.metadata, rule.metadata, values, extra=extra)
                produced.append(
                    _Output(
                        pick.rule,
                        track,
                        output.model_copy(update={"metadata": meta}),
                        extra,
                        rule.metadata.default,
                    )
                )
    final = _defaults_flag(produced, eligible=[True] * len(produced))
    by_stream: dict[int, list[AudioOutputTrack]] = {}
    for item, output in zip(produced, final, strict=True):
        by_stream.setdefault(item.track.descriptor.index, []).append(output)
    decisions: list[TrackDecision] = []
    for track in tracks:
        index = track.descriptor.index
        found = taken.get(index)
        if found is None:
            why = "No track rule takes this track"
            decisions.append(
                TrackDecision(
                    source_stream=index, kind="audio", selected=False, selection=why, reason=why
                )
            )
            continue
        outputs = by_stream.get(index, [])
        notes = list(found.notes)
        if any(o.metadata.default for o in outputs):
            notes.append("The default audio track")
        rules_used = {rule for rule in found.codec_rule if rule is not None}
        decisions.append(
            TrackDecision(
                source_stream=index,
                kind="audio",
                selected=True,
                selection="; ".join(found.how),
                rule=rules_used.pop() if len(rules_used) == 1 else None,
                outputs=outputs,
                reason=". ".join(found.reasons),
                notes=notes,
                measure=found.measure,
            )
        )
    columns = [MatrixColumn(kind="audio", rule=n, label=label) for n, label in enumerate(labels)]
    return _KindResult(final, decisions, matches, columns, issues)


def _explicit_subtitles(
    rules: Sequence[OutputTrackRule], source: MediaSource, container: Container, defs: Definitions
) -> _KindResult[SubtitleOutputTrack]:
    tracks = describe_kind(source.subtitles)
    holder = defs.containers.get(container)
    labels = [rule_label("subtitle", n, rule, defs) for n, rule in enumerate(rules)]
    picks, issues = match_rules(
        rules, tracks, "subtitle", labels=labels, list_path="subtitle_rules"
    )
    produced: list[_Output[SubtitleOutputTrack]] = []
    taken: dict[int, _Taken] = {}
    matches = [pick.match for pick in picks]
    for pick in picks:
        rule = rules[pick.rule]
        label = labels[pick.rule]
        settings = rule.settings
        if pick.tracks and not isinstance(settings, SubtitleOutputSettings):
            issues.append(_settings_issue("subtitle", pick.rule, label, "subtitle_rules"))
            matches[pick.rule] = _no_track_cell(pick.match, "subtitle")
            continue
        for track in pick.tracks:
            stream = track.stream
            assert isinstance(stream, SubtitleStream)
            assert isinstance(settings, SubtitleOutputSettings)
            state = taken.setdefault(track.descriptor.index, _Taken())
            state.how.append(_how(pick, label))
            base = track_metadata(stream)
            language_out = rule.metadata.language or base.language
            meta = _metadata(
                base, rule.metadata, _subtitle_values(track, language_out), extra=False
            )
            output = SubtitleOutputTrack(
                source=stream.index,
                action=settings.action,
                convert_to=settings.convert_to,
                forced_only=settings.forced_only,
                metadata=meta,
            )
            match settings.action:
                case "burn":
                    reason = "Burn in" + (", forced events only" if settings.forced_only else "")
                case "convert":
                    reason = f"Convert to {settings.convert_to or 'the container format'}"
                case _:
                    reason = "Copy"
                    state.notes.extend(_container_notes(stream, holder))
            state.reasons.append(f"{reason} (rule {label})")
            produced.append(_Output(pick.rule, track, output, False, rule.metadata.default))
    eligible = [item.output.action != "burn" for item in produced]
    final = _defaults_flag(produced, eligible=eligible)
    by_stream: dict[int, list[SubtitleOutputTrack]] = {}
    for item, output in zip(produced, final, strict=True):
        by_stream.setdefault(item.track.descriptor.index, []).append(output)
    decisions: list[TrackDecision] = []
    for track in tracks:
        index = track.descriptor.index
        found = taken.get(index)
        if found is None:
            why = "No track rule takes this track"
            decisions.append(
                TrackDecision(
                    source_stream=index,
                    kind="subtitle",
                    selected=False,
                    selection=why,
                    reason=why,
                )
            )
            continue
        decisions.append(
            TrackDecision(
                source_stream=index,
                kind="subtitle",
                selected=True,
                selection="; ".join(found.how),
                subtitle_outputs=by_stream.get(index, []),
                reason=". ".join(found.reasons),
                notes=found.notes,
            )
        )
    columns = [MatrixColumn(kind="subtitle", rule=n, label=label) for n, label in enumerate(labels)]
    return _KindResult(final, decisions, matches, columns, issues)


@dataclass(frozen=True, slots=True)
class TrackResolution:
    """The tracks of one source for one template."""

    draft: TrackDraft
    """The output tracks, one decision per source track, and the issues of the track stage
    (rule cells that are not exact matches; for defaults the no-match error and the lint)."""
    matches: list[TrackMatch]
    """One matrix cell per rule: audio, then subtitles."""
    columns: list[MatrixColumn]
    """The audio and subtitle columns of the matrix (``A1 …``, ``S1 …``)."""


def _compiled_columns(compiled: Sequence[CompiledRule]) -> list[MatrixColumn]:
    return [
        MatrixColumn(kind=rule.kind, rule=n, label=rule.label(n), defaults=True)
        for n, rule in enumerate(compiled)
    ]


def resolve_tracks(
    template: JobTemplate,
    source: MediaSource,
    *,
    definitions: Definitions | None = None,
    languages: LanguageSettings | None = None,
    container_codecs: bool = True,
) -> TrackResolution:
    """The audio and subtitle tracks of ``source`` with ``template``: explicit rules where the
    template has them, else the defaults. ``languages``: the preferred languages of the defaults.
    ``container_codecs=False`` leaves out the lint's ``defaults.codec_not_in_container``, for a
    caller that reports ``container.codec_unsupported`` itself."""
    defs = definitions or load_definitions()
    container = template.output.container
    preferred_audio = languages.preferred_audio if languages is not None else []
    preferred_subtitle = languages.preferred_subtitle if languages is not None else []

    audio_stage_result: AudioStage | None = None
    if template.audio_rules:
        audio = _explicit_audio(template.audio_rules, source, container, defs)
    else:
        audio_stage_result = audio_stage(
            template.audio_defaults,
            source,
            container=container,
            preferred_languages=preferred_audio,
            definitions=defs,
        )
        compiled = compile_defaults(template, "audio", preferred=preferred_audio)
        audio = _KindResult(
            audio_stage_result.outputs,
            audio_stage_result.decisions,
            _attribute(compiled, audio_stage_result.selection, None),
            _compiled_columns(compiled),
            list(audio_stage_result.issues),
        )

    subtitles: _KindResult[SubtitleOutputTrack]
    if template.subtitle_rules:
        subtitles = _explicit_subtitles(template.subtitle_rules, source, container, defs)
    else:
        stage: SubtitleStage = subtitle_stage(
            template.subtitle_defaults,
            source,
            container=container,
            preferred_languages=preferred_subtitle,
            audio=audio.outputs,
            definitions=defs,
        )
        compiled = compile_defaults(template, "subtitle", preferred=preferred_subtitle)
        subtitles = _KindResult(
            stage.outputs,
            stage.decisions,
            _attribute(compiled, stage.selection, stage.foreign_audio),
            _compiled_columns(compiled),
            list(stage.issues),
        )

    issues = [*audio.issues, *subtitles.issues]
    if audio_stage_result is not None:
        selected = [d for d in audio_stage_result.decisions if d.selected]
        used = {d.rule for d in selected if d.rule is not None} if selected else None
        issues += lint_defaults(
            template.audio_defaults,
            container=container,
            definitions=defs,
            used=used,
            container_codecs=container_codecs,
        )
    draft = TrackDraft(
        audio=audio.outputs,
        subtitles=subtitles.outputs,
        decisions=audio.decisions,
        subtitle_decisions=subtitles.decisions,
        issues=issues,
    )
    return TrackResolution(
        draft=draft,
        matches=[*audio.matches, *subtitles.matches],
        columns=[*audio.columns, *subtitles.columns],
    )
