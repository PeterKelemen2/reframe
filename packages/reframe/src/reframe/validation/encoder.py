"""Encoder rules: an encoder that is unknown or unavailable, and settings it cannot take.

They cover the video encoder and every audio encoder that runs.
"""

from __future__ import annotations

from collections.abc import Iterator

from reframe.capabilities import encoder_issues
from reframe.models.capabilities import CapabilitySnapshot
from reframe.models.issues import ValidationIssue
from reframe.models.job import AudioOutputTrack
from reframe.models.media import AudioStream
from reframe.validation.context import JobContext, TemplateContext
from reframe.validation.registry import job_rule, shared_rule, template_rule
from reframe.validation.tracks import switch_audio_encoder, track_encoder, track_stream
from reframe.validation.video import (
    video_availability_issues,
    video_bit_depth_issues,
    video_choice_issues,
    video_fast_decode_issues,
    video_option_issues,
    video_rate_control_issues,
    video_x26x_rule_issues,
)

AVAILABILITY_CODES = (
    "encoder.unknown",
    "encoder.checking",
    "encoder.untested",
    "encoder.unavailable",
)
SETTING_CODES = (
    "encoder.no_10bit",
    "encoder.checking",  # a cached "no 10-bit" that detection checks again
    "encoder.lookahead_too_short",
    "encoder.subme_needs_trellis",
    "encoder.preset_unsupported",
    "encoder.tune_unsupported",
    "encoder.profile_unsupported",
    "encoder.level_unsupported",
    "encoder.option_unknown",
    "encoder.option_unsupported",
    "encoder.option_invalid",
    "encoder.rate_control_unsupported",
    "encoder.quality_out_of_range",
    "encoder.bitrate_out_of_range",
    "encoder.two_pass_unsupported",
    "encoder.fast_decode_unsupported",
    "encoder.fast_decode_tune_conflict",
)


def audio_encoder_issues(
    encoder_id: str,
    path: str,
    caps: CapabilitySnapshot,
    ctx: JobContext | TemplateContext,
    *,
    track: AudioOutputTrack | None = None,
    stream: AudioStream | None = None,
) -> list[ValidationIssue]:
    """The encoder issues for an audio encoder at ``path``. The closest-match fix also snaps the
    job track's bitrate to the new encoder's values."""
    return encoder_issues(
        encoder_id,
        caps,
        ctx.definitions,
        path=path,
        subject=ctx.subject,
        fix_ops=lambda new: (
            switch_audio_encoder(
                path,
                ctx.definitions.audio_encoders[new],
                ctx.definitions,
                track=track,
                stream=stream,
            ),
            None,
        ),
    )


@shared_rule("encoder", *AVAILABILITY_CODES)
def video_encoder(ctx: JobContext | TemplateContext) -> list[ValidationIssue]:
    video = ctx.doc.video
    if video.passthrough:
        return []
    return video_availability_issues(video, ctx.caps, ctx.definitions, subject=ctx.subject)


@shared_rule("encoder", *SETTING_CODES)
def video_encoder_settings(ctx: JobContext | TemplateContext) -> Iterator[ValidationIssue]:
    video = ctx.doc.video
    if video.passthrough:
        return
    yield from video_bit_depth_issues(video, ctx.caps, ctx.definitions)
    yield from video_choice_issues(video, ctx.caps, ctx.definitions)
    yield from video_option_issues(video, ctx.caps, ctx.definitions)
    yield from video_rate_control_issues(video, ctx.definitions)
    yield from video_fast_decode_issues(video, ctx.definitions)
    yield from video_x26x_rule_issues(video, ctx.definitions)


@job_rule("encoder", *AVAILABILITY_CODES)
def audio_encoders(ctx: JobContext) -> Iterator[ValidationIssue]:
    """Every audio encoder that runs: encoded tracks, and passthru tracks whose source codec
    the container cannot hold (their fallback encoder)."""
    for index, track in enumerate(ctx.job.audio):
        encoder_id = track_encoder(ctx, track)
        if encoder_id is None:
            continue
        yield from audio_encoder_issues(
            encoder_id,
            f"audio[{index}].encoder",
            ctx.caps,
            ctx,
            track=track,
            stream=track_stream(ctx, track),
        )


def template_audio_encoder_ids(ctx: TemplateContext) -> Iterator[tuple[str, str]]:
    """``(path, encoder id)`` of every audio encoder a template names: the codec rules and
    their extra outputs, the passthru fallback, and explicit encode rules."""
    defaults = ctx.template.audio_defaults
    for index, rule in enumerate(defaults.codec_rules):
        if rule.codec != "passthru":
            yield f"audio_defaults.codec_rules[{index}].codec", rule.codec
        for extra_index, extra in enumerate(rule.extras.extra_outputs):
            yield (
                f"audio_defaults.codec_rules[{index}].extras.extra_outputs[{extra_index}].codec",
                extra.codec,
            )
    yield "audio_defaults.passthru.fallback_encoder", defaults.passthru.fallback_encoder
    for index, track_rule in enumerate(ctx.template.audio_rules):
        settings = track_rule.settings
        if settings.kind == "audio" and settings.encoder is not None:
            yield f"audio_rules[{index}].settings.encoder", settings.encoder


@template_rule("encoder", *AVAILABILITY_CODES)
def template_audio_encoders(ctx: TemplateContext) -> Iterator[ValidationIssue]:
    for path, encoder_id in template_audio_encoder_ids(ctx):
        yield from audio_encoder_issues(encoder_id, path, ctx.caps, ctx)
