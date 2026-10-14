"""Encoder rules (05 §C-8 "Encoder"): unknown, checking, unavailable (with the closest-match
fix, quality converted), 10-bit, speed preset / tune / profile / level, advanced options
this build does not support, rate control. For the video encoder and every audio encoder that
runs."""

from __future__ import annotations

from collections.abc import Iterator

from reframe.capabilities import encoder_issues
from reframe.models.capabilities import CapabilitySnapshot
from reframe.models.issues import Fix, FixTarget, ReplaceOp, ValidationIssue
from reframe.models.job import AudioOutputTrack
from reframe.models.media import AudioStream
from reframe.validation.context import JobContext, TemplateContext
from reframe.validation.registry import job_rule, template_rule
from reframe.validation.tracks import switch_audio_encoder, track_encoder, track_stream
from reframe.validation.video import (
    video_availability_issues,
    video_bit_depth_issues,
    video_choice_issues,
    video_fast_decode_issues,
    video_option_issues,
    video_rate_control_issues,
)

AVAILABILITY_CODES = (
    "encoder.unknown",
    "encoder.checking",
    "encoder.untested",
    "encoder.unavailable",
)
SETTING_CODES = (
    "encoder.no_10bit",
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
    target: FixTarget = "job",
) -> list[ValidationIssue]:
    """C-4's issues for an audio encoder at ``path``; the closest-match fix (``libfdk_aac →
    aac``, decision 0020) also snaps the job track's bitrate to the new encoder's values."""
    result: list[ValidationIssue] = []
    for issue in encoder_issues(
        encoder_id, caps, ctx.definitions, path=path, target=target, subject=ctx.subject
    ):
        fixes: list[Fix] = []
        for old in issue.fixes:
            first = old.patch[0]
            new = (
                ctx.definitions.audio_encoders.get(first.value)
                if isinstance(first, ReplaceOp) and isinstance(first.value, str)
                else None
            )
            if new is None:  # pragma: no cover - C-4 makes only replace fixes
                fixes.append(old)
                continue
            ops = switch_audio_encoder(path, new, ctx.definitions, track=track, stream=stream)
            fixes.append(old.model_copy(update={"patch": ops}))
        result.append(issue.model_copy(update={"fixes": fixes}))
    return result


# --------------------------------------------------------------------------- job


@job_rule("encoder", *AVAILABILITY_CODES)
def video_encoder(ctx: JobContext) -> list[ValidationIssue]:
    if ctx.job.video.passthrough:
        return []
    return video_availability_issues(
        ctx.job.video, ctx.caps, ctx.definitions, target=ctx.target, subject=ctx.subject
    )


@job_rule("encoder", *SETTING_CODES)
def video_encoder_settings(ctx: JobContext) -> Iterator[ValidationIssue]:
    video = ctx.job.video
    if video.passthrough:
        return
    yield from video_bit_depth_issues(video, ctx.caps, ctx.definitions, target=ctx.target)
    yield from video_choice_issues(video, ctx.caps, ctx.definitions, target=ctx.target)
    yield from video_option_issues(video, ctx.caps, ctx.definitions, target=ctx.target)
    yield from video_rate_control_issues(video, ctx.definitions, target=ctx.target)
    yield from video_fast_decode_issues(video, ctx.definitions, target=ctx.target)


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
            target=ctx.target,
        )


# --------------------------------------------------------------------------- template


@template_rule("encoder", *AVAILABILITY_CODES)
def template_video_encoder(ctx: TemplateContext) -> list[ValidationIssue]:
    video = ctx.template.video
    if video.passthrough:
        return []
    return video_availability_issues(
        video, ctx.caps, ctx.definitions, target=ctx.target, subject=ctx.subject
    )


@template_rule("encoder", *SETTING_CODES)
def template_video_settings(ctx: TemplateContext) -> Iterator[ValidationIssue]:
    video = ctx.template.video
    if video.passthrough:
        return
    yield from video_bit_depth_issues(video, ctx.caps, ctx.definitions, target=ctx.target)
    yield from video_choice_issues(video, ctx.caps, ctx.definitions, target=ctx.target)
    yield from video_option_issues(video, ctx.caps, ctx.definitions, target=ctx.target)
    yield from video_rate_control_issues(video, ctx.definitions, target=ctx.target)
    yield from video_fast_decode_issues(video, ctx.definitions, target=ctx.target)


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
        yield from audio_encoder_issues(encoder_id, path, ctx.caps, ctx, target=ctx.target)
