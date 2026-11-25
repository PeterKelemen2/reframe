"""Rule cases of external subtitle encodings, tag values, track names and generated
chapters."""

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


def source_title(title: str, *, copy: bool = False) -> Any:
    """The first source audio track (AC-3 5.1, encoded to AAC stereo) titled ``title``; the
    output track keeps the source title, or with ``copy`` passes the track through."""

    def mod(s: Any) -> None:
        s.source.audio[0].title = title
        if copy:
            s.job.audio[0].action = "passthru"

    return mod


def lossless_source(s: Any) -> None:
    stream = s.source.audio[0]
    stream.codec, stream.display_codec, stream.lossless = "truehd", "TrueHD", True


def subtitle_converted(name: str | None, convert_to: str = "ass") -> Any:
    def mod(s: Any) -> None:
        track = s.job.subtitles[0]
        track.action, track.convert_to = "convert", convert_to
        track.metadata.name = name

    return mod


def generate_every(minutes: float, *, source_chapters: bool = False) -> Any:
    def mod(s: Any) -> None:
        if not source_chapters:
            s.source.chapters = []
        s.job.chapters.generate_every = minutes

    return mod


def external_name(name: str) -> Any:
    def mod(s: Any) -> None:
        s.job.subtitles.append(
            SubtitleOutputTrack(source=ExternalSubtitle(path=EXTERNAL, name=name))
        )
        s.fs.add_file(EXTERNAL, UTF8)

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
            "external_name_nul", "metadata.nul_character", "subtitles[2].source.name", err,
            external_name("Hu\0n"), external_name("Hun"),
        ),
        case(
            "track_name_variable_typo", "metadata.name_variable_unknown",
            "audio[0].metadata.name", h.WARN,
            track_name("{lang_nmae} {channels}"), track_name("Signs {Karaoke}"),
        ),
        case(
            "track_name_with_another_variable", "metadata.name_variable_unknown",
            "audio[0].metadata.name", h.WARN,
            track_name("{lang_name} {episode}"), track_name("{lang_name} {{episode}}"),
        ),
        case(
            "track_name_names_the_source_codec", "metadata.name_stale",
            "audio[0].metadata.name", h.WARN,
            track_name("English AC-3 5.1"), track_name("English AAC Stereo"),
        ),
        case(
            "source_title_names_the_source_layout", "metadata.name_stale",
            "audio[0].metadata.name", h.WARN,
            source_title("Japanese 5.1"), source_title("Japanese 5.1", copy=True),
        ),
        case(
            "converted_subtitle_names_its_old_format", "metadata.name_stale",
            "subtitles[0].metadata.name", h.WARN,
            subtitle_converted("English SRT"), subtitle_converted("English SRT", "srt"),
        ),
        case(
            "lossless_source_mixed_down_to_lossy", "audio.lossless_downmix", "audio[0].mixdown",
            h.INFO,
            lossless_source, h.both(lossless_source, h.audio(0, mixdown=None)),
        ),
        case(
            "tag_too_long", "metadata.tag_too_long", "tags.plot", err,
            tags(plot="x" * 3001), tags(plot="x" * 3000),
        ),
        case(
            "chapters_too_many", "chapters.too_many", "chapters.generate_every", err,
            generate_every(0.001), generate_every(0.02),
        ),
        case(
            "chapters_too_many_but_the_source_has_chapters", "chapters.too_many",
            "chapters.generate_every", err,
            generate_every(0.001), generate_every(0.001, source_chapters=True),
        ),
    ]  # fmt: skip
