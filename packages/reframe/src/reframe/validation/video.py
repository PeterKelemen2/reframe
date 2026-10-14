"""Checks of ``VideoSettings`` against the encoder definitions and this FFmpeg build.

Shared by the job rules and the template rules (a preset's ``video`` is the same model). Pure
helpers; ``encoder.py`` and ``container.py`` register them.
"""

from __future__ import annotations

from collections.abc import Sequence

from reframe.capabilities import encoder_issues
from reframe.definitions import (
    ChoiceSetting,
    ContainerDef,
    Definitions,
    EncoderOption,
    PresetDefault,
    VideoEncoderDef,
    convert_quality,
    mapping_supported,
    supported_presets,
)
from reframe.definitions.quality import round_to_step
from reframe.jsonpatch import format_pointer
from reframe.models.capabilities import CapabilitySnapshot, EncoderStatus
from reframe.models.issues import (
    AddOp,
    Fix,
    FixTarget,
    JsonPatchOp,
    RemoveOp,
    ReplaceOp,
    ValidationIssue,
)
from reframe.models.job import (
    AverageBitrate,
    ConstantQuality,
    Container,
    OptionValue,
    VideoSettings,
)
from reframe.validation.common import (
    SwitchContainer,
    containers_for,
    error,
    fix,
    info,
    replace,
    switch_container_fixes,
    usable_encoder,
    warning,
)

__all__ = [
    "switch_video_encoder",
    "ten_bit_patch",
    "video_availability_issues",
    "video_bit_depth_issues",
    "video_choice_issues",
    "video_container_issues",
    "video_option_issues",
    "video_rate_control_issues",
    "video_x26x_rule_issues",
]

_CHOICES: tuple[tuple[str, str, str], ...] = (
    # (VideoSettings field, VideoEncoderDef field, label)
    ("preset", "presets", "speed preset"),
    ("tune", "tunes", "tune"),
    ("profile", "profiles", "profile"),
    ("level", "levels", "level"),
)


def _status(caps: CapabilitySnapshot, encoder_id: str) -> EncoderStatus | None:
    """The detected status, ``None`` when the encoder is not listed (nothing known)."""
    return caps.encoders.get(encoder_id)


def _setting(encoder: VideoEncoderDef, field: str) -> ChoiceSetting | None:
    setting: ChoiceSetting | None = getattr(encoder, field)
    return setting


def _num(value: float) -> str:
    return f"{value:g}"


# --------------------------------------------------------------------------- switching


def switch_video_encoder(
    video: VideoSettings,
    new_id: str,
    definitions: Definitions,
    caps: CapabilitySnapshot | None = None,
) -> tuple[list[JsonPatchOp], str | None]:
    """The patch that switches ``video`` to the encoder ``new_id``, and a note on the quality.

    Besides the encoder it converts a constant-quality value to the new encoder's scale (C-6
    ``convert_quality``: approximate, 03 §Missing encoder behaviour), keeps the bitrate inside
    the new encoder's range, turns off 2-pass and 10-bit where the new encoder has none, resets
    a speed preset, tune, profile or level that the new encoder does not have, and drops
    advanced options it does not know. So the fix does not leave new errors behind.
    """
    old = definitions.video_encoders.get(video.encoder)
    new = definitions.video_encoders[new_id]
    ops: list[JsonPatchOp] = [replace("video.encoder", new_id)]
    note: str | None = None
    rc = video.rate_control
    new_quality, new_bitrate = new.rate_control.quality, new.rate_control.bitrate
    if isinstance(rc, ConstantQuality):
        old_quality = old.rate_control.quality if old is not None else None
        if new_quality is None:
            if new_bitrate is not None:
                ops.append(replace("video.rate_control", AverageBitrate().model_dump(mode="json")))
        elif old is not None and old_quality is not None:
            value = convert_quality(rc.value, old.id, new.id, definitions=definitions)
            ops.append(replace("video.rate_control.value", value))
            note = (
                f"quality {old_quality.label} {_num(rc.value)} → {new_quality.label} "
                f"{_num(value)}, approximate"
            )
        else:
            value = round_to_step(rc.value, new_quality)
            if value != rc.value:
                ops.append(replace("video.rate_control.value", value))
    elif new_bitrate is None:
        if new_quality is not None:
            ops.append(
                replace(
                    "video.rate_control",
                    ConstantQuality(value=new_quality.default).model_dump(mode="json"),
                )
            )
    else:
        kbps = min(max(rc.kbps, new_bitrate.min_kbps), new_bitrate.max_kbps)
        if kbps != rc.kbps:
            ops.append(replace("video.rate_control.kbps", kbps))
        if rc.two_pass and new_bitrate.two_pass is None:
            ops.append(replace("video.rate_control.two_pass", False))
            ops.append(replace("video.rate_control.turbo_first_pass", False))
    for field, def_field, _ in _CHOICES:
        value = getattr(video, field)
        setting = _setting(new, def_field)
        if value is not None and (setting is None or setting.get(value) is None):
            ops.append(replace(f"video.{field}", None))
    status = _status(caps, new_id) if caps is not None else None
    if video.bit_depth == 10 and _no_10bit_reason(new, status, rechecking=_rechecking(caps)):
        # Also what detection found (a GPU without 10-bit), not only the definition.
        ops.append(replace("video.bit_depth", 8))
        profiles = new.profiles
        choice = profiles.get(video.profile) if video.profile and profiles else None
        reset = replace("video.profile", None)
        depths = choice.bit_depths if choice is not None else None
        if depths is not None and 8 not in depths and reset not in ops:
            ops.append(reset)
    if video.fast_decode and new.fast_decode is None:
        ops.append(replace("video.fast_decode", False))
    kept = {key: value for key, value in video.advanced.items() if new.option(key) is not None}
    if kept != video.advanced:
        ops.append(replace("video.advanced", dict(kept)))
    return ops, note


def _switch_fix(
    video: VideoSettings,
    new_id: str,
    definitions: Definitions,
    target: FixTarget,
    *,
    closest: bool = False,
    caps: CapabilitySnapshot | None = None,
) -> Fix:
    """ "Use libx265 (closest match; quality CQ 27 → RF 23.6, approximate)"."""
    ops, note = switch_video_encoder(video, new_id, definitions, caps)
    details = [text for text in ("closest match" if closest else None, note) if text]
    label = f"Use {new_id}" + (f" ({'; '.join(details)})" if details else "")
    return fix(label, *ops, target=target)


# --------------------------------------------------------------------------- availability


def video_availability_issues(
    video: VideoSettings,
    caps: CapabilitySnapshot,
    definitions: Definitions,
    *,
    target: FixTarget = "job",
    subject: str | None = None,
) -> list[ValidationIssue]:
    """C-4's ``encoder_issues`` for the video encoder; the closest-match fix also converts
    the quality (and the rest, :func:`switch_video_encoder`)."""
    issues = encoder_issues(
        video.encoder, caps, definitions, path="video.encoder", target=target, subject=subject
    )
    result: list[ValidationIssue] = []
    for issue in issues:
        fixes: list[Fix] = []
        for old_fix in issue.fixes:
            first = old_fix.patch[0]
            if isinstance(first, ReplaceOp) and isinstance(first.value, str):
                fixes.append(
                    _switch_fix(video, first.value, definitions, target, closest=True, caps=caps)
                )
            else:  # pragma: no cover - C-4 makes only replace fixes
                fixes.append(old_fix)
        result.append(issue.model_copy(update={"fixes": fixes}))
    return result


# --------------------------------------------------------------------------- 10-bit


def _rechecking(caps: CapabilitySnapshot | None) -> bool:
    """A cached snapshot that detection is checking again (C-4): its results are not final."""
    return caps is not None and caps.from_cache and caps.detecting


def _no_10bit_reason(
    encoder: VideoEncoderDef, status: EncoderStatus | None, *, rechecking: bool = False
) -> str | None:
    """Why the encoder cannot encode 10-bit here; ``None`` when it can (or may: not tested,
    or a cached "no" that detection is checking again)."""
    if "10" not in encoder.pix_fmts:
        return "it has no 10-bit mode"
    if status is not None and status.supports_10bit is False and not rechecking:
        return status.reason_10bit or "the 10-bit test encode failed"
    return None


def _bit_depth_ops(video: VideoSettings, encoder: VideoEncoderDef, depth: int) -> list[JsonPatchOp]:
    """Set the bit depth; reset a profile that does not allow it (x265 ``main``, …)."""
    ops: list[JsonPatchOp] = [replace("video.bit_depth", depth)]
    profiles = encoder.profiles
    if video.profile is not None and profiles is not None:
        choice = profiles.get(video.profile)
        if choice is not None and choice.bit_depths is not None and depth not in choice.bit_depths:
            ops.append(replace("video.profile", None))
    return ops


def ten_bit_patch(
    video: VideoSettings, caps: CapabilitySnapshot, definitions: Definitions
) -> list[JsonPatchOp] | None:
    """The patch that switches ``video`` to 10-bit; ``None`` when its encoder cannot do it."""
    encoder = definitions.video_encoders.get(video.encoder)
    status = _status(caps, video.encoder)
    if encoder is None or _no_10bit_reason(encoder, status, rechecking=_rechecking(caps)):
        return None
    return _bit_depth_ops(video, encoder, 10)


def video_bit_depth_issues(
    video: VideoSettings,
    caps: CapabilitySnapshot,
    definitions: Definitions,
    *,
    target: FixTarget = "job",
) -> list[ValidationIssue]:
    """``encoder.no_10bit``: 10-bit output with an encoder (or a GPU) that cannot do it.

    A cached "no 10-bit" that detection is checking again (``from_cache`` and ``detecting``)
    is not final: ``encoder.checking`` (info), as C-4 does for the encoder status, so a
    caller waits for the new result before the job starts."""
    encoder = definitions.video_encoders.get(video.encoder)
    if encoder is None or video.bit_depth != 10:
        return []
    status = _status(caps, video.encoder)
    rechecking = _rechecking(caps)
    reason = _no_10bit_reason(encoder, status, rechecking=rechecking)
    if reason is None:
        if rechecking and status is not None and status.supports_10bit is False:
            last = status.reason_10bit or "the 10-bit test encode failed"
            return [
                info(
                    "encoder.checking",
                    "video.bit_depth",
                    f"10-bit with {encoder.label} is being checked again (last result: "
                    f"{last}). The job waits for the result before it starts.",
                )
            ]
        return []
    ops = _bit_depth_ops(video, encoder, 8)
    return [
        error(
            "encoder.no_10bit",
            "video.bit_depth",
            f"{encoder.label} cannot encode 10-bit: {reason}.",
            fix("Use 8-bit", *ops, target=target),
        )
    ]


# --------------------------------------------------------------------------- choices


def video_choice_issues(
    video: VideoSettings,
    caps: CapabilitySnapshot,
    definitions: Definitions,
    *,
    target: FixTarget = "job",
) -> list[ValidationIssue]:
    """``encoder.<preset|tune|profile|level>_unsupported``: a value the encoder (or this
    build) does not have. The fix resets it to the encoder's default."""
    encoder = definitions.video_encoders.get(video.encoder)
    if encoder is None:
        return []
    status = _status(caps, video.encoder)
    issues: list[ValidationIssue] = []
    for field, def_field, label in _CHOICES:
        value: str | None = getattr(video, field)
        if value is None:
            continue
        setting = _setting(encoder, def_field)
        problem: str | None = None
        if setting is None:
            problem = f"{encoder.label} has no {label} setting"
        elif setting.get(value) is None:
            problem = f"{value!r} is not a {label} of {encoder.label}"
        elif field == "preset" and value not in {
            c.value for c in supported_presets(encoder, status)
        }:
            problem = f"this FFmpeg build's {encoder.id} does not offer the {label} {value!r}"
        elif field == "profile" and value not in setting.values(video.bit_depth):
            problem = f"the profile {value!r} is not for {video.bit_depth}-bit output"
        if problem is not None:
            issues.append(
                error(
                    f"encoder.{field}_unsupported",
                    f"video.{field}",
                    f"{problem[0].upper()}{problem[1:]}.",
                    fix(
                        f"Use the encoder's default {label}",
                        replace(f"video.{field}", None),
                        target=target,
                    ),
                )
            )
    return issues


# --------------------------------------------------------------------------- options


def _value_problem(option: EncoderOption, value: OptionValue) -> str | None:
    if option.type == "bool":
        return None if isinstance(value, bool) else "must be on or off"
    if option.type in ("int", "float"):
        if isinstance(value, bool) or not isinstance(value, int | float):
            return "must be a number"
        if option.type == "int" and not float(value).is_integer():
            return "must be a whole number"
        if option.min is not None and value < option.min:
            return f"is below the minimum {_num(option.min)}"
        if option.max is not None and value > option.max:
            return f"is above the maximum {_num(option.max)}"
        return None
    if not isinstance(value, str):
        return "must be text"
    if option.type == "enum" and option.choices is not None:
        allowed = [c.value for c in option.choices]
        if value not in allowed:
            return f"must be one of {', '.join(allowed)}"
    return None


def video_option_issues(
    video: VideoSettings,
    caps: CapabilitySnapshot,
    definitions: Definitions,
    *,
    target: FixTarget = "job",
) -> list[ValidationIssue]:
    """Advanced options: unknown to the encoder, not supported by this build (C-6
    ``supported_options``), or a bad value. The fix removes the option (back to the
    default)."""
    encoder = definitions.video_encoders.get(video.encoder)
    if encoder is None:
        return []
    status = _status(caps, video.encoder)
    issues: list[ValidationIssue] = []
    for key, value in video.advanced.items():
        path = f"video.advanced.{key}"
        reset = fix(
            f"Reset {key} to its default",
            RemoveOp(path=format_pointer(["video", "advanced", key])),
            target=target,
        )
        option = encoder.option(key)
        if option is None:
            issues.append(
                error(
                    "encoder.option_unknown",
                    path,
                    f"{encoder.label} has no advanced option {key!r}.",
                    reset,
                )
            )
        elif not mapping_supported(encoder, option.mapping, status):
            issues.append(
                error(
                    "encoder.option_unsupported",
                    path,
                    f"{option.label} ({key}) is not supported by this FFmpeg build's {encoder.id}.",
                    reset,
                )
            )
        else:
            problem = _value_problem(option, value)
            if problem is not None:
                issues.append(
                    error(
                        "encoder.option_invalid",
                        path,
                        f"{option.label} ({key}) {problem}: {value!r}.",
                        reset,
                    )
                )
    return issues


# --------------------------------------------------------------------------- rate control


def video_rate_control_issues(
    video: VideoSettings,
    definitions: Definitions,
    *,
    target: FixTarget = "job",
) -> list[ValidationIssue]:
    """Rate control that the encoder does not have, or a value outside its range."""
    encoder = definitions.video_encoders.get(video.encoder)
    if encoder is None:
        return []
    rc = video.rate_control
    quality, bitrate = encoder.rate_control.quality, encoder.rate_control.bitrate
    issues: list[ValidationIssue] = []
    if isinstance(rc, ConstantQuality):
        if quality is None:
            fixes = (
                [
                    fix(
                        "Use average bitrate",
                        replace("video.rate_control", AverageBitrate().model_dump(mode="json")),
                        target=target,
                    )
                ]
                if bitrate is not None
                else []
            )
            issues.append(
                error(
                    "encoder.rate_control_unsupported",
                    "video.rate_control",
                    f"{encoder.label} has no constant-quality mode.",
                    *fixes,
                )
            )
        elif not quality.min <= rc.value <= quality.max:
            snapped = round_to_step(rc.value, quality)
            issues.append(
                error(
                    "encoder.quality_out_of_range",
                    "video.rate_control.value",
                    f"{quality.label} {_num(rc.value)} is outside {encoder.label}'s range "
                    f"{_num(quality.min)} to {_num(quality.max)}.",
                    fix(
                        f"Use {quality.label} {_num(snapped)}",
                        replace("video.rate_control.value", snapped),
                        target=target,
                    ),
                )
            )
        return issues
    if bitrate is None:
        fixes = (
            [
                fix(
                    "Use constant quality",
                    replace(
                        "video.rate_control",
                        ConstantQuality(value=quality.default).model_dump(mode="json"),
                    ),
                    target=target,
                )
            ]
            if quality is not None
            else []
        )
        issues.append(
            error(
                "encoder.rate_control_unsupported",
                "video.rate_control",
                f"{encoder.label} has no average-bitrate mode.",
                *fixes,
            )
        )
        return issues
    if not bitrate.min_kbps <= rc.kbps <= bitrate.max_kbps:
        clamped = min(max(rc.kbps, bitrate.min_kbps), bitrate.max_kbps)
        issues.append(
            error(
                "encoder.bitrate_out_of_range",
                "video.rate_control.kbps",
                f"{rc.kbps} kb/s is outside {encoder.label}'s range "
                f"{bitrate.min_kbps} to {bitrate.max_kbps} kb/s.",
                fix(
                    f"Use {clamped} kb/s",
                    replace("video.rate_control.kbps", clamped),
                    target=target,
                ),
            )
        )
    if rc.two_pass and bitrate.two_pass is None:
        issues.append(
            error(
                "encoder.two_pass_unsupported",
                "video.rate_control.two_pass",
                f"{encoder.label} has no 2-pass mode.",
                fix(
                    "Use one pass",
                    replace("video.rate_control.two_pass", False),
                    replace("video.rate_control.turbo_first_pass", False),
                    target=target,
                ),
            )
        )
    return issues


def _option_value(
    video: VideoSettings, encoder: VideoEncoderDef, key: str, *, tune_known: bool = False
) -> tuple[OptionValue | None, bool]:
    """The value x264 / x265 use for the advanced option ``key``, and whether the job sets
    it: the job's value, else the speed preset's default (C-6's per-preset tables; the
    encoder's default preset when none is set). ``None`` when the default depends on the
    job's tune (the table does not say) or is not known; ``tune_known``: the caller applies
    the tune itself and gets the preset's value."""
    if key in video.advanced:
        return video.advanced[key], True
    option = encoder.option(key)
    if option is None or option.default.kind != "preset":
        return None, False
    default = option.default
    assert isinstance(default, PresetDefault)
    if video.tune is not None and video.tune in default.tunes and not tune_known:
        return None, False
    preset = video.preset or (encoder.presets.default if encoder.presets else None)
    return (default.values.get(preset) if preset is not None else None), False


def _set_option(key: str, value: OptionValue, target: FixTarget, label: str) -> Fix:
    return fix(
        label, AddOp(path=format_pointer(["video", "advanced", key]), value=value), target=target
    )


def video_x26x_rule_issues(
    video: VideoSettings, definitions: Definitions, *, target: FixTarget = "job"
) -> list[ValidationIssue]:
    """Rules across two advanced options, checked with the real encoders
    (testdata/README.md "Validation (C-8)"):

    - ``encoder.lookahead_too_short`` (error): x265 stops with "Lookahead depth must be
      greater than the max consecutive bframe count" when ``rc-lookahead`` is not above
      ``bframes`` (0 works only with ``bframes`` 0). The ``animation`` tune adds 2 to the
      preset's B-frames and ``zerolatency`` sets both to 0; options the job sets win over
      the tune.
    - ``encoder.subme_needs_trellis`` (warning): x264 uses ``subme`` 9 instead of 10 or 11
      unless ``trellis`` is 2 (also the ``veryslow`` / ``placebo`` presets with trellis 0
      or 1), without a message.
    """
    encoder = definitions.video_encoders.get(video.encoder)
    if encoder is None:
        return []
    issues: list[ValidationIssue] = []
    if encoder.id == "libx265":
        bframes, bframes_set = _option_value(video, encoder, "bframes", tune_known=True)
        lookahead, lookahead_set = _option_value(video, encoder, "rc-lookahead", tune_known=True)
        if video.tune == "zerolatency":
            bframes = bframes if bframes_set else 0
            lookahead = lookahead if lookahead_set else 0
        elif video.tune == "animation" and not bframes_set and isinstance(bframes, int):
            bframes = min(bframes + 2, 16)
        if (
            isinstance(bframes, int)
            and isinstance(lookahead, int)
            and lookahead <= bframes
            and not (lookahead == 0 and bframes == 0)
        ):
            fixes = [
                _set_option("rc-lookahead", bframes + 1, target, f"Look ahead {bframes + 1} frames")
            ]
            if lookahead >= 1:
                fixes.append(
                    _set_option("bframes", lookahead - 1, target, f"Use {lookahead - 1} B-frames")
                )
            else:
                fixes.append(_set_option("bframes", 0, target, "Use no B-frames"))
            issues.append(
                error(
                    "encoder.lookahead_too_short",
                    "video.advanced.rc-lookahead",
                    f"x265 needs a lookahead longer than the B-frames: rc-lookahead {lookahead} "
                    f"with {bframes} B-frames stops the encoder.",
                    *fixes,
                )
            )
    if encoder.id == "libx264":
        subme, _ = _option_value(video, encoder, "subme")
        trellis, _ = _option_value(video, encoder, "trellis")
        if isinstance(subme, int) and subme >= 10 and trellis is not None and str(trellis) != "2":
            issues.append(
                warning(
                    "encoder.subme_needs_trellis",
                    "video.advanced.subme",
                    f"x264 uses subme {subme} only with trellis 2: with trellis {trellis} it "
                    "uses subme 9.",
                    _set_option("trellis", "2", target, "Set trellis 2"),
                    _set_option("subme", 9, target, "Use subme 9"),
                )
            )
    return issues


def video_fast_decode_issues(
    video: VideoSettings, definitions: Definitions, *, target: FixTarget = "job"
) -> list[ValidationIssue]:
    """``encoder.fast_decode_unsupported`` (warning): the setting would be ignored.
    ``encoder.fast_decode_tune_conflict`` (error): fast decode is a tune of an encoder that
    takes one tune only (x265), and the job sets another tune; the command builder refuses
    it (decision 0013)."""
    encoder = definitions.video_encoders.get(video.encoder)
    if encoder is None or not video.fast_decode:
        return []
    fast = encoder.fast_decode
    if fast is not None:
        if fast.tune is None or fast.combines_with_tune or video.tune is None:
            return []
        return [
            error(
                "encoder.fast_decode_tune_conflict",
                "video.fast_decode",
                f"{encoder.label} takes one tune: fast decode ({fast.tune}) cannot be combined "
                f"with the tune {video.tune!r}.",
                fix("Turn off fast decode", replace("video.fast_decode", False), target=target),
                fix("Remove the tune", replace("video.tune", None), target=target),
            )
        ]
    return [
        warning(
            "encoder.fast_decode_unsupported",
            "video.fast_decode",
            f"{encoder.label} has no fast-decode setting: it is ignored.",
            fix("Turn off fast decode", replace("video.fast_decode", False), target=target),
        )
    ]


# --------------------------------------------------------------------------- container


def _convert_candidates(
    video: VideoSettings,
    allowed_codecs: list[str],
    caps: CapabilitySnapshot,
    definitions: Definitions,
) -> list[str]:
    """Encoders of an allowed codec that a fix may switch to: the same family (vendor) first,
    then software encoders, in definition order. At most one per codec."""
    current = definitions.video_encoders.get(video.encoder)
    family = current.family if current is not None else "software"
    ranked = sorted(
        definitions.video_encoders.values(),
        key=lambda e: (e.family != family, e.hardware),
    )
    chosen: list[str] = []
    codecs: set[str] = set()
    for encoder in ranked:
        if (
            encoder.codec in allowed_codecs
            and encoder.codec not in codecs
            and usable_encoder(encoder.id, caps)
        ):
            chosen.append(encoder.id)
            codecs.add(encoder.codec)
    return chosen


def _encode_fix(
    video: VideoSettings,
    container: ContainerDef,
    caps: CapabilitySnapshot,
    definitions: Definitions,
    target: FixTarget,
) -> Fix:
    """ "Encode the video": turn off passthrough, and switch to an encoder the container
    holds when the job's encoder cannot go into it."""
    ops: list[JsonPatchOp] = [replace("video.passthrough", False)]
    encoder = definitions.video_encoders.get(video.encoder)
    if encoder is not None and encoder.codec not in container.video.encode:
        candidates = _convert_candidates(video, container.video.encode, caps, definitions)
        if candidates:
            ops += switch_video_encoder(video, candidates[0], definitions, caps)[0]
            return fix(f"Encode the video with {candidates[0]}", *ops, target=target)
    return fix("Encode the video", *ops, target=target)


def video_container_issues(
    video: VideoSettings,
    container_id: Container,
    caps: CapabilitySnapshot,
    definitions: Definitions,
    *,
    source_codec: str | None = None,
    target: FixTarget = "job",
    switch: SwitchContainer | None = None,
    passthrough_known: bool = False,
) -> list[ValidationIssue]:
    """``container.codec_unsupported`` for the video track: the encoder's codec (or, for
    passthrough, the source codec) cannot go into the container. Fixes: another encoder,
    another container, or (passthrough) encode the video (with an encoder the container
    holds).

    ``passthrough_known``: a job (the source is known), where a source codec that ffprobe
    could not name cannot be copied either (the command builder refuses it). A template has
    no source and is not checked for passthrough."""

    def switch_to(allowed: Sequence[Container]) -> list[Fix]:
        if switch is not None:
            return switch(allowed)
        return switch_container_fixes(allowed, container_id, definitions, target=target)

    container = definitions.containers.get(container_id)
    if container is None:
        return []
    if video.passthrough:
        if source_codec is None and not passthrough_known:
            return []
        if source_codec is not None and container.video.can_copy(source_codec):
            return []
        fixes = (
            switch_to(containers_for(definitions, "video", source_codec, copy=True))
            if source_codec is not None
            else []
        )
        fixes.append(_encode_fix(video, container, caps, definitions, target))
        what = f"{source_codec} video" if source_codec is not None else "video of an unknown codec"
        return [
            error(
                "container.codec_unsupported",
                "video.passthrough",
                f"{container.label} cannot hold {what}: it cannot be passed through.",
                *fixes,
            )
        ]
    encoder = definitions.video_encoders.get(video.encoder)
    if encoder is None or encoder.codec in container.video.encode:
        return []
    fixes = [
        _switch_fix(video, candidate, definitions, target, caps=caps)
        for candidate in _convert_candidates(video, container.video.encode, caps, definitions)
    ]
    fixes.extend(switch_to(containers_for(definitions, "video", encoder.codec)))
    return [
        error(
            "container.codec_unsupported",
            "video.encoder",
            f"{container.label} cannot hold {encoder.codec_label} video ({encoder.label}).",
            *fixes,
        )
    ]
