"""Metadata edit and remux (05 §C-13; decision 0034).

The parts of C-13 live where their kind of code lives:

- :func:`remux_job` (here): a drafted job turned into a remux-only job, the start of the
  "I only want to fix languages and flags" case (``Reframe.jobs.draft_remux``).
- the job type with its reason (``metadata_edit`` / ``remux`` / ``encode``) and why a job
  cannot be edited in place: :func:`reframe.command.job_type`,
  :func:`reframe.command.in_place_blockers`;
- the mkvpropedit arguments of the in-place edit and of the post-mux fix-up:
  :mod:`reframe.command.mkvpropedit` (pure; the plan of a ``metadata_edit`` job is one
  mkvpropedit step on the source, ``reframe.command.build_plan``);
- the re-probe check after every metadata change: :func:`reframe.queue.verify.check_output`;
  the BCP 47 languages it reads come from :mod:`reframe.probe.matroska` (no MediaInfo needed);
- the validation of in-place jobs: :mod:`reframe.validation.inplace`.
"""

from __future__ import annotations

from reframe import languages
from reframe.batch import track_metadata
from reframe.command.jobtype import is_matroska_source
from reframe.definitions import Definitions
from reframe.models.job import (
    AudioOutputTrack,
    ChapterSettings,
    FullRange,
    JobSettings,
    SubtitleOutputTrack,
    TagSettings,
    TrackMetadata,
)
from reframe.models.media import MediaSource, VideoStream

__all__ = ["remux_job", "source_video_metadata"]


def source_video_metadata(stream: VideoStream) -> TrackMetadata:
    """The video track's language, title and six flags exactly as the source has them (an
    in-place edit changes nothing the user does not change; a draft for encoding sets the
    default flag, ``reframe.jobs.video_metadata``)."""
    value = stream.language_ietf or stream.language
    d = stream.disposition
    return TrackMetadata(
        language=(languages.normalize(value) or value) if value else None,
        name=stream.title,
        default=d.default,
        forced=d.forced,
        commentary=d.comment,
        hearing_impaired=d.hearing_impaired,
        visual_impaired=d.visual_impaired,
        original=d.original,
    )


def remux_job(
    job: JobSettings,
    source: MediaSource,
    *,
    edit_in_place: bool = True,
    definitions: Definitions | None = None,
) -> JobSettings:
    """``job`` turned into a remux-only job (03 §Remux-only jobs): video passthrough, every
    source audio and subtitle track copied in source order with its metadata, and
    ``output.edit_in_place`` = ``edit_in_place``. Pure. The output path and naming of ``job``
    are kept, except what an in-place edit needs. A metadata change on the result then gives
    the job type ``metadata_edit`` (MKV source, edit in place) or ``remux``.

    What a remux keeps of the source, so that only the user's changes differ (decision 0034):
    the whole file (no range), the source's chapters as they are, the source's global tags
    (``passthru_metadata`` on, no tag overrides of the preset). For an in-place edit of an MKV
    the output is MKV and the output path is the source; the video track keeps its flags as
    they are. Otherwise the preset's container and output path stay (a remux writes a new
    file), and the video track keeps the draft's metadata. ``definitions`` is not needed
    today (kept for the contract).
    """
    del definitions
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
            result.video.metadata = source_video_metadata(source.video[0])
    return result
