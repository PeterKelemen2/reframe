"""The dimension maths against the real FFmpeg: the rules it relies on, and the filter chains
run on real files."""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from reframe.dimensions import (
    chroma_steps,
    compute_geometry,
    rotate_crop,
    source_geometry,
)
from reframe.models import (
    CropRect,
    CropSettings,
    DimensionSettings,
    FitWithin,
    Geometry,
    MediaSource,
    SameAsSource,
    VideoStream,
)
from reframe.probe import Prober

pytestmark = pytest.mark.needs_ffmpeg

Media = Callable[[str], Path]


def tools() -> tuple[str, str]:
    from reframe_testing import media

    ffmpeg, ffprobe = media.find_ffmpeg(), media.find_ffprobe()
    assert ffmpeg is not None
    assert ffprobe is not None
    return ffmpeg, ffprobe


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=120, check=False)


def ffmpeg(*args: str) -> subprocess.CompletedProcess[str]:
    result = run(tools()[0], "-hide_banner", "-nostdin", *args)
    assert result.returncode == 0, result.stderr[-2000:]
    return result


def stream_info(path: Path) -> dict[str, Any]:
    out = run(
        tools()[1],
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,sample_aspect_ratio:stream_side_data",
        "-of",
        "json",
        str(path),
    )
    info: dict[str, Any] = json.loads(out.stdout)["streams"][0]
    return info


async def video_stream(path: Path) -> VideoStream:
    outcome = await Prober(tools()[1]).probe(path)
    assert isinstance(outcome, MediaSource), outcome
    return outcome.video[0]


def filter_chain(g: Geometry, scaler: str = "lanczos", *, setsar: bool = True) -> str:
    parts: list[str] = []
    c = g.crop
    if any((c.top, c.bottom, c.left, c.right)):
        parts.append(f"crop={g.cropped_width}:{g.cropped_height}:{c.left}:{c.top}")
    parts += {
        0: [],
        90: ["transpose=clock"],
        180: ["hflip", "vflip"],
        270: ["transpose=cclock"],
    }[g.filter_rotation]
    if g.flip_horizontal:
        parts.append("hflip")
    parts.append(f"scale={g.scaled_width}:{g.scaled_height}:flags={scaler}")
    if setsar:
        parts.append(f"setsar={g.output_sar.num}/{g.output_sar.den}")
    return ",".join(parts)


def encode(source: Path, out: Path, vf: str, *before_input: str) -> dict[str, Any]:
    ffmpeg(
        "-v", "error", "-y", *before_input, "-i", str(source), "-frames:v", "1",
        "-vf", vf, "-c:v", "ffv1", str(out),
    )  # fmt: skip
    return stream_info(out)


def frame_md5(source: Path, vf: str) -> str:
    out = ffmpeg(
        "-v", "error", "-i", str(source), "-frames:v", "1", "-vf", vf, "-f", "framemd5", "-",
    ).stdout  # fmt: skip
    return out.strip().splitlines()[-1].split(",")[-1].strip()


def sar_of(info: dict[str, Any]) -> str:
    return str(info.get("sample_aspect_ratio", "1:1"))


def _pixel_formats() -> list[str]:
    """Every pixel format that swscale can write (no hardware, paletted or bitstream ones)."""
    listing = run(tools()[0], "-hide_banner", "-pix_fmts").stdout
    names = []
    for line in listing.splitlines():
        match = re.match(r"^([IOHPB.]{5}) (\S+)\s+\d+\s+\d+", line)
        if match and match.group(1)[1] == "O" and match.group(1)[2:] == "...":
            names.append(match.group(2))
    return names


def test_chroma_steps_match_ffmpeg_crop_for_every_pixel_format() -> None:
    """Crop rounds 35 down to its grid for each pixel format, which shows the steps it uses."""
    names = _pixel_formats()
    assert len(names) > 100
    labels = "".join(f"[s{i}]" for i in range(len(names)))
    graph = [f"color=size=64x64:d=0.04,split={len(names) + 1}{labels}[out]"]
    graph += [f"[s{i}]format={n},crop@grid_{n}=35:35:3:3,nullsink" for i, n in enumerate(names)]
    result = ffmpeg(
        "-v", "verbose", "-filter_complex", ";".join(graph), "-map", "[out]",
        "-frames:v", "1", "-f", "null", "-",
    )  # fmt: skip
    line = re.compile(r"\[crop@grid_(\S+) @ [^]]*\] w:64 h:64 .*-> w:(\d+) h:(\d+)")
    seen = {m[1]: (int(m[2]), int(m[3])) for m in line.finditer(result.stderr)}
    assert set(seen) == set(names)
    wrong = {}
    for name, size in seen.items():
        steps = chroma_steps(name)
        expected = None if steps is None else (35 // steps[0] * steps[0], 35 // steps[1] * steps[1])
        if expected != size:
            wrong[name] = (steps, size)
    assert wrong == {}


def test_crop_rounds_silently_to_the_grid(tmp_path: Path, fixture_media: Media) -> None:
    """Unsnapped numbers give a different picture than asked; snapped ones are exact."""
    source = fixture_media("letterbox")  # 320x180 4:2:0, 2.39:1 bars: top 22, bottom 24
    raw = encode(source, tmp_path / "raw.mkv", "crop=319:135:1:23")
    assert (raw["width"], raw["height"]) == (318, 134)
    first = frame_md5(source, "crop=318:134:1:23")
    assert first == frame_md5(source, "crop=318:134:0:22")
    assert first != frame_md5(source, "crop=318:134:2:24")
    odd = ffmpeg(
        "-v", "verbose", "-f", "lavfi", "-i", "color=size=853x481:d=0.04", "-frames:v", "1",
        "-vf", "format=yuv420p,crop=iw:ih", "-f", "null", "-",
    )  # fmt: skip
    assert re.search(r"w:853 h:481 .*-> w:852 h:480", odd.stderr)


@pytest.mark.parametrize(
    ("height", "interlaced", "ok"),
    [(240, False, True), (241, False, False), (240, True, True), (242, True, False)],
)
def test_x264_height_rules_for_4_2_0(height: int, interlaced: bool, ok: bool) -> None:
    flags = ["-flags", "+ildct+ilme"] if interlaced else []
    result = run(
        tools()[0], "-hide_banner", "-nostdin", "-v", "error", "-f", "lavfi",
        "-i", f"color=size=320x{height}:d=0.1", "-pix_fmt", "yuv420p", *flags,
        "-c:v", "libx264", "-f", "null", "-",
    )  # fmt: skip
    assert (result.returncode == 0) is ok, result.stderr
    if not ok:
        divisor = 4 if interlaced else 2
        assert f"height not divisible by {divisor} (320x{height})" in result.stderr


@pytest.mark.anyio
async def test_anamorphic_dvd_to_square_pixels(tmp_path: Path, fixture_media: Media) -> None:
    source = fixture_media("anamorphic")
    src = source_geometry(await video_stream(source))
    assert (src.width, src.height, src.sar.num, src.sar.den) == (720, 480, 32, 27)
    g = compute_geometry(src, DimensionSettings(crop=CropSettings(mode="none")))
    assert (g.scaled_width, g.scaled_height, str(g.output_sar)) == (854, 480, "1/1")
    out = encode(source, tmp_path / "square.mkv", filter_chain(g))
    assert (out["width"], out["height"], sar_of(out)) == (854, 480, "1:1")
    # Without setsar, scale keeps the display aspect with a SAR of its own.
    out = encode(source, tmp_path / "no-setsar.mkv", filter_chain(g, setsar=False))
    assert sar_of(out) == "1280:1281"


@pytest.mark.anyio
async def test_anamorphic_dvd_crop_keeping_the_pixel_aspect(
    tmp_path: Path, fixture_media: Media
) -> None:
    source = fixture_media("anamorphic")
    src = source_geometry(await video_stream(source))
    crop = CropSettings(mode="manual", rect=CropRect(left=9, right=7))
    g = compute_geometry(src, DimensionSettings(crop=crop, pixel_aspect="keep"))
    assert (g.crop.left, g.crop.right, g.cropped_width, g.cropped_height) == (8, 6, 706, 480)
    assert (g.scaled_width, g.scaled_height, str(g.output_sar)) == (706, 480, "32/27")
    out = encode(source, tmp_path / "keep.mkv", filter_chain(g))
    assert (out["width"], out["height"], sar_of(out)) == (706, 480, "32:27")


@pytest.mark.anyio
async def test_letterbox_crop_and_fit(tmp_path: Path, fixture_media: Media) -> None:
    source = fixture_media("letterbox")
    src = source_geometry(await video_stream(source))
    rect = CropRect(top=23, bottom=23, left=1)
    s = DimensionSettings(
        crop=CropSettings(mode="manual", rect=rect),
        size=FitWithin(width=160, height=160),
    )
    g = compute_geometry(src, s)
    assert (g.crop.top, g.crop.bottom, g.crop.left, g.crop.right) == (22, 22, 0, 0)
    assert (g.cropped_width, g.cropped_height) == (320, 136)
    assert (g.scaled_width, g.scaled_height) == (160, 68)
    out = encode(source, tmp_path / "letterbox.mkv", filter_chain(g))
    assert (out["width"], out["height"], sar_of(out)) == (160, 68, "1:1")


@pytest.fixture(scope="module")
def corner_source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """64x32 black, SAR 32:27, with a white 16x8 box in the top-left corner of the frame."""
    path = tmp_path_factory.mktemp("rotation") / "corner.mkv"
    ffmpeg(
        "-v", "error", "-y", "-f", "lavfi", "-i", "color=black:size=64x32:d=0.04",
        "-vf", "drawbox=x=0:y=0:w=16:h=8:color=white:t=fill,format=yuv420p,setsar=32/27",
        "-frames:v", "1", "-c:v", "ffv1", str(path),
    )  # fmt: skip
    return path


def with_display_matrix(source: Path, rotation: int, out: Path) -> Path:
    """``source`` with a display matrix that turns it ``rotation`` degrees clockwise."""
    counter_clockwise = (360 - rotation) % 360
    ffmpeg(
        "-v", "error", "-y", "-display_rotation:v:0", str(counter_clockwise),
        "-i", str(source), "-c", "copy", str(out),
    )  # fmt: skip
    return out


_CLOCKWISE = {
    ("top", "left"): ("top", "right"),
    ("top", "right"): ("bottom", "right"),
    ("bottom", "right"): ("bottom", "left"),
    ("bottom", "left"): ("top", "left"),
}


def expected_corner(rotation: int, flip: bool) -> tuple[str, str]:
    corner = ("top", "left")
    for _ in range(rotation // 90):
        corner = _CLOCKWISE[corner]
    if flip:
        corner = (corner[0], "right" if corner[1] == "left" else "left")
    return corner


def bright_corner(path: Path, width: int, height: int) -> tuple[str, str] | None:
    """The quarter of the decoded frame where the white box is, or ``None`` if none is."""
    frame = subprocess.run(
        [tools()[0], "-v", "error", "-i", str(path), "-frames:v", "1", "-f", "rawvideo",
         "-pix_fmt", "gray", "-"],
        capture_output=True, timeout=120, check=True,
    ).stdout  # fmt: skip
    assert len(frame) == width * height
    means = {}
    for vertical, rows in (("top", range(height // 2)), ("bottom", range(height // 2, height))):
        for horizontal, start in (("left", 0), ("right", width // 2)):
            values = [frame[y * width + x] for y in rows for x in range(start, start + width // 2)]
            means[(vertical, horizontal)] = sum(values) / len(values)
    best = max(means, key=lambda k: means[k])
    return best if means[best] > 40 else None


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("source_rotation", "job_rotation", "flip"),
    [(90, 0, False), (270, 0, False), (90, 90, True), (180, 270, False), (0, 90, False),
     (0, 180, True), (270, 270, True)],
)  # fmt: skip
async def test_rotation_chain(
    tmp_path: Path, corner_source: Path, source_rotation: int, job_rotation: int, flip: bool
) -> None:
    source = with_display_matrix(corner_source, source_rotation, tmp_path / "rotated.mkv")
    src = source_geometry(await video_stream(source))
    assert (src.width, src.height, src.rotation) == (64, 32, source_rotation)
    total = (source_rotation + job_rotation) % 360

    # Keep the pixel aspect, no setsar: FFmpeg's own SAR after its transposes must be ours.
    keep = DimensionSettings(
        crop=CropSettings(mode="none"),
        size=SameAsSource(),
        pixel_aspect="keep",
        rotate=job_rotation,  # type: ignore[arg-type]
        flip_horizontal=flip,
    )
    g = compute_geometry(src, keep)
    out_path = tmp_path / "keep.mkv"
    out = encode(source, out_path, filter_chain(g, setsar=False))
    assert (out["width"], out["height"]) == (g.scaled_width, g.scaled_height)
    assert sar_of(out) == f"{g.output_sar.num}:{g.output_sar.den}"
    assert "side_data_list" not in out  # no display matrix: it is not turned twice
    assert bright_corner(out_path, out["width"], out["height"]) == expected_corner(total, flip)

    # Square pixels with a crop that removes the box: the crop is in the displayed picture.
    displayed_crop = rotate_crop(CropRect(top=8), src.rotation)  # the box's rows, displayed
    square = keep.model_copy(
        update={"pixel_aspect": "square", "crop": CropSettings(mode="manual", rect=displayed_crop)}
    )
    g = compute_geometry(src, square)
    out_path = tmp_path / "square.mkv"
    out = encode(source, out_path, filter_chain(g))
    assert (out["width"], out["height"], sar_of(out)) == (g.scaled_width, g.scaled_height, "1:1")
    assert bright_corner(out_path, out["width"], out["height"]) is None


@pytest.mark.anyio
async def test_portrait_fit_turns_the_box(tmp_path: Path, corner_source: Path) -> None:
    """The 64x32 corner file turned 90° by its display matrix is portrait (32x64, SAR 27:32);
    "Fit within 48x24" fits it inside 24x48 with its long side vertical."""
    source = with_display_matrix(corner_source, 90, tmp_path / "rotated.mkv")
    src = source_geometry(await video_stream(source))
    s = DimensionSettings(crop=CropSettings(mode="none"), size=FitWithin(width=48, height=24))
    g = compute_geometry(src, s)
    assert g.notes[0] == "Portrait picture: fit box turned to 24\u00d748."
    assert (g.scaled_width, g.scaled_height) == (20, 48)
    out_path = tmp_path / "portrait.mkv"
    out = encode(source, out_path, filter_chain(g))
    assert (out["width"], out["height"], sar_of(out)) == (20, 48, "1:1")
    assert bright_corner(out_path, 20, 48) == expected_corner(90, False)


def test_noautorotate_keeps_the_display_matrix(tmp_path: Path, corner_source: Path) -> None:
    from reframe.tools.versions import parse_ffmpeg_version

    version = parse_ffmpeg_version(run(tools()[0], "-hide_banner", "-version").stdout)
    assert version is not None
    assert version.series is not None
    source = with_display_matrix(corner_source, 90, tmp_path / "rotated.mkv")
    out = encode(source, tmp_path / "noauto.mkv", "transpose=clock", "-noautorotate")
    rotations = [d.get("rotation") for d in out.get("side_data_list", [])]
    if version.series >= (9, 0):
        assert rotations == [-90]  # still there: a player would turn the picture again
    else:
        assert rotations == []  # n8.1.3: -noautorotate does not copy the display matrix
    out = encode(
        source, tmp_path / "noauto0.mkv", "transpose=clock",
        "-noautorotate", "-display_rotation:v:0", "0",
    )  # fmt: skip
    assert "side_data_list" not in out  # the way out for a builder that rotates by itself
    out = encode(source, tmp_path / "auto.mkv", "null")
    assert (out["width"], out["height"]) == (32, 64)
    assert "side_data_list" not in out
