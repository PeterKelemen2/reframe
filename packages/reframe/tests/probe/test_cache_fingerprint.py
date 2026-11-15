"""The parser fingerprint covers the Matroska track reader.

The reader sets each Matroska stream's ``language_ietf``. A change to it changes what a probe
produces, so it must change the fingerprint too.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from reframe.probe import cache as cache_mod


@pytest.fixture
def probe_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A copy of the ``reframe.probe`` sources that ``parser_fingerprint`` hashes instead of
    the installed ones (it reads the files next to ``cache.py``)."""
    here = Path(cache_mod.__file__).resolve().parent
    copy = tmp_path / "probe"
    copy.mkdir()
    for module in here.glob("*.py"):
        shutil.copyfile(module, copy / module.name)
    monkeypatch.setattr(cache_mod, "__file__", str(copy / "cache.py"))
    cache_mod.parser_fingerprint.cache_clear()
    try:
        yield copy
    finally:
        cache_mod.parser_fingerprint.cache_clear()


@pytest.mark.parametrize("module", ["matroska.py", "prober.py", "sampling.py"])
def test_a_change_to_a_reader_changes_the_fingerprint(probe_sources: Path, module: str) -> None:
    before = cache_mod.parser_fingerprint()
    with (probe_sources / module).open("a", encoding="utf-8") as handle:
        handle.write("\n# changed\n")
    cache_mod.parser_fingerprint.cache_clear()
    assert cache_mod.parser_fingerprint() != before


def test_the_matroska_reader_is_hashed() -> None:
    assert "matroska.py" in cache_mod._PARSER_MODULES
