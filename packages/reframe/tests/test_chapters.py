"""Chapter files: HandBrake CSV, OGM text and Matroska XML, read and written."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path, PurePath

import pytest

from reframe import chapters
from reframe.chapters import (
    ChapterFileError,
    chapter_export,
    detect_format,
    parse_chapters,
    read_chapter_file,
    write_chapters,
)
from reframe.models import ChapterFormat, ChapterImport, OutputChapter

NAMES = ['Árvíztűrő, "tükör"', "Line\nbreak", "Part = 1; #2", "<Two> & more", "  spaced  "]


def output(names: list[str]) -> list[OutputChapter]:
    return [
        OutputChapter(
            number=n + 1, start=n * 61.25, end=(n + 1) * 61.25, name=name, source_name=None,
            source_index=n,
        )
        for n, name in enumerate(names)
    ]  # fmt: skip


def parsed(text: str, chapter_format: ChapterFormat | None = None) -> ChapterImport:
    result = parse_chapters(text, chapter_format)
    assert isinstance(result, ChapterImport), result
    return result


def failure(text: str, chapter_format: ChapterFormat | None = None) -> ChapterFileError:
    result = parse_chapters(text, chapter_format)
    assert isinstance(result, ChapterFileError), result
    return result


def test_csv_quotes_a_name_as_handbrake_does_and_reads_it_back() -> None:
    text = write_chapters(output(NAMES[:3]), "csv")
    assert text == '1,"Árvíztűrő, ""tükör"""\n2,"Line\nbreak"\n3,Part = 1; #2\n'
    assert [c.name for c in parsed(text).chapters] == NAMES[:3]


def test_csv_import_trims_names_and_takes_handbrakes_windows_lines() -> None:
    found = parsed('1, Opening \r\n2,"Part, one"\r\n\r\n')
    assert [(c.start, c.name) for c in found.chapters] == [(None, "Opening"), (None, "Part, one")]
    assert found.issues == []


def test_csv_numbers_out_of_order_are_read_in_line_order_with_a_warning() -> None:
    found = parsed("2,Two\n1,One\n")
    assert [c.name for c in found.chapters] == ["Two", "One"]
    assert [i.code for i in found.issues] == ["chapters.numbers"]


@pytest.mark.parametrize(
    ("text", "line", "message"),
    [
        ("1,One\n2\n", 2, "a line needs a number and a name"),
        ("1,One\nx,Two\n", 2, "'x' is not a chapter number"),
    ],
)
def test_a_bad_csv_line_is_named(text: str, line: int, message: str) -> None:
    error = failure(text, "csv")
    assert (error.kind, error.line, error.message) == ("invalid", line, message)
    assert error.detail == f"Line {line}: {message}"


def test_ogm_round_trip_keeps_the_times_to_the_millisecond_and_one_line_per_name() -> None:
    text = write_chapters(output(NAMES), "ogm")
    assert text.splitlines()[:4] == [
        "CHAPTER01=00:00:00.000",
        'CHAPTER01NAME=Árvíztűrő, "tükör"',
        "CHAPTER02=00:01:01.250",
        "CHAPTER02NAME=Line break",
    ]
    found = parsed(text)
    assert [c.start for c in found.chapters] == [0.0, 61.25, 122.5, 183.75, 245.0]
    assert [c.name for c in found.chapters] == [
        NAMES[0],
        "Line break",
        NAMES[2],
        NAMES[3],
        "  spaced",
    ]


def test_ogm_reads_a_comma_decimal_and_a_name_without_a_time() -> None:
    found = parsed("CHAPTER01=01:02:03,5\nCHAPTER01NAME=One\nCHAPTER02NAME=Two\n")
    assert [(c.start, c.name) for c in found.chapters] == [(3723.5, "One"), (None, "Two")]
    assert [i.code for i in found.issues] == ["chapters.no_time"]


def test_a_line_that_is_not_ogm_is_named() -> None:
    error = failure("CHAPTER01=00:00:00.000\n\nCHAPTER01NAME=One\nnonsense\n")
    assert (error.kind, error.line) == ("invalid", 4)


def test_xml_round_trip_escapes_the_markup_and_drops_what_xml_cannot_hold() -> None:
    text = write_chapters(output([*NAMES[:4], "bell\x07"]), "xml")
    assert "&lt;Two&gt; &amp; more" in text
    found = parsed(text)
    assert [c.name for c in found.chapters] == [*NAMES[:4], "bell "]
    assert [c.start for c in found.chapters] == [0.0, 61.25, 122.5, 183.75, 245.0]


def test_xml_writes_no_display_for_a_chapter_without_a_name() -> None:
    text = write_chapters(output(["", "Two"]), "xml")
    assert text.count("<ChapterDisplay>") == 1
    assert [c.name for c in parsed(text).chapters] == ["", "Two"]


XML_HEAD = "<?xml version='1.0'?>\n"


def atom(start: str, name: str, inner: str = "") -> str:
    return (
        f"<ChapterAtom><ChapterTimeStart>{start}</ChapterTimeStart><ChapterDisplay>"
        f"<ChapterString>{name}</ChapterString></ChapterDisplay>{inner}</ChapterAtom>"
    )


def test_xml_reads_the_first_edition_and_leaves_out_nested_chapters_with_warnings() -> None:
    first = atom("00:00:00.000000000", "One", atom("00:00:00.500000000", "Inner")) + atom(
        "00:01:00.5", "Two"
    )
    text = (
        f"{XML_HEAD}<Chapters><EditionEntry>{first}</EditionEntry>"
        f"<EditionEntry>{atom('00:00:00.000', 'Other')}</EditionEntry></Chapters>"
    )
    found = parsed(text)
    assert [(c.start, c.name) for c in found.chapters] == [(0.0, "One"), (60.5, "Two")]
    assert [i.code for i in found.issues] == ["chapters.editions", "chapters.nested"]


@pytest.mark.parametrize(
    ("text", "line"),
    [
        (f"{XML_HEAD}<Chapters>\n<EditionEntry>\n<ChapterAtom>\n</Chapters>", 5),
        (f"{XML_HEAD}<Chapters><EditionEntry>\n<ChapterAtom></ChapterAtom>"
         "</EditionEntry></Chapters>", 3),
        (f"{XML_HEAD}<Chapters><EditionEntry>\n" + atom("soon", "One") +
         "</EditionEntry></Chapters>", 3),
        (f"{XML_HEAD}<Tags/>", 1),
    ],
)  # fmt: skip
def test_xml_that_is_not_a_chapter_file_is_named_by_its_line(text: str, line: int) -> None:
    error = failure(text)
    assert (error.kind, error.line) == ("invalid", line)


def test_xml_entities_are_refused() -> None:
    """An entity can expand to gigabytes (billion laughs)."""
    text = (
        '<?xml version="1.0"?>\n<!DOCTYPE Chapters [\n<!ENTITY a "aaaaaaaaaa">\n'
        '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">\n]>\n'
        "<Chapters><EditionEntry>" + atom("00:00:00.000", "&b;") + "</EditionEntry></Chapters>"
    )
    error = failure(text)
    assert error.message == "the file declares XML entities, which are not read"


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("\n\n  <?xml version='1.0'?><Chapters/>", "xml"),
        ("chapter01=00:00:00.000\n", "ogm"),
        ("1,Opening\n", "csv"),
        ("Opening\n", None),
        ("", None),
    ],
)
def test_the_format_comes_from_the_first_line(text: str, found: str | None) -> None:
    assert detect_format(text) == found


def test_a_file_of_no_chapter_format_is_refused() -> None:
    assert failure("Opening\nPart one\n").message.startswith("this is not a chapter file")


def test_a_file_without_chapters_is_refused() -> None:
    assert failure(f"{XML_HEAD}<Chapters><EditionEntry/></Chapters>").message == (
        "the file has no chapters"
    )


@pytest.mark.parametrize(
    ("data", "names", "codes"),
    [
        ("﻿1,Ősz\n".encode(), ["Ősz"], []),
        ("﻿1,Ősz\n".encode("utf-16-le"), ["Ősz"], []),
        ("﻿1,Ősz\n".encode("utf-16-be"), ["Ősz"], []),
        ("1,Café\n".encode("latin-1"), ["Café"], ["chapters.not_utf8"]),
    ],
)
def test_the_file_is_read_as_utf8_utf16_or_latin1(
    tmp_path: Path, data: bytes, names: list[str], codes: list[str]
) -> None:
    file = tmp_path / "chapters.csv"
    file.write_bytes(data)
    result = read_chapter_file(file)
    assert isinstance(result, ChapterImport)
    assert [c.name for c in result.chapters] == names
    assert [i.code for i in result.issues] == codes


def test_a_file_over_the_limit_is_not_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chapters, "MAX_CHAPTER_FILE", 10)
    file = tmp_path / "chapters.csv"
    file.write_bytes(b"1,Opening\n")
    assert isinstance(read_chapter_file(file), ChapterImport)
    file.write_bytes(b"1,Opening!\n")
    result = read_chapter_file(file)
    assert isinstance(result, ChapterFileError)
    assert result.kind == "unreadable"


def test_a_folder_is_not_a_chapter_file(tmp_path: Path) -> None:
    result = read_chapter_file(tmp_path)
    assert isinstance(result, ChapterFileError)
    assert result.message == "The path is a folder, not a file."


@pytest.mark.parametrize(
    ("named_after", "chapter_format", "file_name"),
    [
        ("/out/Film (2001).mkv", "xml", "Film (2001).chapters.xml"),
        ("/out/Film", "ogm", "Film.chapters.txt"),
        ("/out/Show.S01E01.mp4", "csv", "Show.S01E01.chapters.csv"),
    ],
)
def test_the_export_is_named_after_the_output(
    named_after: str, chapter_format: ChapterFormat, file_name: str
) -> None:
    export = chapter_export(output(["One"]), chapter_format, PurePath(named_after))
    assert export.file_name == file_name


def test_a_time_that_rounds_up_carries_into_the_next_unit() -> None:
    near = OutputChapter(
        number=1, start=3599.9996, end=3600.5, name="x", source_name=None, source_index=None
    )
    assert write_chapters([near], "ogm").startswith("CHAPTER01=01:00:00.000\n")


@pytest.mark.parametrize(
    ("text", "line"),
    [
        ("CHAPTER01=" + "9" * 320 + ":00:00.000\nCHAPTER01NAME=x\n", 1),
        ("CHAPTER" + "1" * 5000 + "=00:00:00.000\n", 1),
        ("CHAPTER01=00:00:00.000\nCHAPTER" + "1" * 5000 + "NAME=x\n", 2),
        (
            f"{XML_HEAD}<Chapters><EditionEntry>\n"
            + atom("9" * 320 + ":00:00", "x")
            + "</EditionEntry></Chapters>",
            3,
        ),
        ("1" * 5000 + ",x\n", 1),
    ],
    ids=["ogm-hours", "ogm-number", "ogm-name-number", "xml-hours", "csv-number"],
)
def test_an_absurdly_long_number_is_a_bad_line_not_a_crash(text: str, line: int) -> None:
    error = failure(text)
    assert (error.kind, error.line) == ("invalid", line)
    assert len(error.detail) < 120


def test_a_fifo_is_refused_at_once_not_waited_on(fifo_read: Callable[..., object]) -> None:
    result = fifo_read("chapters.txt", read_chapter_file)
    assert isinstance(result, ChapterFileError)
    assert (result.kind, result.message) == ("unreadable", "The path is not a regular file.")


@pytest.mark.parametrize("separator", ["\N{LINE SEPARATOR}", "\x85", "\x0b", "\x1c"])
def test_ogm_lines_end_only_where_mkvmerge_ends_them(separator: str) -> None:
    found = parsed(f"CHAPTER01=00:00:00.000\nCHAPTER01NAME=One{separator}Two\n")
    assert [c.name for c in found.chapters] == [f"One{separator}Two"]


def test_ogm_takes_a_carriage_return_alone_as_a_line_end() -> None:
    found = parsed("CHAPTER01=00:00:00.000\rCHAPTER01NAME=One\rCHAPTER02=00:00:02.000\r")
    assert [(c.start, c.name) for c in found.chapters] == [(0.0, "One"), (2.0, "")]


def test_ogm_keeps_the_file_order_and_repeated_numbers_as_mkvmerge_does() -> None:
    repeated = parsed(
        "CHAPTER01=00:00:00.000\nCHAPTER01NAME=A\nCHAPTER01=00:00:02.000\nCHAPTER01NAME=B\n"
    )
    assert [(c.start, c.name) for c in repeated.chapters] == [(0.0, "A"), (2.0, "B")]
    unordered = parsed(
        "CHAPTER01=00:00:00.000\nCHAPTER01NAME=A\nCHAPTER03=00:00:01.000\nCHAPTER03NAME=C\n"
        "CHAPTER02=00:00:02.000\nCHAPTER02NAME=B\n"
    )
    assert [(c.start, c.name) for c in unordered.chapters] == [(0.0, "A"), (1.0, "C"), (2.0, "B")]
    names_first = parsed("CHAPTER01NAME=A\nCHAPTER01=00:00:00.000\n")
    assert [(c.start, c.name) for c in names_first.chapters] == [(0.0, "A")]


def test_names_keep_the_spaces_mkvmerge_keeps() -> None:
    ogm = parsed("CHAPTER01=00:00:00.000\nCHAPTER01NAME=  lead and trail \t\n")
    assert [c.name for c in ogm.chapters] == ["  lead and trail"]
    xml = parsed(
        f"{XML_HEAD}<Chapters><EditionEntry>"
        + atom("00:00:00.000", "  spaced  ")
        + atom("00:00:01.000", "two\r\nlines")
        + "</EditionEntry></Chapters>"
    )
    assert [c.name for c in xml.chapters] == ["  spaced  ", "two\nlines"]


def test_a_csv_with_quoted_numbers_is_told_from_its_content() -> None:
    found = parsed('"1","Intro"\n"2","Two"\n')
    assert (found.format, [c.name for c in found.chapters]) == ("csv", ["Intro", "Two"])


PUNCTUATION = "It\N{RIGHT SINGLE QUOTATION MARK}s \N{LEFT DOUBLE QUOTATION MARK}one\N{RIGHT DOUBLE QUOTATION MARK} \N{EN DASH} 5\N{EURO SIGN}"  # noqa: E501


@pytest.mark.parametrize(
    ("data", "name", "read_as"),
    [
        (b"1,It\x92s \x93one\x94 \x96 5\x80\n", PUNCTUATION, "Windows-1252"),
        (b"1,Caf\xe9 \x81\n", "Café \x81", "Latin-1 (ISO 8859-1)"),
    ],
)
def test_a_file_that_is_not_utf8_is_read_as_windows_1252_where_it_can_be(
    tmp_path: Path, data: bytes, name: str, read_as: str
) -> None:
    file = tmp_path / "chapters.csv"
    file.write_bytes(data)
    result = read_chapter_file(file)
    assert isinstance(result, ChapterImport)
    assert [c.name for c in result.chapters] == [name]
    [warning] = result.issues
    assert warning.code == "chapters.not_utf8"
    assert f"read as {read_as}:" in warning.message


@pytest.mark.parametrize("encoding", ["utf-32-le", "utf-32-be"])
def test_a_utf32_file_is_not_taken_for_utf16(tmp_path: Path, encoding: str) -> None:
    file = tmp_path / "chapters.csv"
    file.write_bytes("﻿1,Ősz\n".encode(encoding))
    result = read_chapter_file(file)
    assert isinstance(result, ChapterImport)
    assert [c.name for c in result.chapters] == ["Ősz"]
