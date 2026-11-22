"""The parser fingerprint covers every source file and table that decides what a probe
produces: the Matroska track reader, the sample and the language tables."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from reframe.probe import cache as cache_mod


@pytest.fixture
def probe_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A copy of the ``reframe`` package's probe sources, ``languages.py`` and language tables
    that ``parser_fingerprint`` hashes instead of the installed ones (it finds them from
    ``cache.py``)."""
    package = Path(cache_mod.__file__).resolve().parent.parent
    copy = tmp_path / "reframe"
    (copy / "probe").mkdir(parents=True)
    (copy / "definitions" / "data").mkdir(parents=True)
    for module in (package / "probe").glob("*.py"):
        shutil.copyfile(module, copy / "probe" / module.name)
    shutil.copyfile(package / "languages.py", copy / "languages.py")
    for table in (package / "definitions" / "data").glob("language-*.json.gz"):
        shutil.copyfile(table, copy / "definitions" / "data" / table.name)
    monkeypatch.setattr(cache_mod, "__file__", str(copy / "probe" / "cache.py"))
    cache_mod.parser_fingerprint.cache_clear()
    try:
        yield copy
    finally:
        cache_mod.parser_fingerprint.cache_clear()


@pytest.mark.parametrize(
    "file",
    [
        "probe/matroska.py",
        "probe/prober.py",
        "probe/sampling.py",
        "probe/parse.py",
        "languages.py",
        "definitions/data/language-core.json.gz",
        "definitions/data/language-locale-names.json.gz",
        "definitions/data/language-search.json.gz",
    ],
)
def test_a_change_to_a_reader_changes_the_fingerprint(probe_sources: Path, file: str) -> None:
    before = cache_mod.parser_fingerprint()
    with (probe_sources / file).open("ab") as handle:
        handle.write(b"\n# changed\n")
    cache_mod.parser_fingerprint.cache_clear()
    assert cache_mod.parser_fingerprint() != before
