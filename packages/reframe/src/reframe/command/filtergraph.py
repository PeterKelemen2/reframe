"""The video filter graph (05 §C-7, 03 §Filters, decisions 0009, 0010, 0013).

**Order.** The fixed order of 03 §Filters (``Definitions.filter_order``), with the stages of
C-5's geometry (decision 0009) and the burn-in of decision 0013::

    detelecine → interlace detection → deinterlace → denoise → deblock
    → crop [→ bitmap subtitle overlay] → transpose → hflip     ("crop" stage)
    → custom → scale → setsar                                  ("scale" stage)
    → tone mapping → colorspace [→ HDR side data removed]
    → sharpen → chroma smooth → grayscale
    [→ text subtitles burned in]
    → format / hardware upload                                  ("format" stage)

- ``setparams`` with the probed or assumed colour comes right before an implementation that
  needs tagged input (``zscale``), when the source does not say its colour.
- After tone mapping or a colour conversion of an HDR source, ``sidedata`` filters remove the
  HDR metadata of the frames (mastering display, content light level, HDR10+, Dolby Vision):
  otherwise the encoder writes the source's HDR10 metadata into the SDR output (FFmpeg
  n9.0.2 does, see ``testdata/README.md`` "Command builder (C-7)").
- The ``format`` stage is the encoder's software pixel format (``format=yuv420p10le``) or the
  hardware encoder's filter tail (``format=nv12,hwupload``).

**Escaping.** A filter graph is parsed twice: the graph parser splits filters at
``[ ] , ;`` and the option parser splits ``key=value`` pairs at ``:``. Both understand
backslash escapes and single quotes. :func:`quote_value` escapes a value for the option
parser (``\\`` before ``\\ ' :``) and then quotes it for the graph parser (``'…'``, with a
quote written as ``'\\''``), the form of the FFmpeg documentation:
``subtitles=filename='C\\:/Movies/Film.srt'``. Windows paths are written with forward
slashes (:func:`filter_path`). ``tests/command/test_filtergraph.py`` runs real FFmpeg on file
names with every special character.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import PurePath, PureWindowsPath

from reframe.command.errors import PlanError
from reframe.definitions import Definitions, FilterDef, FilterImplementation
from reframe.models import (
    CapabilitySnapshot,
    FilterConfig,
    Geometry,
    HdrFormat,
    VideoStream,
)

__all__ = [
    "HDR_SIDE_DATA",
    "BitmapBurn",
    "TextBurn",
    "VideoGraph",
    "assumed_colour",
    "build_video_graph",
    "escape_value",
    "filter_available",
    "filter_path",
    "keeps_hdr",
    "quote_value",
    "subtitles_filter",
]

#: Frame side data that describes HDR and must not reach an SDR output (``sidedata`` types).
HDR_SIDE_DATA = (
    "MASTERING_DISPLAY_METADATA",
    "CONTENT_LIGHT_LEVEL",
    "DYNAMIC_HDR_PLUS",
    "DOVI_RPU_BUFFER",
    "DOVI_METADATA",
    "DYNAMIC_HDR_VIVID",
)
#: ffprobe colour values that mean "not known".
_UNKNOWN_COLOUR = frozenset({"unknown", "unspecified", "reserved", ""})


# --------------------------------------------------------------------------- escaping


def escape_value(text: str) -> str:
    """Escape a value for FFmpeg's option parser (``av_get_token``): a backslash before
    ``\\``, ``'`` and ``:``. Also the form for ``-x265-params`` / ``-svtav1-params`` values."""
    return "".join("\\" + c if c in "\\':" else c for c in text)


def quote_value(text: str) -> str:
    """A filter option value as one graph token: :func:`escape_value`, then single quotes for
    the graph parser (a quote inside becomes ``'\\''``)."""
    return "'" + escape_value(text).replace("'", "'\\''") + "'"


def filter_path(path: PurePath) -> str:
    """A path for a filter argument: Windows paths with forward slashes (``C:/Movies/x.srt``;
    FFmpeg opens them on Windows), other paths unchanged."""
    if isinstance(path, PureWindowsPath):
        return path.as_posix()
    return str(path)


def subtitles_filter(
    path: PurePath, *, stream: int | None = None, charenc: str | None = None
) -> str:
    """``subtitles=filename='…'[:si=N][:charenc=…]`` (``si``: the index among the file's
    subtitle streams)."""
    parts = [f"subtitles=filename={quote_value(filter_path(path))}"]
    if stream is not None:
        parts.append(f"si={stream}")
    if charenc:
        parts.append(f"charenc={quote_value(charenc)}")
    return ":".join(parts)


# --------------------------------------------------------------------------- availability


def filter_available(caps: CapabilitySnapshot, definitions: Definitions) -> dict[str, bool]:
    """Which FFmpeg filters of the definitions this build can run, for
    :meth:`FilterDef.implementation_for`.

    A filter that needs Vulkan (``libplacebo``) counts only when its run test passed
    (``usable_filter`` is ``True``, decision 0021). Any other filter counts unless the build is
    known not to have it (a filter list that was not read assumes it is there).
    """
    vulkan = {
        name
        for f in definitions.filters.values()
        for impl in f.implementations
        if impl.needs_vulkan
        for name in impl.filters
    }
    names = {
        name for f in definitions.filters.values() for i in f.implementations for name in i.filters
    }
    result: dict[str, bool] = {}
    for name in sorted(names):
        usable = caps.usable_filter(name)
        result[name] = usable is True if name in vulkan else usable is not False
    return result


# --------------------------------------------------------------------------- colour


def _known(value: str | None) -> str | None:
    return None if value is None or value in _UNKNOWN_COLOUR else value


def _is_hdr(video: VideoStream) -> bool:
    return video.hdr is not None and bool(video.hdr.formats)


def assumed_colour(video: VideoStream) -> tuple[str, str, str]:
    """``(primaries, transfer, matrix)``: the probed values, with what is unknown filled in by
    the usual standard for the picture (HDR: BT.2020 PQ, or HLG; up to 480 lines: BT.601
    NTSC; up to 576 lines: BT.601 PAL; else BT.709)."""
    if _is_hdr(video):
        assert video.hdr is not None
        hlg = HdrFormat.HLG in video.hdr.formats
        defaults = ("bt2020", "arib-std-b67" if hlg else "smpte2084", "bt2020nc")
    elif video.height <= 480:
        defaults = ("smpte170m", "smpte170m", "smpte170m")
    elif video.height <= 576:
        defaults = ("bt470bg", "smpte170m", "bt470bg")
    else:
        defaults = ("bt709", "bt709", "bt709")
    c = video.color
    return (
        _known(c.primaries) or defaults[0],
        _known(c.transfer) or defaults[1],
        _known(c.matrix) or defaults[2],
    )


def _setparams(video: VideoStream) -> str | None:
    """``setparams`` for the colour values the source does not say (``None``: it says all)."""
    c = video.color
    if _known(c.primaries) and _known(c.transfer) and _known(c.matrix):
        return None
    primaries, transfer, matrix = assumed_colour(video)
    return f"setparams=color_primaries={primaries}:color_trc={transfer}:colorspace={matrix}"


def keeps_hdr(video: VideoStream, filters: Mapping[str, FilterConfig], bit_depth: int) -> bool:
    """The output stays HDR: an HDR source, no tone mapping, no colour conversion, 10-bit
    (C-16's ``{hdr}`` uses the same rule, without the colour conversion)."""
    return (
        _is_hdr(video) and "tonemap" not in filters and "colorspace" not in filters
        and bit_depth == 10
    )  # fmt: skip


# --------------------------------------------------------------------------- burn-in


@dataclass(frozen=True, slots=True)
class TextBurn:
    """A text subtitle burned in with the ``subtitles`` filter."""

    path: PurePath
    """The file that holds the subtitles (the source, or an external file)."""
    stream: int | None
    """``si``: index among the file's subtitle streams (``None`` for an external file)."""
    charenc: str | None = None
    shift: float = 0.0
    """Seconds added to the frame times while the filter runs (the range start minus the
    external file's offset): the filter reads its file from the start, but after ``-ss`` the
    frames start at 0."""


@dataclass(frozen=True, slots=True)
class BitmapBurn:
    """A bitmap subtitle (PGS, VobSub) burned in with ``overlay``."""

    input_label: str
    """The subtitle stream in the graph: ``0:5`` (source) or ``1:0`` (an external ``.sup``)."""
    canvas: tuple[int, int] | None = None
    """The subtitle canvas size, when it is known and differs from the picture: it is scaled
    to the picture first."""


# --------------------------------------------------------------------------- the graph


@dataclass(slots=True)
class VideoGraph:
    """The video filters: a simple chain (``-filter:v:0``) or a complex graph
    (``-filter_complex`` with the output label ``[v]``)."""

    chain: str | None = None
    complex: str | None = None
    hdr_removed: bool = False
    """The graph removes the HDR metadata (tone mapping or a colour conversion of HDR)."""
    filters: list[str] = field(default_factory=list)
    """The filter ids used, in order (for descriptions and tests)."""

    OUTPUT_LABEL = "[v]"


def _crop_stage(g: Geometry) -> tuple[list[str], list[str]]:
    """The crop (before a bitmap overlay) and the rotation and flip (after it)."""
    c = g.crop
    crop = (
        [f"crop={g.cropped_width}:{g.cropped_height}:{c.left}:{c.top}"]
        if any((c.top, c.bottom, c.left, c.right))
        else []
    )
    turn = {0: [], 90: ["transpose=clock"], 180: ["hflip", "vflip"], 270: ["transpose=cclock"]}
    after = list(turn[g.filter_rotation])
    if g.flip_horizontal:
        after.append("hflip")
    return crop, after


def _scale_stage(g: Geometry, scaler: str) -> list[str]:
    sar = g.output_sar
    return [
        f"scale={g.scaled_width}:{g.scaled_height}:flags={scaler}",
        f"setsar={sar.num}/{sar.den}",
    ]


#: ``FilterConfig.preset``'s default. An implementation without a preset of that name uses its
#: own ``default_preset`` (Denoise ``light``, Colorspace ``bt709``; decision 0013).
DEFAULT_PRESET = "default"


def resolve_config(
    fdef: FilterDef, config: FilterConfig, available: Mapping[str, bool]
) -> FilterConfig:
    """``config`` with the preset ``default`` replaced by the implementation's default preset
    when no implementation has a preset of that name."""
    if config.preset != DEFAULT_PRESET:
        return config
    impl = fdef.implementation_for(config, available)
    if impl is not None and impl.preset(DEFAULT_PRESET) is not None:
        return config
    if impl is None and config.implementation is None:
        impl = fdef.implementation_for(None, available)
    if impl is None:
        return config
    return config.model_copy(update={"preset": impl.default_preset})


def _chain(
    fdef: FilterDef, config: FilterConfig, available: Mapping[str, bool]
) -> tuple[FilterImplementation, str]:
    config = resolve_config(fdef, config, available)
    impl = fdef.implementation_for(config, available)
    chain = fdef.chain_for(config, available)
    if impl is None or chain is None:
        what = config.implementation or "the default implementation"
        raise PlanError(
            f"filter {fdef.id!r}: {what}, preset {config.preset!r}"
            f"{f', tune {config.tune!r}' if config.tune else ''} cannot be used with this "
            "FFmpeg build (validation reports it)"
        )
    return impl, chain


def _with_option(chain: str, option: str) -> str:
    """Append ``key=value`` to the (last) filter of ``chain``: ``bwdif=mode=…`` →
    ``bwdif=mode=…:deint=interlaced``; ``bwdif`` → ``bwdif=deint=interlaced``."""
    chain = chain.rstrip("=")
    last = chain.rsplit(",", 1)[-1]
    return f"{chain}{':' if '=' in last else '='}{option}"


def build_video_graph(
    *,
    video: VideoStream,
    filters: Mapping[str, FilterConfig],
    geometry: Geometry,
    scaler: str,
    tail: list[str],
    definitions: Definitions,
    available: Mapping[str, bool],
    text_burn: TextBurn | None = None,
    bitmap_burn: BitmapBurn | None = None,
) -> VideoGraph:
    """The video filters of one job in the fixed order (see the module doc).

    ``tail`` is the format stage (``["format=yuv420p"]`` or a hardware filter tail).
    Unknown filter ids raise :class:`PlanError` (validation reports them).
    """
    for filter_id in filters:
        if filter_id not in definitions.filters:
            raise PlanError(f"unknown filter {filter_id!r} (validation reports it)")
    graph = VideoGraph()
    before: list[str] = []  # up to the crop (a bitmap overlay comes after these)
    after: list[str] = []  # from the rotation on
    hdr_source = _is_hdr(video)

    def add(target: list[str], filter_id: str) -> None:
        config = filters.get(filter_id)
        if config is None:
            return
        fdef = definitions.filters[filter_id]  # type: ignore[index]
        if filter_id == "tonemap" and not hdr_source:
            return  # nothing to tone map: an SDR source stays as it is (decision 0013)
        impl, chain = _chain(fdef, config, available)
        if filter_id == "custom" and not chain.strip():
            return
        if impl.combed_only and "interlace_detection" in filters:
            chain = _with_option(chain, impl.combed_only)
        if impl.requires_tagged_input:
            setparams = _setparams(video)
            if setparams is not None:
                target.append(setparams)
        target.append(chain)
        graph.filters.append(filter_id)

    for stage in definitions.filter_order:
        if stage == "crop":
            crop, turn = _crop_stage(geometry)
            before.extend(crop)
            after.extend(turn)
        elif stage == "scale":
            after.extend(_scale_stage(geometry, scaler))
        elif stage == "format":
            if text_burn is not None:
                after.extend(_text_burn(text_burn))
            after.extend(tail)
        else:
            target = before if not _past_crop(stage, definitions) else after
            add(target, stage)
            if (
                stage == "colorspace"
                and hdr_source
                and ("tonemap" in graph.filters or "colorspace" in graph.filters)
            ):
                after.extend(f"sidedata=mode=delete:type={t}" for t in HDR_SIDE_DATA)
                graph.hdr_removed = True

    if bitmap_burn is None:
        graph.chain = ",".join(before + after)
        return graph
    graph.complex = _overlay_graph(video, geometry, before, after, bitmap_burn)
    return graph


def _past_crop(stage: str, definitions: Definitions) -> bool:
    order = definitions.filter_order
    return order.index(stage) > order.index("crop")


def _text_burn(burn: TextBurn) -> list[str]:
    sub = subtitles_filter(burn.path, stream=burn.stream, charenc=burn.charenc)
    if not burn.shift:
        return [sub]
    amount = _seconds(abs(burn.shift))
    forward, back = ("+", "-") if burn.shift > 0 else ("-", "+")
    return [f"setpts=PTS{forward}{amount}/TB", sub, f"setpts=PTS{back}{amount}/TB"]


def _seconds(value: float) -> str:
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text or "0"


def _overlay_graph(
    video: VideoStream, g: Geometry, before: list[str], after: list[str], burn: BitmapBurn
) -> str:
    """``[0:v]…crop[base];[sub]…[subs];[base][subs]overlay=…,…[v]``.

    The subtitle canvas covers the source picture. When the crop removes lines, the canvas
    is aligned with the bottom of the cropped picture (decision 0013): subtitles placed in a
    letterbox bar at the bottom move up into the picture instead of being cropped away.
    """
    c = g.crop
    x = -c.left
    y = -(c.top + c.bottom)
    parts: list[str] = []
    base_in = f"[0:{video.index}]"
    if before:
        parts.append(f"{base_in}{','.join(before)}[base]")
        base_in = "[base]"
    sub_in = f"[{burn.input_label}]"
    if burn.canvas is not None and burn.canvas != (video.width, video.height):
        parts.append(f"{sub_in}scale={video.width}:{video.height}[subs]")
        sub_in = "[subs]"
    overlay = f"overlay=x={x}:y={y}:eof_action=pass" if (x or y) else "overlay=eof_action=pass"
    rest = "".join("," + f for f in after)
    parts.append(f"{base_in}{sub_in}{overlay}{rest}{VideoGraph.OUTPUT_LABEL}")
    return ";".join(parts)
