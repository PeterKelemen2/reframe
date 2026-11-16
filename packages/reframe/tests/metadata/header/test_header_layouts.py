"""Unusual layouts, built byte by byte: where the writer puts an edit, and what it refuses."""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest

from reframe.metadata import header
from reframe.metadata.header import apply_header_edit
from reframe.metadata.layout import read_layout
from reframe.models.plan import HeaderEdit, InfoHeaderEdit, TrackHeaderEdit
from reframe.probe.matroska import MatroskaError, _Reader, read_matroska, tracks_by_kind
from reframe_testing.ebml import encode_size

from . import corpus
from .corpus import Track

AUDIO = [Track("video", name="V"), Track("audio", name="A", language="eng")]


def write(tmp_path: Path, data: bytes, name: str = "t.mkv") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def audio_name(path: Path, name: str) -> HeaderEdit:
    return HeaderEdit(path=path, tracks=[TrackHeaderEdit(track_type="audio", number=1, name=name)])


def audio(path: Path) -> object:
    return tracks_by_kind(read_matroska(path))["audio"][0]


def refused(path: Path, edit: HeaderEdit, code: str) -> None:
    before = path.read_bytes()
    result = apply_header_edit(edit)
    assert (result.status, result.code) == ("refused", code), result
    assert path.read_bytes() == before


def test_a_grown_size_field_is_widened_in_place(tmp_path: Path) -> None:
    """Defect: ``Tracks`` that outgrows its 1-byte size field is moved (or damaged) though
    the ``Void`` after it has room."""
    path = write(tmp_path, corpus.synthetic([Track("audio", name="A")], room=600))
    before = corpus.segment(path.read_bytes())
    assert before.first(corpus.TRACKS).header == 5
    assert apply_header_edit(audio_name(path, "x" * 300)).ok

    after = corpus.segment(path.read_bytes())
    tracks = after.first(corpus.TRACKS)
    assert tracks.pos == before.first(corpus.TRACKS).pos
    assert tracks.header == 6
    assert len(path.read_bytes()) == before.base + (before.size or 0)
    assert read_matroska(path).tracks[0].name == "x" * 300


def test_duplicate_flag_elements_become_one(tmp_path: Path) -> None:
    """Defect: a track with two ``FlagDefault`` elements keeps the one readers take last."""
    track = Track("audio", flags=(("default", True), ("default", True)))
    path = write(tmp_path, corpus.synthetic([track], room=40))
    edit = HeaderEdit(
        path=path,
        tracks=[TrackHeaderEdit(track_type="audio", number=1, flags={"default": True})],
    )
    assert apply_header_edit(edit).ok

    tracks = corpus.segment(path.read_bytes()).first(corpus.TRACKS)
    entry = corpus.kids(path.read_bytes()[tracks.data : tracks.end])[0][1]
    flags = [raw for i, raw in corpus.kids(entry[2:]) if i == corpus.FLAG_IDS["default"]]
    assert flags == [corpus.element(0x88, b"\x01")]


def test_a_short_write_is_an_os_error() -> None:
    class Stuck(io.BytesIO):
        def write(self, data: object) -> int:
            return 0

    with pytest.raises(OSError, match="short write"):
        header._FileIO(Stuck()).write(0, b"data")


def front_seek_heads(*, crc: bool = False) -> bytes:
    """Two ``SeekHead`` elements before the clusters: the first only links to the second,
    which lists ``Info`` and ``Tracks`` (with a ``Void`` child and an unknown child)."""
    ebml = corpus.element(0x1A45DFA3, corpus.element(0x4282, b"matroska"))
    info = corpus.element(corpus.INFO, corpus.element(0x7BA9, b"Title"))
    tracks = corpus.element(
        corpus.TRACKS,
        corpus.track_entry(1, Track("audio", name="A", language="eng")) + corpus.any_void(3),
    )
    first_len = len(corpus.with_crc(corpus.SEEK_HEAD, [corpus.seek(corpus.SEEK_HEAD, 0, 4)], crc))

    def second(info_at: int, tracks_at: int) -> bytes:
        odd = corpus.element(
            corpus.SEEK,
            corpus.element(corpus.SEEK_ID, corpus.TRACKS.to_bytes(4, "big"))
            + corpus.element(corpus.SEEK_POSITION, tracks_at.to_bytes(4, "big"))
            + corpus.element(0x4321, b"?"),
        )
        entries = [corpus.seek(corpus.INFO, info_at, 4), odd, corpus.any_void(4)]
        return corpus.with_crc(corpus.SEEK_HEAD, entries, crc)

    second_at = first_len + 40
    info_at = second_at + len(second(0, 0)) + 60
    tracks_at = info_at + len(info)
    body = (
        corpus.with_crc(corpus.SEEK_HEAD, [corpus.seek(corpus.SEEK_HEAD, second_at, 4)], crc)
        + corpus.any_void(40)
        + second(info_at, tracks_at)
        + corpus.any_void(60)
        + info
        + tracks
        + corpus.element(corpus.CLUSTER, corpus.element(0xE7, b"\x00"))
    )
    return ebml + corpus.SEGMENT.to_bytes(4, "big") + encode_size(len(body), 8) + body


@pytest.mark.parametrize("crc", [False, True])
def test_a_second_seek_head_before_the_clusters_is_rewritten_in_place(
    tmp_path: Path, crc: bool
) -> None:
    """Defect: the entry for a moved ``Tracks`` in a second ``SeekHead`` still points to the
    old place (readers that follow it find a ``Void``)."""
    path = write(tmp_path, front_seek_heads(crc=crc))
    first = corpus.segment(path.read_bytes()).top[0]
    first_bytes = path.read_bytes()[first.pos : first.end]
    assert apply_header_edit(audio_name(path, "x" * 500)).ok

    data = path.read_bytes()
    assert data[first.pos : first.end] == first_bytes
    seg = corpus.segment(data)
    assert seg.top[-1].id == corpus.TRACKS
    assert read_matroska(path).tracks[0].name == "x" * 500
    assert corpus.crc_problems(path) == []


def test_a_linked_seek_head_that_lists_no_moved_element_stays(tmp_path: Path) -> None:
    """Defect: a second ``SeekHead`` behind the clusters is moved or emptied though it lists
    nothing that moves."""
    data = corpus.synthetic(AUDIO)
    seg = corpus.segment(data)
    cluster = seg.first(corpus.CLUSTER)
    linked = corpus.with_crc(
        corpus.SEEK_HEAD, [corpus.seek(corpus.CLUSTER, cluster.pos - seg.base, 4)], False
    )
    link = corpus.seek(corpus.SEEK_HEAD, len(data) - seg.base, 4)
    head, gap = seg.top[0], seg.top[1]
    new_head = corpus.rebuild_seek_head(data, seg, {}, [link])
    data = corpus.splice(
        data, head.pos, gap.end, new_head + corpus.any_void(gap.end - head.pos - len(new_head))
    )
    data = (
        data[: seg.size_pos] + encode_size(len(data) - seg.base + len(linked), 8) + data[seg.base :]
    )
    path = write(tmp_path, data + linked)
    linked_at = len(data)
    assert apply_header_edit(audio_name(path, "x" * 500)).ok

    after = path.read_bytes()
    assert after[linked_at : linked_at + len(linked)] == linked
    assert read_matroska(path).tracks[1].name == "x" * 500


def test_a_seek_entry_that_points_away_from_the_tracks_is_refused(tmp_path: Path) -> None:
    data = corpus.synthetic(AUDIO)
    seg = corpus.segment(data)
    info = seg.first(corpus.INFO)
    head, gap = seg.top[0], seg.top[1]
    new_head = corpus.rebuild_seek_head(data, seg, {corpus.TRACKS: info.pos - seg.base})
    region = new_head + corpus.any_void(gap.end - head.pos - len(new_head))
    path = write(tmp_path, corpus.splice(data, head.pos, gap.end, region))
    refused(path, audio_name(path, "B"), "header.seek_head")


def test_a_seek_head_link_past_the_segment_is_refused(tmp_path: Path) -> None:
    data = corpus.synthetic(AUDIO)
    seg = corpus.segment(data)
    link = corpus.seek(corpus.SEEK_HEAD, len(data), 4)
    head, gap = seg.top[0], seg.top[1]
    new_head = corpus.rebuild_seek_head(data, seg, {}, [link])
    region = new_head + corpus.any_void(gap.end - head.pos - len(new_head))
    path = write(tmp_path, corpus.splice(data, head.pos, gap.end, region))
    refused(path, audio_name(path, "B"), "header.seek_head")


def test_an_element_of_unknown_size_before_the_clusters_is_refused(tmp_path: Path) -> None:
    """The probe's reader stops at it and still finds ``Tracks`` through the ``SeekHead``;
    the writer cannot know where the element ends."""
    data = bytearray(corpus.synthetic(AUDIO))
    gap = corpus.segment(bytes(data)).top[1]
    assert gap.id == corpus.VOID
    assert gap.header == 9
    data[gap.pos + 1 : gap.pos + 9] = b"\x01" + b"\xff" * 7
    path = write(tmp_path, bytes(data))
    read_matroska(path)
    refused(path, audio_name(path, "B"), "header.unreadable")


def test_a_child_that_overruns_its_track_entry_is_refused(tmp_path: Path) -> None:
    """The probe's reader cuts the name short; the writer would copy the bytes after it."""
    data = bytearray(corpus.synthetic(AUDIO, room=40))
    at = bytes(data).index(b"\x53\x6e\x81A")
    data[at + 2] = 0x84
    path = write(tmp_path, bytes(data))
    read_matroska(path)
    refused(path, audio_name(path, "B"), "header.unreadable")


def test_a_seek_head_with_more_entries_than_the_limit_is_refused(tmp_path: Path) -> None:
    """The probe's reader looks at the first ``MAX_CHILDREN`` entries only; the writer would
    rewrite entries it has not checked."""
    path = write(tmp_path, corpus.synthetic(AUDIO, extra_seeks=4096))
    read_matroska(path)
    refused(path, audio_name(path, "x" * 500), "header.unreadable")


def test_a_file_without_clusters_is_edited(tmp_path: Path) -> None:
    path = write(tmp_path, corpus.synthetic(AUDIO, room=40, cluster=False))
    assert apply_header_edit(audio_name(path, "B")).ok
    assert read_matroska(path).tracks[1].name == "B"


def test_tracks_behind_the_clusters_use_the_void_after_them(tmp_path: Path) -> None:
    """Defect: a ``Tracks`` already moved behind the clusters moves again (the file grows)
    though it fits with the ``Void`` after it, here in a segment of unknown size."""
    path = write(tmp_path, corpus.synthetic(AUDIO))
    assert apply_header_edit(audio_name(path, "x" * 500)).ok
    assert apply_header_edit(audio_name(path, "y")).ok
    path.write_bytes(corpus.unknown_size(path.read_bytes()))
    size = os.path.getsize(path)
    tracks = corpus.segment(path.read_bytes()).first(corpus.TRACKS)

    assert apply_header_edit(audio_name(path, "z" * 400)).ok
    assert os.path.getsize(path) == size
    assert corpus.segment(path.read_bytes()).first(corpus.TRACKS).pos == tracks.pos
    assert read_matroska(path).tracks[1].name == "z" * 400


def grow_segment(data: bytes, extra: bytes) -> bytes:
    seg = corpus.segment(data)
    size = encode_size(len(data) - seg.base + len(extra), 8)
    return data[: seg.size_pos] + size + data[seg.base :] + extra


def test_the_scans_after_the_segment_and_behind_the_clusters_stop_at_the_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Defect: a scan for ``Void`` elements or for a stopped edit's copies that reads past
    ``MAX_TOP_LEVEL`` elements."""
    path = write(tmp_path, corpus.synthetic(AUDIO))
    assert apply_header_edit(audio_name(path, "x" * 500)).ok
    path.write_bytes(grow_segment(path.read_bytes(), corpus.any_void(2) * 6))
    monkeypatch.setattr("reframe.probe.matroska.MAX_TOP_LEVEL", 5)
    assert apply_header_edit(audio_name(path, "y")).ok
    assert read_matroska(path).tracks[1].name == "y"

    path.write_bytes(path.read_bytes() + corpus.any_void(2) * 6)
    refused(path, audio_name(path, "z" * 600), "header.trailing_data")


def test_removing_the_title_of_a_file_without_info_changes_nothing(tmp_path: Path) -> None:
    path = write(tmp_path, corpus.synthetic(AUDIO))
    path.write_bytes(corpus.no_info(path.read_bytes()))
    before = path.read_bytes()
    result = apply_header_edit(HeaderEdit(path=path, info=InfoHeaderEdit(title=None)))
    assert result.status == "written"
    assert path.read_bytes() == before


def layout_of(data: bytes, tmp_path: Path) -> object:
    path = write(tmp_path, data)
    with open(path, "rb") as handle:
        return read_layout(_Reader(handle, len(data)))


def test_the_layout_needs_a_segment_and_tracks(tmp_path: Path) -> None:
    data = corpus.synthetic(AUDIO)
    seg = corpus.segment(data)
    with pytest.raises(MatroskaError, match="no Segment"):
        layout_of(data[: seg.pos] + b"\x1f\x43\xb6\x75" + data[seg.pos + 4 :], tmp_path)
    tracks = seg.first(corpus.TRACKS)
    no_tracks = corpus.splice(data, tracks.pos, tracks.end, corpus.void(tracks.end - tracks.pos))
    no_entry = corpus.rebuild_seek_head(no_tracks, seg, {corpus.TRACKS: 0})
    no_entry = no_entry.replace(
        corpus.TRACKS.to_bytes(4, "big"), corpus.CHAPTERS.to_bytes(4, "big")
    )
    head = seg.top[0]
    no_tracks = corpus.splice(no_tracks, head.pos, head.end, no_entry[: head.end - head.pos])
    with pytest.raises(MatroskaError, match="no Tracks"):
        layout_of(no_tracks, tmp_path)
