"""Exceptions that core packages raise below :mod:`reframe.service`, which re-exports them."""

from __future__ import annotations

__all__ = ["ReframeClosedError"]


class ReframeClosedError(RuntimeError):
    """The facade was used after :meth:`Reframe.close`."""

    def __init__(self) -> None:
        super().__init__("this Reframe instance is closed")
