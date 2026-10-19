"""Track roles from evidence: disposition flags, then title keywords, then a structural heuristic.

A role is given once, by the strongest evidence that finds it. An audio or subtitle track without
any role gets ``main``. Languages are compared case-insensitively; ``und`` and a missing tag never
match. It must not import :mod:`reframe.languages`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from reframe.models.media import (
    AudioStream,
    Disposition,
    RoleEvidence,
    SubtitleStream,
    TrackRole,
    TrackRoleInfo,
)

__all__ = [
    "AUDIO_KEYWORDS",
    "COMMENTARY_MAX_BITRATE",
    "FORCED_MAX_RATIO",
    "SUBTITLE_KEYWORDS",
    "assign_audio_roles",
    "assign_subtitle_roles",
    "audio_flag_roles",
    "subtitle_flag_roles",
    "title_roles",
]

#: Highest bit rate (bits/s) of a "low bitrate" 2.0 track for the commentary heuristic.
COMMENTARY_MAX_BITRATE = 192_000
#: A subtitle track with at most this share of the events of another track in the same
#: language is a possible forced track.
FORCED_MAX_RATIO = 0.25


@dataclass(frozen=True)
class Keyword:
    """One title keyword. ``text`` may have spaces (they match spaces, ``-``, ``_`` or ``.``)."""

    text: str
    role: TrackRole
    case_sensitive: bool = False
    substring: bool = False
    """Match anywhere (Japanese, which has no spaces between words; German compounds)."""
    not_after: tuple[str, ...] = ()
    """No match right after one of these prefixes."""

    def pattern(self) -> re.Pattern[str]:
        body = r"[\s_.\-]+".join(re.escape(word) for word in self.text.split())
        if not self.substring:
            body = rf"(?<!\w){body}(?!\w)"
        guards = "".join(f"(?<!{re.escape(prefix)})" for prefix in self.not_after)
        return re.compile(guards + body, 0 if self.case_sensitive else re.IGNORECASE)


_COMMENTARY = [
    Keyword(word, TrackRole.COMMENTARY)
    for word in (
        "commentary",
        "commentaries",
        "commentaire",
        "comentario",
        "commento",
        "kommentár",
    )
] + [
    Keyword("kommentar", TrackRole.COMMENTARY, substring=True),
    Keyword("コメンタリー", TrackRole.COMMENTARY, substring=True),
]
_NOT_FORCED = ("non", "non-", "non ", "not ", "not-")

#: Title keywords for audio tracks.
AUDIO_KEYWORDS: Sequence[Keyword] = (
    *_COMMENTARY,
    Keyword("audio description", TrackRole.DESCRIPTION),
    Keyword("descriptive", TrackRole.DESCRIPTION),
    Keyword("described", TrackRole.DESCRIPTION),
    Keyword("deskription", TrackRole.DESCRIPTION, substring=True),
    Keyword("hörfilm", TrackRole.DESCRIPTION, substring=True),
    Keyword("AD", TrackRole.DESCRIPTION, case_sensitive=True),
    Keyword("music only", TrackRole.MUSIC),
    Keyword("isolated score", TrackRole.MUSIC),
)

#: Title keywords for subtitle tracks.
SUBTITLE_KEYWORDS: Sequence[Keyword] = (
    Keyword("forced", TrackRole.FORCED, not_after=_NOT_FORCED),
    Keyword("foreign", TrackRole.FORCED),
    Keyword("signs", TrackRole.SIGNS),
    Keyword("songs", TrackRole.SIGNS),
    Keyword("SDH", TrackRole.SDH),
    Keyword("CC", TrackRole.SDH, case_sensitive=True),
    Keyword("hearing impaired", TrackRole.SDH),
    *_COMMENTARY,
)

_PATTERNS: dict[Keyword, re.Pattern[str]] = {}


def _pattern(keyword: Keyword) -> re.Pattern[str]:
    pattern = _PATTERNS.get(keyword)
    if pattern is None:
        pattern = _PATTERNS[keyword] = keyword.pattern()
    return pattern


def audio_flag_roles(disposition: Disposition) -> list[TrackRoleInfo]:
    roles: list[TrackRoleInfo] = []
    if disposition.comment:
        roles.append(_flag(TrackRole.COMMENTARY, "comment"))
    if disposition.visual_impaired:
        roles.append(_flag(TrackRole.DESCRIPTION, "visual_impaired"))
    elif disposition.descriptions:
        roles.append(_flag(TrackRole.DESCRIPTION, "descriptions"))
    if disposition.clean_effects:
        roles.append(_flag(TrackRole.MUSIC, "clean_effects"))
    return roles


def subtitle_flag_roles(disposition: Disposition) -> list[TrackRoleInfo]:
    roles: list[TrackRoleInfo] = []
    if disposition.forced:
        roles.append(_flag(TrackRole.FORCED, "forced"))
    if disposition.hearing_impaired:
        roles.append(_flag(TrackRole.SDH, "hearing_impaired"))
    elif disposition.captions:
        roles.append(_flag(TrackRole.SDH, "captions"))
    if disposition.comment:
        roles.append(_flag(TrackRole.COMMENTARY, "comment"))
    if disposition.descriptions:
        roles.append(_flag(TrackRole.DESCRIPTION, "descriptions"))
    return roles


def title_roles(title: str | None, keywords: Iterable[Keyword]) -> list[TrackRoleInfo]:
    """Roles from title keywords, one per role (the first keyword that matches)."""
    if not title:
        return []
    roles: list[TrackRoleInfo] = []
    seen: set[TrackRole] = set()
    for keyword in keywords:
        if keyword.role in seen:
            continue
        match = _pattern(keyword).search(title)
        if match is not None:
            seen.add(keyword.role)
            roles.append(
                TrackRoleInfo(
                    role=keyword.role,
                    evidence=RoleEvidence.TITLE,
                    detail=f'title contains "{match.group(0)}"',
                )
            )
    return roles


def _flag(role: TrackRole, flag: str) -> TrackRoleInfo:
    return TrackRoleInfo(role=role, evidence=RoleEvidence.FLAG, detail=f"disposition {flag}")


def _merge(*groups: Iterable[TrackRoleInfo]) -> list[TrackRoleInfo]:
    """Keep the first (strongest) evidence for each role."""
    merged: list[TrackRoleInfo] = []
    seen: set[TrackRole] = set()
    for group in groups:
        for info in group:
            if info.role not in seen:
                seen.add(info.role)
                merged.append(info)
    return merged


def _language(tag: str | None) -> str | None:
    if not tag:
        return None
    lang = tag.strip().casefold()
    return None if lang in ("", "und") else lang


def _main(disposition: Disposition, what: str) -> TrackRoleInfo:
    if disposition.default:
        return TrackRoleInfo(
            role=TrackRole.MAIN, evidence=RoleEvidence.FLAG, detail="disposition default"
        )
    return TrackRoleInfo(
        role=TrackRole.MAIN, evidence=RoleEvidence.HEURISTIC, detail=f"no {what} evidence"
    )


def assign_audio_roles(streams: Sequence[AudioStream]) -> None:
    """Set ``roles`` on every audio stream (in place; ``streams`` in file order)."""
    for stream in streams:
        stream.roles = _merge(
            audio_flag_roles(stream.disposition), title_roles(stream.title, AUDIO_KEYWORDS)
        )
    for position, stream in enumerate(streams):
        if stream.roles or stream.title or stream.disposition.default or stream.channels > 2:
            continue
        bitrate = stream.bitrate.value
        lang = _language(stream.language)
        if bitrate is None or bitrate > COMMENTARY_MAX_BITRATE or lang is None:
            continue
        main = next(
            (
                other
                for other in streams[:position]
                if other.channels > 2
                and _language(other.language) == lang
                and not any(r.role is not TrackRole.MAIN for r in other.roles)
            ),
            None,
        )
        if main is None:
            continue
        layout = "mono" if stream.channels == 1 else "2.0"
        stream.roles = [
            TrackRoleInfo(
                role=TrackRole.COMMENTARY,
                evidence=RoleEvidence.HEURISTIC,
                detail=(
                    f"{layout} at {round(bitrate / 1000)} kb/s after the {main.channels}-channel "
                    f"track #{main.index} in the same language ({stream.language})"
                ),
            )
        ]
    for stream in streams:
        if not stream.roles:
            stream.roles = [_main(stream.disposition, "commentary, description or music")]


def assign_subtitle_roles(streams: Sequence[SubtitleStream]) -> None:
    """Set ``roles`` on every subtitle stream (in place; ``streams`` in file order)."""
    for stream in streams:
        stream.roles = _merge(
            subtitle_flag_roles(stream.disposition),
            title_roles(stream.title, SUBTITLE_KEYWORDS),
        )
    for stream in streams:
        count = stream.event_count
        lang = _language(stream.language)
        if not count or lang is None:  # unknown, or an empty track (0 events): not forced
            continue
        if any(r.role in (TrackRole.FORCED, TrackRole.SIGNS) for r in stream.roles):
            continue
        others = [
            other
            for other in streams
            if other is not stream
            and other.event_count is not None
            and _language(other.language) == lang
        ]
        if not others:
            continue
        biggest = max(others, key=lambda other: other.event_count or 0)
        top = biggest.event_count or 0
        if top <= 0 or count > FORCED_MAX_RATIO * top:
            continue
        stream.roles = [
            *stream.roles,
            TrackRoleInfo(
                role=TrackRole.FORCED,
                evidence=RoleEvidence.HEURISTIC,
                detail=(
                    f"{count} events, {round(100 * count / top)} % of the {top} events of "
                    f"track #{biggest.index} in the same language ({stream.language})"
                ),
            ),
        ]
    for stream in streams:
        if not stream.roles:
            stream.roles = [_main(stream.disposition, "forced, SDH, signs or commentary")]
