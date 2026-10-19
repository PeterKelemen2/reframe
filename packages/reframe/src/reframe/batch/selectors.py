"""Track selectors: which source tracks a track rule takes, with relaxation.

When a selector finds no candidate, its title pattern, profiles, channels and codecs are dropped
one at a time, in :data:`RELAX_ORDER`, and each dropped field is recorded. Languages and roles
are never dropped.

Among several rules, a relaxed rule never takes a track that another rule matches exactly (a
track picked by hand is such a match), nor a track that an earlier relaxed rule took. Exact
matches may share a track: one source track in two outputs is a choice, as a passthru and a
stereo copy of one track are.

Pure: no I/O.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Literal

from reframe import languages
from reframe.batch.descriptors import describe_stream
from reframe.batch.selection import sort_key
from reframe.models.batch import MatchStatus, TrackDescriptor, TrackMatch
from reframe.models.issues import Fix, ReplaceOp, Severity, ValidationIssue
from reframe.models.media import AudioStream, SubtitleStream
from reframe.models.template import OutputTrackRule, TrackSelector

__all__ = [
    "RELAX_ORDER",
    "RELAX_WORDS",
    "SORT_WORDS",
    "RulePick",
    "Track",
    "candidates",
    "describe_kind",
    "match_rules",
    "relaxation_steps",
    "selector_matches",
    "title_regex",
]

#: The fields dropped one at a time when a selector finds nothing; never the language or the roles.
RELAX_ORDER: tuple[str, ...] = ("title_pattern", "profiles", "channels", "codecs")
#: How a dropped field is named in the match message.
RELAX_WORDS = {
    "title_pattern": "title",
    "profiles": "profile",
    "channels": "channels",
    "codecs": "codec",
}
#: How a selector's sort is named in the match message.
SORT_WORDS = {
    "source_order": "source order",
    "most_channels": "most channels",
    "highest_bitrate": "highest bit rate",
}
_TIE_BREAK: dict[str, Literal["source_order", "most_channels", "best_quality"]] = {
    "source_order": "source_order",
    "most_channels": "most_channels",
    "highest_bitrate": "best_quality",
}

Kind = Literal["audio", "subtitle"]


@dataclass(frozen=True, slots=True)
class Track:
    """One source track of a kind: its descriptor and its stream."""

    descriptor: TrackDescriptor
    stream: AudioStream | SubtitleStream


def describe_kind(streams: Sequence[AudioStream | SubtitleStream]) -> list[Track]:
    """The tracks of one kind (``source.audio`` or ``source.subtitles``), in source order."""
    return [Track(describe_stream(s, position), s) for position, s in enumerate(streams)]


def title_regex(pattern: str | None) -> re.Pattern[str] | str | None:
    """The compiled case-insensitive title pattern, ``None`` without one, or the error text
    of a pattern that is not a valid regular expression."""
    if pattern is None:
        return None
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        return str(exc)


def _language_rank(selector: TrackSelector, language: str | None) -> int | None:
    if selector.languages is None:
        return 0
    for rank, tag in enumerate(selector.languages):
        if languages.matches(tag, language):
            return rank
    return None


def _profile(selector: TrackSelector, track: Track) -> bool:
    assert selector.profiles is not None
    wanted = {p.casefold() for p in selector.profiles}
    names = {
        value.casefold()
        for value in (track.descriptor.profile, track.stream.display_codec, track.stream.profile)
        if value
    }
    return bool(wanted & names)


def selector_matches(
    selector: TrackSelector, track: Track, title: re.Pattern[str] | None = None
) -> bool:
    """Whether ``track`` passes every filter of ``selector`` (``title``: the compiled
    ``title_pattern``; :func:`title_regex`)."""
    d = track.descriptor
    if d.kind != selector.kind:
        return False
    if _language_rank(selector, d.language) is None:
        return False
    if selector.codecs is not None and (d.codec or "").casefold() not in {
        c.casefold() for c in selector.codecs
    }:
        return False
    if selector.profiles is not None and not _profile(selector, track):
        return False
    if selector.roles is not None and not set(selector.roles) & set(d.roles):
        return False
    if selector.exclude_roles is not None and set(selector.exclude_roles) & set(d.roles):
        return False
    if selector.channels is not None and d.channels != selector.channels:
        return False
    return not (
        selector.title_pattern is not None
        and (title is None or title.search(d.title or "") is None)
    )


def candidates(
    selector: TrackSelector,
    tracks: Sequence[Track],
    *,
    exclude: Collection[int] = (),
    title: re.Pattern[str] | None = None,
) -> list[Track]:
    """The tracks that match ``selector`` (not those whose stream index is in
    ``exclude``), in the selector's order: language preference, then ``sort``."""
    tie = _TIE_BREAK[selector.sort]
    found = [
        t
        for t in tracks
        if t.descriptor.index not in exclude and selector_matches(selector, t, title)
    ]

    def key(track: Track) -> tuple[int, ...]:
        rank = _language_rank(selector, track.descriptor.language) or 0
        return (rank, *sort_key(track.stream, track.descriptor.position, tie))

    return sorted(found, key=key)


def relaxation_steps(selector: TrackSelector) -> list[tuple[tuple[str, ...], TrackSelector]]:
    """The full selector, then the selector without each field of :data:`RELAX_ORDER` that
    it sets, one more at a time; each with the fields dropped so far."""
    steps: list[tuple[tuple[str, ...], TrackSelector]] = [((), selector)]
    dropped: list[str] = []
    current = selector
    for name in RELAX_ORDER:
        if getattr(current, name) is None:
            continue
        dropped.append(name)
        current = current.model_copy(update={name: None})
        steps.append((tuple(dropped), current))
    return steps


@dataclass(frozen=True, slots=True)
class RulePick:
    """What one rule took in one file."""

    rule: int
    """The rule's index in its list."""
    match: TrackMatch
    tracks: list[Track]
    """The tracks it takes, in output order (empty: missing or skipped)."""


def _words(fields: Sequence[str]) -> str:
    return ", ".join(RELAX_WORDS[name] for name in fields)


def match_rules(
    rules: Sequence[OutputTrackRule],
    tracks: Sequence[Track],
    kind: Kind,
    *,
    labels: Sequence[str],
    list_path: str,
) -> tuple[list[RulePick], list[ValidationIssue]]:
    """Match every rule of one kind against the tracks of that kind: one :class:`RulePick` per
    rule, and an issue for every cell that is not an exact match. ``labels``: the rules' column
    labels; ``list_path``: the template's list of rules, for the issue paths.

    A rule whose selector is of the other kind, or whose title pattern is not a regular
    expression, matches nothing and is an error.
    """
    issues: list[ValidationIssue] = []
    patterns: list[re.Pattern[str] | None] = []
    usable: list[bool] = []
    for number, rule in enumerate(rules):
        selector = rule.selector
        compiled = title_regex(selector.title_pattern)
        ok = True
        if selector.kind != kind:
            ok = False
            issues.append(
                ValidationIssue(
                    severity=Severity.ERROR,
                    code="batch.rule_kind",
                    path=f"{list_path}[{number}].selector.kind",
                    message=(
                        f"Rule {labels[number]} selects {selector.kind} tracks, but it is a "
                        f"{kind} rule: it takes no track."
                    ),
                )
            )
        if isinstance(compiled, str):
            ok = False
            issues.append(
                ValidationIssue(
                    severity=Severity.ERROR,
                    code="batch.bad_title_pattern",
                    path=f"{list_path}[{number}].selector.title_pattern",
                    message=(
                        f"The title pattern of rule {labels[number]} is not a regular "
                        f"expression ({compiled}): the rule takes no track."
                    ),
                )
            )
            compiled = None
        patterns.append(compiled)
        usable.append(ok)

    exact: list[list[Track]] = [
        candidates(rule.selector, tracks, title=patterns[n]) if usable[n] else []
        for n, rule in enumerate(rules)
    ]
    # The exact matches, which relaxed rules leave alone; a hand pick is one.
    claimed: dict[int, set[int]] = {}
    for n, rule in enumerate(rules):
        if rule.selector.stream is not None:
            pinned = [t for t in tracks if t.descriptor.index == rule.selector.stream]
            taken = pinned if usable[n] else []
        else:
            found = exact[n]
            taken = found if rule.multiple else found[rule.selector.nth : rule.selector.nth + 1]
        for track in taken:
            claimed.setdefault(track.descriptor.index, set()).add(n)

    picks: list[RulePick] = []
    relaxed_taken: set[int] = set()
    for n, rule in enumerate(rules):
        selector = rule.selector
        if not usable[n]:
            picks.append(RulePick(n, _cell(kind, n, "missing", [], [], (), ""), []))
            continue
        if selector.stream is not None:
            picks.append(_pinned(kind, n, rule, tracks))
            continue
        if selector.languages == []:  # takes no track by design
            message = "the rule takes no track"
            picks.append(RulePick(n, _cell(kind, n, "skipped", [], [], (), message), []))
            continue
        others = {index for index, owners in claimed.items() if owners - {n}}
        chosen: tuple[tuple[str, ...], list[Track]] | None = None
        for dropped, step in relaxation_steps(selector):
            if not dropped:
                found = exact[n]
            else:
                step_title = title_regex(step.title_pattern)
                found = candidates(
                    step,
                    tracks,
                    exclude=others | relaxed_taken,
                    title=step_title if not isinstance(step_title, str) else None,
                )
            if (rule.multiple and found) or len(found) > selector.nth:
                chosen = (dropped, found)
                break
        if chosen is None:
            status: MatchStatus = "missing" if rule.required else "skipped"
            picks.append(RulePick(n, _cell(kind, n, status, [], [], (), ""), []))
            continue
        dropped, found = chosen
        taken = found if rule.multiple else [found[selector.nth]]
        if dropped:
            relaxed_taken.update(t.descriptor.index for t in taken)
        parts: list[str] = []
        if dropped:
            parts.append(f"matched without {_words(dropped)}")
        ambiguous = not rule.multiple and len(found) > selector.nth + 1
        if ambiguous:
            picked = taken[0].descriptor.index
            parts.append(f"{len(found)} candidates, picked #{picked} ({SORT_WORDS[selector.sort]})")
        status = "relaxed" if dropped else ("ambiguous" if ambiguous else "exact")
        picks.append(
            RulePick(n, _cell(kind, n, status, taken, found, dropped, "; ".join(parts)), taken)
        )

    for pick in picks:
        if rules[pick.rule].selector.languages == [] and rules[pick.rule].selector.stream is None:
            continue  # a rule that takes no track: nothing to report
        issue = _cell_issue(pick, labels[pick.rule], list_path)
        if issue is not None:
            issues.append(issue)
    return picks, issues


def _cell(
    kind: Kind,
    rule: int,
    status: MatchStatus,
    taken: Sequence[Track],
    found: Sequence[Track],
    dropped: Sequence[str],
    message: str,
) -> TrackMatch:
    severity: Severity | None = None
    if status in ("relaxed", "ambiguous"):
        severity = Severity.WARNING
    elif status == "missing":
        severity = Severity.ERROR
        message = message or "no track matches"
    elif status == "skipped":
        severity = Severity.INFO
        message = message or "no track matches: skipped (the rule is optional)"
    return TrackMatch(
        kind=kind,
        rule=rule,
        status=status,
        streams=[t.descriptor.index for t in taken],
        candidates=[t.descriptor.index for t in found],
        relaxed=list(dropped),
        severity=severity,
        message=message,
    )


def _pinned(kind: Kind, n: int, rule: OutputTrackRule, tracks: Sequence[Track]) -> RulePick:
    index = rule.selector.stream
    track = next((t for t in tracks if t.descriptor.index == index), None)
    if track is None:
        status: MatchStatus = "missing" if rule.required else "skipped"
        article = "an" if kind == "audio" else "a"
        message = f"the picked track #{index} is not {article} {kind} track of this file"
        return RulePick(n, _cell(kind, n, status, [], [], (), message), [])
    message = f"#{index} picked by hand"
    return RulePick(n, _cell(kind, n, "exact", [track], [track], (), message), [track])


def _cell_issue(pick: RulePick, label: str, list_path: str) -> ValidationIssue | None:
    match = pick.match
    path = f"{list_path}[{pick.rule}]"
    pointer = f"/{list_path}/{pick.rule}/required"
    taken = ", ".join(f"#{index}" for index in match.streams)
    match match.status:
        case "relaxed" | "ambiguous":
            code = "batch.track_relaxed" if match.status == "relaxed" else "batch.track_ambiguous"
            return ValidationIssue(
                severity=Severity.WARNING,
                code=code,
                path=path,
                message=f"Rule {label} took {taken}: {match.message}.",
            )
        case "missing":
            return ValidationIssue(
                severity=Severity.ERROR,
                code="batch.track_missing",
                path=path,
                message=f"No source track matches rule {label}, and the rule is required.",
                fixes=[
                    Fix(
                        label="Make the rule optional (skip it where no track matches)",
                        patch=[ReplaceOp(path=pointer, value=False)],
                        target="template",
                    )
                ],
            )
        case "skipped":
            return ValidationIssue(
                severity=Severity.INFO,
                code="batch.track_skipped",
                path=path,
                message=f"No source track matches rule {label}: it is skipped (optional).",
            )
        case _:
            return None
