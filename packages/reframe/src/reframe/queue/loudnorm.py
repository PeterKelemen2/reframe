"""The ``loudnorm`` measurements of ``analyse`` steps.

Each analyse step prints one JSON block of measurements on stderr. Every key is stored as
``<measurement id>.<key>``, for example ``a0.input_i``.

A silent track measures ``-inf`` or ``inf``, and the second pass refuses those values. The
clamping keeps each value in the range that loudnorm accepts. A non-finite ``target_offset``
becomes 0, not the top of its range: ``offset=99`` turns a near-silent track into full-scale
noise.
"""

from __future__ import annotations

import json
import math
import re

__all__ = ["LIMITS", "MeasureError", "clamp", "parse_blocks"]

#: Measured key → (lowest, highest) value that the second pass accepts.
LIMITS: dict[str, tuple[float, float]] = {
    "input_i": (-99.0, 0.0),
    "input_tp": (-99.0, 99.0),
    "input_lra": (0.0, 99.0),
    "input_thresh": (-99.0, 0.0),
    "target_offset": (-99.0, 99.0),
}
#: The value of a key when the measurement is infinite and the range end would be harmful.
_NOT_FINITE: dict[str, float] = {"target_offset": 0.0}
#: NaN (never seen; a defence): loudnorm's own defaults, which mean "not measured".
_UNKNOWN: dict[str, float] = {
    "input_i": 0.0,
    "input_tp": 99.0,
    "input_lra": 0.0,
    "input_thresh": -70.0,
    "target_offset": 0.0,
}

_BLOCK = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.S)


class MeasureError(ValueError):
    """The step printed no usable ``loudnorm`` block."""


def parse_blocks(stderr: str) -> list[dict[str, str]]:
    """Every ``loudnorm`` JSON block in ``stderr``, in order (values as strings)."""
    blocks: list[dict[str, str]] = []
    for match in _BLOCK.finditer(stderr):
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise MeasureError(f"the loudnorm result is not valid JSON ({exc})") from exc
        if not isinstance(data, dict):
            raise MeasureError("the loudnorm result is not a JSON object")
        blocks.append({str(key): str(value) for key, value in data.items()})
    return blocks


def _format(value: float) -> str:
    return f"{value:.2f}"


def clamp(block: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """The block with the second-pass values put into loudnorm's ranges, and a note per
    changed value."""
    result = dict(block)
    notes: list[str] = []
    for key, (low, high) in LIMITS.items():
        text = block.get(key)
        if text is None:
            continue
        try:
            value = float(text)
        except ValueError as exc:
            raise MeasureError(f"loudnorm printed {key} = {text!r}, not a number") from exc
        if math.isnan(value):
            new = _UNKNOWN[key]
        elif math.isinf(value):
            new = _NOT_FINITE.get(key, low if value < 0 else high)
        else:
            new = min(max(value, low), high)
        if new != value:
            result[key] = _format(new)
            notes.append(f"{key} {text} → {result[key]}")
    return result, notes
