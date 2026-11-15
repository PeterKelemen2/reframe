"""The table-based ``reframe.languages`` gives the library-based module's results.

The oracle (``oracle.py``) is the module as it was on ``langcodes`` and ``language_data``. A
difference means a user sees another name, code or search result than before. The full sweeps
are ``slow``; the other tests run a fixed subset of the same corpus.
"""

from __future__ import annotations

import dataclasses
import functools
import importlib.resources
import importlib.util
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

pytest.importorskip("langcodes", reason="needs the dev dependency group (langcodes)")
pytest.importorskip("language_data", reason="needs the dev dependency group (language_data)")

from language_data.name_data import CODE_TO_NAMES  # type: ignore[import-untyped]
from language_data.names import load_trie  # type: ignore[import-untyped]
from language_data.util import data_filename  # type: ignore[import-untyped]

from reframe import languages


def _load_oracle() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_reframe_languages_oracle", Path(__file__).with_name("oracle.py")
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


oracle = _load_oracle()

#: Regions and scripts of the fast subset: the ones the picker and the batch rules meet, plus
#: aliases, ranges, macro-regions and ones whose names differ by locale.
REGION_SAMPLE = (
    "US", "GB", "BR", "PT", "CN", "TW", "HK", "MO", "AT", "CH", "419", "001", "150", "ME", "CD",
    "AF", "IN", "MA", "EG", "MX", "AR", "ES", "CA", "PR", "RS", "BA", "DD", "BU", "QM", "XZ",
    "ZZ", "AA", "172", "EU",
)  # fmt: skip
SCRIPT_SAMPLE = (
    "Latn", "Cyrl", "Arab", "Hans", "Hant", "Hani", "Deva", "Jpan", "Kore", "Grek", "Hebr",
    "Ethi", "Zzzz", "Qaaa", "Qabx", "Brai", "Zyyy", "Aran", "Cyrs", "Kawi",
)  # fmt: skip

#: Inputs that take odd paths through the parser, the alias tables and the name tables.
ODD_INPUTS = (
    "cmn-yue", "es-abc-def-419", "zh-cmn-yue-hak", "zh-cmn-yue-419", "zh-min-nan-hak-TW",
    "zh-min-nan-TW", "zh-min", "zh-cmn-Hans", "zh-yue-HK", "sh-Cyrl", "sh-QU",
    "tgl-PH", "TL-latn", "hbs-RS", "sgn-US", "sgn-BE-FR", "i-klingon", "i-default", "x-foo",
    "en-x-foo", "en-a-bbb-x-c", "en-a-bbb-a-ccc", "en-gb-oed", "art-lojban", "no-bok",
    "und-aaland", "und-hepburn-heploc", "es-abc-419", "de-1901-1901", "de-DE-1901-1996",
    "sl-rozaj-biske-1994", "ca-ES-valencia", "el-polyton", "be-tarask", "en-Dsrt",
    "yue-Hans-CN", "nan-Latn", "kk-Arab", "az-Arab-IR", "en-Latn-US-fonipa", "ja-Latn",
    "ar-001", "es-013", "pt-AO", "en-150", "zh-Hant-SG", "und-US", "und-Latn", "mul-US",
    "zxx-Latn", "mis-DE", "qaa-US", "qtz-Qaaa-QM", "root", "und", "UND", "en_us", " pt_br ",
    "achenés", "achinéz", "Hakka Chinese", "Chinese Traditional", "german language", "Ungarisch",
    "német", "allemand", "アファル語", "Serbian (Montenegro)", "Geji", "Kui (India)",
    "Persian (Afghanistan)", "-en", "e", "Ga", "Maa", "Brazilian Portuguese", "Mandarin",
    "ger", "chi", "fre", "scc", "scr", "ji", "in", "iw", "jw", "mo", "aar", "nor", "mol",
    "twi", "bih", "bh", "cnr", "drw", "prs", "swc", "tnf",
)  # fmt: skip


@functools.cache
def _registry() -> list[dict[str, list[str]]]:
    """The IANA registry records, every value of each field."""
    text = (
        importlib.resources.files("language_data") / "data" / "language-subtag-registry.txt"
    ).read_text(encoding="utf-8")
    records = []
    for record in text.split("\n%%\n")[1:]:
        fields: dict[str, list[str]] = {}
        for line in record.splitlines():
            if ": " in line and not line.startswith(" "):
                key, value = line.split(": ", 1)
                fields.setdefault(key, []).append(value)
        records.append(fields)
    return records


def _subtags(kind: str) -> list[str]:
    return [r["Subtag"][0] for r in _registry() if r["Type"][0] == kind and "Subtag" in r]


def _plain(subtags: Iterable[str]) -> list[str]:
    """Range records as their two ends (``qaa..qtz`` → ``qaa``, ``qtz``)."""
    return [s for subtag in subtags for s in subtag.split("..")]


@functools.cache
def _listed_bases() -> list[str]:
    return [e.tag for e in oracle.language_list() if not e.variant]


def _registry_tags() -> list[str]:
    """Every registry subtag alone (a script, region or variant is not a language), upper-case
    forms, every extlang with its prefix, every grandfathered and redundant tag, every variant
    with its prefixes, every deprecated script, region and variant on a language, and every
    alias of the tables."""
    tags = _plain(_subtags("language"))
    tags += [t.upper() for t in tags[::7]]
    for kind in ("script", "region", "variant"):
        tags += [form for s in _plain(_subtags(kind)) for form in (s, s.lower())]
    for record in _registry():
        kind = record["Type"][0]
        if kind == "extlang":
            tags += [record["Subtag"][0], *(f"{p}-{record['Subtag'][0]}" for p in record["Prefix"])]
        elif kind in ("grandfathered", "redundant"):
            tags += [record["Tag"][0], record["Tag"][0].upper()]
        elif kind == "variant":
            variant = record["Subtag"][0]
            tags += [f"und-{variant}", *(f"{p}-{variant}" for p in record.get("Prefix", []))]
        if kind in ("script", "region", "variant") and "Deprecated" in record:
            tags += [f"{base}-{record['Subtag'][0]}" for base in ("en", "sr", "zh", "und")]
    from langcodes import data_dicts

    tags += list(data_dicts.LANGUAGE_REPLACEMENTS)
    tags += [
        f"{base}-{region}"
        for region in data_dicts.TERRITORY_REPLACEMENTS
        for base in ("en", "pt", "und")
    ]
    return [*tags, *ODD_INPUTS]


def _combined(bases: Iterable[str], regions: Iterable[str], scripts: Iterable[str]) -> list[str]:
    regions, scripts = list(regions), list(scripts)
    return [f"{b}-{x}" for b in bases for x in (*regions, *scripts)]


def _call(fn: Callable[[Any], Any], value: Any) -> Any:
    try:
        result = fn(value)
    except Exception as exc:
        return ("raises", type(exc).__name__)
    if dataclasses.is_dataclass(result) and not isinstance(result, type):
        return dataclasses.astuple(result)
    return result


TAG_FUNCTIONS = (
    "normalize",
    "validate",
    "english_name",
    "native_name",
    "to_matroska_legacy",
    "to_mp4",
    "to_matroska_ietf",
    "base_language",
    "short_code",
    "entry",
)


def _differences(values: Iterable[str], functions: Iterable[str]) -> list[tuple[Any, ...]]:
    diffs = []
    for name in functions:
        ours, theirs = getattr(languages, name), getattr(oracle, name)
        for value in values:
            got, want = _call(ours, value), _call(theirs, value)
            if got != want:
                diffs.append((name, value, want, got))
    return diffs


def test_registry_aliases_extlangs_grandfathered_and_odd_tags() -> None:
    assert _differences(_registry_tags(), TAG_FUNCTIONS)[:20] == []


def test_listed_languages_with_sample_regions_and_scripts() -> None:
    tags = _combined(_listed_bases(), REGION_SAMPLE, SCRIPT_SAMPLE)
    functions = ("normalize", "validate", "english_name", "native_name", "entry")
    assert _differences(tags, functions)[:20] == []


@pytest.mark.slow
def test_listed_languages_with_every_region_and_script() -> None:
    regions = _plain(_subtags("region"))
    scripts = _plain(_subtags("script"))
    tags = _combined(_listed_bases(), regions, scripts)
    functions = ("normalize", "english_name", "native_name", "to_matroska_legacy", "to_mp4")
    assert _differences(tags, functions)[:20] == []


@pytest.mark.slow
def test_every_registry_language_with_a_region_and_a_script() -> None:
    """Native names of languages outside the list, named in their own locales."""
    tags = _combined(_plain(_subtags("language")), ("US", "CN", "IN"), ("Latn", "Arab"))
    assert _differences(tags, ("normalize", "english_name", "native_name"))[:20] == []


def test_language_list() -> None:
    ours = [dataclasses.astuple(e) for e in languages.language_list()]
    assert ours == [dataclasses.astuple(e) for e in oracle.language_list()]


@functools.cache
def _locale_names() -> list[str]:
    """The names of every listed language in every CLDR locale."""
    bases = [b for b in _listed_bases() if b not in oracle.SPECIAL_CODES]
    return sorted({n for b in bases for n in CODE_TO_NAMES.get(b, {}).values()})


def _with_suffixes(names: Iterable[str]) -> list[str]:
    """Names with words added or letters cut: the prefix match of the name tables."""
    return [form for n in names for form in (f"{n} language", f"{n}isch", n[:-2], f"{n[:4]}x")]


def test_names_of_listed_languages_in_every_locale() -> None:
    assert _differences(_locale_names(), ("normalize",))[:20] == []


def test_prefix_matches_of_names() -> None:
    assert _differences(_with_suffixes(_locale_names()[::5]), ("normalize",))[:20] == []


@pytest.mark.slow
def test_every_key_of_the_name_tables() -> None:
    keys = [
        key
        for locale in ("en", "und")
        for key, _ in load_trie(data_filename(f"trie/{locale}/name_to_language.marisa")).items()
    ]
    names = sorted({*keys, *_with_suffixes(_locale_names())})
    assert _differences(names, ("normalize",))[:20] == []


def _tags_of(result: list[Any]) -> list[str]:
    return [item.tag for item in result]


def _search_differences(queries: Iterable[str], favourites: tuple[str, ...] = ()) -> list[Any]:
    diffs = []
    for query in queries:
        got = _tags_of(languages.search(query, favourites=favourites))
        want = _tags_of(oracle.search(query, favourites=favourites))
        if got != want:
            diffs.append((query, want[:5], got[:5]))
    return diffs


def _picker_queries() -> list[str]:
    queries: list[str] = []
    for e in oracle.language_list():
        codes = (e.tag, e.iso639_1, e.iso639_2b, e.iso639_2t, e.iso639_3)
        queries += [c for c in codes if c] + [e.english_name, e.native_name, e.english_name[:3]]
    return [*queries, *ODD_INPUTS, "", " ", "e", "zzzzqqq", "de-AT", "yue", "Cantonese"]


def test_search_picker_queries() -> None:
    assert _search_differences(_picker_queries())[:20] == []
    favourites = ("hun", "en", "pt_BR", "yue", "not a language", "sr-Latn-RS")
    assert _search_differences(["", "e", "portug", "yue", "ser"], favourites) == []


def test_search_names_in_other_locales() -> None:
    assert _search_differences(_locale_names()[::40])[:20] == []


@pytest.mark.slow
def test_search_every_name_in_every_locale() -> None:
    assert _search_differences(_locale_names())[:20] == []


@functools.cache
def _case_maps_to_ascii() -> dict[str, str]:
    """Every non-ASCII character with an ASCII letter in its lower, upper, title or casefold
    form, mapped to the ASCII text it stands in for (the Kelvin sign: ``k``, the ligature
    U+FB01: ``fi``)."""
    found: dict[str, str] = {}
    for code in range(0x80, sys.maxunicode + 1):
        char = chr(code)
        for form in (char.lower(), char.upper(), char.title(), char.casefold()):
            ascii_part = "".join(ch for ch in form if ch.isascii() and ch.isalpha())
            if form != char and ascii_part:
                found[char] = ascii_part.lower()
                break
    return found


def _case_mapped_inputs() -> list[str]:
    """Codes and names of the picker list, each letter run that one of
    :func:`_case_maps_to_ascii` stands in for replaced by it."""
    words: set[str] = {"Ko", "Ka", "UOK", "Kore", "en-K", "sk-SK", "ko-KR", "it-IT"}
    for e in oracle.language_list():
        for value in (e.tag, e.iso639_1, e.iso639_2b, e.iso639_3, e.english_name, e.native_name):
            if value:
                words |= {value, value.upper(), value.capitalize()}
    inputs: set[str] = set()
    for char, text in _case_maps_to_ascii().items():
        for word in words:
            for form in {text, text.upper(), text.capitalize()}:
                start = word.find(form)
                while start != -1:
                    inputs.add(word[:start] + char + word[start + len(form) :])
                    start = word.find(form, start + 1)
    return sorted(inputs)


def test_the_kelvin_sign_is_not_a_k() -> None:
    assert _case_maps_to_ascii()["\u212a"] == "k"
    assert languages.normalize("\u212ao") == oracle.normalize("\u212ao") == "fuj"
    assert languages.normalize("UO\u212a") is oracle.normalize("UO\u212a") is None


def test_characters_whose_case_forms_are_ascii() -> None:
    inputs = _case_mapped_inputs()
    assert _differences(inputs, TAG_FUNCTIONS)[:20] == []
    assert _search_differences(inputs)[:20] == []


def _match_tags() -> list[str | None]:
    listed = [e.tag for e in oracle.language_list()]
    extra = ["cmn", "yue", "zh-Hans-CN", "de-DE-1901", "de-1901", "pt_br", "por", "garbage!"]
    return [*listed, *extra, "sr-Latn-RS", "zsm", "arb", "und", None]


def test_matches_and_same_language() -> None:
    tags = _match_tags()
    diffs = []
    for rule in tags[::3]:
        for track in tags:
            for name in ("matches", "same_language"):
                got = getattr(languages, name)(rule, track)
                if got != getattr(oracle, name)(rule, track):
                    diffs.append((name, rule, track))
    assert diffs[:20] == []


tag_like = st.from_regex(r"\A[A-Za-z]{2,3}([-_][A-Za-z0-9]{1,8}){0,4}\Z")


@settings(max_examples=400, suppress_health_check=[HealthCheck.too_slow])
@given(st.one_of(tag_like, st.from_regex(r"\A[A-Za-z]{2,8}\Z"), st.text(max_size=16)))
def test_property_same_results_for_any_input(value: str) -> None:
    assert _differences([value], TAG_FUNCTIONS) == []


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(st.one_of(tag_like, st.text(max_size=12)))
def test_property_same_search_for_any_query(query: str) -> None:
    assert _search_differences([query]) == []
