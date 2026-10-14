"""The filter graph: escaping (a known source of bugs: 05 §C-7 asks for dedicated tests),
Windows paths, the fixed filter order, colour tagging, HDR side data and burn-in."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from reframe.command import PlanError, escape_value, filter_path, quote_value, subtitles_filter
from reframe.command.filtergraph import (
    HDR_SIDE_DATA,
    BitmapBurn,
    TextBurn,
    assumed_colour,
    build_video_graph,
    filter_available,
    frame_rate_factor,
    keeps_hdr,
    overlay_format,
)
from reframe.definitions import load_definitions
from reframe.dimensions import compute_geometry, source_geometry
from reframe.models import (
    ColorInfo,
    CropRect,
    CropSettings,
    DimensionSettings,
    FilterConfig,
    Geometry,
    HdrFormat,
    HdrInfo,
    SameAsSource,
    VideoStream,
)
from reframe_testing import media

from .conftest import caps, recorded

DEFS = load_definitions()


# --------------------------------------------------------------------------- escaping


@pytest.mark.parametrize(
    ("text", "escaped"),
    [
        ("plain", "plain"),
        ("C:/x", "C\\:/x"),
        ("it's", "it\\'s"),
        ("back\\slash", "back\\\\slash"),
        ("a,b;c[d]", "a,b;c[d]"),  # graph-level characters: protected by quote_value
    ],
)
def test_escape_value(text: str, escaped: str) -> None:
    assert escape_value(text) == escaped


def test_quote_value_is_the_documented_form() -> None:
    assert quote_value("C:/Movies/Film.srt") == "'C\\:/Movies/Film.srt'"
    assert quote_value("it's") == "'it\\'\\''s'"
    assert quote_value("a,b;[c]") == "'a,b;[c]'"


@pytest.mark.parametrize(
    ("path", "text"),
    [
        (PureWindowsPath(r"C:\Movies\Film (2024).srt"), "C:/Movies/Film (2024).srt"),
        (PureWindowsPath(r"\\server\share\subs\a.ass"), "//server/share/subs/a.ass"),
        (PureWindowsPath(r"D:\it's: here\x.srt"), "D:/it's: here/x.srt"),
        (PurePosixPath("/media/a b/c:d.srt"), "/media/a b/c:d.srt"),
        (PurePosixPath("/media/back\\slash.srt"), "/media/back\\slash.srt"),
    ],
)
def test_filter_path(path: PurePosixPath | PureWindowsPath, text: str) -> None:
    assert filter_path(path) == text


def test_subtitles_filter_with_a_windows_path() -> None:
    path = PureWindowsPath(r"C:\Users\Me\Movies\It's: a test.srt")
    assert subtitles_filter(path, charenc="cp1250") == (
        "subtitles=filename='C\\:/Users/Me/Movies/It\\'\\''s\\: a test.srt':charenc='cp1250'"
    )
    assert subtitles_filter(PureWindowsPath(r"E:\a.mkv"), stream=2) == (
        "subtitles=filename='E\\:/a.mkv':si=2"
    )


#: File names with every character that either parser treats specially.
AWKWARD_NAMES = [
    "plain.srt",
    "with space.srt",
    "colon:name.srt",
    "quote'name.srt",
    "comma,semi;br[ack]et.srt",
    "back\\slash.srt",
    "percent%d =eq.srt",
    "ünï cødé \u2013 dash.srt",
    "all ' : , ; [ ] \\ \" $ & mixed.srt",
]


@pytest.mark.needs_ffmpeg
@pytest.mark.parametrize("name", AWKWARD_NAMES)
def test_subtitles_filter_opens_awkward_file_names(
    name: str, tmp_path: Path, fixture_media: Callable[[str], Path]
) -> None:
    """Real FFmpeg: the ``subtitles`` filter opens the file (a wrong path fails the run)."""
    folder = tmp_path / "dir, ;'[x]"
    folder.mkdir()
    sub = folder / name
    shutil.copy(fixture_media("text-subs").with_name("text-subs.en.srt"), sub)
    ffmpeg = media.find_ffmpeg()
    assert ffmpeg is not None
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
         "color=size=320x180:d=1", "-vf", subtitles_filter(sub), "-frames:v", "1",
         "-f", "null", "-"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""


# --------------------------------------------------------------------------- availability


def test_libplacebo_counts_only_when_its_run_test_passed() -> None:
    assert filter_available(caps(libplacebo=True), DEFS)["libplacebo"] is True
    assert filter_available(caps(libplacebo=False), DEFS)["libplacebo"] is False
    assert filter_available(caps(libplacebo=None), DEFS)["libplacebo"] is False
    unknown = filter_available(caps(filters=False), DEFS)
    assert unknown["zscale"] is True
    assert unknown["libplacebo"] is False


# --------------------------------------------------------------------------- colour


def stream(**kwargs: object) -> VideoStream:
    return VideoStream.model_validate({"index": 0, "width": 1920, "height": 1080, **kwargs})


def test_assumed_colour() -> None:
    assert assumed_colour(stream(height=480, width=720)) == ("smpte170m",) * 3
    assert assumed_colour(stream(height=576, width=720)) == ("bt470bg", "smpte170m", "bt470bg")
    assert assumed_colour(stream()) == ("bt709",) * 3
    hlg = stream(hdr=HdrInfo(formats=[HdrFormat.HLG]))
    assert assumed_colour(hlg) == ("bt2020", "arib-std-b67", "bt2020nc")
    partly = stream(color=ColorInfo(primaries="bt709", transfer="unknown", matrix="bt470bg"))
    assert assumed_colour(partly) == ("bt709", "bt709", "bt470bg")


def test_keeps_hdr() -> None:
    hdr = stream(hdr=HdrInfo(formats=[HdrFormat.HDR10]))
    assert keeps_hdr(hdr, {}, 10)
    assert not keeps_hdr(hdr, {}, 8)
    assert not keeps_hdr(hdr, {"tonemap": FilterConfig()}, 10)
    assert not keeps_hdr(hdr, {"colorspace": FilterConfig()}, 10)
    assert not keeps_hdr(stream(), {}, 10)


# --------------------------------------------------------------------------- the graph


def geometry_of(video: VideoStream, **settings: object) -> Geometry:
    dims = DimensionSettings.model_validate({"size": SameAsSource().model_dump(), **settings})
    return compute_geometry(source_geometry(video), dims)


def graph(video: VideoStream, filters: dict[str, FilterConfig], **kwargs: object) -> str:
    g = build_video_graph(
        video=video,
        filters=filters,
        geometry=kwargs.pop("geometry", None) or geometry_of(video),  # type: ignore[arg-type]
        scaler="lanczos",
        tail=["format=yuv420p"],
        definitions=DEFS,
        available=filter_available(caps(libplacebo=bool(kwargs.pop("libplacebo", True))), DEFS),
        **kwargs,  # type: ignore[arg-type]
    )
    return g.complex or g.chain or ""


def test_fixed_order_whatever_the_map_order() -> None:
    video = stream()
    chain = graph(
        video,
        {
            "grayscale": FilterConfig(),
            "sharpen": FilterConfig(preset="light"),
            "deblock": FilterConfig(preset="light"),
            "denoise": FilterConfig(implementation="hqdn3d", preset="light"),
            "deinterlace": FilterConfig(),
            "detelecine": FilterConfig(),
        },
    )
    names = [part.split("=", 1)[0] for part in chain.split(",")]
    assert names == [
        "fieldmatch", "decimate", "bwdif", "hqdn3d", "deblock", "scale", "setsar", "unsharp",
        "hue", "format",
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("config", "factor"),
    [
        (FilterConfig(), 1),
        (FilterConfig(preset="bob"), 2),
        (FilterConfig(implementation="yadif", preset="bob"), 2),
        (FilterConfig(implementation="yadif", preset="skip-spatial"), 1),
        (FilterConfig(preset="custom", custom="mode=1:parity=tff"), 2),
        (FilterConfig(implementation="yadif", preset="custom", custom="3"), 2),
        (FilterConfig(implementation="yadif", preset="custom", custom="0:1"), 1),
        (FilterConfig(preset="custom", custom="mode=send_frame"), 1),
    ],
)
def test_a_deinterlacer_that_sends_fields_doubles_the_rate(
    config: FilterConfig, factor: int
) -> None:
    g = build_video_graph(
        video=stream(), filters={"deinterlace": config}, geometry=geometry_of(stream()),
        scaler="lanczos", tail=["format=yuv420p"], definitions=DEFS,
        available=filter_available(caps(), DEFS),
    )  # fmt: skip
    assert g.rate_factor == factor


@pytest.mark.parametrize(
    ("filters", "factor"),
    [
        ({"detelecine": FilterConfig()}, Fraction(4, 5)),  # fieldmatch,decimate
        ({"detelecine": FilterConfig(preset="custom", custom="order=tff")}, Fraction(4, 5)),
        ({"custom": FilterConfig(custom="decimate=cycle=10")}, Fraction(9, 10)),
        ({"custom": FilterConfig(custom="decimate=2")}, Fraction(1, 2)),
        ({"custom": FilterConfig(custom="decimate=mixed=1")}, Fraction(1)),  # variable output
        ({"custom": FilterConfig(custom="decimate=cycle=x")}, Fraction(1)),  # FFmpeg refuses it
        ({"custom": FilterConfig(custom="fps=25")}, Fraction(1)),  # not followed
        ({"detelecine": FilterConfig(), "deinterlace": FilterConfig(preset="bob")},
         Fraction(8, 5)),
    ],
)  # fmt: skip
def test_detelecine_lowers_the_rate(filters: dict[str, FilterConfig], factor: Fraction) -> None:
    """M2 review, second round: ``decimate`` drops one frame in five."""
    g = build_video_graph(
        video=stream(), filters=filters, geometry=geometry_of(stream()), scaler="lanczos",
        tail=["format=yuv420p"], definitions=DEFS, available=filter_available(caps(), DEFS),
    )  # fmt: skip
    assert g.rate_factor == factor


def test_frame_rate_factor() -> None:
    assert frame_rate_factor("scale=1:1,yadif=1") == 2
    assert frame_rate_factor("scale=1:1,yadif") == 1
    assert frame_rate_factor("fieldmatch,decimate,bwdif=mode=send_field") == Fraction(8, 5)


def test_combed_only_is_added_with_interlace_detection() -> None:
    chain = graph(stream(), {"interlace_detection": FilterConfig(), "deinterlace": FilterConfig()})
    assert "idet,bwdif=mode=send_frame:parity=auto:deint=interlaced" in chain
    custom = graph(
        stream(),
        {
            "interlace_detection": FilterConfig(),
            "deinterlace": FilterConfig(preset="custom", custom=""),
        },
    )
    assert "bwdif=deint=interlaced" in custom


def test_empty_custom_filter_is_left_out() -> None:
    assert graph(stream(), {"custom": FilterConfig(custom="  ")}) == (
        "scale=1920:1080:flags=lanczos,setsar=1/1,format=yuv420p"
    )


def test_setparams_only_for_an_untagged_source() -> None:
    untagged = graph(stream(), {"colorspace": FilterConfig(preset="bt2020")})
    assert "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709,zscale=p=bt2020" in (
        untagged
    )
    tagged = stream(color=ColorInfo(primaries="bt709", transfer="bt709", matrix="bt709"))
    assert "setparams" not in graph(tagged, {"colorspace": FilterConfig(preset="bt2020")})


def test_hdr_side_data_is_removed_after_tone_mapping() -> None:
    src = recorded("hdr10")
    chain = graph(src.video[0], {"tonemap": FilterConfig()})
    deletes = [f"sidedata=mode=delete:type={t}" for t in HDR_SIDE_DATA]
    assert chain.index("libplacebo=") < chain.index(deletes[0])
    assert all(d in chain for d in deletes)
    zscale = graph(src.video[0], {"tonemap": FilterConfig()}, libplacebo=False)
    assert "zscale=t=linear" in zscale
    assert "libplacebo" not in zscale
    colour_only = graph(src.video[0], {"colorspace": FilterConfig()})
    assert deletes[0] in colour_only


def test_tone_mapping_an_sdr_source_does_nothing() -> None:
    assert "tonemap" not in graph(stream(), {"tonemap": FilterConfig()})


def test_unusable_filters_raise() -> None:
    with pytest.raises(PlanError, match="unknown filter"):
        graph(stream(), {"vignette": FilterConfig()})
    with pytest.raises(PlanError, match="cannot be used"):
        graph(
            recorded("hdr10").video[0],
            {"tonemap": FilterConfig(implementation="libplacebo")},
            libplacebo=False,
        )
    with pytest.raises(PlanError, match="preset 'nope'"):
        graph(stream(), {"denoise": FilterConfig(preset="nope")})
    with pytest.raises(PlanError, match="yadif, preset 'x'"):
        graph(stream(), {"deinterlace": FilterConfig(implementation="yadif", preset="x")})


def test_the_default_preset_is_the_implementations_default() -> None:
    """``FilterConfig()`` says ``default``; Denoise's implementations call theirs ``light``."""
    assert "nlmeans=s=2.1" in graph(stream(), {"denoise": FilterConfig()})
    assert "hqdn3d=luma_spatial=2" in graph(
        stream(), {"denoise": FilterConfig(implementation="hqdn3d")}
    )
    assert "zscale=p=bt709:t=bt709:m=bt709" in graph(stream(), {"colorspace": FilterConfig()})
    # An unknown tune falls back to the preset's plain chain (C-6's FilterPreset.chain_for).
    assert "nlmeans=s=2.1:p=7" in graph(stream(), {"denoise": FilterConfig(tune="nope")})


def test_text_burn_in_comes_last_with_its_time_shift() -> None:
    burn = TextBurn(path=PurePosixPath("/m/a.srt"), stream=None, charenc="cp1250", shift=12.5)
    chain = graph(stream(), {"grayscale": FilterConfig()}, text_burn=burn)
    assert chain.endswith(
        "hue=s=0,setpts=PTS+12.5/TB,subtitles=filename='/m/a.srt':charenc='cp1250',"
        "setpts=PTS-12.5/TB,format=yuv420p"
    )


def test_a_negative_time_shift() -> None:
    """An external file's offset larger than the range start: the frames move back."""
    burn = TextBurn(path=PurePosixPath("/m/a.srt"), stream=None, shift=-0.5)
    assert graph(stream(), {}, text_burn=burn).endswith(
        "setpts=PTS-0.5/TB,subtitles=filename='/m/a.srt',setpts=PTS+0.5/TB,format=yuv420p"
    )


def test_bitmap_overlay_is_bottom_aligned_in_the_cropped_picture() -> None:
    video = stream()
    crop = CropSettings(mode="manual", rect=CropRect(top=130, bottom=140, left=10, right=0))
    g = geometry_of(video, crop=crop.model_dump())
    burn = BitmapBurn(input_label="0:5", canvas=(1280, 720))
    assert graph(video, {"deinterlace": FilterConfig()}, geometry=g, bitmap_burn=burn) == (
        "[0:0]bwdif=mode=send_frame:parity=auto,crop=1910:810:10:130[base];"
        "[0:5]scale=1920:1080[subs];"
        "[base][subs]overlay=x=-10:y=-270:eof_action=pass,"
        "scale=1910:810:flags=lanczos,setsar=1/1,format=yuv420p[v]"
    )
    plain = graph(video, {}, bitmap_burn=BitmapBurn(input_label="1:0", canvas=(1920, 1080)))
    assert plain == (
        "[0:0][1:0]overlay=eof_action=pass,scale=1920:1080:flags=lanczos,setsar=1/1,"
        "format=yuv420p[v]"
    )


@pytest.mark.parametrize(
    ("bit_depth", "pix_fmt", "expected"),
    [
        (8, "yuv420p", None),  # overlay's default: 8-bit 4:2:0
        (None, None, None),
        (10, "yuv420p10le", "yuv420p10"),
        (10, "p010le", "yuv420p10"),
        (10, "yuv422p10le", "yuv422p10"),
        (12, "yuv444p12le", "yuv444p10"),  # the deepest format overlay has
    ],
)
def test_bitmap_overlay_keeps_more_than_8_bits(
    bit_depth: int | None, pix_fmt: str | None, expected: str | None
) -> None:
    """M2 review, finding M3: ``overlay`` cut a 10-bit source to 8 bits."""
    video = stream(bit_depth=bit_depth, pix_fmt=pix_fmt)
    assert overlay_format(video) == expected
    written = graph(video, {}, bitmap_burn=BitmapBurn(input_label="0:5", canvas=(1920, 1080)))
    assert ("overlay=eof_action=pass:format=" in written) is (expected is not None)
