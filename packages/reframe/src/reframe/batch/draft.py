"""Output tracks of a job drafted from a template (decision 0018; 05 §C-12).

M2 has the codec-rule stage of the audio defaults, not the selection stage: **every** source
audio track, in source order, goes through the template's codec rules, and **every** source
subtitle track is copied. Each output track gets the source track's language, title and
flags. M6 puts the selection stage (languages, commentary, ``und``, order, default track) in
front of :func:`~reframe.batch.apply_codec_rules` and keeps this function's shape.

Container rules for subtitles (text to ``mov_text`` in MP4, no PGS in MP4) are applied by the
command builder and reported by validation (03 §Subtitles), not here.

Pure: no I/O.
"""

from __future__ import annotations

from reframe import languages
from reframe.batch.audio_rules import apply_codec_rules
from reframe.batch.metadata import effective_language, track_metadata
from reframe.definitions import Definitions, load_definitions
from reframe.models.defaults import TrackDecision, TrackDraft
from reframe.models.job import AudioOutputTrack, SubtitleOutputTrack
from reframe.models.media import AudioStream, MediaSource
from reframe.models.settings import LanguageSettings
from reframe.models.template import JobTemplate

__all__ = ["draft_tracks", "first_of_language"]


def first_of_language(streams: list[AudioStream]) -> list[bool]:
    """For each track: is it the first of its language in this order? Languages are compared
    by base language (``ger`` = ``de``, ``pt-BR`` = ``pt``); tracks without a language are
    one language (``und``)."""
    seen: list[str | None] = []
    result: list[bool] = []
    for stream in streams:
        language = effective_language(stream)
        first = not any(languages.same_language(language, other) for other in seen)
        result.append(first)
        if first:
            seen.append(language)
    return result


def draft_tracks(
    source: MediaSource,
    template: JobTemplate,
    *,
    definitions: Definitions | None = None,
    languages: LanguageSettings | None = None,
) -> TrackDraft:
    """Every audio track through ``template.audio_defaults`` (container
    ``template.output.container``), every subtitle track copied (decision 0018).

    ``first_track_of_language_only`` rules take the first track of each language in source
    order (in M2 every track is selected, in source order).

    ``languages``: Settings → Languages; its preferred audio and subtitle languages are used
    when a selection's ``languages`` is ``None`` (``None`` = no preferred languages). Used by
    the selection stage (core-complete wave 1a).
    """
    del languages  # the selection stage (C-12, M6) uses it
    defs = definitions or load_definitions()
    container = template.output.container
    audio: list[AudioOutputTrack] = []
    decisions: list[TrackDecision] = []
    for stream, first in zip(source.audio, first_of_language(source.audio), strict=True):
        outputs, decision = apply_codec_rules(
            stream,
            template.audio_defaults,
            container,
            definitions=defs,
            first_of_language=first,
        )
        audio.extend(outputs)
        decisions.append(decision)
    subtitles = [
        SubtitleOutputTrack(source=stream.index, action="copy", metadata=track_metadata(stream))
        for stream in source.subtitles
    ]
    return TrackDraft(audio=audio, subtitles=subtitles, decisions=decisions)
