"""The preview cache (C-10): keys, file names that a key cannot escape, the LRU with a size
limit (one budget for frames and clips), temporary files."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from reframe.preview.cache import (
    STALE,
    PreviewCache,
    digest,
    frame_key,
    is_clip_id,
    is_frame_key,
    megabytes,
    source_fingerprint,
    timestamp_ms,
)

KEY = "0123456789abcdef-1500-fedcba9876543210"
CLIP = "0123456789abcdef0123456789abcdef"


def write(path: Path, size: int, used: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    os.utime(path, (used, used))
    return path


# --------------------------------------------------------------------------- keys


def test_digest_is_stable_and_covers_every_part() -> None:
    assert digest("a", [1, 2], {"b": Path("/x")}) == digest("a", [1, 2], {"b": "/x"})
    assert digest("a", [1, 2]) != digest("a", [2, 1])
    assert digest({"x": 1, "y": 2}) == digest({"y": 2, "x": 1})
    assert len(digest()) == 64


def test_digest_takes_names_that_are_not_utf8() -> None:
    assert digest(Path("/media/bad\udcffname.mkv")) != digest(Path("/media/badname.mkv"))


def test_source_fingerprint_changes_with_the_file(tmp_path: Path) -> None:
    a = tmp_path / "a.mkv"
    a.write_bytes(b"1234")
    first = source_fingerprint(a, a.stat())
    assert len(first) == 16
    assert source_fingerprint(a, a.stat()) == first
    os.utime(a, ns=(1_000_000_000, 1_000_000_001))
    assert source_fingerprint(a, a.stat()) != first
    b = tmp_path / "b.mkv"
    b.write_bytes(b"1234")
    os.utime(b, ns=(1_000_000_000, 1_000_000_001))
    assert source_fingerprint(b, b.stat()) != source_fingerprint(a, a.stat())


@pytest.mark.parametrize(
    ("seconds", "ms"), [(0.0, 0), (1.5, 1500), (0.0004, 0), (2.0004, 2000), (2.0006, 2001)]
)
def test_timestamp_ms(seconds: float, ms: int) -> None:
    assert timestamp_ms(seconds) == ms


def test_frame_key_form() -> None:
    key = frame_key("0123456789abcdef", 1.5, "fedcba9876543210" + "0" * 48)
    assert key == KEY
    assert is_frame_key(key)


@pytest.mark.parametrize(
    "key",
    [
        "",
        "../frames/x",
        "0123456789abcdef-1500-fedcba9876543210.png",
        "0123456789ABCDEF-1500-fedcba9876543210",
        "0123456789abcdef--1500-fedcba9876543210",
        "0123456789abcdef-1500-fedcba98765432",
        "0123456789abcdef-1500-fedcba9876543210/..",
        "0123456789abcdef-1500-fedcba9876543210\n",
        "0123456789abcdef-1234567890123-fedcba9876543210",
    ],
)
def test_not_a_frame_key(key: str) -> None:
    assert not is_frame_key(key)
    with pytest.raises(ValueError, match="not a frame key"):
        PreviewCache(Path("/cache")).frame(key)


def test_clip_ids() -> None:
    assert is_clip_id(CLIP)
    for bad in ("", CLIP[:-1], CLIP.upper(), CLIP + ".mkv", "../" + CLIP[3:]):
        assert not is_clip_id(bad)
    with pytest.raises(ValueError, match="not a clip id"):
        PreviewCache(Path("/cache")).clip("x", ".mkv")


def test_megabytes() -> None:
    assert megabytes(1024) == 2**30
    assert megabytes(0) == 0
    assert megabytes(-1) == 0


# --------------------------------------------------------------------------- names and lookups


def test_layout(tmp_path: Path) -> None:
    cache = PreviewCache(tmp_path)
    assert cache.frame(KEY) == tmp_path / "frames" / f"{KEY}.png"
    assert cache.clip(CLIP, ".mp4") == tmp_path / "clips" / f"{CLIP}.mp4"
    temp = cache.temporary(cache.frame(KEY))
    assert temp.parent == cache.frames
    assert temp.name.startswith(".tmp-")
    assert temp.name.endswith(f"-{KEY}.png")
    assert cache.temporary(cache.frame(KEY)) != temp


def test_find_frame_marks_the_use(tmp_path: Path) -> None:
    cache = PreviewCache(tmp_path)
    assert cache.find_frame(KEY) is None  # no folder yet
    png = write(cache.frame(KEY), 10, used=1000.0)
    before = time.time()
    assert cache.find_frame(KEY) == png
    assert png.stat().st_mtime >= before - 1
    assert cache.find_frame("../" + KEY) is None


def test_a_folder_is_not_a_frame(tmp_path: Path) -> None:
    cache = PreviewCache(tmp_path)
    cache.frame(KEY).mkdir(parents=True)
    assert cache.find_frame(KEY) is None


def test_find_clip(tmp_path: Path) -> None:
    cache = PreviewCache(tmp_path)
    assert cache.find_clip(CLIP) is None  # no folder yet
    write(cache.clips / f"{CLIP}.part.mkv", 10, used=1000.0)
    write(cache.clips / f".tmp-1234-{CLIP}.mkv", 10, used=1000.0)
    other = "f" * 32
    write(cache.clips / f"{other}.mkv", 10, used=1000.0)
    assert cache.find_clip(CLIP) is None
    clip = write(cache.clip(CLIP, ".mp4"), 10, used=1000.0)
    assert cache.find_clip(CLIP) == clip
    assert clip.stat().st_mtime > 1000.0
    assert cache.find_clip("../clips/" + CLIP) is None
    assert cache.find_clip(CLIP[:-1]) is None


def test_touch_a_missing_file(tmp_path: Path) -> None:
    assert not PreviewCache.touch(tmp_path / "nothing.png")


# --------------------------------------------------------------------------- the LRU


def test_entries_are_least_recently_used_first(tmp_path: Path) -> None:
    cache = PreviewCache(tmp_path)
    now = 100_000.0
    old = write(cache.frame(KEY), 5, used=now - 100)
    clip = write(cache.clip(CLIP, ".mkv"), 7, used=now - 300)
    newest = write(cache.frame(KEY.replace("1500", "2500")), 3, used=now - 10)
    (cache.frames / "a-folder").mkdir()
    stale = write(cache.frames / f".tmp-0000-{KEY}.png", 9, used=now - STALE - 1)
    fresh = write(cache.clips / f"{CLIP}.part.mkv", 9, used=now - 5)
    passlog = write(cache.clips / f"{CLIP}.part.passlog-0.log", 9, used=now - STALE - 5)
    entries = cache.entries(now=now)
    assert [e.path for e in entries] == [clip, old, newest]
    assert [e.size for e in entries] == [7, 5, 3]
    assert not stale.exists()
    assert not passlog.exists()
    assert fresh.exists()  # a running clip


def test_size(tmp_path: Path) -> None:
    cache = PreviewCache(tmp_path)
    assert cache.size() == 0
    write(cache.frame(KEY), 5, used=time.time())
    write(cache.clip(CLIP, ".mkv"), 7, used=time.time())
    write(cache.clips / f"{CLIP}.part.mkv", 100, used=time.time())
    assert cache.size() == 12


def test_trim_removes_the_least_recently_used(tmp_path: Path) -> None:
    cache = PreviewCache(tmp_path)
    now = 100_000.0
    a = write(cache.frame(KEY), 40, used=now - 500)
    b = write(cache.clip(CLIP, ".mkv"), 40, used=now - 400)
    c = write(cache.frame(KEY.replace("1500", "2500")), 40, used=now - 300)
    assert cache.trim(200, now=now) == []
    assert cache.trim(80, now=now) == [a]
    assert cache.trim(40, now=now) == [b]
    assert c.exists()
    assert cache.trim(0, now=now) == [c]
    assert cache.entries(now=now) == []


def test_trim_keeps_protected_and_fresh_files(tmp_path: Path) -> None:
    cache = PreviewCache(tmp_path)
    now = 100_000.0
    mine = write(cache.frame(KEY), 40, used=now - 500)
    fresh = write(cache.frame(KEY.replace("1500", "2500")), 40, used=now - 5)
    old = write(cache.clip(CLIP, ".mkv"), 40, used=now - 400)
    assert cache.trim(0, protect=[mine], now=now) == [old]
    assert mine.exists()
    assert fresh.exists()
    assert cache.trim(0, protect=[mine], now=now, grace=0) == [fresh]
    assert cache.trim(0, now=now, grace=0) == [mine]


def test_trim_with_the_real_clock(tmp_path: Path) -> None:
    cache = PreviewCache(tmp_path)
    old = write(cache.frame(KEY), 40, used=time.time() - 3600)
    assert cache.trim(0) == [old]


def test_trim_survives_a_file_removed_meanwhile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = PreviewCache(tmp_path)
    now = 100_000.0
    gone = write(cache.frame(KEY), 40, used=now - 500)
    locked = write(cache.clip(CLIP, ".mkv"), 40, used=now - 400)
    real_unlink = os.unlink

    def unlink(path: str | os.PathLike[str]) -> None:
        if Path(path) == gone:
            real_unlink(path)
            raise FileNotFoundError(path)  # another process removed it first
        if Path(path) == locked:
            raise PermissionError(path)  # Windows: a player has it open
        real_unlink(path)

    monkeypatch.setattr("reframe.preview.cache.os.unlink", unlink)
    assert cache.trim(0, now=now) == [gone]
    assert locked.exists()


def test_clear(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache = PreviewCache(tmp_path)
    write(cache.frame(KEY), 5, used=time.time())
    write(cache.clip(CLIP, ".mkv"), 7, used=time.time())
    running = write(cache.clips / f"{CLIP}.part.mkv", 100, used=time.time())
    assert cache.clear() == 12
    assert cache.entries() == []
    assert running.exists()
    write(cache.frame(KEY), 5, used=time.time())
    monkeypatch.setattr("reframe.preview.cache.os.unlink", _refuse)
    assert cache.clear() == 0


def _refuse(path: str | os.PathLike[str]) -> None:
    raise PermissionError(path)


def test_entries_of_a_file_that_vanishes_while_scanning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = PreviewCache(tmp_path)
    write(cache.frame(KEY), 5, used=time.time())
    real_scandir = os.scandir

    class Vanished:
        def __init__(self, entry: os.DirEntry[str]) -> None:
            self.name = entry.name
            self.path = entry.path

        def is_file(self, *, follow_symlinks: bool = True) -> bool:
            raise FileNotFoundError(self.path)

    def scandir(path: str | os.PathLike[str]) -> list[object]:
        return [Vanished(e) for e in real_scandir(path)]

    monkeypatch.setattr("reframe.preview.cache.os.scandir", scandir)
    assert cache.entries() == []
