"""Reframe's own Matroska header writer: track languages, names and flags, and the segment
title, written into an existing file in place.

A refused edit leaves the file byte for byte unchanged. Once the first byte is written, every
state a crash or kill can leave is a file with all the old values or all the new ones: new
copies of moved elements are written after the end of the segment first, where readers do not
look, and one write then switches every reader over. A write that fails part-way is undone with
the bytes it replaced, and the result says what the file holds, read back from the file.
"""

from __future__ import annotations

import copy
import os
import shutil
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import BinaryIO, Literal, cast, get_args

from reframe.metadata.ebml import (
    Child,
    children,
    encode_element,
    encode_id,
    encode_size,
    encode_uint,
    join_with_crc,
    max_size,
    split_crc,
    void,
)
from reframe.metadata.layout import Element, Layout, Refusal, SeekHead, read_layout
from reframe.metadata.versions import needed_version
from reframe.models.plan import HeaderEdit, HeaderFlag, TrackHeaderEdit
from reframe.probe import matroska
from reframe.probe.matroska import (
    _EBML,
    _INFO,
    _KINDS,
    _SEEK,
    _SEEK_HEAD,
    _SEEK_ID,
    _SEEK_POSITION,
    _STRINGS,
    _TITLE,
    _TRACK_ENTRY,
    _TRACKS,
    _UINTS,
    _VOID,
    MatroskaError,
    MatroskaFile,
    _Budget,
    _header,
    _read,
    _Reader,
    read_exactly,
    tracks_by_kind,
)

__all__ = [
    "HeaderBackup",
    "HeaderEditResult",
    "HeaderEditStatus",
    "HeaderFileState",
    "apply_header_edit",
]

HeaderEditStatus = Literal["written", "refused", "failed"]
HeaderFileState = Literal["unchanged", "old", "new", "damaged"]

#: Free space the writer wants on the disk beyond the bytes it writes: a copy-on-write file
#: system also needs room for an overwrite, and a write that runs out of room stops part-way.
SPARE_SPACE = 16 * 1024 * 1024

_DOC_TYPE_VERSION = 0x4287
_IDS = {name: element_id for element_id, name in (_UINTS | _STRINGS).items()}
_TRACK_TYPE = _IDS["type"]
_NAME = _IDS["name"]
_LANGUAGE = _IDS["language"]
_LANGUAGE_IETF = _IDS["language_ietf"]
#: Each flag's element and its value when the element is absent (only ``default`` is set).
_FLAGS: dict[HeaderFlag, tuple[int, bool]] = {
    flag: (_IDS[flag], flag == "default") for flag in get_args(HeaderFlag)
}
_FLAG_IDS = dict(_FLAGS.values())


@dataclass(frozen=True, slots=True)
class HeaderBackup:
    """Bytes of the file as they were before the edit, starting at ``offset``: writing them
    back there undoes a write that could not be undone."""

    offset: int
    data: bytes


@dataclass(frozen=True, slots=True)
class HeaderEditResult:
    """The outcome of :func:`apply_header_edit`.

    ``written``: every edit is in the file. ``refused``: nothing was written, the file is
    unchanged. ``failed``: an OS error; :attr:`file_state` says what the file holds.
    """

    status: HeaderEditStatus
    code: str | None = None
    """``header.<reason>`` for ``refused`` and ``failed``."""
    reason: str | None = None
    """What went wrong, for the user (not what the file holds: see :attr:`file_state`)."""
    file_state: HeaderFileState | None = field(default=None, kw_only=True)
    """``unchanged``: byte for byte. ``old``: all the old values (after the segment, where no
    reader looks, there may be bytes of the stopped edit). ``new``: all the new values.
    ``damaged``: the header may be damaged; :attr:`backup` holds its old bytes. ``None``: not
    said."""
    backup: HeaderBackup | None = field(default=None, kw_only=True)

    @property
    def ok(self) -> bool:
        return self.status == "written"


_Stage = Literal["before", "switch", "after"]


@dataclass(frozen=True, slots=True)
class _Write:
    pos: int
    data: bytes
    old: bytes | None = None
    """The bytes this write replaces (``None``: it writes past the end of the segment)."""
    stage: _Stage = "before"
    """Before the switch the file reads old, after it new."""


@dataclass(frozen=True, slots=True)
class _Truncate:
    size: int
    stage: _Stage = "before"


_Step = _Write | _Truncate


class _FileIO:
    """The writes of one edit; each call is one write that a crash can stop after."""

    def __init__(self, handle: BinaryIO) -> None:
        self._handle = handle

    def write(self, pos: int, data: bytes) -> None:
        self._handle.seek(pos)
        view = memoryview(data)
        while view:
            written = self._handle.write(view)
            if not written:
                raise OSError("short write")
            view = view[written:]

    def truncate(self, size: int) -> None:
        self._handle.truncate(size)

    def sync(self) -> None:
        os.fsync(self._handle.fileno())


def _text(value: str, *, ascii_only: bool = False) -> bytes:
    if "\0" in value:
        raise Refusal("header.invalid_value", "A text value contains a NUL character.")
    try:
        return value.encode("ascii" if ascii_only else "utf-8")
    except UnicodeEncodeError:
        raise Refusal(
            "header.invalid_value", f"The language code {value!r} is not plain ASCII."
        ) from None


def _wanted(edit: TrackHeaderEdit) -> dict[int, bytes | None]:
    """The element values that ``edit`` writes (``None``: removed)."""
    wanted: dict[int, bytes | None] = {}
    if edit.language is not None and edit.language_ietf is not None:
        wanted[_LANGUAGE] = _text(edit.language, ascii_only=True)
        wanted[_LANGUAGE_IETF] = _text(edit.language_ietf)
    if edit.delete_name:
        wanted[_NAME] = None
    elif edit.name is not None:
        wanted[_NAME] = _text(edit.name)
    for flag, value in edit.flags.items():
        wanted[_FLAGS[flag][0]] = b"\x01" if value else b"\x00"
    return wanted


def _has(payload: bytes, kids: Sequence[Child], element_id: int, value: bytes | None) -> bool:
    found = [kid.data(payload) for kid in kids if kid.id == element_id]
    if element_id in _FLAG_IDS:
        assert value is not None
        if len(found) > 1:
            return False
        have = bool(int.from_bytes(found[0], "big")) if found else _FLAG_IDS[element_id]
        return have == (value != b"\x00")
    if value is None:
        return not found
    return len(found) == 1 and found[0].split(b"\0", 1)[0] == value


def _rebuilt(raw: bytes, wanted: dict[int, bytes | None], budget: _Budget, what: str) -> bytes:
    """The master element ``raw`` with ``wanted`` applied, or ``raw`` when it has them all."""
    element_id, _, header = _header(raw, 0)
    payload = raw[header:]
    crc, kids = split_crc(payload, children(payload, budget, what))
    todo = {i: v for i, v in wanted.items() if not _has(payload, kids, i, v)}
    if not todo:
        return raw
    parts: list[bytes] = []
    done: set[int] = set()
    for kid in kids:
        if kid.id not in todo:
            parts.append(kid.raw(payload))
            continue
        value = todo[kid.id]
        if value is not None and kid.id not in done:
            parts.append(encode_element(kid.id, value))
        done.add(kid.id)
    parts += [encode_element(i, v) for i, v in todo.items() if v is not None and i not in done]
    return _element(element_id, join_with_crc(parts, crc), header - len(encode_id(element_id)))


def _element(element_id: int, payload: bytes, width: int) -> bytes:
    """The element, with a size field of ``width`` bytes if it fits."""
    return encode_element(element_id, payload, width if len(payload) <= max_size(width) else None)


def _entry_kind(raw: bytes, budget: _Budget) -> str | None:
    _, _, header = _header(raw, 0)
    payload = raw[header:]
    kind: str | None = None
    for kid in children(payload, budget, "a TrackEntry"):
        if kid.id == _TRACK_TYPE:
            kind = _KINDS.get(int.from_bytes(kid.data(payload), "big"))
    return kind


def _new_tracks(raw: bytes, edits: Sequence[TrackHeaderEdit], budget: _Budget) -> bytes:
    """The ``Tracks`` element ``raw`` with ``edits`` applied (``raw`` when nothing changes)."""
    _, _, header = _header(raw, 0)
    payload = raw[header:]
    crc, kids = split_crc(payload, children(payload, budget, "Tracks"))
    entries: list[bytes] = [kid.raw(payload) for kid in kids]
    by_kind: dict[str, list[int]] = {"video": [], "audio": [], "subtitle": []}
    for index, kid in enumerate(kids):
        if kid.id == _TRACK_ENTRY:
            kind = _entry_kind(entries[index], budget)
            if kind is not None:
                by_kind[kind].append(index)
    for edit in edits:
        indexes = by_kind[edit.track_type]
        if edit.number > len(indexes):
            raise Refusal(
                "header.no_such_track",
                f"The file has no {edit.track_type} track number {edit.number}.",
            )
        index = indexes[edit.number - 1]
        entries[index] = _rebuilt(entries[index], _wanted(edit), budget, "a TrackEntry")
    if all(new == kid.raw(payload) for new, kid in zip(entries, kids, strict=True)):
        return raw
    return _element(_TRACKS, join_with_crc(entries, crc), header - 4)


def _new_info(raw: bytes, title: str | None, budget: _Budget) -> bytes:
    value = _text(title) if title else None
    return _rebuilt(raw, {_TITLE: value}, budget, "the segment information")


@dataclass(slots=True)
class _Change:
    element: Element
    new: bytes
    slot_end: int
    """The end of the element and the ``Void`` elements right after it."""
    fitted: bytes | None = None
    """The bytes written in place, or ``None`` when the element moves."""


def _fit(new: bytes, slot: int, max_width: int) -> bytes | None:
    """``new`` and a ``Void`` filling a slot of ``slot`` bytes, or ``None`` when it does not
    fit. A 1-byte gap cannot be a ``Void``: the size field is widened by one byte instead."""
    element_id, _, header = _header(new, 0)
    id_bytes = encode_id(element_id)
    payload = new[header:]
    for width in range(header - len(id_bytes), max_width + 1):
        candidate = id_bytes + encode_size(len(payload), width) + payload
        gap = slot - len(candidate)
        if gap < 0:
            return None
        if gap == 0:
            return candidate
        if gap >= 2:
            return candidate + void(gap)
    return None


def _seek(target: int, position: int, width: int | None) -> bytes:
    if width is not None and position >= 1 << (8 * width):
        width = None
    return encode_element(
        _SEEK,
        encode_element(_SEEK_ID, encode_id(target))
        + encode_element(_SEEK_POSITION, encode_uint(position, width)),
    )


def _new_seek_head(
    head: SeekHead, base: int, relocated: dict[int, int], added: dict[int, int]
) -> bytes | None:
    """``head`` with its entries for the elements in ``relocated`` (``{old position: new
    position}``, in the file) pointing to the new places, and an entry for each of ``added``
    (``{element ID: new position}``). ``None`` when nothing changes."""
    budget = _Budget()
    parts: list[bytes] = []
    changed = bool(added)
    for seek, (target, position) in zip(head.seeks, head.targets, strict=True):
        new = None if position is None else relocated.get(base + position)
        if target is None or new is None:
            parts.append(seek.raw(head.payload))
            continue
        data = seek.data(head.payload)
        width = next(
            (k.size for k in children(data, budget, "a Seek") if k.id == _SEEK_POSITION), None
        )
        parts.append(_seek(target, new - base, width))
        changed = True
    if not changed:
        return None
    parts += [_seek(target, pos - base, None) for target, pos in added.items()]
    element = head.element
    return _element(element.id, join_with_crc(parts, head.crc), element.header - 4)


_LEFTOVER_IDS = tuple(encode_id(i) for i in (_TRACKS, _INFO, _SEEK_HEAD, _VOID))


def _leftovers(reader: _Reader, start: int) -> bool:
    """Whether the bytes after the segment are what a stopped edit leaves there: copies of
    header elements, the last one perhaps cut short."""
    pos = start
    for _ in range(matroska.MAX_TOP_LEVEL):
        if pos >= reader.size:
            return True
        head = reader.read(pos, 12)
        if not any(head.startswith(i) or i.startswith(head) for i in _LEFTOVER_IDS):
            return False
        try:
            _, size, header = _header(head, 0)
        except MatroskaError:
            return len(head) < 12
        if size is None or size > matroska.MAX_ELEMENT:
            return False
        pos += header + size
    return False


def _plan(reader: _Reader, layout: Layout, edit: HeaderEdit) -> list[_Step]:
    budget = reader.budget
    changes: list[_Change] = []
    tracks_raw = reader.read(layout.tracks.pos, layout.tracks.header + layout.tracks.size)
    new_tracks = _new_tracks(tracks_raw, edit.tracks, budget)
    if new_tracks != tracks_raw:
        end = layout.slot_end(layout.tracks, reader)
        changes.append(_Change(layout.tracks, new_tracks, end))
    if edit.info is not None:
        if layout.info is None:
            if edit.info.title:
                raise Refusal("header.no_info", "The file has no segment information.")
        else:
            info_raw = reader.read(layout.info.pos, layout.info.header + layout.info.size)
            new_info = _new_info(info_raw, edit.info.title, budget)
            if new_info != info_raw:
                end = layout.slot_end(layout.info, reader)
                changes.append(_Change(layout.info, new_info, end))
    if not changes:
        return []

    for change in changes:
        fitted = _fit(change.new, change.slot_end - change.element.pos, layout.max_size_width)
        if fitted is not None and (layout.in_front(change.element) or len(changes) == 1):
            change.fitted = fitted
    moved = [c for c in changes if c.fitted is None]
    patches: list[_Write] = [_Write(c.element.pos, c.fitted) for c in changes if c.fitted]
    steps: list[_Step] = []
    cleanup: list[_Step] = []
    if moved:
        steps += _move(reader, layout, moved, patches, cleanup)
    elif layout.segment_size is not None:
        end = layout.base + layout.segment_size
        if end < layout.size and _leftovers(reader, end):
            steps.append(_Truncate(end))
    if new_tracks != tracks_raw:
        version = _version_patch(reader, needed_version(new_tracks))
        if version is not None:
            steps.append(version)
    steps.append(_commit(reader, patches))
    return steps + cleanup


def _version_patch(reader: _Reader, need: int) -> _Write | None:
    """The EBML header's ``DocTypeVersion`` raised to ``need``, as mkvpropedit does when it
    writes ``Tracks``; ``None`` when it is high enough, absent (the header would have to grow)
    or not one element."""
    element_id, size, header = reader.header(0)
    if element_id != _EBML or size is None:
        return None
    payload = reader.read(header, size)
    crc, kids = split_crc(payload, children(payload, reader.budget, "the EBML header"))
    versions = [kid for kid in kids if kid.id == _DOC_TYPE_VERSION]
    if len(versions) != 1:
        return None
    kid = versions[0]
    if not 1 <= kid.size <= 8 or int.from_bytes(kid.data(payload), "big") >= need:
        return None
    value = encode_uint(need, kid.size)
    if not crc:
        pos = kid.offset + kid.header
        return _Write(header + pos, value, old=payload[pos : pos + kid.size])
    parts = [k.raw(payload) if k is not kid else k.raw(payload)[: k.header] + value for k in kids]
    return _Write(header, join_with_crc(parts, crc=True), old=payload)


def _move(
    reader: _Reader,
    layout: Layout,
    moved: list[_Change],
    patches: list[_Write],
    cleanup: list[_Step],
) -> list[_Step]:
    """The steps before the commit, and the commit's patches, for elements that move to the
    end of the segment. A ``SeekHead`` after the clusters that lists one of them moves too."""
    if layout.segment_size is None:
        raise Refusal(
            "header.unknown_size",
            "The file's segment has an unknown size, so a grown header cannot be moved.",
        )
    end = layout.base + layout.segment_size
    if end > layout.size:
        raise Refusal("header.truncated", "The file is shorter than its segment says.")
    first = layout.seek_head
    if first is None:
        raise Refusal(
            "header.no_room", "The file has no SeekHead, so a grown header cannot be moved."
        )
    steps: list[_Step] = []
    if end < layout.size:
        if not _leftovers(reader, end):
            raise Refusal("header.trailing_data", "The file has unknown data after its segment.")
        steps.append(_Truncate(end))

    relocated: dict[int, int] = {}
    copies: list[bytes] = []
    old_back: list[tuple[Element, int]] = []
    pos = end
    for change in moved:
        relocated[change.element.pos] = pos
        copies.append(change.new)
        pos += len(change.new)
        if not layout.in_front(change.element):
            old_back.append((change.element, change.slot_end))
    heads = [first, *layout.other_seek_heads]
    listed = {
        layout.base + position
        for head in heads
        for _, position in head.targets
        if position is not None
    }
    added = {c.element.id: relocated[c.element.pos] for c in moved if c.element.pos not in listed}
    for head in layout.other_seek_heads:
        new = _new_seek_head(head, layout.base, relocated, {})
        if new is None:
            continue
        if layout.in_front(head.element):
            patches.append(_fit_patch(layout, reader, head.element, new))
            continue
        relocated[head.element.pos] = pos
        copies.append(new)
        pos += len(new)
        old_back.append((head.element, layout.slot_end(head.element, reader)))
    steps.append(_Write(end, b"".join(copies)))

    size = layout.segment_size + (pos - end)
    if size > max_size(layout.size_width):
        raise Refusal("header.no_room", "The file's segment size field is too short.")
    patches.append(_Write(layout.size_pos, encode_size(size, layout.size_width)))
    new_first = _new_seek_head(first, layout.base, relocated, added)
    if new_first is not None:
        patches.append(_fit_patch(layout, reader, first.element, new_first))
    for change in moved:
        if layout.in_front(change.element):
            patches.append(_Write(change.element.pos, void(change.slot_end - change.element.pos)))
    for old, slot_end in old_back:
        mark = void(slot_end - old.pos)
        cleanup.append(_Write(old.pos, mark, reader.read(old.pos, len(mark)), "after"))
    return steps


def _fit_patch(layout: Layout, reader: _Reader, element: Element, new: bytes) -> _Write:
    slot_end = layout.slot_end(element, reader)
    fitted = _fit(new, slot_end - element.pos, layout.max_size_width)
    if fitted is None:
        raise Refusal("header.no_room", "The file's SeekHead has no room for the new entry.")
    return _Write(element.pos, fitted)


def _commit(reader: _Reader, patches: list[_Write]) -> _Write:
    """One write covering every patch: the switch from the old values to the new ones."""
    start = min(p.pos for p in patches)
    stop = max(p.pos + len(p.data) for p in patches)
    old = reader.read(start, stop - start)
    span = bytearray(old)
    for patch in patches:
        span[patch.pos - start : patch.pos - start + len(patch.data)] = patch.data
    return _Write(start, bytes(span), old, "switch")


class _Overlay:
    """The file as it would be after some of the steps (only read through)."""

    def __init__(self, handle: BinaryIO, size: int, steps: Sequence[_Step]) -> None:
        self._handle = handle
        self._base = size
        self._writes: list[_Write] = []
        self.size = size
        for step in steps:
            if isinstance(step, _Truncate):
                self._base = min(self._base, step.size)
                self.size = step.size
                self._writes = [w for w in self._writes if w.pos < step.size]
            else:
                self._writes.append(step)
                self.size = max(self.size, step.pos + len(step.data))
        self._pos = 0

    def seek(self, pos: int) -> int:
        self._pos = pos
        return pos

    def read(self, count: int) -> bytes:
        start = self._pos
        stop = min(start + count, self.size)
        out = bytearray(max(0, stop - start))
        if start < self._base:
            self._handle.seek(start)
            data = self._handle.read(min(stop, self._base) - start)
            out[: len(data)] = data
        for write in self._writes:
            lo = max(start, write.pos)
            hi = min(stop, write.pos + len(write.data))
            if lo < hi:
                out[lo - start : hi - start] = write.data[lo - write.pos : hi - write.pos]
        self._pos = stop
        return bytes(out)


def _read_state(handle: BinaryIO, size: int, steps: Sequence[_Step]) -> MatroskaFile | None:
    overlay = _Overlay(handle, size, steps)
    try:
        return _read(_Reader(cast(BinaryIO, overlay), overlay.size))
    except (MatroskaError, ValueError, OverflowError):
        return None


def _expected(old: MatroskaFile, edit: HeaderEdit) -> MatroskaFile:
    new = copy.deepcopy(old)
    by_kind = tracks_by_kind(new)
    for track_edit in edit.tracks:
        track = by_kind[track_edit.track_type][track_edit.number - 1]
        if track_edit.language is not None:
            track.language = track_edit.language
            track.language_ietf = track_edit.language_ietf
        if track_edit.delete_name:
            track.name = None
        elif track_edit.name is not None:
            track.name = track_edit.name
        for flag, value in track_edit.flags.items():
            setattr(track, flag, value)
    if edit.info is not None:
        new.title = edit.info.title or None
    return new


def _check(
    handle: BinaryIO, size: int, old: MatroskaFile, new: MatroskaFile, steps: list[_Step]
) -> None:
    """Every state the steps pass through reads as ``old`` or ``new``, and the last as
    ``new``, through Reframe's own reader: a guard against a layout the planner got wrong."""
    for count in range(1, len(steps) + 1):
        state = _read_state(handle, size, steps[:count])
        if state != new and (count == len(steps) or state != old):
            raise Refusal(
                "header.unsafe_layout",
                "The file's header is laid out in a way Reframe cannot edit safely.",
            )


def _prepare(handle: BinaryIO, edit: HeaderEdit) -> list[_Step]:
    size = os.fstat(handle.fileno()).st_size
    try:
        old = _read(_Reader(handle, size))
        reader = _Reader(handle, size)
        layout = read_layout(reader)
        steps = _plan(reader, layout, edit)
    except (MatroskaError, ValueError, OverflowError) as exc:
        raise Refusal(
            "header.unreadable", f"The file's Matroska header cannot be edited safely ({exc})."
        ) from exc
    if steps:
        _check(handle, size, old, _expected(old, edit), steps)
    return steps


def _identity(handle: BinaryIO) -> tuple[int, int, int, int]:
    st = os.fstat(handle.fileno())
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns


def apply_header_edit(edit: HeaderEdit) -> HeaderEditResult:
    """Write ``edit`` into ``edit.path``. Blocking: run it in a worker thread.

    Never raises for a file it cannot edit (a refusal) or an OS error (a failure).
    """
    try:
        with open(edit.path, "rb") as handle:
            identity = _identity(handle)
            steps = _prepare(handle, edit)
    except Refusal as exc:
        return HeaderEditResult("refused", exc.code, exc.reason, file_state="unchanged")
    except OSError as exc:
        return _failed(f"The file could not be read ({exc}).", "unchanged")
    if not steps:
        return HeaderEditResult("written", file_state="new")
    short = _short_of_space(edit.path, steps)
    if short is not None:
        return HeaderEditResult("failed", "header.no_space", short, file_state="unchanged")
    try:
        with open(edit.path, "r+b", buffering=0) as handle:
            if _identity(handle) != identity:
                return HeaderEditResult(
                    "failed",
                    "header.changed",
                    "The file changed while its header was read.",
                    file_state="unchanged",
                )
            io = _FileIO(handle)
            for index, step in enumerate(steps):
                try:
                    if isinstance(step, _Truncate):
                        io.truncate(step.size)
                    else:
                        io.write(step.pos, step.data)
                    io.sync()
                except OSError as exc:
                    return _after_failure(handle, io, step, index == 0, identity[2], exc)
    except OSError as exc:
        return _failed(f"The file could not be written ({exc}).", "unchanged")
    return HeaderEditResult("written", file_state="new")


def _failed(reason: str, state: HeaderFileState) -> HeaderEditResult:
    return HeaderEditResult("failed", "header.io_error", reason, file_state=state)


def _short_of_space(path: os.PathLike[str] | str, steps: Sequence[_Step]) -> str | None:
    """Why the disk has too little free space for ``steps``, or ``None``. A file system that
    reports no size (some shares do) is not checked."""
    need = sum(len(s.data) for s in steps if isinstance(s, _Write)) + SPARE_SPACE
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    if usage.total <= 0 or usage.free >= need:
        return None
    return (
        f"The disk has {usage.free / 1e6:.1f} MB free; writing the header safely needs "
        f"{need / 1e6:.1f} MB."
    )


def _after_failure(
    handle: BinaryIO, io: _FileIO, step: _Step, first: bool, size: int, exc: OSError
) -> HeaderEditResult:
    """The result of a step that failed: a write over old bytes is undone first, and what
    the file holds is read back, not assumed."""
    if isinstance(step, _Write) and step.old is not None:
        problem = _put_back(handle, io, step.pos, step.old)
        if problem is not None:
            return HeaderEditResult(
                "failed",
                "header.io_error",
                f"Writing the header failed ({exc}), and writing its old bytes back failed "
                f"too ({problem}).",
                file_state="damaged",
                backup=HeaderBackup(step.pos, step.old),
            )
    if step.stage == "after":
        state: HeaderFileState = "new"
    elif first and _size(handle) == size:
        state = "unchanged"
    else:
        state = "old"
    return _failed(f"Writing the header failed ({exc}).", state)


def _put_back(handle: BinaryIO, io: _FileIO, pos: int, old: bytes) -> str | None:
    """Make the file hold ``old`` at ``pos`` again; why that failed, or ``None``."""
    try:
        if read_exactly(handle, pos, len(old)) == old:
            return None
        io.write(pos, old)
        io.sync()
        if read_exactly(handle, pos, len(old)) == old:
            return None
        return "the bytes read back differ"
    except OSError as exc:
        return str(exc)


def _size(handle: BinaryIO) -> int | None:
    try:
        return os.fstat(handle.fileno()).st_size
    except OSError:
        return None
