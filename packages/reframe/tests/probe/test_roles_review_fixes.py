"""A subtitle track with 0 events is empty, not a forced track, as real tools write it."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from reframe.batch import foreign_audio_search
from reframe.models import MediaSource, RoleEvidence, TrackRole
from reframe.probe import Prober
from reframe.tools import discover_tools, run

FULL_SRT = "".join(
    f"{n}\n00:00:0{n - 1},100 --> 00:00:0{n - 1},400\nLine {n}\n\n" for n in range(1, 5)
)
LATE_SRT = "1\n00:00:10,000 --> 00:00:11,000\nAfter the end\n"


def _tool(name: str) -> str:
    from reframe.tools.discovery import locate_tools

    location = locate_tools().get(name)  # type: ignore[call-overload]
    if location is not None and location.path is not None and location.problem is None:
        return str(location.path)
    found = shutil.which(name)
    if found is None:
        pytest.skip(f"{name} not found")
    return found


@pytest.mark.needs_ffmpeg
@pytest.mark.anyio
async def test_an_empty_subtitle_track_is_not_forced(tmp_path: Path) -> None:
    from reframe_testing import media

    ffmpeg = media.find_ffmpeg()
    assert ffmpeg is not None
    full, late = tmp_path / "full.srt", tmp_path / "late.srt"
    full.write_text(FULL_SRT, encoding="utf-8")
    late.write_text(LATE_SRT, encoding="utf-8")
    out = tmp_path / "empty-sub.mkv"
    argv = [
        ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10:duration=4",
        "-i", str(full), "-i", str(late),
        "-map", "0", "-map", "1", "-map", "2",
        "-c:v", "libx264", "-c:s", "srt",
        "-metadata:s:s:0", "language=eng", "-metadata:s:s:1", "language=eng",
        "-t", "4", str(out),
    ]  # fmt: skip
    muxed = await run(argv, timeout=60)
    assert muxed.returncode == 0, muxed
    stats = await run([_tool("mkvpropedit"), str(out), "--add-track-statistics-tags"], timeout=60)
    assert stats.returncode == 0, stats

    tools = await discover_tools()
    source = await Prober(tools.ffprobe).probe(out)
    assert isinstance(source, MediaSource)
    # What the real tools write and the probe reads.
    assert [(s.index, s.event_count, s.event_count_source) for s in source.subtitles] == [
        (1, 4, "stats_tag"),
        (2, 0, "stats_tag"),
    ]
    empty = source.subtitles[1]
    assert [(r.role, r.evidence) for r in empty.roles] == [(TrackRole.MAIN, RoleEvidence.HEURISTIC)]
    # The foreign audio search does not take the empty track either.
    found = foreign_audio_search(
        source.subtitles, audio_language="en", user_language="en", can_burn=False
    )
    assert found.searched
    assert found.track is None
