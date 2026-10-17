"""Output tracks of a job drafted from a template (05 §C-12; decisions 0018, 0031, 0040).

:func:`draft_tracks` is the track stage of the one rule engine
(:func:`reframe.batch.rules.resolve_tracks`): a template's explicit track rules, else its
audio defaults (the selection stage, then the codec rules and the default track:
:func:`reframe.batch.explain.audio_stage`) and subtitle defaults (the selection, the foreign
audio search, burn-in and the default track: :func:`reframe.batch.explain.subtitle_stage`),
with the defaults lint for this source.

When no language is set for a kind (the preset's selection has none and Settings has no
preferred languages of that kind), every track of that kind is kept in source order with its
source metadata, as M2 did (decision 0018): every audio track through the codec rules, every
subtitle copied (decision 0031).

Container rules for subtitles (text to ``mov_text`` in MP4, no PGS in MP4) are applied by the
command builder and reported by validation (03 §Subtitles); the decisions only note them.

Pure: no I/O.
"""

from __future__ import annotations

from reframe import languages
from reframe.batch.metadata import effective_language
from reframe.batch.rules import resolve_tracks
from reframe.definitions import Definitions
from reframe.models.defaults import TrackDraft
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
    """The audio and subtitle tracks of ``source`` with ``template`` (container
    ``template.output.container``), one decision per source track (selected or not, with the
    reason), and the issues: track rules that do not match exactly, no listed audio language
    with ``no_match = "none"`` (an error), and the defaults lint for this source
    (:func:`~reframe.batch.lint_defaults`).

    ``languages``: Settings → Languages; its preferred audio and subtitle languages are used
    when a selection has no languages (``None`` = no preferred languages).
    """
    return resolve_tracks(
        source=source, template=template, definitions=definitions, languages=languages
    ).draft
