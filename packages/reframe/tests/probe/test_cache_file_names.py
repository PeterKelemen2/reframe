"""The probe cache with file names and tags that hold lone surrogates.

The entry is ASCII JSON, so such a path or tag is written and reads back exactly.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from reframe.models import MediaSource, SourceRef
from reframe.probe import ProbeCache, Prober
from reframe.probe.cache import CacheKey
from reframe.tools import discover_tools

TOOL = "ffprobe n9.0.2"
POSIX_NAME = "/m/bad\udcffname.mkv"  # os.fsdecode(b"/m/bad\xffname.mkv") on POSIX
WINDOWS_NAME = "C:\\m\\odd\ud800name.mkv"  # an unpaired UTF-16 surrogate


def _source(path: str, title: str = "A") -> MediaSource:
    src = MediaSource(ref=SourceRef(path=Path(path)))
    src.container.title = title
    return src


@pytest.mark.parametrize("path", [POSIX_NAME, WINDOWS_NAME], ids=["byte-0xff", "lone-surrogate"])
def test_a_path_that_is_not_utf8_is_stored_and_read_back(tmp_path: Path, path: str) -> None:
    cache = ProbeCache(tmp_path)
    key = CacheKey(path, 10, 123)
    src = _source(path, title="Title \udcfe")  # a tag can hold one too
    assert cache.put(key, src, tool=TOOL) is True
    entry = cache.entry_path(key)
    assert list(tmp_path.iterdir()) == [entry]  # no temporary file left behind
    text = entry.read_bytes().decode("ascii")  # escapes, never raw surrogates
    assert json.loads(text)["key"]["path"] == path
    got = ProbeCache(tmp_path).get(key, tool=TOOL)  # another process: read from the file
    assert got == src
    assert got is not None
    assert str(got.ref.path) == path
    assert got.container.title == "Title \udcfe"


def test_other_text_is_unchanged_by_the_ascii_entry(tmp_path: Path) -> None:
    cache = ProbeCache(tmp_path)
    key = CacheKey("/m/日本語 - Amélie.mkv", 10, 123)
    src = _source(key.path, title="日本語 😀")
    assert cache.put(key, src, tool=TOOL)
    assert ProbeCache(tmp_path).get(key, tool=TOOL) == src


def test_an_entry_that_cannot_be_serialised_is_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: object, **kwargs: object) -> str:
        raise ValueError("cannot serialise")

    monkeypatch.setattr(json, "dumps", fail)  # the module the cache uses
    cache = ProbeCache(tmp_path)
    key = CacheKey(POSIX_NAME, 10, 123)
    assert cache.put(key, _source(POSIX_NAME), tool=TOOL) is False
    assert list(tmp_path.iterdir()) == []
    assert cache.get(key, tool=TOOL) == _source(POSIX_NAME)  # the memory layer has it


@pytest.mark.anyio
@pytest.mark.needs_ffmpeg
@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows file names are UTF-16: no name holds the byte 0xFF"
)
async def test_probe_of_a_real_file_whose_name_is_not_utf8(
    tmp_path: Path, fixture_media: Callable[[str], Path]
) -> None:
    """A name that is not UTF-8 must not make ``ProbeCache.put`` raise ``UnicodeEncodeError``."""
    file = tmp_path / os.fsdecode(b"bad\xffname.mkv")
    shutil.copyfile(fixture_media("multitrack"), file)
    assert os.fsencode(file).endswith(b"bad\xffname.mkv")
    tools = await discover_tools()
    cache_dir = tmp_path / "cache"
    prober = Prober(tools.ffprobe, cache=ProbeCache(cache_dir))
    first = await prober.probe(file)
    assert isinstance(first, MediaSource), first
    assert first.ref.path == file
    assert [a.language for a in first.audio] == ["jpn", "eng", "eng"]
    [entry] = cache_dir.glob("*.json")
    entry.read_bytes().decode("ascii")
    # A new process reads the entry from its file, and the probe gives the same source.
    fresh = ProbeCache(cache_dir)
    key = CacheKey.for_file(file, file.stat())
    cached = fresh.get(key, tool=prober.tool.identity(), options=prober.cache_options())
    assert cached == first
    again = await Prober(tools.ffprobe, cache=fresh).probe(file)
    assert again == first
