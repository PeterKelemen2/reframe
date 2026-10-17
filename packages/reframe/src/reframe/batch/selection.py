"""The selection stage of the audio and subtitle defaults: which source tracks a preset takes,
why, and in which order (03 §Audio defaults part 1, §Subtitles "Subtitle defaults"; 05 §C-12;
decision 0031).

:func:`select_tracks` applies one :class:`~reframe.models.TrackSelection` to the audio or the
subtitle tracks of a source, setting by setting:

=================================  ==========================================================
Setting                            What it does here
=================================  ==========================================================
``languages``                      The ordered list (``None`` or empty: the preferred
                                   languages of Settings). A track belongs to the first listed
                                   language that :func:`reframe.languages.matches` it: rule
                                   ``pt`` takes ``pt-BR`` and ``por``; ``pt-BR`` takes only
                                   ``pt-BR``; ``ger`` = ``de``.
``undetermined``                   A track without a language (or ``und``): the first listed
                                   language (it is then treated, encoded and written as that
                                   language), or an other language.
``tracks_per_language``            None, the first (after the tie-break), or all of them.
``tie_break``                      :func:`sort_key`. Audio "best quality": lossless first,
                                   then the highest known bit rate; an unknown bit rate after
                                   every known one; then more channels, then source order.
                                   Subtitles: full subtitles before SDH before forced and
                                   Signs & Songs, then source order.
``other_languages``                Main tracks in no listed language: drop, keep the best
                                   track of the first such language (source order), or keep
                                   all of them.
``no_match``                       No main track in any listed language (a listed-language
                                   extra track does not count): the default-flagged main track
                                   (none flagged: the first), the first main track, or none
                                   (for audio a validation error when no main track is taken,
                                   ``reframe.batch.explain``).
``commentary``                     Commentary, audio description and music-only tracks
                                   (:func:`extra_role`): dropped, or kept after the main tracks
                                   when their language is taken (a listed language, or any
                                   language when other languages are kept).
``order``                          Language list order (each language in tie-break order,
                                   then the no-match track, then other languages in source
                                   order), or source order; the extra tracks always come last.
=================================  ==========================================================

``default_track`` is applied to the outputs by ``reframe.batch.explain``, which runs the codec
rules (audio) and the foreign audio search and burn-in (subtitles) on the selection.

**Keep everything** (decision 0031, after decision 0018): when no language is set at all
(``languages`` is ``None`` or empty and Settings has no preferred languages of that kind), the
selection takes every track in source order and ignores the other settings, as M2 did.

The functions here are the building blocks the batch engine (C-12, M7) reuses when it compiles
the defaults into track rules. Pure: no I/O.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from reframe import languages
from reframe.batch.metadata import effective_language
from reframe.models.defaults import TrackSelection
from reframe.models.media import AudioStream, SubtitleStream, TrackRole

__all__ = [
    "KEEP_EVERYTHING",
    "Pick",
    "PickGroup",
    "Selection",
    "TrackKind",
    "effective_languages",
    "extra_role",
    "is_forced",
    "is_undetermined",
    "language_label",
    "language_slot",
    "select_tracks",
    "sort_key",
    "subtitle_rank",
]

TrackKind = Literal["audio", "subtitle"]
#: Why a selected track was taken: every track (no language set), a listed language, the
#: no-match rule, an other language, or an extra track (commentary, description, music).
PickGroup = Literal["all", "language", "no_match", "other", "extra"]

#: The one line every track gets when no language is set (decision 0031).
KEEP_EVERYTHING: dict[TrackKind, str] = {
    "audio": "No audio languages set (preset or Settings): every track is kept, in source order",
    "subtitle": (
        "No subtitle languages set (preset or Settings): every subtitle is copied, in source order"
    ),
}

#: Extra tracks (03: "Commentary and audio description"; music-only too, decision 0031).
_EXTRA_ROLES: dict[TrackKind, dict[TrackRole, str]] = {
    "audio": {
        TrackRole.COMMENTARY: "Commentary",
        TrackRole.DESCRIPTION: "Audio description",
        TrackRole.MUSIC: "Music only",
    },
    "subtitle": {
        TrackRole.COMMENTARY: "Commentary",
        TrackRole.DESCRIPTION: "Descriptions",
    },
}

_TIE_BREAK_WORDS = {
    "source_order": "source order",
    "most_channels": "most channels",
    "best_quality": "best quality",
}


# --------------------------------------------------------------------------- results


@dataclass(frozen=True, slots=True)
class Pick[S: (AudioStream, SubtitleStream)]:
    """What the selection did with one source track."""

    stream: S
    selected: bool
    why: str
    """One line: ``Hungarian: the first of 2 matching tracks (best quality)``,
    ``Commentary (disposition comment): dropped``."""
    group: PickGroup | None = None
    """Why it was taken; ``None`` for a dropped track."""
    slot: int | None = None
    """The index of the listed language the track counts as (``None``: no listed language)."""
    language: str | None = None
    """The language the track counts as: the first listed language for an undetermined track
    treated as it, else the track's own (:func:`~reframe.batch.effective_language`)."""

    @property
    def relabelled(self) -> bool:
        """An undetermined track that is treated as the first listed language."""
        own = effective_language(self.stream)
        return is_undetermined(own) and not is_undetermined(self.language)


@dataclass(frozen=True, slots=True)
class Selection[S: (AudioStream, SubtitleStream)]:
    """The selection of one kind of track."""

    kind: TrackKind
    configured: bool
    """``False``: no language set, every track kept in source order (decision 0031)."""
    languages: tuple[str, ...]
    """The effective languages, canonical BCP 47, in order (empty when not configured)."""
    picks: tuple[Pick[S], ...]
    """One per source track, in source order."""
    order: tuple[int, ...]
    """Positions (in :attr:`picks`) of the selected tracks, in output order."""
    no_listed_language: bool = False
    """Configured, the source has main tracks of this kind, and none of them is in a listed
    language (03 "No listed language found"). Extra tracks (commentary, description, music
    only) do not count, whatever their language (decision 0031 §3)."""

    @property
    def selected(self) -> list[Pick[S]]:
        """The selected tracks in output order."""
        return [self.picks[position] for position in self.order]


# --------------------------------------------------------------------------- helpers


def effective_languages(
    selection_languages: Sequence[str] | None, preferred: Sequence[str] = ()
) -> tuple[str, ...]:
    """The selection's languages, or the preferred languages of Settings when it has none
    (``None`` or empty); canonical BCP 47 (``hun`` → ``hu``), duplicates removed, in order."""
    found: list[str] = []
    for tag in selection_languages or preferred:
        canonical = languages.normalize(tag) or tag
        if canonical not in found:
            found.append(canonical)
    return tuple(found)


def is_undetermined(language: str | None) -> bool:
    """No language, ``und``, or a tag that is not a language."""
    return language is None or languages.base_language(language) == languages.UNDETERMINED


def language_slot(
    language: str | None,
    listed: Sequence[str],
    undetermined: Literal["first_language", "other"] = "other",
) -> int | None:
    """The index of the first listed language that matches ``language``
    (:func:`reframe.languages.matches`), else ``0`` for an undetermined track treated as the
    first language, else ``None`` (an other language). A listed ``und`` matches undetermined
    tracks whatever ``undetermined`` says."""
    for index, tag in enumerate(listed):
        if languages.matches(tag, language):
            return index
    if listed and undetermined == "first_language" and is_undetermined(language):
        return 0
    return None


def language_label(language: str | None) -> str:
    """``Hungarian``, ``Portuguese (Brazil)``, ``Undetermined``."""
    return languages.english_name(language)


def _has_role(stream: AudioStream | SubtitleStream, role: TrackRole) -> bool:
    return any(info.role is role for info in stream.roles)


def extra_role(stream: AudioStream | SubtitleStream) -> tuple[TrackRole, str] | None:
    """The role that makes a track an **extra** track, with its evidence: commentary, audio
    description or music only (audio), commentary or descriptions (subtitles). From C-3's
    roles (``disposition comment``, ``title contains "Commentary"``, a heuristic), else from
    the disposition flags alone (a source built without the prober)."""
    kind: TrackKind = "audio" if isinstance(stream, AudioStream) else "subtitle"
    extras = _EXTRA_ROLES[kind]
    for info in stream.roles:
        if info.role in extras:
            return info.role, info.detail or str(info.evidence)
    d = stream.disposition
    if d.comment:
        return TrackRole.COMMENTARY, "disposition comment"
    if kind == "audio" and d.visual_impaired:
        return TrackRole.DESCRIPTION, "disposition visual_impaired"
    if d.descriptions:
        return TrackRole.DESCRIPTION, "disposition descriptions"
    if kind == "audio" and d.clean_effects:
        return TrackRole.MUSIC, "disposition clean_effects"
    return None


def _extra_label(stream: AudioStream | SubtitleStream, found: tuple[TrackRole, str]) -> str:
    kind: TrackKind = "audio" if isinstance(stream, AudioStream) else "subtitle"
    role, evidence = found
    return f"{_EXTRA_ROLES[kind][role]} ({evidence})"


def is_forced(stream: AudioStream | SubtitleStream) -> bool:
    """The forced flag, or C-3's ``forced`` role (flag, title or heuristic)."""
    return stream.disposition.forced or _has_role(stream, TrackRole.FORCED)


def subtitle_rank(stream: SubtitleStream) -> int:
    """Subtitles' "best" order: 0 full subtitles, 1 SDH, 2 forced or Signs & Songs."""
    if is_forced(stream) or _has_role(stream, TrackRole.SIGNS):
        return 2
    d = stream.disposition
    if _has_role(stream, TrackRole.SDH) or d.hearing_impaired or d.captions:
        return 1
    return 0


def sort_key(
    stream: AudioStream | SubtitleStream,
    position: int,
    tie_break: Literal["source_order", "most_channels", "best_quality"],
) -> tuple[int, ...]:
    """The tie-break order of the tracks of one language (smallest first).

    Audio: ``source_order``; ``most_channels`` (then source order); ``best_quality``:
    lossless first, then the highest known bit rate (an unknown bit rate after every known
    one: the preview offers **Measure**), then more channels, then source order.
    Subtitles: ``source_order``; the other two put full subtitles first, then SDH, then
    forced and Signs & Songs (:func:`subtitle_rank`), then source order.
    """
    if tie_break == "source_order":
        return (position,)
    if isinstance(stream, SubtitleStream):
        return (subtitle_rank(stream), position)
    if tie_break == "most_channels":
        return (-stream.channels, position)
    bitrate = stream.bitrate.value
    return (
        0 if stream.lossless else 1,
        0 if bitrate is not None else 1,
        -(bitrate or 0),
        -stream.channels,
        position,
    )


def _track(stream: AudioStream | SubtitleStream) -> str:
    """``#3``: the absolute stream index, as ``reframe plan`` and C-3's role details show
    it."""
    return f"#{stream.index}"


# --------------------------------------------------------------------------- the stage


@dataclass(slots=True)
class _State[S: (AudioStream, SubtitleStream)]:
    streams: Sequence[S]
    picks: dict[int, Pick[S]]

    def take(
        self, position: int, why: str, group: PickGroup, slot: int | None, language: str | None
    ) -> None:
        self.picks[position] = Pick(self.streams[position], True, why, group, slot, language)

    def drop(self, position: int, why: str) -> None:
        self.picks[position] = Pick(self.streams[position], False, why)


def select_tracks[S: (AudioStream, SubtitleStream)](
    streams: Sequence[S],
    selection: TrackSelection,
    *,
    preferred_languages: Sequence[str] = (),
    kind: TrackKind | None = None,
) -> Selection[S]:
    """Apply ``selection`` to ``streams`` (all audio or all subtitle tracks of one source, in
    source order). ``preferred_languages``: Settings → Languages, preferred audio or subtitle
    languages, used when the selection has no languages. ``kind``: for an empty ``streams``
    (else taken from the streams). Every track gets one :class:`Pick`."""
    if kind is None:
        kind = "subtitle" if streams and isinstance(streams[0], SubtitleStream) else "audio"
    listed = effective_languages(selection.languages, preferred_languages)
    if not listed:
        picks = tuple(
            Pick(stream, True, KEEP_EVERYTHING[kind], "all", None, effective_language(stream))
            for stream in streams
        )
        return Selection(kind, False, (), picks, tuple(range(len(streams))))

    state: _State[S] = _State(streams, {})
    names = ", ".join(language_label(tag) for tag in listed)
    tie = _TIE_BREAK_WORDS[selection.tie_break]
    slots = [
        language_slot(effective_language(stream), listed, selection.undetermined)
        for stream in streams
    ]
    extras = {p: found for p, s in enumerate(streams) if (found := extra_role(s)) is not None}
    main = [p for p in range(len(streams)) if p not in extras]

    def key(position: int) -> tuple[int, ...]:
        return sort_key(streams[position], position, selection.tie_break)

    def counts_as(position: int) -> str | None:
        slot = slots[position]
        return listed[slot] if slot is not None else effective_language(streams[position])

    def name_of(position: int) -> str:
        slot = slots[position]
        own = effective_language(streams[position])
        if slot is None:
            return language_label(own)
        if is_undetermined(own) and not languages.matches(listed[slot], own):
            return f"Undetermined (treated as {language_label(listed[slot])})"
        return language_label(listed[slot])

    # 1. The listed languages, in order.
    by_language: list[list[int]] = [
        sorted((p for p in main if slots[p] == slot), key=key) for slot in range(len(listed))
    ]
    taken_by_language: list[int] = []
    for slot, candidates in enumerate(by_language):
        if not candidates:
            continue
        match selection.tracks_per_language:
            case "none":
                for p in candidates:
                    state.drop(p, f"{name_of(p)}: tracks per language is None: dropped")
            case "first":
                first, *rest = candidates
                how = (
                    "the first matching track"
                    if not rest
                    else f"the first of {len(candidates)} matching tracks ({tie})"
                )
                state.take(first, f"{name_of(first)}: {how}", "language", slot, listed[slot])
                taken_by_language.append(first)
                for p in rest:
                    state.drop(
                        p,
                        f"{name_of(p)}: not the first matching track ({tie} takes "
                        f"{_track(streams[first])}): dropped",
                    )
            case "all":
                for p in candidates:
                    state.take(
                        p, f"{name_of(p)}: all matching tracks", "language", slot, listed[slot]
                    )
                    taken_by_language.append(p)

    # 2. No listed language found: no **main** track is in a listed language (a commentary or
    # description in a listed language does not count: it is not the programme's own track).
    no_listed = bool(main) and all(slots[p] is None for p in main)
    no_match_taken: int | None = None
    if no_listed:
        head = f"No listed language found ({names})"
        match selection.no_match:
            case "default_flagged":
                flagged = [p for p in main if streams[p].disposition.default]
                if flagged:
                    no_match_taken = flagged[0]
                    why = f"{head}: the default-flagged track"
                else:
                    no_match_taken = main[0]
                    why = f"{head}: the first track (no track is default-flagged)"
                state.take(no_match_taken, why, "no_match", None, counts_as(no_match_taken))
            case "first_track":
                no_match_taken = main[0]
                state.take(
                    no_match_taken, f"{head}: the first track", "no_match", None,
                    counts_as(no_match_taken),
                )  # fmt: skip
            case "none":
                pass

    # 3. Other languages (main tracks in no listed language).
    others = [p for p in main if slots[p] is None and p != no_match_taken]
    taken_others: list[int] = []
    not_listed = "is not a listed language"
    match selection.other_languages:
        case "drop":
            take_none = no_listed and selection.no_match == "none"
            tail = " (no listed language found: take none)" if take_none else ""
            for p in others:
                state.drop(p, f"{name_of(p)} {not_listed}: dropped{tail}")
        case "keep_first":
            if no_match_taken is not None:
                for p in others:
                    state.drop(
                        p,
                        f"{name_of(p)} {not_listed}: dropped (other languages: keep the first "
                        f"track; {_track(streams[no_match_taken])} is kept)",
                    )
            elif others:
                first_language = effective_language(streams[others[0]])
                same = sorted(
                    (
                        p
                        for p in others
                        if languages.same_language(effective_language(streams[p]), first_language)
                    ),
                    key=key,
                )
                kept = same[0]
                state.take(
                    kept,
                    f"{name_of(kept)} {not_listed}: kept (other languages: keep the first track)",
                    "other",
                    None,
                    counts_as(kept),
                )
                taken_others.append(kept)
                for p in others:
                    if p != kept:
                        state.drop(
                            p,
                            f"{name_of(p)} {not_listed}: dropped (other languages: keep the "
                            f"first track; {_track(streams[kept])} is kept)",
                        )
        case "keep_all":
            for p in others:
                state.take(
                    p,
                    f"{name_of(p)} {not_listed}: kept (other languages: keep all)",
                    "other",
                    None,
                    counts_as(p),
                )
                taken_others.append(p)

    # 4. Commentary, audio description, music only.
    taken_extras: list[int] = []
    for p, found in extras.items():
        label = _extra_label(streams[p], found)
        if selection.commentary == "drop":
            state.drop(p, f"{label}: dropped")
        elif slots[p] is not None or selection.other_languages != "drop":
            state.take(p, f"{label}: kept after the main tracks", "extra", slots[p], counts_as(p))
            taken_extras.append(p)
        else:
            state.drop(p, f"{label}: {name_of(p)} {not_listed}: dropped")

    # 5. The output order.
    main_order: list[int]
    extra_order: list[int]
    if selection.order == "language_list":
        main_order = [*taken_by_language, *_maybe(no_match_taken), *sorted(taken_others)]
        extra_order = sorted(
            taken_extras,
            key=lambda p: (slots[p] if slots[p] is not None else len(listed), p),
        )
    else:
        main_order = sorted([*taken_by_language, *taken_others, *_maybe(no_match_taken)])
        extra_order = sorted(taken_extras)

    picks = tuple(state.picks[p] for p in range(len(streams)))
    return Selection(
        kind,
        True,
        listed,
        picks,
        (*main_order, *extra_order),
        no_listed_language=no_listed,
    )


def _maybe(value: int | None) -> list[int]:
    return [] if value is None else [value]
