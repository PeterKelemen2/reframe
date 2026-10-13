"""Audio and subtitle defaults stored in a preset (03 §Audio defaults, §Subtitles; C-12).

Three parts: **which tracks** (:class:`TrackSelection`), **how to encode them**
(:class:`AudioCodecRule` list, first match wins) and **passthru** (:class:`PassthruPolicy`).
The defaults below are the "Default" column of 03's tables.
"""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import Field, field_validator

from reframe.models.base import (
    DocumentModel,
    LanguageTag,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveInt,
    ReframeModel,
)
from reframe.models.job import AudioOutputTrack, LoudnessTarget, SubtitleOutputTrack

__all__ = [
    "AudioCodecRule",
    "AudioDefaults",
    "AudioRuleExtras",
    "BurnInBehaviour",
    "ExtraAudioOutput",
    "PassthruCodec",
    "PassthruPolicy",
    "RuleMixdown",
    "SourceChannels",
    "SubtitleDefaults",
    "TrackDecision",
    "TrackDraft",
    "TrackSelection",
    "check_catch_all",
    "default_codec_rules",
]

#: Codecs that can be passed through (03 §Audio defaults, part 3).
PassthruCodec = Literal["ac3", "eac3", "dts", "dtshd", "truehd", "aac", "mp3", "flac", "opus"]
ALL_PASSTHRU_CODECS: tuple[PassthruCodec, ...] = get_args(PassthruCodec)
#: Condition on the **source** track's channels.
SourceChannels = Literal["any", "mono", "stereo_or_less", "5.1_or_more", "7.1_or_more"]
#: ``up_to_5.1`` only downmixes 7.1; ``keep`` keeps the source layout.
RuleMixdown = Literal["keep", "up_to_5.1", "5.1", "stereo", "dpl2", "mono"]
BurnInBehaviour = Literal["none", "foreign_audio", "first", "foreign_audio_then_first"]


class TrackSelection(DocumentModel):
    """Which source tracks to take (03 §Audio defaults, part 1). Shared by audio and subtitle
    defaults; :class:`SubtitleDefaults` uses other default values.

    ``languages`` ``None`` = the preferred languages from Settings (audio or subtitle).
    """

    languages: list[LanguageTag] | None = None
    tracks_per_language: Literal["none", "first", "all"] = "first"
    tie_break: Literal["source_order", "most_channels", "best_quality"] = "best_quality"
    """If a language has several tracks. ``best_quality``: lossless first, then the highest
    bit rate."""
    undetermined: Literal["first_language", "other"] = "other"
    """``und`` tracks: treat as the first listed language, or as an other language."""
    other_languages: Literal["drop", "keep_first", "keep_all"] = "drop"
    no_match: Literal["default_flagged", "first_track", "none"] = "default_flagged"
    """No listed language found. ``none`` = take none (a validation error for audio)."""
    commentary: Literal["drop", "keep_after_main"] = "drop"
    """Commentary and audio description tracks."""
    order: Literal["language_list", "source"] = "language_list"
    default_track: Literal["first_output", "first_in_first_language", "forced", "none"] = (
        "first_output"
    )
    """``forced`` is meant for subtitles (03 §Subtitles: none / first output / forced)."""


class ExtraAudioOutput(DocumentModel):
    """An extra output for the same source track (HandBrake's per-rule encoder list), for
    example an AAC stereo track for compatibility."""

    codec: str
    mixdown: RuleMixdown = "stereo"
    bitrate: PositiveInt | None = None


class AudioRuleExtras(DocumentModel):
    """The optional settings of a codec rule (the expanded row in 03)."""

    samplerate: PositiveInt | None = None
    gain: float = 0.0
    drc: NonNegativeFloat = 0.0
    loudness: LoudnessTarget = "off"
    name_template: str | None = None
    """``{lang_native} {channels}`` → ``Magyar 5.1``."""
    first_track_of_language_only: bool = False
    extra_outputs: list[ExtraAudioOutput] = Field(default_factory=list)


class AudioCodecRule(DocumentModel):
    """One row of the codec-rule table. Rules are checked top to bottom; the first that
    matches a selected track wins.

    ``languages`` ``None`` = any language; ``codec`` is an encoder id or ``"passthru"``;
    ``max_bitrate`` is in kb/s (``None`` for lossless encoders such as FLAC) and snaps to the
    encoder's allowed values. A rule with ``languages=None`` and ``source_channels="any"`` is
    a **catch-all**.
    """

    languages: list[LanguageTag] | None = None
    source_channels: SourceChannels = "any"
    codec: str = "aac"
    mixdown: RuleMixdown = "keep"
    max_bitrate: PositiveInt | None = None
    if_fits: Literal["passthru", "reencode"] = "passthru"
    extras: AudioRuleExtras = Field(default_factory=AudioRuleExtras)

    @property
    def is_catch_all(self) -> bool:
        return self.languages is None and self.source_channels == "any"


def check_catch_all(rules: list[AudioCodecRule]) -> list[AudioCodecRule]:
    """The rule list must end with a catch-all rule (Any / Any). Used by the validators."""
    if not rules:
        raise ValueError("there must be at least one codec rule (the catch-all)")
    if not rules[-1].is_catch_all:
        raise ValueError(
            "the last codec rule must be the catch-all (languages=None, source_channels='any')"
        )
    return rules


def default_codec_rules() -> list[AudioCodecRule]:
    """The single catch-all rule of a new preset: anything → AAC, up to 5.1, 256 kb/s."""
    return [AudioCodecRule(codec="aac", mixdown="up_to_5.1", max_bitrate=256)]


class PassthruPolicy(DocumentModel):
    """Allowed passthru codecs and the fallback encoder (03 §Audio defaults, part 3)."""

    allowed: list[PassthruCodec] = Field(default_factory=lambda: list(ALL_PASSTHRU_CODECS))
    fallback_encoder: str = "aac"
    """Used when a rule says passthru but the codec is not allowed or the container cannot
    hold it."""


class AudioDefaults(DocumentModel):
    """``AudioDefaults(selection, codec_rules, passthru)``. The last codec rule is always the
    catch-all; the model enforces it."""

    selection: TrackSelection = Field(default_factory=TrackSelection)
    codec_rules: list[AudioCodecRule] = Field(default_factory=default_codec_rules)
    passthru: PassthruPolicy = Field(default_factory=PassthruPolicy)

    @field_validator("codec_rules")
    @classmethod
    def _catch_all_last(cls, rules: list[AudioCodecRule]) -> list[AudioCodecRule]:
        return check_catch_all(rules)


def _subtitle_selection() -> TrackSelection:
    return TrackSelection(no_match="none", default_track="none")


class SubtitleDefaults(DocumentModel):
    """Subtitle defaults: the same selection part as audio (other defaults: no match → none,
    no default track), plus foreign audio search and burn-in behaviour (HandBrake parity)."""

    selection: TrackSelection = Field(default_factory=_subtitle_selection)
    foreign_audio_search: bool = False
    burn_in: BurnInBehaviour = "none"


# --------------------------------------------------------------------------- results (C-12)


class TrackDecision(ReframeModel):
    """What the audio defaults did with one source audio track, and why: one row of the live
    preview (03 §Audio defaults → Live preview) and of ``explain`` (C-12).

    Built by ``reframe.batch.apply_codec_rules``. In M2 every source track is taken (no
    selection stage, decision 0018), so a decision only describes the codec-rule stage.
    """

    source_stream: NonNegativeInt
    """Absolute stream index of the source audio track."""
    rule: PositiveInt | None = None
    """The codec rule that matched, 1-based (the ``#`` column); ``None`` when none matched."""
    outputs: list[AudioOutputTrack] = Field(default_factory=list)
    """The output track(s): the rule's output, then its extra outputs. Empty when no rule
    matched."""
    reason: str
    """Why, in one line: ``AC-3, 5.1, 224 ≤ 320: passthru``,
    ``Lossless source → encode at the max``,
    ``Rule 2 needs 5.1 or more. Rule 3 matches, and the source fits``."""
    notes: list[str] = Field(default_factory=list)
    """Details that do not change the outcome: a snapped bitrate or sample rate, a downmix
    forced by the encoder, the extra outputs."""
    measure: bool = False
    """The source bit rate is unknown and decided the outcome: the preview offers
    **Measure** (a packet-size scan, C-10)."""


class TrackDraft(ReframeModel):
    """The output tracks drafted for a source from a template (``reframe.batch.draft_tracks``;
    decision 0018): every audio track through the codec rules, every subtitle copied."""

    audio: list[AudioOutputTrack] = Field(default_factory=list)
    subtitles: list[SubtitleOutputTrack] = Field(default_factory=list)
    decisions: list[TrackDecision] = Field(default_factory=list)
    """One per source audio track, in source order."""
