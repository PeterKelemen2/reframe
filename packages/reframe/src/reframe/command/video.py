"""Video encoder arguments, built from the encoder's definition.

Options get the output stream specifier (``-preset:v:0``). The ``x26x_param`` values share one
params argument, which comes after the other options. When the output stays HDR,
:func:`hdr_params` adds the colour and HDR10 metadata to it, and an advanced option of the same
name wins.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path, PureWindowsPath

from reframe.command.errors import PlanError
from reframe.command.filtergraph import escape_value, filter_path, known_colour
from reframe.definitions import (
    ChoiceSetting,
    Definitions,
    EncoderOption,
    OptionMapping,
    VideoEncoderDef,
    fill_placeholders,
    mapping_supported,
    option_context,
    option_default,
)
from reframe.definitions.hdr import content_light_text, svt_mastering_display, x265_master_display
from reframe.models import (
    ConstantQuality,
    EncoderStatus,
    JobSettings,
    OptionValue,
    Rational,
    VideoSettings,
    VideoStream,
)

__all__ = [
    "PassMode",
    "VideoArgs",
    "encoder_and_pix_fmt",
    "format_number",
    "frame_rate_args",
    "hdr_params",
    "pass_log_files",
    "spec",
    "split_params",
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


def split_params(text: str) -> list[tuple[str, str]]:
    """The ``key=value`` entries of a custom parameter string, split at ``:`` (a ``\\:``
    stays in the value, unescaped); an entry without ``=`` is ``key=1`` (a switch). Empty
    entries are dropped."""
    entries: list[str] = []
    current: list[str] = []
    escaped = False
    for char in text.strip():
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            entries.append("".join(current))
            current = []
        else:
            current.append(char)
    entries.append("".join(current))
    result: list[tuple[str, str]] = []
    for raw in entries:
        entry = raw.strip()
        if not entry:
            continue
        name, sep, value = entry.partition("=")
        result.append((name.strip().lstrip("-"), value.strip() if sep else "1"))
    return result


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
            self.args += [spec(option, V0), fill_placeholders(value, values)]

    def add_params(self, params: Mapping[str, str], values: Mapping[str, str]) -> None:
        for name, value in params.items():
            self.params[name] = fill_placeholders(value, values)

    def mapped(self, mapping: OptionMapping, value: str) -> None:
        if mapping.kind == "x26x_param":
            self.params[mapping.name] = value
        elif mapping.kind == "private_opt":
            self.args += [spec(f"-{mapping.name}", V0), value]
        else:
            self.args += [spec(mapping.arg, V0), value]

    def render(self, encoder: VideoEncoderDef) -> list[str]:
        """The arguments, with the params argument after them. An encoder without a params
        argument takes the custom parameters as its own options (``rc-lookahead=20`` →
        ``-rc-lookahead:v:0 20``)."""
        if encoder.params_arg is None:
            custom = [
                arg
                for name, value in split_params(self.params_raw)
                for arg in (spec(f"-{name}", V0), value)
            ]
            return [*self.args, *custom]
        items = [f"{k}={escape_value(v)}" for k, v in self.params.items()]
        if self.params_raw.strip():
            items.append(self.params_raw.strip().strip(":"))
        if not items:
            return list(self.args)
        return [*self.args, spec(encoder.params_arg, V0), ":".join(items)]


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


def _options(
    encoder: VideoEncoderDef,
    video: VideoSettings,
    status: EncoderStatus | None,
    out: VideoArgs,
) -> None:
    """The advanced options of the job. Options of another encoder or that this build does not
    support are skipped (validation reports them); so are options whose ``requires`` does not
    hold (:func:`~reframe.definitions.option_context`, which validation uses too).
    Parts of a composite value (``deblock=-1,-1``) are filled with their defaults."""
    context = option_context(encoder, video)
    preset = context.get("preset")
    preset_name = preset if isinstance(preset, str) else None
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
            default = option_default(sibling, preset_name)
            if default is None:
                raise PlanError(
                    f"option {sibling.key!r} has no default to complete {name}= (set it as well)"
                )
            values.append(_option_text(default))
        out.params[name] = ",".join(values)


def _choice_value(option: EncoderOption, value: OptionValue) -> str:
    if option.choices is not None and isinstance(value, str):
        found = next((c for c in option.choices if c.value == value), None)
        if found is not None:
            return found.written
    return _option_text(value)


#: SVT-AV1 colour names that differ from FFmpeg's (``svt-av1/Docs/Parameters.md``).
_SVT_MATRIX = {"bt2020nc": "bt2020-ncl", "bt2020c": "bt2020-cl", "smpte170m": "bt601"}
_SVT_TRANSFER = {"arib-std-b67": "hlg", "smpte170m": "bt601", "iec61966-2-1": "srgb"}
_SVT_PRIMARIES = {"smpte170m": "bt601"}


def hdr_params(encoder: VideoEncoderDef, stream: VideoStream) -> dict[str, str]:
    """Colour and HDR10 metadata for the params argument when the output stays HDR."""
    c = stream.color
    colour = [known_colour(v) for v in (c.primaries, c.transfer, c.matrix)]
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
                params["master-display"] = x265_master_display(md)
            if cll is not None:
                params["max-cll"] = content_light_text(cll)
    elif encoder.params_arg == "-svtav1-params":
        names = ("color-primaries", "transfer-characteristics", "matrix-coefficients")
        tables = (_SVT_PRIMARIES, _SVT_TRANSFER, _SVT_MATRIX)
        for name, value, table in zip(names, colour, tables, strict=True):
            if value is not None:
                params[name] = table.get(value, value)
        if md is not None:
            params["mastering-display"] = svt_mastering_display(md)
        if cll is not None:
            params["content-light"] = content_light_text(cll)
    return params


def pass_log_files(prefix: Path, *, stats_param: bool) -> list[Path]:
    """The files a 2-pass encode writes next to ``prefix``. ``stats_param`` says whether the
    encoder names its log with a ``stats=`` param (x265) rather than ``-passlogfile``."""
    if stats_param:
        names = ["", ".temp", ".cutree", ".cutree.temp"]
        return [prefix.with_name(prefix.name + n) for n in names]
    names = ["-0.log", "-0.log.temp", "-0.log.mbtree", "-0.log.mbtree.temp"]
    return [prefix.with_name(prefix.name + n) for n in names]


def _passlog_param(prefix: Path) -> str:
    return filter_path(prefix) if isinstance(prefix, PureWindowsPath) else str(prefix)


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
    """Frame-rate options. Constant: ``-r R -fps_mode cfr``, where R is the chosen rate, else the
    source's average times ``factor`` (the rate change of the filters). Otherwise a chosen rate
    becomes ``-fpsmax R``: FFmpeg has no peak mode, so a faster source becomes CFR at R."""
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


def encoder_and_pix_fmt(job: JobSettings, defs: Definitions) -> tuple[VideoEncoderDef, str]:
    """The job's video encoder and the pixel format of its bit depth."""
    settings = job.video
    encoder = defs.video_encoders.get(settings.encoder)
    if encoder is None:
        raise PlanError(f"unknown video encoder {settings.encoder!r} (validation reports it)")
    pix_fmt = encoder.pix_fmts.get("10" if settings.bit_depth == 10 else "8")
    if pix_fmt is None:
        raise PlanError(f"{encoder.label} has no {settings.bit_depth}-bit mode")
    return encoder, pix_fmt


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
    _options(encoder, video, status, out)
    out.add(encoder.extra_args, {})
    out.params_raw = video.custom_params
    return out.render(encoder)
