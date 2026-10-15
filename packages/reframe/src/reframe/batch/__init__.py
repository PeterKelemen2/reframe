"""Batch engine (04-batch-mode.md; 05 §C-12).

Built so far: the **audio and subtitle defaults** of a preset (03 §Audio defaults, §Subtitles;
decisions 0018, 0019, 0023, 0031):

- the **selection stage** (:mod:`reframe.batch.selection`, :func:`select_tracks`): which
  source tracks to take, why, and in which order;
- the **codec-rule stage** of the audio defaults (:func:`apply_codec_rules`, built in M2);
- the foreign audio search, burn-in and the default-track settings, and
  :func:`explain` / :func:`explain_subtitles` (:mod:`reframe.batch.explain`): one
  :class:`~reframe.models.TrackDecision` per source track, the rows of the live preview;
- :func:`draft_tracks`: the output tracks of a job drafted from a template;
- the defaults lint (:func:`lint_defaults`).

Not built yet (M7): descriptors, fingerprints, grouping, rule derivation and resolution. Pure:
no I/O.
"""

from reframe.batch.audio_rules import (
    PASSTHRU,
    apply_codec_rules,
    channels_match,
    language_matches,
    passthru_codec,
    requested_mixdown,
)
from reframe.batch.draft import draft_tracks, first_of_language
from reframe.batch.explain import (
    audio_stage,
    explain,
    explain_subtitles,
    foreign_audio_search,
    subtitle_stage,
)
from reframe.batch.lint import lint_defaults
from reframe.batch.metadata import (
    NAME_TEMPLATE_VARIABLES,
    effective_language,
    render_track_name,
    track_metadata,
)
from reframe.batch.selection import Selection, effective_languages, select_tracks

__all__ = [
    "NAME_TEMPLATE_VARIABLES",
    "PASSTHRU",
    "Selection",
    "apply_codec_rules",
    "audio_stage",
    "channels_match",
    "draft_tracks",
    "effective_language",
    "effective_languages",
    "explain",
    "explain_subtitles",
    "first_of_language",
    "foreign_audio_search",
    "language_matches",
    "lint_defaults",
    "passthru_codec",
    "render_track_name",
    "requested_mixdown",
    "select_tracks",
    "subtitle_stage",
    "track_metadata",
]
