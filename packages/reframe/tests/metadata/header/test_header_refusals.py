"""Files the writer cannot edit safely are refused, and stay byte for byte unchanged; OS
errors are failures, not exceptions."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from reframe.metadata import header
from reframe.metadata.header import apply_header_edit
from reframe.models.plan import HeaderEdit, InfoHeaderEdit, TrackHeaderEdit
from reframe.probe import matroska

from . import corpus
from .corpus import Track

LONG_TITLE = "T" * 3000


def grow(path: Path) -> HeaderEdit:
    return corpus.multitrack_edit(path, long=True, title=LONG_TITLE)


def set_title(path: Path) -> HeaderEdit:
    return HeaderEdit(path=path, info=InfoHeaderEdit(title="New title"))


def edit_track(path: Path, **values: object) -> HeaderEdit:
    track = TrackHeaderEdit.model_validate({"track_type": "audio", "number": 1, **values})
    return HeaderEdit(path=path, tracks=[track])


Surgery = Callable[[bytes], bytes]
Edit = Callable[[Path], HeaderEdit]

# (layout made from the multi-track fixture, edit, refusal code)
REFUSED: dict[str, tuple[Surgery, Edit, str]] = {
    "unknown segment size": (corpus.unknown_size, grow, "header.unknown_size"),
    "SeekHead without room": (corpus.info_after_seek_head, grow, "header.no_room"),
    "no SeekHead": (corpus.no_seek_head, grow, "header.no_room"),
    "hostile SeekHead entry": (corpus.hostile_seek_head, corpus.shrink_edit, "header.seek_head"),
    "CRC-32 mismatch": (corpus.crc_mismatch, corpus.shrink_edit, "header.unreadable"),
    "two Info elements": (corpus.second_info, corpus.shrink_edit, "header.duplicate"),
    "no Info": (corpus.no_info, set_title, "header.no_info"),
    "data after the segment": (corpus.trailing_data, grow, "header.trailing_data"),
    "an element of unknown size after the segment": (
        corpus.trailing_unknown_size,
        grow,
        "header.trailing_data",
    ),
    "truncated": (corpus.truncated, grow, "header.truncated"),
    "no such track": (
        lambda d: d,
        lambda p: edit_track(p, number=4, name="x"),
        "header.no_such_track",
    ),
    "NUL in a name": (lambda d: d, lambda p: edit_track(p, name="a\0b"), "header.invalid_value"),
    "non-ASCII language": (
        lambda d: d,
        lambda p: edit_track(p, language="hün", language_ietf="hu"),
        "header.invalid_value",
    ),
}

# The same layouts with an edit that fits in place: nothing needs to move.
FITS: dict[str, tuple[Surgery, Edit]] = {
    "unknown segment size": (corpus.unknown_size, corpus.shrink_edit),
    "SeekHead without room": (corpus.info_after_seek_head, corpus.shrink_edit),
    "no SeekHead": (corpus.no_seek_head, corpus.shrink_edit),
    "no Info": (corpus.no_info, corpus.shrink_edit),
    "data after the segment": (corpus.trailing_data, corpus.shrink_edit),
    "truncated": (corpus.truncated, corpus.shrink_edit),
}


def assert_refused(path: Path, edit: HeaderEdit, code: str) -> None:
    before = path.read_bytes()
    mtime = path.stat().st_mtime_ns
    result = apply_header_edit(edit)
    assert (result.status, result.code) == ("refused", code), result
    assert result.reason
    assert result.reason.endswith(".")
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == mtime


@pytest.mark.needs_ffmpeg
@pytest.mark.parametrize("case", list(REFUSED))
def test_a_refused_file_is_byte_for_byte_unchanged(
    fixture_media: Callable[[str], Path], tmp_path: Path, case: str
) -> None:
    """Defect: the writer edits a file it cannot edit safely (or damages it on the way to a
    refusal)."""
    surgery, make_edit, code = REFUSED[case]
    path = tmp_path / "t.mkv"
    path.write_bytes(surgery(fixture_media("multitrack").read_bytes()))
    assert_refused(path, make_edit(path), code)


@pytest.mark.needs_ffmpeg
@pytest.mark.parametrize("case", list(FITS))
def test_an_edit_that_fits_is_written_into_an_unusual_layout(
    fixture_media: Callable[[str], Path], tmp_path: Path, case: str
) -> None:
    """Defect: a refusal meant for a moved element also blocks an edit written in place."""
    surgery, make_edit = FITS[case]
    path = tmp_path / "t.mkv"
    path.write_bytes(surgery(fixture_media("multitrack").read_bytes()))
    assert apply_header_edit(make_edit(path)).ok
    audio = [t for t in matroska.read_matroska(path).tracks if t.kind == "audio"]
    assert audio[0].name is None
    assert audio[1].name is None


@pytest.mark.needs_ffmpeg
def test_a_file_that_is_not_matroska_is_refused(
    fixture_media: Callable[[str], Path], tmp_path: Path
) -> None:
    path = tmp_path / "t.mp4"
    path.write_bytes(fixture_media("vfr").with_suffix(".mp4").read_bytes())
    assert_refused(path, corpus.shrink_edit(path), "header.unreadable")


AUDIO = [Track("video", name="V"), Track("audio", name="A", language="eng")]


def write(tmp_path: Path, data: bytes) -> Path:
    path = tmp_path / "t.mkv"
    path.write_bytes(data)
    return path


@pytest.mark.parametrize(
    ("limit", "value", "code"),
    [
        ("MAX_READ", 200, "header.unreadable"),
        ("MAX_ELEMENTS", 10, "header.unreadable"),
        ("MAX_ELEMENT", 40, "header.unreadable"),
        ("MAX_TOP_LEVEL", 3, "header.unreadable"),
        ("MAX_CHILDREN", 2, "header.unreadable"),
        ("MAX_SEEK_HEAD", 20, "header.too_large"),
    ],
)
def test_a_header_beyond_the_reader_limits_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, limit: str, value: int, code: str
) -> None:
    """Defect: a read that ignores the reader's ``MAX_*`` limits (a hostile file then costs
    unbounded time and memory)."""
    path = write(tmp_path, corpus.synthetic(AUDIO * 2, room=40))
    edit = edit_track(path, name="B")
    monkeypatch.setattr(matroska, limit, value)
    assert_refused(path, edit, code)


def test_a_segment_size_field_too_short_for_the_move_is_refused(tmp_path: Path) -> None:
    path = write(tmp_path, corpus.synthetic(AUDIO, title=None, size_width=1, seek_head_room=0))
    assert_refused(path, edit_track(path, name="x" * 200), "header.no_room")


def test_a_seek_head_link_to_no_seek_head_is_refused(tmp_path: Path) -> None:
    data = corpus.synthetic(AUDIO)
    seg = corpus.segment(data)
    info = seg.first(corpus.INFO)
    link = corpus.seek(corpus.SEEK_HEAD, info.pos - seg.base, 4)
    head, gap = seg.top[0], seg.top[1]
    new_head = corpus.rebuild_seek_head(data, seg, {}, [link])
    region = new_head + corpus.any_void(gap.end - head.pos - len(new_head))
    path = write(tmp_path, corpus.splice(data, head.pos, gap.end, region))
    assert_refused(path, edit_track(path, name="B"), "header.seek_head")


def test_a_seek_entry_without_a_position_is_refused(tmp_path: Path) -> None:
    data = corpus.synthetic(AUDIO)
    seg = corpus.segment(data)
    broken = corpus.element(corpus.SEEK, corpus.element(corpus.SEEK_ID, corpus.TRACKS.to_bytes(4)))
    head, gap = seg.top[0], seg.top[1]
    new_head = corpus.rebuild_seek_head(data, seg, {}, [broken])
    region = new_head + corpus.any_void(gap.end - head.pos - len(new_head))
    path = write(tmp_path, corpus.splice(data, head.pos, gap.end, region))
    assert_refused(path, edit_track(path, name="B"), "header.seek_head")


def test_a_seek_entry_to_a_missing_element_is_refused(tmp_path: Path) -> None:
    """The segment information is a ``Void``, and its ``SeekHead`` entry still points
    there."""
    data = corpus.synthetic(AUDIO)
    info = corpus.segment(data).first(corpus.INFO)
    path = write(
        tmp_path, corpus.splice(data, info.pos, info.end, corpus.void(info.end - info.pos))
    )
    assert_refused(path, edit_track(path, name="B"), "header.seek_head")


def test_two_tracks_elements_are_refused(tmp_path: Path) -> None:
    data = corpus.synthetic(AUDIO, seek_head_room=200)
    seg = corpus.segment(data)
    gap = seg.top[1]
    tracks = data[seg.first(corpus.TRACKS).pos : seg.first(corpus.TRACKS).end]
    region = tracks + corpus.any_void(gap.end - gap.pos - len(tracks))
    path = write(tmp_path, corpus.splice(data, gap.pos, gap.end, region))
    assert_refused(path, edit_track(path, name="B"), "header.duplicate")


def test_a_plan_whose_states_do_not_read_back_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Defect: a planning mistake reaches the file instead of the self-check stopping it."""
    path = write(tmp_path, corpus.synthetic(AUDIO, room=40))
    tracks = corpus.segment(path.read_bytes()).first(corpus.TRACKS)
    plan = header._plan

    def damaged(*args: object) -> list[header._Step]:
        steps = plan(*args)  # type: ignore[arg-type]
        return [header._Write(tracks.pos, b"\0" * 8), *steps]

    monkeypatch.setattr(header, "_plan", damaged)
    assert_refused(path, edit_track(path, name="B"), "header.unsafe_layout")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores modes")
def test_a_file_that_cannot_be_written_is_a_failure_and_unchanged(tmp_path: Path) -> None:
    path = write(tmp_path, corpus.synthetic(AUDIO, room=40))
    before = path.read_bytes()
    path.chmod(0o444)
    try:
        result = apply_header_edit(edit_track(path, name="B"))
    finally:
        path.chmod(0o644)
    assert (result.status, result.code, result.file_state) == (
        "failed",
        "header.io_error",
        "unchanged",
    )
    assert path.read_bytes() == before


def test_a_missing_file_is_a_failure(tmp_path: Path) -> None:
    result = apply_header_edit(edit_track(tmp_path / "gone.mkv", name="B"))
    assert (result.status, result.code) == ("failed", "header.io_error")


def test_a_file_that_changes_while_it_is_read_is_not_written(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Defect: the writer writes a plan made for other bytes."""
    path = write(tmp_path, corpus.synthetic(AUDIO, room=40))
    prepare = header._prepare

    def changing(handle: object, edit: HeaderEdit) -> list[header._Step]:
        steps = prepare(handle, edit)  # type: ignore[arg-type]
        with open(path, "ab") as other:
            other.write(b"\0")
        return steps

    monkeypatch.setattr(header, "_prepare", changing)
    before = path.read_bytes()
    result = apply_header_edit(edit_track(path, name="B"))
    assert (result.status, result.code) == ("failed", "header.changed")
    assert path.read_bytes() == before + b"\0"
