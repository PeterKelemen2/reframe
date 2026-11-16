"""The probe cache with JSON nested more than 64 levels deep.

A deep entry is a miss (never a ``RecursionError``), and the next probe rewrites it. A deep
source is not cached: ``put`` returns ``False``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reframe.models import MediaSource, SourceRef
from reframe.probe.cache import CacheKey, ProbeCache
from reframe.settings import MAX_DEPTH, too_deep
from reframe_testing.helpers import nested

TOOL = "ffprobe n9.0.2"
#: Deep enough for CPython's ``json.loads`` to raise ``RecursionError`` (a C-stack check).
PARSER_DEPTH = 200_000


def key() -> CacheKey:
    return CacheKey("/m/a.mkv", 10, 123)


def source(extra: object = None) -> MediaSource:
    """A source; ``extra`` is an unknown field (kept: ``DocumentModel``) at entry level 3."""
    data = MediaSource(ref=SourceRef(path=Path("/m/a.mkv"))).model_dump(mode="json")
    if extra is not None:
        data["from_the_future"] = extra
    return MediaSource.model_validate(data)


def entry_with(cache: ProbeCache, levels: int) -> Path:
    """Write a valid entry, then nest its ``source`` so the entry is ``levels`` deep."""
    assert cache.put(key(), source(), tool=TOOL)
    path = cache.entry_path(key())
    text = path.read_text(encoding="ascii")
    deep = "[" * (levels - 2) + "]" * (levels - 2)
    marker = '"source":{'
    assert text.count(marker) == 1
    path.write_text(text.replace(marker, f'{marker}"from_the_future":{deep},'), encoding="ascii")
    return path


@pytest.mark.parametrize("levels", [MAX_DEPTH + 1, 300, PARSER_DEPTH])
def test_a_deep_entry_is_a_miss_and_is_rewritten(tmp_path: Path, levels: int) -> None:
    """65 levels (the first one too deep), 300 (Pydantic validates it) and 200 000
    (``json.loads`` raises ``RecursionError``)."""
    cache = ProbeCache(tmp_path)
    path = entry_with(cache, levels)
    fresh = ProbeCache(tmp_path)
    assert fresh.get(key(), tool=TOOL) is None
    assert fresh.put(key(), source(), tool=TOOL)  # the next probe rewrites it
    assert ProbeCache(tmp_path).get(key(), tool=TOOL) == source()
    assert not too_deep(json.loads(path.read_text(encoding="ascii")))


def test_an_entry_of_64_levels_is_a_hit(tmp_path: Path) -> None:
    cache = ProbeCache(tmp_path)
    path = entry_with(cache, MAX_DEPTH)
    doc = json.loads(path.read_text(encoding="ascii"))
    assert not too_deep(doc)
    assert too_deep(doc, MAX_DEPTH - 1)  # exactly 64
    got = ProbeCache(tmp_path).get(key(), tool=TOOL)
    assert got is not None
    assert got.model_dump(mode="json")["from_the_future"] == nested(MAX_DEPTH - 2)


def test_a_source_of_64_levels_is_cached(tmp_path: Path) -> None:
    cache = ProbeCache(tmp_path)
    deep = source(nested(MAX_DEPTH - 2))
    assert cache.put(key(), deep, tool=TOOL)
    doc = json.loads(cache.entry_path(key()).read_text(encoding="ascii"))
    assert too_deep(doc, MAX_DEPTH - 1)
    assert not too_deep(doc)
    assert ProbeCache(tmp_path).get(key(), tool=TOOL) == deep


@pytest.mark.parametrize("levels", [MAX_DEPTH + 1, 300])
def test_a_source_that_would_write_a_deep_entry_is_not_cached(tmp_path: Path, levels: int) -> None:
    """65 levels, and 300 (past the 255 levels that Pydantic's ``model_dump`` accepts). Not in
    memory either: a later ``get`` is a miss. An earlier entry of the file stays as it was."""
    cache = ProbeCache(tmp_path)
    assert cache.put(key(), source(), tool=TOOL)
    before = cache.entry_path(key()).read_bytes()
    deep = source(nested(levels - 2))
    assert not cache.put(key(), deep, tool=TOOL)
    assert cache.entry_path(key()).read_bytes() == before
    got = cache.get(key(), tool=TOOL)
    assert got == source()  # the earlier result, not the deep one
    empty = ProbeCache(tmp_path / "empty")
    assert not empty.put(key(), deep, tool=TOOL)
    assert empty.get(key(), tool=TOOL) is None
    assert not (tmp_path / "empty").exists()


def test_deep_options_are_not_cached(tmp_path: Path) -> None:
    cache = ProbeCache(tmp_path)
    options = {"x": nested(MAX_DEPTH)}
    assert not cache.put(key(), source(), tool=TOOL, options=options)
    assert cache.get(key(), tool=TOOL, options=options) is None
    assert not tmp_path.joinpath(cache.entry_path(key()).name).exists()
