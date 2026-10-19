"""Safe file names: the Windows rules, tested on every OS."""

from __future__ import annotations

import os

import pytest
from hypothesis import given
from hypothesis import strategies as st

from reframe.naming.sanitize import (
    MAX_PART_BYTES,
    RESERVED_NAMES,
    Piece,
    is_reserved,
    replace_forbidden,
    replace_undecodable,
    sanitize_segments,
)


def _one(text: str, extension: str = "mkv", fallback: str = "source") -> tuple[str, list[str]]:
    parts, notes = sanitize_segments([[Piece(text)]], extension=extension, fallback=fallback)
    assert len(parts) == 1
    return parts[0], notes


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Mission: Impossible", "Mission - Impossible"),
        ("12:30", "12-30"),
        ("AC/DC Live", "AC-DC Live"),
        ("a\\b", "a-b"),
        ("Who|What", "Who-What"),
        ('The "Best" Of', "The 'Best' Of"),
        ("What If...?", "What If..."),
        ("M*A*S*H", "MASH"),
        ("<Title>", "Title"),
        ("tab\there\x00\x1f", "tabhere"),
    ],
)
def test_forbidden_characters(text: str, expected: str) -> None:
    assert replace_forbidden(text)[0] == expected


def test_every_windows_forbidden_character_is_replaced() -> None:
    forbidden = '<>:"/\\|?*' + "".join(chr(c) for c in range(32))
    cleaned, changes = replace_forbidden(f"a{forbidden}b")
    assert not set(cleaned) & set(forbidden)
    assert changes


def test_replacement_note() -> None:
    _, notes = _one("Mission: Impossible?")
    assert notes == ["Replaced characters that Windows does not allow: ':' → '-', '?' removed."]


@pytest.mark.parametrize(
    "name",
    [
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "com9",
        "LPT9",
        "COM0",
        "LPT¹",
        "NUL.mkv",
        "CON .txt",
    ],
)
def test_reserved_names(name: str) -> None:
    assert is_reserved(name)


@pytest.mark.parametrize("name", ["CONSOLE", "COM10", "NULL", "AUXILIARY.mkv", "con-air"])
def test_not_reserved(name: str) -> None:
    assert not is_reserved(name)


def test_reserved_name_gets_an_underscore() -> None:
    part, notes = _one("CON")
    assert part == "CON_.mkv"
    assert "reserved name" in notes[0]
    parts, _ = sanitize_segments([[Piece("nul")], [Piece("x")]], extension="mkv", fallback="f")
    assert parts == ["nul_", "x.mkv"]
    parts, _ = sanitize_segments(
        [[Piece("aux.backup")], [Piece("x")]], extension="mkv", fallback="f"
    )
    assert parts == ["aux_.backup", "x.mkv"]
    assert set(RESERVED_NAMES) >= {"CON", "COM1", "LPT3"}


@pytest.mark.parametrize("extension", ["mkv", "m4v", ""])
def test_a_long_reserved_name_stays_in_the_byte_limit(extension: str) -> None:
    """The ``_`` of a reserved name comes after the cut to the byte limit: it must not take
    the part one byte over it (``CON.xxx…`` cut to 255 bytes, then ``CON_.xxx…``)."""
    long = "CON." + "x" * 300
    folder, file = sanitize_segments(
        [[Piece(long)], [Piece(long, "main_title")]], extension=extension, fallback="f"
    )[0]
    suffix = f".{extension}" if extension else ""
    assert folder == "CON_." + "x" * (MAX_PART_BYTES - 5)
    assert len(folder.encode()) == MAX_PART_BYTES
    assert len(file.encode()) == MAX_PART_BYTES - len(".part")
    assert file == "CON_." + "x" * (MAX_PART_BYTES - len(".part") - 5 - len(suffix)) + suffix
    # The fallback (the source file name) too.
    [part], _ = sanitize_segments([[Piece("")]], extension=extension, fallback=long)
    assert part == file
    # Never half a character: "CON.x" + 125 "é" is 255 bytes, "CON_.x" + 124 "é" is 254.
    parts, _ = sanitize_segments(
        [[Piece("CON.x" + "é" * 200)], [Piece("x")]], extension="", fallback="f"
    )
    assert parts == ["CON_.x" + "é" * 124, "x"]


_DEVICES = ["CON", "nul", "COM1", "LPT¹", "AUX", "aux "]
#: Text that exercises the rules of :func:`sanitize_segments`.
_MIXED = st.lists(
    st.one_of(
        st.sampled_from(
            [
                *_DEVICES,
                ".",
                " ",
                "..",
                ": ",
                "?",
                "/",
                "\\",
                "\x00",
                "\udcff",
                "\ud800",
                "é",
                "日本語",
                "😀",
                "x" * 120,
                "é" * 70,
                "日本語" * 30,
                "Show.S01E01",
            ]
        ),
        st.text(max_size=10),
    ),
    max_size=10,
).map("".join)
#: A reserved name with a tail long enough to be cut (``CON.xxx…``).
_LONG_RESERVED = st.builds(
    lambda device, tail: f"{device}.{tail}",
    st.sampled_from(_DEVICES),
    st.text(alphabet="xé日😀. -\udcff", min_size=200, max_size=300),
)
_TEXT = st.one_of(_MIXED, _LONG_RESERVED)
_PIECES = st.lists(
    st.builds(Piece, _TEXT, st.sampled_from([None, "sub_title", "main_title", "name"])),
    min_size=1,
    max_size=4,
)


@given(
    segments=st.lists(_PIECES, min_size=1, max_size=3),
    extension=st.sampled_from(["mkv", "m4v", "webm", ""]),
    fallback=_TEXT,
)
def test_every_part_is_safe_and_fits(
    segments: list[list[Piece]], extension: str, fallback: str
) -> None:
    parts, _ = sanitize_segments(segments, extension=extension, fallback=fallback)
    assert parts
    suffix = f".{extension}" if extension else ""
    *folders, file = parts
    assert file.endswith(suffix)
    stem = file[: len(file) - len(suffix)]
    for part in [*folders, stem]:
        assert part
        assert not is_reserved(part), part
        assert part == part.strip(" ")
        assert not part.endswith(".")
        assert not set(part) & set('<>:"/\\|?*')
        assert all(ord(char) >= 32 and not 0xD800 <= ord(char) <= 0xDFFF for char in part)
    for part in folders:
        assert len(os.fsencode(part)) <= MAX_PART_BYTES
    assert len(os.fsencode(file + ".part")) <= MAX_PART_BYTES


def test_bytes_that_are_not_utf8_become_the_replacement_character() -> None:
    name = os.fsdecode(b"bad\xffname") if os.name != "nt" else "bad\udcffname"
    part, notes = _one(name)
    assert part == "bad�name.mkv"
    assert notes == [
        "Replaced bytes that are not UTF-8 with '�' (such a name cannot be written on "
        "Windows or in JSON)."
    ]
    assert replace_undecodable("a\udcff\ud800b") == "a��b"
    # A run of them is one replacement character each, and each counts 3 bytes.
    part, _ = _one("\udcff" * 100)
    assert part == "�" * 82 + ".mkv"  # 246 bytes of 3-byte characters
    # The fallback (the source file name) too.
    part, notes = _one("", fallback=name)
    assert part == "bad�name.mkv"
    assert notes[0].startswith("Replaced bytes that are not UTF-8")


def test_trailing_dots_and_spaces() -> None:
    assert _one("Magnum.P.I.")[0] == "Magnum.P.I.mkv"
    assert _one("Name . . ")[0] == "Name.mkv"
    parts, notes = sanitize_segments(
        [[Piece("S.H.I.E.L.D.")], [Piece(" x ")]], extension="mkv", fallback="f"
    )
    assert parts == ["S.H.I.E.L.D", "x.mkv"]
    assert notes == ["Removed trailing dots from 'S.H.I.E.L.D.'."]


def test_dot_folders_are_dropped() -> None:
    """``..`` cannot climb out of the output folder: the trailing-dot rule empties it."""
    parts, notes = sanitize_segments(
        [[Piece("..")], [Piece(".")], [Piece("name")]], extension="mkv", fallback="f"
    )
    assert parts == ["name.mkv"]
    assert notes.count("Dropped an empty folder level.") == 2


def test_empty_file_name_falls_back_to_the_file_name() -> None:
    part, notes = _one("", fallback="hacksawridge.2160p")
    assert part == "hacksawridge.2160p.mkv"
    assert notes == ["The file name was empty: used the source file name 'hacksawridge.2160p'."]
    assert _one("...", fallback="CON")[0] == "CON_.mkv"
    assert _one(" ", fallback="")[0] == "output.mkv"


def test_255_byte_limit_shortens_sub_title_first() -> None:
    name = Piece("The.Show", "name")
    code = Piece(".S01E01.")
    sub = Piece("A" * 300, "sub_title")
    parts, notes = sanitize_segments([[name, code, sub]], extension="mkv", fallback="f")
    [part] = parts
    # The file name keeps room for ".part" (the queue's partial file name).
    assert len(part.encode()) == MAX_PART_BYTES - len(".part")
    assert part.startswith("The.Show.S01E01.AAA")
    assert part.endswith(".mkv")
    assert notes == [f"Shortened {{sub_title}} so that '{part[:-4]}' fits in 246 bytes."]


def test_255_byte_limit_then_main_title() -> None:
    """``{sub_title}`` goes first (all of it, here), then ``{main_title}``."""
    main = Piece("M" * 300, "main_title")
    sub = Piece("short", "sub_title")
    parts, notes = sanitize_segments([[main, Piece(" - "), sub]], extension="mkv", fallback="f")
    assert len(parts[0].encode()) <= 250
    assert parts[0] == "M" * (246 - 3) + " -.mkv"
    assert [note.split(" so ")[0] for note in notes] == [
        "Shortened {sub_title}",
        "Shortened {main_title}",
    ]


def test_shortening_stops_as_soon_as_it_fits() -> None:
    main = Piece("The.Show.S01E01." + "Title" * 10, "main_title")
    sub = Piece("Episode." * 40, "sub_title")
    parts, notes = sanitize_segments([[main, Piece(" "), sub]], extension="mkv", fallback="f")
    assert parts[0].startswith(main.text + " Episode.")
    assert len(parts[0].encode()) <= 250
    assert [n for n in notes if n.startswith("Shortened")] == [notes[-1]]
    assert "{sub_title}" in notes[-1]


def test_255_byte_limit_cuts_at_last() -> None:
    parts, notes = sanitize_segments([[Piece("x" * 300)]], extension="mkv", fallback="f")
    assert len(parts[0].encode()) == 250
    assert notes[0].startswith("Cut a path part to 246 bytes")


def test_folder_parts_have_the_full_255_bytes() -> None:
    parts, _ = sanitize_segments([[Piece("é" * 200)], [Piece("x")]], extension="mkv", fallback="f")
    assert len(parts[0].encode()) == 254  # 127 two-byte characters; never half a character
    assert parts[0] == "é" * 127


def test_multibyte_characters_are_never_split() -> None:
    part, _ = _one("日本語" * 40, extension="mkv")
    assert len(part.encode()) <= 250
    part.encode().decode("utf-8")


def test_no_extension() -> None:
    parts, _ = sanitize_segments([[Piece("name")]], extension="", fallback="f")
    assert parts == ["name"]
