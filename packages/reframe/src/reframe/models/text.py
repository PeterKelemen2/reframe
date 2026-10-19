"""Text that can hold a byte of a file name that is not UTF-8.

Python keeps such a byte as a lone surrogate (PEP 383: 0xFF is ``\\udcff``), which UTF-8 and
Pydantic's ``model_dump_json`` cannot write. Display text (:data:`DisplayText`) shows it as
``�``. Data (paths, patch values) keeps it, so the file is found again, and :func:`json_text`
writes it as an escape.
"""

from __future__ import annotations

import json
import re
from typing import Annotated

from pydantic import AfterValidator, BaseModel, PlainSerializer

__all__ = ["UNDECODABLE_REPLACEMENT", "DisplayText", "json_text", "replace_undecodable"]

#: What a byte that is not UTF-8 becomes in display text (U+FFFD, the replacement character).
UNDECODABLE_REPLACEMENT = "\ufffd"
#: A lone surrogate: a POSIX name byte that is not UTF-8 (``surrogateescape``: 0xFF → ``\udcff``)
#: or an unpaired UTF-16 surrogate of a Windows name.
_SURROGATE = re.compile("[\ud800-\udfff]")


def replace_undecodable(text: str) -> str:
    """``text`` with every byte that is not UTF-8 (a lone surrogate) replaced with ``�``.
    One code point becomes one code point, so positions in the text stay the same."""
    return _SURROGATE.sub(UNDECODABLE_REPLACEMENT, text)


#: Free text for people: messages, reasons, notes, labels. A byte that is not UTF-8 becomes
#: ``�`` when the model is validated and again when it is dumped (text set after validation).
DisplayText = Annotated[
    str, AfterValidator(replace_undecodable), PlainSerializer(replace_undecodable, return_type=str)
]


def _escape(match: re.Match[str]) -> str:
    return f"\\u{ord(match[0]):04x}"


def json_text(
    value: object,
    *,
    ensure_ascii: bool = True,
    indent: int | None = None,
    separators: tuple[str, str] | None = None,
) -> str:
    """``value`` (a model, or JSON data such as ``model_dump(mode="json")``) as JSON text that
    is valid UTF-8. A lone surrogate is written as an escape (``\\udcff``), which ``json.loads``
    and JavaScript's ``JSON.parse`` read back as the same string. Read a model back with
    ``model_validate(json.loads(text))``: ``model_validate_json`` rejects the escape.

    ``ensure_ascii=False`` writes the other characters that are not ASCII as they are.
    """
    data = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    text = json.dumps(data, ensure_ascii=ensure_ascii, indent=indent, separators=separators)
    return text if ensure_ascii else _SURROGATE.sub(_escape, text)
