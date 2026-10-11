"""The probe cache (C-3): key = path + size + mtime; ffprobe build, parser version and options
invalidate; corrupt entries are ignored and rewritten; writes are atomic."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from reframe.models import MediaSource, SourceRef
from reframe.probe import cache as cache_mod
from reframe.probe.cache import CacheKey, ProbeCache
from reframe.probe.parse import PARSER_VERSION

TOOL = "ffprobe n9.0.2"


def source(path: str = "/m/a.mkv", title: str = "A") -> MediaSource:
    src = MediaSource(ref=SourceRef(path=Path(path)))
    src.container.title = title
    return src


def key(size: int = 10, mtime_ns: int = 123, path: str = "/m/a.mkv") -> CacheKey:
    return CacheKey(path, size, mtime_ns)


def test_default_directory_is_in_the_cache_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REFRAME_CACHE_DIR", str(tmp_path))
    assert ProbeCache().directory == tmp_path / "probe"


def test_hit_and_miss(tmp_path: Path) -> None:
    cache = ProbeCache(tmp_path)
    assert cache.get(key(), tool=TOOL) is None
    assert cache.put(key(), source(), tool=TOOL, options={"mediainfo": True})
    assert cache.get(key(), tool=TOOL, options={"mediainfo": True}) == source()
    # A fresh cache (another process) reads the file.
    fresh = ProbeCache(tmp_path)
    assert fresh.get(key(), tool=TOOL, options={"mediainfo": True}) == source()


@pytest.mark.parametrize(
    ("other_key", "tool", "options"),
    [
        (key(size=11), TOOL, {"mediainfo": True}),  # the file grew
        (key(mtime_ns=124), TOOL, {"mediainfo": True}),  # the file was touched
        (key(path="/m/b.mkv"), TOOL, {"mediainfo": True}),
        (key(), "ffprobe n8.1.3", {"mediainfo": True}),  # another ffprobe
        (key(), TOOL, {"mediainfo": False}),  # other options
    ],
)
def test_invalidation(
    tmp_path: Path, other_key: CacheKey, tool: str, options: dict[str, bool]
) -> None:
    cache = ProbeCache(tmp_path)
    cache.put(key(), source(), tool=TOOL, options={"mediainfo": True})
    assert cache.get(other_key, tool=tool, options=options) is None
    cache.forget_memory()
    assert cache.get(other_key, tool=tool, options=options) is None


def test_another_parser_version_is_a_miss(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ProbeCache(tmp_path).put(key(), source(), tool=TOOL)
    monkeypatch.setattr(cache_mod, "PARSER_VERSION", PARSER_VERSION + 1)
    assert ProbeCache(tmp_path).get(key(), tool=TOOL) is None


def test_a_tool_change_is_overwritten(tmp_path: Path) -> None:
    cache = ProbeCache(tmp_path)
    cache.put(key(), source(title="old"), tool="ffprobe old")
    cache.put(key(), source(title="new"), tool=TOOL)
    fresh = ProbeCache(tmp_path)
    got = fresh.get(key(), tool=TOOL)
    assert got is not None
    assert got.container.title == "new"


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        "[]",
        json.dumps({"format": 1}),
        json.dumps({"format": 99, "parser": 1}),
        "\x00\x01",
    ],
)
def test_corrupt_entry_is_ignored_and_rewritten(tmp_path: Path, content: str) -> None:
    cache = ProbeCache(tmp_path)
    path = cache.entry_path(key())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    assert cache.get(key(), tool=TOOL) is None
    assert cache.put(key(), source(), tool=TOOL)
    assert ProbeCache(tmp_path).get(key(), tool=TOOL) == source()


def test_invalid_source_in_entry_is_a_miss(tmp_path: Path) -> None:
    cache = ProbeCache(tmp_path)
    cache.put(key(), source(), tool=TOOL)
    path = cache.entry_path(key())
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["source"]["video"] = [{"index": -1}]
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert ProbeCache(tmp_path).get(key(), tool=TOOL) is None


def test_entry_layout(tmp_path: Path) -> None:
    cache = ProbeCache(tmp_path)
    cache.put(key(), source(), tool=TOOL, options={"mediainfo": False})
    files = list(tmp_path.iterdir())
    assert files == [cache.entry_path(key())]  # no temporary file left behind
    doc = json.loads(files[0].read_text(encoding="utf-8"))
    assert doc["key"] == {"path": "/m/a.mkv", "size": 10, "mtime_ns": 123}
    assert doc["tool"] == TOOL
    assert doc["options"] == {"mediainfo": False}
    assert doc["format"] == cache_mod.CACHE_FORMAT


def test_returned_sources_are_copies(tmp_path: Path) -> None:
    cache = ProbeCache(tmp_path)
    original = source()
    cache.put(key(), original, tool=TOOL)
    original.container.title = "changed by the caller"
    got = cache.get(key(), tool=TOOL)
    assert got is not None
    assert got.container.title == "A"
    got.container.title = "changed again"
    again = cache.get(key(), tool=TOOL)
    assert again is not None
    assert again.container.title == "A"


def test_memory_layer_is_bounded(tmp_path: Path) -> None:
    cache = ProbeCache(tmp_path, memory_entries=2)
    for i in range(3):
        cache.put(key(size=i), source(), tool=TOOL)
    assert len(cache._memory) == 2
    assert cache.get(key(size=0), tool=TOOL) is not None  # read back from its file


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_unwritable_directory_is_not_an_error(tmp_path: Path) -> None:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root can write anywhere")
    tmp_path.chmod(0o500)
    try:
        cache = ProbeCache(tmp_path / "probe")
        assert cache.put(key(), source(), tool=TOOL) is False
        assert cache.get(key(), tool=TOOL) == source()  # the memory layer still has it
    finally:
        tmp_path.chmod(0o700)


def test_replace_failure_is_not_an_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(src: object, dst: object) -> None:
        raise PermissionError("in use")

    monkeypatch.setattr(os, "replace", fail)
    cache = ProbeCache(tmp_path)
    assert cache.put(key(), source(), tool=TOOL) is False
    assert list(tmp_path.iterdir()) == []  # the temporary file was removed


def test_clear(tmp_path: Path) -> None:
    cache = ProbeCache(tmp_path)
    cache.put(key(), source(), tool=TOOL)
    cache.clear()
    assert cache.get(key(), tool=TOOL) is None
    assert list(tmp_path.glob("*.json")) == []
    ProbeCache(tmp_path / "missing").clear()


def test_key_for_file(tmp_path: Path) -> None:
    file = tmp_path / "a.mkv"
    file.write_bytes(b"x" * 5)
    stat = file.stat()
    k = CacheKey.for_file(file, stat)
    assert (k.path, k.size, k.mtime_ns) == (str(file.absolute()), 5, stat.st_mtime_ns)
    assert k.digest() != CacheKey(k.path, 6, k.mtime_ns).digest()
