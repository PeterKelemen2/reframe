"""Metadata edits and remux-only jobs. The functions are pure: they build settings and read
nothing from disk."""

from __future__ import annotations

from reframe.batch import track_metadata
from reframe.command.jobtype import is_matroska_source
from reframe.models.job import (
    AudioOutputTrack,
    ChapterSettings,
    FullRange,
    JobSettings,
    SubtitleOutputTrack,
    TagSettings,
)
from reframe.models.media import MediaSource

__all__ = ["remux_job"]


def remux_job(
    job: JobSettings,
    source: MediaSource,
    *,
    edit_in_place: bool = True,
) -> JobSettings:
    """``job`` turned into a remux-only job: video passthrough, every source audio and subtitle
    track copied in source order with its metadata, and ``output.edit_in_place`` set to
    ``edit_in_place``. Pure. The output path and naming of ``job`` are kept, except what an
    in-place edit needs.

    What a remux keeps of the source, so that only the user's changes differ: the whole file
    (no range), the source's chapters as they are, the source's global tags (``passthru_metadata``
    on, no tag overrides of the preset). For an in-place edit of an MKV the output is MKV and the
    output path is the source; the video track keeps its flags as they are. Otherwise the
    preset's container and output path stay (a remux writes a new file), and the video track
    keeps the draft's metadata.
    """
    result = job.model_copy(deep=True)
    in_place = edit_in_place and is_matroska_source(source)
    previous = {t.source_stream: t for t in job.audio if t.source_stream is not None}
    audio: list[AudioOutputTrack] = []
    for stream in source.audio:
        before = previous.get(stream.index)
        audio.append(
            AudioOutputTrack(
                action="passthru",
                encoder=before.encoder if before is not None else "aac",
                source_stream=stream.index,
                metadata=track_metadata(stream),
            )
        )
    result.audio = audio
    result.subtitles = [
        SubtitleOutputTrack(source=stream.index, action="copy", metadata=track_metadata(stream))
        for stream in source.subtitles
    ]
    result.video.passthrough = True
    result.range = FullRange()
    result.chapters = ChapterSettings(enabled=True, names=None, generate_every=None)
    result.tags = TagSettings()
    result.output.passthru_metadata = True
    result.output.edit_in_place = edit_in_place
    if in_place:
        result.output.container = "mkv"
        result.output.path = source.ref.path
        if source.video:
            result.video.metadata = track_metadata(source.video[0])
    return result
