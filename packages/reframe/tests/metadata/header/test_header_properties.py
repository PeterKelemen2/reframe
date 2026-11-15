"""What the header writer encodes reads back the same through the probe's Matroska reader."""

from __future__ import annotations

import string
import tempfile
from pathlib import Path
from typing import get_args

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from reframe.metadata import ebml
from reframe.metadata.header import _fit, apply_header_edit
from reframe.models.plan import (
    HeaderEdit,
    HeaderFlag,
    HeaderTrackType,
    InfoHeaderEdit,
    TrackHeaderEdit,
)
from reframe.probe.matroska import MatroskaTrack, _Budget, _header, read_matroska

from .corpus import Track, crc_problems, synthetic

FLAGS: tuple[HeaderFlag, ...] = get_args(HeaderFlag)
DEFAULTS = {"default": True}

TRACKS = [
    Track("video", name="Video", language="und"),
    Track("audio", name="Japanese 5.1", language="jpn", flags=(("default", True),)),
    Track("audio", name="English", language="eng", ietf="en", flags=(("default", False),)),
    Track("subtitle", language="eng", flags=(("forced", True), ("commentary", False))),
    Track("subtitle", name="Signs", language="eng"),
]

texts = st.text(
    alphabet=st.characters(exclude_categories=["Cs"], exclude_characters="\0"),
    min_size=1,
    max_size=400,
)
languages = st.text(alphabet=string.ascii_lowercase, min_size=3, max_size=3)
ietf_tags = st.sampled_from(["en", "pt-BR", "zh-Hant", "yue", "und", "sr-Latn-RS", "de-CH"])
flag_sets = st.dictionaries(st.sampled_from(FLAGS), st.booleans())


@st.composite
def track_edits(draw: st.DrawFn) -> TrackHeaderEdit:
    kinds: list[tuple[HeaderTrackType, int]] = [("video", 1), ("audio", 2), ("subtitle", 2)]
    kind, count = draw(st.sampled_from(kinds))
    language = draw(st.none() | languages)
    name_action = draw(st.sampled_from(["keep", "set", "delete"]))
    return TrackHeaderEdit(
        track_type=kind,
        number=draw(st.integers(1, count)),
        language=language,
        language_ietf=None if language is None else draw(ietf_tags),
        name=draw(texts) if name_action == "set" else None,
        delete_name=name_action == "delete",
        flags=draw(flag_sets),
    )


def expected(edit: HeaderEdit) -> tuple[str | None, list[MatroskaTrack]]:
    """The reader's view after ``edit``, worked out from the synthetic tracks."""
    tracks: list[MatroskaTrack] = []
    for number, track in enumerate(TRACKS, 1):
        flags = DEFAULTS | dict(track.flags)
        tracks.append(
            MatroskaTrack(
                number=number,
                kind=track.kind,  # type: ignore[arg-type]
                codec_id="A_AAC" if track.kind == "audio" else "V_TEST",
                name=track.name,
                language=track.language or "eng",
                language_ietf=track.ietf,
                **{flag: flags.get(flag, False) for flag in FLAGS},
            )
        )
    for track_edit in edit.tracks:
        edited = [t for t in tracks if t.kind == track_edit.track_type][track_edit.number - 1]
        if track_edit.language is not None:
            edited.language = track_edit.language
            edited.language_ietf = track_edit.language_ietf
        if track_edit.delete_name:
            edited.name = None
        elif track_edit.name is not None:
            edited.name = track_edit.name
        for flag, value in track_edit.flags.items():
            setattr(edited, flag, value)
    title: str | None = "Title"
    if edit.info is not None:
        title = edit.info.title or None
    return title, tracks


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    edits=st.lists(track_edits(), max_size=4),
    title=st.none() | st.just("") | texts,
    set_title=st.booleans(),
    room=st.sampled_from([0, 2, 3, 9, 40, 600]),
    info_room=st.sampled_from([0, 2, 50]),
    crc=st.booleans(),
)
def test_edited_elements_read_back_through_the_probe_reader(
    edits: list[TrackHeaderEdit],
    title: str | None,
    set_title: bool,
    room: int,
    info_room: int,
    crc: bool,
) -> None:
    """Defect: a value the writer encodes (UTF-8 text, a flag, both languages, a CRC-32, a
    moved element) reads back different, or another track changes."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "t.mkv"
        path.write_bytes(synthetic(TRACKS, room=room, info_room=info_room, crc=crc))
        edit = HeaderEdit(
            path=path, tracks=edits, info=InfoHeaderEdit(title=title) if set_title else None
        )
        result = apply_header_edit(edit)
        assert result.status == "written", result
        info = read_matroska(path)
        assert (info.title, info.tracks) == expected(edit)
        assert crc_problems(path) == []


@given(
    element_id=st.sampled_from([0xEC, 0x83, 0x536E, 0x22B59C, 0x1654AE6B, 0x1A45DFA3]),
    payload=st.binary(max_size=300),
    width=st.none() | st.integers(1, 8),
)
def test_an_encoded_element_parses_back(element_id: int, payload: bytes, width: int | None) -> None:
    """Defect: an ID, a size field of a chosen width or a payload that the reader parses
    differently from what the writer meant."""
    raw = ebml.encode_element(element_id, payload, width)
    parsed_id, size, header = _header(raw, 0)
    assert (parsed_id, size, raw[header:]) == (element_id, len(payload), payload)
    if width is not None:
        assert header == len(ebml.encode_id(element_id)) + width


@given(total=st.integers(2, 70000))
def test_a_void_header_covers_exactly_its_gap(total: int) -> None:
    """Defect: a gap the writer fills with a ``Void`` is one byte too short or too long, so
    the next element is read from the wrong place."""
    header = ebml.void(total)
    parsed_id, size, length = _header(header + bytes(total), 0)
    assert parsed_id == ebml.VOID
    assert size is not None
    assert length == len(header)
    assert length + size == total


@given(size=st.integers(0, (1 << 56) - 2))
def test_a_size_takes_the_shortest_field_that_holds_it(size: int) -> None:
    """Defect: a size encoded as the all-ones value, which readers take as "unknown"."""
    raw = ebml.encode_size(size)
    _, parsed, _ = _header(b"\x80" + raw, 0)
    assert parsed == size
    assert len(raw) == 1 or size > ebml.max_size(len(raw) - 1)


@given(extra=st.integers(0, 40), payload=st.integers(0, 300))
def test_fit_fills_the_slot_exactly_and_widens_for_a_one_byte_gap(extra: int, payload: int) -> None:
    """Defect: an element written into its place leaves a 1-byte gap (no ``Void`` can fill
    it) or overruns the next element."""
    new = ebml.encode_element(0x1654AE6B, bytes(payload))
    slot = len(new) + extra
    fitted = _fit(new, slot, 8)
    assert fitted is not None
    assert len(fitted) <= slot
    # Only the gap's Void header is written: the old bytes after it are its payload.
    fitted += bytes(slot - len(fitted))
    element_id, size, header = _header(fitted, 0)
    assert element_id == 0x1654AE6B
    assert size == payload
    rest = fitted[header + size :]
    if rest:
        children = ebml.children(rest, _Budget(), "the gap")
        assert [c.id for c in children] == [ebml.VOID]
    if extra == 1:
        assert header == len(new) - payload + 1


def test_fit_refuses_a_slot_that_is_too_small() -> None:
    new = ebml.encode_element(0x1654AE6B, bytes(10))
    assert _fit(new, len(new) - 1, 8) is None
    assert _fit(new, len(new) + 1, len(new) - 4 - 10) is None
