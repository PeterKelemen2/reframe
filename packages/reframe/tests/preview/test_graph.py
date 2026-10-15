"""How a preview frame is made (C-10): the source and output chains, the agreement of the output
graph with C-7's builder, and the FFmpeg command of one timestamp. Pure."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from reframe.command import PlanError, build_plan
from reframe.models import (
    ColorInfo,
    CropRect,
    DolbyVisionInfo,
    HdrFormat,
    HdrInfo,
    JobSettings,
    MediaSource,
    OutputSettings,
    SourceRef,
    SubtitleOutputTrack,
    VideoStream,
)
from reframe.preview.graph import (
    DISPLAY_TAIL,
    PNG_ARGS,
    FrameRecipe,
    frame_argv,
    job_video_graph,
    output_recipe,
    source_recipe,
)

from .helpers import DEFS, caps, real_tools, recorded

TOOLS = real_tools(mkvpropedit=False)


def job(source: MediaSource, **fields: Any) -> JobSettings:
    """A job of ``source`` (no audio or subtitles) with JobSettings fields as dicts."""
    data: dict[str, Any] = {
        "source": SourceRef(path=source.ref.path).model_dump(),
        "output": OutputSettings(container="mkv", path=Path("/out/x.mkv")).model_dump(),
        **fields,
    }
    return JobSettings.model_validate(data)


def builder_filter(j: JobSettings, source: MediaSource, *, libplacebo: bool = False) -> str:
    """The video filter of the plan's encode step (``-filter:v:0``)."""
    plan = build_plan(j, source, caps(libplacebo=libplacebo), TOOLS, definitions=DEFS)
    argv = [a for a in plan.steps[-2].argv if isinstance(a, str)]
    return argv[argv.index("-filter:v:0") + 1]


def stream(**kwargs: object) -> VideoStream:
    return VideoStream.model_validate({"index": 0, "width": 1920, "height": 1080, **kwargs})


TAGGED = ColorInfo(primaries="bt709", transfer="bt709", matrix="bt709")


# --------------------------------------------------------------------------- source frames


def test_a_tagged_sdr_source_is_only_converted_to_rgb() -> None:
    recipe = source_recipe(stream(color=TAGGED), caps(), DEFS)
    assert recipe == FrameRecipe(kind="source", chain=list(DISPLAY_TAIL))
    assert DISPLAY_TAIL == ("scale=flags=bicubic+accurate_rnd+full_chroma_int", "format=rgb24")


def test_an_untagged_source_gets_the_assumed_colour_first() -> None:
    hd = source_recipe(stream(), caps(), DEFS)
    assert hd.prefix == ["setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709"]
    sd = source_recipe(stream(width=720, height=576), caps(), DEFS)
    assert sd.prefix == ["setparams=color_primaries=bt470bg:color_trc=smpte170m:colorspace=bt470bg"]


def test_an_hdr_source_is_tone_mapped_for_display() -> None:
    video = recorded("hdr10.mkv").video[0]
    cpu = source_recipe(video, caps(libplacebo=False), DEFS)
    assert cpu.prefix == []  # the fixture says its colour
    assert cpu.chain == [
        "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,"
        "zscale=t=bt709:m=bt709:r=tv",
        *DISPLAY_TAIL,
    ]
    assert cpu.notes == [
        "The source is HDR10: a PNG cannot hold HDR, so the frames are tone mapped to SDR for "
        "display with zscale + tonemap."
    ]
    gpu = source_recipe(video, caps(libplacebo=True), DEFS)
    assert gpu.chain[0].startswith("libplacebo=tonemapping=bt.2390:peak_detect=1:")
    assert "libplacebo" in gpu.notes[0]
    unknown = source_recipe(video, caps(libplacebo=None), DEFS)
    assert unknown.chain == cpu.chain  # not checked yet: the CPU path


def test_an_untagged_hlg_source() -> None:
    video = stream(hdr=HdrInfo(formats=[HdrFormat.HLG, HdrFormat.DOLBY_VISION]))
    recipe = source_recipe(video, caps(), DEFS)
    setparams = "setparams=color_primaries=bt2020:color_trc=arib-std-b67:colorspace=bt2020nc"
    assert recipe.prefix == [setparams]
    assert recipe.chain[0] == setparams  # zscale's own tagging, as in C-7's graph
    assert "HLG, Dolby Vision" in recipe.notes[0]


def test_dolby_vision_profile_5_needs_libplacebo() -> None:
    dovi = HdrInfo(formats=[HdrFormat.DOLBY_VISION], dolby_vision=DolbyVisionInfo(profile=5))
    video = stream(hdr=dovi)
    cpu = source_recipe(video, caps(libplacebo=False), DEFS)
    assert cpu.notes[0].endswith(
        "with zscale + tonemap (Dolby Vision profile 5: the colours are only right with "
        "libplacebo)."
    )
    gpu = source_recipe(video, caps(libplacebo=True), DEFS)
    assert gpu.notes[0].endswith("with libplacebo.")
    eight = stream(
        hdr=HdrInfo(
            formats=[HdrFormat.HDR10, HdrFormat.DOLBY_VISION],
            dolby_vision=DolbyVisionInfo(profile=8),
        )
    )
    assert source_recipe(eight, caps(), DEFS).notes[0].endswith("with zscale + tonemap.")


def test_no_tone_mapper_in_the_build() -> None:
    snapshot = caps(libplacebo=False).model_copy(update={"filters": ["scale"]})
    recipe = source_recipe(recorded("hdr10.mkv").video[0], snapshot, DEFS)
    assert recipe.chain == list(DISPLAY_TAIL)
    assert recipe.notes == [
        "The source is HDR10: a PNG cannot hold HDR, so the frames are shown without tone "
        "mapping (pale): this FFmpeg build has neither zscale nor a working libplacebo."
    ]
    source = recorded("hdr10.mkv")
    kept = output_recipe(
        job(source, video={"encoder": "libx265", "bit_depth": 10}), source, snapshot, DEFS
    )
    assert kept.notes == [
        "The output stays HDR: the output frames are shown without tone mapping (pale): this "
        "FFmpeg build has neither zscale nor a working libplacebo, like the source frames."
    ]


# --------------------------------------------------------------------------- output frames

AGREEMENT: list[tuple[str, dict[str, Any]]] = [
    ("letterbox.mkv", {}),
    (
        "letterbox.mkv",
        {
            "dimensions": {
                "crop": {"mode": "manual", "rect": CropRect(top=22, bottom=24).model_dump()},
                "size": {"mode": "width", "width": 640},
                "allow_upscaling": True,
                "scaler": "bicubic",
            }
        },
    ),
    ("anamorphic.mkv", {"dimensions": {"pixel_aspect": "keep", "size": {"mode": "source"}}}),
    ("anamorphic.mkv", {"dimensions": {"rotate": 90, "flip_horizontal": True}}),
    ("interlaced.mkv", {"filters": {"deinterlace": {}, "interlace_detection": {}}}),
    ("interlaced.mkv", {"filters": {"detelecine": {}, "deinterlace": {"preset": "bob"}}}),
    (
        "multitrack.mkv",
        {
            "filters": {
                "denoise": {"preset": "light"},
                "deblock": {},
                "sharpen": {},
                "chroma_smooth": {},
                "grayscale": {},
                "custom": {"custom": "eq=gamma=1.2"},
            }
        },
    ),
    ("multitrack.mkv", {"filters": {"colorspace": {"preset": "bt2020"}}}),
    ("hdr10.mkv", {"video": {"encoder": "libx265", "bit_depth": 10}}),
    ("hdr10.mkv", {"filters": {"tonemap": {}}}),
    ("hdr10.mkv", {"filters": {"tonemap": {"implementation": "zscale", "tune": "mobius"}}}),
    ("hdr10.mkv", {"filters": {"colorspace": {}}}),
]


@pytest.mark.parametrize(("name", "fields"), AGREEMENT)
@pytest.mark.parametrize("libplacebo", [False, True])
def test_the_output_graph_is_the_builders(
    name: str, fields: dict[str, Any], libplacebo: bool
) -> None:
    """The preview's output graph is C-7's video filter, up to the format stage."""
    source = recorded(name)
    j = job(source, **fields)
    graph = job_video_graph(j, source, caps(libplacebo=libplacebo), DEFS)
    assert graph is not None
    assert graph.chain == builder_filter(j, source, libplacebo=libplacebo)


def test_a_hardware_encoder_gets_its_software_format() -> None:
    source = recorded("letterbox.mkv")
    j = job(source, video={"encoder": "h264_vaapi"})
    graph = job_video_graph(j, source, caps(), DEFS)
    assert graph is not None
    assert graph.chain is not None
    planned = builder_filter(j, source)
    assert planned.endswith(",format=nv12,hwupload")
    assert graph.chain == planned.removesuffix(",hwupload")


def test_the_output_recipe_adds_the_display_tail() -> None:
    source = recorded("letterbox.mkv")
    j = job(source, dimensions={"crop": {"mode": "manual", "rect": {"top": 22, "bottom": 24}}})
    recipe = output_recipe(j, source, caps(), DEFS)
    graph = job_video_graph(j, source, caps(), DEFS)
    assert graph is not None
    assert recipe.kind == "output"
    assert recipe.chain == [graph.chain, *DISPLAY_TAIL]
    assert recipe.prefix == source_recipe(source.video[0], caps(), DEFS).prefix
    assert recipe.notes == []


def test_an_output_that_stays_hdr_is_tone_mapped_for_display() -> None:
    source = recorded("hdr10.mkv")
    kept = output_recipe(
        job(source, video={"encoder": "libx265", "bit_depth": 10}), source, caps(), DEFS
    )
    tone = source_recipe(source.video[0], caps(), DEFS).chain[0]
    assert kept.chain[-3:] == [tone, *DISPLAY_TAIL]
    assert kept.chain[0].endswith("format=yuv420p10le")
    assert "The output stays HDR" in kept.notes[0]
    # 8-bit without tone mapping: still PQ in the frames, so still mapped for display
    eight = output_recipe(job(source), source, caps(), DEFS)
    assert eight.chain[-3] == tone
    mapped = output_recipe(job(source, filters={"tonemap": {}}), source, caps(), DEFS)
    assert mapped.chain[-2:] == list(DISPLAY_TAIL)
    assert tone not in mapped.chain
    assert mapped.notes == []


def test_a_copied_video_shows_the_source_picture() -> None:
    source = recorded("letterbox.mkv")
    recipe = output_recipe(job(source, video={"passthrough": True}), source, caps(), DEFS)
    plain = source_recipe(source.video[0], caps(), DEFS)
    assert (recipe.kind, recipe.chain, recipe.prefix) == ("output", plain.chain, plain.prefix)
    assert recipe.notes == ["The video is copied: the output frames are the source picture."]
    assert job_video_graph(job(source, video={"passthrough": True}), source, caps(), DEFS) is None


def test_burned_subtitles_are_not_drawn() -> None:
    source = recorded("multitrack.mkv")
    burn = SubtitleOutputTrack(source=source.subtitles[0].index, action="burn")
    j = job(source)
    j.subtitles = [burn]
    recipe = output_recipe(j, source, caps(), DEFS)
    assert recipe.notes == [
        "Burned-in subtitles are not drawn on the output frames; a preview clip shows them."
    ]
    assert not any("subtitles=" in part for part in recipe.chain)


@pytest.mark.parametrize(
    ("video", "message"),
    [
        ({"encoder": "no_such_encoder"}, "unknown video encoder"),
        ({"encoder": "h264_amf", "bit_depth": 10}, "has no 10-bit mode"),
    ],
)
def test_the_output_graph_fails_like_the_builder(video: dict[str, Any], message: str) -> None:
    source = recorded("letterbox.mkv")
    with pytest.raises(PlanError, match=message):
        output_recipe(job(source, video=video), source, caps(), DEFS)


def test_no_video_stream() -> None:
    source = recorded("letterbox.mkv").model_copy(update={"video": []})
    with pytest.raises(PlanError, match="no video stream"):
        output_recipe(job(source), source, caps(), DEFS)
    with pytest.raises(PlanError, match="no video stream"):
        job_video_graph(job(source), source, caps(), DEFS)


def test_an_unusable_filter_fails() -> None:
    source = recorded("letterbox.mkv")
    snapshot = caps().model_copy(update={"filter_failures": {"nlmeans": "broken"}})
    with pytest.raises(PlanError, match="denoise"):
        output_recipe(
            job(source, filters={"denoise": {"implementation": "nlmeans"}}), source, snapshot, DEFS
        )


# --------------------------------------------------------------------------- the command


def test_one_kind_needs_no_split() -> None:
    recipe = FrameRecipe(kind="source", chain=["format=rgb24"])
    argv = frame_argv("ffmpeg", Path("/m/a.mkv"), 0, 12.5, [(recipe, Path("/c/a.png"))])
    assert argv == [
        "ffmpeg", "-hide_banner", "-nostdin", "-nostats", "-loglevel", "error", "-y",
        "-ss", "12.5", "-i", "/m/a.mkv",
        "-filter_complex", "[0:0]format=rgb24[o0]",
        "-map", "[o0]", "-frames:v", "1", *PNG_ARGS, "/c/a.png",
    ]  # fmt: skip


def test_two_kinds_share_one_decode() -> None:
    prefix = ["setparams=colorspace=bt709"]
    src = FrameRecipe(kind="source", chain=["format=rgb24"], prefix=prefix)
    out = FrameRecipe(kind="output", chain=["crop=10:10:0:0", "format=rgb24"], prefix=prefix)
    argv = frame_argv(
        "ffmpeg", Path("/m/a.mkv"), 2, 0.0, [(src, Path("/s.png")), (out, Path("/o.png"))]
    )
    graph = argv[argv.index("-filter_complex") + 1]
    assert graph == (
        "[0:2]setparams=colorspace=bt709,split=2[i0][i1];"
        "[i0]format=rgb24[o0];[i1]crop=10:10:0:0,format=rgb24[o1]"
    )
    assert argv[argv.index("-ss") + 1] == "0"
    assert argv.index("-ss") < argv.index("-i")
    assert argv[-1] == "/o.png"
    assert argv.count("-frames:v") == 2


def test_a_prefix_without_split() -> None:
    recipe = FrameRecipe(kind="source", chain=[], prefix=["setparams=colorspace=bt709"])
    argv = frame_argv("ffmpeg", Path("/a.mkv"), 0, 1.0, [(recipe, Path("/a.png"))])
    assert argv[argv.index("-filter_complex") + 1] == (
        "[0:0]setparams=colorspace=bt709[i0];[i0]null[o0]"
    )


def test_frame_argv_needs_frames_with_one_prefix() -> None:
    with pytest.raises(ValueError, match="no frame"):
        frame_argv("ffmpeg", Path("/a.mkv"), 0, 1.0, [])
    a = FrameRecipe(kind="source", chain=["format=rgb24"], prefix=["setparams=colorspace=bt709"])
    b = FrameRecipe(kind="output", chain=["format=rgb24"])
    with pytest.raises(ValueError, match="share their prefix"):
        frame_argv("ffmpeg", Path("/a.mkv"), 0, 1.0, [(a, Path("/a.png")), (b, Path("/b.png"))])


def test_the_identity_covers_the_png_options() -> None:
    recipe = FrameRecipe(kind="source", chain=["format=rgb24"])
    assert recipe.identity() == ["source", [], ["format=rgb24"], list(PNG_ARGS)]
