"""Clean-up of text that comes from the name (03 §Output naming → Options).

- **Word separator** (Reframe): Keep source · Space · Dot · Underscore. The source separator is
  the one of the parsed name (:func:`reframe.naming.parse.detect_separator`). Dots that are not
  word separators stay: between the letters of an acronym (``S.H.I.E.L.D``, ``E.T.``) and
  between numbers (``12.00``, ``1.23.45``, ``AM-1.00``).
- **HandBrake parity**, in HandBrake's order (``AutoNameHelper.CleanupSourceName``): replace
  underscores with spaces; remove dashes, commas and periods; title case (HandBrake lower-cases
  the text, then capitalises each word).

The word separator runs first, so *Space* + *Remove common punctuation* gives
``The Sopranos``, not HandBrake's ``TheSopranos``.
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
    """A number, or text that ends with ``-`` and a number (``12``, ``AM-1``)."""
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
