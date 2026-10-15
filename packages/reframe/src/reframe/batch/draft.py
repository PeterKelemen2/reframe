"""Output tracks of a job drafted from a template (05 §C-12; decisions 0018, 0031).

:func:`draft_tracks` runs the audio defaults (the selection stage, then the codec rules and the
default track: :func:`reframe.batch.explain.audio_stage`) and the subtitle defaults (the
selection, the foreign audio search, burn-in and the default track:
:func:`reframe.batch.explain.subtitle_stage`), and adds the defaults lint for this source.

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
from reframe.batch.explain import audio_stage, subtitle_stage
from reframe.batch.lint import lint_rules
from reframe.batch.metadata import effective_language
from reframe.definitions import Definitions, load_definitions
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
    """The audio and subtitle tracks of ``source`` with ``template``'s defaults (container
    ``template.output.container``), one decision per source track (selected or not, with the
    reason), and the issues: no listed audio language with ``no_match = "none"`` (an error)
    and the defaults lint for this source (:func:`~reframe.batch.lint_defaults`).

    ``languages``: Settings → Languages; its preferred audio and subtitle languages are used
    when a selection has no languages (``None`` = no preferred languages).
    """
    defs = definitions or load_definitions()
    container = template.output.container
    preferred_audio = languages.preferred_audio if languages is not None else []
    preferred_subtitle = languages.preferred_subtitle if languages is not None else []
    audio = audio_stage(
        template.audio_defaults,
        source,
        container=container,
        preferred_languages=preferred_audio,
        definitions=defs,
    )
    subtitles = subtitle_stage(
        template.subtitle_defaults,
        source,
        container=container,
        preferred_languages=preferred_subtitle,
        audio=audio.outputs,
        definitions=defs,
    )
    selected = [d for d in audio.decisions if d.selected]
    used = {d.rule for d in selected if d.rule is not None} if selected else None
    issues = [
        *audio.issues,
        *subtitles.issues,
        *lint_rules(template.audio_defaults, container=container, definitions=defs, used=used),
    ]
    return TrackDraft(
        audio=audio.outputs,
        subtitles=subtitles.outputs,
        decisions=audio.decisions,
        subtitle_decisions=subtitles.decisions,
        issues=issues,
    )
