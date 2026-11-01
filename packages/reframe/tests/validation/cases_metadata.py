"""Rule cases of external subtitle encodings, tag values and generated chapters."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from reframe.models import ExternalSubtitle, SubtitleOutputTrack
from reframe.textfile import TextCharset

EXTERNAL = Path("/media/movies/Movie.2019.hu.srt")
UNKNOWN = TextCharset(None, ascii=False)
ASCII = TextCharset("UTF-8", ascii=True)
UTF8 = TextCharset("UTF-8", ascii=False)
UTF16 = TextCharset("UTF-16LE", ascii=False)
AT = "subtitles[2].source.charset"


def external(found: TextCharset, charset: str | None = None, path: Path = EXTERNAL) -> Any:
    def mod(s: Any) -> None:
        source = ExternalSubtitle(path=path, charset=charset)
        s.job.subtitles.append(SubtitleOutputTrack(source=source))
        s.fs.add_file(path, found)

    return mod


def tags(**values: str | None) -> Any:
    def mod(s: Any) -> None:
        for name, value in values.items():
            setattr(s.job.tags, name, value)

    return mod


def track_name(value: str) -> Any:
    def mod(s: Any) -> None:
        s.job.audio[0].metadata.name = value

    return mod


def generate_every(minutes: float) -> Any:
    def mod(s: Any) -> None:
        s.source.chapters = []
        s.job.chapters.generate_every = minutes

    return mod


def cases(h: Any) -> list[Any]:
    case, err = h.Case, h.ERR
    return [
        case(
            "charset_not_detected", "subtitle.charset_unknown", AT, err,
            external(UNKNOWN), external(UNKNOWN, "CP1250"),
        ),
        case(
            "charset_of_a_bitmap_file", "subtitle.charset_unknown", AT, err,
            external(UNKNOWN), external(UNKNOWN, path=EXTERNAL.with_suffix(".sup")),
        ),
        case(
            "utf16_file", "subtitle.utf16", AT, err,
            external(UTF16), external(UTF8),
        ),
        case(
            "utf16_file_with_a_charset", "subtitle.utf16", AT, err,
            external(UTF16, "CP1252"), external(UNKNOWN, "CP1252"),
        ),
        case(
            "utf16_chosen", "subtitle.utf16", AT, err,
            external(UTF8, "utf-16le"), external(UTF8),
        ),
        case(
            "legacy_charset_on_utf8", "subtitle.charset_mismatch", AT, err,
            external(UTF8, "CP1250"), external(ASCII, "CP1250"),
        ),
        case(
            "utf8_chosen_on_another_encoding", "subtitle.charset_mismatch", AT, err,
            external(UNKNOWN, "utf8"), external(UTF8, "UTF-8"),
        ),
        case(
            "tag_unknown_variable", "naming.unknown_variable", "tags.genre", err,
            tags(genre="{nme}"), tags(genre="{name}"),
        ),
        case(
            "tag_syntax", "naming.template_syntax", "tags.title", err,
            tags(title="{name"), tags(title="{name}"),
        ),
        case(
            "tag_format_spec", "naming.bad_format_spec", "tags.release_date", err,
            tags(release_date="{year:%Y}"), tags(release_date="{year:04}"),
        ),
        case(
            "tag_nul", "metadata.nul_character", "tags.comment", err,
            tags(comment="a\0b"), tags(comment="a b"),
        ),
        case(
            "track_name_nul", "metadata.nul_character", "audio[0].metadata.name", err,
            track_name("Main\0"), track_name("Main"),
        ),
        case(
            "tag_too_long", "metadata.tag_too_long", "tags.plot", err,
            tags(plot="x" * 3001), tags(plot="x" * 3000),
        ),
        case(
            "chapters_too_many", "chapters.too_many", "chapters.generate_every", err,
            generate_every(0.001), generate_every(0.02),
        ),
    ]  # fmt: skip
