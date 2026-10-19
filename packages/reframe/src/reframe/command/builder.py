"""``build_plan``: one job becomes an :class:`~reframe.models.EncodePlan`. FFmpeg scopes options by
position: input options come before their ``-i``, output options before the output file. The
range end is an output ``-t``, the only form that cuts the copied chapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
from pathlib import Path

from reframe.command.audio import AudioOut, audio_output
from reframe.command.errors import PlanError
from reframe.command.filtergraph import (
    VideoGraph,
    build_video_graph,
    filter_available,
    keeps_hdr,
)
from reframe.command.jobtype import job_type
from reframe.command.metadata import (
    OutputTrack,
    chapter_plan,
    chapter_range,
    render_tag,
    stream_metadata_args,
    tag_args,
)
from reframe.command.mkvpropedit import (
    FixupTrack,
    InfoEdit,
    TrackEdit,
    edit_args,
    fixup_edits,
    in_place_edits,
)
from reframe.command.quoting import Shell, command_line, default_shell, quote_posix, quote_windows
from reframe.command.subtitles import SubtitlePlan, plan_subtitles
from reframe.command.video import (
    V0,
    format_number,
    frame_rate_args,
    pass_log_files,
    source_rate,
    spec,
    video_encoder_args,
)
from reframe.definitions import ContainerDef, Definitions, VideoEncoderDef, load_definitions
from reframe.dimensions import compute_geometry, source_geometry
from reframe.models import (
    AverageBitrate,
    CapabilitySnapshot,
    ChapterRange,
    EncodePlan,
    ExternalSubtitle,
    FrameRange,
    Geometry,
    JobSettings,
    Measurement,
    MediaSource,
    NamingOptions,
    PlanArg,
    PlanFile,
    PlanStep,
    StepKind,
    TimeRange,
    ToolName,
    ToolSet,
    ToolStatus,
    VideoSettings,
    VideoStream,
)

__all__ = [
    "DEFAULT_VAAPI_DEVICE",
    "GLOBAL_ARGS",
    "STEP_WEIGHTS",
    "build_plan",
    "partial_path",
]

GLOBAL_ARGS = ("-hide_banner", "-nostdin", "-y", "-progress", "pipe:1", "-nostats")
#: ``{vaapi_device}`` when the encoder status names no render node (the definitions' default).
DEFAULT_VAAPI_DEVICE = "/dev/dri/renderD128"
#: Relative progress weights; the runner normalises them.
STEP_WEIGHTS: dict[StepKind, float] = {
    "analyse": 0.05,
    "pass1": 0.4,
    "pass2": 0.6,
    "encode": 1.0,
    "mkvpropedit": 0.01,
    "finalize": 0.0,
}
_NULL_OUTPUT = ("-f", "null", "-")


def partial_path(final: Path, suffix: str = "") -> Path:
    """``Movie.mkv`` → ``Movie.part.mkv``; with ``suffix`` (``.chapters.txt``, ``.passlog``) →
    ``Movie.part.chapters.txt``."""
    stem = final.name[: -len(final.suffix)] if final.suffix else final.name
    return final.with_name(f"{stem}.part{suffix or final.suffix}")


@dataclass(frozen=True, slots=True)
class _Range:
    start: float
    """Seconds to seek in the source (0 = from the start)."""
    duration: float | None
    """Seconds to encode (``None`` = to the end)."""
    expected: float
    """The output duration for progress."""


def _source_duration(source: MediaSource, video: VideoStream) -> float | None:
    return source.container.duration or video.duration


def _resolve_range(job: JobSettings, source: MediaSource, video: VideoStream) -> _Range:
    total = _source_duration(source, video)
    r = job.range
    start = 0.0
    end: float | None = None
    if isinstance(r, ChapterRange):
        start, end = chapter_range(source, r)
    elif isinstance(r, TimeRange):
        start, end = r.start, r.end
    elif isinstance(r, FrameRange):
        rate = source_rate(video)
        if rate is None:
            raise PlanError("a frame range needs the source's frame rate (validation)")
        fps = float(rate)
        start = r.start / fps
        end = r.end / fps if r.end is not None else None
    if end is not None and total is not None and end >= total:
        end = None
    if end is not None and end <= start:
        raise PlanError("the range is empty (validation reports it)")
    duration = None if end is None else end - start
    if duration is not None:
        expected = duration
    else:
        expected = max(0.0, total - start) if total is not None else 0.0
    return _Range(start=start, duration=duration, expected=expected)


@dataclass(slots=True)
class _Video:
    """The video part of the plan."""

    codec_args: dict[int | None, list[str]]
    """Codec arguments per run (``None`` = single run; 1 and 2 for a 2-pass encode)."""
    graph: VideoGraph | None
    hw_init: list[str]
    geometry: Geometry | None
    two_runs: bool
    passlog: Path | None
    stats_param: bool
    label: str


def _fill(text: str, values: dict[str, str]) -> str:
    for name, value in values.items():
        text = text.replace("{" + name + "}", value)
    return text


def _video_plan(
    job: JobSettings,
    video: VideoStream,
    caps: CapabilitySnapshot,
    container: ContainerDef,
    defs: Definitions,
    subs: SubtitlePlan,
    passlog: Path,
) -> _Video:
    settings = job.video
    if settings.passthrough:
        codec = video.codec or ""
        if not container.video.can_copy(codec):
            raise PlanError(f"{codec} video cannot be copied into {container.label}")
        args = [spec("-c:v", V0), "copy"]
        if codec in container.codec_tags:
            args += [spec("-tag:v", V0), container.codec_tags[codec]]
        return _Video({None: args}, None, [], None, False, None, False, "Remux")
    encoder = defs.video_encoders.get(settings.encoder)
    if encoder is None:
        raise PlanError(f"unknown video encoder {settings.encoder!r} (validation reports it)")
    if encoder.codec not in container.video.encode:
        raise PlanError(f"{encoder.codec_label} cannot be written into {container.label}")
    pix_fmt = encoder.pix_fmts.get("10" if settings.bit_depth == 10 else "8")
    if pix_fmt is None:
        raise PlanError(f"{encoder.label} has no {settings.bit_depth}-bit mode")
    status = caps.status(encoder.id)
    geometry_src = source_geometry(video)
    if "deinterlace" in job.filters.root:
        geometry_src = geometry_src.model_copy(update={"interlaced": False})
    geometry = compute_geometry(geometry_src, job.dimensions)
    values = {"vaapi_device": status.device or DEFAULT_VAAPI_DEVICE, "sw_pix_fmt": pix_fmt}
    setup = encoder.hardware_setup
    hw_init = [_fill(a, values) for a in setup.init_args] if setup else []
    tail = (
        [_fill(f, values) for f in setup.filter_tail]
        if setup and setup.filter_tail
        else [f"format={pix_fmt}"]
    )
    graph = build_video_graph(
        video=video,
        filters=job.filters.root,
        geometry=geometry,
        scaler=job.dimensions.scaler,
        tail=tail,
        definitions=defs,
        available=filter_available(caps, defs),
        text_burn=subs.text_burn,
        bitmap_burn=subs.bitmap_burn,
    )
    hdr = keeps_hdr(video, job.filters.root, settings.bit_depth) and not graph.hdr_removed
    rc = settings.rate_control
    two_pass = encoder.rate_control.bitrate.two_pass if encoder.rate_control.bitrate else None
    two_runs = (
        isinstance(rc, AverageBitrate)
        and rc.two_pass
        and two_pass is not None
        and two_pass.mode == "two_runs"
    )
    extra = _codec_extra(encoder, settings, video, container, graph.rate_factor)
    runs: list[int | None] = [1, 2] if two_runs else [None]
    codec_args = {
        run: [
            *video_encoder_args(
                encoder, settings, video, status=status, run=run,
                passlog=passlog if two_runs else None, hdr=hdr,
            ),
            *extra,
        ]
        for run in runs
    }  # fmt: skip
    stats_param = two_pass is not None and any("{passlog}" in v for v in two_pass.params.values())
    return _Video(
        codec_args, graph, hw_init, geometry, two_runs, passlog if two_runs else None,
        stats_param, encoder.label,
    )  # fmt: skip


def _codec_extra(
    encoder: VideoEncoderDef,
    settings: VideoSettings,
    video: VideoStream,
    container: ContainerDef,
    rate_factor: Fraction,
) -> list[str]:
    args = frame_rate_args(settings, video, factor=rate_factor)
    tag = container.codec_tags.get(encoder.codec)
    if tag is not None:
        args += [spec("-tag:v", V0), tag]
    return args


def _audio_plan(
    job: JobSettings, source: MediaSource, container: ContainerDef, defs: Definitions
) -> list[AudioOut]:
    streams = {a.index: a for a in source.audio}
    outs: list[AudioOut] = []
    for i, track in enumerate(job.audio):
        if track.source_stream is None or track.source_stream not in streams:
            raise PlanError(f"audio track {i + 1}: the source has no audio stream "
                            f"{track.source_stream} (validation reports it)")  # fmt: skip
        outs.append(audio_output(i, track, streams[track.source_stream], container, defs))
    return outs


def _drc_args(outs: list[AudioOut], only: int | None = None) -> list[str]:
    """``-drc_scale:<index> <value>`` for each decoded AC-3 / E-AC-3 source stream. The first
    track that decodes a stream decides its value: one decoder per input stream."""
    seen: dict[int, float] = {}
    for out in outs:
        if out.drc is None or out.stream.index in seen:
            continue
        if only is not None and out.stream.index != only:
            continue
        seen[out.stream.index] = out.drc
    args: list[str] = []
    for index, value in seen.items():
        args += [f"-drc_scale:{index}", format_number(value)]
    return args


def _tracks(
    job: JobSettings, video: VideoStream, audio: list[AudioOut], subs: SubtitlePlan
) -> list[OutputTrack]:
    tracks = [
        OutputTrack("v", 0, job.video.metadata, video.language_ietf or video.language, video.title)
    ]
    for out in audio:
        track = job.audio[out.index]
        stream = out.stream
        tracks.append(
            OutputTrack(
                "a", out.index, track.metadata, stream.language_ietf or stream.language,
                stream.title,
            )
        )  # fmt: skip
    for sub in subs.outputs:
        tracks.append(
            OutputTrack("s", sub.index, sub.track.metadata, sub.source_language, sub.source_title)
        )
    return tracks


def build_plan(
    job: JobSettings,
    source: MediaSource,
    caps: CapabilitySnapshot,
    tools: ToolSet,
    *,
    definitions: Definitions | None = None,
    shell: Shell | None = None,
    naming: NamingOptions | None = None,
    now: datetime | None = None,
) -> EncodePlan:
    """The exact commands for one job. Pure: no I/O, no clock, no environment reads.

    The caller runs validation first; a job that cannot be planned raises :class:`PlanError`.
    ``job.output.path`` is the final output path (naming resolved it). ``shell`` is the quoting
    style of :attr:`EncodePlan.display` (default: this OS's). ``naming`` (the effective naming
    options) and ``now`` are used by tag values that hold naming variables (``{date}`` is empty
    without ``now``).
    """
    defs = definitions if definitions is not None else load_definitions()
    container = defs.containers.get(job.output.container)
    if container is None:
        raise PlanError(f"unknown container {job.output.container!r}")
    if not source.video:
        raise PlanError("the source has no video stream")
    video = source.video[0]
    kind, _ = job_type(job, source, definitions=defs)
    options = naming if naming is not None else NamingOptions()
    if kind == "metadata_edit":
        return _in_place_plan(job, source, tools, defs, options, now, shell or default_shell())
    final = job.output.path
    if final is None:
        raise PlanError("the output path is not set (naming resolves it before planning)")
    tmp = partial_path(final)
    rng = _resolve_range(job, source, video)
    passlog = partial_path(final, ".passlog")

    subs = plan_subtitles(
        job.subtitles, source, container, start=rng.start, first_input=1,
        passthrough=job.video.passthrough,
    )  # fmt: skip
    vplan = _video_plan(job, video, caps, container, defs, subs, passlog)
    audio = _audio_plan(job, source, container, defs)
    chapters = chapter_plan(
        job, source, container, start=rng.start, duration=rng.duration,
        expected_duration=rng.expected, file_path=partial_path(final, ".chapters.txt"),
    )  # fmt: skip
    files: list[PlanFile] = [chapters.file] if chapters.file is not None else []

    # ---- inputs
    seek = ["-ss", format_number(rng.start)] if rng.start else []
    source_input = [*_drc_args(audio), *subs.decoder_args, *seek, "-i", str(job.source.path)]
    external = [arg for entry in subs.inputs for arg in entry.args]
    chapter_input: list[str] = []
    chapter_map: str = "-1"
    if chapters.map_from == 0:
        chapter_map = "0"
    elif chapters.file is not None:
        index = 1 + len(subs.inputs)
        chapter_input = ["-f", "ffmetadata", "-i", str(chapters.file.path)]
        chapter_map = str(index)
    limit = ["-t", format_number(rng.duration)] if rng.duration is not None else []
    trim = ["-ss", "0"] if _drops_before_start(job, rng) else []

    # ---- maps and filters
    graph = vplan.graph
    video_map = ["-map", VideoGraph.OUTPUT_LABEL if graph and graph.complex else f"0:{video.index}"]
    video_filter: list[str] = []
    if graph is not None and graph.complex:
        video_filter = ["-filter_complex", graph.complex]
    elif graph is not None and graph.chain:
        video_filter = [spec("-filter:v", V0), graph.chain]
    attachments = container.attachments and subs.copies_ass and bool(source.attachments)
    maps = [*video_map]
    for out in audio:
        maps += ["-map", f"0:{out.stream.index}"]
    for sub in subs.outputs:
        maps += ["-map", sub.map]
    if attachments:
        maps += ["-map", "0:t?"]
    audio_filters: list[PlanArg] = []
    for out in audio:
        if out.filter is not None:
            audio_filters += [spec("-filter:a", f"a:{out.index}"), out.filter]
    stream_codecs: list[PlanArg] = [a for out in audio for a in out.args]
    stream_codecs += [a for sub in subs.outputs for a in sub.args()]

    # ---- metadata, chapters, tags, container flags
    tracks = _tracks(job, video, audio, subs)
    metadata = ["-map_metadata:s", "-1"]
    if attachments:
        for k in range(len(source.attachments)):
            metadata += [f"-map_metadata:s:t:{k}", f"0:s:t:{k}"]
    metadata += stream_metadata_args(tracks, container, defs)
    output_size = (
        (vplan.geometry.scaled_width, vplan.geometry.scaled_height)
        if vplan.geometry is not None
        else (video.width, video.height)
    )

    def render_value(value: str) -> str:
        return render_tag(
            value, job, source, options=options, output_size=output_size, now=now,
            definitions=defs,
        )  # fmt: skip

    tags = tag_args(job.tags, passthru=job.output.passthru_metadata, render_value=render_value)
    flags: list[str] = []
    if job.output.web_optimized:
        flags += container.format_flags.get("web_optimized", [])
    for out in audio:
        for arg_pair in _pairs(out.global_args):
            if not _contains_pair(flags, arg_pair):
                flags += arg_pair
    output = ["-f", container.muxer, str(tmp)]

    def ffmpeg_argv(run: int | None) -> list[PlanArg]:
        return [
            *GLOBAL_ARGS, *vplan.hw_init, *source_input, *external, *chapter_input, *maps,
            *trim, *limit, *video_filter, *audio_filters, *vplan.codec_args[run], *stream_codecs,
            *metadata, "-map_chapters", chapter_map, *tags, *flags, *output,
        ]  # fmt: skip

    steps: list[PlanStep] = []
    for out in audio:
        if out.analyse_filter is None or out.measurement_id is None:
            continue
        steps.append(_analyse_step(job, out, rng, _drc_args(audio, only=out.stream.index)))
    temp_files: list[Path] = []
    if vplan.two_runs:
        assert vplan.passlog is not None
        pass1: list[PlanArg] = [
            *GLOBAL_ARGS, *vplan.hw_init, *source_input, *external, *video_map, *limit,
            *video_filter, *vplan.codec_args[1], *_NULL_OUTPUT,
        ]  # fmt: skip
        steps.append(_step("pass1", pass1, f"Pass 1 of 2: analyse the video ({vplan.label})"))
        steps.append(_step("pass2", ffmpeg_argv(2), f"Pass 2 of 2: encode ({vplan.label})"))
        temp_files = pass_log_files(vplan.passlog, stats_param=vplan.stats_param)
    else:
        what = "Remux (copy the streams)" if kind == "remux" else f"Encode ({vplan.label})"
        steps.append(_step("encode", ffmpeg_argv(None), what))
    fixup = _fixup_step(tracks, container, defs, tools, tmp)
    if fixup is not None:
        steps.append(fixup)
    steps.append(
        PlanStep(
            kind="finalize", tool=None, progress_weight=STEP_WEIGHTS["finalize"],
            description=f"Rename {tmp.name} to {final.name}",
        )
    )  # fmt: skip
    return EncodePlan(
        job_type=kind,
        steps=steps,
        output_tmp=tmp,
        output_final=final,
        expected_duration=round(rng.expected, 6),
        display=_display(steps, tools, tmp, final, shell or default_shell()),
        files=files,
        temp_files=temp_files,
    )


def _fixup_step(
    tracks: list[OutputTrack],
    container: ContainerDef,
    defs: Definitions,
    tools: ToolSet,
    tmp: Path,
) -> PlanStep | None:
    """The post-mux fix-up: mkvpropedit writes what FFmpeg's Matroska muxer does not (the BCP 47
    languages and the track flags). Only for MKV, and only when mkvpropedit was found: validation
    warns about what is lost without it."""
    if container.id != "mkv" or tools.mkvpropedit.status is not ToolStatus.FOUND:
        return None
    edits = fixup_edits(
        [FixupTrack(t.type, t.index + 1, t.language, t.metadata) for t in tracks],
        container,
        defs,
    )
    if not edits:
        return None
    what = []
    if any(e.language is not None for e in edits):
        what.append("the BCP 47 languages (Matroska LanguageIETF)")
    if any(e.flags for e in edits):
        what.append("the track flags FFmpeg cannot write")
    return PlanStep(
        kind="mkvpropedit", tool="mkvpropedit", argv=[str(tmp), *edit_args(edits)],
        progress_weight=STEP_WEIGHTS["mkvpropedit"], description="Write " + " and ".join(what),
    )  # fmt: skip


def _describe_edits(edits: list[TrackEdit | InfoEdit]) -> str:
    tracks = sum(1 for e in edits if isinstance(e, TrackEdit))
    parts = []
    if tracks:
        parts.append(f"the metadata of {tracks} track" + ("" if tracks == 1 else "s"))
    if any(isinstance(e, InfoEdit) for e in edits):
        parts.append("the title")
    return " and ".join(parts)


def _in_place_plan(
    job: JobSettings,
    source: MediaSource,
    tools: ToolSet,
    defs: Definitions,
    options: NamingOptions,
    now: datetime | None,
    shell: Shell,
) -> EncodePlan:
    """The plan of a ``metadata_edit`` job: one mkvpropedit step on the source itself, with no
    ``.part`` file and no rename. ``output_tmp`` and ``output_final`` are the source. No step
    when the source already has every value."""
    target = Path(job.source.path)
    video = source.video[0]

    def render_title(value: str) -> str:
        return render_tag(
            value, job, source, options=options, output_size=(video.width, video.height),
            now=now, definitions=defs,
        )  # fmt: skip

    edits = in_place_edits(job, source, defs, render_title=render_title)
    steps: list[PlanStep] = []
    if edits:
        steps.append(
            PlanStep(
                kind="mkvpropedit", tool="mkvpropedit", argv=[str(target), *edit_args(edits)],
                progress_weight=STEP_WEIGHTS["mkvpropedit"],
                description=f"Edit {_describe_edits(edits)} of {target.name} "
                "in place",
            )
        )  # fmt: skip
    return EncodePlan(
        job_type="metadata_edit",
        steps=steps,
        output_tmp=target,
        output_final=target,
        expected_duration=0.0,
        display=_display(steps, tools, target, target, shell),
        files=[],
        temp_files=[],
    )


def _drops_before_start(job: JobSettings, rng: _Range) -> bool:
    """Whether the output gets ``-ss 0``, which drops the packets that copied streams and external
    subtitles have before time 0.

    Not with a copied video: its first packets, the keyframe before the range start, would be
    dropped too.
    """
    if job.video.passthrough:
        return False
    negative = any(
        isinstance(t.source, ExternalSubtitle) and t.source.offset_ms < 0
        for t in job.subtitles
        if t.action != "burn"
    )
    return rng.start > 0 or negative


def _pairs(args: list[str]) -> list[list[str]]:
    return [args[i : i + 2] for i in range(0, len(args), 2)]


def _contains_pair(args: list[str], pair: list[str]) -> bool:
    return any(args[i : i + 2] == pair for i in range(0, len(args) - 1, 2))


def _step(kind: StepKind, argv: list[PlanArg], description: str) -> PlanStep:
    return PlanStep(
        kind=kind,
        tool="ffmpeg",
        argv=argv,
        progress_weight=STEP_WEIGHTS[kind],
        description=description,
    )


def _analyse_step(job: JobSettings, out: AudioOut, rng: _Range, drc: list[str]) -> PlanStep:
    assert out.analyse_filter is not None
    assert out.measurement_id is not None
    seek = ["-ss", format_number(rng.start)] if rng.start else []
    limit = ["-t", format_number(rng.duration)] if rng.duration is not None else []
    argv: list[PlanArg] = [
        *GLOBAL_ARGS, *drc, *seek, "-i", str(job.source.path), "-map", f"0:{out.stream.index}",
        *limit, spec("-filter:a", "a:0"), out.analyse_filter, *_NULL_OUTPUT,
    ]  # fmt: skip
    title = f" ({out.stream.title})" if out.stream.title else ""
    return PlanStep(
        kind="analyse",
        tool="ffmpeg",
        argv=argv,
        progress_weight=STEP_WEIGHTS["analyse"],
        description=f"Measure the loudness of audio track {out.index + 1}{title}",
        measures=[Measurement(id=out.measurement_id, parser="loudnorm")],
    )


def _program(tools: ToolSet, name: ToolName) -> str:
    info = tools.get(name)
    return str(info.path) if info.path is not None else name


def _display(steps: list[PlanStep], tools: ToolSet, tmp: Path, final: Path, shell: Shell) -> str:
    lines: list[str] = []
    quote = quote_posix if shell == "posix" else quote_windows
    for step in steps:
        if step.tool is None:
            mover = "mv -f --" if shell == "posix" else "move /Y"
            lines.append(f"{mover} {quote(str(tmp))} {quote(str(final))}")
            continue
        lines.append(command_line(_program(tools, step.tool), step.argv, shell))
    return " && ".join(lines)
