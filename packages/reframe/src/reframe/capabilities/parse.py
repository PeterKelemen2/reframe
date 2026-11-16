"""Parse ``ffmpeg -encoders``, ``-filters`` and ``-h encoder=<name>``. Pure.

The formats are FFmpeg's real output, as captured in ``testing/reframe_testing/fake_data/``
and recorded in ``testdata/README.md``. The help can end with an ``Exiting with exit code 0``
line on stdout: the parser ignores it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

__all__ = [
    "EncoderHelp",
    "parse_encoder_help",
    "parse_encoders",
    "parse_filters",
]

_ENCODER_LINE = re.compile(r"^\s*(?P<flags>[VAS][A-Z.]{5})\s+(?P<name>\S+)(?:\s+(?P<desc>.*))?$")
_FILTER_LINE = re.compile(r"^\s*(?P<flags>[A-Z.|]{2,3})\s+(?P<name>\S+)\s+(?P<io>\S*->\S*)(?:\s|$)")
_SEPARATOR = re.compile(r"^\s*-{6}\s*$")
_NOT_RECOGNIZED = re.compile(r"^Codec '(?P<name>[^']*)' is not recognized by FFmpeg\.")
_HEADER = re.compile(r"^Encoder (?P<name>\S+) \[(?P<desc>.*)\]:\s*$")
_OPTION = re.compile(r"^  -(?P<name>\S+)\s+<(?P<type>[^>]+)>\s+(?P<rest>.*)$")
_CONSTANT = re.compile(r"^ {3,}(?P<name>\S+)\s+(?P<value>-?\d\S*)?\s+[E.][D.][F.][V.]")
_RANGE = re.compile(r"\(from (?P<low>-?\d+) to (?P<high>-?\d+)\)")
#: An integer ``-preset`` range is listed value by value only when it is shorter than this.
MAX_RANGE_PRESETS = 64


@dataclass(frozen=True)
class EncoderHelp:
    """What ``ffmpeg -h encoder=<name>`` says about one encoder."""

    private_options: list[str] = field(default_factory=list)
    """Every option of the ``AVOptions`` sections, in order, without the ``-``."""
    presets: list[str] = field(default_factory=list)
    """The values of ``-preset``: its named constants, or the numbers of an integer range
    without names. Empty when FFmpeg lists none (the encoder takes a free string)."""
    pix_fmts: list[str] = field(default_factory=list)
    """``Supported pixel formats`` (``vaapi`` alone for VAAPI encoders, which take hardware
    frames)."""


def parse_encoders(text: str) -> frozenset[str]:
    """The encoder names of ``ffmpeg -hide_banner -encoders``; empty if the text has no
    list (not FFmpeg output)."""
    names: set[str] = set()
    started = False
    for line in text.splitlines():
        if not started:
            started = bool(_SEPARATOR.match(line))
            continue
        match = _ENCODER_LINE.match(line)
        if match is not None:
            names.add(match["name"])
    return frozenset(names)


def parse_filters(text: str) -> list[str]:
    """Filter names of ``ffmpeg -hide_banner -filters``, sorted; ``[]`` if there is no list."""
    names: set[str] = set()
    started = False
    for line in text.splitlines():
        if not started:
            started = bool(_SEPARATOR.match(line))
            continue
        match = _FILTER_LINE.match(line)
        if match is not None:
            names.add(match["name"])
    return sorted(names)


def parse_encoder_help(text: str) -> EncoderHelp | None:
    """Parse ``ffmpeg -hide_banner -h encoder=<name>``; ``None`` when FFmpeg does not know the
    encoder or the text is not encoder help."""
    help_name: str | None = None
    options: list[str] = []
    presets: list[str] = []
    preset_range: tuple[int, int] | None = None
    pix_fmts: list[str] = []
    current: str | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if _NOT_RECOGNIZED.match(line):
            return None
        if (header := _HEADER.match(line)) is not None:
            help_name = header["name"]
            continue
        stripped = line.strip()
        if stripped.startswith("Supported pixel formats:"):
            pix_fmts = stripped.split(":", 1)[1].split()
            continue
        if (option := _OPTION.match(line)) is not None:
            current = option["name"]
            if current not in options:
                options.append(current)
            if current == "preset" and option["type"] == "int":
                found = _RANGE.search(option["rest"])
                if found is not None:
                    preset_range = (int(found["low"]), int(found["high"]))
            continue
        if current == "preset" and (constant := _CONSTANT.match(line)) is not None:
            if constant["name"] not in presets:
                presets.append(constant["name"])
            continue
        if line and not line.startswith(" "):
            current = None  # a new section ("… AVOptions:") or the end
    if help_name is None:
        return None
    if not presets and preset_range is not None:
        low, high = preset_range
        if 0 <= high - low < MAX_RANGE_PRESETS:
            presets = [str(value) for value in range(low, high + 1)]
    return EncoderHelp(private_options=options, presets=presets, pix_fmts=pix_fmts)
