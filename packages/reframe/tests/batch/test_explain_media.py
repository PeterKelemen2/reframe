"""Foreign audio search and default tracks on a ``multitrack`` file that mkvmerge has changed."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from reframe.batch import draft_tracks
from reframe.models import (
    JobTemplate,
    LanguageSettings,
    MediaSource,
    SubtitleDefaults,
    TrackSelection,
)
from reframe.probe import Prober
from reframe.tools import discover_tools, run

FORCED_SRT = "1\n00:00:01,000 --> 00:00:02,000\nElvish: Hello\n"


def _mkvmerge() -> str:
    from reframe.tools.discovery import locate_tools

    location = locate_tools().get("mkvmerge")  # type: ignore[call-overload]
    if location is not None and location.path is not None and location.problem is None:
        return str(location.path)
    found = shutil.which("mkvmerge")
    if found is None:
        pytest.skip("mkvmerge not found")
    return found


@pytest.mark.needs_ffmpeg
@pytest.mark.anyio
async def test_foreign_audio_search_on_an_mkvmerge_file(
    fixture_media: Callable[[str], Path], tmp_path: Path
) -> None:
    srt = tmp_path / "forced.srt"
    srt.write_text(FORCED_SRT, encoding="utf-8")
    out = tmp_path / "fas.mkv"
    argv = [
        _mkvmerge(),
        "-q",
        "-o",
        str(out),
        str(fixture_media("multitrack")),
        "--language",
        "0:eng",
        "--track-name",
        "0:Forced",
        "--forced-display-flag",
        "0:1",
        str(srt),
    ]
    muxed = await run(argv, timeout=60)
    assert muxed.returncode == 0, muxed
    tools = await discover_tools()
    source = await Prober(tools.ffprobe).probe(out)
    assert isinstance(source, MediaSource)
    forced = source.subtitles[-1]
    # What the selection relies on: ffprobe's forced flag and mkvmerge's NUMBER_OF_FRAMES.
    assert (forced.index, forced.title, forced.disposition.forced) == (7, "Forced", True)
    assert (forced.event_count, forced.event_count_source) == (1, "stats_tag")
    assert forced.disposition.default
    assert [s.disposition.default for s in source.subtitles] == [True, False, False, True]

    plain = draft_tracks(source, JobTemplate())
    assert [(t.source, t.metadata.default) for t in plain.subtitles] == [
        (4, True),
        (5, False),
        (6, False),
        (7, False),
    ]

    # English audio, English subtitles: the search takes the first forced English track
    # (the fixture's flagged "Signs & Songs", #6) and puts it first; "forced" makes it the
    # default subtitle.
    template = JobTemplate(
        subtitle_defaults=SubtitleDefaults(
            selection=TrackSelection(no_match="none", default_track="forced"),
            foreign_audio_search=True,
        )
    )
    languages = LanguageSettings(preferred_audio=["en"], preferred_subtitle=["en"])
    draft = draft_tracks(source, template, languages=languages)
    assert [t.source_stream for t in draft.audio] == [2]  # the commentary is dropped
    assert [
        (t.source, t.action, t.metadata.forced, t.metadata.default) for t in draft.subtitles
    ] == [
        (6, "copy", True, True),
        (4, "copy", False, False),
    ]
    row = next(d for d in draft.subtitle_decisions if d.source_stream == 6)
    assert row.selection == (
        "Foreign audio search: #6 is the forced English track (forced flag) for the English audio"
    )
