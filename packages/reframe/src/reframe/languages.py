"""Language tags: normalisation, search, Matroska/MP4 codes and display names (C-6).

Pure module built on ``langcodes`` (+ ``language_data``). The only I/O is reading the data
that these two packages ship (the IANA subtag registry, for macrolanguages), once, cached.

Canonical form
--------------
Every function accepts what appears in files and what users type: Matroska legacy ISO 639-2/B
(``ger``), ISO 639-2/T (``deu``), ISO 639-1 (``de``), ISO 639-3 (``yue``), BCP 47 with script
and region (``pt-BR``, ``es-419``, ``zh-Hans``, ``sr-Latn``) in any case (``PT-br``) or with
underscores (``pt_BR``), the special codes ``und``, ``mul``, ``zxx``, ``mis``, and English or
native language names (``German``, ``magyar``). :func:`normalize` turns this into **one
canonical BCP 47 tag** (``de``, ``pt-BR``) - the form stored in ``TrackMetadata.language`` and
the settings - or ``None`` for invalid input. :func:`validate` gives the reason.

The canonical tag is langcodes' standardised tag (CLDR normalisation: deprecated ``iw`` →
``he``, ``in`` → ``id``, ``jw`` → ``jv``, ``mo`` → ``ro``, ``ji`` → ``yi``; 3-letter codes →
the 2-letter code when there is one), with :data:`OVERRIDES` applied first.

Overrides (where langcodes is wrong for Matroska)
-------------------------------------------------
langcodes follows CLDR and maps ``tl``/``tgl`` (Tagalog) to ``fil`` (Filipino) and
``sh``/``hbs`` (Serbo-Croatian) to ``sr-Latn``. ISO 639 and mkvtoolnix keep them apart:
``tgl`` and ``fil`` are two ISO 639-2 codes, and ``mkvpropedit --set language=tl`` writes
``tgl`` + ``tl``, ``--set language=sh`` writes ``und`` + ``sh`` (legacy + ``LanguageIETF``).
So :data:`OVERRIDES` keeps ``tl`` (Matroska ``tgl``) and ``sh`` (Matroska ``und``:
Serbo-Croatian has no ISO 639-2 code). Every other ISO 639-2 code keeps its meaning in
langcodes 3.5.1 (a test checks all 438 /B and /T codes).

Matroska and MP4 codes
----------------------
- :func:`to_matroska_legacy`: the Matroska ``Language`` element, ISO 639-2/**B** (``ger``,
  ``fre``, ``chi``). A language without an ISO 639-2 code gets its macrolanguage's code if
  that has one (``yue``, ``cmn`` → ``chi``; ``arb`` → ``ara``), else ``und``.
- :func:`to_matroska_ietf`: the Matroska ``LanguageIETF`` (BCP 47) element: the canonical tag.
- :func:`to_mp4`: ISO 639-2/**T** (``deu``) for the MP4 ``mdhd`` language, same fallbacks.

For every tag that mkvpropedit accepts, ``mkvpropedit --set language=<tag>`` writes exactly
``to_matroska_legacy(tag)`` + ``to_matroska_ietf(tag)`` (a ``needs_ffmpeg`` test compares
them for ~35 tags, including ``pt-BR``, ``yue``, ``sh``, ``tl``, ``arb``, ``zsm``, ``qaa``).

Verified tool behaviour (FFmpeg n9.0.2, mkvtoolnix 101.0, Linux; ``needs_ffmpeg`` tests)
-----------------------------------------------------------------------------------------
- FFmpeg's Matroska muxer writes ``-metadata:s:a:0 language=X`` **verbatim** into the legacy
  ``Language`` element and never writes ``LanguageIETF``: ``language=de`` stores ``de`` and
  ``language=pt-BR`` stores ``pt-BR`` (both invalid there). ffprobe reads the string back
  verbatim, except ``und``: then ffprobe shows no ``language`` tag. So C-7 passes
  :func:`to_matroska_legacy` to FFmpeg for MKV, and ``LanguageIETF`` needs the
  ``mkvpropedit`` fix-up (C-13).
- FFmpeg's MP4 muxer keeps a 3-letter code as given (``ger`` and ``deu`` both read back
  unchanged) and **silently drops** a 2-letter code or a BCP 47 tag (``de``, ``pt-BR``: no
  ``language`` tag on read-back, no warning). So C-7 passes :func:`to_mp4` for MP4.
- ``mkvpropedit --set language-ietf=X`` changes only ``LanguageIETF``: on a ``ger`` track,
  ``language-ietf=fr`` leaves ``Language`` = ``ger`` (an inconsistent track). ``--set
  language=X`` accepts a BCP 47 tag or ISO 639 code and writes **both** elements
  (``language=pt-BR`` → ``por`` + ``pt-BR``; ``language=deu`` → ``ger`` + ``de``). It
  rejects deprecated codes (``in``, ``jw``, ``mo``, ``ji``) and ``pt_BR``: pass
  :func:`to_matroska_ietf` (or ``language=`` + ``language-ietf=`` from this module).
- **ffprobe never shows ``LanguageIETF``**: after ``language-ietf=pt-BR`` it still shows the
  legacy ``language=ger``/``por``. The probe (C-3) gets only the legacy code from ffprobe;
  ``pt-BR`` or ``yue`` needs ``mkvmerge -J`` (``language_ietf``) or MediaInfo, and a C-13
  re-probe with ffprobe cannot see a ``LanguageIETF`` change.

Language list scope (``GET /api/languages``)
--------------------------------------------
:func:`language_list` has one entry per ISO 639-2 individual language or macrolanguage (which
includes every ISO 639-1 language), plus the special codes ``und``, ``mul``, ``zxx``, ``mis``,
plus :data:`COMMON_VARIANTS` (``pt-BR``, ``zh-Hans``, ...). Not included: ISO 639-2
collective codes (``afa``, ``sla``), the local-use range ``qaa``-``qtz``, and languages that
only ISO 639-3 has (``yue``, ``cmn``). :func:`search` still finds any valid tag or a name that
langcodes knows (``yue``, ``Cantonese``, ``de-AT``) and returns an entry for it.

Rule matching
-------------
:func:`same_language` compares base languages: ``ger`` = ``de``, ``pt-BR`` = ``pt`` =
``pt-PT``. :func:`matches` is the one-way check for preset rules: a rule for ``pt`` matches a
``pt-BR`` track, a rule for ``pt-BR`` does not match a ``pt`` or ``pt-PT`` track. Both treat a
dominant language and its macrolanguage as the same language (CLDR: ``cmn`` = ``zh``,
``arb`` = ``ar``) and a missing or invalid language as ``und``.

Invalid input never raises: the conversion and display functions treat it as ``und``.
"""

from __future__ import annotations

import functools
import importlib.resources
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

from langcodes import Language
from langcodes.tag_parser import LanguageTagError

from reframe.models.job import Container

__all__ = [
    "COMMON_VARIANTS",
    "OVERRIDES",
    "SPECIAL_CODES",
    "UNDETERMINED",
    "LanguageEntry",
    "base_language",
    "english_name",
    "entry",
    "join_short_codes",
    "language_list",
    "matches",
    "native_name",
    "normalize",
    "picker_label",
    "same_language",
    "search",
    "short_code",
    "to_matroska_ietf",
    "to_matroska_legacy",
    "to_mp4",
    "validate",
]

UNDETERMINED: Final = "und"

#: ISO 639-2 special codes: undetermined, multiple, no linguistic content, uncoded.
SPECIAL_CODES: Final = ("und", "mul", "zxx", "mis")

#: Primary language subtags where langcodes' CLDR normalisation changes the language (see the
#: module docstring). Input primary subtag (lower case) → canonical primary subtag.
OVERRIDES: Final[dict[str, str]] = {"tl": "tl", "tgl": "tl", "sh": "sh", "hbs": "sh"}

#: Region and script variants offered by the picker next to the base languages.
COMMON_VARIANTS: Final = (
    "en-US",
    "en-GB",
    "es-419",
    "es-ES",
    "fr-CA",
    "pt-BR",
    "pt-PT",
    "sr-Cyrl",
    "sr-Latn",
    "zh-Hans",
    "zh-Hant",
)

#: English names that replace langcodes' name (ISO 639-2 calls ``und`` "Undetermined";
#: langcodes says "Unknown language").
_NAME_OVERRIDES: Final[dict[str, str]] = {"und": "Undetermined"}


def _code_set(text: str) -> frozenset[str]:
    """Whitespace-separated codes → set."""
    return frozenset(text.split())


#: ISO 639-2 individual languages, macrolanguages and special codes, as the /T code (the /B
#: code differs for 20 of them; langcodes knows those). 418 codes, from the ISO 639-3 code
#: table (``Part2T`` where ``Part2B`` is set; SIL, as shipped by babelfish 0.6.1).
_ISO639_2T: Final = _code_set(
    """
    aar abk ace ach ada ady afh afr ain aka akk ale alt amh ang anp ara arc arg arn arp arw asm
    ast ava ave awa aym aze bak bal bam ban bas bej bel bem ben bho bik bin bis bla bod bos bra
    bre bua bug bul byn cad car cat ceb ces cha chb che chg chk chm chn cho chp chr chu chv chy
    cop cor cos cre crh csb cym dak dan dar del den deu dgr din div doi dsb dua dum dyu dzo efi
    egy eka ell elx eng enm epo est eus ewe ewo fan fao fas fat fij fil fin fon fra frm fro frr
    frs fry ful fur gaa gay gba gez gil gla gle glg glv gmh goh gon gor got grb grc grn gsw guj
    gwi hai hat hau haw heb her hil hin hit hmn hmo hrv hsb hun hup hye iba ibo ido iii iku ile
    ilo ina ind inh ipk isl ita jav jbo jpn jpr jrb kaa kab kac kal kam kan kas kat kau kaw kaz
    kbd kha khm kho kik kin kir kmb kok kom kon kor kos kpe krc krl kru kua kum kur kut lad lah
    lam lao lat lav lez lim lin lit lol loz ltz lua lub lug lui lun luo lus mad mag mah mai mak
    mal man mar mas mdf mdr men mga mic min mis mkd mlg mlt mnc mni moh mon mos mri msa mul mus
    mwl mwr mya myv nap nau nav nbl nde ndo nds nep new nia niu nld nno nob nog non nor nqo nso
    nwc nya nym nyn nyo nzi oci oji ori orm osa oss ota pag pal pam pan pap pau peo phn pli pol
    pon por pro pus que raj rap rar roh rom ron run rup rus sad sag sah sam san sas sat scn sco
    sel sga shn sid sin slk slv sma sme smj smn smo sms sna snd snk sog som sot spa sqi srd srn
    srp srr ssw suk sun sus sux swa swe syc syr tah tam tat tel tem ter tet tgk tgl tha tig tir
    tiv tkl tlh tli tmh tog ton tpi tsi tsn tso tuk tum tur tvl twi tyv udm uga uig ukr umb und
    urd uzb vai ven vie vol vot wal war was wln wol xal xho yao yap yid yor zap zbl zen zha zho
    zul zun zxx zza
    """
)

#: ISO 639-2 collective codes (not in the picker list, but valid Matroska/MP4 codes): the
#: collections in the IANA registry added with ISO 639-2 (2005-10-16), ``bh`` as ``bih``.
_ISO639_2_COLLECTIVE: Final = _code_set(
    """
    afa alg apa art ath aus bad bai bat ber bih bnt btk cai cau cel cmc cpe cpf cpp crp cus day
    dra fiu gem him ijo inc ine ira iro kar khi kro map mkh mno mun myn nah nai nic nub oto paa
    phi pra roa sai sal sem sgn sio sit sla smi son ssa tai tup tut wak wen ypk znd
    """
)

#: The shape that :data:`reframe.models.LanguageTag` accepts.
_TAG_SHAPE: Final = re.compile(r"^[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*$")
_MAX_TAG_LENGTH: Final = 64
_MAX_NAME_LENGTH: Final = 100


# --------------------------------------------------------------------------- data


@functools.cache
def _iso639_2_codes() -> frozenset[str]:
    """Every ISO 639-2 code, /B and /T (``ger`` and ``deu``), and the collective codes."""
    b_codes = {_parse(code).to_alpha3(variant="B") for code in _canonical_639_2()}
    return _ISO639_2T | _ISO639_2_COLLECTIVE | b_codes


def _is_iso639_2(code: str) -> bool:
    return code in _iso639_2_codes() or "qaa" <= code <= "qtz"  # qaa-qtz: local use


@functools.cache
def _canonical_639_2() -> tuple[str, ...]:
    """The canonical tag of every ISO 639-2 language and special code, sorted, no duplicates."""
    tags = {_normalize_code(code) for code in _ISO639_2T}
    return tuple(sorted(tag for tag in tags if tag is not None))


@functools.cache
def _macrolanguages() -> dict[str, str]:
    """``{language subtag: macrolanguage subtag}`` from the IANA registry (``yue`` → ``zh``)."""
    text = (
        importlib.resources.files("language_data") / "data" / "language-subtag-registry.txt"
    ).read_text(encoding="utf-8")
    result: dict[str, str] = {}
    for record in text.split("\n%%\n"):
        fields = dict(
            line.split(": ", 1) for line in record.splitlines() if ": " in line and line[0] != " "
        )
        if fields.get("Type") == "language" and "Macrolanguage" in fields:
            result[fields["Subtag"]] = fields["Macrolanguage"]
    return result


# --------------------------------------------------------------------------- normalisation


@functools.lru_cache(maxsize=4096)
def _parse(tag: str) -> Language:
    """A canonical tag as a ``Language`` (no second normalisation: ``tl`` stays ``tl``)."""
    return Language.get(tag, normalize=False)


def _fold(text: str) -> str:
    """Case- and accent-insensitive form for name matching (``Français`` → ``francais``)."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).strip()


def _code_language(text: str) -> Language | None:
    """Parse code-shaped input (BCP 47 / ISO 639) with the overrides, or ``None``."""
    text = text.strip().replace("_", "-")
    if not _TAG_SHAPE.fullmatch(text) or len(text) > _MAX_TAG_LENGTH:
        return None
    primary = text.split("-", 1)[0].lower()
    try:
        if primary in OVERRIDES:
            lang = Language.get(text, normalize=False).update_dict({"language": OVERRIDES[primary]})
        else:
            lang = Language.get(text)
    except (LanguageTagError, ValueError):
        return None
    return lang


@functools.lru_cache(maxsize=4096)
def _normalize_code(text: str) -> str | None:
    """Canonical tag for code-shaped input only (no name lookup), or ``None``."""
    lang = _code_language(text)
    if lang is None or not lang.is_valid():
        return None
    tag = lang.to_tag()
    return tag if _TAG_SHAPE.fullmatch(tag) else None


def _looks_like_name(text: str) -> bool:
    """Starts with a letter, at most 100 characters, no digit, ``_`` or control character
    (names: ``N'Ko``, full-width brackets, ``རྫོང་ཁ``). langcodes' name lookup crashes on a NUL
    character (``SystemError`` from its trie), so this check also protects it."""
    text = unicodedata.normalize("NFKC", text)
    return (
        len(text) <= _MAX_NAME_LENGTH
        and text[:1].isalpha()
        and not any(
            ch.isdigit() or ch == "_" or unicodedata.category(ch).startswith("C") for ch in text
        )
    )


@functools.lru_cache(maxsize=1024)
def _normalize_name(text: str) -> str | None:
    """Canonical tag for a language name (English or native, any case/accents), or ``None``.

    Only text that looks like a name is looked up (:func:`_looks_like_name`): langcodes'
    fuzzy name match would turn ``-en`` into ``enc``.
    """
    if not _looks_like_name(text):
        return None
    folded = _fold(text)
    known = _name_index().get(folded)
    if known is not None:
        return known
    for in_language in ("en", None):
        try:
            found = Language.find(text, in_language)
        except (LookupError, LanguageTagError, ValueError):
            continue
        return _normalize_code(found.to_tag())
    return None


def normalize(value: str | None) -> str | None:
    """The canonical BCP 47 tag for a code, tag or language name, or ``None`` if invalid.

    ``ger``/``deu``/``de``/``German``/``Deutsch`` → ``de``; ``PT_br`` → ``pt-BR``; ``iw`` →
    ``he``; ``und`` → ``und``. Idempotent: ``normalize(normalize(x)) == normalize(x)``.
    """
    if value is None or not value.strip():
        return None
    return _normalize_code(value) or _normalize_name(value.strip())


def validate(value: str | None) -> str | None:
    """``None`` if :func:`normalize` accepts ``value``, else the reason in plain words."""
    if value is None or not value.strip():
        return "No language given: enter a language name or code, for example hu or pt-BR."
    if normalize(value) is not None:
        return None
    text = value.strip().replace("_", "-")
    if text[:2].lower() == "x-":
        return f"{value!r}: private-use tags (x-...) are not supported."
    if "-" not in text or not _TAG_SHAPE.fullmatch(text):
        return f"{value!r} is not a known language name or code."
    lang = _code_language(text)
    if lang is None:
        return f"{value!r} is not a valid language tag (BCP 47)."
    checks = [
        ("language code", lang.language, Language.make(language=lang.language)),
        ("script", lang.script, Language.make(script=lang.script)),
        ("region", lang.territory, Language.make(territory=lang.territory)),
        *(("variant", v, Language.make(variants=[v])) for v in lang.variants or ()),
    ]
    for kind, subtag, single in checks:
        if subtag is not None and not single.is_valid():
            return f"{value!r}: {subtag!r} is not a known {kind}."
    return f"{value!r} is not a valid language tag (BCP 47)."


def _language_or_und(value: str | None) -> Language:
    tag = normalize(value)
    return _parse(tag if tag is not None else UNDETERMINED)


def base_language(value: str | None) -> str:
    """The primary language subtag of the canonical tag: ``pt-BR`` → ``pt``, ``ger`` →
    ``de``, ``sr-Latn`` → ``sr``. ``und`` for ``und`` and for invalid input."""
    return _language_or_und(value).language or UNDETERMINED


# --------------------------------------------------------------------------- container codes


def _iso639_2(value: str | None, variant: str) -> str:
    language = _language_or_und(value).language
    if language is None:
        return UNDETERMINED
    for candidate in (language, _macrolanguages().get(language)):
        if candidate is None:
            continue
        try:
            code = _parse(candidate).to_alpha3(variant=variant)
        except LookupError:  # pragma: no cover - every valid 2-letter code has one
            continue
        if _is_iso639_2(code):
            return code
    return UNDETERMINED


def to_matroska_legacy(value: str | None) -> str:
    """ISO 639-2/B for the Matroska ``Language`` element: ``de`` → ``ger``, ``zh-Hans`` →
    ``chi``, ``pt-BR`` → ``por``, ``yue`` → ``chi`` (macrolanguage); ``und`` if unknown."""
    return _iso639_2(value, "B")


def to_mp4(value: str | None) -> str:
    """ISO 639-2/T for the MP4 ``mdhd`` language: ``de`` → ``deu``; ``und`` if unknown."""
    return _iso639_2(value, "T")


def to_matroska_ietf(value: str | None) -> str:
    """BCP 47 for the Matroska ``LanguageIETF`` element: the canonical tag (``und`` if
    invalid). ``ger`` → ``de``, ``pt_br`` → ``pt-BR``."""
    return normalize(value) or UNDETERMINED


# --------------------------------------------------------------------------- display


def english_name(value: str | None) -> str:
    """English display name: ``hu`` → ``Hungarian``, ``pt-BR`` → ``Portuguese (Brazil)``,
    ``zh-Hans`` → ``Chinese (Simplified)``, ``und``/invalid → ``Undetermined``."""
    lang = _language_or_und(value)
    tag = lang.to_tag()
    if tag in _NAME_OVERRIDES:
        return _NAME_OVERRIDES[tag]
    return lang.display_name("en")


def native_name(value: str | None, *, capitalize: bool = False) -> str:
    """The language's name in itself (CLDR autonym): ``hu`` → ``magyar``, ``pt-BR`` →
    ``português (Brasil)``. English name when CLDR has none (and for ``und``, ``mul``, ...).

    ``capitalize=True`` upper-cases the first letter (``Magyar``): the form for name templates
    (``{lang_native}``). It does not change the rest (``Português (Brasil)``).
    """
    lang = _language_or_und(value)
    if lang.language is None or lang.language in SPECIAL_CODES:
        name = english_name(value)
    else:
        name = lang.autonym()
    return name[:1].upper() + name[1:] if capitalize else name


def short_code(value: str | None) -> str:
    """Upper-case ISO 639-2/B code for file names (``{audio_langs}``): ``hu`` → ``HUN``,
    ``de`` → ``GER``, ``pt-BR`` → ``POR``, invalid → ``UND``."""
    return to_matroska_legacy(value).upper()


def join_short_codes(values: Iterable[str | None], sep: str = "-") -> str:
    """:func:`short_code` of each value, duplicates removed, in order: ``HUN-ENG``."""
    return sep.join(dict.fromkeys(short_code(v) for v in values))


def picker_label(value: str | None, *, container: Container = "mkv") -> str:
    """What the picker shows will be written: ``Hungarian · hun (ISO 639-2) · hu (BCP 47)``.

    The ISO 639-2 code is /B for MKV and WebM (``ger``) and /T for MP4 (``deu``).
    """
    code = to_mp4(value) if container == "mp4" else to_matroska_legacy(value)
    return f"{english_name(value)} · {code} (ISO 639-2) · {to_matroska_ietf(value)} (BCP 47)"


# --------------------------------------------------------------------------- language list


@dataclass(frozen=True, slots=True)
class LanguageEntry:
    """One language for the picker (``GET /api/languages``)."""

    tag: str
    """Canonical BCP 47 tag (``hu``, ``pt-BR``): stored and written as ``LanguageIETF``."""
    iso639_1: str | None
    """ISO 639-1 code (``hu``), ``None`` if the language has none."""
    iso639_2b: str
    """ISO 639-2/B, written to the Matroska ``Language`` element (``hun``, ``ger``): the
    :func:`to_matroska_legacy` value, so the macrolanguage or ``und`` for a language without
    an ISO 639-2 code (``yue`` → ``chi``, ``sh`` → ``und``)."""
    iso639_2t: str
    """ISO 639-2/T, written to MP4 (``hun``, ``deu``): the :func:`to_mp4` value."""
    iso639_3: str
    """ISO 639-3 code of the base language (``hun``, ``deu``, ``hbs`` for ``sh``)."""
    english_name: str
    """``Hungarian``, ``Portuguese (Brazil)``."""
    native_name: str
    """CLDR autonym as CLDR writes it (``magyar``); the English name if CLDR has none."""
    variant: bool
    """A region or script variant of a base language (``pt-BR``)."""


@functools.lru_cache(maxsize=1024)
def _make_entry(tag: str) -> LanguageEntry:
    lang = _parse(tag)
    language = lang.language or UNDETERMINED
    return LanguageEntry(
        tag=tag,
        iso639_1=language if len(language) == 2 else None,
        iso639_2b=to_matroska_legacy(tag),
        iso639_2t=to_mp4(tag),
        iso639_3=_parse(language).to_alpha3(variant="T"),
        english_name=english_name(tag),
        native_name=native_name(tag),
        variant=tag != language,
    )


def entry(value: str | None) -> LanguageEntry | None:
    """The :class:`LanguageEntry` for any valid code, tag or name (also outside
    :func:`language_list`, for example ``yue`` or ``de-AT``); ``None`` if invalid."""
    tag = normalize(value)
    return None if tag is None else _make_entry(tag)


def _sort_key(item: LanguageEntry) -> tuple[str, str]:
    return _fold(item.english_name), item.tag


@functools.cache
def language_list() -> tuple[LanguageEntry, ...]:
    """Every picker language (scope: module docstring), ordered by English name."""
    variants = (tag for tag in (_normalize_code(v) for v in COMMON_VARIANTS) if tag is not None)
    tags = dict.fromkeys([*_canonical_639_2(), *variants])
    return tuple(sorted((_make_entry(tag) for tag in tags), key=_sort_key))


@functools.cache
def _name_index() -> dict[str, str]:
    """Folded English and native names of the list → tag (English names win)."""
    index: dict[str, str] = {}
    for item in language_list():
        index.setdefault(_fold(item.native_name), item.tag)
    for item in language_list():
        index[_fold(item.english_name)] = item.tag
    return index


# --------------------------------------------------------------------------- search

# Match ranks, best first.
_RANK_TAG = 0  # the query is (or normalises to) the entry's tag: "de", "ger", "pt_br"
_RANK_CODE = 1  # the query is one of the entry's ISO codes: "por" for pt-BR
_RANK_ENGLISH = 2  # English name, exact
_RANK_NATIVE = 3  # native name, exact
_RANK_PREFIX = 4  # a name starts with the query
_RANK_WORD = 5  # a word of a name starts with the query: "brazil"
_RANK_SUBSTRING = 6  # a name contains the query
_RANK_FOUND = 7  # langcodes finds the entry by a name in another language: "allemand"

_WORD_SPLIT: Final = re.compile(r"[\s()\-,/]+")


@dataclass(frozen=True, slots=True)
class _Searchable:
    """The folded strings that :func:`search` compares, computed once per entry."""

    tag: str
    codes: frozenset[str]
    english: str
    native: str
    words: tuple[str, ...]


@functools.lru_cache(maxsize=2048)
def _searchable(item: LanguageEntry) -> _Searchable:
    english, native = _fold(item.english_name), _fold(item.native_name)
    codes = (item.iso639_1, item.iso639_2b, item.iso639_2t, item.iso639_3)
    return _Searchable(
        tag=item.tag.casefold(),
        codes=frozenset(code for code in codes if code is not None),
        english=english,
        native=native,
        words=tuple(w for name in (english, native) for w in _WORD_SPLIT.split(name) if w),
    )


def _rank(item: LanguageEntry, folded: str, code_tag: str | None, name_tag: str | None) -> int:
    s = _searchable(item)
    if item.tag == code_tag or folded == s.tag:
        return _RANK_TAG
    if folded in s.codes:
        return _RANK_CODE
    if folded == s.english:
        return _RANK_ENGLISH
    if folded == s.native:
        return _RANK_NATIVE
    if s.english.startswith(folded) or s.native.startswith(folded):
        return _RANK_PREFIX
    if any(word.startswith(folded) for word in s.words):
        return _RANK_WORD
    if folded in s.english or folded in s.native:
        return _RANK_SUBSTRING
    if item.tag == name_tag:
        return _RANK_FOUND
    return -1


def search(
    query: str, *, favourites: Sequence[str] = (), limit: int | None = None
) -> list[LanguageEntry]:
    """Picker search, best match first.

    Matches the BCP 47 tag, ISO 639-1/2B/2T/3 codes, English and native names (case- and
    accent-insensitive). Order: exact tag or code (``ger`` finds German), exact name, name
    prefix, word prefix, substring; ties by English name, base languages before variants.
    Matching ``favourites`` (any form, ``Settings.languages.favourites``) come first. A valid
    tag or a name langcodes knows that is not in :func:`language_list` (``yue``,
    ``Cantonese``, ``de-AT``) adds an entry for it. An empty query returns the favourites,
    then the whole list.
    """
    fav_tags = list(dict.fromkeys(t for t in (normalize(f) for f in favourites) if t))
    fav_rank = {tag: i for i, tag in enumerate(fav_tags)}
    listed = language_list()
    listed_tags = {item.tag for item in listed}
    extra = [_make_entry(tag) for tag in fav_tags if tag not in listed_tags]
    text = query.strip()
    if not text:
        favs = [_make_entry(tag) for tag in fav_tags]
        result = favs + [item for item in listed if item.tag not in fav_rank]
        return result[:limit] if limit is not None else result

    folded = _fold(text)
    code_tag = _normalize_code(text)
    if code_tag is not None and code_tag not in listed_tags and code_tag not in fav_rank:
        extra.append(_make_entry(code_tag))
    scored = _score((*listed, *extra), folded, code_tag, None, fav_rank)
    if not scored and code_tag is None:
        # Nothing matched: try the name in any language langcodes knows ("Cantonese",
        # "allemand"). Not done when something matched, so "e" does not add the language "E".
        name_tag = _normalize_name(text)
        if name_tag is not None:
            listed_or_fav = name_tag in listed_tags or name_tag in fav_rank
            pool = (*listed, *extra) if listed_or_fav else (*listed, *extra, _make_entry(name_tag))
            scored = _score(pool, folded, None, name_tag, fav_rank)
    result = [item for _, item in sorted(scored, key=lambda pair: pair[0])]
    return result[:limit] if limit is not None else result


_ScoreKey = tuple[int, int, int, bool, str, str]


def _score(
    items: Iterable[LanguageEntry],
    folded: str,
    code_tag: str | None,
    name_tag: str | None,
    fav_rank: dict[str, int],
) -> list[tuple[_ScoreKey, LanguageEntry]]:
    scored: list[tuple[_ScoreKey, LanguageEntry]] = []
    for item in items:
        rank = _rank(item, folded, code_tag, name_tag)
        if rank < 0:
            continue
        fav = fav_rank.get(item.tag)
        key = (0 if fav is not None else 1, rank, fav or 0, item.variant, *_sort_key(item))
        scored.append((key, item))
    return scored


# --------------------------------------------------------------------------- rule matching


def _match_language(lang: Language) -> str:
    """Primary subtag with CLDR's dominant-language rule (``cmn`` → ``zh``)."""
    return lang.prefer_macrolanguage().language or UNDETERMINED


def same_language(a: str | None, b: str | None) -> bool:
    """Same base language: ``ger`` = ``de``, ``pt-BR`` = ``pt`` = ``pt-PT``, ``cmn`` =
    ``zh``. Missing or invalid values count as ``und`` (so ``und`` = ``None``)."""
    return _match_language(_language_or_und(a)) == _match_language(_language_or_und(b))


def matches(rule: str | None, track: str | None) -> bool:
    """Whether a preset rule language matches a track language (one-way).

    The base languages must be the same (:func:`same_language`), and each script, region
    and variant subtag of the rule must also be on the track: rule ``pt`` matches tracks
    ``pt``, ``pt-BR``, ``por``; rule ``pt-BR`` matches only ``pt-BR`` (not ``pt``, not
    ``pt-PT``). A missing or invalid track language is ``und``; ``und`` matches only ``und``.
    An invalid rule matches nothing.
    """
    rule_tag = normalize(rule)
    if rule_tag is None:
        return False
    r, t = _parse(rule_tag), _language_or_und(track)
    if _match_language(r) != _match_language(t):
        return False
    if r.script is not None and r.script != t.script:
        return False
    if r.territory is not None and r.territory != t.territory:
        return False
    return set(r.variants or ()) <= set(t.variants or ())
