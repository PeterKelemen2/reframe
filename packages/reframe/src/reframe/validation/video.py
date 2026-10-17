"""Checks of ``VideoSettings`` against the encoder definitions and this FFmpeg build.

Shared by the job rules and the template rules (a preset's ``video`` is the same model). Pure
helpers; ``encoder.py`` and ``container.py`` register them.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from reframe.capabilities import encoder_issues
from reframe.definitions import (
    ChoiceSetting,
    Condition,
    ContainerDef,
    Definitions,
    EncoderOption,
    PresetDefault,
    VideoEncoderDef,
    convert_quality,
    describe_condition,
    mapping_supported,
    option_context,
    option_default,
    supported_presets,
    unmet_conditions,
)
from reframe.definitions.custom_params import (
    CustomParam,
    custom_param_rules,
    dict_pairs,
    file_key,
    library_key_forms,
    own_option_allowed,
    split_custom_params,
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
    "CUSTOM_PARAM_CODES",
    "OPTION_RULE_CODES",
    "switch_video_encoder",
    "ten_bit_patch",
    "video_availability_issues",
    "video_bit_depth_issues",
    "video_choice_issues",
    "video_container_issues",
    "video_custom_param_issues",
    "video_option_issues",
    "video_option_rule_issues",
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
    advanced options it does not know or whose value it does not take (x264's colour matrix
    ``GBR`` is x265's ``gbr``). So the fix does not leave new errors behind.
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
    kept = {
        key: value
        for key, value in video.advanced.items()
        if (option := new.option(key)) is not None and _value_problem(option, value, new.id) is None
    }
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


#: What FFmpeg drops around a params-argument value (``av_get_token``): the HDR texts reach the
#: encoder without these, and with any other character kept (x265 cannot parse a text that
#: starts with a vertical tab, and SVT-AV1 never ends).
_FFMPEG_SPACE = " \n\t\r"
#: A number as x265 (``sscanf`` ``%hu`` / ``%u``) and SVT-AV1 read it: C white space (not a
#: no-break space), an optional sign, ASCII digits. ``+5`` is written as ``5`` and ``-0`` as
#: ``0``; another negative number wraps (x265 ``-1`` → 65535) or is changed (SVT-AV1 ``-0.265``
#: → 0.735), so the checks refuse it (decision 0035, final review RC-2).
_C_SPACE = "[ \t\n\v\f\r]*"
_UINT = rf"{_C_SPACE}([-+]?[0-9]+)"
_REAL = rf"{_C_SPACE}([-+]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?)"
_X265_MASTER_DISPLAY = re.compile(
    f"G\\({_UINT},{_UINT}\\)B\\({_UINT},{_UINT}\\)R\\({_UINT},{_UINT}\\)WP\\({_UINT},{_UINT}\\)L\\({_UINT},{_UINT}\\)"
)
_SVT_DISPLAY_TAG = re.compile(rf"(G|B|R|WP|L)\({_REAL},{_REAL}\)")
_LIGHT_LEVEL = re.compile(rf"{_UINT},{_UINT}")
_U16, _U32 = 0xFFFF, 0xFFFFFFFF
#: SVT-AV1 keeps the luminance in fixed point (24.8 / 18.14): beyond the PQ maximum of
#: 10000 cd/m² it overflows (L(10000000,1) was read as -1734967296/256).
_PQ_MAX = 10000.0


def _x265_master_display_problem(text: str) -> str | None:
    """x265 4.3 parses ``G(x,y)B(x,y)R(x,y)WP(x,y)L(max,min)`` with ``%hu`` and ``%u``: any
    other text writes no mastering display ("unable to parse mastering display color volume
    info", exit 0), and a number above 65535 wraps (70000 → 4464)."""
    found = _X265_MASTER_DISPLAY.fullmatch(text.strip(_FFMPEG_SPACE))
    expected = (
        "must be G(x,y)B(x,y)R(x,y)WP(x,y)L(max,min) with whole numbers: chromaticities in "
        "units of 0.00002 (0 to 50000), luminance in units of 0.0001 cd/m²"
    )
    if found is None:
        return expected
    numbers = [int(n) for n in found.groups()]
    if any(n < 0 for n in numbers):
        return expected
    if any(n > 50000 for n in numbers[:8]) or any(n > _U32 for n in numbers[8:]):
        return expected
    return None


def _svt_mastering_display_problem(text: str) -> str | None:
    """SVT-AV1 v4.2 reads the tags in any order; with other text FFmpeg never ends (any
    letters before or after the tags: checked, 15 s), without a tag it writes no mastering
    display, a chromaticity above 1 is clipped and a luminance above 8388607 cd/m² overflows."""
    expected = (
        "must be G(x,y)B(x,y)R(x,y)WP(x,y)L(max,min) with plain numbers: chromaticities from 0 "
        "to 1, luminance in cd/m² up to 10000"
    )
    stripped = text.strip(_FFMPEG_SPACE)
    tags = list(_SVT_DISPLAY_TAG.finditer(stripped))
    if "".join(m.group(0) for m in tags) != stripped:
        return expected
    names = sorted(m.group(1) for m in tags)
    if names != sorted(["G", "B", "R", "WP", "L"]):
        return expected
    for m in tags:
        values = (float(m.group(2)), float(m.group(3)))
        limit = _PQ_MAX if m.group(1) == "L" else 1.0
        if any(v < 0 or v > limit for v in values):
            return expected
    return None


def _light_level_problem(text: str) -> str | None:
    """x265 (``%hu,%hu``) and SVT-AV1: ``MaxCLL,MaxFALL``. x265 with one number writes MaxFALL
    0 ("Invalid value"), SVT-AV1 refuses one or three numbers ("Invalid cll provided"); a
    number above 65535 wraps (x265) or is clipped (SVT-AV1)."""
    found = _LIGHT_LEVEL.fullmatch(text.strip(_FFMPEG_SPACE))
    if found is None or any(not 0 <= int(n) <= _U16 for n in found.groups()):
        return "must be MaxCLL,MaxFALL: two whole numbers in cd/m² up to 65535"
    return None


#: Text options with a format the encoder parses (core-complete review R5-8, decision 0035).
_TEXT_FORMATS = {
    ("libx265", "master-display"): _x265_master_display_problem,
    ("libx265", "max-cll"): _light_level_problem,
    ("libsvtav1", "mastering-display"): _svt_mastering_display_problem,
    ("libsvtav1", "content-light"): _light_level_problem,
}


def _value_problem(
    option: EncoderOption, value: OptionValue, encoder_id: str | None = None
) -> str | None:
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
    text_format = _TEXT_FORMATS.get((encoder_id or "", option.key))
    if text_format is not None:
        return text_format(value)
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
            problem = _value_problem(option, value, encoder.id)
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


# --------------------------------------------------------------------------- option rules (M9)

OPTION_RULE_CODES = (
    "encoder.option_inactive",
    "encoder.option_ignored",
    "encoder.option_conflict",
)
"""The codes of :func:`video_option_rule_issues` (registered in ``validation/levels.py``)."""


def _option_pointer(key: str) -> str:
    return format_pointer(["video", "advanced", key])


def _remove_option(key: str, target: FixTarget, label: str | None = None) -> Fix:
    return fix(label or f"Remove {key}", RemoveOp(path=_option_pointer(key)), target=target)


def _value_label(option: EncoderOption, value: OptionValue) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    if option.choices is not None:
        found = next((c for c in option.choices if c.value == str(value)), None)
        if found is not None:
            return found.label
    return _num(value) if isinstance(value, int | float) else str(value)


def _condition_fix(condition: Condition, encoder: VideoEncoderDef, target: FixTarget) -> Fix | None:
    """ "Set SAO on": a fix that makes an ``option:<key>`` condition hold (``eq`` or ``in``);
    ``None`` for the other conditions (rate control, bit depth, "not …")."""
    if not condition.field.startswith("option:") or condition.op not in ("eq", "in"):
        return None
    key = condition.field.removeprefix("option:")
    other = encoder.option(key)
    if other is None:  # pragma: no cover - the linter checks the condition's option
        return None
    value = condition.value[0] if isinstance(condition.value, list) else condition.value
    return _set_option(key, value, target, f"Set {other.label} to {_value_label(other, value)}")


def _int(value: OptionValue | None) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except ValueError:
        return None


class _Options:
    """The advanced options of a job as the command builder writes them (C-7 skips an option
    of another encoder, one the build lacks, a bad value and an option whose ``requires``
    does not hold)."""

    def __init__(
        self, video: VideoSettings, encoder: VideoEncoderDef, status: EncoderStatus | None
    ) -> None:
        self.encoder = encoder
        self.context = option_context(encoder, video)
        preset = self.context.get("preset")
        self.preset = preset if isinstance(preset, str) else None
        self.written: dict[str, OptionValue] = {}
        self.inactive: dict[str, list[Condition]] = {}
        for key, value in video.advanced.items():
            option = encoder.option(key)
            if (
                option is None
                or not mapping_supported(encoder, option.mapping, status)
                or _value_problem(option, value, encoder.id) is not None
            ):
                continue  # video_option_issues reports these
            unmet = unmet_conditions(option, self.context)
            if unmet:
                self.inactive[key] = unmet
            else:
                self.written[key] = value

    def effective(self, key: str) -> OptionValue | None:
        """What the encoder uses: the written value, else the default."""
        if key in self.written:
            return self.written[key]
        option = self.encoder.option(key)
        return option_default(option, self.preset) if option is not None else None

    def label(self, key: str) -> str:
        option = self.encoder.option(key)
        return f"{option.label} ({key})" if option is not None else key


def _inactive_issues(opts: _Options, target: FixTarget) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    encoder = opts.encoder
    for key, unmet in opts.inactive.items():
        needs = " and ".join(describe_condition(c, encoder) for c in unmet)
        fixes = [_remove_option(key, target)]
        if len(unmet) == 1 and (set_fix := _condition_fix(unmet[0], encoder, target)):
            fixes.append(set_fix)
        issues.append(
            warning(
                "encoder.option_inactive",
                f"video.advanced.{key}",
                f"{opts.label(key)} is not written: it needs {needs}.",
                *fixes,
            )
        )
    return issues


def _vbv_rules(video: VideoSettings, opts: _Options, target: FixTarget) -> list[ValidationIssue]:
    """x264 core 165 and x265 4.3 use VBV only with a maximum rate and a buffer size: a
    maximum rate alone is dropped ("VBV maxrate specified, but no bufsize, ignored"; x264 with
    constant quality writes ``rc=crf`` and no VBV in its SEI), and so is a buffer alone with
    constant quality ("VBV bufsize set but maxrate unspecified, ignored"). With an average
    bitrate a buffer alone is used: the encoder takes the bitrate as the maximum ("VBV maxrate
    unspecified, assuming CBR"), so that is not reported."""
    maxrate, bufsize = (_int(opts.written.get(key)) or 0 for key in ("vbv-maxrate", "vbv-bufsize"))
    used_max, used_buf = (_int(opts.effective(key)) or 0 for key in ("vbv-maxrate", "vbv-bufsize"))
    name = opts.encoder.label
    issues: list[ValidationIssue] = []
    if maxrate > 0 and used_buf == 0:
        issues.append(
            warning(
                "encoder.option_inactive",
                "video.advanced.vbv-maxrate",
                f"{name} ignores {opts.label('vbv-maxrate')} without {opts.label('vbv-bufsize')}.",
                _remove_option("vbv-maxrate", target),
            )
        )
    if bufsize > 0 and used_max == 0 and isinstance(video.rate_control, ConstantQuality):
        issues.append(
            warning(
                "encoder.option_inactive",
                "video.advanced.vbv-bufsize",
                f"{name} ignores {opts.label('vbv-bufsize')} without "
                f"{opts.label('vbv-maxrate')} at a constant quality.",
                _remove_option("vbv-bufsize", target),
            )
        )
    return issues


def _x264_rules(opts: _Options, target: FixTarget) -> list[ValidationIssue]:
    """x264 core 165 lowers these with ``bluray-compat`` on, without a message."""
    if opts.effective("bluray-compat") is not True:
        return []
    limits: tuple[tuple[str, OptionValue, bool], ...] = (
        # (key, Blu-ray value, the job's value is above it)
        ("bframes", 3, (_int(opts.written.get("bframes")) or 0) > 3),
        ("weightp", "1", opts.written.get("weightp") == "2"),
        ("b-pyramid", "strict", opts.written.get("b-pyramid") == "normal"),
    )
    issues: list[ValidationIssue] = []
    for key, value, above in limits:
        if not above:
            continue
        option = opts.encoder.option(key)
        assert option is not None
        shown = _value_label(option, value)
        issues.append(
            warning(
                "encoder.option_ignored",
                f"video.advanced.{key}",
                f"With Blu-ray compatibility x264 uses {opts.label(key)} {shown}, not "
                f"{_value_label(option, opts.written[key])}.",
                _set_option(key, value, target, f"Use {shown}"),
                _remove_option(key, target),
            )
        )
    return issues


def _x265_rules(opts: _Options, target: FixTarget) -> list[ValidationIssue]:
    """x265 4.3: a minimum CU above the CTU stops the encoder; a TU size or quantisation
    group above the CTU is lowered to the CTU size with a warning; pmode turns limit-refs 2
    and 3 off with a warning."""
    ctu = _int(opts.effective("ctu"))
    if ctu is None:
        return []
    issues: list[ValidationIssue] = []
    # The presets' own minimum (8 or 16) never exceeds a CTU size: only a set value can.
    min_cu = _int(opts.written.get("min-cu-size"))
    if min_cu is not None and min_cu > ctu:
        issues.append(
            error(
                "encoder.option_conflict",
                "video.advanced.min-cu-size",
                f"x265 stops when the minimum CU size ({min_cu}) is larger than the CTU size "
                f"({ctu}).",
                _set_option("min-cu-size", str(ctu), target, f"Use min CU size {ctu}"),
                _remove_option("min-cu-size", target),
            )
        )
    limit_refs = opts.written.get("limit-refs")
    if opts.effective("pmode") is True and limit_refs in ("2", "3"):
        issues.append(
            warning(
                "encoder.option_ignored",
                "video.advanced.limit-refs",
                f"x265 turns limit references {limit_refs} off with parallel mode analysis "
                "(pmode).",
                _set_option("limit-refs", "1", target, "Use limit references 1"),
                _set_option("pmode", False, target, "Turn parallel mode analysis off"),
            )
        )
    for key, what in (("max-tu-size", "maximum TU size"), ("qg-size", "quantisation group")):
        size = _int(opts.written.get(key))
        if size is not None and size > ctu:
            issues.append(
                warning(
                    "encoder.option_ignored",
                    f"video.advanced.{key}",
                    f"x265 lowers the {what} {size} to the CTU size {ctu}.",
                    _set_option(key, str(ctu), target, f"Use {ctu}"),
                    _remove_option(key, target),
                )
            )
    return issues


def _svt_rules(opts: _Options, target: FixTarget) -> list[ValidationIssue]:
    """SVT-AV1 v4.2: forward keyframes (``irefresh-type=1``) force hierarchical levels 4
    ("Fwd key frame is only supported for hierarchical levels 4 at this point")."""
    levels = opts.written.get("hierarchical-levels")
    if opts.effective("irefresh-type") != "1" or levels is None or levels == "4":
        return []
    option = opts.encoder.option("hierarchical-levels")
    assert option is not None
    return [
        warning(
            "encoder.option_ignored",
            "video.advanced.hierarchical-levels",
            f"With forward keyframes SVT-AV1 uses hierarchical levels 4 "
            f"({_value_label(option, '4')}), not {_value_label(option, levels)}.",
            _set_option("hierarchical-levels", "4", target, "Use 16 frames"),
            _remove_option("hierarchical-levels", target),
        )
    ]


def _min_max_conflict(
    opts: _Options,
    low_key: str,
    high_key: str,
    message: str,
    target: FixTarget,
) -> list[ValidationIssue]:
    """``low_key`` above ``high_key`` (both as the encoder uses them) stops the encoder."""
    low, high = _int(opts.effective(low_key)), _int(opts.effective(high_key))
    if low is None or high is None or low <= high:
        return []
    if low_key not in opts.written and high_key not in opts.written:
        return []  # pragma: no cover - the defaults are consistent (the linter's range)
    path_key = low_key if low_key in opts.written else high_key
    fixes = [
        _set_option(low_key, high, target, f"Use {opts.label(low_key)} {high}"),
        _set_option(high_key, low, target, f"Use {opts.label(high_key)} {low}"),
    ]
    return [
        error(
            "encoder.option_conflict",
            f"video.advanced.{path_key}",
            message.format(low=low, high=high),
            *fixes,
        )
    ]


def _vp9_rules(video: VideoSettings, opts: _Options, target: FixTarget) -> list[ValidationIssue]:
    """libvpx: ``qmin`` above ``qmax`` fails, and so does a CQ value outside them ("CQ level 30
    must be between minimum and maximum quantizer value (0-29)")."""
    issues = _min_max_conflict(
        opts,
        "qmin",
        "qmax",
        "libvpx stops when the minimum quantiser ({low}) is above the maximum ({high}).",
        target,
    )
    rc = video.rate_control
    qmin, qmax = _int(opts.effective("qmin")), _int(opts.effective("qmax"))
    if issues or not isinstance(rc, ConstantQuality) or qmin is None or qmax is None:
        return issues
    crf = round(rc.value)
    for key, bound, outside in (("qmin", qmin, crf < qmin), ("qmax", qmax, crf > qmax)):
        if not outside:
            continue
        fixes = [_set_option(key, crf, target, f"Use {opts.label(key)} {crf}")]
        fixes.append(
            fix(f"Use CQ {bound}", replace("video.rate_control.value", bound), target=target)
        )
        issues.append(
            error(
                "encoder.option_conflict",
                f"video.advanced.{key}",
                f"libvpx stops when the CQ value {crf} is outside the quantiser range "
                f"{qmin} to {qmax}.",
                *fixes,
            )
        )
    return issues


def video_option_rule_issues(
    video: VideoSettings,
    caps: CapabilitySnapshot,
    definitions: Definitions,
    *,
    target: FixTarget = "job",
) -> list[ValidationIssue]:
    """Rules of the advanced options (C-6, M9), each checked with the encoder
    (testdata/README.md "Advanced encoder options (C-6, complete option sets)"):

    - ``encoder.option_inactive`` (warning): the job sets an option whose ``requires`` does
      not hold, so the command builder leaves it out (x264 ``nal-hrd`` without VBV, x265
      ``amp`` without ``rect``, ``limit-tu`` with TU inter depth 1, ``rd-refine`` below RD 5,
      AMF pre-analysis options without pre-analysis …). The encoders ignore these too. Also
      x264 / x265 ``vbv-maxrate`` without ``vbv-bufsize``, and a buffer without a maximum rate
      at a constant quality: the builder writes them, and the encoders drop them.
    - ``encoder.option_ignored`` (warning): the encoder silently changes a value the job sets:
      x264 with Blu-ray compatibility (B-frames above 3, smart weighted P-frames, a normal
      B-pyramid); x265 ``max-tu-size`` or ``qg-size`` above the CTU size, ``limit-refs`` 2
      or 3 with ``pmode``; SVT-AV1 hierarchical levels other than 4 with forward keyframes.
    - ``encoder.option_conflict`` (error): the encoder refuses to start: x265 ``min-cu-size``
      above the CTU size; SVT-AV1 ``min-qp`` above ``max-qp`` or ``qm-min`` above ``qm-max``;
      libvpx ``qmin`` above ``qmax`` or a CQ value outside them.
    """
    encoder = definitions.video_encoders.get(video.encoder)
    if encoder is None or video.passthrough:
        return []
    opts = _Options(video, encoder, _status(caps, encoder.id))
    issues = _inactive_issues(opts, target)
    if encoder.id in ("libx264", "libx265"):
        issues += _vbv_rules(video, opts, target)
    if encoder.id == "libx264":
        issues += _x264_rules(opts, target)
    elif encoder.id == "libx265":
        issues += _x265_rules(opts, target)
    elif encoder.id == "libsvtav1":
        issues += _svt_rules(opts, target)
        issues += _min_max_conflict(
            opts,
            "min-qp",
            "max-qp",
            "SVT-AV1 stops when the minimum quantiser ({low}) is above the maximum ({high}).",
            target,
        )
        issues += _min_max_conflict(
            opts,
            "qm-min",
            "qm-max",
            "SVT-AV1 stops when the minimum QM level ({low}) is above the maximum ({high}).",
            target,
        )
    elif encoder.id == "libvpx-vp9":
        issues += _vp9_rules(video, opts, target)
    return issues


# --------------------------------------------------------------------------- custom parameters

CUSTOM_PARAM_CODES = ("encoder.custom_param_file", "encoder.custom_param_unknown")
"""The codes of :func:`video_custom_param_issues` (registered in ``validation/levels.py``)."""


def _remove_param(
    params: Sequence[CustomParam], param: CustomParam | None, target: FixTarget
) -> Fix:
    if param is None:  # a key only FFmpeg's own splitting finds (quotes): drop them all
        return fix(
            "Remove the custom parameters", replace("video.custom_params", ""), target=target
        )
    rest = ":".join(p.raw for p in params if p is not param)
    return fix(
        f"Remove {param.raw.strip()} from the custom parameters",
        replace("video.custom_params", rest),
        target=target,
    )


def _param_file_issues(
    encoder: VideoEncoderDef, video: VideoSettings, target: FixTarget
) -> list[ValidationIssue]:
    """x264 / x265 / SVT-AV1: the keys the library reads, split as typed and as FFmpeg splits
    the params argument (quotes and escapes)."""
    params = split_custom_params(video.custom_params)
    candidates: list[tuple[str, str, CustomParam | None]] = [(p.name, p.value, p) for p in params]
    for key, value in dict_pairs(video.custom_params.strip().strip(":")):
        forms = library_key_forms(key)
        owner = next((p for p in params if library_key_forms(p.name) & forms), None)
        candidates.append((key, value, owner))
    issues: list[ValidationIssue] = []
    reported: set[str] = set()
    for name, value, owner in candidates:
        what = file_key(encoder.id, name, value)
        seen = owner.raw if owner is not None else name
        if what is None or seen in reported:
            continue
        reported.add(seen)
        issues.append(
            error(
                "encoder.custom_param_file",
                "video.custom_params",
                f"The custom parameter {name!r} names a file ({encoder.label}: {what}). Reframe "
                "does not pass parameters that make the encoder read or write files.",
                _remove_param(params, owner, target),
            )
        )
    return issues


def _own_option_issues(
    encoder: VideoEncoderDef,
    video: VideoSettings,
    status: EncoderStatus | None,
    target: FixTarget,
) -> list[ValidationIssue]:
    """VP9, NVENC, QSV, AMF, VAAPI: each entry is written as ``-<name>:v:0``; only the allow-list
    of :func:`~reframe.definitions.custom_params.own_option_allowed` passes."""
    rules = custom_param_rules()
    params = split_custom_params(video.custom_params)
    build = status.private_options if status is not None else []
    issues: list[ValidationIssue] = []
    for param in params:
        name = param.name
        if own_option_allowed(encoder.id, name, build):
            continue
        if name in rules.file_options or name.startswith("/"):
            code = "encoder.custom_param_file"
            message = (
                f"The custom parameter {name!r} is an FFmpeg option that reads or writes a "
                "file. Reframe does not pass parameters that read or write files."
            )
        elif name in rules.unchecked_options:
            code = "encoder.custom_param_unknown"
            message = (
                f"The custom parameter {name!r} passes text to the {encoder.label} library that "
                "Reframe cannot check, so it is not passed to FFmpeg."
            )
        else:
            code = "encoder.custom_param_unknown"
            message = (
                f"The custom parameter {name!r} is not an option of {encoder.id} (ffmpeg -h "
                f"encoder={encoder.id}) or a generic encoder option: Reframe passes only these "
                "to FFmpeg."
            )
        issues.append(
            error(code, "video.custom_params", message, _remove_param(params, param, target))
        )
    return issues


def video_custom_param_issues(
    video: VideoSettings,
    caps: CapabilitySnapshot,
    definitions: Definitions,
    *,
    target: FixTarget = "job",
) -> list[ValidationIssue]:
    """Custom parameters that Reframe does not pass to FFmpeg (C-6; decision 0035 "Follow-up
    (core-complete review)"), each with a fix that removes the entry:

    - ``encoder.custom_param_file`` (error): a key that makes x264, x265 or SVT-AV1 read or
      write a file (x265 ``csv`` / ``analysis-save``, x264 ``dump-yuv`` / ``stats``, …, as the
      library reads keys: ``_`` as ``-``, a ``no`` prefix, FFmpeg's quotes), or, for an
      encoder without a params argument, one of FFmpeg's own options that reads or writes a
      file (``vstats_file``, ``passlogfile``, ``progress``, a ``/`` name).
    - ``encoder.custom_param_unknown`` (error): for an encoder without a params argument, a
      name that is neither a private option of the encoder (this build's list from encoder
      detection, else the recorded one) nor a generic encoder option. FFmpeg would read it as
      any of its own options, so only these are passed.

    The dry run checks the same before it starts FFmpeg."""
    if video.passthrough or not video.custom_params.strip():
        return []
    encoder = definitions.video_encoders.get(video.encoder)
    if encoder is None:
        return []
    if encoder.params_arg is not None:
        return _param_file_issues(encoder, video, target)
    return _own_option_issues(encoder, video, _status(caps, encoder.id), target)


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
