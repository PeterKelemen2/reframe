"""Which custom encoder parameters Reframe passes to FFmpeg (C-6; decision 0035 "Follow-up
(core-complete review, 2026-10-16)"). Pure: package data only.

``VideoSettings.custom_params`` reaches FFmpeg in two ways (:mod:`reframe.command.video`):

- **A params argument** (x264, x265, SVT-AV1): the text as typed, at the end of
  ``-x265-params``. FFmpeg splits it like ``av_dict_parse_string`` (:func:`dict_pairs`) and the
  library reads every key. A key that names a file (x265 ``csv`` / ``analysis-save``, x264
  ``dump-yuv`` / ``stats``, …) would make the encoder read or write any file the user can, so
  :func:`file_key` names them (``data/custom_params.toml`` ``[file_keys]``, each checked with
  the encoder).
- **Own options** (every other encoder): each entry becomes ``-<name>:v:0 <value>``. FFmpeg
  reads such a name as one of its own options first (``-vstats_file``, ``-progress``,
  ``-passlogfile``, ``-/filter`` read or write files), so only an allow-list is safe
  (:func:`own_option_allowed`): the encoder's private options (``ffmpeg -h encoder=<id>``) and
  the generic encoder options (AVCodecContext, flags ``E..V``).

Validation (C-8, ``reframe.validation.video.video_custom_param_issues``) reports both, and the
dry run never runs with such a parameter.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Collection, Mapping
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
]

#: What an own option's name may look like: FFmpeg option names (``rc-lookahead``,
#: ``init_qpB``, ``2pass``). Refuses ``/filter`` (FFmpeg reads the value from a file), ``:``
#: (a stream specifier) and every other character.
OWN_OPTION_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

_WHITESPACE = " \n\t\r"


@dataclass(frozen=True, slots=True)
class CustomParamRules:
    """``data/custom_params.toml``."""

    file_keys: Mapping[str, Mapping[str, str]]
    """Encoder id → key (as :func:`library_key_forms` writes it) → what the encoder does with
    the file."""
    value_exceptions: Mapping[str, frozenset[str]]
    """Key → values that do not name a file (x265 ``scaling-list=default``)."""
    codec_options: frozenset[str]
    """The generic encoder options (AVCodecContext, ``E..V``)."""
    file_options: frozenset[str]
    """FFmpeg's own options that read or write a file: never passed."""
    unchecked_options: frozenset[str]
    """Private options that pass text to a library Reframe cannot check: never passed."""
    private_options: Mapping[str, frozenset[str]]
    """Encoder id → its private options as recorded (when detection has not read the build's
    list)."""


@cache
def custom_param_rules() -> CustomParamRules:
    """The packaged rules (cached)."""
    data = resources.files("reframe.definitions") / "data" / "custom_params.toml"
    with data.open("rb") as f:
        raw = tomllib.load(f)
    ffmpeg = raw["ffmpeg"]
    return CustomParamRules(
        file_keys={
            encoder: {_fold(key): what for key, what in keys.items()}
            for encoder, keys in raw["file_keys"].items()
        },
        value_exceptions={
            _fold(key): frozenset(values) for key, values in raw["value_exceptions"].items()
        },
        codec_options=frozenset(ffmpeg["codec_options"]),
        file_options=frozenset(ffmpeg["file_options"]),
        unchecked_options=frozenset(ffmpeg["unchecked_options"]),
        private_options={
            encoder: frozenset(names) for encoder, names in raw["private_options"].items()
        },
    )


# --------------------------------------------------------------------------- the typed text


@dataclass(frozen=True, slots=True)
class CustomParam:
    """One entry of ``VideoSettings.custom_params``: ``name`` and ``value`` as the command
    builder writes them (:func:`reframe.command.video.split_params`), ``raw`` as typed (a fix
    drops one entry and keeps the others' text)."""

    name: str
    value: str
    raw: str


def split_custom_params(text: str) -> list[CustomParam]:
    """The entries of a custom parameter string, split at an unescaped ``:``; ``\\`` escapes
    the next character (``\\:`` keeps a colon); an entry without ``=`` is ``name=1``; empty
    entries are dropped. The builder's :func:`~reframe.command.video.split_params` rule
    exactly (a test keeps them equal)."""
    segments: list[tuple[str, str]] = []
    typed: list[str] = []
    plain: list[str] = []
    escaped = False
    for char in text.strip():
        if escaped:
            typed.append(char)
            plain.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
            typed.append(char)
        elif char == ":":
            segments.append(("".join(typed), "".join(plain)))
            typed, plain = [], []
        else:
            typed.append(char)
            plain.append(char)
    segments.append(("".join(typed), "".join(plain)))
    params: list[CustomParam] = []
    for raw, unescaped in segments:
        entry = unescaped.strip()
        if not entry:
            continue
        name, sep, value = entry.partition("=")
        params.append(
            CustomParam(name=name.strip().lstrip("-"), value=value.strip() if sep else "1", raw=raw)
        )
    return params


def _get_token(text: str, start: int, term: str) -> tuple[str, int]:
    """FFmpeg's ``av_get_token``: leading whitespace skipped, ``\\`` escapes a character,
    ``'…'`` quotes, trailing whitespace (outside quotes and escapes) dropped; stops at a
    character of ``term``. The token and the index where it stopped."""
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
    ``-x265-params`` (``av_dict_parse_string(…, "=", ":")``, which applies the whole text or
    nothing). Pairs are returned up to the first one FFmpeg refuses (no ``=``, an empty key or
    value): enough to find every key a library could see."""
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


# --------------------------------------------------------------------------- the checks


def _fold(name: str) -> str:
    """``--Analysis_Save`` → ``analysis-save`` (x264 and x265 read ``_`` as ``-``; quotes and
    escapes are FFmpeg's)."""
    text = name.replace("'", "").replace("\\", "").strip().lstrip("-")
    return text.casefold().replace("_", "-")


def library_key_forms(name: str) -> set[str]:
    """The keys a library may read for ``name``: folded (:func:`_fold`), and without a ``no-``
    or ``no`` prefix (x264 and x265 read ``nocsv`` / ``no-csv`` as ``csv``)."""
    key = _fold(name)
    forms = {key}
    prefix = "no-" if key.startswith("no-") else "no"
    if key.startswith(prefix) and len(key) > len(prefix):
        forms.add(key.removeprefix(prefix))
    return forms


def file_key(encoder_id: str, name: str, value: str = "") -> str | None:
    """What the encoder does with the file that the params-argument key ``name`` names
    (``None``: not a file key of ``encoder_id``, or a value that names no file)."""
    rules = custom_param_rules()
    keys = rules.file_keys.get(encoder_id, {})
    for form in sorted(library_key_forms(name)):
        what = keys.get(form)
        if what is None:
            continue
        if value.strip().strip("'") in rules.value_exceptions.get(form, frozenset()):
            continue
        return what
    return None


def own_option_allowed(encoder_id: str, name: str, build_options: Collection[str] = ()) -> bool:
    """Whether ``-<name>:v:0`` may be written for an encoder without a params argument: a
    private option of the encoder (``build_options``: this build's list from encoder detection;
    empty: the recorded list) or a generic encoder option, and never one of FFmpeg's own options
    that read or write a file."""
    rules = custom_param_rules()
    if OWN_OPTION_NAME.match(name) is None:
        return False
    if name in rules.file_options or name in rules.unchecked_options:
        return False
    private = build_options or rules.private_options.get(encoder_id, frozenset())
    return name in private or name in rules.codec_options
