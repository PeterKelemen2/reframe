"""``reframe.languages``: normalisation, container codes, names, search and real-tool checks."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from reframe import languages
from reframe.languages import (
    COMMON_VARIANTS,
    SPECIAL_CODES,
    LanguageEntry,
    base_language,
    english_name,
    entry,
    join_short_codes,
    language_list,
    matches,
    native_name,
    normalize,
    picker_label,
    same_language,
    search,
    short_code,
    to_matroska_ietf,
    to_matroska_legacy,
    to_mp4,
    validate,
)

#: The pydantic ``LanguageTag`` pattern (reframe.models.base).
TAG_PATTERN = re.compile(r"^[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*$")

#: The 20 ISO 639-2 languages whose /B and /T codes differ: (B, T, ISO 639-1).
B_T_PAIRS = [
    ("alb", "sqi", "sq"),
    ("arm", "hye", "hy"),
    ("baq", "eus", "eu"),
    ("bur", "mya", "my"),
    ("chi", "zho", "zh"),
    ("cze", "ces", "cs"),
    ("dut", "nld", "nl"),
    ("fre", "fra", "fr"),
    ("geo", "kat", "ka"),
    ("ger", "deu", "de"),
    ("gre", "ell", "el"),
    ("ice", "isl", "is"),
    ("mac", "mkd", "mk"),
    ("mao", "mri", "mi"),
    ("may", "msa", "ms"),
    ("per", "fas", "fa"),
    ("rum", "ron", "ro"),
    ("slo", "slk", "sk"),
    ("tib", "bod", "bo"),
    ("wel", "cym", "cy"),
]


@pytest.mark.parametrize(("b", "t", "two"), [p for p in B_T_PAIRS if p[0] in ("chi", "fre", "ger")])
def test_bibliographic_and_terminology_pairs(b: str, t: str, two: str) -> None:
    for code in (b, t, two, b.upper(), t.title()):
        assert normalize(code) == two
        assert to_matroska_legacy(code) == b
        assert to_mp4(code) == t
        assert to_matroska_ietf(code) == two


def test_exactly_twenty_codes_differ_between_b_and_t() -> None:
    differ = {t for t in languages._ISO639_2T if to_matroska_legacy(t) != to_mp4(t)}
    assert differ == {t for _, t, _ in B_T_PAIRS}


def test_every_iso639_2_code_keeps_its_meaning() -> None:
    """Each /T code and each /B code of ``B_T_PAIRS`` maps back to itself. Only ``tgl`` needs an
    override."""
    assert len(languages._ISO639_2T) == 418
    for code in languages._ISO639_2T:
        assert normalize(code) is not None, code
        assert to_mp4(code) == code
    for b, _, _ in B_T_PAIRS:
        assert to_matroska_legacy(b) == b


@pytest.mark.parametrize(
    ("value", "tag"),
    [
        ("DE", "de"),
        ("hun", "hu"),
        ("PT-br", "pt-BR"),
        ("pt_br", "pt-BR"),
        ("ZH-HANT", "zh-Hant"),
        ("sr_cyrl", "sr-Cyrl"),
        ("en-us", "en-US"),
        ("  fr-CA  ", "fr-CA"),
        ("zh-yue", "yue"),
        ("cmn", "cmn"),
        ("tlh", "tlh"),
        # deprecated codes
        ("ji", "yi"),
        ("scc", "sr"),
        ("scr", "hr"),
        # overrides
        ("TGL", "tl"),
        ("tgl-PH", "tl-PH"),
        ("fil", "fil"),
        ("hbs", "sh"),
        # names
        ("german", "de"),
        ("francais", "fr"),
        ("Brazilian Portuguese", "pt-BR"),
        ("Cantonese", "yue"),
        ("Serbo-Croatian", "sh"),
        ("allemand", "de"),
    ],
)
def test_normalize(value: str, tag: str) -> None:
    assert normalize(value) == tag
    assert validate(value) is None


@pytest.mark.parametrize("code", SPECIAL_CODES)
def test_special_codes(code: str) -> None:
    assert normalize(code) == code
    assert normalize(code.upper()) == code
    assert to_matroska_legacy(code) == code
    assert to_mp4(code) == code
    assert to_matroska_ietf(code) == code
    assert base_language(code) == code
    assert native_name(code) == english_name(code)


def test_special_code_names() -> None:
    assert english_name("und") == "Undetermined"
    assert english_name("mul") == "Multiple languages"
    assert english_name("zxx") == "No linguistic content"
    assert english_name("mis") == "Uncoded languages"


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        (None, "No language given"),
        ("   ", "No language given"),
        ("xx", "not a known language name or code"),
        ("jp", "not a known language name or code"),
        ("qwertyuiop asdf", "not a known language name or code"),
        ("x-foo", "private-use tags"),
        ("xx-US", "'xx' is not a known language code"),
        ("en-Latnx", "'latnx' is not a known variant"),
        ("en-US-US", "not a valid language tag (BCP 47)"),
        ("en-a-bbb-a-ccc", "not a valid language tag (BCP 47)"),
        ("a" + " " * 40 + "1", "not a known language name or code"),
        ("A\x00:¿", "not a known language name or code"),
        ("Ger\x01man", "not a known language name or code"),
        ("G" * 101, "not a known language name or code"),
        ("en--US", "not a known language name or code"),
        ("toolongcode-x", "not a known language name or code"),
        ("-en", "not a known language name or code"),
    ],
)
def test_invalid(value: str | None, reason: str) -> None:
    assert normalize(value) is None
    problem = validate(value)
    assert problem is not None
    assert reason in problem
    # Conversions and names never raise: invalid input is "und".
    assert to_matroska_legacy(value) == "und"
    assert to_mp4(value) == "und"
    assert to_matroska_ietf(value) == "und"
    assert english_name(value) == "Undetermined"
    assert short_code(value) == "UND"
    assert base_language(value) == "und"
    assert entry(value) is None


def test_validate_reports_script_and_region() -> None:
    assert validate("de-Abcd") == "'de-Abcd': 'Abcd' is not a known script."
    assert validate("de-AB") == "'de-AB': 'AB' is not a known region."
    assert validate("de-1234") == "'de-1234': '1234' is not a known variant."


@pytest.mark.parametrize(
    ("value", "legacy", "mp4", "ietf"),
    [
        ("hu", "hun", "hun", "hu"),
        ("pt-BR", "por", "por", "pt-BR"),
        ("es-419", "spa", "spa", "es-419"),
        ("zh-Hans", "chi", "zho", "zh-Hans"),
        ("sr-Latn", "srp", "srp", "sr-Latn"),
        ("fr-CA", "fre", "fra", "fr-CA"),
        ("iw", "heb", "heb", "he"),
        ("in", "ind", "ind", "id"),
        ("jw", "jav", "jav", "jv"),
        ("mo", "rum", "ron", "ro"),
        ("tl", "tgl", "tgl", "tl"),
        ("tgl", "tgl", "tgl", "tl"),
        ("fil", "fil", "fil", "fil"),
        ("sh", "und", "und", "sh"),
        # languages without an ISO 639-2 code: the macrolanguage, else und
        ("yue", "chi", "zho", "yue"),
        ("arb", "ara", "ara", "arb"),
        ("zsm", "may", "msa", "zsm"),
        ("aaa", "und", "und", "aaa"),
        # local use and collective codes are ISO 639-2
        ("qaa", "qaa", "qaa", "qaa"),
        ("qtz", "qtz", "qtz", "qtz"),
        ("sgn", "sgn", "sgn", "sgn"),
    ],
)
def test_container_codes(value: str, legacy: str, mp4: str, ietf: str) -> None:
    assert to_matroska_legacy(value) == legacy
    assert to_mp4(value) == mp4
    assert to_matroska_ietf(value) == ietf


def test_base_language() -> None:
    assert base_language("pt-BR") == "pt"
    assert base_language("ger") == "de"
    assert base_language("sr-Latn") == "sr"
    assert base_language("cmn") == "cmn"
    assert base_language(None) == "und"


@pytest.mark.parametrize(
    ("value", "english", "native"),
    [
        ("hu", "Hungarian", "magyar"),
        ("ger", "German", "Deutsch"),
        ("pt-BR", "Portuguese (Brazil)", "português (Brasil)"),
        ("zh-Hans", "Chinese (Simplified)", "中文\uff08简体\uff09"),
        ("tl", "Tagalog", "Tagalog"),
        ("ace", "Acehnese", "Acehnese"),  # no CLDR autonym: the English name
        ("und", "Undetermined", "Undetermined"),
    ],
)
def test_names(value: str, english: str, native: str) -> None:
    assert english_name(value) == english
    assert native_name(value) == native


def test_native_name_capitalised_for_templates() -> None:
    assert native_name("hu", capitalize=True) == "Magyar"
    assert native_name("pt-BR", capitalize=True) == "Português (Brasil)"
    assert native_name("ja", capitalize=True) == "日本語"
    assert native_name("de", capitalize=True) == "Deutsch"


def test_short_codes() -> None:
    assert short_code("hu") == "HUN"
    assert short_code("de") == "GER"
    assert short_code("pt-BR") == "POR"
    assert join_short_codes(["hu", "eng", "en", None]) == "HUN-ENG-UND"
    assert join_short_codes(["hu", "en"], sep=".") == "HUN.ENG"
    assert join_short_codes([]) == ""


def test_picker_label() -> None:
    assert picker_label("hu") == "Hungarian · hun (ISO 639-2) · hu (BCP 47)"
    assert picker_label("de") == "German · ger (ISO 639-2) · de (BCP 47)"
    assert picker_label("de", container="webm") == "German · ger (ISO 639-2) · de (BCP 47)"
    assert picker_label("de", container="mp4") == "German · deu (ISO 639-2) · de (BCP 47)"
    assert picker_label("pt_br") == "Portuguese (Brazil) · por (ISO 639-2) · pt-BR (BCP 47)"
    assert picker_label("sh") == "Serbo-Croatian · und (ISO 639-2) · sh (BCP 47)"


def test_language_list_scope_and_order() -> None:
    items = language_list()
    assert items is language_list()  # cached
    tags = [item.tag for item in items]
    assert len(tags) == len(set(tags))
    names = [item.english_name for item in items]
    assert len(names) == len(set(names))
    assert [languages._fold(n) for n in names] == sorted(languages._fold(n) for n in names)
    # ISO 639-2 codes, then the common variants
    assert len(items) == 418 + len(COMMON_VARIANTS)
    assert set(COMMON_VARIANTS) <= set(tags)
    assert set(SPECIAL_CODES) <= set(tags)
    assert {"hu", "de", "tl", "fil", "ang"} <= set(tags)
    # not in the list: collective codes, local use, ISO 639-3-only languages
    assert not {"sgn", "art", "qaa", "yue", "cmn", "sh"} & set(tags)
    with_639_1 = {item.iso639_1 for item in items if not item.variant and item.iso639_1}
    assert len(with_639_1) >= 180


def test_language_entry_fields() -> None:
    by_tag = {item.tag: item for item in language_list()}
    assert by_tag["de"] == LanguageEntry(
        tag="de",
        iso639_1="de",
        iso639_2b="ger",
        iso639_2t="deu",
        iso639_3="deu",
        english_name="German",
        native_name="Deutsch",
        variant=False,
    )
    pt_br = by_tag["pt-BR"]
    assert (pt_br.iso639_1, pt_br.iso639_2b, pt_br.iso639_3, pt_br.variant) == (
        "pt",
        "por",
        "por",
        True,
    )
    und = by_tag["und"]
    assert (und.iso639_1, und.iso639_2b, und.iso639_2t, und.iso639_3) == (None, "und", "und", "und")
    assert by_tag["tl"].iso639_2b == "tgl"


def test_entry_outside_the_list() -> None:
    yue = entry("Cantonese")
    assert yue is not None
    assert (yue.tag, yue.iso639_2b, yue.iso639_3, yue.english_name) == (
        "yue",
        "chi",
        "yue",
        "Cantonese",
    )
    sh = entry("sh")
    assert sh is not None
    assert (sh.iso639_1, sh.iso639_2b, sh.iso639_3) == ("sh", "und", "hbs")


def tags_of(result: list[LanguageEntry]) -> list[str]:
    return [item.tag for item in result]


@pytest.mark.parametrize(
    ("query", "first"),
    [
        ("magyar", ["hu"]),
        ("magy", ["hu"]),
        ("Deutsch", ["de"]),
        ("por", ["pt", "pt-BR", "pt-PT"]),
        ("pt", ["pt", "pt-BR", "pt-PT"]),
        ("pt-br", ["pt-BR"]),
        ("PT_BR", ["pt-BR"]),
        ("brazil", ["pt-BR"]),
        ("chinese", ["zh", "zh-Hans", "zh-Hant"]),
        ("francais", ["fr"]),
        ("iw", ["he"]),
        ("sr-latn", ["sr-Latn"]),
    ],
)
def test_search_ranking(query: str, first: list[str]) -> None:
    assert tags_of(search(query))[: len(first)] == first


def test_search_rank_order() -> None:
    # exact code, then name prefix, then word prefix, then substring
    result = tags_of(search("ger"))
    assert result[0] == "de"
    assert "nds" in result  # Low German: word prefix "german"
    result = tags_of(search("pt"))
    assert result[:3] == ["pt", "pt-BR", "pt-PT"]
    assert "egy" in result  # Egyptian: substring
    assert result.index("egy") > 2


def test_search_code_beats_name() -> None:
    # "Ga" is the English name of gaa, but "ga" is the code of Irish: codes come first.
    assert tags_of(search("Ga"))[0] == "ga"
    assert "gaa" in tags_of(search("Ga"))


def test_search_favourites_first() -> None:
    favourites = ["hun", "en", "pt_BR", "yue", "not a language", "hu"]
    result = search("", favourites=favourites)
    assert tags_of(result)[:4] == ["hu", "en", "pt-BR", "yue"]
    assert len(result) == len(language_list()) + 1  # yue is not in the list
    assert len(set(tags_of(result))) == len(result)
    # with a query: matching favourites first, then the other matches
    assert tags_of(search("e", favourites=["hu", "en"]))[0] == "en"
    assert tags_of(search("portug", favourites=["pt-BR"]))[:2] == ["pt-BR", "pt"]
    assert tags_of(search("yue", favourites=["yue"])) == ["yue"]


def test_search_limit_and_no_match() -> None:
    assert len(search("", limit=5)) == 5
    assert len(search("e", limit=3)) == 3
    assert search("zzzzqqq") == []
    assert search("   ") == list(language_list())


def test_search_finds_tags_and_names_outside_the_list() -> None:
    assert tags_of(search("de-AT")) == ["de-AT"]
    assert tags_of(search("yue")) == ["yue"]
    assert tags_of(search("Cantonese")) == ["yue"]
    assert tags_of(search("allemand"))[0] == "de"  # French name for German
    # one-letter queries do not add a language named "E"
    assert "eee" not in tags_of(search("e"))


@pytest.mark.parametrize(
    ("a", "b", "same"),
    [
        ("ger", "de", True),
        ("pt-BR", "pt-PT", True),
        ("zh-Hans", "chi", True),
        ("cmn", "zh", True),
        ("yue", "zh", False),
        ("tl", "fil", False),
        ("sh", "sr", False),
        ("und", None, True),
        ("und", "garbage!", True),
        (None, None, True),
        ("und", "en", False),
    ],
)
def test_same_language(a: str | None, b: str | None, same: bool) -> None:
    assert same_language(a, b) is same
    assert same_language(b, a) is same


@pytest.mark.parametrize(
    ("rule", "track", "result"),
    [
        ("pt", "pt-BR", True),
        ("pt", "por", True),
        ("pt-BR", "pt", False),
        ("pt-BR", "pt-PT", False),
        ("pt-BR", "pt_br", True),
        ("de", "ger", True),
        ("zh", "zh-Hans", True),
        ("zh-Hans", "zh-Hant", False),
        ("zh-Hans", "zh-Hans-CN", True),
        ("zh", "cmn", True),
        ("de-1901", "de-DE-1901", True),
        ("de-1901", "de-DE", False),
        ("und", None, True),
        ("und", "en", False),
        ("en", None, False),
        ("garbage!", "en", False),
    ],
)
def test_matches(rule: str | None, track: str | None, result: bool) -> None:
    assert matches(rule, track) is result


def test_container_codes_round_trip_for_every_entry() -> None:
    for item in language_list():
        base = base_language(item.tag)
        assert normalize(to_matroska_legacy(item.tag)) == base, item.tag
        assert normalize(to_mp4(item.tag)) == base, item.tag
        assert normalize(item.tag) == item.tag, item.tag
        forms = {
            "code": item.iso639_2b if not item.variant else item.tag,
            "upper": item.tag.upper(),
            "underscore": item.tag.replace("-", "_"),
            "name": item.english_name,
            "native": item.native_name,
        }
        for form, value in forms.items():
            tag = normalize(value)
            assert tag is not None, (item.tag, form)
            assert normalize(tag) == tag, (item.tag, form)
            if form in ("upper", "underscore") or (form == "code" and item.variant):
                assert tag == item.tag, (item.tag, form)
            if form == "code" and not item.variant:
                assert tag == base_language(item.tag), (item.tag, form)


def test_every_name_in_the_list_normalizes() -> None:
    """English names give the entry; native names give the same language. A name that is
    also a code means the code (gaa "Ga" → Irish ``ga``; Masai's autonym "Maa" → ``maa``)."""
    as_code = []
    for item in language_list():
        for name in (item.english_name, item.native_name):
            tag = normalize(name)
            assert tag is not None, name
            assert normalize(name.upper()) == tag, name
            if languages._normalize_code(name) not in (None, item.tag):
                as_code.append(name)
            elif name == item.english_name:
                assert tag == item.tag, name
            else:
                # Native names can be shared (Akan: ak, fat, twi): the same language
                assert same_language(tag, item.tag), name
    assert sorted(as_code) == ["Ga", "Maa"]


def _search_keys(item: LanguageEntry) -> list[str]:
    """The keys that must find ``item`` first: its tag, its ISO codes (a variant shares them
    with its base language, so it has none) and its English name, unless that name is another
    language's code (gaa "Ga" is Irish ``ga``)."""
    keys = [item.tag]
    if not item.variant:
        keys += [c for c in (item.iso639_1, item.iso639_2b, item.iso639_2t, item.iso639_3) if c]
    code_meaning = languages._normalize_code(item.english_name)
    if code_meaning in (None, item.tag):
        keys.append(item.english_name)
    return keys


def test_search_finds_every_entry_first() -> None:
    skipped = []
    for item in language_list():
        for key in _search_keys(item):
            assert search(key)[0] == item, (item.tag, key)
        if item.english_name not in _search_keys(item):
            skipped.append(item.tag)
    assert skipped == ["gaa"]  # the only name that is another language's code


tag_like = st.from_regex(r"\A[A-Za-z]{2,3}([-_][A-Za-z0-9]{2,4}){0,2}\Z")


@settings(max_examples=500, suppress_health_check=[HealthCheck.too_slow])
@given(st.one_of(tag_like, st.text(max_size=12)))
def test_property_normalize_is_idempotent_and_total(value: str) -> None:
    tag = normalize(value)
    assert (validate(value) is None) == (tag is not None)
    if tag is not None:
        assert normalize(tag) == tag
        assert TAG_PATTERN.fullmatch(tag)
        assert len(tag) <= 64
    for code in (to_matroska_legacy(value), to_mp4(value)):
        assert re.fullmatch(r"[a-z]{3}", code)
    assert to_matroska_ietf(value) == (tag or "und")
    english_name(value)
    native_name(value)


def _tool(name: str) -> str:
    from reframe.tools.discovery import locate_tools

    location = locate_tools().get(name)  # type: ignore[call-overload]
    if location is not None and location.path is not None and location.problem is None:
        return str(location.path)
    found = shutil.which(name)
    if found is None:
        pytest.skip(f"{name} not found")
    return found


def _ffmpeg_tools() -> tuple[str, str]:
    from reframe_testing import media

    ffmpeg, ffprobe = media.find_ffmpeg(), media.find_ffprobe()
    assert ffmpeg is not None
    assert ffprobe is not None
    return ffmpeg, ffprobe


def _mux(ffmpeg: str, out: Path, language: str) -> None:
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=d=0.2",
            "-c:a",
            "aac",
            "-metadata:s:a:0",
            f"language={language}",
            str(out),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )


def _probe_language(ffprobe: str, path: Path) -> str | None:
    out = subprocess.run(
        [ffprobe, "-v", "error", "-of", "json", "-show_entries", "stream_tags", str(path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    tags: dict[str, Any] = json.loads(out.stdout)["streams"][0].get("tags", {})
    language = tags.get("language")
    return None if language is None else str(language)


@pytest.mark.needs_ffmpeg
@pytest.mark.parametrize(
    ("container", "written", "read_back"),
    [
        ("mkv", "ger", "ger"),
        ("mkv", "de", "de"),
        ("mkv", "pt-BR", "pt-BR"),
        ("mkv", "und", None),
        ("mp4", "deu", "deu"),
        ("mp4", "ger", "ger"),
        ("mp4", "de", None),
        ("mp4", "pt-BR", None),
        ("mp4", "und", "und"),
    ],
)
def test_ffmpeg_writes_language_verbatim(
    tmp_path: Path, container: str, written: str, read_back: str | None
) -> None:
    ffmpeg, ffprobe = _ffmpeg_tools()
    out = tmp_path / f"a.{container}"
    _mux(ffmpeg, out, written)
    assert _probe_language(ffprobe, out) == read_back


@pytest.mark.needs_ffmpeg
def test_ffmpeg_gets_container_codes_right(tmp_path: Path) -> None:
    ffmpeg, ffprobe = _ffmpeg_tools()
    for tag in ("de", "pt-BR", "zh-Hans"):
        mkv, mp4 = tmp_path / "a.mkv", tmp_path / "a.mp4"
        _mux(ffmpeg, mkv, to_matroska_legacy(tag))
        _mux(ffmpeg, mp4, to_mp4(tag))
        assert _probe_language(ffprobe, mkv) == to_matroska_legacy(tag)
        assert _probe_language(ffprobe, mp4) == to_mp4(tag)


def _mkvmerge_language(mkvmerge: str, path: Path) -> tuple[str | None, str | None]:
    out = subprocess.run(
        [mkvmerge, "-J", str(path)], check=True, capture_output=True, text=True, timeout=60
    )
    props: dict[str, Any] = json.loads(out.stdout)["tracks"][0]["properties"]
    return props.get("language"), props.get("language_ietf")


def _propedit(mkvpropedit: str, path: Path, *sets: str) -> None:
    args = [arg for value in sets for arg in ("--set", value)]
    subprocess.run(
        [mkvpropedit, str(path), "--edit", "track:a1", *args],
        check=True,
        capture_output=True,
        timeout=60,
    )


@pytest.mark.needs_ffmpeg
def test_ffprobe_does_not_show_language_ietf(tmp_path: Path) -> None:
    ffmpeg, ffprobe = _ffmpeg_tools()
    mkvpropedit = _tool("mkvpropedit")
    path = tmp_path / "a.mkv"
    _mux(ffmpeg, path, "por")
    _propedit(mkvpropedit, path, "language-ietf=pt-BR")
    assert _probe_language(ffprobe, path) == "por"
    _propedit(mkvpropedit, path, "language-ietf=fr")
    assert _probe_language(ffprobe, path) == "por"
    # language= writes both elements (legacy closest ISO 639-2/B)
    _propedit(mkvpropedit, path, "language=zh-Hans")
    assert _probe_language(ffprobe, path) == "chi"


#: Tags for the mkvpropedit cross-check (all accepted by mkvpropedit).
MKVTOOLNIX_TAGS = [
    "pt-BR",
    "yue",
    "cmn",
    "nan",
    "tl",
    "tgl",
    "fil",
    "sh",
    "hbs",
    "sr-Latn",
    "es-419",
    "zh-Hans",
    "zh-Hant",
    "iw",
    "mul",
    "zxx",
    "mis",
    "und",
    "qaa",
    "sgn",
    "chi",
    "zho",
    "fre",
    "fra",
    "deu",
    "nb",
    "no",
    "arb",
    "swh",
    "zsm",
    "aaa",
    "en-US",
    "hu",
    "el",
]


@pytest.mark.needs_ffmpeg
def test_mkvpropedit_agrees_with_our_matroska_codes(tmp_path: Path) -> None:
    """``mkvpropedit --set language=<tag>`` writes legacy + IETF; ours must be the same."""
    ffmpeg, _ = _ffmpeg_tools()
    mkvpropedit, mkvmerge = _tool("mkvpropedit"), _tool("mkvmerge")
    source = tmp_path / "source.mkv"
    _mux(ffmpeg, source, "ger")
    path = tmp_path / "a.mkv"
    for tag in MKVTOOLNIX_TAGS:
        shutil.copyfile(source, path)
        _propedit(mkvpropedit, path, f"language={tag}")
        expected = (to_matroska_legacy(tag), to_matroska_ietf(tag))
        assert _mkvmerge_language(mkvmerge, path) == expected, tag


#: Tags where ``mkvpropedit --set language=<tag>`` writes another legacy code than Reframe;
#: the IETF tag is the same.
MKVTOOLNIX_DIFFERENT_LEGACY = {
    "ase": ("sgn", "und"),
    "bfi": ("sgn", "und"),
    "fsl": ("sgn", "und"),
    "gsg": ("sgn", "und"),
    "pes": ("und", "per"),
    "ekk": ("und", "est"),
    "kmr": ("und", "kur"),
    "ckb": ("und", "kur"),
    "azb": ("und", "aze"),
    "bcc": ("und", "bal"),
}


@pytest.mark.needs_ffmpeg
def test_mkvpropedit_legacy_differences_and_explicit_pairs(tmp_path: Path) -> None:
    """For these tags mkvpropedit's own legacy code differs from ours. With both values given,
    ours are written."""
    ffmpeg, _ = _ffmpeg_tools()
    mkvpropedit, mkvmerge = _tool("mkvpropedit"), _tool("mkvmerge")
    source = tmp_path / "source.mkv"
    _mux(ffmpeg, source, "ger")
    path = tmp_path / "a.mkv"
    for tag, (theirs, ours) in MKVTOOLNIX_DIFFERENT_LEGACY.items():
        assert to_matroska_legacy(tag) == ours
        shutil.copyfile(source, path)
        _propedit(mkvpropedit, path, f"language={tag}")
        assert _mkvmerge_language(mkvmerge, path) == (theirs, to_matroska_ietf(tag)), tag
        shutil.copyfile(source, path)
        _propedit(
            mkvpropedit,
            path,
            f"language={to_matroska_legacy(tag)}",
            f"language-ietf={to_matroska_ietf(tag)}",
        )
        assert _mkvmerge_language(mkvmerge, path) == (ours, to_matroska_ietf(tag)), tag
