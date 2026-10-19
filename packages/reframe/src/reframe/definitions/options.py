"""How the advanced options of a job resolve: defaults, the condition context, and which options
are written. Pure.

The command builder and validation both use these functions, so an option that validation calls
inactive is one that the builder leaves out.
"""

from __future__ import annotations

from collections.abc import Mapping

from reframe.definitions.models import Condition, EncoderOption, VideoEncoderDef
from reframe.models.job import AverageBitrate, OptionValue, VideoSettings

__all__ = [
    "describe_condition",
    "effective_option",
    "option_context",
    "option_default",
    "unmet_conditions",
]


def option_default(option: EncoderOption, preset: str | None) -> OptionValue | None:
    """The value the encoder uses when the job does not set ``option``: the fixed default,
    the speed preset's value (``None`` when the preset does not use the option), or ``None``
    when the encoder decides. Tunes are not applied (the tables are per preset)."""
    default = option.default
    if default.kind == "fixed":
        return default.value
    if default.kind == "preset":
        return default.values.get(preset) if preset is not None else None
    return None


def option_context(encoder: VideoEncoderDef, video: VideoSettings) -> dict[str, OptionValue | None]:
    """The values that the ``requires`` conditions read. ``preset`` falls back to the encoder's
    default preset, and each ``option:<key>`` falls back to :func:`option_default`."""
    rc = video.rate_control
    preset = video.preset or (encoder.presets.default if encoder.presets else None)
    context: dict[str, OptionValue | None] = {
        "rate_control": rc.mode,
        "two_pass": isinstance(rc, AverageBitrate) and rc.two_pass,
        "bit_depth": video.bit_depth,
        "preset": preset,
        "tune": video.tune,
    }
    for option in encoder.options:
        value = video.advanced.get(option.key)
        context[f"option:{option.key}"] = (
            value if value is not None else option_default(option, preset)
        )
    return context


def effective_option(
    encoder: VideoEncoderDef, video: VideoSettings, key: str
) -> OptionValue | None:
    """The value of option ``key`` for this job: the job's, else the default
    (:func:`option_default`); ``None`` when unknown."""
    option = encoder.option(key)
    if option is None:
        return None
    if key in video.advanced:
        return video.advanced[key]
    preset = video.preset or (encoder.presets.default if encoder.presets else None)
    return option_default(option, preset)


def unmet_conditions(
    option: EncoderOption, context: Mapping[str, OptionValue | None]
) -> list[Condition]:
    """The conditions of ``option.requires`` that do not hold (empty: the option is written)."""
    return [c for c in option.requires if not c.matches(context)]


def _value_text(option: EncoderOption | None, value: OptionValue) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    if option is not None and option.choices is not None:
        found = next((c for c in option.choices if c.value == str(value)), None)
        if found is not None:
            return found.label
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


_FIELD_LABELS = {
    "rate_control": "the rate control",
    "two_pass": "2-pass",
    "bit_depth": "the bit depth",
    "preset": "the speed preset",
    "tune": "the tune",
}
_RATE_CONTROL = {"quality": "constant quality", "bitrate": "average bitrate"}


def describe_condition(condition: Condition, encoder: VideoEncoderDef) -> str:
    """What the condition asks for, in words, for messages (``"SAO (sao) on"``)."""
    other: EncoderOption | None = None
    if condition.field.startswith("option:"):
        key = condition.field.removeprefix("option:")
        other = encoder.option(key)
        subject = f"{other.label} ({key})" if other is not None else key
    else:
        subject = _FIELD_LABELS.get(condition.field, condition.field)
    values = condition.value if isinstance(condition.value, list) else [condition.value]
    if condition.field == "rate_control":
        texts = [_RATE_CONTROL.get(str(v), str(v)) for v in values]
    elif condition.field == "two_pass":
        texts = ["on" if v else "off" for v in values]
    else:
        texts = [_value_text(other, v) for v in values]
    joined = " or ".join(texts)
    if condition.op in ("ne", "not_in"):
        return f"{subject} not {joined}"
    return f"{subject} {joined}"
