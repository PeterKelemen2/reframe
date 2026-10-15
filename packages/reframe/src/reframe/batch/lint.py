"""The audio defaults lint (05 §C-12; 03 §Audio defaults → How the defaults are applied).

Contract stub: built by the C-12 defaults task (wave 1a). ``validate_template`` (C-8) adds its
issues to a preset's issues; the live preview (``draft_tracks``) adds the source-dependent ones.
"""

from __future__ import annotations

from reframe.definitions import Definitions
from reframe.models.defaults import AudioDefaults
from reframe.models.issues import ValidationIssue
from reframe.models.job import Container
from reframe.models.media import MediaSource

__all__ = ["lint_defaults"]


def lint_defaults(
    defaults: AudioDefaults,
    *,
    container: Container = "mkv",
    source: MediaSource | None = None,
    definitions: Definitions | None = None,
) -> list[ValidationIssue]:
    """Problems of the codec rules: a rule shadowed by an earlier rule (warning), an
    unreachable rule, a max bitrate outside the encoder's range (info: snapped, with a note),
    a codec the container cannot hold (error, with fixes); with ``source``, a rule that matches
    no track of that source (info). Paths are template paths
    (``audio_defaults.codec_rules[1].max_bitrate``); fixes target ``"template"``. Pure."""
    del defaults, container, source, definitions
    return []
