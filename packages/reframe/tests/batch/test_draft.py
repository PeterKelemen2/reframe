"""C-12 M2 track drafts (decision 0018): every audio track through the codec rules, every
subtitle copied, metadata from the source.

The sources are the recorded probes of the generated fixtures (``testdata/probes/fixtures``,
pinned FFmpeg build), so the result does not depend on the FFmpeg that runs the tests; one
test probes the generated ``multitrack`` file with the real ffprobe.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from reframe.batch import draft_tracks, first_of_language
from reframe.models import (
    AudioCodecRule,
    AudioDefaults,
    AudioOutputTrack,
    AudioStream,
    JobTemplate,
    MediaSource,
    OutputOptions,
    SourceFingerprint,
    SubtitleOutputTrack,
    TrackFlags,
    TrackMetadata,
)
from reframe.probe import Prober, parse_ffprobe
from reframe.tools import discover_tools

PROBES = Path(__file__).resolve().parents[4] / "testdata" / "probes" / "fixtures"
SEASON = sorted((PROBES / "season").glob("*.json"))


def recorded(rel: str) -> MediaSource:
    path = PROBES / rel
    data = json.loads(path.read_text(encoding="utf-8"))
    name = rel.removesuffix(".json")
    return parse_ffprobe(
        data, Path("/media", name), fingerprint=SourceFingerprint(size=0, mtime=0.0)
    )


def flags(**on: bool) -> dict[str, bool]:
    return {name: on.get(name, False) for name in TrackFlags.model_fields}


#: ``draft_tracks(multitrack, JobTemplate())``: the default catch-all rule (AAC, up to 5.1,
#: 256 kb/s, passthru when the source fits). The AAC tracks have no bit rate in an
#: FFmpeg-made MKV; a lossy source fits at any bit rate (decision 0023), so they pass through.
MULTITRACK_AUDIO = [
    AudioOutputTrack(
        action="passthru",
        encoder="aac",
        source_stream=1,
        metadata=TrackMetadata(language="ja", name="Japanese 5.1", **flags(default=True)),
    ),
    AudioOutputTrack(
        action="passthru",
        encoder="aac",
        source_stream=2,
        metadata=TrackMetadata(language="en", name="English Stereo", **flags()),
    ),
    AudioOutputTrack(
        action="passthru",
        encoder="aac",
        source_stream=3,
        metadata=TrackMetadata(
            language="en", name="Director's Commentary", **flags(commentary=True)
        ),
    ),
]
MULTITRACK_SUBTITLES = [
    SubtitleOutputTrack(
        source=4,
        action="copy",
        metadata=TrackMetadata(language="en", name="English", **flags(default=True)),
    ),
    SubtitleOutputTrack(
        source=5,
        action="copy",
        metadata=TrackMetadata(language="en", name="English SDH", **flags(hearing_impaired=True)),
    ),
    SubtitleOutputTrack(
        source=6,
        action="copy",
        metadata=TrackMetadata(language="en", name="Signs & Songs", **flags(forced=True)),
    ),
]
MULTITRACK_REASONS = [
    (1, 1, "AC-3, 5.1, 192 ≤ 256: passthru", False),
    (2, 1, "AAC, 2.0: passthru", False),
    (3, 1, "AAC, 2.0: passthru", False),
]


def check_multitrack(source: MediaSource) -> None:
    draft = draft_tracks(source, JobTemplate())
    assert draft.audio == MULTITRACK_AUDIO
    assert draft.subtitles == MULTITRACK_SUBTITLES
    assert [(d.source_stream, d.rule, d.reason, d.measure) for d in draft.decisions] == (
        MULTITRACK_REASONS
    )
    assert [t for d in draft.decisions for t in d.outputs] == draft.audio


def test_multitrack() -> None:
    check_multitrack(recorded("multitrack.mkv.json"))


@pytest.mark.needs_ffmpeg
@pytest.mark.anyio
async def test_multitrack_probed_live(fixture_media: Callable[[str], Path]) -> None:
    """The same draft from the generated file, probed with this machine's ffprobe."""
    tools = await discover_tools()
    source = await Prober(tools.ffprobe).probe(fixture_media("multitrack"))
    assert isinstance(source, MediaSource)
    check_multitrack(source)


def test_season() -> None:
    """Every episode: one output per audio track in source order, every subtitle copied.
    E05 has an extra commentary track, E09 lacks the commentary (``scripts/make-testdata.py``)."""
    assert len(SEASON) == 12
    counts = []
    for path in SEASON:
        source = recorded(f"season/{path.name}")
        draft = draft_tracks(source, JobTemplate())
        counts.append(len(draft.audio))
        assert [t.source_stream for t in draft.audio] == [a.index for a in source.audio]
        assert [d.source_stream for d in draft.decisions] == [a.index for a in source.audio]
        assert [s.source for s in draft.subtitles] == [s.index for s in source.subtitles]
        assert all(s.action == "copy" for s in draft.subtitles)
        for track, stream in zip(draft.audio, source.audio, strict=True):
            assert track.metadata.name == stream.title
            assert track.metadata.default == stream.disposition.default
            assert track.metadata.commentary == stream.disposition.comment
    assert counts == [3, 3, 3, 3, 4, 3, 3, 3, 2, 3, 3, 3]
    e05 = draft_tracks(recorded("season/Show.S01E05.Title.mkv.json"), JobTemplate())
    commentary = e05.audio[3]
    assert (commentary.metadata.name, commentary.metadata.commentary) == ("Commentary", True)
    assert commentary.action == "passthru"
    assert e05.decisions[3].reason == "AC-3, 2.0, 96 ≤ 256: passthru"


def test_container_and_rules_of_the_template() -> None:
    """The template's container and audio defaults are used: in WebM an AC-3 track cannot
    pass through; a rule for English takes the English tracks."""
    source = recorded("multitrack.mkv.json")
    template = JobTemplate(
        output=OutputOptions(container="webm"),
        audio_defaults=AudioDefaults(
            codec_rules=[
                AudioCodecRule(languages=["en"], codec="libopus", mixdown="stereo", max_bitrate=96),
                AudioCodecRule(codec="libopus", mixdown="up_to_5.1", max_bitrate=256),
            ]
        ),
    )
    draft = draft_tracks(source, template)
    assert [(t.action, t.encoder, t.mixdown, t.bitrate) for t in draft.audio] == [
        ("encode", "libopus", None, 192),
        ("encode", "libopus", "stereo", 96),
        ("encode", "libopus", "stereo", 96),
    ]
    assert [d.rule for d in draft.decisions] == [2, 1, 1]
    assert draft.decisions[0].reason == (
        "192 ≤ 256, but WebM cannot hold AC-3 → encode at 192 kb/s, the smallest allowed value"
        " ≥ 192"
    )
    # Subtitles are copied whatever the container (the builder and validation apply 03's
    # container rules).
    assert [s.action for s in draft.subtitles] == ["copy", "copy", "copy"]


def test_first_track_of_language_in_source_order() -> None:
    def audio(index: int, language: str | None, ietf: str | None = None) -> AudioStream:
        return AudioStream(index=index, language=language, language_ietf=ietf, channels=2)

    streams = [
        audio(1, "jpn"),
        audio(2, "eng"),
        audio(3, "eng"),
        audio(4, "ger"),
        audio(5, "deu"),
        audio(6, None),
        audio(7, "und"),
        audio(8, "por", "pt-BR"),
        audio(9, "por"),
    ]
    assert first_of_language(streams) == [True, True, False, True, False, True, False, True, False]
    assert first_of_language([]) == []


def test_empty_source() -> None:
    from reframe.models import SourceRef

    source = MediaSource(
        ref=SourceRef(path=Path("/media/empty.mkv"), fingerprint=SourceFingerprint(size=0, mtime=0))
    )
    draft = draft_tracks(source, JobTemplate())
    assert (draft.audio, draft.subtitles, draft.decisions) == ([], [], [])
