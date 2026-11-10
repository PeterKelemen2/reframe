"""Custom encoder parameters that name files, and the checks that refuse them.

``VideoSettings.custom_params`` reaches FFmpeg either as an encoder params argument (x264,
x265, SVT-AV1), where a key that names a file makes the encoder read or write that file, or
as an own option ``-<name>:v:0`` (every other encoder). Own options are an allow-list, because
FFmpeg reads a name as one of its own options first. The file keys and the allowed options
are in ``data/custom_params.toml``.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from importlib import resources

__all__ = [
    "OWN_OPTION_NAME",
    "CustomParam",
    "CustomParamRules",
    "custom_param_rules",
    "dict_pairs",
    "file_key",
    "library_key_forms",
    "own_option_allowed",
    "split_custom_params",
    "whole_param",
]

#: An own option's name: letters, digits, ``_`` and ``-``. Refuses ``/filter`` (FFmpeg reads
#: its value from a file) and ``:`` (a stream specifier).
OWN_OPTION_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

_WHITESPACE = " \n\t\r"


@dataclass(frozen=True, slots=True)
class CustomParamRules:
    """``data/custom_params.toml``."""

    file_keys: Mapping[str, Mapping[str, str]]
    """Encoder id → folded key → what the encoder does with the file."""
    value_exceptions: Mapping[str, frozenset[str]]
    """Key → values the library takes as a name, not as a file."""
    value_contains: frozenset[str]
    """Keys of :attr:`value_exceptions` that the library matches against a part of the value;
    the others match the whole value."""
    codec_options: frozenset[str]
    """The generic encoder options (AVCodecContext)."""
    file_options: frozenset[str]
    """FFmpeg's own options that read or write a file: never passed."""
    unchecked_options: frozenset[str]
    """Private options that pass text to a library Reframe cannot check: never passed."""
    private_options: Mapping[str, frozenset[str]]
    """Encoder id → its recorded private options, for when the build's list is not known."""


@cache
def custom_param_rules() -> CustomParamRules:
    """The packaged rules (cached)."""
    data = resources.files("reframe.definitions") / "data" / "custom_params.toml"
    with data.open("rb") as f:
        raw = tomllib.load(f)
    ffmpeg = raw["ffmpeg"]
    match: dict[str, str] = raw.get("value_match", {})  # "whole" (the default) or "contains"
    return CustomParamRules(
        file_keys={
            encoder: {_fold(key): what for key, what in keys.items()}
            for encoder, keys in raw["file_keys"].items()
        },
        value_exceptions={
            _fold(key): frozenset(values) for key, values in raw["value_exceptions"].items()
        },
        value_contains=frozenset(_fold(key) for key, mode in match.items() if mode == "contains"),
        codec_options=frozenset(ffmpeg["codec_options"]),
        file_options=frozenset(ffmpeg["file_options"]),
        unchecked_options=frozenset(ffmpeg["unchecked_options"]),
        private_options={
            encoder: frozenset(names) for encoder, names in raw["private_options"].items()
        },
    )


@dataclass(frozen=True, slots=True)
class CustomParam:
    """One entry of ``VideoSettings.custom_params``: ``name`` and ``value`` as the command
    builder writes them, ``raw`` as typed."""

    name: str
    value: str
    raw: str
    continues: bool = False
    """The entry is the rest of the value typed before it: the ``:`` that split them is inside
    single quotes, or the drive colon of a Windows path (``csv=C:\\x`` gives ``csv=C`` and
    ``\\x``). A fix that removes a parameter removes all of it (:func:`whole_param`)."""


def _drive_letter(entry: str) -> bool:
    value = entry.partition("=")[2].strip()
    return len(value) == 1 and value.isascii() and value.isalpha()


def split_custom_params(text: str) -> list[CustomParam]:
    """The entries of a custom parameter string, split at an unescaped ``:``; ``\\`` escapes
    the next character. An entry without ``=`` is ``name=1``; empty entries are dropped."""
    segments: list[tuple[str, str, bool]] = []
    typed: list[str] = []
    plain: list[str] = []
    escaped = quoted = False
    for char in text.strip():
        if escaped:
            typed.append(char)
            plain.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
            typed.append(char)
        elif char == ":":
            segments.append(("".join(typed), "".join(plain), quoted))
            typed, plain = [], []
        else:
            quoted ^= char == "'"
            typed.append(char)
            plain.append(char)
    segments.append(("".join(typed), "".join(plain), False))
    params: list[CustomParam] = []
    for i, (raw, unescaped, _) in enumerate(segments):
        entry = unescaped.strip()
        if not entry:
            continue
        before = segments[i - 1] if i else None
        continues = before is not None and (
            before[2] or (raw.startswith(("\\", "/")) and _drive_letter(before[1]))
        )
        name, sep, value = entry.partition("=")
        params.append(
            CustomParam(
                name=name.strip().lstrip("-"),
                value=value.strip() if sep else "1",
                raw=raw,
                continues=continues,
            )
        )
    return params


def whole_param(params: Sequence[CustomParam], param: CustomParam) -> list[CustomParam]:
    """The entries of the parameter that ``param`` is part of: the entry it continues, and the
    entries that continue it (:attr:`CustomParam.continues`)."""
    start = end = next(i for i, p in enumerate(params) if p is param)
    while params[start].continues and start > 0:
        start -= 1
    while end + 1 < len(params) and params[end + 1].continues:
        end += 1
    return list(params[start : end + 1])


def _get_token(text: str, start: int, term: str) -> tuple[str, int]:
    i = start
    while i < len(text) and text[i] in _WHITESPACE:
        i += 1
    out: list[str] = []
    end = 0  # length of ``out`` that trailing-whitespace trimming must keep
    while i < len(text) and text[i] not in term:
        char = text[i]
        i += 1
        if char == "\\" and i < len(text):
            out.append(text[i])
            i += 1
            end = len(out)
        elif char == "'":
            while i < len(text) and text[i] != "'":
                out.append(text[i])
                i += 1
            if i < len(text):
                i += 1
                end = len(out)
        else:
            out.append(char)
    while len(out) > end and out[-1] in _WHITESPACE:
        out.pop()
    return "".join(out), i


def dict_pairs(text: str) -> list[tuple[str, str]]:
    """The ``(key, value)`` pairs FFmpeg reads from a dictionary option such as
    ``-x265-params`` (``av_dict_parse_string`` with ``=`` and ``:``). FFmpeg applies the whole
    text or none of it. The pairs are returned up to the first one FFmpeg refuses (no ``=``, an
    empty key or value), which is enough to find every key a library could see."""
    pairs: list[tuple[str, str]] = []
    i = 0
    while i < len(text):
        key, i = _get_token(text, i, "=")
        if not key or i >= len(text) or text[i] != "=":
            break
        value, i = _get_token(text, i + 1, ":")
        if not value:
            break
        pairs.append((key, value))
        if i < len(text):
            i += 1  # the ':'
    return pairs


def _fold(name: str) -> str:
    """The key as x264 and x265 read it: quotes and escapes removed, leading ``-`` dropped,
    ``_`` read as ``-``."""
    text = name.replace("'", "").replace("\\", "").strip().lstrip("-")
    return text.casefold().replace("_", "-")


def library_key_forms(name: str) -> set[str]:
    """The keys a library may read for ``name``: the folded key, and the key without a ``no-``
    or ``no`` prefix (x264 and x265 read ``nocsv`` as ``csv``)."""
    key = _fold(name)
    forms = {key}
    prefix = "no-" if key.startswith("no-") else "no"
    if key.startswith(prefix) and len(key) > len(prefix):
        forms.add(key.removeprefix(prefix))
    return forms


def _names_no_file(rules: CustomParamRules, key: str, value: str) -> bool:
    names = rules.value_exceptions.get(key)
    if not names:
        return False
    text = value.partition("\0")[0]  # the library reads a C string: up to a NUL
    if key in rules.value_contains:
        return any(name in text for name in names)
    return text in names


def file_key(encoder_id: str, name: str, value: str = "") -> str | None:
    """What the encoder does with the file that the params key ``name`` names, or ``None``.

    ``None`` when ``encoder_id`` has no such file key, or when the library takes ``value`` as a
    name. ``value`` is as the library reads it (after :func:`dict_pairs`), and the match is the
    one the library makes: the whole value, or a part of it (see ``value_match`` in the data
    file). A ``no`` prefix gives the library ``true`` or ``false``, so no name applies there."""
    rules = custom_param_rules()
    keys = rules.file_keys.get(encoder_id, {})
    typed = _fold(name)
    for form in sorted(library_key_forms(name)):
        what = keys.get(form)
        if what is None:
            continue
        if form == typed and _names_no_file(rules, form, value):
            continue
        return what
    return None


def own_option_allowed(encoder_id: str, name: str, build_options: Collection[str] = ()) -> bool:
    """Whether ``-<name>:v:0`` may be written for an encoder with no params argument.

    Allowed: a private option of the encoder (``build_options``: this build's list from encoder
    detection; empty: the recorded list), or a generic encoder option. Never an FFmpeg option
    that reads or writes a file."""
    rules = custom_param_rules()
    if OWN_OPTION_NAME.match(name) is None:
        return False
    if name in rules.file_options or name in rules.unchecked_options:
        return False
    private = build_options or rules.private_options.get(encoder_id, frozenset())
    return name in private or name in rules.codec_options
