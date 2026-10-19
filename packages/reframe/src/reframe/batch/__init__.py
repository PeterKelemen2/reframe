"""The batch engine. Pure: no I/O. The service that probes, names and validates a batch is
not imported here."""

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
