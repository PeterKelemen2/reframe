"""``reframe.metadata.remux_job``: a drafted job turned into a remux-only job."""

from __future__ import annotations

import json
from pathlib import Path

from reframe.batch import track_metadata, video_metadata
from reframe.batch.descriptors import describe_stream
from reframe.metadata import remux_job
from reframe.models import (
    AudioOutputTrack,
    ChapterSettings,
    FullRange,
    JobSettings,
    MediaSource,
    OutputSettings,
    SourceFingerprint,
    SourceRef,
    TagSettings,
    TimeRange,
    TrackMetadata,
)
from reframe.probe import parse_ffprobe

PROBES = Path(__file__).resolve().parents[4] / "testdata" / "probes" / "fixtures"


def recorded(name: str, path: Path) -> MediaSource:
    data = json.loads((PROBES / f"{name}.json").read_text(encoding="utf-8"))
    return parse_ffprobe(data, path, fingerprint=SourceFingerprint(size=0, mtime=0.0))


def drafted(source: MediaSource) -> JobSettings:
    return JobSettings(
        source=SourceRef(path=source.ref.path),
        output=OutputSettings(container="mp4", path=Path("/out/x.mp4"), passthru_metadata=False),
        range=TimeRange(start=1.0),
        audio=[
            AudioOutputTrack(source_stream=a.index, encoder="ac3", metadata=TrackMetadata())
            for a in source.audio[:1]
        ],
        chapters=ChapterSettings(names=["A"]),
        tags=TagSettings(title="{name}", genre="Drama"),
    )


def test_in_place_remux_of_an_mkv() -> None:
    source = recorded("multitrack.mkv", Path("/media/Show.S01E01.mkv"))
    job = remux_job(drafted(source), source)
    assert job.output.edit_in_place
    assert job.output.container == "mkv"
    assert job.output.path == source.ref.path
    assert job.output.passthru_metadata
    assert job.video.passthrough
    assert job.range == FullRange()
    assert job.chapters == ChapterSettings()
    assert job.tags == TagSettings()
    assert [(t.source_stream, t.action, t.encoder) for t in job.audio] == [
        (1, "passthru", "ac3"), (2, "passthru", "aac"), (3, "passthru", "aac"),
    ]  # fmt: skip
    first = job.audio[0].metadata
    assert (first.language, first.name, first.default) == ("ja", "Japanese 5.1", True)
    assert job.audio[2].metadata.commentary
    assert [(s.source, s.action) for s in job.subtitles] == [(4, "copy"), (5, "copy"), (6, "copy")]
    assert job.subtitles[1].metadata.hearing_impaired
    assert job.subtitles[2].metadata.forced
    assert job.video.metadata == track_metadata(source.video[0])


def test_remux_to_a_new_file_keeps_container_path_and_draft_video_metadata() -> None:
    source = recorded("multitrack.mkv", Path("/media/a.mkv"))
    draft = drafted(source)
    draft.video.metadata = TrackMetadata(default=True, name="Main")
    job = remux_job(draft, source, edit_in_place=False)
    assert not job.output.edit_in_place
    assert (job.output.container, job.output.path) == ("mp4", Path("/out/x.mp4"))
    assert job.video.metadata.name == "Main"


def test_a_source_that_is_not_mkv_keeps_its_new_path() -> None:
    source = recorded("multitrack.mkv", Path("/media/a.mkv"))
    source.container.format_name = "mov,mp4,m4a,3gp,3g2,mj2"
    job = remux_job(drafted(source), source)
    assert job.output.edit_in_place  # validation says why it cannot be done (inplace.*)
    assert job.output.path == Path("/out/x.mp4")


def test_video_track_metadata_is_exact() -> None:
    source = recorded("multitrack.mkv", Path("/media/a.mkv"))
    video = source.video[0]
    video.disposition.default = False
    video.language = "ger"
    video.title = "Main"
    meta = track_metadata(video)
    assert (meta.language, meta.name, meta.default) == ("de", "Main", False)
    video.language = None
    assert track_metadata(video).language is None


def test_a_broken_video_language_ietf_gives_way_to_a_valid_language() -> None:
    source = recorded("multitrack.mkv", Path("/media/a.mkv"))
    video = source.video[0]
    video.language_ietf = "zz"  # the right shape, not a language
    video.language = "ger"
    assert track_metadata(video).language == "de"
    assert video_metadata(video).language == "de"
    assert describe_stream(video, 0).language == "de"
