"""Output tracks of a job drafted from a template. :func:`draft_tracks` is the track stage of
the rule engine: a template's explicit track rules, else its audio and subtitle defaults,
checked by the defaults lint for this source.

With no language set for a kind (no selection language and no preferred language in
Settings), every track of that kind is kept in source order: every audio track through the
codec rules, every subtitle copied. The command builder applies the subtitle container rules
(text to ``mov_text`` in MP4, no PGS in MP4); the decisions only note them.

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
    by base language; tracks without a language are one language (``und``)."""
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
    """The audio and subtitle tracks of ``source`` with ``template``, one decision per source
    track (selected or not, with the reason), and the issues: track rules that do not match
    exactly, no listed audio language with ``no_match = "none"`` (an error), and the defaults
    lint for this source (:func:`~reframe.batch.lint_defaults`).

    ``languages``: the preferred audio and subtitle languages, used when a selection has no
    languages (``None`` = none preferred).
    """
    return resolve_tracks(
        source=source, template=template, definitions=definitions, languages=languages
    ).draft
