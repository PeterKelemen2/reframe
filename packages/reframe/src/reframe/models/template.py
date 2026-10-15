"""Job templates and track rules (04 §Track rules, §Per-file overrides; C-12).

A :class:`JobTemplate` is a :class:`~reframe.models.job.JobSettings` without the
source-specific parts, plus track **rules** instead of concrete tracks, a naming template and
the per-file policies. A preset is a template with a name (``reframe.models.preset``); a
batch group template is the same model. There is one rule engine for presets and batch mode.

How the audio rules are built (04): when ``audio_rules`` is empty, C-12 compiles
``audio_defaults`` into rules (one per language of the selection, with
:class:`AudioCodecRules` settings). A manual edit in batch mode becomes explicit rules with
fixed :class:`AudioOutputSettings`; explicit rules take precedence over the defaults. The
same holds for subtitles.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator

from reframe.models.base import DocumentModel, LanguageTag, NonNegativeInt, PositiveInt
from reframe.models.defaults import (
    AudioCodecRule,
    AudioDefaults,
    PassthruPolicy,
    SubtitleDefaults,
    check_catch_all,
    default_codec_rules,
)
from reframe.models.geometry import DimensionSettings
from reframe.models.job import (
    FilterSettings,
    OutputOptions,
    TagSettings,
    VideoSettings,
    _AudioEncoding,
    _SubtitleHandling,
)
from reframe.models.media import TrackRole
from reframe.models.naming import NamingOptions

__all__ = [
    "AudioCodecRules",
    "AudioOutputSettings",
    "ChapterNamePolicy",
    "ChapterOptions",
    "CropPolicy",
    "JobTemplate",
    "OutputTrackRule",
    "SubtitleOutputSettings",
    "TrackMetadataTemplate",
    "TrackRuleSettings",
    "TrackSelector",
]

CropPolicy = Literal["detect_per_file", "fixed"]
"""``detect_per_file``: auto-detect the crop for each file (default); ``fixed``: the same
manual crop (``dimensions.crop``) for all files."""
ChapterNamePolicy = Literal["source", "generated"]


class TrackSelector(DocumentModel):
    """Which source track(s) a rule takes (04 §Track rules; field names as in the plan)."""

    kind: Literal["audio", "subtitle"]
    languages: list[LanguageTag] | None = None
    """BCP 47, in order of preference."""
    codecs: list[str] | None = None
    """``truehd``, ``dts``, ``ac3``, …"""
    profiles: list[str] | None = None
    """``DTS-HD MA``, ``TrueHD Atmos``, …"""
    roles: list[TrackRole] | None = None
    exclude_roles: list[TrackRole] | None = None
    channels: PositiveInt | None = None
    title_pattern: str | None = None
    """Case-insensitive regular expression."""
    nth: NonNegativeInt = 0
    """The nth candidate after filtering and sorting."""
    sort: Literal["source_order", "most_channels", "highest_bitrate"] = "source_order"
    """``highest_bitrate`` is decision 0031's best-quality order: lossless first, then the
    highest known bit rate (an unknown one after every known one), then more channels;
    for subtitles ``most_channels`` and ``highest_bitrate`` put full subtitles before SDH
    before forced and Signs & Songs (decision 0040)."""
    stream: NonNegativeInt | None = None
    """A per-file override (04 §Resolution matrix: a candidate picked by hand in a cell): the
    absolute index of the source track this rule takes in that one file; the other fields
    are not checked. Not for a preset: a stream index does not carry over to other files."""


class AudioOutputSettings(_AudioEncoding):
    """Fixed audio settings of a rule (a manual edit in batch mode)."""

    kind: Literal["audio"] = "audio"


class AudioCodecRules(DocumentModel):
    """Codec rules evaluated per matched source track (compiled from the preset's audio
    defaults). The last rule is the catch-all; the model enforces it."""

    kind: Literal["audio_rules"] = "audio_rules"
    rules: list[AudioCodecRule] = Field(default_factory=default_codec_rules)
    passthru: PassthruPolicy = Field(default_factory=PassthruPolicy)

    @field_validator("rules")
    @classmethod
    def _catch_all_last(cls, rules: list[AudioCodecRule]) -> list[AudioCodecRule]:
        return check_catch_all(rules)


class SubtitleOutputSettings(_SubtitleHandling):
    """Fixed subtitle settings of a rule."""

    kind: Literal["subtitle"] = "subtitle"


#: The settings of a track rule, discriminated by ``kind``.
TrackRuleSettings = Annotated[
    AudioOutputSettings | AudioCodecRules | SubtitleOutputSettings, Field(discriminator="kind")
]


class TrackMetadataTemplate(DocumentModel):
    """Output metadata of a rule. ``None`` means "from the source track" for every field."""

    language: LanguageTag | None = None
    name_template: str | None = None
    """``{lang_name} {channels} {codec}`` → ``Japanese 5.1 Opus``; ``None`` = source title."""
    default: bool | None = None
    forced: bool | None = None
    commentary: bool | None = None
    hearing_impaired: bool | None = None
    visual_impaired: bool | None = None
    original: bool | None = None


class OutputTrackRule(DocumentModel):
    """ "Output track N comes from the source track that matches ``selector``, with
    ``settings`` and ``metadata``" (04 §Track rules)."""

    selector: TrackSelector
    multiple: bool = False
    """True: one output track per matching source track."""
    settings: TrackRuleSettings
    metadata: TrackMetadataTemplate = Field(default_factory=TrackMetadataTemplate)
    required: bool = True
    """No match: an error (True) or skip with a warning (False)."""


class ChapterOptions(DocumentModel):
    """The chapter options of a template (chapter names are per file)."""

    enabled: bool = True
    generate_every: Annotated[float, Field(gt=0)] | None = None
    """Minutes, when the source has no chapters."""


class JobTemplate(DocumentModel):
    """``JobSettings`` without source-specific fields, plus rules, naming and policies.

    Not in a template: the source, the range (always the full file), the output path and
    per-job name, concrete audio/subtitle tracks, chapter names.
    """

    schema_version: PositiveInt = 1
    output: OutputOptions = Field(default_factory=OutputOptions)
    dimensions: DimensionSettings = Field(default_factory=DimensionSettings)
    crop_policy: CropPolicy = "detect_per_file"
    filters: FilterSettings = Field(default_factory=FilterSettings)
    video: VideoSettings = Field(default_factory=VideoSettings)
    audio_defaults: AudioDefaults = Field(default_factory=AudioDefaults)
    subtitle_defaults: SubtitleDefaults = Field(default_factory=SubtitleDefaults)
    audio_rules: list[OutputTrackRule] = Field(default_factory=list)
    subtitle_rules: list[OutputTrackRule] = Field(default_factory=list)
    chapters: ChapterOptions = Field(default_factory=ChapterOptions)
    chapter_name_policy: ChapterNamePolicy = "source"
    tags: TagSettings = Field(default_factory=TagSettings)
    """Tag templates (they may use naming variables)."""
    naming: NamingOptions | None = None
    """``None`` = the naming options from Settings → Output."""
