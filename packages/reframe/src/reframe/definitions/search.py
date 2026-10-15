"""Search in the advanced encoder options (03 §Advanced encoder options: "Search covers labels,
CLI names and help text across all categories"). Pure.

``Reframe.jobs.search_options`` calls :func:`search_options` with the encoder's options.

Ranking (case-insensitive; each word of the query must match somewhere; an option's score is
the sum of its words' best scores, ties keep the definition order):

=====  ====================================================================
score  where the word matches
=====  ====================================================================
100    the key or the CLI name, exactly (``psy-rd``)
 80    the start of the key or the CLI name (``psy`` → ``psy-rd``, ``psy-rdoq``)
 70    the start of a word of the label (``psy`` → "Psy-RD strength")
 60    inside the key or the CLI name
 50    inside the label
 30    a choice (its value or label: ``umh``, "Hexagon")
 20    the help text
 10    the category ("loop" → every loop filter)
=====  ====================================================================

The CLI name is what the mapping writes: the params name (``psy-rd``), the private option
(``b_ref_mode``) or the FFmpeg argument without its dash (``bf``). A leading dash in the query
is ignored, so ``-bf`` finds ``bf``.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from reframe.definitions.models import EncoderOption

__all__ = ["cli_name", "search_options"]

_WORD_START = re.compile(r"[\w]+")


def cli_name(option: EncoderOption) -> str:
    """The name the option has on the command line: ``psy-rd``, ``b_ref_mode``, ``bf``."""
    mapping = option.mapping
    if mapping.kind == "ffmpeg_arg":
        return mapping.arg.lstrip("-")
    return mapping.name


def _word_score(option: EncoderOption, word: str) -> int:
    names = {option.key.casefold(), cli_name(option).casefold()}
    label = option.label.casefold()
    if word in names:
        return 100
    if any(name.startswith(word) for name in names):
        return 80
    if any(match.group().startswith(word) for match in _WORD_START.finditer(label)) or (
        label.startswith(word)
    ):
        return 70
    if any(word in name for name in names):
        return 60
    if word in label:
        return 50
    for choice in option.choices or []:
        if word in choice.value.casefold() or word in choice.label.casefold():
            return 30
    if word in option.help.casefold():
        return 20
    if word in option.category.casefold():
        return 10
    return 0


def search_options(options: Sequence[EncoderOption], query: str) -> list[EncoderOption]:
    """The options whose label, key, CLI name (the mapping's parameter or argument name) or
    help text matches ``query`` (case-insensitive), best matches first. An empty query gives
    every option in definition order. Pure."""
    words = [w.lstrip("-") for w in query.casefold().split()]
    words = [w for w in words if w]
    if not words:
        return list(options)
    scored: list[tuple[int, int, EncoderOption]] = []
    for index, option in enumerate(options):
        scores = [_word_score(option, word) for word in words]
        if all(scores):
            scored.append((-sum(scores), index, option))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [option for _score, _index, option in scored]
