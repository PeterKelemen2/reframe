"""The name corpus ``testdata/names.toml`` passes.

Every case runs the real guessit and the default naming options. A path with a folder lies
under the media root ``/library``; the case's ``siblings`` are the other files in its folder
(season packs). The header of ``names.toml`` describes the keys.
"""

from __future__ import annotations

import tomllib
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from reframe.models import NamingOptions
from reframe.naming import resolve_output_name

REPO = Path(__file__).resolve().parents[4]
NAMES = REPO / "testdata" / "names.toml"
CASES: list[dict[str, Any]] = tomllib.loads(NAMES.read_text(encoding="utf-8"))["case"]
LIBRARY = Path("/library")

#: The categories the corpus must cover, and the least number of cases in each.
REQUIRED = {
    "movie": 20,
    "episode": 20,
    "multi-episode": 5,
    "anime": 10,
    "year-in-show": 5,
    "no-separators": 5,
    "season-pack": 5,
    "movie-folder": 5,
}
CATEGORIES = {*REQUIRED, "plex", "daily"}


def _id(case: dict[str, Any]) -> str:
    return str(case["path"]).rsplit("/", 1)[-1][:70]


def _resolve(case: dict[str, Any], fake_fs: Any, now: datetime) -> Any:
    relative = Path(case["path"])
    base, root = (LIBRARY, LIBRARY) if len(relative.parts) > 1 else (Path("/"), None)
    file = base / relative
    fs = fake_fs({file.parent: [relative.name, *case.get("siblings", [])]})
    return resolve_output_name(file, NamingOptions(), root=root, fs=fs, now=now)


def _check_case(case: dict[str, Any], fake_fs: Any, now: datetime) -> None:
    result = _resolve(case, fake_fs, now)
    context = f"{case['path']}\nreason: {result.reason}\nfields: {result.fields!r}"
    if "source" in case:
        assert result.source == case["source"], context
    assert result.fields.main_title == case["main_title"], context
    for key, expected in case.get("fields", {}).items():
        actual = getattr(result.fields, key)
        if expected == "":
            assert actual in (None, []), f"{key}: {actual!r}\n{context}"
        else:
            assert actual == expected, f"{key}: {actual!r} != {expected!r}\n{context}"
    if "output" in case:
        assert result.relative_path == case["output"]
    assert not result.issues


@pytest.mark.parametrize("case", CASES, ids=[_id(case) for case in CASES])
def test_corpus_case(case: dict[str, Any], fake_fs: Any, now: datetime) -> None:
    _check_case(case, fake_fs, now)


def test_corpus_ignores_guessit_user_config(
    guessit_user_config: str, fake_fs: Any, now: datetime
) -> None:
    for case in CASES:
        _check_case(case, fake_fs, now)


def test_corpus_size_and_categories() -> None:
    assert len(CASES) >= 100
    counts = Counter(case["category"] for case in CASES)
    assert set(counts) <= CATEGORIES
    for category, minimum in REQUIRED.items():
        assert counts[category] >= minimum, category
    paths = [case["path"] for case in CASES]
    assert len(paths) == len(set(paths))
    for case in CASES:
        assert {"category", "path", "main_title"} <= set(case), case


def test_corpus_holds_the_examples_of_03() -> None:
    by_path = {case["path"]: case for case in CASES}
    hacksaw = by_path[
        "Hacksaw.Ridge.2016.HYBRID.2160p.UHD.BluRay.REMUX.TrueHD.7.1.Atmos.DoVi.HDR.HEVC."
        "HUN-HenDerson/hacksawridge.2160p.remux-henderson.mkv"
    ]
    sopranos = by_path[
        "The.Sopranos.S03.1080p.BluRay.REMUX-Kataklysm/"
        "The.Sopranos.S03E02.Proshai.Livushka.1080p.BluRay.REMUX-Kataklysm.mkv"
    ]
    assert (hacksaw["source"], hacksaw["main_title"]) == ("folder", "Hacksaw.Ridge")
    assert (sopranos["source"], sopranos["main_title"]) == (
        "file",
        "The.Sopranos.S03E02.Proshai.Livushka",
    )
