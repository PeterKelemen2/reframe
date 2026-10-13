"""The FFmpeg behaviour the forced-only rule relies on (``subtitle.forced_only_unsupported``),
checked with the real FFmpeg (testdata/README.md "Validation (C-8)").

- ``forced_subs_only`` is a decoder option of ``pgssub`` and ``dvdsub`` only (not ``dvbsub``,
  not the text decoders).
- A stream copy does not decode, so the option changes nothing: every event is kept.
- Decoded (as for a burn-in), the VobSub fixture, which has no forced events, keeps none.
- On a text track the option is reported as unused and every event is kept.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from reframe.validation.tracks import FORCED_ONLY_CODECS

pytestmark = pytest.mark.needs_ffmpeg

Media = Callable[[str], Path]
DECODERS = {"hdmv_pgs_subtitle": "pgssub", "dvd_subtitle": "dvdsub"}


def tools() -> tuple[str, str]:
    from reframe_testing import media

    ffmpeg, ffprobe = media.find_ffmpeg(), media.find_ffprobe()
    assert ffmpeg is not None
    assert ffprobe is not None
    return ffmpeg, ffprobe


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=120, check=False)


def subtitle_packets(path: Path) -> int:
    out = run(
        tools()[1],
        "-v",
        "error",
        "-count_packets",
        "-select_streams",
        "s:0",
        "-show_entries",
        "stream=nb_read_packets",
        "-of",
        "json",
        str(path),
    )
    assert out.returncode == 0, out.stderr
    streams = json.loads(out.stdout)["streams"]
    return int(streams[0]["nb_read_packets"]) if streams else 0


@pytest.mark.parametrize(
    ("decoder", "has_option"),
    [("pgssub", True), ("dvdsub", True), ("dvbsub", False), ("subrip", False), ("ass", False)],
)
def test_forced_subs_only_is_a_pgs_and_vobsub_decoder_option(
    decoder: str, has_option: bool
) -> None:
    help_text = run(tools()[0], "-hide_banner", "-h", f"decoder={decoder}").stdout
    assert ("-forced_subs_only" in help_text) is has_option
    if has_option:
        assert decoder in {DECODERS[c] for c in FORCED_ONLY_CODECS}


def test_copy_keeps_every_event(fixture_media: Media, tmp_path: Path) -> None:
    source = fixture_media("vobsub")
    events = subtitle_packets(source)
    assert events > 0
    out = tmp_path / "copy.mkv"
    result = run(
        tools()[0], "-hide_banner", "-nostdin", "-y", "-forced_subs_only", "1",
        "-i", str(source), "-map", "0:s:0", "-c", "copy", str(out),
    )  # fmt: skip
    assert result.returncode == 0, result.stderr[-2000:]
    assert subtitle_packets(out) == events


def test_decoding_drops_the_events_that_are_not_forced(
    fixture_media: Media, tmp_path: Path
) -> None:
    source = fixture_media("vobsub")
    out = tmp_path / "decoded.mkv"
    result = run(
        tools()[0], "-hide_banner", "-nostdin", "-y", "-forced_subs_only", "1",
        "-i", str(source), "-map", "0:s:0", "-c:s", "dvdsub", str(out),
    )  # fmt: skip
    assert result.returncode == 0, result.stderr[-2000:]
    assert "Output file is empty, nothing was encoded" in result.stderr


def test_text_ignores_the_option(fixture_media: Media, tmp_path: Path) -> None:
    source = fixture_media("text-subs")
    events = subtitle_packets(source)
    out = tmp_path / "text.mkv"
    result = run(
        tools()[0], "-hide_banner", "-nostdin", "-y", "-forced_subs_only", "1",
        "-i", str(source), "-map", "0:s:0", "-c:s", "ass", str(out),
    )  # fmt: skip
    assert result.returncode == 0, result.stderr[-2000:]
    assert "was not actually used for any stream" in result.stderr
    assert subtitle_packets(out) == events
