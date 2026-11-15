"""The writer stopped after each of its writes: every file left opens in ffprobe and
``mkvmerge -J`` with all the old values or all the new ones."""

from __future__ import annotations

import errno
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from reframe.metadata import header
from reframe.metadata.header import apply_header_edit
from reframe.models.plan import HeaderEdit, InfoHeaderEdit, TrackHeaderEdit

from . import corpus

pytestmark = [pytest.mark.needs_ffmpeg, pytest.mark.needs_mkvtoolnix]

FILE_IO = header._FileIO


class Stop:
    """Lets the writer make ``allowed`` writes, then fails the next one (``None``: none)."""

    def __init__(self, allowed: int | None) -> None:
        self.allowed = allowed
        self.writes = 0

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        stop = self

        class StoppingIO(FILE_IO):
            def write(self, pos: int, data: bytes) -> None:
                stop.tick()
                super().write(pos, data)

            def truncate(self, size: int) -> None:
                stop.tick()
                super().truncate(size)

        monkeypatch.setattr(header, "_FileIO", StoppingIO)

    def tick(self) -> None:
        if self.allowed is not None and self.writes >= self.allowed:
            raise OSError(errno.EIO, "stopped by the test")
        self.writes += 1


def view(path: Path) -> tuple[Any, ...]:
    return corpus.reader_values(path), corpus.mkvmerge_view(path), corpus.ffprobe_view(path)


def long_title(path: Path) -> HeaderEdit:
    return corpus.multitrack_edit(path, long=True, title="Hosszú cím " * 300)


def back_shrink(path: Path) -> HeaderEdit:
    return HeaderEdit(
        path=path, tracks=[TrackHeaderEdit(track_type="audio", number=1, name="short")]
    )


def back_and_front(path: Path) -> HeaderEdit:
    return back_shrink(path).model_copy(update={"info": InfoHeaderEdit(title="Új cím")})


SCENARIOS: dict[str, tuple[str, Callable[[Path], HeaderEdit], int]] = {
    # name: (corpus file, edit, writes)
    "in place": ("ffmpeg-multitrack", corpus.shrink_edit, 1),
    "tracks moves": ("ffmpeg-multitrack", lambda p: corpus.multitrack_edit(p, long=True), 2),
    "tracks and info move": ("ffmpeg-multitrack", long_title, 2),
    "mkvmerge, both move": ("mkvmerge-reordered", long_title, 2),
    "CRC-32, both move": ("mkvmerge-crc", long_title, 2),
    "second SeekHead moves": ("mkvpropedit-linked", long_title, 3),
    "tracks behind the clusters, in place": ("reframe-moved", back_shrink, 1),
    "tracks behind the clusters moves again": ("reframe-moved", long_title, 3),
    "tracks behind the clusters and info": ("reframe-moved", back_and_front, 3),
}


@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_every_stop_leaves_all_old_or_all_new_values(
    header_corpus: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> None:
    """Defect: a crash or kill between two writes leaves a file that a player cannot open,
    or one with some old and some new values, or one that ffprobe and mkvmerge read
    differently."""
    name, make_edit, writes = SCENARIOS[scenario]
    source = header_corpus[name]
    old = view(source)
    full = corpus.copy(source, tmp_path, "full.mkv")
    counter = Stop(None)
    counter.install(monkeypatch)
    assert apply_header_edit(make_edit(full)).ok
    assert counter.writes == writes
    new = view(full)
    assert new != old

    for allowed in range(writes):
        path = corpus.copy(source, tmp_path, f"stopped-{allowed}.mkv")
        Stop(allowed).install(monkeypatch)
        result = apply_header_edit(make_edit(path))
        assert result.status == "failed"
        assert result.code == "header.io_error"
        state = view(path)
        assert state in (old, new), f"stopped after {allowed} writes"
        if allowed == 0:
            assert path.read_bytes() == source.read_bytes()
            assert result.reason is not None
            assert "unchanged" in result.reason
        else:
            assert result.reason is not None
            assert "old or the new" in result.reason
        assert state[1]["errors"] == []


def test_a_stopped_edit_is_finished_by_the_next_one(
    header_corpus: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defect: the copies a stopped edit left after the segment make the next edit refuse
    the file, or stay in it."""
    source = header_corpus["ffmpeg-multitrack"]
    path = corpus.copy(source, tmp_path, "t.mkv")
    edit = long_title(path)
    Stop(1).install(monkeypatch)
    assert apply_header_edit(edit).status == "failed"
    left = path.stat().st_size
    assert left > source.stat().st_size

    counter = Stop(None)
    counter.install(monkeypatch)
    assert apply_header_edit(edit).ok
    assert counter.writes == 3  # truncate, the copies, the switch
    clean = corpus.copy(source, tmp_path, "clean.mkv")
    assert apply_header_edit(long_title(clean)).ok
    assert path.read_bytes() == clean.read_bytes()


@pytest.mark.parametrize("kept", [3, 9, 200])
def test_a_torn_copy_after_the_segment_reads_old_and_is_cleaned_up(
    header_corpus: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kept: int,
) -> None:
    """Defect: a crash in the middle of writing the moved copies (only ``kept`` bytes of them
    reach the file) leaves a file that cannot be opened or edited again."""
    source = header_corpus["ffmpeg-multitrack"]
    path = corpus.copy(source, tmp_path, "t.mkv")

    class TornIO(FILE_IO):
        def write(self, pos: int, data: bytes) -> None:
            super().write(pos, data[:kept])
            raise OSError(errno.EIO, "torn by the test")

    monkeypatch.setattr(header, "_FileIO", TornIO)
    assert apply_header_edit(long_title(path)).status == "failed"
    assert path.stat().st_size == source.stat().st_size + kept
    assert view(path) == view(source)

    monkeypatch.setattr(header, "_FileIO", FILE_IO)
    assert apply_header_edit(long_title(path)).ok
    clean = corpus.copy(source, tmp_path, "clean.mkv")
    assert apply_header_edit(long_title(clean)).ok
    assert path.read_bytes() == clean.read_bytes()
