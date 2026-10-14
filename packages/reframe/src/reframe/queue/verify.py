"""The output check after the encode (05 §C-11: "re-probe the output and check its layout").

The job says which streams the output must have: one video stream, one audio stream per
output audio track, one subtitle stream per output subtitle track that is not burned in. Each
must carry the language the command builder wrote (the container's form of the track's
language, or of the source track's: ISO 639-2/B for Matroska and WebM, /T for MP4; ``und``
when there is none). The re-probed file is compared with that; every difference is one line
of the failure message.

Only video, audio and subtitle streams are compared: attachments (fonts copied with ASS
subtitles) and data streams (MP4 writes the chapters as a ``bin_data`` text track) are not
tracks of the job. The language comparison uses the container's form on both sides, so
``ger`` and ``deu`` for German are the same language, and ``und`` equals no tag.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from reframe.command.metadata import container_language
from reframe.definitions import ContainerDef, Definitions
from reframe.models.job import ExternalSubtitle, JobSettings
from reframe.models.media import MediaSource

__all__ = ["ExpectedStream", "check_output", "expected_streams"]

_NAMES = {"video": "video", "audio": "audio", "subtitle": "subtitle"}


@dataclass(frozen=True, slots=True)
class ExpectedStream:
    kind: str
    """``video``, ``audio`` or ``subtitle``."""
    language: str
    """In the container's form (``jpn``, ``und``)."""


def _source_language(stream_language: str | None, ietf: str | None) -> str | None:
    return ietf or stream_language


def expected_streams(
    job: JobSettings, source: MediaSource, container: ContainerDef
) -> list[ExpectedStream]:
    """The streams the output must have, in output order per kind."""
    result: list[ExpectedStream] = []
    if source.video:
        video = source.video[0]
        language = job.video.metadata.language or _source_language(
            video.language, video.language_ietf
        )
        result.append(ExpectedStream("video", container_language(language, container)))
    audio_by_index = {stream.index: stream for stream in source.audio}
    for track in job.audio:
        stream = (
            audio_by_index.get(track.source_stream) if track.source_stream is not None else None
        )
        fallback = _source_language(stream.language, stream.language_ietf) if stream else None
        language = track.metadata.language or fallback
        result.append(ExpectedStream("audio", container_language(language, container)))
    subtitle_by_index = {stream.index: stream for stream in source.subtitles}
    for sub in job.subtitles:
        if sub.action == "burn":
            continue
        if isinstance(sub.source, ExternalSubtitle):
            fallback = sub.source.language
        else:
            found = subtitle_by_index.get(sub.source)
            fallback = _source_language(found.language, found.language_ietf) if found else None
        language = sub.metadata.language or fallback
        result.append(ExpectedStream("subtitle", container_language(language, container)))
    return result


def _plural(count: int, kind: str) -> str:
    return f"{count} {kind} track" + ("" if count == 1 else "s")


def check_output(
    job: JobSettings, source: MediaSource, output: MediaSource, definitions: Definitions
) -> list[str]:
    """What differs between the plan and the re-probed ``output`` (empty: it matches)."""
    container = definitions.containers.get(job.output.container)
    if container is None:
        return [f"unknown container {job.output.container!r}"]
    expected = expected_streams(job, source, container)
    found: dict[str, Sequence[str | None]] = {
        "video": [s.language for s in output.video],
        "audio": [s.language for s in output.audio],
        "subtitle": [s.language for s in output.subtitles],
    }
    problems: list[str] = []
    for kind in ("video", "audio", "subtitle"):
        wanted = [e.language for e in expected if e.kind == kind]
        have = [container_language(language, container) for language in found[kind]]
        if len(wanted) != len(have):
            problems.append(f"{_plural(len(wanted), _NAMES[kind])} expected, {len(have)} found")
            continue
        for number, (want, got) in enumerate(zip(wanted, have, strict=True), start=1):
            if want != got:
                problems.append(
                    f"{_NAMES[kind]} track {number}: language {want} expected, {got} found"
                )
    return problems
