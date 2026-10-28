"""Free filter text in a job (``FilterConfig.custom``), read the way FFmpeg's filtergraph parser
reads it, and the filters a web client may name there. FFmpeg puts the text into the video
graph as it is, so a filter that reads a file, opens a device or loads a plugin would run with
the server's rights."""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from reframe.definitions import Definitions, FilterDef
from reframe.models import FilterConfig

__all__ = ["ALLOWED_FILTERS", "GraphFilter", "GraphSyntaxError", "free_text_problem", "parse_graph"]

ALLOWED_FILTERS = frozenset(
    {
        # The filters of Reframe's own definitions, but libplacebo (custom_shader_path, lut,
        # shader_cache and extra_opts name files).
        "bwdif", "cas", "deblock", "decimate", "fieldmatch", "format", "hqdn3d", "hue", "idet",
        "nlmeans", "tonemap", "unsharp", "yadif", "zscale",
        # One video input, one video output, and no option that names a file, a device, a URL
        # or a plugin (`ffmpeg -h filter=<name>` of the pinned build).
        "atadenoise", "avgblur", "boxblur", "chromanr", "chromashift", "colorbalance",
        "colorchannelmixer", "colorcorrect", "colorhold", "colorize", "colorlevels",
        "colormatrix", "colorspace", "colortemperature", "convolution", "copy", "crop",
        "cropdetect", "dctdnoiz", "deband", "deflicker", "dejudder", "detelecine", "drawbox",
        "drawgrid", "edgedetect", "eq", "estdif", "exposure", "fade", "fftdnoiz", "field",
        "fieldorder", "fps", "framerate", "framestep", "fspp", "gblur", "gradfun", "grayworld",
        "hflip", "histeq", "hqx", "interlace", "kerndeint", "lenscorrection", "lut", "lutrgb",
        "lutyuv", "median", "minterpolate", "monochrome", "mpdecimate", "negate", "noise",
        "normalize", "null", "owdenoise", "pad", "perspective", "pixelize", "pp7", "pullup",
        "removegrain", "rgbashift", "rotate", "sab", "scale", "separatefields", "setdar",
        "setfield", "setparams", "setpts", "setrange", "setsar", "shuffleplanes", "smartblur",
        "spp", "swapuv", "tblend", "telecine", "tinterlace", "tmix", "tpad", "transpose",
        "trim", "vaguedenoiser", "vflip", "vibrance", "vignette", "w3fdif", "weave", "xbr",
    }
)  # fmt: skip

_SPACE = " \n\t\r"
_CUSTOM = "{custom}"
_FILE_KEY = re.compile(f"(?:^|:)[{_SPACE}]*/")
"""An option name that starts with ``/``: the ffmpeg tool reads that option's value from the
file the value names. A ``:`` the option parser reads as quoted matches too: when in doubt,
refuse."""


class GraphSyntaxError(ValueError):
    """Text that FFmpeg refuses, or reads in a way that cannot be checked (a quote that is not
    closed, a backslash at the end)."""


@dataclass(frozen=True, slots=True)
class GraphFilter:
    name: str
    """Without the ``@instance`` suffix."""
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    options: str = ""
    """After FFmpeg's first level of unquoting, as the filter's option parser gets them."""


def _skip(text: str, i: int) -> int:
    while i < len(text) and text[i] in _SPACE:
        i += 1
    return i


def _token(text: str, i: int, term: str) -> tuple[str, int]:
    """FFmpeg's ``av_get_token``: up to a character of ``term`` outside quotes; ``'…'`` and
    ``\\x`` lose their quoting, spaces around the token go."""
    i = _skip(text, i)
    out: list[str] = []
    kept = 0
    while i < len(text) and text[i] not in term:
        char = text[i]
        i += 1
        if char == "\\":
            if i == len(text):
                raise GraphSyntaxError("the text ends with a backslash")
            out.append(text[i])
            i += 1
            kept = len(out)
        elif char == "'":
            end = text.find("'", i)
            if end < 0:
                raise GraphSyntaxError("a quote is not closed")
            out.append(text[i:end])
            i = end + 1
            kept = len(out)
        else:
            out.append(char)
    while len(out) > kept and out[-1] in _SPACE:
        out.pop()
    return "".join(out), i


def _labels(text: str, i: int) -> tuple[tuple[str, ...], int]:
    labels: list[str] = []
    while i < len(text) and text[i] == "[":
        label, i = _token(text, i + 1, "]")
        if not label or i == len(text):
            raise GraphSyntaxError("a link label is empty or not closed")
        labels.append(label)
        i = _skip(text, i + 1)
    return tuple(labels), i


def _filter(text: str, i: int) -> tuple[GraphFilter, int]:
    inputs, i = _labels(text, i)
    name, i = _token(text, i, "=,;[")
    name = name.partition("@")[0]
    if not name:
        raise GraphSyntaxError("a filter has no name")
    options = ""
    if i < len(text) and text[i] == "=":
        options, i = _token(text, i + 1, "[],;")
    outputs, i = _labels(text, i)
    return GraphFilter(name, inputs, outputs, options), i


def parse_graph(text: str) -> list[list[GraphFilter]]:
    """The chains of a filtergraph (``;`` between chains, ``,`` between filters). A leading
    ``sws_flags=…;`` is read as a filter, not as FFmpeg's scaler flags. Raises
    :class:`GraphSyntaxError`."""
    chains: list[list[GraphFilter]] = []
    chain: list[GraphFilter] = []
    i = _skip(text, 0)
    while i < len(text):
        found, i = _filter(text, i)
        chain.append(found)
        i = _skip(text, i)
        if i == len(text):
            break
        if text[i] not in ",;":
            raise GraphSyntaxError(f"{text[i]!r} follows a filter")
        if text[i] == ";":
            chains.append(chain)
            chain = []
        i = _skip(text, i + 1)
    if chain:
        chains.append(chain)
    return chains


def _breaks_out(text: str) -> str | None:
    """Why ``text``, put after a filter's ``=``, would end that filter's options. (A quote
    left open makes the rest of the chain options: the parser refuses that.)"""
    quoted = False
    i = 0
    while i < len(text):
        char = text[i]
        if quoted:
            quoted = char != "'"
        elif char == "\\":
            if i + 1 == len(text):
                return "the text ends with a backslash"
            i += 1
        elif char == "'":
            quoted = True
        elif char in ",;[]":
            return f"{char!r} outside quotes would start another filter"
        i += 1
    return None


def _templates(fdef: FilterDef, implementation: str | None) -> Iterator[str]:
    """Every chain of ``fdef`` that takes the custom text. The preset and tune are not
    followed: the text is checked wherever it could go. Without a chosen implementation, any
    may run, depending on what the FFmpeg build has."""
    for impl in fdef.implementations:
        if implementation is not None and impl.id != implementation:
            continue
        for preset in impl.presets:
            chains = [preset.chain, *preset.tune_chains.values()]
            yield from (chain for chain in chains if chain is not None and _CUSTOM in chain)


def _chain_problem(template: str, text: str) -> str | None:
    if template.strip() != _CUSTOM:
        problem = _breaks_out(text)
        if problem is not None:
            return problem
    try:
        chains = parse_graph(template.replace(_CUSTOM, text))
    except GraphSyntaxError as exc:
        return f"FFmpeg's filter syntax cannot be checked here: {exc}"
    if len(chains) > 1:
        return "';' starts a second filter chain"
    for found in (found for chain in chains for found in chain):
        if found.inputs or found.outputs:
            return "link labels ([…]) are not allowed"
        if found.name not in ALLOWED_FILTERS:
            return f"the FFmpeg filter {found.name!r} is not allowed"
        if _FILE_KEY.search(found.options):
            return (
                f"an option name of {found.name!r} starts with '/' (FFmpeg then reads the "
                "value from a file)"
            )
    return None


def free_text_problem(filters: Mapping[str, FilterConfig], definitions: Definitions) -> str | None:
    """Why the free text of ``filters`` must not reach FFmpeg from a web client, naming the
    filter; ``None`` when every text is a chain of allowed filters."""
    for filter_id, config in filters.items():
        fdef = definitions.filters.get(filter_id)  # type: ignore[call-overload]
        if not config.custom or fdef is None:
            continue
        for template in _templates(fdef, config.implementation):
            problem = _chain_problem(template, config.custom)
            if problem is not None:
                return f"filters.{filter_id}: {problem}"
    return None
