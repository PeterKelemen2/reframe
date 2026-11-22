"""Output track metadata, taken from a source track: its language, title and the six flags of
its disposition. An audio codec rule's name template (``{lang_native} {channels}`` →
``Magyar 5.1``) replaces the title.
"""

from __future__ import annotations

from collections.abc import Mapping

from reframe import languages
from reframe.models.job import TrackMetadata
from reframe.models.media import AudioStream, SubtitleStream, VideoStream
from reframe.naming.template import Value, parse_template, render

__all__ = ["effective_language", "language_values", "render_track_name", "track_metadata"]


def language_values(language: str | None) -> dict[str, Value]:
    """The language variables of a track name template: ``lang``, ``lang_name``,
    ``lang_native``."""
    return {
        "lang": language,
        "lang_name": languages.english_name(language),
        "lang_native": languages.native_name(language, capitalize=True),
    }


def effective_language(stream: AudioStream | SubtitleStream | VideoStream) -> str | None:
    """The language that rules match and that is written: ``language_ietf`` if set, else
    ``language``; canonical BCP 47 (``jpn`` → ``ja``) when it is valid.

    A ``language_ietf`` that is not a valid tag (a broken Matroska ``LanguageIETF``) is passed
    over for a valid ``language``, so the track is not undetermined. When neither is valid,
    the raw tag is kept (``language_ietf`` first)."""
    raw = [value for value in (stream.language_ietf, stream.language) if value]
    for value in raw:
        canonical = languages.normalize(value)
        if canonical is not None:
            return canonical
    return raw[0] if raw else None


def track_metadata(
    stream: AudioStream | SubtitleStream | VideoStream, *, name: str | None = None
) -> TrackMetadata:
    """The source track's language, title (or ``name``) and six flags, written explicitly."""
    d = stream.disposition
    return TrackMetadata(
        language=effective_language(stream),
        name=name if name is not None else stream.title,
        default=d.default,
        forced=d.forced,
        commentary=d.comment,
        hearing_impaired=d.hearing_impaired,
        visual_impaired=d.visual_impaired,
        original=d.original,
    )


def render_track_name(template: str, values: Mapping[str, Value]) -> str:
    """Render a track name template with the naming template syntax (``<…>`` groups, format
    specs). A ``/`` is kept as text: a track name has no folders."""
    segments = render(parse_template(template), values)
    return "/".join("".join(piece.text for piece in segment) for segment in segments).strip()
