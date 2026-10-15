"""Search in the advanced encoder options (03 §Advanced encoder options: "Search covers labels,
CLI names and help text across all categories").

Contract stub: built by the C-6 option-sets task (wave 1e). ``Reframe.jobs.search_options``
calls it.
"""

from __future__ import annotations

from collections.abc import Sequence

from reframe.definitions.models import EncoderOption

__all__ = ["search_options"]


def search_options(options: Sequence[EncoderOption], query: str) -> list[EncoderOption]:
    """The options whose label, key, CLI name (the mapping's parameter or argument name) or
    help text matches ``query`` (case-insensitive), best matches first. An empty query gives
    every option in definition order. Pure."""
    raise NotImplementedError("C-6 option search")
