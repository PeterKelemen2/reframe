"""The header writer's test corpus, made at test time, and the oracle reads.

The byte surgery here parses files with nothing but ``_header`` of the probe's reader, so the
damaged and unusual layouts do not depend on the writer's own layout code.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reframe.models.plan import HeaderEdit, InfoHeaderEdit, TrackHeaderEdit
from reframe.probe.matroska import _header, read_matroska
from reframe_testing import media
from reframe_testing.mkvtoolnix import mkvpropedit_args, mkvtoolnix_tool

SEGMENT = 0x18538067
SEEK_HEAD = 0x114D9B74
INFO = 0x1549A966
TRACKS = 0x1654AE6B
CLUSTER = 0x1F43B675
CHAPTERS = 0x1043A770
VOID = 0xEC
CRC = 0xBF
SEEK = 0x4DBB
SEEK_ID = 0x53AB
SEEK_POSITION = 0x53AC
TRACK_ENTRY = 0xAE

LONG = 6000


@dataclass(frozen=True)
class Top:
    id: int
    pos: int
    header: int
    size: int

    @property
    def end(self) -> int:
        return self.pos + self.header + self.size

    @property
    def data(self) -> int:
        return self.pos + self.header


@dataclass(frozen=True)
class Segment:
    pos: int
    size_pos: int
    base: int
    size: int | None
    top: list[Top]
    """Every top-level element of the segment, in file order (clusters included)."""

    def first(self, element_id: int) -> Top:
        return next(t for t in self.top if t.id == element_id)


def segment(data: bytes) -> Segment:
    _, size, header = _header(data, 0)
    assert size is not None
    pos = header + size
    _, seg_size, seg_header = _header(data, pos)
    base = pos + seg_header
    end = len(data) if seg_size is None else min(len(data), base + seg_size)
    top: list[Top] = []
    cursor = base
    while cursor < end:
        element_id, element_size, element_header = _header(data, cursor)
        assert element_size is not None
        top.append(Top(element_id, cursor, element_header, element_size))
        cursor += element_header + element_size
    return Segment(pos, pos + 4, base, seg_size, top)


def encode_size(size: int, width: int | None = None) -> bytes:
    width = width or next(w for w in range(1, 9) if size < (1 << (7 * w)) - 1)
    return ((1 << (7 * width)) | size).to_bytes(width, "big")


def element(element_id: int, payload: bytes, width: int | None = None) -> bytes:
    raw_id = element_id.to_bytes((element_id.bit_length() + 7) // 8, "big")
    return raw_id + encode_size(len(payload), width) + payload


def void(total: int) -> bytes:
    """A whole ``Void`` element of ``total`` bytes (at least 9)."""
    return bytes([VOID]) + encode_size(total - 9, 8) + bytes(total - 9)


def kids(payload: bytes) -> list[tuple[int, bytes]]:
    """``(id, raw child)`` of a master payload."""
    out: list[tuple[int, bytes]] = []
    pos = 0
    while pos < len(payload):
        element_id, size, header = _header(payload, pos)
        assert size is not None
        out.append((element_id, payload[pos : pos + header + size]))
        pos += header + size
    return out


def with_crc(element_id: int, children: list[bytes], crc: bool, width: int | None = None) -> bytes:
    body = b"".join(children)
    if crc:
        body = element(CRC, zlib.crc32(body).to_bytes(4, "little")) + body
    return element(element_id, body, width)


def seek(target: int, position: int, width: int) -> bytes:
    raw_id = target.to_bytes(4, "big")
    return element(
        SEEK, element(SEEK_ID, raw_id) + element(SEEK_POSITION, position.to_bytes(width, "big"))
    )


def rebuild_seek_head(
    data: bytes,
    seg: Segment,
    positions: dict[int, int],
    extra: list[bytes] | None = None,
    *,
    crc: bool | None = None,
) -> bytes:
    """The first ``SeekHead`` with new positions (``{element ID: SeekPosition}``), each in 4
    bytes, and ``extra`` entries first; a ``CRC-32`` when ``crc`` (``None``: as before)."""
    head = seg.first(SEEK_HEAD)
    payload = data[head.data : head.end]
    children = kids(payload)
    if crc is None:
        crc = bool(children) and children[0][0] == CRC
    entries = list(extra or [])
    for child_id, raw in children:
        if child_id != SEEK:
            continue
        _, _, header = _header(raw, 0)
        fields = dict(kids(raw[header:]))
        target = int.from_bytes(fields[SEEK_ID][-4:], "big")
        if target in positions:
            entries.append(seek(target, positions[target], 4))
        else:
            entries.append(raw)
    return with_crc(SEEK_HEAD, entries, crc)


def splice(data: bytes, start: int, end: int, new: bytes) -> bytes:
    assert len(new) == end - start, (len(new), end - start)
    return data[:start] + new + data[end:]


def unknown_size(data: bytes) -> bytes:
    seg = segment(data)
    return splice(data, seg.size_pos, seg.base, b"\x01" + b"\xff" * 7)


def info_after_seek_head(data: bytes) -> bytes:
    """``SeekHead``, then ``Info`` with no ``Void`` between: no room for a longer entry (the
    layout of a real file with an unknown muxer)."""
    seg = segment(data)
    head, gap, info = seg.top[0], seg.top[1], seg.top[2]
    assert (head.id, gap.id, info.id) == (SEEK_HEAD, VOID, INFO)
    length = len(rebuild_seek_head(data, seg, {INFO: 0}))
    new_head = rebuild_seek_head(data, seg, {INFO: head.pos + length - seg.base})
    region = new_head + data[info.pos : info.end]
    region += void(info.end - head.pos - len(region))
    return splice(data, head.pos, info.end, region)


def hostile_seek_head(data: bytes) -> bytes:
    """A ``Seek`` for ``Tracks`` that points past the end of the file, before the real one."""
    seg = segment(data)
    head, gap = seg.top[0], seg.top[1]
    new_head = rebuild_seek_head(data, seg, {}, [seek(TRACKS, (1 << 64) - 1, 8)])
    return splice(data, head.pos, gap.end, new_head + void(gap.end - head.pos - len(new_head)))


def crc_mismatch(data: bytes) -> bytes:
    """One byte of a track name changed, so the ``Tracks`` ``CRC-32`` no longer matches."""
    tracks = segment(data).first(TRACKS)
    at = data.index(b"Japanese", tracks.pos)
    return splice(data, at, at + 1, b"j")


def second_info(data: bytes) -> bytes:
    """A second, small ``Info`` in the ``Void`` after the ``SeekHead``."""
    seg = segment(data)
    gap = seg.top[1]
    assert gap.id == VOID
    small = element(INFO, element(0x2AD7B1, (1000000).to_bytes(3, "big")))
    return splice(data, gap.pos, gap.end, small + void(gap.end - gap.pos - len(small)))


def no_seek_head(data: bytes) -> bytes:
    seg = segment(data)
    head, gap = seg.top[0], seg.top[1]
    return splice(data, head.pos, gap.end, void(gap.end - head.pos))


def no_info(data: bytes) -> bytes:
    """The ``Info`` is a ``Void``, and its ``Seek`` names the chapters instead."""
    seg = segment(data)
    info = seg.first(INFO)
    head = seg.first(SEEK_HEAD)
    payload = bytearray(data[head.data : head.end])
    at = payload.index(INFO.to_bytes(4, "big"))
    payload[at : at + 4] = CHAPTERS.to_bytes(4, "big")
    children = kids(bytes(payload))
    if children[0][0] == CRC:
        rest = b"".join(raw for _, raw in children[1:])
        payload[2:6] = zlib.crc32(rest).to_bytes(4, "little")
    out = splice(data, head.data, head.end, bytes(payload))
    return splice(out, info.pos, info.end, void(info.end - info.pos))


def trailing_data(data: bytes) -> bytes:
    return data + b"not an element" * 4


def trailing_unknown_size(data: bytes) -> bytes:
    """A ``Tracks`` ID after the segment, with an unknown size: not a copy a stopped edit
    leaves."""
    return data + TRACKS.to_bytes(4, "big") + b"\x01" + b"\xff" * 7 + b"\0" * 20


def truncated(data: bytes) -> bytes:
    return data[:-100]


def add_crc(data: bytes) -> bytes:
    """``CRC-32`` elements in the ``SeekHead``, ``Info``, ``Tracks`` and every ``TrackEntry``
    of a file mkvmerge wrote (it writes none). The ``Void`` after the ``SeekHead`` pays for
    them; the elements after ``Tracks`` keep their places."""
    seg = segment(data)
    head, gap, info, tracks = seg.top[0:4]
    assert (head.id, gap.id, info.id, tracks.id) == (SEEK_HEAD, VOID, INFO, TRACKS)
    new_info = with_crc(INFO, [raw for _, raw in kids(data[info.data : info.end])], True)
    entries = [
        with_crc(TRACK_ENTRY, [r for _, r in kids(raw[_header(raw, 0)[2] :])], True)
        if child_id == TRACK_ENTRY
        else raw
        for child_id, raw in kids(data[tracks.data : tracks.end])
    ]
    new_tracks = with_crc(TRACKS, entries, True)
    tracks_at = tracks.end - len(new_tracks)
    info_at = tracks_at - len(new_info)
    positions = {INFO: info_at - seg.base, TRACKS: tracks_at - seg.base}
    new_head = rebuild_seek_head(data, seg, positions, crc=True)
    region = new_head + void(info_at - head.pos - len(new_head)) + new_info + new_tracks
    return splice(data, head.pos, tracks.end, region)


def run(*argv: str) -> None:
    subprocess.run(argv, check=True, capture_output=True, timeout=120)


def cover_jpeg(folder: Path) -> Path:
    ffmpeg = media.find_ffmpeg()
    assert ffmpeg is not None
    out = folder / "cover.jpg"
    run(
        ffmpeg,
        "-v",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=red:s=32x32",
        "-frames:v",
        "1",
        str(out),
    )
    return out


def mkvmerge_reordered(source: Path, folder: Path) -> Path:
    """The multi-track fixture through mkvmerge: audio and subtitles before the video, with a
    cover and a font attached."""
    font = folder / "font.ttf"
    font.write_bytes(media.fixture_font().data)
    out = folder / "mkvmerge-reordered.mkv"
    run(
        mkvtoolnix_tool("mkvmerge"), "-q", "-o", str(out),
        "--track-order", "0:2,0:4,0:0,0:1,0:3,0:5,0:6",
        "--attachment-mime-type", "image/jpeg", "--attachment-name", "cover.jpg",
        "--attach-file", str(cover_jpeg(folder)),
        "--attachment-mime-type", "font/ttf", "--attach-file", str(font),
        str(source),
    )  # fmt: skip
    return out


def mkvmerge_crc(source: Path, folder: Path) -> Path:
    plain = folder / "mkvmerge-plain.mkv"
    run(mkvtoolnix_tool("mkvmerge"), "-q", "-o", str(plain), str(source))
    out = folder / "mkvmerge-crc.mkv"
    out.write_bytes(add_crc(plain.read_bytes()))
    return out


def multitrack_edit(path: Path, *, long: bool = False, title: str | None = "Új cím") -> HeaderEdit:
    """The demo edit of the multi-track fixture; ``long`` names grow ``Tracks`` past its room."""
    name = "Magyar 5.1" + ("·" * LONG if long else "")
    return HeaderEdit(
        path=path,
        tracks=[
            TrackHeaderEdit(
                track_type="audio", number=1, language="hun", language_ietf="hu", name=name,
                flags={"default": True, "original": True},
            ),
            TrackHeaderEdit(
                track_type="audio", number=2, language="por", language_ietf="pt-BR",
                flags={"default": False},
            ),
            TrackHeaderEdit(
                track_type="audio", number=3, delete_name=True, flags={"commentary": True}
            ),
            TrackHeaderEdit(
                track_type="subtitle", number=2,
                flags={"hearing_impaired": True, "visual_impaired": True, "forced": True},
            ),
            TrackHeaderEdit(track_type="video", number=1, delete_name=True),
        ],
        info=None if title is None else InfoHeaderEdit(title=title),
    )  # fmt: skip


def shrink_edit(path: Path) -> HeaderEdit:
    """An edit that makes ``Tracks`` shorter: it always fits in place."""
    return HeaderEdit(
        path=path,
        tracks=[
            TrackHeaderEdit(track_type="audio", number=1, delete_name=True),
            TrackHeaderEdit(track_type="audio", number=2, delete_name=True),
        ],
    )


def generic_edit(path: Path, *, long: bool = False, title: str | None = None) -> HeaderEdit:
    """An edit of the first video and audio track that any fixture has."""
    name = "Name" + ("x" * LONG if long else "")
    return HeaderEdit(
        path=path,
        tracks=[
            TrackHeaderEdit(
                track_type="audio", number=1, language="ger", language_ietf="de-CH", name=name,
                flags={"default": False, "commentary": True},
            ),
            TrackHeaderEdit(track_type="video", number=1, flags={"original": True}),
        ],
        info=None if title is None else InfoHeaderEdit(title=title),
    )  # fmt: skip


def mkvmerge_json(path: Path) -> dict[str, Any]:
    out = subprocess.run(
        [mkvtoolnix_tool("mkvmerge"), "-J", str(path)],
        capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip
    data: dict[str, Any] = json.loads(out.stdout)
    return data


def mkvmerge_view(path: Path) -> dict[str, Any]:
    """What ``mkvmerge -J`` reads of the edited values: the title and each track's
    properties, without the UIDs."""
    data = mkvmerge_json(path)
    assert data["container"]["recognized"], data
    tracks = [
        {"type": t["type"], "codec": t["codec"]}
        | {k: v for k, v in t["properties"].items() if k not in ("uid", "number")}
        for t in data["tracks"]
    ]
    return {
        "title": data["container"]["properties"].get("title"),
        "tracks": tracks,
        "attachments": [a["file_name"] for a in data["attachments"]],
        "errors": data.get("errors", []),
    }


def ffprobe_view(path: Path) -> list[tuple[str, str | None, str | None, str | None]]:
    """``(codec type, codec, language, title)`` of every stream ffprobe reads."""
    streams = media.probe(path)["streams"]
    return [
        (s["codec_type"], s.get("codec_name"), s.get("tags", {}).get("language"),
         s.get("tags", {}).get("title"))
        for s in streams
    ]  # fmt: skip


def mkvpropedit(edit: HeaderEdit, path: Path) -> subprocess.CompletedProcess[str]:
    argv = mkvpropedit_args(edit.model_copy(update={"path": path}))
    return subprocess.run(
        [mkvtoolnix_tool("mkvpropedit"), *argv],
        capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip


def copy(source: Path, folder: Path, name: str) -> Path:
    out = folder / name
    shutil.copyfile(source, out)
    return out


Maker = Callable[[Path], Path]


def reader_values(path: Path) -> object:
    info = read_matroska(path)
    return info.title, info.tracks


FLAG_IDS = {
    "default": 0x88,
    "forced": 0x55AA,
    "commentary": 0x55AF,
    "hearing_impaired": 0x55AB,
    "visual_impaired": 0x55AC,
    "original": 0x55AE,
}
KIND_CODES = {"video": 1, "audio": 2, "subtitle": 0x11, "other": 0x12}


@dataclass(frozen=True)
class Track:
    kind: str
    name: str | None = None
    language: str | None = None
    ietf: str | None = None
    flags: tuple[tuple[str, bool], ...] = ()


def any_void(total: int) -> bytes:
    """A whole ``Void`` element of ``total`` bytes (at least 2)."""
    if total < 9:
        return bytes([VOID, 0x80 | (total - 2)]) + bytes(total - 2)
    return void(total)


def track_entry(number: int, track: Track, *, crc: bool = False) -> bytes:
    children = [element(0xD7, bytes([number])), element(0x83, bytes([KIND_CODES[track.kind]]))]
    children.append(element(0x86, b"A_AAC" if track.kind == "audio" else b"V_TEST"))
    if track.name is not None:
        children.append(element(0x536E, track.name.encode()))
    if track.language is not None:
        children.append(element(0x22B59C, track.language.encode()))
    if track.ietf is not None:
        children.append(element(0x22B59D, track.ietf.encode()))
    children += [element(FLAG_IDS[flag], bytes([value])) for flag, value in track.flags]
    return with_crc(TRACK_ENTRY, children, crc)


def synthetic(
    tracks: list[Track],
    *,
    title: str | None = "Title",
    room: int = 0,
    info_room: int = 0,
    seek_head_room: int = 64,
    crc: bool = False,
    size_width: int = 8,
    seek_head: bool = True,
    extra_seeks: int = 0,
    cluster: bool = True,
) -> bytes:
    """A small Matroska file: ``SeekHead`` (``Info`` and ``Tracks``), ``Info``, ``Tracks``
    and one ``Cluster``; ``*room`` are the ``Void`` sizes after each (0: none). ``extra_seeks``
    adds that many ``Seek`` entries for the ``Cluster``."""
    ebml = element(0x1A45DFA3, element(0x4286, b"\x01") + element(0x4282, b"matroska"))
    info_children = [element(0x2AD7B1, (1000000).to_bytes(3, "big"))]
    if title is not None:
        info_children.append(element(0x7BA9, title.encode()))
    info = with_crc(INFO, info_children, crc)
    entries = [track_entry(i + 1, t, crc=crc) for i, t in enumerate(tracks)]
    tracks_element = with_crc(TRACKS, entries, crc)
    clusters = element(CLUSTER, element(0xE7, b"\x00")) if cluster else b""

    def head(info_at: int, tracks_at: int) -> bytes:
        entries = [seek(INFO, info_at, 4), seek(TRACKS, tracks_at, 4)]
        entries += [seek(CLUSTER, 0, 4)] * extra_seeks
        return with_crc(SEEK_HEAD, entries, crc)

    def pad(total: int) -> bytes:
        return any_void(total) if total else b""

    head_len = len(head(0, 0)) if seek_head else 0
    info_at = head_len + seek_head_room
    tracks_at = info_at + len(info) + info_room
    body = (
        (head(info_at, tracks_at) if seek_head else b"")
        + pad(seek_head_room)
        + info
        + pad(info_room)
        + tracks_element
        + pad(room)
        + clusters
    )
    segment_header = SEGMENT.to_bytes(4, "big") + encode_size(len(body), size_width)
    return ebml + segment_header + body


def crc_problems(path: Path) -> list[str]:
    """The ``CRC-32`` elements that do not match, in the top-level elements other than
    clusters and in each ``TrackEntry``."""
    data = path.read_bytes()
    problems: list[str] = []

    def check(what: str, payload: bytes) -> None:
        children = kids(payload)
        if children and children[0][0] == CRC:
            stored = int.from_bytes(children[0][1][2:6], "little")
            if stored != zlib.crc32(payload[len(children[0][1]) :]):
                problems.append(what)

    for top in segment(data).top:
        if top.id in (CLUSTER, VOID):
            continue
        payload = data[top.data : top.end]
        check(f"0x{top.id:X} at {top.pos}", payload)
        if top.id == TRACKS:
            for child_id, raw in kids(payload):
                if child_id == TRACK_ENTRY:
                    check(f"TrackEntry in Tracks at {top.pos}", raw[_header(raw, 0)[2] :])
    return problems


EBML = 0x1A45DFA3
DOC_TYPE_VERSION = 0x4287
DOC_TYPE_READ_VERSION = 0x4285


def doc_type_versions(data: bytes) -> tuple[int | None, int | None]:
    """``(DocTypeVersion, DocTypeReadVersion)`` of the EBML header (``None``: absent)."""
    _, size, header = _header(data, 0)
    assert size is not None
    values = {
        child_id: int.from_bytes(raw[_header(raw, 0)[2] :], "big")
        for child_id, raw in kids(data[header : header + size])
    }
    return values.get(DOC_TYPE_VERSION), values.get(DOC_TYPE_READ_VERSION)


def with_doc_type_version(data: bytes, version: int | None, *, crc: bool = False) -> bytes:
    """The file with another ``DocTypeVersion`` (``None``: none), and with ``crc`` a ``CRC-32``
    in the EBML header."""
    _, size, header = _header(data, 0)
    assert size is not None
    children = [
        element(child_id, bytes([version])) if child_id == DOC_TYPE_VERSION and version else raw
        for child_id, raw in kids(data[header : header + size])
        if child_id != DOC_TYPE_VERSION or version is not None
    ]
    return with_crc(EBML, children, crc) + data[header + size :]


def ebml_crc_ok(data: bytes) -> bool:
    """The EBML header has no ``CRC-32``, or one that matches."""
    _, size, header = _header(data, 0)
    assert size is not None
    payload = data[header : header + size]
    children = kids(payload)
    if not children or children[0][0] != CRC:
        return True
    stored = int.from_bytes(children[0][1][2:6], "little")
    return stored == zlib.crc32(payload[len(children[0][1]) :])
