"""Parse ``ffmpeg -encoders``, ``-filters`` and ``-h encoder=<name>`` (C-4). Pure.

The formats are checked against real output of FFmpeg n9.0.2 (the pinned BtbN build and the
Arch package), captured in ``testing/reframe_testing/fake_data/`` (``encoders.stdout.txt``,
``filters.stdout.txt``, ``help_encoder/*.stdout.txt``):

``-encoders``: a legend, a `` ------`` line, then one line per encoder::

     V....D libx265              libx265 H.265 / HEVC (codec hevc)
     A....D aac                  AAC (Advanced Audio Coding)

``-filters``: a legend, a ``  ------`` line, then one line per filter. FFmpeg 9 prints two
flag columns (``T.``, ``.S``); FFmpeg 7 printed three (``TSC``)::

     .. libplacebo        N->V       Apply various GPU filters from libplacebo
     .S zscale            V->V       Apply resizing, colorspace and bit depth conversion.

``-h encoder=<name>``: a header, capability lines, then one or more ``… AVOptions:`` sections.
An option is a line indented by two spaces (``  -preset   <int>  E..V…  … (from 0 to 9)``);
its named values are indented by five spaces. ``-h encoder=<unknown>`` exits with 0 and prints
``Codec '<name>' is not recognized by FFmpeg.``. FFmpeg 8 and 9 end the help with an empty
line and ``Exiting with exit code 0`` on stdout; it is ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

__all__ = [
    "EncoderHelp",
    "EncoderListing",
    "parse_encoder_help",
    "parse_encoders",
    "parse_filters",
]

MediaKind = Literal["video", "audio", "subtitle"]

_KINDS: dict[str, MediaKind] = {"V": "video", "A": "audio", "S": "subtitle"}
_ENCODER_LINE = re.compile(r"^\s*(?P<flags>[VAS][A-Z.]{5})\s+(?P<name>\S+)(?:\s+(?P<desc>.*))?$")
_FILTER_LINE = re.compile(r"^\s*(?P<flags>[A-Z.|]{2,3})\s+(?P<name>\S+)\s+(?P<io>\S*->\S*)(?:\s|$)")
_SEPARATOR = re.compile(r"^\s*-{6}\s*$")
_NOT_RECOGNIZED = re.compile(r"^Codec '(?P<name>[^']*)' is not recognized by FFmpeg\.")
_HEADER = re.compile(r"^Encoder (?P<name>\S+) \[(?P<desc>.*)\]:\s*$")
_OPTION = re.compile(r"^  -(?P<name>\S+)\s+<(?P<type>[^>]+)>\s+(?P<rest>.*)$")
_CONSTANT = re.compile(r"^ {3,}(?P<name>\S+)\s+(?P<value>-?\d\S*)?\s+[E.][D.][F.][V.]")
_RANGE = re.compile(r"\(from (?P<low>-?\d+) to (?P<high>-?\d+)\)")
#: Integer presets (``libsvtav1``: "from -2 to 13") are listed one by one up to this many.
MAX_RANGE_PRESETS = 64


@dataclass(frozen=True)
class EncoderListing:
    """One line of ``ffmpeg -encoders``."""

    name: str
    kind: MediaKind
    description: str = ""
    experimental: bool = False
    """The ``X`` flag: FFmpeg needs ``-strict experimental`` for it."""


@dataclass(frozen=True)
class EncoderHelp:
    """What ``ffmpeg -h encoder=<name>`` says about one encoder."""

    name: str
    description: str = ""
    private_options: list[str] = field(default_factory=list)
    """Every option of the ``AVOptions`` sections, in order, without the ``-``."""
    presets: list[str] = field(default_factory=list)
    """The values of ``-preset``: its named constants (``p1`` … ``p7``, ``veryfast`` …), or
    for an integer range without names the numbers (``libsvtav1``: ``-2`` … ``13``). Empty when
    the encoder takes a free string (``libx264``, ``libx265``: FFmpeg does not list them)."""
    pix_fmts: list[str] = field(default_factory=list)
    """``Supported pixel formats`` (``vaapi`` alone for VAAPI encoders, which take hardware
    frames)."""
    hardware_devices: list[str] = field(default_factory=list)
    """``Supported hardware devices`` (``cuda``, ``vaapi``, ``qsv``, ``amf``), without repeats."""


def parse_encoders(text: str) -> dict[str, EncoderListing]:
    """The encoders of ``ffmpeg -hide_banner -encoders`` by name; ``{}`` if the text has no
    list (not FFmpeg output)."""
    result: dict[str, EncoderListing] = {}
    started = False
    for line in text.splitlines():
        if not started:
            started = bool(_SEPARATOR.match(line))
            continue
        match = _ENCODER_LINE.match(line)
        if match is None:
            continue
        flags = match["flags"]
        result[match["name"]] = EncoderListing(
            name=match["name"],
            kind=_KINDS[flags[0]],
            description=(match["desc"] or "").strip(),
            experimental=flags[3] == "X",
        )
    return result


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
    encoder (``Codec '…' is not recognized by FFmpeg.``) or the text is not encoder help."""
    help_name: str | None = None
    description = ""
    options: list[str] = []
    presets: list[str] = []
    preset_range: tuple[int, int] | None = None
    pix_fmts: list[str] = []
    devices: list[str] = []
    current: str | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if _NOT_RECOGNIZED.match(line):
            return None
        if (header := _HEADER.match(line)) is not None:
            help_name, description = header["name"], header["desc"]
            continue
        stripped = line.strip()
        if stripped.startswith("Supported pixel formats:"):
            pix_fmts = stripped.split(":", 1)[1].split()
            continue
        if stripped.startswith("Supported hardware devices:"):
            devices = list(dict.fromkeys(stripped.split(":", 1)[1].split()))
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
    return EncoderHelp(
        name=help_name,
        description=description,
        private_options=options,
        presets=presets,
        pix_fmts=pix_fmts,
        hardware_devices=devices,
    )
