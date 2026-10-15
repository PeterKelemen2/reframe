"""What the audio and subtitle defaults do with a source, track by track (05 §C-12
``explain``; 03 §Audio defaults → Live preview, §Subtitles; decision 0031).

One :class:`~reframe.models.TrackDecision` per source track, in source order: the row of the
live preview ``source track → selected? (why) → rule # → output → reason``.

**Audio** (:func:`audio_stage`, :func:`explain`): the selection stage
(:func:`~reframe.batch.selection.select_tracks`), then the codec rules
(:func:`~reframe.batch.apply_codec_rules`, unchanged) for every selected track in the output
order (``first_track_of_language_only`` = the first selected track of its language in that
order), then the default-track setting: ``first_output``, ``first_in_first_language`` (none in
that language: the first output), ``forced`` (the first output from a forced source track,
else none) or ``none``. Only the ``default`` flag is overridden; the other five flags, the
language and the title come from the source track (an undetermined track treated as the first
listed language gets that language). Extra outputs are never the default track. ``no_match =
"none"`` with no listed language found is a ``defaults.no_listed_language`` error.

**Subtitles** (:func:`subtitle_stage`, :func:`explain_subtitles`): the same selection, then

- **foreign audio search** (HandBrake parity, decision 0031): when the audio (the default
  audio output, else the first) is in the first subtitle language (the viewer's language),
  the forced subtitle track in that language is taken, put first and flagged forced. The
  evidence, best first: the forced flag or a ``Forced`` / ``Foreign`` title; every event
  forced (a C-10 scan); a Signs & Songs track; few events (C-3's heuristic: at most 25 % of
  another track's events in the same language); some forced events in a full PGS / VobSub
  track (only when it is burned in, with forced-only).
- **burn-in**: ``foreign_audio`` burns the foreign audio search track, or, when the audio is
  not in the viewer's language, the first selected subtitle in that language (HandBrake's
  "foreign audio subtitle"); ``first`` burns the first subtitle output;
  ``foreign_audio_then_first`` the first of them that exists. At most one track is burned in.
- the default-track policy on the copied tracks: ``none``, ``first_output``, ``forced`` (the
  first copied track flagged forced) or ``first_in_first_language``.

**Keep everything** (decision 0031): a kind with no language set at all keeps every track in
source order with its source flags (at most one default track per kind), as M2 did (decision
0018); for subtitles that means every track copied, no foreign audio search and no burn-in.

Pure: no I/O.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from reframe import languages
from reframe.batch.audio_rules import apply_codec_rules
from reframe.batch.metadata import effective_language, track_metadata
from reframe.batch.selection import (
    KEEP_EVERYTHING,
    Pick,
    Selection,
    is_forced,
    is_undetermined,
    language_label,
    select_tracks,
)
from reframe.definitions import ContainerDef, Definitions, load_definitions
from reframe.models.defaults import (
    AudioDefaults,
    BurnInBehaviour,
    SubtitleDefaults,
    TrackDecision,
)
from reframe.models.issues import Fix, ReplaceOp, Severity, ValidationIssue
from reframe.models.job import AudioOutputTrack, Container, SubtitleOutputTrack, TrackMetadata
from reframe.models.media import (
    AudioStream,
    MediaSource,
    RoleEvidence,
    SubtitleStream,
    TrackRole,
)
from reframe.probe.roles import FORCED_MAX_RATIO

__all__ = [
    "FORCED_ONLY_CODECS",
    "AudioStage",
    "ForeignAudio",
    "SubtitleStage",
    "audio_language",
    "audio_stage",
    "explain",
    "explain_subtitles",
    "forced_evidence",
    "foreign_audio_search",
    "subtitle_stage",
]

#: Subtitle codecs whose FFmpeg decoder has ``forced_subs_only`` (PGS, VobSub; decision 0014).
FORCED_ONLY_CODECS = frozenset({"hdmv_pgs_subtitle", "dvd_subtitle"})


def _with_default[T: (AudioOutputTrack, SubtitleOutputTrack)](track: T, value: bool) -> T:
    if track.metadata.default == value:
        return track
    metadata = track.metadata.model_copy(update={"default": value})
    return track.model_copy(update={"metadata": metadata})


def _track(stream: SubtitleStream) -> str:
    """``#6``: the absolute stream index (as ``reframe plan`` and C-3's role details)."""
    return f"#{stream.index}"


# =========================================================================== audio


@dataclass(frozen=True, slots=True)
class AudioStage:
    """The audio part of a draft."""

    selection: Selection[AudioStream]
    decisions: list[TrackDecision]
    """One per source audio track, in source order."""
    outputs: list[AudioOutputTrack]
    """The output tracks in output order (each track's rule output, then its extra
    outputs)."""
    issues: list[ValidationIssue] = field(default_factory=list)


def _default_audio_position(
    selection: Selection[AudioStream],
    produced: dict[int, list[AudioOutputTrack]],
    policy: str,
) -> int | None:
    """The source position of the track whose rule output is the default audio track."""
    order = [p for p in selection.order if produced.get(p)]
    if not order:
        return None
    if not selection.configured:  # source flags, at most one default track
        return next((p for p in order if selection.picks[p].stream.disposition.default), None)
    match policy:
        case "first_output":
            return order[0]
        case "first_in_first_language":
            return next((p for p in order if selection.picks[p].slot == 0), order[0])
        case "forced":
            return next((p for p in order if is_forced(selection.picks[p].stream)), None)
        case _:
            return None


_DEFAULT_POLICY_WORDS = {
    "first_output": "the first output track",
    "first_in_first_language": "the first track in the first language",
    "forced": "the forced track",
}


def audio_stage(
    defaults: AudioDefaults,
    source: MediaSource,
    *,
    container: Container = "mkv",
    preferred_languages: Sequence[str] = (),
    definitions: Definitions | None = None,
) -> AudioStage:
    """The selection stage, the codec rules and the default track for the audio of
    ``source``. ``preferred_languages``: Settings → preferred audio languages."""
    defs = definitions or load_definitions()
    selection = select_tracks(
        source.audio, defaults.selection, preferred_languages=preferred_languages, kind="audio"
    )
    results: dict[int, tuple[list[AudioOutputTrack], TrackDecision]] = {}
    seen: list[str | None] = []
    for position in selection.order:
        pick = selection.picks[position]
        stream = pick.stream
        notes: list[str] = []
        if pick.relabelled:
            stream = stream.model_copy(update={"language": pick.language, "language_ietf": None})
            notes.append(
                f"Undetermined language: treated and written as {language_label(pick.language)}"
                ", the first listed language"
            )
        first = not any(languages.same_language(pick.language, other) for other in seen)
        if first:
            seen.append(pick.language)
        outputs, decision = apply_codec_rules(
            stream, defaults, container, definitions=defs, first_of_language=first
        )
        decision = decision.model_copy(
            update={"selection": pick.why, "notes": [*notes, *decision.notes]}
        )
        results[position] = (outputs, decision)

    produced = {p: outputs for p, (outputs, _) in results.items()}
    policy = defaults.selection.default_track
    chosen = _default_audio_position(selection, produced, policy)
    ordered: list[AudioOutputTrack] = []
    by_position: dict[int, TrackDecision] = {}
    for position in selection.order:
        outputs, decision = results[position]
        fixed = [
            _with_default(track, index == 0 and position == chosen)
            for index, track in enumerate(outputs)
        ]
        notes = decision.notes
        if selection.configured and position == chosen:
            notes = [*notes, f"The default audio track ({_DEFAULT_POLICY_WORDS[policy]})"]
        by_position[position] = decision.model_copy(update={"outputs": fixed, "notes": notes})
        ordered.extend(fixed)

    decisions = [
        by_position.get(position) or _dropped(pick, "audio")
        for position, pick in enumerate(selection.picks)
    ]
    issues: list[ValidationIssue] = []
    if selection.no_listed_language and defaults.selection.no_match == "none":
        issues.append(_no_listed_language(selection))
    return AudioStage(selection, decisions, ordered, issues)


def _dropped(
    pick: Pick[AudioStream] | Pick[SubtitleStream], kind: Literal["audio", "subtitle"]
) -> TrackDecision:
    """A track the selection did not take: no output, and the reason is why."""
    return TrackDecision(
        source_stream=pick.stream.index,
        kind=kind,
        selected=False,
        selection=pick.why,
        reason=pick.why,
    )


def _no_listed_language(selection: Selection[AudioStream]) -> ValidationIssue:
    names = " or ".join(language_label(tag) for tag in selection.languages)
    pointer = "/audio_defaults/selection/no_match"
    return ValidationIssue(
        severity=Severity.ERROR,
        code="defaults.no_listed_language",
        path="audio_defaults.selection.no_match",
        message=(
            f"This source has no audio track in {names}, and the audio defaults take no track "
            "when no listed language is found."
        ),
        fixes=[
            Fix(
                label="Take the default-flagged track",
                patch=[ReplaceOp(path=pointer, value="default_flagged")],
                target="template",
            ),
            Fix(
                label="Take the first track",
                patch=[ReplaceOp(path=pointer, value="first_track")],
                target="template",
            ),
        ],
    )


def explain(
    defaults: AudioDefaults,
    source: MediaSource,
    *,
    container: Container = "mkv",
    preferred_languages: Sequence[str] = (),
    definitions: Definitions | None = None,
) -> list[TrackDecision]:
    """One decision per source audio track, in source order: selected or not and why
    (``selection``), the codec rule, the output(s) with their flags, and the reason
    (03 §Audio defaults → Live preview). ``preferred_languages``: Settings → preferred audio
    languages (used when ``defaults.selection.languages`` is empty)."""
    return audio_stage(
        defaults,
        source,
        container=container,
        preferred_languages=preferred_languages,
        definitions=definitions,
    ).decisions


# =========================================================================== subtitles


@dataclass(frozen=True, slots=True)
class ForeignAudio:
    """The outcome of the foreign audio search (HandBrake parity, decision 0031)."""

    audio_language: str | None
    user_language: str | None
    searched: bool
    """The audio is in the viewer's language, so there is something to search for."""
    track: int | None = None
    """The position (in ``source.subtitles``) of the forced track found."""
    evidence: str | None = None
    forced_only: bool = False
    """Only the forced events of a full PGS / VobSub track: usable only burned in."""
    note: str = ""
    """One line for the preview."""


def forced_evidence(
    stream: SubtitleStream, peers: Sequence[SubtitleStream]
) -> tuple[int, str] | None:
    """Why ``stream`` looks like the forced subtitles of its language, as ``(rank, words)``
    (0 is the strongest), or ``None``. ``peers``: the other subtitle tracks in the same
    language (for the event counts).

    0. The forced flag, or C-3's ``forced`` role from a flag or a title (``Forced``,
       ``Foreign``).
    1. Every event is forced (``forced_event_count`` of a C-10 scan).
    2. A Signs & Songs track (title).
    3. Few events: C-3's heuristic role, or at most 25 % of the events of another track in
       the same language (``reframe.probe.roles.FORCED_MAX_RATIO``; counts measured later
       are compared here too).
    4. Some forced events in a full PGS or VobSub track: usable only burned in, with
       forced-only (``forced_subs_only``).
    """
    if stream.disposition.forced:
        return 0, "forced flag"
    for info in stream.roles:
        if info.role is TrackRole.FORCED and info.evidence is not RoleEvidence.HEURISTIC:
            return 0, info.detail or "forced"
    count, forced = stream.event_count, stream.forced_event_count
    if count and forced is not None and forced >= count:
        return 1, f"all {count} events are forced"
    for info in stream.roles:
        if info.role is TrackRole.SIGNS:
            return 2, f"Signs & Songs, {info.detail or info.evidence}"
    for info in stream.roles:
        if info.role is TrackRole.FORCED:
            return 3, info.detail or "few events"
    counted = [p for p in peers if p.event_count]
    if count is not None and counted:
        biggest = max(counted, key=lambda p: p.event_count or 0)
        top = biggest.event_count or 0
        if count <= FORCED_MAX_RATIO * top:
            return 3, (
                f"{count} events, {round(100 * count / top)} % of the {top} events of "
                f"track #{biggest.index}"
            )
    if forced and stream.codec in FORCED_ONLY_CODECS:
        return 4, f"{forced} forced events in a full track"
    return None


def foreign_audio_search(
    subtitles: Sequence[SubtitleStream],
    *,
    audio_language: str | None,
    user_language: str | None,
    can_burn: bool,
) -> ForeignAudio:
    """HandBrake's "Foreign Audio Search" without a scan pass: when the audio is in the
    viewer's language (``user_language``, the first subtitle language), find the subtitle
    track in that language that translates the foreign parts (:func:`forced_evidence`; ties
    in source order). ``can_burn``: the burn-in behaviour would burn it (rank 4 needs it)."""
    if is_undetermined(audio_language) or user_language is None:
        return ForeignAudio(
            audio_language, user_language, False, note="Foreign audio search: no audio language"
        )
    audio_name = language_label(audio_language)
    if not languages.same_language(audio_language, user_language):
        return ForeignAudio(
            audio_language,
            user_language,
            False,
            note=(
                f"Foreign audio search: not run, the audio is {audio_name} and the first "
                f"subtitle language is {language_label(user_language)}"
            ),
        )
    same = [
        (position, stream)
        for position, stream in enumerate(subtitles)
        if languages.same_language(effective_language(stream), audio_language)
    ]
    ranked: list[tuple[int, int, str]] = []
    for position, stream in same:
        peers = [other for p, other in same if p != position]
        found = forced_evidence(stream, peers)
        if found is not None and not _is_commentary(stream):
            ranked.append((found[0], position, found[1]))
    ranked.sort()
    usable = [entry for entry in ranked if entry[0] < 4 or can_burn]
    if not usable:
        if ranked:
            _, position, words = ranked[0]
            note = (
                f"Foreign audio search: {_track(subtitles[position])} has {words}, but only "
                "a burned-in track can show just them (burn-in: none)"
            )
        else:
            note = (
                f"Foreign audio search: no forced {audio_name} subtitle track (no forced flag "
                "or title, and no low event count)"
            )
        return ForeignAudio(audio_language, user_language, True, note=note)
    rank, position, words = usable[0]
    return ForeignAudio(
        audio_language,
        user_language,
        True,
        track=position,
        evidence=words,
        forced_only=rank == 4,
        note=(
            f"Foreign audio search: {_track(subtitles[position])} is the forced {audio_name} track "
            f"({words}) for the {audio_name} audio"
        ),
    )


def _is_commentary(stream: SubtitleStream) -> bool:
    return stream.disposition.comment or any(
        info.role in (TrackRole.COMMENTARY, TrackRole.DESCRIPTION) for info in stream.roles
    )


def audio_language(audio: Sequence[AudioOutputTrack], source: MediaSource) -> str | None:
    """The language the viewer hears: the default audio output (else the first); without
    outputs, the source's default-flagged audio track (else the first)."""
    by_index = {stream.index: stream for stream in source.audio}
    if audio:
        main = next((t for t in audio if t.metadata.default), audio[0])
        if main.metadata.language is not None:
            return languages.normalize(main.metadata.language) or main.metadata.language
        stream = by_index.get(main.source_stream) if main.source_stream is not None else None
        return effective_language(stream) if stream is not None else None
    if not source.audio:
        return None
    stream = next((s for s in source.audio if s.disposition.default), source.audio[0])
    return effective_language(stream)


@dataclass(frozen=True, slots=True)
class SubtitleStage:
    """The subtitle part of a draft."""

    selection: Selection[SubtitleStream]
    decisions: list[TrackDecision]
    """One per source subtitle track, in source order."""
    outputs: list[SubtitleOutputTrack]
    """In output order (the foreign audio search track first)."""
    foreign_audio: ForeignAudio | None = None
    issues: list[ValidationIssue] = field(default_factory=list)


def _container_notes(stream: SubtitleStream, container: ContainerDef | None) -> list[str]:
    """What the container does with a copied track (03 §Subtitles; the builder converts and
    validation reports, this only says so)."""
    if container is None or stream.codec is None or container.subtitles.can_copy(stream.codec):
        return []
    shown = stream.display_codec or stream.codec
    if stream.subtitle_kind == "text" and container.text_subtitle_target is not None:
        return [f"{container.label}: converted to {container.text_subtitle_target}"]
    return [
        f"{container.label} cannot hold {shown} subtitles: validation offers burn-in or "
        "another container"
    ]


def _burn_target(
    behaviour: BurnInBehaviour,
    order: Sequence[int],
    selection: Selection[SubtitleStream],
    foreign: ForeignAudio | None,
    heard: str | None,
) -> tuple[int, str] | None:
    """The position of the track to burn in, and why."""
    if behaviour in ("foreign_audio", "foreign_audio_then_first"):
        if foreign is not None and foreign.track is not None:
            return foreign.track, "foreign audio search"
        viewer = selection.languages[0]
        if not is_undetermined(heard) and not languages.same_language(heard, viewer):
            for position in order:
                if selection.picks[position].slot == 0:
                    return position, (
                        f"foreign audio: the {language_label(viewer)} subtitles for the "
                        f"{language_label(heard)} audio"
                    )
    if behaviour in ("first", "foreign_audio_then_first") and order:
        return order[0], "the first subtitle track"
    return None


def _default_subtitle_position(
    policy: str,
    copies: Sequence[int],
    selection: Selection[SubtitleStream],
    metadata: dict[int, TrackMetadata],
) -> int | None:
    if not copies:
        return None
    match policy:
        case "first_output":
            return copies[0]
        case "forced":
            return next((p for p in copies if metadata[p].forced), None)
        case "first_in_first_language":
            first = selection.languages[0]
            return next(
                (p for p in copies if languages.matches(first, metadata[p].language)), copies[0]
            )
        case _:
            return None


def subtitle_stage(
    defaults: SubtitleDefaults,
    source: MediaSource,
    *,
    container: Container = "mkv",
    preferred_languages: Sequence[str] = (),
    audio: Sequence[AudioOutputTrack] = (),
    definitions: Definitions | None = None,
) -> SubtitleStage:
    """The selection, the foreign audio search, the burn-in and the default track for the
    subtitles of ``source``. ``audio``: the drafted audio outputs (the foreign audio search
    needs the language the viewer hears; without them, the source's default audio track)."""
    defs = definitions or load_definitions()
    holder = defs.containers.get(container)
    streams = source.subtitles
    selection = select_tracks(
        streams, defaults.selection, preferred_languages=preferred_languages, kind="subtitle"
    )
    if not selection.configured:
        return _keep_every_subtitle(selection, holder)

    heard = audio_language(audio, source)
    foreign: ForeignAudio | None = None
    if defaults.foreign_audio_search:
        foreign = foreign_audio_search(
            streams,
            audio_language=heard,
            user_language=selection.languages[0],
            can_burn=defaults.burn_in != "none",
        )
    order = list(selection.order)
    fas = foreign.track if foreign is not None else None
    if fas is not None:
        order = [fas, *(p for p in order if p != fas)]
    burn = _burn_target(defaults.burn_in, order, selection, foreign, heard)

    metadata: dict[int, TrackMetadata] = {}
    for position in order:
        pick = selection.picks[position]
        meta = track_metadata(pick.stream)
        if pick.selected and pick.relabelled:
            meta = meta.model_copy(update={"language": pick.language})
        if position == fas:
            meta = meta.model_copy(update={"forced": True})
        metadata[position] = meta
    burned = burn[0] if burn is not None else None
    copies = [p for p in order if p != burned]
    policy = defaults.selection.default_track
    chosen = _default_subtitle_position(policy, copies, selection, metadata)

    outputs: list[SubtitleOutputTrack] = []
    by_position: dict[int, TrackDecision] = {}
    for position in order:
        pick = selection.picks[position]
        stream = pick.stream
        meta = metadata[position].model_copy(update={"default": position == chosen})
        notes: list[str] = []
        if pick.selected and pick.relabelled:
            notes.append(
                f"Undetermined language: treated and written as {language_label(pick.language)}"
                ", the first listed language"
            )
        if position == burned:
            assert burn is not None
            forced_only = position == fas and foreign is not None and foreign.forced_only
            track = SubtitleOutputTrack(
                source=stream.index, action="burn", forced_only=forced_only, metadata=meta
            )
            reason = f"Burn in ({burn[1]}{', forced events only' if forced_only else ''})"
        else:
            track = SubtitleOutputTrack(source=stream.index, action="copy", metadata=meta)
            reason = "Copy"
            if position == fas:
                reason += ", flagged forced (foreign audio search)"
            if position == chosen:
                reason += f", the default subtitle track ({_DEFAULT_POLICY_WORDS[policy]})"
            notes.extend(_container_notes(stream, holder))
        why = pick.why if pick.selected else None
        if position == fas:
            assert foreign is not None
            why = f"{why}; {foreign.note}" if why else foreign.note
        by_position[position] = TrackDecision(
            source_stream=stream.index,
            kind="subtitle",
            selected=True,
            selection=why,
            subtitle_outputs=[track],
            reason=reason,
            notes=notes,
        )
        outputs.append(track)

    decisions: list[TrackDecision] = []
    for position, pick in enumerate(selection.picks):
        decision = by_position.get(position) or _dropped(pick, "subtitle")
        if (
            foreign is not None
            and fas is None
            and languages.same_language(effective_language(pick.stream), heard)
        ):
            # Why the search found nothing, on the tracks it looked at.
            decision = decision.model_copy(update={"notes": [*decision.notes, foreign.note]})
        decisions.append(decision)
    return SubtitleStage(selection, decisions, outputs, foreign)


def _keep_every_subtitle(
    selection: Selection[SubtitleStream], holder: ContainerDef | None
) -> SubtitleStage:
    """Every subtitle copied with its source flags (at most one default), as M2 did."""
    picks = selection.picks
    chosen = next((p for p, pick in enumerate(picks) if pick.stream.disposition.default), None)
    outputs: list[SubtitleOutputTrack] = []
    decisions: list[TrackDecision] = []
    for position, pick in enumerate(picks):
        meta = track_metadata(pick.stream).model_copy(update={"default": position == chosen})
        track = SubtitleOutputTrack(source=pick.stream.index, action="copy", metadata=meta)
        outputs.append(track)
        decisions.append(
            TrackDecision(
                source_stream=pick.stream.index,
                kind="subtitle",
                selected=True,
                selection=KEEP_EVERYTHING["subtitle"],
                subtitle_outputs=[track],
                reason="Copy",
                notes=_container_notes(pick.stream, holder),
            )
        )
    return SubtitleStage(selection, decisions, outputs)


def explain_subtitles(
    defaults: SubtitleDefaults,
    source: MediaSource,
    *,
    container: Container = "mkv",
    preferred_languages: Sequence[str] = (),
    audio: Sequence[AudioOutputTrack] = (),
    definitions: Definitions | None = None,
) -> list[TrackDecision]:
    """One decision per source subtitle track, in source order (``kind="subtitle"``): selected
    or not and why, and the output (copy or burn-in, with its flags) with the reason.
    ``preferred_languages``: Settings → preferred subtitle languages. ``audio``: the drafted
    audio outputs, for the foreign audio search (without them: the source's default audio
    track)."""
    return subtitle_stage(
        defaults,
        source,
        container=container,
        preferred_languages=preferred_languages,
        audio=audio,
        definitions=definitions,
    ).decisions
