"""Ambiguous names: a name of one language that the name search resolves to another (or to
none). Each keeps the result it had on langcodes, without the libraries installed."""

from __future__ import annotations

import pytest

from reframe.languages import english_name, native_name, normalize

#: Name → (what ``normalize`` gives, the languages that have this English or native name).
TIES: dict[str, tuple[str | None, tuple[str, ...]]] = {
    "'Are'are": (None, ("alu",)),
    "'Auhelawa": (None, ("kud",)),
    "Akan": ("ak", ("fat", "tw")),
    "Aymara": ("ay", ("ayr",)),
    "Bikol": ("bik", ("bcl",)),
    "Bontok": ("bnc", ("lbk",)),
    "Buriat": ("bua", ("bxr",)),
    "Cree": ("cr", ("cwd",)),
    "Delaware": ("del", ("umu",)),
    "Dinka": ("din", ("dik",)),
    "Gbaya": ("gba", ("gya",)),
    "Geji": ("gyz", ("gji",)),
    "Gondi": ("gon", ("gno",)),
    "Grebo": ("grb", ("gbo",)),
    "Haida": ("hai", ("hdn",)),
    "Hmong": ("hmn", ("hea",)),
    "Inuktitut": ("iu", ("ike",)),
    "Inupiaq": ("ik", ("esk",)),
    "Jewish Babylonian Aramaic (ca. 200-1200 CE)": (None, ("tmr",)),
    "Judeo-Arabic": ("jrb", ("aju",)),
    "Kalenjin": ("kln", ("spy",)),
    "Kanuri": ("kr", ("knc",)),
    "Kisampur": ("lks", ("saq",)),
    "Kishambaa": ("sw", ("ksb",)),
    "Kiswahili": ("sw", ("swh",)),
    "Kiswahili (Jamhuri ya Kidemokrasia ya Kongo)": ("swh", ("sw-CD",)),
    "Komi": ("kv", ("kpv",)),
    "Kongo": ("kg", ("kng",)),
    "Kpɛlɛɛ": ("kpe", ("xpe",)),
    "Kristang": ("cpp", ("kcm",)),
    "Kui (India)": ("uki", ("kxu",)),
    "Luluhia": ("luy", ("bxk",)),
    "MUNDAŊ": ("unx", ("mua",)),
    "Makua": ("xak", ("mgh",)),
    "Malagasy": ("mg", ("plt",)),
    "Mandingo": ("man", ("emk", "mnk")),
    "Mari": ("chm", ("mhr",)),
    "Marwari": ("mwr", ("dhd",)),
    "Middle Korean (10th-16th cent.)": (None, ("okm",)),
    "Ojibwa": ("oj", ("ojg",)),
    "Old Aramaic (up to 700 BCE)": (None, ("oar",)),
    "Old Korean (3rd-9th cent.)": (None, ("oko",)),
    "Oromoo": ("om", ("gaz",)),
    "Persian (Afghanistan)": ("fa", ("fa-AF",)),
    "Pulaar": ("ff", ("fuc",)),
    "Punan Batu 1": (None, ("pnm",)),
    "Romany": ("rom", ("rmy",)),
    "Runasimi": ("qu", ("quz",)),
    "Semandang": ("sdq", ("sdm",)),
    "Serbian (Montenegro)": ("sr", ("sr-ME",)),
    "Sirmauri": ("srx", ("him",)),
    "Slave": ("den", ("xsl",)),
    "Swahili (Congo - Kinshasa)": ("sw", ("sw-CD",)),
    "Tamashek": ("tmh", ("ttq",)),
    "Vahcuengh": ("za", ("zyb",)),
    "Western Panjabi": ("lah", ("pnb",)),
    "Zapotec": ("zap", ("zai",)),
    "Zaza": ("zza", ("diq",)),
    "avañe’ẽ": ("gn", ("gug",)),  # noqa: RUF001
    "azərbaycan": ("az", ("azj",)),
    "bahasa Malaysia": ("ms", ("zsm",)),
    "eesti": ("et", ("ekk",)),
    "kurdî (kurmancî)": ("ku", ("kmr",)),
    "latviešu": ("lv", ("lvs",)),
    "o‘zbek": ("uz", ("uzn",)),  # noqa: RUF001
    "sardu": ("sc", ("src",)),
    "shqip": ("sq", ("als",)),
    "монгол": ("mn", ("khk",)),
    "српски (Црна Гора)": ("sr", ("sr-ME",)),
    "ייִדיש": ("yi", ("ydd",)),
    "العربية": ("ar", ("arb",)),
    "بلۆچی": ("bal", ("bcc",)),
    "فارسی": ("fa", ("pes",)),
    "فارسی (افغانستان)": ("fa", ("fa-AF",)),
    "لہندا پنجابی": ("lah", ("pnb",)),
    "پښتو": ("ps", ("pbu",)),
    "ܣܘܪܝܝܐ": ("syr", ("cld",)),
    "कोंकणी": ("kok", ("knn",)),
    "डोगरी": ("doi", ("dgo",)),
    "नेपाली": ("ne", ("npi",)),
    "भोजपुरी": ("bho", ("bh",)),
    "राजस्थानी": ("raj", ("mup",)),
    "ଓଡ଼ିଆ": ("or", ("ory",)),
    "中文": ("zh", ("cmn",)),
}


@pytest.mark.parametrize(("name", "result", "named"), [(k, *v) for k, v in TIES.items()])
def test_an_ambiguous_name_keeps_its_result(
    name: str, result: str | None, named: tuple[str, ...]
) -> None:
    assert normalize(name) == result
    for tag in named:
        assert name in (english_name(tag), native_name(tag)), tag
