"""The probe cache: keys, invalidation, corrupt entries, pruning and atomic writes."""

from __future__ import annotations

import json
import os
import sys
import time
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
    monkeypatch.setattr(cache_mod, "parser_fingerprint", lambda: f"{PARSER_VERSION + 1}:x")
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


def _age(path: Path, seconds: float) -> None:
    then = time.time() - seconds
    os.utime(path, (then, then))


def test_prune_by_age_count_and_leftovers(tmp_path: Path) -> None:
    cache = ProbeCache(tmp_path, max_entries=2, max_age=100.0)
    for i in range(4):
        cache.put(key(size=i), source(), tool=TOOL)
    paths = [cache.entry_path(key(size=i)) for i in range(4)]
    _age(paths[0], 1000)  # too old
    _age(paths[1], 50)
    _age(paths[2], 40)
    _age(paths[3], 30)
    leftover = tmp_path / ".abc-123.tmp"
    leftover.write_text("x")
    _age(leftover, 7200)
    fresh_tmp = tmp_path / ".def-456.tmp"
    fresh_tmp.write_text("x")
    (tmp_path / "notes.txt").write_text("not ours")
    assert cache.prune() == 3  # paths[0] (age), paths[1] (count), the old leftover
    assert [p.exists() for p in paths] == [False, False, True, True]
    assert not leftover.exists()
    assert fresh_tmp.exists()
    assert (tmp_path / "notes.txt").exists()
    assert ProbeCache(tmp_path / "missing").prune() == 0


def test_put_prunes_on_the_first_put_and_then_every_n(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    monkeypatch.setattr(cache_mod, "PRUNE_EVERY", 3)
    cache = ProbeCache(tmp_path)

    def fake_prune() -> int:
        calls.append(1)
        return 0

    monkeypatch.setattr(cache, "prune", fake_prune)
    for i in range(7):
        cache.put(key(size=i), source(), tool=TOOL)
    assert len(calls) == 3  # puts 1, 4 and 7


def test_parser_fingerprint_follows_the_source() -> None:
    fingerprint = cache_mod.parser_fingerprint()
    assert fingerprint.startswith(f"{PARSER_VERSION}:")
    assert len(fingerprint.split(":")[1]) == 16
    doc_path_names = cache_mod._PARSER_MODULES
    here = Path(cache_mod.__file__).parent
    assert all((here / name).is_file() for name in doc_path_names)


def test_parser_fingerprint_without_source(monkeypatch: pytest.MonkeyPatch) -> None:
    import reframe

    monkeypatch.setattr(cache_mod, "_PARSER_MODULES", ("missing-module.py",))
    cache_mod.parser_fingerprint.cache_clear()
    try:
        assert cache_mod.parser_fingerprint() == f"{PARSER_VERSION}:reframe-{reframe.__version__}"
    finally:
        cache_mod.parser_fingerprint.cache_clear()
