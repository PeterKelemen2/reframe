"""Quality conversion between encoders (C-6; used by C-8's "use the closest encoder" fix).

Each encoder's :class:`~reframe.definitions.models.QualityMode` has a ``scale``: points
``(value, x264 RF equivalent)``. A value is mapped to the common scale through the source
encoder's points and back through the target encoder's points (piecewise linear), then
clamped to the target range and rounded to its step. The result is approximate
(03 §Missing encoder behaviour: "a note says that the result is approximate").
"""

from __future__ import annotations

from reframe.definitions.loader import load_definitions
from reframe.definitions.models import Definitions, QualityMode, interpolate

__all__ = ["convert_quality", "round_to_step"]


def round_to_step(value: float, mode: QualityMode) -> float:
    """``value`` clamped to ``mode``'s range and rounded to its step."""
    clamped = min(max(value, mode.min), mode.max)
    steps = round((clamped - mode.min) / mode.step)
    result = mode.min + steps * mode.step
    return round(min(max(result, mode.min), mode.max), 6)


def _mode(definitions: Definitions, encoder_id: str) -> QualityMode:
    encoder = definitions.video_encoders.get(encoder_id)
    if encoder is None:
        raise KeyError(f"unknown video encoder {encoder_id!r}")
    if encoder.rate_control.quality is None:
        raise ValueError(f"{encoder_id} has no constant-quality mode")
    return encoder.rate_control.quality


def convert_quality(
    value: float,
    from_encoder: str,
    to_encoder: str,
    *,
    definitions: Definitions | None = None,
) -> float:
    """``value`` on ``from_encoder``'s quality scale, converted to ``to_encoder``'s.

    Raises ``KeyError`` for an unknown encoder id and ``ValueError`` for an encoder without
    a constant-quality mode (both are programming errors: the caller has the definitions).
    """
    defs = definitions if definitions is not None else load_definitions()
    source, target = _mode(defs, from_encoder), _mode(defs, to_encoder)
    if from_encoder == to_encoder:
        return round_to_step(value, target)
    clamped = min(max(value, source.min), source.max)
    common = interpolate(source.scale, clamped)
    inverse = [(y, x) for x, y in target.scale]
    return round_to_step(interpolate(inverse, common), target)
