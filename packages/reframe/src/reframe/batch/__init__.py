"""Batch engine (04-batch-mode.md; 05 §C-12).

Built so far (M2, decision 0018): the **codec-rule stage** of the audio defaults
(:func:`apply_codec_rules`) and the M2 track draft (:func:`draft_tracks`). Not built yet: the
selection stage and ``explain`` (M6); descriptors, fingerprints, grouping, rule derivation
and resolution (M7). Pure: no I/O.
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
from reframe.batch.lint import lint_defaults
from reframe.batch.metadata import (
    NAME_TEMPLATE_VARIABLES,
    effective_language,
    render_track_name,
    track_metadata,
)

__all__ = [
    "NAME_TEMPLATE_VARIABLES",
    "PASSTHRU",
    "apply_codec_rules",
    "channels_match",
    "draft_tracks",
    "effective_language",
    "first_of_language",
    "language_matches",
    "lint_defaults",
    "passthru_codec",
    "render_track_name",
    "requested_mixdown",
    "track_metadata",
]
