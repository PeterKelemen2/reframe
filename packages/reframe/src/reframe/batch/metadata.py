"""Output track metadata taken from a source track (03 §Track metadata; decision 0018).

The output track gets the source track's language, title and the six flags of its
disposition. An audio codec rule's name template (``{lang_native} {channels}`` →
``Magyar 5.1``) replaces the title.
"""

from __future__ import annotations

from collections.abc import Mapping

from reframe import languages
from reframe.models.job import TrackMetadata
from reframe.models.media import AudioStream, SubtitleStream
from reframe.naming.template import Value, parse_template, render

__all__ = ["NAME_TEMPLATE_VARIABLES", "effective_language", "render_track_name", "track_metadata"]

#: The variables of an audio track name template, with what they hold.
NAME_TEMPLATE_VARIABLES: dict[str, str] = {
    "lang": "The language tag: hu, pt-BR",
    "lang_name": "The English name of the language: Hungarian",
    "lang_native": "The language's own name: Magyar",
    "channels": "The output channel layout: 5.1, 2.0",
    "codec": "The output codec: AC-3, AAC; for passthru the source codec",
    "bitrate": "The output bit rate in kb/s (empty for passthru and lossless encoders)",
    "title": "The source track's title",
    "source_codec": "The source codec: TrueHD Atmos, DTS-HD MA",
}


def effective_language(stream: AudioStream | SubtitleStream) -> str | None:
    """The language that rules match and that is written: ``language_ietf`` if set, else
    ``language`` (05 §C-2); canonical BCP 47 (``jpn`` → ``ja``) when it is valid.

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
    stream: AudioStream | SubtitleStream, *, name: str | None = None
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
