"""Chapter files: HandBrake's CSV, OGM text and Matroska XML, read and written.

Pure, except :func:`read_chapter_file`, which reads one file of at most
:data:`MAX_CHAPTER_FILE` bytes. A file that cannot be read is a :class:`ChapterFileError`
value, never an exception.
"""

from __future__ import annotations

import codecs
import csv
import io
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Literal
from xml.parsers import expat
from xml.sax.saxutils import escape

from reframe.models import (
    ChapterExport,
    ChapterFormat,
    ChapterImport,
    ImportedChapter,
    OutputChapter,
    Severity,
    ValidationIssue,
)

__all__ = [
    "EXTENSIONS",
    "MAX_CHAPTER_FILE",
    "ChapterFileError",
    "chapter_export",
    "detect_format",
    "parse_chapters",
    "read_chapter_file",
    "write_chapters",
]

#: Bytes: a chapter file of a thousand chapters in XML is about 300 KB.
MAX_CHAPTER_FILE = 4 * 2**20
#: The file name ending of each format (OGM chapter files are plain text).
EXTENSIONS: dict[ChapterFormat, str] = {"csv": ".csv", "ogm": ".txt", "xml": ".xml"}

_OGM_TIME = re.compile(r"^CHAPTER(\d+)=(\d+):(\d{1,2}):(\d{1,2}(?:[.,]\d+)?)$", re.IGNORECASE)
_OGM_NAME = re.compile(r"^CHAPTER(\d+)NAME=(.*)$", re.IGNORECASE)
_XML_TIME = re.compile(r"^(\d+):(\d{1,2}):(\d{1,2}(?:\.\d+)?)$")
_CSV_ROW = re.compile(r"^\s*\d+\s*,")
#: Characters XML 1.0 does not allow, not even as a reference.
_NOT_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


@dataclass(frozen=True, slots=True)
class ChapterFileError:
    """Why a chapter file could not be read."""

    kind: Literal["unreadable", "invalid"]
    """``unreadable``: the file (missing, too large, an I/O error); ``invalid``: its content."""
    message: str
    line: int | None = None
    """1-based line of the content error, when known."""

    @property
    def detail(self) -> str:
        return self.message if self.line is None else f"Line {self.line}: {self.message}"


@dataclass(slots=True)
class _Read:
    chapters: list[ImportedChapter] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)


def _warning(code: str, message: str) -> ValidationIssue:
    return ValidationIssue(severity=Severity.WARNING, code=code, path="", message=message)


def _decode(data: bytes) -> tuple[str, list[ValidationIssue]]:
    for bom, encoding in (
        (codecs.BOM_UTF8, "utf-8-sig"),
        (codecs.BOM_UTF16_LE, "utf-16"),
        (codecs.BOM_UTF16_BE, "utf-16"),
    ):
        if data.startswith(bom):
            return data.decode(encoding, errors="replace"), []
    try:
        return data.decode("utf-8"), []
    except UnicodeDecodeError:
        warning = _warning(
            "chapters.not_utf8",
            "The file is not UTF-8, so it was read as Latin-1 (ISO 8859-1): check the names.",
        )
        return data.decode("latin-1"), [warning]


def detect_format(text: str) -> ChapterFormat | None:
    """The format of a chapter file's text, from its first line that is not empty."""
    for line in text.lstrip("﻿").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("<"):
            return "xml"
        if stripped.upper().startswith("CHAPTER"):
            return "ogm"
        if _CSV_ROW.match(stripped):
            return "csv"
        return None
    return None


def _seconds(hours: str, minutes: str, seconds: str) -> float:
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds.replace(",", "."))


def _parse_csv(text: str) -> _Read | ChapterFileError:
    """HandBrake's export: ``number,name`` per line, RFC 4180 quoting (testdata/README.md)."""
    found = _Read()
    numbers: list[int] = []
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        for row in reader:
            line = reader.line_num
            if not row or not "".join(row).strip():
                continue
            if len(row) < 2:
                return ChapterFileError("invalid", "a line needs a number and a name", line)
            try:
                numbers.append(int(row[0].strip()))
            except ValueError:
                return ChapterFileError("invalid", f"{row[0]!r} is not a chapter number", line)
            found.chapters.append(ImportedChapter(start=None, name=row[1].strip()))
    except csv.Error as exc:
        return ChapterFileError("invalid", str(exc), reader.line_num)
    if numbers != list(range(1, len(numbers) + 1)):
        found.issues.append(
            _warning(
                "chapters.numbers",
                "The chapter numbers are not 1, 2, 3 … in order: the names are taken in the "
                "order of the lines.",
            )
        )
    return found


def _parse_ogm(text: str) -> _Read | ChapterFileError:
    times: dict[int, float] = {}
    names: dict[int, str] = {}
    order: list[int] = []
    for line_number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        time = _OGM_TIME.match(line)
        name = _OGM_NAME.match(line) if time is None else None
        if time is not None:
            number = int(time[1])
            times[number] = _seconds(time[2], time[3], time[4])
        elif name is not None:
            number = int(name[1])
            names[number] = name[2].strip()
        else:
            return ChapterFileError(
                "invalid", "expected CHAPTERnn=hh:mm:ss.sss or CHAPTERnnNAME=name", line_number
            )
        if number not in order:
            order.append(number)
    found = _Read()
    for number in sorted(order):
        found.chapters.append(ImportedChapter(start=times.get(number), name=names.get(number, "")))
    if any(number not in times for number in order):
        found.issues.append(
            _warning("chapters.no_time", "A chapter has a name but no time (CHAPTERnn=).")
        )
    return found


@dataclass(slots=True)
class _Node:
    tag: str
    line: int
    children: list[_Node] = field(default_factory=list)
    text: str = ""

    def child(self, tag: str) -> _Node | None:
        return next((c for c in self.children if c.tag == tag), None)


class _EntityRefused(ValueError):
    pass


def _xml_tree(text: str) -> _Node | ChapterFileError:
    parser = expat.ParserCreate()
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    stack: list[_Node] = []
    root: list[_Node] = []

    def refuse(*_args: object) -> None:
        raise _EntityRefused

    def start(tag: str, _attrs: dict[str, str]) -> None:
        node = _Node(tag, parser.CurrentLineNumber)
        if stack:
            stack[-1].children.append(node)
        else:
            root.append(node)
        stack.append(node)

    def end(_tag: str) -> None:
        stack.pop()

    def text_of(data: str) -> None:
        if stack:
            stack[-1].text += data

    # An entity declaration could expand to gigabytes; a chapter file never needs one.
    parser.EntityDeclHandler = refuse
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = text_of
    try:
        parser.Parse(text, True)
    except _EntityRefused:
        return ChapterFileError(
            "invalid", "the file declares XML entities, which are not read", parser.ErrorLineNumber
        )
    except expat.ExpatError as exc:
        return ChapterFileError("invalid", expat.ErrorString(exc.code), exc.lineno)
    if not root:
        return ChapterFileError("invalid", "the file has no XML element")
    return root[0]


def _parse_xml(text: str) -> _Read | ChapterFileError:
    root = _xml_tree(text)
    if isinstance(root, ChapterFileError):
        return root
    if root.tag != "Chapters":
        return ChapterFileError("invalid", f"the root element is <{root.tag}>, not <Chapters>", 1)
    editions = [c for c in root.children if c.tag == "EditionEntry"]
    if not editions:
        return ChapterFileError("invalid", "there is no <EditionEntry>", root.line)
    found = _Read()
    if len(editions) > 1:
        found.issues.append(
            _warning(
                "chapters.editions",
                f"The file has {len(editions)} editions: only the first one is read.",
            )
        )
    nested = False
    for atom in (c for c in editions[0].children if c.tag == "ChapterAtom"):
        start_node = atom.child("ChapterTimeStart")
        if start_node is None:
            return ChapterFileError(
                "invalid", "a <ChapterAtom> has no <ChapterTimeStart>", atom.line
            )
        time = _XML_TIME.match(start_node.text.strip())
        if time is None:
            return ChapterFileError(
                "invalid", f"{start_node.text.strip()!r} is not a time (hh:mm:ss.nnnnnnnnn)",
                start_node.line,
            )  # fmt: skip
        display = atom.child("ChapterDisplay")
        string = display.child("ChapterString") if display is not None else None
        name = string.text.strip() if string is not None else ""
        found.chapters.append(ImportedChapter(start=_seconds(*time.groups()), name=name))
        nested = nested or atom.child("ChapterAtom") is not None
    if nested:
        found.issues.append(_warning("chapters.nested", "Chapters inside chapters are left out."))
    return found


_PARSERS = {"csv": _parse_csv, "ogm": _parse_ogm, "xml": _parse_xml}


def parse_chapters(
    text: str, chapter_format: ChapterFormat | None = None
) -> ChapterImport | ChapterFileError:
    """The chapters of a chapter file's text; ``chapter_format`` ``None``: from the content."""
    text = text.lstrip("﻿")
    found_format = chapter_format or detect_format(text)
    if found_format is None:
        return ChapterFileError(
            "invalid", "this is not a chapter file (CSV, OGM text or Matroska XML)"
        )
    read = _PARSERS[found_format](text)
    if isinstance(read, ChapterFileError):
        return read
    if not read.chapters:
        return ChapterFileError("invalid", "the file has no chapters")
    return ChapterImport(format=found_format, chapters=read.chapters, issues=read.issues)


def read_chapter_file(
    path: str | os.PathLike[str], chapter_format: ChapterFormat | None = None
) -> ChapterImport | ChapterFileError:
    """:func:`parse_chapters` of a file (UTF-8 or UTF-16 with a byte order mark, UTF-8, else
    Latin-1 with a warning). Blocks: call it in a worker thread."""
    try:
        with open(path, "rb") as file:
            data = file.read(MAX_CHAPTER_FILE + 1)
    except FileNotFoundError:
        return ChapterFileError("unreadable", "The file does not exist.")
    except IsADirectoryError:
        return ChapterFileError("unreadable", "The path is a folder, not a file.")
    except OSError as exc:
        return ChapterFileError("unreadable", f"The file cannot be read: {exc.strerror}.")
    if len(data) > MAX_CHAPTER_FILE:
        limit = MAX_CHAPTER_FILE // 2**20
        return ChapterFileError("unreadable", f"The file is larger than {limit} MiB.")
    text, issues = _decode(data)
    result = parse_chapters(text, chapter_format)
    if isinstance(result, ChapterFileError):
        return result
    return result.model_copy(update={"issues": [*issues, *result.issues]})


def _clock(seconds: float, digits: int) -> str:
    units = round(seconds * 10**digits)
    whole, fraction = divmod(units, 10**digits)
    minutes, secs = divmod(whole, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{fraction:0{digits}d}"


def _write_csv(chapters: Sequence[OutputChapter]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    for chapter in chapters:
        writer.writerow([chapter.number, chapter.name])
    return out.getvalue()


def _write_ogm(chapters: Sequence[OutputChapter]) -> str:
    lines: list[str] = []
    for chapter in chapters:
        number = f"{chapter.number:02d}"
        # A line end in a name would start a line of its own.
        name = " ".join(chapter.name.splitlines())
        lines += [f"CHAPTER{number}={_clock(chapter.start, 3)}", f"CHAPTER{number}NAME={name}"]
    return "\n".join(lines) + "\n"


def _write_xml(chapters: Sequence[OutputChapter]) -> str:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<Chapters>", "  <EditionEntry>"]
    for chapter in chapters:
        lines += [
            "    <ChapterAtom>",
            f"      <ChapterTimeStart>{_clock(chapter.start, 9)}</ChapterTimeStart>",
            f"      <ChapterTimeEnd>{_clock(chapter.end, 9)}</ChapterTimeEnd>",
        ]
        if chapter.name:
            lines += [
                "      <ChapterDisplay>",
                f"        <ChapterString>{escape(_NOT_XML.sub(' ', chapter.name))}</ChapterString>",
                "        <ChapterLanguage>und</ChapterLanguage>",
                "      </ChapterDisplay>",
            ]
        lines.append("    </ChapterAtom>")
    lines += ["  </EditionEntry>", "</Chapters>"]
    return "\n".join(lines) + "\n"


_WRITERS = {"csv": _write_csv, "ogm": _write_ogm, "xml": _write_xml}


def write_chapters(chapters: Sequence[OutputChapter], chapter_format: ChapterFormat) -> str:
    """The text of a chapter file with ``chapters`` (to be saved as UTF-8)."""
    return _WRITERS[chapter_format](chapters)


def chapter_export(
    chapters: Sequence[OutputChapter], chapter_format: ChapterFormat, name_of: PurePath
) -> ChapterExport:
    """:func:`write_chapters` with a file name from ``name_of`` (the output path)."""
    stem = name_of.name[: -len(name_of.suffix)] if name_of.suffix else name_of.name
    return ChapterExport(
        format=chapter_format,
        file_name=f"{stem}.chapters{EXTENSIONS[chapter_format]}",
        content=write_chapters(chapters, chapter_format),
    )
