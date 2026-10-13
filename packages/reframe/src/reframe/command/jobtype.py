"""Job type detection (03 §Remux-only jobs; 05 §C-13 bullet 1, built for M2's two types).

- **remux**: video passthrough, and every output audio track is copied (passthru that the
  container can hold) and every output subtitle track has the action ``copy`` (a text track
  that the container cannot hold is still converted to its text format: MP4 ``mov_text``).
  Nothing is decoded but those subtitles, so it runs at disk speed (FFmpeg ``-c copy``).
- **encode**: anything else.

``metadata_edit`` (mkvpropedit in place) is C-13 (M6) and is never returned here.
"""

from __future__ import annotations

from reframe.definitions import Definitions, load_definitions
from reframe.models import AudioStream, JobSettings, JobType, MediaSource

__all__ = ["job_type"]


def _track_label(number: int, stream: AudioStream | None) -> str:
    if stream is None:
        return f"audio track {number}"
    what = stream.display_codec or (stream.codec or "").upper() or "audio"
    return f"audio track {number} ({what})"


def job_type(
    job: JobSettings, source: MediaSource, *, definitions: Definitions | None = None
) -> tuple[JobType, str]:
    """The job type and why, in one sentence for the Summary tab."""
    defs = definitions if definitions is not None else load_definitions()
    if not job.video.passthrough:
        encoder = defs.video_encoders.get(job.video.encoder)
        label = encoder.label if encoder is not None else job.video.encoder
        return "encode", f"Encode: the video is encoded with {label}."
    container = defs.containers.get(job.output.container)
    audio = {a.index: a for a in source.audio}
    for number, track in enumerate(job.audio, start=1):
        stream = audio.get(track.source_stream) if track.source_stream is not None else None
        name = _track_label(number, stream)
        if track.action != "passthru":
            return "encode", f"Encode: video passthrough, but {name} is encoded."
        codec = stream.codec if stream is not None else None
        if container is not None and (codec is None or not container.audio.can_copy(codec)):
            return "encode", (
                f"Encode: video passthrough, but {name} cannot be copied into "
                f"{container.label}, so it is encoded."
            )
    for number, sub in enumerate(job.subtitles, start=1):
        if sub.action != "copy":
            verb = "burned in" if sub.action == "burn" else "converted"
            return "encode", f"Encode: video passthrough, but subtitle track {number} is {verb}."
    return "remux", (
        "Remux: the video and every audio and subtitle track are copied without re-encoding."
    )
