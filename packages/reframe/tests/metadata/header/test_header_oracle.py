"""The writer against mkvpropedit: the same edit reads back the same in ``mkvmerge -J``, and
ffprobe still reads every stream."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest

from reframe.metadata.header import apply_header_edit
from reframe.models.plan import HeaderEdit, InfoHeaderEdit, TrackHeaderEdit
from reframe.probe.matroska import read_matroska, tracks_by_kind

from . import corpus

pytestmark = [pytest.mark.needs_ffmpeg, pytest.mark.needs_mkvtoolnix]

MULTITRACK = (
    "ffmpeg-multitrack",
    "mkvmerge-reordered",
    "mkvmerge-crc",
    "mkvpropedit-moved",
    "mkvpropedit-linked",
    "reframe-moved",
)
OTHERS = ("ffmpeg-text-subs", "ffmpeg-chapters")


def shrink(path: Path) -> HeaderEdit:
    return corpus.generic_edit(path).model_copy(
        update={"tracks": [corpus.shrink_edit(path).tracks[0]]}
    )


def demo(path: Path) -> HeaderEdit:
    return corpus.multitrack_edit(path)


def demo_long(path: Path) -> HeaderEdit:
    return corpus.multitrack_edit(path, long=True, title=None)


def demo_long_title(path: Path) -> HeaderEdit:
    return corpus.multitrack_edit(path, long=True, title="Hosszú cím " * 300)


def generic(path: Path) -> HeaderEdit:
    return corpus.generic_edit(path, title="Új cím")


def generic_long(path: Path) -> HeaderEdit:
    return corpus.generic_edit(path, long=True, title="T" * 3000)


def remove_title(path: Path) -> HeaderEdit:
    return HeaderEdit(path=path, info=InfoHeaderEdit(title=None))


EDITS: dict[str, Callable[[Path], HeaderEdit]] = {
    "shrink": shrink,
    "demo": demo,
    "demo-long": demo_long,
    "demo-long-title": demo_long_title,
    "generic": generic,
    "generic-long": generic_long,
    "remove-title": remove_title,
}
CASES = [
    (name, edit)
    for name in MULTITRACK
    for edit in ("shrink", "demo", "demo-long", "demo-long-title", "remove-title")
] + [(name, edit) for name in OTHERS for edit in ("shrink", "generic", "generic-long")]


@pytest.mark.parametrize(("name", "edit_name"), CASES)
def test_the_writer_and_mkvpropedit_read_back_the_same(
    header_corpus: dict[str, Path], tmp_path: Path, name: str, edit_name: str
) -> None:
    """Defect: a value, a flag, a track or an attachment that mkvmerge or ffprobe reads
    differently after Reframe's edit than after mkvpropedit's, or a stream ffprobe loses."""
    source = header_corpus[name]
    ours = corpus.copy(source, tmp_path, "ours.mkv")
    theirs = corpus.copy(source, tmp_path, "theirs.mkv")
    edit = EDITS[edit_name](ours)

    result = apply_header_edit(edit)
    assert result.status == "written", result
    oracle = corpus.mkvpropedit(edit, theirs)
    assert oracle.returncode == 0, oracle.stdout

    assert corpus.mkvmerge_view(ours) == corpus.mkvmerge_view(theirs)
    assert corpus.mkvmerge_view(ours)["errors"] == []
    before = corpus.ffprobe_view(source)
    after = corpus.ffprobe_view(ours)
    assert after == corpus.ffprobe_view(theirs)
    assert [s[:2] for s in after] == [s[:2] for s in before]
    assert read_matroska(ours) == read_matroska(theirs)
    assert corpus.crc_problems(ours) == []


@pytest.mark.parametrize("name", MULTITRACK)
def test_six_thousand_character_names_move_tracks_behind_the_clusters(
    header_corpus: dict[str, Path], tmp_path: Path, name: str
) -> None:
    """Defect: a ``Tracks`` that outgrows its place is written over the element after it."""
    ours = corpus.copy(header_corpus[name], tmp_path, "ours.mkv")
    old = corpus.segment(ours.read_bytes())
    name = "Ő" * (corpus.LONG + 100)
    edit = HeaderEdit(path=ours, tracks=[TrackHeaderEdit(track_type="audio", number=1, name=name)])
    assert apply_header_edit(edit).ok

    new = corpus.segment(ours.read_bytes())
    cluster = new.first(corpus.CLUSTER).pos
    tracks = [t for t in new.top if t.id == corpus.TRACKS]
    assert len(tracks) == 1
    assert tracks[0].pos > cluster
    assert new.top[-1].id == corpus.TRACKS or new.top[-1].id == corpus.SEEK_HEAD
    old_tracks = old.first(corpus.TRACKS)
    assert next(t for t in new.top if t.pos == old_tracks.pos).id == corpus.VOID
    assert os.path.getsize(ours) == new.base + (new.size or 0)
    assert tracks_by_kind(read_matroska(ours))["audio"][0].name == name


@pytest.mark.parametrize("name", ["ffmpeg-multitrack", "mkvmerge-reordered"])
def test_an_edit_that_fits_changes_only_the_header(
    header_corpus: dict[str, Path], tmp_path: Path, name: str
) -> None:
    """Defect: an edit that fits rewrites more than its own element, or grows the file."""
    source = header_corpus[name]
    ours = corpus.copy(source, tmp_path, "ours.mkv")
    tracks = corpus.segment(source.read_bytes()).first(corpus.TRACKS)
    assert apply_header_edit(shrink(ours)).ok

    before, after = source.read_bytes(), ours.read_bytes()
    assert len(after) == len(before)
    changed = [i for i in range(len(before)) if before[i] != after[i]]
    assert changed
    assert tracks.pos <= changed[0]
    assert changed[-1] < tracks.end


def test_an_edit_the_file_has_writes_nothing(
    header_corpus: dict[str, Path], tmp_path: Path
) -> None:
    """Defect: a no-op edit still writes (and so needs a writable file), or reports a
    failure."""
    ours = corpus.copy(header_corpus["ffmpeg-multitrack"], tmp_path, "ours.mkv")
    assert apply_header_edit(demo(ours)).ok
    data = ours.read_bytes()
    ours.chmod(0o444)
    try:
        result = apply_header_edit(demo(ours))
    finally:
        ours.chmod(0o644)
    assert result.status == "written"
    assert ours.read_bytes() == data
