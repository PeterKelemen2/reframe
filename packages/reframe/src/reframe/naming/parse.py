"""Release-name parsing (03 §Output naming → Variables, "Name parts"; C-16).

``guessit`` runs in advanced mode, so every match comes with its position. Text fields are cut
from the original string and keep their spelling and separators: ``{main_title}`` of
``Hacksaw.Ridge.2016.HYBRID.2160p…`` is ``Hacksaw.Ridge``, not guessit's ``Hacksaw Ridge``.

The rules:

- ``{main_title}`` is the text from the start of the name to the first **release tag** (year,
  resolution, source, codec, edition, group…). Leading tags (an anime ``[Group]``, a website)
  are skipped. For an episode, the cut is the first tag *after* the episode code, so the show
  name, a year before the code (``Doctor.Who.2005.S01E01.Rose``), the code and the episode
  title stay.
- ``{name}`` is the movie title (``{main_title}`` of a movie) or the show name: the text before
  the episode code, without a year that stands right before the code.
- ``{sub_title}`` is the text between the episode code (or air date) and the cut.
- ``{episode_code}`` is the code as written, multi-episode codes included (``S03E02E03``,
  ``1x01-1x02``, ``S01E16-E17``, ``E1071``, ``001``).

guessit quirks worked around here (each has a test with the real guessit output in
``tests/naming/test_guessit_quirks.py``):

1. A title *after* the episode number (``01 - Pilot.mkv``) is the episode title.
2. A bare number after `` - `` (``Bleach - 001 - …``, ``One Piece - 1000 - …``) is an absolute
   episode number; guessit splits it into season 0 / episode 1, or season 10 / episode 0.
3. ``UHD.BluRay``: guessit's source match covers only ``BluRay``; ``UHD`` right before it is
   added back. ``WEB`` + ``Rip`` (two matches) is one source, ``WEBRip``.
4. A site tag glued to the group (``-GRP[rarbg]``) is dropped from the release group.
5. HDR tags that guessit does not report (``HDR10Plus``, ``HLG``) are still scored.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from types import MappingProxyType

from guessit import guessit
from rebulk.match import Match as RebulkMatch

from reframe.models.naming import NameSpan, ParsedName
from reframe.naming.sanitize import replace_undecodable

__all__ = [
    "GUESSIT_OPTIONS",
    "SCORED_FIELDS",
    "NameParse",
    "clean_text",
    "detect_separator",
    "guess_matches",
    "parse_name",
]

#: Word separators of release names. ``-`` counts only in names without any of these.
WORD_SEPARATORS = " ._"
_STRIP = " \t._-"
_OPEN = "([{"
_CLOSE = ")]}"

#: Matches that are part of the name, never a release tag.
_NAME_PROPS = frozenset(
    {
        "title",
        "alternative_title",
        "film_title",
        "part",
        "volume",
        "country",
        "episode_title",
        "episode_details",
        "bonus_title",
    }
)
#: The episode code and its friends (kept in ``{main_title}`` of an episode).
_CODE_PROPS = frozenset({"season", "episode", "absolute_episode"})
_EPISODE_PROPS = frozenset({"episode_count", "season_count", "week", "date"})

#: guessit ``other`` values that are HDR formats.
_HDR_OTHER = frozenset({"HDR10", "HDR10+", "Dolby Vision", "HLG", "HDR"})
_HDR_TOKEN = re.compile(
    r"(?<![A-Za-z0-9])(?:HDR10\+|HDR10Plus|HDR10|HDR|HLG|DoVi|DV)(?![A-Za-z0-9])", re.IGNORECASE
)

#: The scored fields of 03 §Where the name comes from, in display order.
SCORED_FIELDS = (
    "title",
    "year",
    "resolution",
    "source",
    "video_codec",
    "audio_codec",
    "hdr",
    "edition",
    "release_group",
)

#: guessit property → span field name of :class:`NameSpan`.
_SPAN_FIELD = {
    "screen_size": "resolution",
    "source": "source_type",
    "release_group": "release_group",
    "edition": "edition",
    "year": "year",
    "date": "date",
}


#: The options of every guessit call (a copy is passed: guessit wants a ``dict``).
#: ``no_user_config``: guessit 4.4.0 otherwise reads ``guessit.options.(json|yml|yaml)`` in the
#: working folder and ``options.*`` in ``~/.guessit`` and ``~/.config/guessit``. Such a file
#: changes the parse (``{"type": "movie"}`` turns an episode title into ``alternative_title``)
#: or, when it is malformed, makes every call fail; and naming reads the file system only
#: through :class:`~reframe.naming.fs.NamingFs`.
GUESSIT_OPTIONS: Mapping[str, object] = MappingProxyType(
    {"advanced": True, "name_only": True, "no_user_config": True}
)


@dataclass(frozen=True, slots=True)
class GuessMatch:
    """One guessit match: property name, value and position in the parsed string."""

    prop: str
    value: object
    start: int
    end: int


@lru_cache(maxsize=8192)
def guess_matches(text: str) -> tuple[GuessMatch, ...]:
    """guessit's matches for ``text`` (advanced mode, name only), sorted by position.

    Cached: a season folder is parsed once for every file in it. Matches without text
    (``type``, ``mimetype``) are left out. guessit failing is not an error: no matches.
    """
    try:
        result = guessit(text, dict(GUESSIT_OPTIONS))
    except Exception:  # guessit raises its own exception types on odd input
        return ()
    matches: list[GuessMatch] = []
    for prop, found in result.items():
        for match in found if isinstance(found, list) else [found]:
            if not isinstance(match, RebulkMatch) or match.end <= match.start:
                continue
            value: object = match.value
            if not isinstance(value, int | str):
                value = str(value)
            matches.append(GuessMatch(prop, value, match.start, match.end))
    matches.sort(key=lambda m: (m.start, -m.end, m.prop))
    return tuple(_dedupe(matches))


def _dedupe(matches: list[GuessMatch]) -> list[GuessMatch]:
    """Drop a match inside another match of the same property (guessit reports ``01`` and
    ``1`` for one episode number, and one span per season of ``S01-S06``)."""
    kept: list[GuessMatch] = []
    for match in matches:
        if any(
            k.prop == match.prop and k.start <= match.start and match.end <= k.end for k in kept
        ):
            continue
        kept.append(match)
    return kept


def clean_text(text: str) -> str:
    """Strip separators, dashes and unbalanced brackets from both ends (``" - Rose "`` →
    ``Rose``, ``Mad Max Fury Road (`` → ``Mad Max Fury Road``)."""
    previous = None
    while previous != text:
        previous = text
        text = text.strip(_STRIP)
        if text[-1:] in _OPEN:
            text = text[:-1]
        if text[:1] in _CLOSE:
            text = text[1:]
        for opening, closing in zip(_OPEN, _CLOSE, strict=True):
            if text.endswith(closing) and text.count(closing) > text.count(opening):
                text = text[:-1]
            if text.startswith(opening) and text.count(opening) > text.count(closing):
                text = text[1:]
    return text


def clean_tag(text: str) -> str:
    """A release tag without separators or brackets around it: ``[1080p]`` → ``1080p``."""
    return text.strip(_STRIP + _OPEN + _CLOSE)


def _trim(text: str, start: int, end: int, *, tag: bool = False) -> tuple[int, int]:
    """``(start, end)`` narrowed to the text that :func:`clean_text` (or, for a release tag,
    :func:`clean_tag`) keeps."""
    part = text[start:end]
    cleaned = clean_tag(part) if tag else clean_text(part)
    if not cleaned:
        return start, start
    offset = part.find(cleaned)
    return start + offset, start + offset + len(cleaned)


def detect_separator(text: str) -> str | None:
    """The word separator of a name: the most frequent of space, dot and underscore (a tie
    goes to the space, then the dot). A dash only when the name has none of these and at least
    two dashes (``the-sopranos-s03e02``; not ``WALL-E``)."""
    counts = [(text.count(sep), -i, sep) for i, sep in enumerate(WORD_SEPARATORS)]
    count, _, sep = max(counts)
    if count:
        return sep
    if text.count("-") >= 2:
        return "-"
    return None


@dataclass(slots=True)
class NameParse:
    """One parsed name: the fields, the spans, and what the score counts."""

    text: str
    fields: ParsedName
    spans: list[NameSpan] = field(default_factory=list)
    recognised: list[str] = field(default_factory=list)
    """The :data:`SCORED_FIELDS` found."""
    word_separators: bool = False

    @property
    def score(self) -> int:
        return len(self.recognised) + (2 if self.word_separators else 0)

    @property
    def has_episode(self) -> bool:
        return self.fields.episode is not None


def _leading_start(text: str, matches: list[GuessMatch], kept: set[int]) -> int:
    """Where the name starts: after leading release tags and a leading ``[…]`` block."""
    pos = 0
    for i, match in enumerate(matches):
        if match.start < pos:
            continue
        if text[pos : match.start].strip(_STRIP + _OPEN + _CLOSE):
            break
        if i in kept:
            break
        pos = match.end
    first_kept = min((matches[i].start for i in kept), default=len(text))
    while True:
        rest = text[pos:]
        stripped = rest.lstrip(_STRIP)
        if not stripped.startswith("["):
            break
        close = stripped.find("]")
        block_end = pos + (len(rest) - len(stripped)) + close + 1
        if close == -1 or block_end > first_kept:
            break
        pos = block_end
    return pos


_CODE_PREFIX = re.compile(r"(?i)(?<![A-Za-z0-9])(?:season[ ._]?|episode[ ._]?|ep[ ._]?|s|e)$")


def _code_left(text: str, pos: int) -> int:
    """Extend an episode code to the left over its prefix: ``S``01, ``E``1071, ``Ep``01,
    ``Season.``5, ``Episode ``01."""
    prefix = _CODE_PREFIX.search(text[:pos])
    return prefix.start() if prefix else pos


_CODE_GAP = re.compile(r"^[-._ &+eExXsS]{0,3}$")


def _source_span(text: str, matches: list[GuessMatch]) -> tuple[int, int] | None:
    sources = [m for m in matches if m.prop == "source"]
    if not sources:
        return None
    first = sources[0]
    start, end = first.start, first.end
    if first.value == "Ultra HD Blu-ray":
        before = re.search(r"(?i)(?<![A-Za-z0-9])UHD[ ._-]?$", text[:start])
        if before:
            start = before.start()
    for match in matches:
        if match.prop == "other" and match.value == "Rip" and match.start == end:
            end = match.end
    return _trim(text, start, end, tag=True)


def _joined(text: str, spans: list[tuple[int, int]], separator: str | None) -> str | None:
    """The text of several spans: one stretch of the original when only separators lie
    between them, else the pieces joined with the name's separator."""
    if not spans:
        return None
    gaps = [text[a_end:b_start] for (_, a_end), (b_start, _) in itertools.pairwise(spans)]
    if all(not gap.strip(_STRIP) for gap in gaps):
        return clean_tag(text[spans[0][0] : spans[-1][1]]) or None
    pieces = [clean_tag(text[s:e]) for s, e in spans]
    return (separator or " ").join(p for p in pieces if p) or None


def parse_name(text: str) -> NameParse:
    """Parse one name (a file name without its extension, or a folder name).

    A byte that is not UTF-8 (a lone surrogate, ``\\udcff``) becomes ``�`` first, so every
    field and :attr:`NameParse.text` can be written as JSON; positions do not move.
    """
    text = replace_undecodable(text)
    matches = list(guess_matches(text))
    separator = detect_separator(text)

    code = [m for m in matches if m.prop in _CODE_PROPS]
    # Quirk 1: a title after the episode number is the episode title (``01 - Pilot``).
    titles = [m for m in matches if m.prop == "title"]
    if titles and code and titles[0].start > code[0].start:
        matches = [
            GuessMatch("episode_title", m.value, m.start, m.end) if m is titles[0] else m
            for m in matches
        ]

    # The episode code: the first season/episode match and the ones right after it.
    code_start = code_end = None
    if code:
        code_start = _code_left(text, code[0].start)
        code_end = code[0].end
        for match in code[1:]:
            if match.start >= code_end and _CODE_GAP.match(text[code_end : match.start]):
                code_end = match.end
            elif match.start < code_end:
                code_end = max(code_end, match.end)
    dates = [m for m in matches if m.prop == "date"]
    anchor = (code_start, code_end) if code_start is not None and code_end is not None else None
    if anchor is None and dates:
        anchor = (dates[0].start, dates[0].end)
    is_episode = anchor is not None

    # Which matches are part of the name (kept), and which are release tags.
    kept: set[int] = set()
    for i, match in enumerate(matches):
        if match.prop in _NAME_PROPS or (
            is_episode and (match.prop in _CODE_PROPS or match.prop in _EPISODE_PROPS)
        ):
            kept.add(i)
        elif match.prop == "year" and anchor is not None and match.start < anchor[0]:
            kept.add(i)  # a year before the episode code stays (``Doctor.Who.2005.S01E01``)
        elif anchor is not None and match.prop == "year" and match.start < anchor[1]:
            kept.add(i)  # the year guessit also sees inside ``S2023E01``

    start = _leading_start(text, matches, kept)
    tags = [m for i, m in enumerate(matches) if i not in kept and m.start >= start]
    after = anchor[1] if anchor is not None else start
    cut = min((m.start for m in tags if m.start >= after), default=len(text))

    fields = ParsedName(separator=separator)
    spans: list[NameSpan] = []

    def span(name: str, a: int, b: int, *, tag: bool = True) -> None:
        a, b = _trim(text, a, b, tag=tag)
        if b > a:
            spans.append(NameSpan(field=name, start=a, end=b, text=text[a:b]))

    fields.main_title = clean_text(text[start:cut]) or None
    if is_episode and anchor is not None:
        fields.kind = "episode"
        name_end = anchor[0]
        for i, match in enumerate(matches):
            if match.start >= start and (
                (match.prop == "year" and i in kept and match.start < anchor[0])
                or (i not in kept and match.start < name_end)
            ):
                name_end = min(name_end, match.start)
        has_title = any(m.prop == "title" and start <= m.start < name_end for m in matches)
        fields.name = (clean_text(text[start:name_end]) or None) if has_title else None
        if fields.name:
            span("name", start, name_end, tag=False)
        if anchor[1] < cut:
            fields.sub_title = clean_text(text[anchor[1] : cut]) or None
            if fields.sub_title:
                span("sub_title", anchor[1], cut, tag=False)
    else:
        fields.name = fields.main_title
        if fields.name:
            span("name", start, cut, tag=False)

    if code and code_start is not None and code_end is not None:
        fields.episode_code = clean_tag(text[code_start:code_end]) or None
        span("episode_code", code_start, code_end)
        seasons = [m for m in code if m.prop == "season" and m.start < code_end]
        episodes = [
            m for m in code if m.prop in ("episode", "absolute_episode") and m.start < code_end
        ]
        bare = text[code_start:code_end]
        if (
            seasons
            # isdecimal, not isdigit: ``int`` takes every decimal digit (guessit reads
            # Arabic-Indic and full-width digits as numbers too), but not ``²``.
            and bare.isdecimal()
            and len(bare) >= 3
            and text[:code_start].rstrip(" ").endswith("-")
        ):
            # Quirk 2: ``Bleach - 001`` / ``One Piece - 1000`` are absolute episode numbers.
            fields.season = None
            fields.episodes = [int(bare)]
        else:
            fields.season = _int(seasons[0].value) if seasons else None
            numbers = [_int(m.value) for m in episodes if m.prop == "episode"]
            if not numbers:
                numbers = [_int(m.value) for m in episodes]
            fields.episodes = list(dict.fromkeys(n for n in numbers if n is not None))
        fields.episode = fields.episodes[0] if fields.episodes else None
    for match in dates:
        span("date", match.start, match.end)

    years = [m for m in matches if m.prop == "year"]
    if years:
        fields.year = _int(years[0].value)
        for match in years:
            if not (
                code_start is not None
                and code_end is not None
                and match.start < code_end
                and match.end > code_start
            ):
                span("year", match.start, match.end)

    editions = [(m.start, m.end) for m in matches if m.prop == "edition"]
    fields.edition = _joined(text, editions, separator)
    source = _source_span(text, matches)
    if source is not None and source[1] > source[0]:
        fields.source_type = clean_tag(text[source[0] : source[1]]) or None
    groups = [m for m in matches if m.prop == "release_group"]
    if groups:
        # Quirk 4: ``GRP[rarbg]`` → ``GRP``.
        raw = text[groups[0].start : groups[0].end].strip(_STRIP)
        group = clean_tag(re.sub(r"(?<=[^\s\[])\[[^\]]*\]$", "", raw))
        fields.release_group = group or None
    sizes = [m for m in matches if m.prop == "screen_size"]
    if sizes:
        fields.resolution = clean_tag(text[sizes[0].start : sizes[0].end]) or None

    # Spans of the release tags.
    hdr = False
    for match in tags:
        if match.prop == "other" and match.value in _HDR_OTHER:
            hdr = True
            span("hdr", match.start, match.end)
        elif (match.prop == "source" and source is not None) or match.prop == "year":
            continue
        else:
            span(_SPAN_FIELD.get(match.prop, match.prop), match.start, match.end)
    if source is not None:
        span("source_type", *source)
    covered = [(m.start, m.end) for m in matches]
    for token in _HDR_TOKEN.finditer(text, cut):
        if not any(a <= token.start() < b for a, b in covered):
            hdr = True  # Quirk 5: ``HDR10Plus``, ``HLG``
            span("hdr", token.start(), token.end())
    spans.sort(key=lambda s: (s.start, s.end))

    props = {m.prop for m in matches}
    found = {
        "title": fields.name is not None,
        "year": fields.year is not None,
        "resolution": "screen_size" in props,
        "source": "source" in props,
        "video_codec": "video_codec" in props,
        "audio_codec": "audio_codec" in props,
        "hdr": hdr,
        "edition": "edition" in props,
        "release_group": fields.release_group is not None,
    }
    recognised = [name for name in SCORED_FIELDS if found[name]]
    word_separators = fields.name is not None and any(s in fields.name for s in WORD_SEPARATORS)
    return NameParse(
        text=text,
        fields=fields,
        spans=spans,
        recognised=recognised,
        word_separators=word_separators,
    )


def _int(value: object) -> int | None:
    """guessit's numbers are ``int``; anything else is not a number."""
    return value if isinstance(value, int) and value >= 0 else None
