"""Video encoder arguments (05 §C-7 "Video", decision 0013).

Everything comes from the encoder's definition (C-6): rate control (``{value}``, the
``derived`` QP values, ``{kbps}``), the speed preset, tune, profile and level
(:class:`~reframe.definitions.ChoiceSetting`), fast decode, the advanced options
(:class:`~reframe.definitions.EncoderOption`), 2-pass (``{pass}`` / ``{passlog}``) and
``extra_args``. Options are written with the output stream specifier (``-preset:v:0``);
``x26x_param`` values go into the one params argument (``-x265-params a=1:b=2``), joined with
``:`` in this order: rate control, 2-pass, choices, fast decode, colour and HDR metadata,
advanced options, then the job's custom parameters as typed. Values are escaped for FFmpeg's
dictionary parser (a path with ``:`` in ``stats=``).

When the output stays HDR (an HDR source, no tone mapping or colour conversion, 10-bit),
the colour and the HDR10 metadata of the probe are written into the params of x265
(``colorprim``, ``transfer``, ``colormatrix``, ``master-display``, ``max-cll``) and SVT-AV1
(``color-primaries``, ``transfer-characteristics``, ``matrix-coefficients``,
``mastering-display``, ``content-light``); x264 gets the colour only. An advanced option
with the same name wins.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path, PureWindowsPath

from reframe.command.errors import PlanError
from reframe.command.filtergraph import escape_value, filter_path
from reframe.definitions import (
    ChoiceSetting,
    EncoderOption,
    OptionMapping,
    VideoEncoderDef,
    mapping_supported,
)
from reframe.models import (
    AverageBitrate,
    ConstantQuality,
    EncoderStatus,
    MasteringDisplay,
    OptionValue,
    Rational,
    VideoSettings,
    VideoStream,
)

__all__ = [
    "PassMode",
    "VideoArgs",
    "format_number",
    "frame_rate_args",
    "hdr_params",
    "pass_log_files",
    "spec",
    "video_encoder_args",
]

#: Which run of a 2-pass encode the arguments are for: ``None`` = a single run.
PassMode = int | None
V0 = "v:0"


def spec(option: str, stream: str) -> str:
    """``-preset`` → ``-preset:v:0``; ``-b:v`` → ``-b:v:0``."""
    return f"{option.split(':', 1)[0]}:{stream}"


def format_number(value: float | int, *, integer: bool = False) -> str:
    """``22.0`` → ``22``, ``20.5`` → ``20.5``, ``0.15`` → ``0.15``; ``integer`` rounds."""
    if integer:
        return str(round(value))
    if isinstance(value, int) or float(value).is_integer():
        return str(int(value))
    return repr(float(value))


def _option_text(value: OptionValue) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int | float):
        return format_number(value)
    return value


def _fill(template: str, values: Mapping[str, str]) -> str:
    for name, value in values.items():
        template = template.replace("{" + name + "}", value)
    return template


@dataclass(slots=True)
class VideoArgs:
    """The encoder arguments of one run."""

    args: list[str] = field(default_factory=list)
    params: dict[str, str] = field(default_factory=dict)
    params_raw: str = ""
    """The job's custom parameters, appended as typed."""

    def add(self, setting_args: list[str], values: Mapping[str, str]) -> None:
        """Pairs of ``-option value`` with placeholders; options get the ``v:0`` specifier."""
        for i in range(0, len(setting_args), 2):
            option, value = setting_args[i], setting_args[i + 1]
            self.args += [spec(option, V0), _fill(value, values)]

    def add_params(self, params: Mapping[str, str], values: Mapping[str, str]) -> None:
        for name, value in params.items():
            self.params[name] = _fill(value, values)

    def mapped(self, mapping: OptionMapping, value: str) -> None:
        if mapping.kind == "x26x_param":
            self.params[mapping.name] = value
        elif mapping.kind == "private_opt":
            self.args += [spec(f"-{mapping.name}", V0), value]
        else:
            self.args += [spec(mapping.arg, V0), value]

    def render(self, encoder: VideoEncoderDef) -> list[str]:
        """The arguments with the params argument at the end."""
        if encoder.params_arg is None:
            return list(self.args)
        items = [f"{k}={escape_value(v)}" for k, v in self.params.items()]
        if self.params_raw.strip():
            items.append(self.params_raw.strip().strip(":"))
        if not items:
            return list(self.args)
        return [*self.args, spec(encoder.params_arg, V0), ":".join(items)]


# --------------------------------------------------------------------------- choices


def _choice(setting: ChoiceSetting | None, value: str | None, what: str, out: VideoArgs) -> None:
    if value is None:
        return
    if setting is None:
        raise PlanError(f"this encoder has no {what} setting (validation reports {value!r})")
    choice = setting.get(value)
    out.mapped(setting.mapping, choice.written if choice is not None else value)


def _tune(encoder: VideoEncoderDef, video: VideoSettings, out: VideoArgs) -> None:
    tune = video.tune
    fast = encoder.fast_decode if video.fast_decode else None
    if fast is not None and fast.tune is not None:
        if tune is None:
            tune = fast.tune
        elif fast.combines_with_tune:
            tune = f"{tune},{fast.tune}"
        else:
            raise PlanError(
                f"{encoder.label} takes one tune: fast decode ({fast.tune}) cannot be combined "
                f"with the tune {tune!r}"
            )
    if tune is not None and "," in tune and encoder.tunes is not None:
        out.mapped(encoder.tunes.mapping, tune)
    else:
        _choice(encoder.tunes, tune, "tune", out)
    if fast is not None:
        out.add(fast.args, {})
        out.add_params(fast.params, {})


# --------------------------------------------------------------------------- options


def _default(option: EncoderOption, preset: str | None) -> OptionValue | None:
    default = option.default
    if default.kind == "fixed":
        return default.value
    if default.kind == "preset":
        return default.values.get(preset) if preset is not None else None
    return None


def _options(
    encoder: VideoEncoderDef,
    video: VideoSettings,
    status: EncoderStatus | None,
    context: dict[str, OptionValue | None],
    out: VideoArgs,
) -> None:
    """The advanced options of the job. Options of another encoder or that this build does not
    support are skipped (validation reports them); so are options whose ``requires`` does not
    hold. Parts of a composite value (``deblock=-1,-1``) are filled with their defaults."""
    preset = context.get("preset")
    preset_name = preset if isinstance(preset, str) else None
    for key in encoder_option_keys(encoder):
        option = encoder.option(key)
        assert option is not None
        value = video.advanced.get(key)
        context[f"option:{key}"] = value if value is not None else _default(option, preset_name)
    composite: dict[str, dict[int, str]] = {}
    for key, value in video.advanced.items():
        option = encoder.option(key)
        if option is None or not mapping_supported(encoder, option.mapping, status):
            continue
        if not all(c.matches(context) for c in option.requires):
            continue
        text = _choice_value(option, value)
        mapping = option.mapping
        if mapping.kind == "x26x_param" and mapping.part is not None:
            composite.setdefault(mapping.name, {})[mapping.part] = text
            continue
        out.mapped(mapping, text)
    for name, parts in composite.items():
        siblings = sorted(
            (o for o in encoder.options if o.mapping.kind == "x26x_param"
             and o.mapping.name == name and o.mapping.part is not None),
            key=lambda o: o.mapping.part or 0,  # type: ignore[union-attr]
        )  # fmt: skip
        values: list[str] = []
        for sibling in siblings:
            part = sibling.mapping.part  # type: ignore[union-attr]
            if part in parts:
                values.append(parts[part])
                continue
            default = _default(sibling, preset_name)
            if default is None:
                raise PlanError(
                    f"option {sibling.key!r} has no default to complete {name}= (set it as well)"
                )
            values.append(_option_text(default))
        out.params[name] = ",".join(values)


def encoder_option_keys(encoder: VideoEncoderDef) -> list[str]:
    return [o.key for o in encoder.options]


def _choice_value(option: EncoderOption, value: OptionValue) -> str:
    if option.choices is not None and isinstance(value, str):
        found = next((c for c in option.choices if c.value == value), None)
        if found is not None:
            return found.written
    return _option_text(value)


# --------------------------------------------------------------------------- HDR


def _x265_display(md: MasteringDisplay) -> str:
    def c(v: float) -> int:
        return round(v * 50000)

    def lum(v: float) -> int:
        return round(v * 10000)

    return (
        f"G({c(md.green_x)},{c(md.green_y)})B({c(md.blue_x)},{c(md.blue_y)})"
        f"R({c(md.red_x)},{c(md.red_y)})WP({c(md.white_x)},{c(md.white_y)})"
        f"L({lum(md.max_luminance)},{lum(md.min_luminance)})"
    )


def _svt_display(md: MasteringDisplay) -> str:
    def f(v: float) -> str:
        return format_number(round(v, 6))

    return (
        f"G({f(md.green_x)},{f(md.green_y)})B({f(md.blue_x)},{f(md.blue_y)})"
        f"R({f(md.red_x)},{f(md.red_y)})WP({f(md.white_x)},{f(md.white_y)})"
        f"L({f(md.max_luminance)},{f(md.min_luminance)})"
    )


#: SVT-AV1 colour names that differ from FFmpeg's (``svt-av1/Docs/Parameters.md``).
_SVT_MATRIX = {"bt2020nc": "bt2020-ncl", "bt2020c": "bt2020-cl", "smpte170m": "bt601"}
_SVT_TRANSFER = {"arib-std-b67": "hlg", "smpte170m": "bt601", "iec61966-2-1": "srgb"}
_SVT_PRIMARIES = {"smpte170m": "bt601"}
_UNKNOWN = frozenset({"unknown", "unspecified", "reserved", ""})


def hdr_params(encoder: VideoEncoderDef, stream: VideoStream) -> dict[str, str]:
    """Colour and HDR10 metadata for the params argument when the output stays HDR."""
    c = stream.color
    colour = [
        (v if v not in _UNKNOWN else None)
        for v in (c.primaries, c.transfer, c.matrix)
    ]  # fmt: skip
    hdr = stream.hdr
    md = hdr.mastering_display if hdr is not None else None
    cll = hdr.content_light if hdr is not None else None
    params: dict[str, str] = {}
    if encoder.params_arg in ("-x265-params", "-x264-params"):
        for name, value in zip(("colorprim", "transfer", "colormatrix"), colour, strict=True):
            if value is not None:
                params[name] = value
        if encoder.params_arg == "-x265-params":
            if md is not None:
                params["master-display"] = _x265_display(md)
            if cll is not None:
                params["max-cll"] = f"{cll.max_cll},{cll.max_fall}"
    elif encoder.params_arg == "-svtav1-params":
        names = ("color-primaries", "transfer-characteristics", "matrix-coefficients")
        tables = (_SVT_PRIMARIES, _SVT_TRANSFER, _SVT_MATRIX)
        for name, value, table in zip(names, colour, tables, strict=True):
            if value is not None:
                params[name] = table.get(value, value)
        if md is not None:
            params["mastering-display"] = _svt_display(md)
        if cll is not None:
            params["content-light"] = f"{cll.max_cll},{cll.max_fall}"
    return params


# --------------------------------------------------------------------------- 2-pass


def pass_log_files(prefix: Path, *, stats_param: bool) -> list[Path]:
    """The files a 2-pass encode writes next to ``prefix`` (checked with FFmpeg n9.0.2):
    ``-passlogfile P`` gives ``P-0.log`` (x264 also ``P-0.log.mbtree``); x265's ``stats=P``
    gives ``P`` and ``P.cutree``; each has a ``.temp`` twin while the pass runs."""
    if stats_param:
        names = ["", ".temp", ".cutree", ".cutree.temp"]
        return [prefix.with_name(prefix.name + n) for n in names]
    names = ["-0.log", "-0.log.temp", "-0.log.mbtree", "-0.log.mbtree.temp"]
    return [prefix.with_name(prefix.name + n) for n in names]


def _passlog_param(prefix: Path) -> str:
    return filter_path(prefix) if isinstance(prefix, PureWindowsPath) else str(prefix)


# --------------------------------------------------------------------------- frame rate


def _rate(value: Rational | Fraction) -> str:
    if isinstance(value, Fraction):
        return (
            str(value.numerator)
            if value.denominator == 1
            else f"{value.numerator}/{value.denominator}"
        )
    return str(value.num) if value.den == 1 else f"{value.num}/{value.den}"


#: Frame rates a counted rate snaps to (within 0.2 %).
_STANDARD_RATES = tuple(
    Fraction(n, d)
    for n, d in (
        (24000, 1001), (24, 1), (25, 1), (30000, 1001), (30, 1), (48, 1), (50, 1),
        (60000, 1001), (60, 1), (100, 1), (120000, 1001), (120, 1),
    )
)  # fmt: skip


def _snap_rate(rate: Fraction) -> Fraction:
    closest = min(_STANDARD_RATES, key=lambda standard: abs(rate - standard))
    if abs(rate - closest) <= closest / 500:
        return closest
    return rate.limit_denominator(1001)


def _fraction(rate: Rational | Fraction) -> Fraction:
    return rate if isinstance(rate, Fraction) else Fraction(rate.num, rate.den)


def source_rate(stream: VideoStream) -> Rational | Fraction | None:
    """The source's average frame rate: ``avg_frame_rate``, else frames / duration, else
    ``r_frame_rate`` (FFmpeg's Matroska VFR files have no average)."""
    if stream.avg_frame_rate is not None and stream.avg_frame_rate.num > 0:
        return stream.avg_frame_rate
    if stream.frame_count and stream.duration:
        return _snap_rate(Fraction(stream.frame_count) / Fraction(stream.duration))
    if stream.frame_rate is not None and stream.frame_rate.num > 0:
        return stream.frame_rate
    return None


def frame_rate_args(
    video: VideoSettings, stream: VideoStream, *, factor: Fraction | int = 1
) -> list[str]:
    """``Same as source`` + variable: nothing. Constant: ``-r R -fps_mode cfr`` (``R`` = the
    chosen rate, or the source's average times ``factor``, the rate after the filters: 2
    after a Bob deinterlacer, 4/5 after detelecine). Peak (or variable with a chosen rate):
    ``-fpsmax R`` (decision 0013: FFmpeg has no peak mode; a faster source becomes CFR R)."""
    rate = video.framerate
    if video.framerate_mode == "constant":
        target: Rational | Fraction | None = rate
        if target is None:
            source = source_rate(stream)
            if source is not None and factor != 1:
                source = _fraction(source) * factor
            target = source
        if target is None:
            return [spec("-fps_mode", V0), "cfr"]
        return [spec("-r", V0), _rate(target), spec("-fps_mode", V0), "cfr"]
    if rate is not None:
        return [spec("-fpsmax", V0), _rate(rate)]
    return []


# --------------------------------------------------------------------------- the encoder


def video_encoder_args(
    encoder: VideoEncoderDef,
    video: VideoSettings,
    stream: VideoStream,
    *,
    status: EncoderStatus | None,
    run: PassMode,
    passlog: Path | None,
    hdr: bool,
) -> list[str]:
    """``-c:v:0 <encoder>`` and everything after it for one run (``run`` 1 or 2 of a 2-pass
    encode, ``None`` otherwise)."""
    out = VideoArgs(args=[spec("-c:v", V0), encoder.id])
    rc = video.rate_control
    preset = video.preset or (encoder.presets.default if encoder.presets else None)
    context: dict[str, OptionValue | None] = {
        "rate_control": rc.mode,
        "two_pass": isinstance(rc, AverageBitrate) and rc.two_pass,
        "bit_depth": video.bit_depth,
        "preset": preset,
        "tune": video.tune,
    }
    if isinstance(rc, ConstantQuality):
        mode = encoder.rate_control.quality
        if mode is None:
            raise PlanError(f"{encoder.label} has no constant-quality mode")
        integer = mode.step >= 1
        values = {"value": format_number(rc.value, integer=integer)}
        for name, derived in mode.derived.items():
            values[name] = format_number(derived.compute(rc.value), integer=derived.integer)
        out.add(mode.args, values)
        out.add_params(mode.params, values)
    else:
        bitrate = encoder.rate_control.bitrate
        if bitrate is None:
            raise PlanError(f"{encoder.label} has no average-bitrate mode")
        values = {"kbps": str(rc.kbps)}
        out.add(bitrate.args, values)
        out.add_params(bitrate.params, values)
        two_pass = bitrate.two_pass
        if rc.two_pass:
            if two_pass is None:
                raise PlanError(f"{encoder.label} has no 2-pass mode")
            first = run == 1 or two_pass.mode == "single_run"
            values = {}
            if two_pass.mode == "two_runs":
                if run not in (1, 2) or passlog is None:
                    raise PlanError("a 2-pass encode needs the pass number and the log prefix")
                log = str(passlog)
                param_log = _passlog_param(passlog)
                out.add(two_pass.args, {"pass": str(run), "passlog": log})
                out.add_params(two_pass.params, {"pass": str(run), "passlog": param_log})
            if first:
                turbo = rc.turbo_first_pass
                out.add(two_pass.turbo_args if turbo else two_pass.full_args, values)
                out.add_params(two_pass.turbo_params if turbo else two_pass.full_params, values)
    _choice(encoder.presets, video.preset, "speed preset", out)
    _tune(encoder, video, out)
    _choice(encoder.profiles, video.profile, "profile", out)
    _choice(encoder.levels, video.level, "level", out)
    if hdr:
        for name, value in hdr_params(encoder, stream).items():
            out.params.setdefault(name, value)
    _options(encoder, video, status, context, out)
    out.add(encoder.extra_args, {})
    out.params_raw = video.custom_params
    return out.render(encoder)
