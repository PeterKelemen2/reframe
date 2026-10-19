"""Clean-up of text from the name. The word separator runs first, so *Space* and *Remove
common punctuation* give ``The Sopranos``, not HandBrake's ``TheSopranos``. The other options
follow the order of HandBrake's ``AutoNameHelper.CleanupSourceName``.
"""

from __future__ import annotations

import re

from reframe.models.naming import NamingOptions, WordSeparator

__all__ = ["SEPARATOR_CHARS", "clean_name_text", "convert_separator", "title_case"]

SEPARATOR_CHARS: dict[WordSeparator, str | None] = {
    "keep": None,
    "space": " ",
    "dot": ".",
    "underscore": "_",
}


def _letter(token: str) -> bool:
    return len(token) == 1 and token.isalpha()


def _number_end(token: str) -> bool:
    return re.search(r"(?:^|-)\d+$", token) is not None


def convert_separator(text: str, source: str | None, target: str | None) -> str:
    """Replace the word separator ``source`` with ``target`` (``None``: keep)."""
    if target is None or source is None or source == target:
        return text
    if source != ".":
        return text.replace(source, target)
    tokens = text.split(".")
    out = [tokens[0]]
    for i in range(1, len(tokens)):
        before, token = tokens[i - 1], tokens[i]
        if (_letter(before) and _letter(token)) or (_number_end(before) and token.isdigit()):
            out.append(".")  # S.H.I.E.L.D, 12.00
        elif _letter(before) and i >= 2 and _letter(tokens[i - 2]):
            out.append("." + target)  # the end of an acronym: "E.T. the"
        else:
            out.append(target)
        out.append(token)
    return "".join(out)


def title_case(text: str) -> str:
    """HandBrake's title case: lower-case everything, then capitalise the first letter or
    digit of each word (an apostrophe does not start a new word: ``They're``)."""
    out: list[str] = []
    in_word = False
    for char in text.lower():
        if char.isalnum():
            out.append(char if in_word else char.upper())
            in_word = True
        else:
            out.append(char)
            in_word = in_word and char == "'"
    return "".join(out)


def clean_name_text(text: str, separator: str | None, options: NamingOptions) -> str:
    """Apply the word separator and the HandBrake clean-up options to a text from the name."""
    text = convert_separator(text, separator, SEPARATOR_CHARS[options.word_separator])
    if options.replace_underscores:
        text = text.replace("_", " ")
    if options.remove_punctuation:
        text = text.replace("-", "").replace(",", "").replace(".", "")
    if options.title_case:
        text = title_case(text)
    return text
