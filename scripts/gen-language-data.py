"""Build the language data files of ``reframe.languages`` from ``langcodes`` and ``language_data``.

The files are committed in ``reframe/definitions/data/``, so the product reads them with the
standard library and needs neither library. Each is gzipped JSON with sorted keys; ``--check``
compares the JSON inside, so a different zlib cannot fail it. A file whose JSON is unchanged is
not written again. Needs the dev dependency group (``uv sync``).

- ``language-core.json.gz``: the registry subtags, the alias tables, ISO 639 codes, the
  canonical tag of each language subtag, English names, and the native names of the language
  subtags and the picker list.
- ``language-locale-names.json.gz``: names in each locale and the CLDR matching data, for the
  native name of any other tag.
- ``language-search.json.gz``: the language names of every locale, for the name search.
"""

from __future__ import annotations

import argparse
import gzip
import importlib.metadata
import importlib.resources
import itertools
import json
import re
import string
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from langcodes import Language, data_dicts, language_distance
from langcodes.tag_parser import EXCEPTIONS, LanguageTagError
from language_data.name_data import CODE_TO_NAMES  # type: ignore[import-untyped]
from language_data.names import DISPLAY_SEPARATORS, load_trie  # type: ignore[import-untyped]
from language_data.util import data_filename  # type: ignore[import-untyped]

from reframe.languages import _ISO639_2T, COMMON_VARIANTS, OVERRIDES, SPECIAL_CODES

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "packages" / "reframe" / "src" / "reframe" / "definitions" / "data"
CORE = "language-core.json.gz"
LOCALE_NAMES = "language-locale-names.json.gz"
SEARCH = "language-search.json.gz"

_TAG_SHAPE = re.compile(r"^[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*$")
_MAX_TAG_LENGTH = 64
_REGISTRY_FIELDS = ("Deprecated", "Preferred-Value", "Suppress-Script", "Macrolanguage")
_LANGUAGE_CODE = re.compile(r"[a-z]{2,3}")
_SCRIPT_CODE = re.compile(r"[A-Z][a-z]{3}")
_TERRITORY_CODE = re.compile(r"[A-Z]{2}|[0-9]{3}")
_ALPHABET_OF = {
    **dict.fromkeys(string.ascii_lowercase, string.ascii_lowercase),
    **dict.fromkeys(string.ascii_uppercase, string.ascii_uppercase),
    **dict.fromkeys(string.digits, string.digits),
}


def _registry_records() -> tuple[str, list[dict[str, str]]]:
    text = (
        importlib.resources.files("language_data") / "data" / "language-subtag-registry.txt"
    ).read_text(encoding="utf-8")
    head, *records = text.split("\n%%\n")
    file_date = head.removeprefix("File-Date: ").strip()
    parsed = []
    for record in records:
        fields: dict[str, str] = {}
        for line in record.splitlines():
            if ": " in line and not line.startswith(" "):
                key, value = line.split(": ", 1)
                fields.setdefault(key, value)
        parsed.append(fields)
    return file_date, parsed


def _subtag_range(subtag: str) -> list[str]:
    """``qaa..qtz`` → every subtag in the range; a plain subtag → itself."""
    if ".." not in subtag:
        return [subtag]
    first, last = subtag.split("..")
    alphabets = [_ALPHABET_OF[ch] for ch in first]
    candidates = ("".join(chars) for chars in itertools.product(*alphabets))
    return [s for s in candidates if first <= s <= last]


def _registry(records: list[dict[str, str]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for record in records:
        kind = record["Type"]
        if kind in ("grandfathered", "redundant"):
            continue
        table = out.setdefault(kind, {"subtags": []})
        for subtag in _subtag_range(record["Subtag"]):
            table["subtags"].append(subtag)
            for field in _REGISTRY_FIELDS:
                if field in record:
                    table.setdefault(field, {})[subtag] = record[field]
    for table in out.values():
        table["subtags"].sort()
    out["grandfathered"] = sorted(r["Tag"].lower() for r in records if r["Type"] == "grandfathered")
    return out


def _check_registry(registry: dict[str, Any]) -> None:
    """The library tables that the product derives from the registry must be the registry's."""
    if set(registry["grandfathered"]) != EXCEPTIONS:
        raise SystemExit("langcodes' grandfathered tags are not the registry's")
    suppress = registry["language"].get("Suppress-Script", {})
    if suppress != data_dicts.DEFAULT_SCRIPTS:
        raise SystemExit("langcodes' default scripts are not the registry's Suppress-Script")
    valid = {
        s
        for kind in ("language", "extlang", "script", "region", "variant")
        for s in registry[kind]["subtags"]
    }
    for subtag in valid:
        if not (data_dicts.VALIDITY.match(subtag) or subtag in data_dicts.ALL_SCRIPTS):
            raise SystemExit(f"langcodes does not accept the registry subtag {subtag!r}")
    scripts = (s for s in data_dicts.ALL_SCRIPTS if ".." not in s)
    for subtag in (*_validity_strings(), *scripts):
        if subtag not in valid:
            raise SystemExit(f"langcodes accepts {subtag!r}, which the registry does not have")


def _validity_strings() -> Iterator[str]:
    """Every string that langcodes' validity pattern matches (a finite alternation)."""
    import re._parser as parser  # type: ignore[import-not-found]

    def expand(items: Any) -> list[str]:
        results = [""]
        for op, arg in items:
            name = str(op)
            if name == "AT":
                continue
            if name == "LITERAL":
                options = [chr(arg)]
            elif name == "IN":
                options = []
                for kind, value in arg:
                    if str(kind) == "LITERAL":
                        options.append(chr(value))
                    elif str(kind) == "RANGE":
                        options.extend(chr(c) for c in range(value[0], value[1] + 1))
                    else:
                        raise SystemExit(f"unexpected validity pattern part {kind}")
            elif name == "SUBPATTERN":
                options = expand(arg[3])
            elif name == "BRANCH":
                options = [s for branch in arg[1] for s in expand(branch)]
            else:
                raise SystemExit(f"unexpected validity pattern part {name}")
            results = [r + o for r in results for o in options]
        return results

    yield from expand(parser.parse(data_dicts.VALIDITY.pattern))


def _language(tag: str) -> Language | None:
    """``reframe.languages``' parse of a code: langcodes with the overrides."""
    text = tag.replace("_", "-")
    primary = text.split("-", 1)[0].lower()
    try:
        if primary in OVERRIDES:
            return Language.get(text, normalize=False).update_dict({"language": OVERRIDES[primary]})
        return Language.get(text)
    except (LanguageTagError, ValueError):
        return None


def _canonical(tag: str) -> str | None:
    """``reframe.languages``' canonical tag for a code, or ``None``."""
    if not _TAG_SHAPE.fullmatch(tag) or len(tag) > _MAX_TAG_LENGTH:
        return None
    lang = _language(tag)
    if lang is None or not lang.is_valid():
        return None
    result = lang.to_tag()
    return result if _TAG_SHAPE.fullmatch(result) else None


def _canonical_table(languages: Iterable[str]) -> dict[str, str | None]:
    """Canonical tag of each language subtag and alias, where it is not the subtag itself."""
    codes = set(languages) | {k for k in data_dicts.LANGUAGE_REPLACEMENTS if "-" not in k}
    table: dict[str, str | None] = {}
    for code in codes:
        if code.split("-", 1)[0] in OVERRIDES:
            continue
        lang = Language.get(code)
        tag = lang.to_tag() if lang.is_valid() else None
        if tag is not None and not _TAG_SHAPE.fullmatch(tag):
            tag = None
        if tag != code:
            table[code] = tag
    return table


def _names(kind: re.Pattern[str]) -> dict[str, dict[str, str]]:
    return {code: names for code, names in CODE_TO_NAMES.items() if kind.fullmatch(code)}


def _english(names: dict[str, dict[str, str]]) -> dict[str, str]:
    return {code: n["en"] for code, n in names.items() if "en" in n}


def _listed_tags() -> list[str]:
    tags = {_canonical(code) for code in _ISO639_2T} | {_canonical(v) for v in COMMON_VARIANTS}
    return sorted(t for t in tags if t is not None)


def _native_table(tags: Iterable[str]) -> dict[str, str]:
    """Autonyms of ``tags``; a one-subtag tag only where it differs from its English name."""
    table = {}
    for tag in tags:
        lang = Language.get(tag, normalize=False)
        if lang.language is None or lang.language in SPECIAL_CODES:
            continue
        native = lang.autonym()
        if "-" in tag or native != lang.display_name("en"):
            table[tag] = native
    return table


def _related_locales(code: str) -> set[str]:
    """Locale languages that can name language ``code`` in an autonym: the language of the
    normalised tag of anything that starts with ``code``, and their macrolanguages."""
    related = {code}
    for key in (code, *(k for k in data_dicts.LANGUAGE_REPLACEMENTS if k.split("-")[0] == code)):
        try:
            language = Language.get(key).language
        except (LanguageTagError, ValueError):
            continue
        if language is not None:
            related.add(language)
    macro = data_dicts.NORMALIZED_MACROLANGUAGES
    return related | {macro[r] for r in related if r in macro}


def _locale_language_names(names: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    out = {}
    for code, by_locale in names.items():
        if code == "und":
            kept = dict(by_locale)  # the "Unknown language" placeholder in any locale
        else:
            related = _related_locales(code)
            kept = {loc: n for loc, n in by_locale.items() if loc.split("-")[0] in related}
        kept.pop("en", None)
        if kept:
            out[code] = kept
    return out


def _without_english(names: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    out = {}
    for code, by_locale in names.items():
        kept = {loc: n for loc, n in by_locale.items() if loc != "en"}
        if kept:
            out[code] = kept
    return out


def _search_table(locale: str) -> dict[str, list[str]]:
    """``{result: [normalised names]}`` of a name trie, with the result ``find`` gives: the
    canonical tag, ``""`` for a name whose tag is not valid."""
    trie = load_trie(data_filename(f"trie/{locale}/name_to_language.marisa"))
    grouped: dict[str, list[str]] = {}
    for key, value in trie.items():
        code = value.decode("utf-8")
        found = Language.get(code) if "-" in code else Language.make(language=code)
        grouped.setdefault(_canonical(found.to_tag()) or "", []).append(key)
    for keys in grouped.values():
        keys.sort()
    return grouped


def _english_display() -> dict[str, str]:
    en = Language.get("en")
    return {"separator": en._display_separator(), "pattern": en._display_pattern()}


def build() -> dict[str, Any]:
    """The JSON documents, by file name."""
    file_date, records = _registry_records()
    registry = _registry(records)
    _check_registry(registry)
    language_names = _names(_LANGUAGE_CODE)
    script_names = _names(_SCRIPT_CODE)
    territory_names = _names(_TERRITORY_CODE)
    listed = _listed_tags()
    canonical_tags = {
        t for t in (_canonical(s) for s in registry["language"]["subtags"]) if t is not None
    }
    core = {
        "source": {
            "langcodes": importlib.metadata.version("langcodes"),
            "language_data": importlib.metadata.version("language_data"),
            "registry_file_date": file_date,
        },
        "registry": registry,
        "aliases": {
            "language": data_dicts.LANGUAGE_REPLACEMENTS,
            "territory": data_dicts.TERRITORY_REPLACEMENTS,
            "macrolanguage": data_dicts.NORMALIZED_MACROLANGUAGES,
        },
        "alpha3": {
            "T": data_dicts.LANGUAGE_ALPHA3,
            "B": data_dicts.LANGUAGE_ALPHA3_BIBLIOGRAPHIC,
        },
        "canonical": _canonical_table(registry["language"]["subtags"]),
        "english": {
            "language": _english(language_names),
            "script": _english(script_names),
            "territory": _english(territory_names),
            **_english_display(),
        },
        "native": _native_table(sorted(canonical_tags | set(listed))),
    }
    locale_names = {
        "language": _locale_language_names(language_names),
        "script": _without_english(script_names),
        "territory": _without_english(territory_names),
        "likely": data_dicts.LIKELY_SUBTAGS,
        "distance": data_dicts.LANGUAGE_DISTANCES,
        "regions": {
            "maghreb": sorted(language_distance.MAGHREB),
            "us": sorted(language_distance.US),
            "cnsar": sorted(language_distance.CNSAR),
            "latin_america": sorted(language_distance.LATIN_AMERICA),
            "americas": sorted(language_distance.AMERICAS),
        },
        "default_territory_distance": language_distance.DEFAULT_TERRITORY_DISTANCE,
        "separators": [[k, v] for k, v in DISPLAY_SEPARATORS.items()],
    }
    search = {"en": _search_table("en"), "und": _search_table("und")}
    return {CORE: core, LOCALE_NAMES: locale_names, SEARCH: search}


def encode(document: Any) -> bytes:
    """The JSON text of a document: sorted keys, no spaces, UTF-8."""
    text = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return text.encode("utf-8") + b"\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--check", action="store_true", help="fail when a committed file differs from a new build"
    )
    args = parser.parse_args(argv)
    stale = []
    for name, document in build().items():
        path = DATA_DIR / name
        content = encode(document)
        current = gzip.decompress(path.read_bytes()) if path.is_file() else None
        if current == content:
            continue
        stale.append(name)
        if not args.check:
            path.write_bytes(gzip.compress(content, compresslevel=9, mtime=0))
            print(f"wrote {path.relative_to(REPO_ROOT)} ({len(content)} bytes)", file=sys.stderr)
    if args.check and stale:
        print(
            f"stale language data: {', '.join(stale)}; "
            "run uv run python scripts/gen-language-data.py",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
