"""The writer stopped after each of its writes: every file left opens in ffprobe and
``mkvmerge -J`` with all the old values or all the new ones."""

from __future__ import annotations

import errno
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, BinaryIO, cast

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


def any_view(path: Path) -> tuple[Any, ...]:
    """:func:`view`, with an error text for a reader that cannot read the file."""
    out: list[Any] = []
    for read in (corpus.reader_values, corpus.mkvmerge_view, corpus.ffprobe_view):
        try:
            out.append(read(path))
        except Exception as exc:
            out.append(f"cannot read: {exc!r}")
    return tuple(out)


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
        if allowed == 0:
            assert path.read_bytes() == source.read_bytes()
            assert result.file_state == "unchanged"
        else:
            assert result.file_state in ("old", "new")
        assert state == (new if result.file_state == "new" else old), f"stopped after {allowed}"
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


class Partial:
    """A file handle whose next ``write`` stores only ``keep`` bytes and whose retry fails, as
    the kernel does when the disk fills up part-way through a write."""

    def __init__(self, handle: Any, keep: int) -> None:
        self._handle = handle
        self._keep = keep
        self._calls = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._handle, name)

    def write(self, data: memoryview) -> int:
        self._calls += 1
        if self._calls == 1:
            written: int = self._handle.write(data[: self._keep])
            return written
        raise OSError(errno.ENOSPC, "No space left on device")


def tear(monkeypatch: pytest.MonkeyPatch, at: int, keep: int, *, later: bool = True) -> None:
    """Write number ``at`` (from 0) stores ``keep`` bytes, then fails; the writes after it
    succeed only with ``later``."""
    count = [0]

    class TornIO(FILE_IO):
        def write(self, pos: int, data: bytes) -> None:
            index = count[0]
            count[0] += 1
            if index == at:
                handle = self._handle
                self._handle = cast(BinaryIO, Partial(handle, keep))
                try:
                    super().write(pos, data)
                finally:
                    self._handle = handle
            elif index > at and not later:
                raise OSError(errno.ENOSPC, "No space left on device")
            else:
                super().write(pos, data)

        def truncate(self, size: int) -> None:
            count[0] += 1
            super().truncate(size)

    monkeypatch.setattr(header, "_FileIO", TornIO)


def recorded_writes(
    monkeypatch: pytest.MonkeyPatch, make_edit: Callable[[Path], HeaderEdit], path: Path
) -> list[tuple[int, int]]:
    """``(position, length)`` of each write of the edit (a truncate is ``(size, -1)``)."""
    writes: list[tuple[int, int]] = []

    class RecordingIO(FILE_IO):
        def write(self, pos: int, data: bytes) -> None:
            writes.append((pos, len(data)))
            super().write(pos, data)

        def truncate(self, size: int) -> None:
            writes.append((size, -1))
            super().truncate(size)

    monkeypatch.setattr(header, "_FileIO", RecordingIO)
    assert apply_header_edit(make_edit(path)).ok
    monkeypatch.setattr(header, "_FileIO", FILE_IO)
    return writes


def cuts(source: bytes, pos: int, length: int) -> list[int]:
    """How many bytes of a write of ``length`` bytes at ``pos`` reach the file: 1, every
    tenth of it, two bytes into each element header in it, and all but one."""
    keeps = {1, length - 1, *range(1, length, max(1, length // 10))}
    seg = corpus.segment(source)
    starts = [seg.size_pos] + [t.pos for t in seg.top]
    keeps |= {start - pos + 2 for start in starts if pos <= start and start + 2 < pos + length}
    return sorted(k for k in keeps if 0 < k < length)


# name: (corpus file, edit, the index of the switch among the writes)
TORN: dict[str, tuple[str, Callable[[Path], HeaderEdit], int]] = {
    "in place": ("ffmpeg-multitrack", corpus.shrink_edit, 0),
    "tracks moves": ("ffmpeg-multitrack", lambda p: corpus.multitrack_edit(p, long=True), 1),
    "CRC-32, both move": ("mkvmerge-crc", long_title, 1),
    "second SeekHead moves": ("mkvpropedit-linked", long_title, 1),
}


@pytest.mark.parametrize("scenario", list(TORN))
def test_a_switch_torn_by_a_full_disk_is_put_back_and_says_so(
    header_corpus: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> None:
    """Defect: the disk fills up part-way through the switch, the part written stays, and
    the result says "old or new" of a file that ffprobe, mkvmerge and Reframe read
    differently, or cannot read."""
    name, make_edit, at = TORN[scenario]
    source = header_corpus[name]
    original = source.read_bytes()
    old = view(source)
    writes = recorded_writes(monkeypatch, make_edit, corpus.copy(source, tmp_path, "full.mkv"))
    pos, length = writes[at]
    problems: list[str] = []
    for keep in cuts(original, pos, length):
        path = corpus.copy(source, tmp_path, f"torn-{keep}.mkv")
        tear(monkeypatch, at, keep)
        result = apply_header_edit(make_edit(path))
        state = any_view(path)
        if state != old:
            readers = ("reader", "mkvmerge", "ffprobe")
            problems.append(
                f"{keep}/{length} bytes: "
                + ", ".join(
                    f"{r} {'old' if s == o else 'not old'}"
                    for r, s, o in zip(readers, state, old, strict=True)
                )
                + f"; result {result.status} {getattr(result, 'file_state', None)}: {result.reason}"
            )
            continue
        if path.read_bytes()[: len(original)] != original:
            problems.append(f"{keep}/{length} bytes: the old bytes are not back")
        said = (result.status, result.code, getattr(result, "file_state", None))
        if said != ("failed", "header.io_error", "unchanged" if at == 0 else "old"):
            problems.append(f"{keep}/{length} bytes: the result says {said}: {result.reason}")
    assert not problems, "\n".join(problems)


def test_a_torn_clean_up_after_the_switch_is_put_back_and_says_new(
    header_corpus: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defect: the clean-up write behind the clusters, torn, leaves a broken element there and
    a result that does not say the new values are in the file."""
    source = header_corpus["reframe-moved"]
    original = source.read_bytes()
    full = corpus.copy(source, tmp_path, "full.mkv")
    writes = recorded_writes(monkeypatch, long_title, full)
    assert len(writes) == 3
    new = view(full)
    clean = full.read_bytes()
    pos, length = writes[2]
    for keep in range(1, length):
        path = corpus.copy(source, tmp_path, f"torn-{keep}.mkv")
        tear(monkeypatch, 2, keep)
        result = apply_header_edit(long_title(path))
        assert view(path) == new, keep
        data = path.read_bytes()
        assert data[pos : pos + length] == original[pos : pos + length], keep
        assert data[:pos] == clean[:pos], keep
        assert (result.status, result.file_state) == ("failed", "new"), keep


@pytest.mark.parametrize("scenario", ["in place", "tracks moves"])
def test_a_torn_switch_that_cannot_be_put_back_is_reported_damaged_with_its_bytes(
    header_corpus: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> None:
    """Defect: the old bytes cannot be written back either, and the result still says the
    file holds old or new values; or the old bytes are lost."""
    name, make_edit, at = TORN[scenario]
    source = header_corpus[name]
    original = source.read_bytes()
    writes = recorded_writes(monkeypatch, make_edit, corpus.copy(source, tmp_path, "full.mkv"))
    pos, length = writes[at]
    path = corpus.copy(source, tmp_path, "torn.mkv")
    tear(monkeypatch, at, length // 2, later=False)
    result = apply_header_edit(make_edit(path))
    assert (result.status, result.code, result.file_state) == (
        "failed",
        "header.io_error",
        "damaged",
    )
    assert result.reason is not None
    assert "back" in result.reason
    assert path.read_bytes()[pos : pos + length] != original[pos : pos + length]
    assert result.backup is not None
    assert (result.backup.offset, result.backup.data) == (pos, original[pos : pos + length])

    with open(path, "r+b") as handle:  # what the user can do with the saved bytes
        handle.seek(result.backup.offset)
        handle.write(result.backup.data)
    assert path.read_bytes()[: len(original)] == original
    assert view(path) == view(source)


@pytest.mark.parametrize("scenario", ["in place", "tracks moves"])
def test_a_switch_whose_sync_fails_is_put_back(
    header_corpus: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> None:
    """Defect: the switch's ``fsync`` fails (the disk may not hold it), and the result says
    "old or new" while every reader reads the new values from the cache."""
    name, make_edit, at = TORN[scenario]
    source = header_corpus[name]
    path = corpus.copy(source, tmp_path, "t.mkv")
    count = [0]

    class FailingSync(FILE_IO):
        def sync(self) -> None:
            count[0] += 1
            if count[0] == at + 1:
                raise OSError(errno.EIO, "Input/output error")
            super().sync()

    monkeypatch.setattr(header, "_FileIO", FailingSync)
    result = apply_header_edit(make_edit(path))
    assert view(path) == view(source)
    assert (result.status, result.file_state) == ("failed", "unchanged" if at == 0 else "old")


def test_too_little_free_space_writes_nothing(
    header_corpus: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defect: the writer starts on a nearly full disk, where a write can stop part-way."""
    path = corpus.copy(header_corpus["ffmpeg-multitrack"], tmp_path, "t.mkv")
    before = path.read_bytes()
    usage = shutil.disk_usage(path)
    monkeypatch.setattr(shutil, "disk_usage", lambda _: usage._replace(free=4 * 1024 * 1024))
    result = apply_header_edit(long_title(path))
    assert (result.status, result.code, result.file_state) == (
        "failed",
        "header.no_space",
        "unchanged",
    )
    assert result.reason is not None
    assert "MB" in result.reason
    assert path.read_bytes() == before


def test_a_file_system_that_reports_no_size_is_written(
    header_corpus: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defect: a share that reports a size of 0 refuses every edit."""
    path = corpus.copy(header_corpus["ffmpeg-multitrack"], tmp_path, "t.mkv")
    usage = shutil.disk_usage(path)
    monkeypatch.setattr(shutil, "disk_usage", lambda _: usage._replace(total=0, used=0, free=0))
    assert apply_header_edit(long_title(path)).ok


def test_an_edit_in_place_removes_the_leftovers_of_a_stopped_edit(
    header_corpus: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defect: the copies a stopped edit left after the segment stay there for good when the
    next edit fits in place."""
    source = header_corpus["ffmpeg-multitrack"]
    path = corpus.copy(source, tmp_path, "t.mkv")
    Stop(1).install(monkeypatch)
    assert apply_header_edit(long_title(path)).status == "failed"
    assert path.stat().st_size > source.stat().st_size

    Stop(None).install(monkeypatch)
    assert apply_header_edit(corpus.shrink_edit(path)).ok
    clean = corpus.copy(source, tmp_path, "clean.mkv")
    assert apply_header_edit(corpus.shrink_edit(clean)).ok
    assert path.read_bytes() == clean.read_bytes()
