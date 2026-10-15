"""Batch engine (04-batch-mode.md; 05 §C-12). Pure: no I/O (``Reframe.batch``,
:mod:`reframe.batch.service`, is the one part that probes, names and validates; it is not
imported here).

**Audio and subtitle defaults** of a preset (03 §Audio defaults, §Subtitles; decisions 0018,
0019, 0023, 0031):

- the **selection stage** (:mod:`reframe.batch.selection`, :func:`select_tracks`): which
  source tracks to take, why, and in which order;
- the **codec-rule stage** of the audio defaults (:func:`apply_codec_rules`, built in M2);
- the foreign audio search, burn-in and the default-track settings, and
  :func:`explain` / :func:`explain_subtitles` (:mod:`reframe.batch.explain`): one
  :class:`~reframe.models.TrackDecision` per source track, the rows of the live preview;
- the defaults lint (:func:`lint_defaults`).

**Batch / season mode** (04; decision 0040):

- :func:`describe_tracks`, :func:`fingerprint` (:mod:`reframe.batch.descriptors`): track
  descriptors and fingerprints at the strict, standard and loose levels;
- :func:`group_sources` (:mod:`reframe.batch.grouping`): groups, near members, episode order;
- the **one rule engine** for presets and batch mode (:mod:`reframe.batch.rules`,
  :mod:`reframe.batch.selectors`): explicit track rules with relaxation, or the defaults
  compiled into rules (:func:`compile_defaults`); :func:`draft_tracks` is its track stage;
- :func:`derive_template`, :func:`merge_template` (:mod:`reframe.batch.derive`): *Apply to
  group…* and copy / paste of sections;
- :func:`resolve`, :func:`resolve_group` (:mod:`reframe.batch.resolve`) with per-file
  overrides as JSON patches (:mod:`reframe.batch.overrides`): the job of each file and its
  match report.
"""

from reframe.batch.audio_rules import (
    PASSTHRU,
    apply_codec_rules,
    channels_match,
    language_matches,
    passthru_codec,
    requested_mixdown,
)
from reframe.batch.derive import (
    SECTIONS,
    as_template,
    derive_selector,
    derive_template,
    merge_template,
)
from reframe.batch.descriptors import MATCH_LEVELS, describe_tracks, fingerprint
from reframe.batch.draft import draft_tracks, first_of_language
from reframe.batch.explain import (
    audio_stage,
    explain,
    explain_subtitles,
    foreign_audio_search,
    subtitle_stage,
)
from reframe.batch.grouping import NEAR_MAX_DIFFERENCES, episode_key, group_sources
from reframe.batch.lint import lint_defaults
from reframe.batch.metadata import (
    NAME_TEMPLATE_VARIABLES,
    effective_language,
    render_track_name,
    track_metadata,
)
from reframe.batch.overrides import apply_job_override, apply_template_override, split_override
from reframe.batch.resolve import (
    build_job,
    matrix_columns,
    output_size,
    resolve,
    resolve_group,
    video_metadata,
)
from reframe.batch.rules import TrackResolution, compile_defaults, resolve_tracks, rule_label
from reframe.batch.selection import Selection, effective_languages, select_tracks

__all__ = [
    "MATCH_LEVELS",
    "NAME_TEMPLATE_VARIABLES",
    "NEAR_MAX_DIFFERENCES",
    "PASSTHRU",
    "SECTIONS",
    "Selection",
    "TrackResolution",
    "apply_codec_rules",
    "apply_job_override",
    "apply_template_override",
    "as_template",
    "audio_stage",
    "build_job",
    "channels_match",
    "compile_defaults",
    "derive_selector",
    "derive_template",
    "describe_tracks",
    "draft_tracks",
    "effective_language",
    "effective_languages",
    "episode_key",
    "explain",
    "explain_subtitles",
    "fingerprint",
    "first_of_language",
    "foreign_audio_search",
    "group_sources",
    "language_matches",
    "lint_defaults",
    "matrix_columns",
    "merge_template",
    "output_size",
    "passthru_codec",
    "render_track_name",
    "requested_mixdown",
    "resolve",
    "resolve_group",
    "resolve_tracks",
    "rule_label",
    "select_tracks",
    "split_override",
    "subtitle_stage",
    "track_metadata",
    "video_metadata",
]
