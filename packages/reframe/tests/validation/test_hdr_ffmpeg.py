"""The plan the HDR-to-8-bit warning (``filter.hdr_8bit``) describes, run with the real FFmpeg
(testdata/README.md "Validation (C-8)").

The ``hdr10`` fixture (HEVC 10-bit, BT.2020 PQ, mastering display and content light level)
encoded to 8-bit without tone mapping: the command builder only changes the pixel format
(``format=yuv420p``), and FFmpeg keeps the colour tags and the HDR10 side data, so the output
is an 8-bit HDR10 file. Each fix of the warning gives what its label says.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

from reframe.command import build_plan
from reframe.jsonpatch import apply_patch
from reframe.models import (
    CropSettings,
    DimensionSettings,
    HdrFormat,
    JobSettings,
    MediaSource,
    OutputSettings,
    Severity,
    SourceFingerprint,
    VideoSettings,
    VideoStream,
    resolve_argv,
)
from reframe.probe import parse_ffprobe
from reframe.validation import LocalFileSystem, validate

pytestmark = pytest.mark.needs_ffmpeg

Media = Callable[[str], Path]


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"_reframe_validation_{name}", Path(__file__).with_name(f"{name}.py")
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sc = _load("scenario")
#: zscale + tonemap (CPU tone mapping) usable; libplacebo needs a GPU and is not used here.
CAPS = sc.make_caps(filters=["zscale", "tonemap"])


def tools() -> tuple[str, str]:
    from reframe_testing import media

    ffmpeg, ffprobe = media.find_ffmpeg(), media.find_ffprobe()
    assert ffmpeg is not None
    assert ffprobe is not None
    return ffmpeg, ffprobe


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=120, check=False)


def probe(path: Path) -> MediaSource:
    """``reframe.probe``'s view of ``path`` (streams and the first video frame)."""
    ffprobe = tools()[1]
    streams = run(ffprobe, "-v", "error", "-of", "json", "-show_streams", "-show_format",
                  "-show_chapters", str(path))  # fmt: skip
    frames = run(ffprobe, "-v", "error", "-of", "json", "-select_streams", "v:0",
                 "-read_intervals", "%+#1", "-show_frames", str(path))  # fmt: skip
    assert streams.returncode == 0, streams.stderr
    assert frames.returncode == 0, frames.stderr
    return parse_ffprobe(
        json.loads(streams.stdout),
        path,
        frames=json.loads(frames.stdout),
        fingerprint=SourceFingerprint(size=0, mtime=0.0),
    )


def encode(job: JobSettings, source: MediaSource, out: Path) -> VideoStream:
    """Run the builder's plan of ``job`` (written to ``out``) as the queue will, and probe
    the output's video stream."""
    job = job.model_copy(update={"output": OutputSettings(container="mkv", path=out)})
    plan = build_plan(job, source, CAPS, sc.make_tools())
    for step in plan.steps:
        if step.tool is None:
            plan.output_tmp.replace(plan.output_final)
            continue
        assert step.tool == "ffmpeg", step
        result = run(tools()[0], *resolve_argv(step.argv, {}))
        assert result.returncode == 0, result.stderr[-2000:]
    return probe(out).video[0]


def test_hdr10_to_8bit_stays_tagged_hdr(fixture_media: Media, tmp_path: Path) -> None:
    source = probe(fixture_media("hdr10"))
    hdr = source.video[0].hdr
    assert hdr is not None
    assert hdr.formats == [HdrFormat.HDR10]
    job = JobSettings(
        source=source.ref,
        output=OutputSettings(container="mkv", path=tmp_path / "out.mkv"),
        dimensions=DimensionSettings(crop=CropSettings(mode="none")),
        video=VideoSettings(encoder="libx264", preset="ultrafast", bit_depth=8),
    )
    issues = validate(job, source, CAPS, sc.make_tools(), LocalFileSystem())
    assert [i for i in issues if i.severity is Severity.ERROR] == []
    [warning] = [i for i in issues if i.code == "filter.hdr_8bit"]
    assert warning.severity is Severity.WARNING
    assert [f.label for f in warning.fixes] == [
        "Turn on tone mapping (SDR output)",
        "Encode 10-bit (keep HDR)",
    ]

    # What the warning says: 8 bits, still BT.2020 PQ with the source's HDR10 metadata.
    out = encode(job, source, tmp_path / "8bit.mkv")
    assert (out.pix_fmt, out.bit_depth) == ("yuv420p", 8)
    assert (out.color.primaries, out.color.transfer, out.color.matrix) == (
        "bt2020",
        "smpte2084",
        "bt2020nc",
    )
    assert out.hdr is not None
    assert out.hdr.formats == [HdrFormat.HDR10]
    assert out.hdr.mastering_display == hdr.mastering_display
    assert out.hdr.content_light == hdr.content_light

    # The fixes: tone mapping gives BT.709 SDR (no HDR metadata), 10-bit keeps HDR10.
    tone_mapped, ten_bit = (
        JobSettings.model_validate(apply_patch(job.model_dump(mode="json"), fix.patch))
        for fix in warning.fixes
    )
    for fixed in (tone_mapped, ten_bit):
        after = validate(fixed, source, CAPS, sc.make_tools(), LocalFileSystem())
        assert not sc.found(after, "filter.hdr_8bit")
    sdr = encode(tone_mapped, source, tmp_path / "sdr.mkv")
    assert (sdr.bit_depth, sdr.color.transfer, sdr.hdr) == (8, "bt709", None)
    kept = encode(ten_bit, source, tmp_path / "10bit.mkv")
    assert (kept.pix_fmt, kept.color.transfer) == ("yuv420p10le", "smpte2084")
    assert kept.hdr is not None
    assert kept.hdr.formats == [HdrFormat.HDR10]
