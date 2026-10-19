"""How a preview frame is made: the filter chains and the FFmpeg command. Pure: no I/O.

The source frame is the decoded picture with its display rotation applied. An HDR source is
tone mapped to SDR, since a PNG cannot hold HDR. An output frame uses the job's own video
filter graph, and a copied video gives the source picture.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from reframe.command import PlanError
from reframe.command.filtergraph import (
    VideoGraph,
    build_video_graph,
    colour_params,
    filter_available,
    is_hdr,
    tonemap_filters,
)
from reframe.command.video import format_number
from reframe.definitions import Definitions
from reframe.dimensions import compute_geometry, source_geometry
from reframe.models import CapabilitySnapshot, JobSettings, MediaSource, VideoStream
from reframe.models.preview import FrameKind

__all__ = [
    "DISPLAY_TAIL",
    "PNG_ARGS",
    "FrameRecipe",
    "frame_argv",
    "job_video_graph",
    "output_recipe",
    "source_recipe",
]

#: 8-bit RGB for the PNG, with full chroma interpolation and accurate rounding (the crop
#: magnifier shows single pixels). The explicit ``scale`` comes first in every branch: see the
#: frame-seek notes in testdata/README.md.
DISPLAY_TAIL = ("scale=flags=bicubic+accurate_rnd+full_chroma_int", "format=rgb24")
PNG_ARGS = ("-c:v", "png", "-compression_level", "3", "-f", "image2", "-update", "1")
#: Global options of a frame run (errors only: the frame files are the result).
GLOBAL_ARGS = ("-hide_banner", "-nostdin", "-nostats", "-loglevel", "error", "-y")


@dataclass(frozen=True, slots=True)
class FrameRecipe:
    """How one kind of frame is made from the decoded source picture (pure data: its fields
    are part of the cache key's settings hash)."""

    kind: FrameKind
    chain: list[str]
    """The filters after the shared colour tagging (:attr:`prefix`)."""
    prefix: list[str] = field(default_factory=list)
    """``setparams`` for an untagged source: shared by every kind of one run."""
    notes: list[str] = field(default_factory=list)
    """For :attr:`FrameSet.notes <reframe.models.FrameSet.notes>`."""

    def identity(self) -> list[object]:
        """What the settings hash covers."""
        return [self.kind, self.prefix, self.chain, list(PNG_ARGS)]


def _hdr_display(
    video: VideoStream, caps: CapabilitySnapshot, definitions: Definitions
) -> tuple[list[str], str]:
    """The tone mapping filters for showing an HDR picture on an SDR screen, and how they map
    it (for a note). A build that has neither ``zscale`` nor a working ``libplacebo`` shows the
    HDR signal unmapped (pale), with a note."""
    try:
        filters, impl = tonemap_filters(video, definitions, filter_available(caps, definitions))
    except PlanError:
        return [], (
            "shown without tone mapping (pale): this FFmpeg build has neither zscale nor a "
            "working libplacebo"
        )
    how = f"tone mapped to SDR for display with {impl.label}"
    dovi = video.hdr.dolby_vision if video.hdr is not None else None
    if dovi is not None and dovi.profile == 5 and impl.id != "libplacebo":
        # Profile 5 has no HDR10 base layer (IPTPQc2): only libplacebo applies the RPU.
        how += " (Dolby Vision profile 5: the colours are only right with libplacebo)"
    return filters, how


def _hdr_name(video: VideoStream) -> str:
    formats = video.hdr.formats if video.hdr is not None else []
    names = {"hdr10": "HDR10", "hdr10plus": "HDR10+", "hlg": "HLG", "dolby_vision": "Dolby Vision"}
    return ", ".join(names.get(f.value, f.value) for f in formats) or "HDR"


def _prefix(video: VideoStream) -> list[str]:
    setparams = colour_params(video)
    return [setparams] if setparams is not None else []


def source_recipe(
    video: VideoStream, caps: CapabilitySnapshot, definitions: Definitions
) -> FrameRecipe:
    """The source frame: the decoded picture, tone mapped when it is HDR."""
    chain: list[str] = []
    notes: list[str] = []
    if is_hdr(video):
        filters, how = _hdr_display(video, caps, definitions)
        chain += filters
        notes.append(
            f"The source is {_hdr_name(video)}: a PNG cannot hold HDR, so the frames are {how}."
        )
    chain += DISPLAY_TAIL
    return FrameRecipe(kind="source", chain=chain, prefix=_prefix(video), notes=notes)


def job_video_graph(
    job: JobSettings,
    source: MediaSource,
    caps: CapabilitySnapshot,
    definitions: Definitions,
    *,
    tail: Sequence[str] = (),
) -> VideoGraph | None:
    """The job's video filter graph, as the command builder makes it, without subtitle burn-in.
    ``None`` for a copied video. Raises :class:`PlanError` like the builder (an unknown encoder,
    a filter that cannot run, …)."""
    if not source.video:
        raise PlanError("the source has no video stream")
    if job.video.passthrough:
        return None
    video = source.video[0]
    settings = job.video
    encoder = definitions.video_encoders.get(settings.encoder)
    if encoder is None:
        raise PlanError(f"unknown video encoder {settings.encoder!r} (validation reports it)")
    pix_fmt = encoder.pix_fmts.get("10" if settings.bit_depth == 10 else "8")
    if pix_fmt is None:
        raise PlanError(f"{encoder.label} has no {settings.bit_depth}-bit mode")
    geometry_src = source_geometry(video)
    if "deinterlace" in job.filters.root:
        geometry_src = geometry_src.model_copy(update={"interlaced": False})
    geometry = compute_geometry(geometry_src, job.dimensions)
    return build_video_graph(
        video=video,
        filters=job.filters.root,
        geometry=geometry,
        scaler=job.dimensions.scaler,
        tail=[f"format={pix_fmt}", *tail],
        definitions=definitions,
        available=filter_available(caps, definitions),
    )


def output_recipe(
    job: JobSettings, source: MediaSource, caps: CapabilitySnapshot, definitions: Definitions
) -> FrameRecipe:
    """The output frame of ``job``. Raises :class:`PlanError` when the job's graph cannot be
    made."""
    if not source.video:
        raise PlanError("the source has no video stream")
    video = source.video[0]
    notes: list[str] = []
    if any(t.action == "burn" for t in job.subtitles):
        # The subtitles filter reads the whole source for each frame: burn-in is left out.
        notes.append(
            "Burned-in subtitles are not drawn on the output frames; a preview clip shows them."
        )
    graph = job_video_graph(job, source, caps, definitions)
    if graph is None:
        notes.append("The video is copied: the output frames are the source picture.")
        recipe = source_recipe(video, caps, definitions)
        return FrameRecipe(kind="output", chain=recipe.chain, prefix=recipe.prefix, notes=[*notes])
    chain = [graph.chain] if graph.chain else []
    if is_hdr(video) and not graph.hdr_removed:
        filters, how = _hdr_display(video, caps, definitions)
        chain += filters
        notes.append(f"The output stays HDR: the output frames are {how}, like the source frames.")
    chain += DISPLAY_TAIL
    return FrameRecipe(kind="output", chain=chain, prefix=_prefix(video), notes=notes)


def frame_argv(
    program: str,
    source: Path,
    video_index: int,
    timestamp: float,
    outputs: Sequence[tuple[FrameRecipe, Path]],
) -> list[str]:
    """One FFmpeg run that writes a PNG of each recipe at ``timestamp``. Every recipe must have
    the same :attr:`~FrameRecipe.prefix` (they are of one source)."""
    if not outputs:
        raise ValueError("no frame to make")
    prefix = outputs[0][0].prefix
    if any(recipe.prefix != prefix for recipe, _ in outputs):
        raise ValueError("the recipes of one run must share their prefix")
    count = len(outputs)
    head = [*prefix, f"split={count}"] if count > 1 else list(prefix)
    source_label = f"[0:{video_index}]"
    parts: list[str] = []
    if head:
        feeds = [f"[i{k}]" for k in range(count)]
        parts.append(source_label + ",".join(head) + "".join(feeds))
    else:
        feeds = [source_label]
    maps: list[str] = []
    for k, ((recipe, path), feed) in enumerate(zip(outputs, feeds, strict=True)):
        label = f"[o{k}]"
        parts.append(feed + ",".join(recipe.chain or ["null"]) + label)
        maps += ["-map", label, "-frames:v", "1", *PNG_ARGS, str(path)]
    return [
        program, *GLOBAL_ARGS, "-ss", format_number(timestamp), "-i", str(source),
        "-filter_complex", ";".join(parts), *maps,
    ]  # fmt: skip
