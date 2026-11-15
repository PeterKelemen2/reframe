"""Job type detection: ``metadata_edit``, ``remux`` or ``encode``, each with the reason.

A job is a metadata edit only when *Edit in place* is chosen and :func:`in_place_blockers`
finds nothing.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import PurePath

from reframe.definitions import ContainerDef, Definitions, load_definitions
from reframe.models import (
    AudioStream,
    ExternalSubtitle,
    FullRange,
    JobSettings,
    JobType,
    JobTypeInfo,
    MediaSource,
    TagSettings,
)

__all__ = ["in_place_blockers", "is_matroska_source", "job_type", "job_type_info"]


def _track_label(number: int, stream: AudioStream | None) -> str:
    if stream is None:
        return f"audio track {number}"
    what = stream.display_codec or (stream.codec or "").upper() or "audio"
    return f"audio track {number} ({what})"


def is_matroska_source(source: MediaSource) -> bool:
    """The source is a Matroska file that is not WebM (``format_name`` ``matroska,webm`` and
    not a ``.webm`` name)."""
    formats = (source.container.format_name or "").split(",")
    suffix = PurePath(source.ref.path).suffix.lower()
    return "matroska" in formats and suffix != ".webm"


#: The tags an in-place edit cannot set (the title can be set).
OTHER_TAGS = ("actors", "director", "release_date", "comment", "genre", "description", "plot")


def _tags_besides_title(tags: TagSettings) -> list[str]:
    return [name for name in OTHER_TAGS if getattr(tags, name) is not None]


def _audio_blockers(
    job: JobSettings, source: MediaSource, container: ContainerDef | None
) -> list[str]:
    streams = {a.index: a for a in source.audio}
    if [t.source_stream for t in job.audio] != [a.index for a in source.audio]:
        return ["the audio tracks are not the source's audio tracks in source order"]
    for number, track in enumerate(job.audio, start=1):
        stream = streams.get(track.source_stream) if track.source_stream is not None else None
        name = _track_label(number, stream)
        if track.action != "passthru":
            return [f"{name} is encoded"]
        codec = stream.codec if stream is not None else None
        if container is not None and (codec is None or not container.audio.can_copy(codec)):
            return [f"{name} cannot be copied into {container.label}"]
    return []


def _subtitle_blockers(
    job: JobSettings, source: MediaSource, container: ContainerDef | None
) -> list[str]:
    if any(isinstance(sub.source, ExternalSubtitle) for sub in job.subtitles):
        return ["a subtitle file is added"]
    if [sub.source for sub in job.subtitles] != [s.index for s in source.subtitles]:
        return ["the subtitle tracks are not the source's subtitle tracks in source order"]
    streams = {s.index: s for s in source.subtitles}
    for number, sub in enumerate(job.subtitles, start=1):
        if sub.action != "copy":
            verb = "burned in" if sub.action == "burn" else "converted"
            return [f"subtitle track {number} is {verb}"]
        stream = streams.get(sub.source) if isinstance(sub.source, int) else None
        codec = stream.codec if stream is not None else None
        if container is not None and (codec is None or not container.subtitles.can_copy(codec)):
            return [f"subtitle track {number} cannot be copied into {container.label}"]
    return []


def in_place_blockers(
    job: JobSettings, source: MediaSource, *, definitions: Definitions | None = None
) -> list[str]:
    """Why ``job`` cannot edit its source in place (empty: it can), each as a sentence
    fragment (``"the video is encoded"``). ``output.edit_in_place`` itself is not checked."""
    defs = definitions if definitions is not None else load_definitions()
    container = defs.containers.get(job.output.container)
    found: list[str] = []
    if not is_matroska_source(source):
        found.append("the source is not an MKV file")
    if job.output.container != "mkv":
        label = container.label if container is not None else job.output.container
        found.append(f"the output container is {label}, not MKV")
    if not job.video.passthrough:
        found.append("the video is encoded")
    elif len(source.video) > 1:
        found.append(f"only the first of the source's {len(source.video)} video tracks is kept")
    if not isinstance(job.range, FullRange):
        found.append("only a part of the source is kept (a range is set)")
    found += _audio_blockers(job, source, container)
    found += _subtitle_blockers(job, source, container)
    chapters = job.chapters
    if source.chapters and not chapters.enabled:
        found.append("the chapters are removed")
    elif source.chapters and chapters.names is not None:
        found.append("the chapters are renamed")
    elif not source.chapters and chapters.enabled and chapters.generate_every is not None:
        found.append("chapters are generated")
    if not job.output.passthru_metadata:
        found.append("the source's tags are not kept")
    other_tags = _tags_besides_title(job.tags)
    if other_tags:
        found.append("tags other than the title are set (" + ", ".join(other_tags) + ")")
    return found


def _copy_type(job: JobSettings, source: MediaSource, defs: Definitions) -> tuple[JobType, str]:
    """``encode`` or ``remux``, with the reason."""
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


def _typed(
    job: JobSettings, source: MediaSource, defs: Definitions, blockers: Sequence[str]
) -> tuple[JobType, str]:
    if job.output.edit_in_place:
        if not blockers:
            return "metadata_edit", (
                "Metadata edit: only the track metadata changes, so Reframe edits "
                f"{PurePath(source.ref.path).name} in place, in seconds."
            )
        kind, reason = _copy_type(job, source, defs)
        return kind, f"{reason} It cannot be edited in place: {blockers[0]}."
    return _copy_type(job, source, defs)


def job_type(
    job: JobSettings, source: MediaSource, *, definitions: Definitions | None = None
) -> tuple[JobType, str]:
    """The job type and why, in one sentence (two when *Edit in place* is chosen but not
    possible: the second says why)."""
    defs = definitions if definitions is not None else load_definitions()
    blockers = in_place_blockers(job, source, definitions=defs) if job.output.edit_in_place else []
    return _typed(job, source, defs, blockers)


def job_type_info(
    job: JobSettings,
    source: MediaSource,
    *,
    definitions: Definitions | None = None,
    write_blocker: str | None = None,
) -> JobTypeInfo:
    """:func:`job_type` with the in-place blockers, for any job. ``write_blocker``: why the
    caller may not write the source (a server's folders); it comes after a source that is not
    MKV, before the rest, and counts as a blocker of the job type too."""
    defs = definitions if definitions is not None else load_definitions()
    blockers = in_place_blockers(job, source, definitions=defs)
    if write_blocker is not None:
        at = 0 if is_matroska_source(source) else 1
        blockers.insert(at, write_blocker)
    kind, reason = _typed(job, source, defs, blockers)
    return JobTypeInfo(job_type=kind, reason=reason, in_place_blockers=blockers)
