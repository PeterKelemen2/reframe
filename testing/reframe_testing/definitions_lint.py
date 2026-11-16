"""Consistency checks that Pydantic cannot make, across the definitions tables.

:func:`lint_definitions` returns the problems as text, and an empty list when the definitions
are clean. A test keeps the packaged data clean.
"""

from __future__ import annotations

import itertools
import re
from typing import get_args

from reframe.definitions.models import (
    FILTER_IDS,
    FILTER_STAGES,
    OPTION_CATEGORIES,
    TRACK_FLAGS,
    AudioEncoderDef,
    ChoiceSetting,
    CodecSupport,
    Condition,
    ContainerDef,
    Definitions,
    EncoderOption,
    FilterDef,
    FilterImplementation,
    OptionMapping,
    QualityMode,
    VideoCodec,
    VideoEncoderDef,
)
from reframe.models.defaults import PassthruCodec
from reframe.models.job import Container, Mixdown, OptionValue, SubtitleFormat

__all__ = ["lint_definitions"]

CONDITION_FIELDS = ("rate_control", "two_pass", "bit_depth", "preset", "tune")
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
_FILTER_NAME = re.compile(r"^([A-Za-z0-9_]+)")
#: Filters a chain may use besides its implementation's (pixel format conversion).
_HELPER_FILTERS = frozenset({"format"})
#: Placeholders of ``HardwareSetup`` (filled in by the command builder).
_HARDWARE_PLACEHOLDERS = frozenset({"vaapi_device", "sw_pix_fmt"})
#: Speed-ordered preset names, one tuple per scale, fastest first.
_PRESET_SPEED_WORDS: tuple[tuple[str, ...], ...] = (
    (
        "ultrafast",
        "superfast",
        "veryfast",
        "faster",
        "fast",
        "medium",
        "slow",
        "slower",
        "veryslow",
        "placebo",
    ),
    ("speed", "balanced", "quality", "high_quality"),
)


def lint_definitions(defs: Definitions) -> list[str]:
    """Every problem found in ``defs``, as ``"<where>: <what>"`` lines."""
    problems: list[str] = []
    problems += _lint_video(defs)
    problems += _lint_audio(defs)
    problems += _lint_containers(defs)
    problems += _lint_filters(defs)
    return problems


def _lint_video(defs: Definitions) -> list[str]:
    out: list[str] = []
    encoders = defs.video_encoders
    keys: dict[str, str] = {}
    for enc_id, enc in encoders.items():
        where = f"video_encoders.{enc_id}"
        if enc.id != enc_id:
            out.append(f"{where}: id {enc.id!r} differs from the table key")
        if not enc.label or not enc.codec_label or not enc.handbrake_key:
            out.append(f"{where}: label, codec_label and handbrake_key must not be empty")
        if enc.handbrake_key in keys:
            other = keys[enc.handbrake_key]
            out.append(f"{where}: handbrake_key {enc.handbrake_key!r} also used by {other}")
        keys[enc.handbrake_key] = enc_id
        if "8" not in enc.pix_fmts:
            out.append(f"{where}: pix_fmts has no 8-bit format")
        out += _lint_fallback(where, enc, encoders)
        out += _lint_rate_control(where, enc)
        for name in ("presets", "tunes", "profiles", "levels"):
            setting: ChoiceSetting | None = getattr(enc, name)
            if setting is not None:
                out += _lint_choice_setting(f"{where}.{name}", enc, setting)
        if enc.presets is not None:
            out += _lint_preset_order(f"{where}.presets", enc.presets)
        out += _lint_hardware_setup(where, enc)
        if enc.profiles is not None:
            for depth in enc.pix_fmts:
                if not enc.profiles.values(int(depth)):
                    out.append(f"{where}.profiles: no profile for {depth}-bit")
        fd = enc.fast_decode
        if fd is not None and fd.tune is None and not fd.args and not fd.params:
            out.append(f"{where}.fast_decode: needs a tune, args or params")
        if enc.fast_decode is not None and enc.fast_decode.params and enc.params_arg is None:
            out.append(f"{where}.fast_decode: params need a params_arg")
        out += _lint_options(where, enc)
    codecs_in_containers = {c for cont in defs.containers.values() for c in cont.video.encode}
    for enc_id, enc in encoders.items():
        if enc.codec not in codecs_in_containers:
            out.append(f"video_encoders.{enc_id}: no container can hold {enc.codec}")
    return out


def _lint_fallback(
    where: str, enc: VideoEncoderDef, encoders: dict[str, VideoEncoderDef]
) -> list[str]:
    out: list[str] = []
    if not enc.hardware:
        if enc.fallback:
            out.append(f"{where}.fallback: a software encoder needs no fallback chain")
        return out
    if not enc.fallback:
        return [f"{where}.fallback: a hardware encoder needs a fallback chain"]
    if len(set(enc.fallback)) != len(enc.fallback):
        out.append(f"{where}.fallback: duplicate entries")
    if enc.id in enc.fallback:
        out.append(f"{where}.fallback: contains the encoder itself")
    for step in enc.fallback:
        other = encoders.get(step)
        if other is None:
            out.append(f"{where}.fallback: unknown encoder {step!r}")
        elif other.codec != enc.codec:
            out.append(f"{where}.fallback: {step} is {other.codec}, not {enc.codec}")
    last = encoders.get(enc.fallback[-1])
    if last is not None and last.hardware:
        out.append(f"{where}.fallback: the chain must end in a software encoder, not {last.id}")
    return out


def _placeholders(texts: list[str]) -> set[str]:
    return {name for text in texts for name in _PLACEHOLDER.findall(text)}


def _lint_hardware_setup(where: str, enc: VideoEncoderDef) -> list[str]:
    """The placeholders must be ones the command builder fills in."""
    setup = enc.hardware_setup
    if setup is None:
        return []
    out: list[str] = []
    if not enc.hardware:
        out.append(f"{where}.hardware_setup: a software encoder needs no hardware setup")
    unknown = _placeholders([*setup.init_args, *setup.filter_tail]) - _HARDWARE_PLACEHOLDERS
    if unknown:
        out.append(f"{where}.hardware_setup: unknown placeholders {sorted(unknown)}")
    return out


def _preset_speed_rank(value: str) -> float | None:
    """Speed rank of a preset value: lower is faster. ``None`` for a value the linter does not
    know; the linter reports it, so a new encoder's presets need a rank here."""
    for words in _PRESET_SPEED_WORDS:
        if value in words:
            return float(words.index(value))
    if (match := re.fullmatch(r"p(\d+)", value)) is not None:  # NVENC: p1 fastest
        return float(match.group(1))
    if re.fullmatch(r"-?\d+", value):  # SVT-AV1 (and libvpx cpu-used): higher is faster
        return -float(value)
    return None


def _lint_preset_order(w: str, presets: ChoiceSetting) -> list[str]:
    """Presets are listed fastest first, which is the order of the slider."""
    ranks: list[float] = []
    for choice in presets.choices:
        rank = _preset_speed_rank(choice.value)
        if rank is None:
            return [f"{w}: the linter does not know the speed of preset {choice.value!r}"]
        ranks.append(rank)
    if any(b <= a for a, b in itertools.pairwise(ranks)):
        return [f"{w}: presets must be listed fastest first"]
    return []


def _lint_rate_control(where: str, enc: VideoEncoderDef) -> list[str]:
    out: list[str] = []
    rc = enc.rate_control
    if rc.quality is None and rc.bitrate is None:
        out.append(f"{where}.rate_control: needs a quality or a bitrate mode")
    if rc.quality is not None:
        out += _lint_quality(f"{where}.rate_control.quality", enc, rc.quality)
    if rc.bitrate is not None:
        b = rc.bitrate
        w = f"{where}.rate_control.bitrate"
        if not 0 < b.min_kbps < b.max_kbps:
            out.append(f"{w}: needs 0 < min_kbps < max_kbps")
        texts = [*b.args, *b.params.values()]
        if "kbps" not in _placeholders(texts):
            out.append(f"{w}: the arguments do not use {{kbps}}")
        if _placeholders(texts) - {"kbps"}:
            out.append(f"{w}: unknown placeholders {sorted(_placeholders(texts) - {'kbps'})}")
        if b.params and enc.params_arg is None:
            out.append(f"{w}: params need a params_arg")
        tp = b.two_pass
        if tp is not None:
            all_texts = [
                *tp.args,
                *tp.params.values(),
                *tp.turbo_args,
                *tp.turbo_params.values(),
                *tp.full_args,
                *tp.full_params.values(),
            ]
            unknown = _placeholders(all_texts) - {"pass", "passlog"}
            if unknown:
                out.append(f"{w}.two_pass: unknown placeholders {sorted(unknown)}")
            if tp.mode == "two_runs" and "pass" not in _placeholders(
                [*tp.args, *tp.params.values()]
            ):
                out.append(f"{w}.two_pass: two_runs must pass {{pass}} to every run")
            if tp.mode == "single_run" and not (tp.full_args or tp.full_params):
                out.append(f"{w}.two_pass: single_run needs the arguments that turn it on")
            has_params = tp.params or tp.turbo_params or tp.full_params
            if has_params and enc.params_arg is None:
                out.append(f"{w}.two_pass: params need a params_arg")
    return out


def _lint_quality(w: str, enc: VideoEncoderDef, q: QualityMode) -> list[str]:
    out: list[str] = []
    if not q.min < q.max:
        out.append(f"{w}: min must be below max")
    if q.step <= 0:
        out.append(f"{w}: step must be positive")
    elif not _on_grid(q.default, q.min, q.step) or not q.min <= q.default <= q.max:
        out.append(f"{w}: default {q.default} is outside the range or off the step grid")
    texts = [*q.args, *q.params.values()]
    used = _placeholders(texts)
    if "value" not in used:
        out.append(f"{w}: the arguments do not use {{value}}")
    unknown = used - {"value"} - set(q.derived)
    if unknown:
        out.append(f"{w}: unknown placeholders {sorted(unknown)}")
    for name, derived in q.derived.items():
        if derived.factor <= 0:
            out.append(f"{w}.derived.{name}: factor must be positive")
        if derived.min is not None and derived.max is not None and derived.min > derived.max:
            out.append(f"{w}.derived.{name}: min must not be above max")
    if q.params and enc.params_arg is None:
        out.append(f"{w}: params need a params_arg")
    if len(q.scale) < 2:
        out.append(f"{w}.scale: needs at least two points")
    else:
        xs = [p[0] for p in q.scale]
        ys = [p[1] for p in q.scale]
        if any(b <= a for a, b in itertools.pairwise(xs)) or any(
            b <= a for a, b in itertools.pairwise(ys)
        ):
            out.append(f"{w}.scale: values and equivalents must both increase")
        if xs[0] > q.min or xs[-1] < q.max:
            out.append(f"{w}.scale: must cover the range {q.min}..{q.max}")
    for band in q.recommended:
        if not q.min <= band.low <= band.high <= q.max:
            out.append(f"{w}.recommended: band {band.low}..{band.high} is outside the range")
    heights = [b.max_height for b in q.recommended]
    if heights != sorted(set(heights)):
        out.append(f"{w}.recommended: max_height must increase")
    return out


def _on_grid(value: float, start: float, step: float) -> bool:
    n = (value - start) / step
    return abs(n - round(n)) < 1e-6


def _lint_choice_setting(w: str, enc: VideoEncoderDef, setting: ChoiceSetting) -> list[str]:
    out: list[str] = []
    values = [c.value for c in setting.choices]
    if not values:
        out.append(f"{w}: no choices")
    if len(set(values)) != len(values):
        out.append(f"{w}: duplicate values")
    if setting.default is not None and setting.default not in values:
        out.append(f"{w}: default {setting.default!r} is not a choice")
    for depth, value in setting.default_by_depth.items():
        choice = setting.get(value)
        if choice is None:
            out.append(f"{w}: default for {depth}-bit {value!r} is not a choice")
        elif choice.bit_depths is not None and int(depth) not in choice.bit_depths:
            out.append(f"{w}: default for {depth}-bit {value!r} is not valid for {depth}-bit")
    for c in setting.choices:
        if not c.label:
            out.append(f"{w}: choice {c.value!r} has no label")
        if c.bit_depths is not None and not set(c.bit_depths) <= {8, 10}:
            out.append(f"{w}: choice {c.value!r} names an unknown bit depth")
    out += _lint_mapping(w, enc, setting.mapping)
    return out


def _lint_mapping(w: str, enc: VideoEncoderDef, mapping: OptionMapping) -> list[str]:
    out: list[str] = []
    if mapping.kind == "ffmpeg_arg":
        if not mapping.arg.startswith("-") or len(mapping.arg) < 2:
            out.append(f"{w}: ffmpeg_arg {mapping.arg!r} must be an option with a dash")
    elif mapping.kind == "private_opt":
        if not mapping.name or mapping.name.startswith("-"):
            out.append(f"{w}: private_opt name {mapping.name!r} must be given without the dash")
    elif mapping.kind == "x26x_param":
        if not mapping.name:
            out.append(f"{w}: x26x_param needs a name")
        if enc.params_arg is None:
            out.append(f"{w}: x26x_param on an encoder without params_arg")
    return out


def _lint_options(where: str, enc: VideoEncoderDef) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    parts: dict[str, list[int | None]] = {}
    by_key = {o.key: o for o in enc.options}
    preset_values = set(enc.presets.values()) if enc.presets else set()
    tune_values = set(enc.tunes.values()) if enc.tunes else set()
    if enc.fast_decode is not None and enc.fast_decode.tune is not None:
        tune_values.add(enc.fast_decode.tune)
    for opt in enc.options:
        w = f"{where}.options.{opt.key}"
        if opt.key in seen:
            out.append(f"{w}: duplicate key")
        seen.add(opt.key)
        if not opt.label or not opt.category:
            out.append(f"{w}: needs a label and a category")
        elif opt.category not in OPTION_CATEGORIES:
            out.append(f"{w}: unknown category {opt.category!r}")
        if len(opt.help.strip()) < 10:
            out.append(f"{w}: needs help text")
        out += _lint_mapping(w, enc, opt.mapping)
        if opt.mapping.kind == "x26x_param":
            parts.setdefault(opt.mapping.name, []).append(opt.mapping.part)
        out += _lint_option_range(w, opt)
        out += _lint_option_default(w, opt, preset_values, tune_values)
        for cond in opt.requires:
            out += _lint_condition(w, cond, by_key, opt.key)
    for name, indexes in parts.items():
        if indexes == [None]:
            continue
        numbered = sorted(i for i in indexes if i is not None)
        if None in indexes or numbered != list(range(len(indexes))):
            out.append(f"{where}.options: parts of {name!r} must be 0..{len(indexes) - 1}")
    out += _lint_option_targets(where, enc)
    return out


def _mapping_target(mapping: OptionMapping) -> str | None:
    """The key of what a mapping writes, so that mapping kinds compare: the argument (``-bf``),
    ``-<name>`` for a private option, ``params:<name>`` for an ``x26x_param`` (``None`` for a
    composite part)."""
    if mapping.kind == "x26x_param":
        return None if mapping.part is not None else f"params:{mapping.name}"
    if mapping.kind == "private_opt":
        return f"-{mapping.name}"
    return mapping.arg.split(":", 1)[0]


def _setting_targets(enc: VideoEncoderDef) -> dict[str, tuple[str, str | None]]:
    """What the encoder's settings other than the options write: target → (setting, the
    rate-control mode it belongs to, or ``None``)."""
    found: dict[str, tuple[str, str | None]] = {}

    def args(what: str, values: list[str], mode: str | None = None) -> None:
        for arg in values:
            if arg.startswith("-") and not arg.lstrip("-").replace(".", "").isdigit():
                found.setdefault(arg.split(":", 1)[0], (what, mode))

    def params(what: str, values: dict[str, str], mode: str | None = None) -> None:
        for name in values:
            found.setdefault(f"params:{name}", (what, mode))

    for name in ("presets", "tunes", "profiles", "levels"):
        setting: ChoiceSetting | None = getattr(enc, name)
        if setting is None:
            continue
        target = _mapping_target(setting.mapping)
        if target is not None:
            found.setdefault(target, (name, None))
    quality, bitrate = enc.rate_control.quality, enc.rate_control.bitrate
    if quality is not None:
        args("rate control", quality.args, "quality")
        params("rate control", quality.params, "quality")
    if bitrate is not None:
        args("rate control", bitrate.args, "bitrate")
        params("rate control", bitrate.params, "bitrate")
        if bitrate.two_pass is not None:
            two = bitrate.two_pass
            args("2-pass", [*two.args, *two.turbo_args, *two.full_args], "bitrate")
            params("2-pass", {**two.params, **two.turbo_params, **two.full_params}, "bitrate")
    if enc.fast_decode is not None:
        args("fast decode", enc.fast_decode.args)
        params("fast decode", enc.fast_decode.params)
    args("extra_args", enc.extra_args)
    return found


def _lint_option_targets(where: str, enc: VideoEncoderDef) -> list[str]:
    """Two options, or an option and another setting, that write the same argument or parameter:
    the command would carry it twice and the last one would win. An option that ``requires`` one
    rate-control mode may share an argument with the other mode (NVENC ``-multipass``)."""
    out: list[str] = []
    settings = _setting_targets(enc)
    owners: dict[str, str] = {}
    for opt in enc.options:
        target = _mapping_target(opt.mapping)
        if target is None:
            continue
        w = f"{where}.options.{opt.key}"
        if target in owners:
            out.append(f"{w}: writes {target} like option {owners[target]!r}")
        else:
            owners[target] = opt.key
        if target not in settings:
            continue
        what, mode = settings[target]
        modes = {str(c.value) for c in opt.requires if c.field == "rate_control" and c.op == "eq"}
        if mode is None or not modes or mode in modes:
            out.append(f"{w}: writes {target}, which {what} already writes")
    return out


def _lint_option_range(w: str, opt: EncoderOption) -> list[str]:
    out: list[str] = []
    numeric = opt.type in ("int", "float")
    if numeric:
        if opt.min is None or opt.max is None or opt.step is None:
            out.append(f"{w}: a number needs min, max and step")
        elif not (opt.min < opt.max and opt.step > 0):
            out.append(f"{w}: needs min < max and a positive step")
        elif opt.type == "int" and not all(
            float(v).is_integer() for v in (opt.min, opt.max, opt.step)
        ):
            out.append(f"{w}: an int option needs integer min, max and step")
    elif opt.min is not None or opt.max is not None or opt.step is not None:
        out.append(f"{w}: only numbers have min, max and step")
    if opt.type == "enum":
        values = [c.value for c in opt.choices or []]
        if not values:
            out.append(f"{w}: an enum needs choices")
        elif len(set(values)) != len(values):
            out.append(f"{w}: duplicate choices")
        elif any(not c.label for c in opt.choices or []):
            out.append(f"{w}: every choice needs a label")
    elif opt.choices is not None:
        out.append(f"{w}: only enums have choices")
    return out


def _value_problem(opt: EncoderOption, value: OptionValue) -> str | None:
    """Why ``value`` is not a valid value of ``opt`` (``None`` = valid)."""
    if opt.type == "bool":
        return None if isinstance(value, bool) else f"{value!r} is not a bool"
    if opt.type == "enum":
        values = [c.value for c in opt.choices or []]
        return None if isinstance(value, str) and value in values else f"{value!r} is not a choice"
    if opt.type == "string":
        return None if isinstance(value, str) else f"{value!r} is not a string"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return f"{value!r} is not a number"
    if opt.type == "int" and not float(value).is_integer():
        return f"{value!r} is not an integer"
    if opt.min is not None and opt.max is not None and not opt.min <= value <= opt.max:
        return f"{value!r} is outside {opt.min:g}..{opt.max:g}"
    return None


def _lint_option_default(
    w: str, opt: EncoderOption, preset_values: set[str], tune_values: set[str]
) -> list[str]:
    out: list[str] = []
    default = opt.default
    if default.kind == "fixed":
        problem = _value_problem(opt, default.value)
        if problem:
            out.append(f"{w}: default {problem}")
    elif default.kind == "preset":
        if not default.values:
            out.append(f"{w}: a per-preset default needs values")
        for preset, value in default.values.items():
            if preset not in preset_values:
                out.append(f"{w}: default names unknown preset {preset!r}")
            problem = _value_problem(opt, value)
            if problem:
                out.append(f"{w}: default for {preset}: {problem}")
        for tune in default.tunes:
            if tune not in tune_values:
                out.append(f"{w}: default names unknown tune {tune!r}")
    return out


def _lint_condition(
    w: str, cond: Condition, by_key: dict[str, EncoderOption], own_key: str
) -> list[str]:
    values = cond.value if isinstance(cond.value, list) else [cond.value]
    if cond.op in ("eq", "ne") and isinstance(cond.value, list):
        return [f"{w}: {cond.op} takes one value"]
    if cond.field.startswith("option:"):
        key = cond.field.removeprefix("option:")
        other = by_key.get(key)
        if other is None or key == own_key:
            return [f"{w}: requires unknown option {key!r}"]
        problems = [p for v in values if (p := _value_problem(other, v))]
        return [f"{w}: requires {key}: {p}" for p in problems]
    if cond.field not in CONDITION_FIELDS:
        return [f"{w}: unknown condition field {cond.field!r}"]
    if cond.field == "rate_control" and not set(map(str, values)) <= {"quality", "bitrate"}:
        return [f"{w}: rate_control is 'quality' or 'bitrate'"]
    if cond.field == "bit_depth" and not set(values) <= {8, 10}:
        return [f"{w}: bit_depth is 8 or 10"]
    return []


def _lint_audio(defs: Definitions) -> list[str]:
    out: list[str] = []
    for mixdown in get_args(Mixdown):
        if mixdown not in defs.mixdowns:
            out.append(f"mixdowns: {mixdown} is not defined")
    for codec in get_args(PassthruCodec):
        if codec not in defs.passthru_codecs:
            out.append(f"passthru_codecs: {codec} is not defined")
    for enc_id, enc in defs.audio_encoders.items():
        out += _lint_audio_encoder(f"audio_encoders.{enc_id}", enc, defs)
    return out


def _lint_audio_fallback(
    w: str, enc: AudioEncoderDef, encoders: dict[str, AudioEncoderDef]
) -> list[str]:
    """Audio chains like the video chains (known encoders, no duplicates, not the encoder
    itself), and the last one must be in every GPL build."""
    if not enc.fallback:
        if not enc.in_gpl_builds:
            return [f"{w}.fallback: an encoder that GPL builds lack needs a fallback chain"]
        return []
    out: list[str] = []
    if len(set(enc.fallback)) != len(enc.fallback):
        out.append(f"{w}.fallback: duplicate entries")
    if enc.id in enc.fallback:
        out.append(f"{w}.fallback: contains the encoder itself")
    for step in enc.fallback:
        if step not in encoders:
            out.append(f"{w}.fallback: unknown audio encoder {step!r}")
    last = encoders.get(enc.fallback[-1])
    if last is not None and not last.in_gpl_builds:
        out.append(
            f"{w}.fallback: the chain must end in an encoder of every GPL build, not {last.id}"
        )
    return out


def _lint_audio_encoder(w: str, enc: AudioEncoderDef, defs: Definitions) -> list[str]:
    out: list[str] = _lint_audio_fallback(w, enc, defs.audio_encoders)
    if not enc.label:
        out.append(f"{w}: needs a label")
    if not enc.mixdowns:
        out.append(f"{w}: needs mixdowns")
    for mixdown in enc.mixdowns:
        definition = defs.mixdowns.get(mixdown)
        if definition is None:
            out.append(f"{w}: unknown mixdown {mixdown}")
        elif definition.channels > enc.max_channels:
            out.append(f"{w}: mixdown {mixdown} has more channels than max_channels")
    rates = enc.samplerates
    if not rates or rates != sorted(set(rates)):
        out.append(f"{w}: samplerates must be listed, sorted and unique")
    if enc.passthru is not None and enc.passthru not in defs.passthru_codecs:
        out.append(f"{w}: unknown passthru codec {enc.passthru}")
    if enc.lossless:
        if enc.bitrate is not None or enc.quality is not None:
            out.append(f"{w}: a lossless encoder has no bitrate or quality")
        return out
    if enc.bitrate is None:
        return [*out, f"{w}: a lossy encoder needs bitrates"]
    allowed = enc.bitrate.allowed
    if allowed is not None and (not allowed or allowed != sorted(set(allowed))):
        out.append(f"{w}.bitrate.allowed: must be sorted and unique")
    if set(enc.bitrate.by_mixdown) != set(enc.mixdowns):
        out.append(f"{w}.bitrate: by_mixdown must list exactly the mixdowns")
    for mixdown, limits in enc.bitrate.by_mixdown.items():
        lw = f"{w}.bitrate.{mixdown}"
        if not 0 < limits.min <= limits.default <= limits.max:
            out.append(f"{lw}: needs 0 < min <= default <= max")
        if allowed is not None:
            for name in ("min", "max", "default"):
                if getattr(limits, name) not in allowed:
                    out.append(f"{lw}: {name} {getattr(limits, name)} is not an allowed value")
    q = enc.quality
    if q is not None:
        if not (q.min < q.max and q.step > 0 and q.min <= q.default <= q.max):
            out.append(f"{w}.quality: needs min < max, a positive step and the default inside")
        if not q.arg.startswith("-"):
            out.append(f"{w}.quality: arg must be an option with a dash")
    return out


def _lint_containers(defs: Definitions) -> list[str]:
    out: list[str] = []
    containers = defs.containers
    for cont_id in get_args(Container):
        if cont_id not in containers:
            out.append(f"containers: {cont_id} is not defined")
    for flag in TRACK_FLAGS:
        if flag not in defs.track_flags:
            out.append(f"track_flags: {flag} is not defined")
    audio_codecs: set[str] = {e.codec for e in defs.audio_encoders.values()}
    for cont_id, cont in containers.items():
        out += _lint_container(f"containers.{cont_id}", cont, audio_codecs)
    return out


def _lint_container(w: str, cont: ContainerDef, audio_codecs: set[str]) -> list[str]:
    out: list[str] = []
    if not cont.extensions or not all(e.startswith(".") for e in cont.extensions):
        out.append(f"{w}: extensions must start with a dot")
    unknown_video = set(cont.video.encode) - set(get_args(VideoCodec))
    if unknown_video:
        out.append(f"{w}.video.encode: unknown codecs {sorted(unknown_video)}")
    unknown_audio = set(cont.audio.encode) - audio_codecs
    if unknown_audio:
        out.append(f"{w}.audio.encode: unknown codecs {sorted(unknown_audio)}")
    unknown_subs = set(cont.subtitles.encode) - set(get_args(SubtitleFormat))
    if unknown_subs:
        out.append(f"{w}.subtitles.encode: unknown formats {sorted(unknown_subs)}")
    if (
        cont.text_subtitle_target is not None
        and cont.text_subtitle_target not in cont.subtitles.encode
    ):
        out.append(f"{w}: text_subtitle_target is not an encode target")
    for support_name in ("video", "audio", "subtitles"):
        support: CodecSupport = getattr(cont, support_name)
        for codec in support.copy_args:
            if not support.can_copy(codec):
                out.append(f"{w}.{support_name}.copy_args: {codec} is not copyable")
        if not support.copy_codecs and not support.encode:
            out.append(f"{w}.{support_name}: holds nothing")
        denied = support.copy_except
        if denied and "*" not in support.copy_codecs:
            out.append(f"{w}.{support_name}.copy_except: only needed with copy = ['*']")
        if len(set(denied)) != len(denied):
            out.append(f"{w}.{support_name}.copy_except: duplicate entries")
        both = sorted(set(denied) & set(support.copy_codecs))
        if both:
            out.append(f"{w}.{support_name}: {both} both copyable and denied")
    for codec, tag in cont.codec_tags.items():
        if codec not in cont.video.encode and not cont.video.can_copy(codec):
            out.append(f"{w}.codec_tags: the container cannot hold {codec}")
        if not tag:
            out.append(f"{w}.codec_tags: empty tag for {codec}")
    if "default" not in cont.flags:
        out.append(f"{w}: every muxer writes the default flag")
    return out


def _lint_filters(defs: Definitions) -> list[str]:
    out: list[str] = []
    for filter_id in FILTER_IDS:
        if filter_id not in defs.filters:
            out.append(f"filters: {filter_id} is not defined")
    order = defs.filter_order
    expected = set(FILTER_IDS) | set(FILTER_STAGES)
    if len(order) != len(set(order)) or set(order) != expected:
        missing = sorted(expected - set(order))
        extra = sorted(set(order) - expected)
        out.append(
            f"filter_order: needs each filter and stage once (missing {missing}, unknown {extra})"
        )
    for filter_id, definition in defs.filters.items():
        out += _lint_filter(f"filters.{filter_id}", definition)
    return out


def _chain_filters(chain: str) -> list[str]:
    names: list[str] = []
    for segment in chain.split(","):
        match = _FILTER_NAME.match(segment.strip())
        if match:
            names.append(match.group(1))
    return names


def _lint_filter(w: str, f: FilterDef) -> list[str]:
    out: list[str] = []
    h = f.help
    for name in ("what", "use_when", "avoid_when", "settings"):
        if len(getattr(h, name).strip()) < 5:
            out.append(f"{w}.help: {name} is empty")
    ids = [i.id for i in f.implementations]
    if not ids or len(set(ids)) != len(ids):
        out.append(f"{w}: needs implementations with unique ids")
    for impl in f.implementations:
        out += _lint_implementation(f"{w}.{impl.id}", impl)
    return out


def _lint_implementation(w: str, impl: FilterImplementation) -> list[str]:
    """Presets are complete: a default, a chain per preset (and per tune, when there are tunes),
    and chains that use only the implementation's filters."""
    out: list[str] = []
    if not impl.label:
        out.append(f"{w}: needs a label")
    preset_ids = [p.id for p in impl.presets]
    if len(set(preset_ids)) != len(preset_ids):
        out.append(f"{w}: duplicate preset ids")
    if impl.default_preset not in preset_ids:
        out.append(f"{w}: default_preset {impl.default_preset!r} is not a preset")
    if impl.filters and all(p.custom for p in impl.presets):
        out.append(f"{w}: needs at least one preset that is not custom")
    tune_ids = {t.id for t in impl.tunes}
    if len(tune_ids) != len(impl.tunes):
        out.append(f"{w}: duplicate tune ids")
    for preset in impl.presets:
        pw = f"{w}.presets.{preset.id}"
        if not preset.label:
            out.append(f"{pw}: needs a label")
        if preset.chain is None:
            out.append(f"{pw}: has no chain")
        if set(preset.tune_chains) - tune_ids:
            out.append(f"{pw}: unknown tunes {sorted(set(preset.tune_chains) - tune_ids)}")
        if tune_ids and not preset.custom and set(preset.tune_chains) != tune_ids:
            out.append(f"{pw}: needs a chain for every tune of {impl.id}")
        chains = [preset.chain] if preset.chain is not None else []
        chains += list(preset.tune_chains.values())
        uses_custom = False
        for chain in chains:
            if not chain.strip():
                out.append(f"{pw}: empty chain")
            placeholders = set(_PLACEHOLDER.findall(chain))
            uses_custom = uses_custom or "custom" in placeholders
            if placeholders - {"custom"}:
                out.append(f"{pw}: unknown placeholders {sorted(placeholders - {'custom'})}")
            if chain.strip() == "{custom}":
                continue
            used = set(_chain_filters(chain)) - _HELPER_FILTERS
            if not used <= set(impl.filters):
                extra = sorted(used - set(impl.filters))
                out.append(f"{pw}: chain uses {extra}, not in {impl.id}'s filters")
        if uses_custom != preset.custom:
            out.append(f"{pw}: custom must be true exactly when a chain uses {{custom}}")
    return out
