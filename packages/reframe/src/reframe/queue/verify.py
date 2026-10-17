"""The output check after the encode (05 §C-11: "re-probe the output and check its layout"), and
the re-probe check after every metadata change (05 §C-13: the in-place edit and the post-mux
fix-up; decision 0034).

**Layout and languages** (every job). The job says which streams the output must have: one
video stream, one audio stream per output audio track, one subtitle stream per output
subtitle track that is not burned in. Each must carry the language the command builder wrote
(the container's form of the track's language, or of the source track's: ISO 639-2/B for
Matroska and WebM, /T for MP4; ``und`` when there is none). The re-probed file is compared
with that; every difference is one line of the failure message.

Only video, audio and subtitle streams are compared: attachments (fonts copied with ASS
subtitles) and data streams (MP4 writes the chapters as a ``bin_data`` text track) are not
tracks of the job. The language comparison uses the container's form on both sides, so
``ger`` and ``deu`` for German are the same language, and ``und`` equals no tag.

**Metadata** (a plan with an ``mkvpropedit`` step, or a ``metadata_edit`` job): also the BCP 47
language, the name and the flags of every track, and the container title an in-place edit
sets. The BCP 47 language read back is ``language_ietf`` (the probe reads Matroska's
``LanguageIETF`` itself, :mod:`reframe.probe.matroska`), else the ISO 639-2 code; both sides
are compared as canonical BCP 47 tags, so ``eng`` without ``LanguageIETF`` equals ``en``. A
post-mux fix-up writes ``LanguageIETF`` only for a language that ISO 639-2 cannot say
(``pt-BR``); the flags compared are those the muxer writes plus those the step writes. An
in-place edit is compared on all six flags.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from reframe import languages
from reframe.command.metadata import container_language, needs_ietf
from reframe.definitions import ContainerDef, Definitions
from reframe.definitions.models import TRACK_FLAGS, TrackFlag
from reframe.models.job import ExternalSubtitle, JobSettings, TrackMetadata
from reframe.models.media import AudioStream, MediaSource, SubtitleStream, VideoStream
from reframe.models.plan import EncodePlan

__all__ = [
    "ExpectedStream",
    "check_output",
    "expected_streams",
    "metadata_problems",
    "planned_title",
]

_NAMES = {"video": "video", "audio": "audio", "subtitle": "subtitle"}


@dataclass(frozen=True, slots=True)
class ExpectedStream:
    kind: str
    """``video``, ``audio`` or ``subtitle``."""
    language: str
    """In the container's form (``jpn``, ``und``)."""
    bcp47: str | None = None
    """The effective language as written (BCP 47 or ISO 639; ``None``: undetermined)."""
    title: str | None = None
    """The track name written (``None``: none)."""
    metadata: TrackMetadata | None = None
    """The job's metadata of the track (its flags)."""


def _source_language(stream_language: str | None, ietf: str | None) -> str | None:
    return ietf or stream_language


def _title(metadata: TrackMetadata, source_title: str | None) -> str | None:
    """As the command builder writes it: the job's name, else the source's; ``""`` = none."""
    name = metadata.name
    return (source_title if name is None else name) or None


def expected_streams(
    job: JobSettings, source: MediaSource, container: ContainerDef
) -> list[ExpectedStream]:
    """The streams the output must have, in output order per kind."""
    result: list[ExpectedStream] = []

    def add(kind: str, metadata: TrackMetadata, fallback: str | None, title: str | None) -> None:
        language = metadata.language or fallback
        result.append(
            ExpectedStream(
                kind,
                container_language(language, container),
                language,
                _title(metadata, title),
                metadata,
            )
        )

    if source.video:
        video = source.video[0]
        fallback = _source_language(video.language, video.language_ietf)
        add("video", job.video.metadata, fallback, video.title)
    audio_by_index = {stream.index: stream for stream in source.audio}
    for track in job.audio:
        stream = (
            audio_by_index.get(track.source_stream) if track.source_stream is not None else None
        )
        fallback = _source_language(stream.language, stream.language_ietf) if stream else None
        add("audio", track.metadata, fallback, stream.title if stream else None)
    subtitle_by_index = {stream.index: stream for stream in source.subtitles}
    for sub in job.subtitles:
        if sub.action == "burn":
            continue
        if isinstance(sub.source, ExternalSubtitle):
            fallback, title = sub.source.language, sub.source.name
        else:
            found = subtitle_by_index.get(sub.source)
            fallback = _source_language(found.language, found.language_ietf) if found else None
            title = found.title if found else None
        add("subtitle", sub.metadata, fallback, title)
    return result


def _plural(count: int, kind: str) -> str:
    return f"{count} {kind} track" + ("" if count == 1 else "s")


def _streams(
    output: MediaSource,
) -> dict[str, Sequence[VideoStream | AudioStream | SubtitleStream]]:
    return {"video": output.video, "audio": output.audio, "subtitle": output.subtitles}


def planned_title(plan: EncodePlan) -> tuple[bool, str | None]:
    """``(set, title)``: whether the plan's mkvpropedit steps set the segment title
    (``--edit info --set title=…`` or ``--delete title``), and to what."""
    found: tuple[bool, str | None] = (False, None)
    for step in plan.steps:
        if step.kind != "mkvpropedit":
            continue
        argv = [a for a in step.argv if isinstance(a, str)]
        in_info = False
        for i, arg in enumerate(argv):
            if arg == "--edit":
                in_info = i + 1 < len(argv) and argv[i + 1] == "info"
            elif in_info and i + 1 < len(argv):
                value = argv[i + 1]
                if arg == "--set" and value.startswith("title="):
                    found = (True, value.removeprefix("title=") or None)
                elif arg == "--delete" and value == "title":
                    found = (True, None)
    return found


def _bcp47(value: str | None) -> str:
    return languages.to_matroska_ietf(value)


def metadata_problems(
    job: JobSettings,
    source: MediaSource,
    output: MediaSource,
    container: ContainerDef,
    definitions: Definitions,
    *,
    in_place: bool,
    fixup: bool,
    title: tuple[bool, str | None] = (False, None),
) -> list[str]:
    """What differs in BCP 47 languages, names and flags (see the module doc). ``in_place``:
    the source was edited with mkvpropedit; ``fixup``: a post-mux mkvpropedit step ran;
    ``title``: :func:`planned_title`."""
    flags: tuple[TrackFlag, ...] = (
        TRACK_FLAGS
        if in_place
        else tuple(
            f
            for f in TRACK_FLAGS
            if f in container.flags or (fixup and f in container.mkvpropedit_flags)
        )
    )
    expected = expected_streams(job, source, container)
    found = _streams(output)
    problems: list[str] = []
    for kind in ("video", "audio", "subtitle"):
        wanted = [e for e in expected if e.kind == kind]
        have = found[kind]
        if len(wanted) != len(have):
            continue  # the layout check names it
        for number, (want, got) in enumerate(zip(wanted, have, strict=True), start=1):
            label = f"{_NAMES[kind]} track {number}"
            ietf_written = in_place or (fixup and needs_ietf(want.bcp47))
            tag = (
                _bcp47(want.bcp47)
                if ietf_written
                else _bcp47(languages.to_matroska_legacy(want.bcp47))
            )
            got_tag = _bcp47(got.language_ietf or got.language)
            if tag != got_tag:
                problems.append(f"{label}: BCP 47 language {tag} expected, {got_tag} found")
            if want.title != (got.title or None):
                problems.append(
                    f"{label}: name {_quoted(want.title)} expected, {_quoted(got.title)} found"
                )
            metadata = want.metadata or TrackMetadata()
            for flag in flags:
                expected_flag = bool(getattr(metadata, flag))
                disposition = definitions.track_flags[flag].disposition
                if bool(getattr(got.disposition, disposition)) != expected_flag:
                    state = "be set" if expected_flag else "not be set"
                    problems.append(f"{label}: the {flag.replace('_', ' ')} flag should {state}")
    wanted_set, wanted_title = title
    if wanted_set and (output.container.title or None) != wanted_title:
        problems.append(
            f"title {_quoted(wanted_title)} expected, {_quoted(output.container.title)} found"
        )
    return problems


def _quoted(value: str | None) -> str:
    return "none" if not value else repr(value)


def check_output(
    job: JobSettings,
    source: MediaSource,
    output: MediaSource,
    definitions: Definitions,
    *,
    plan: EncodePlan | None = None,
) -> list[str]:
    """What differs between the plan and the re-probed ``output`` (empty: it matches). With a
    ``plan`` that changes metadata with mkvpropedit, the metadata is checked too."""
    container = definitions.containers.get(job.output.container)
    if container is None:
        return [f"unknown container {job.output.container!r}"]
    expected = expected_streams(job, source, container)
    found = _streams(output)
    problems: list[str] = []
    for kind in ("video", "audio", "subtitle"):
        wanted = [e.language for e in expected if e.kind == kind]
        have = [container_language(stream.language, container) for stream in found[kind]]
        if len(wanted) != len(have):
            problems.append(f"{_plural(len(wanted), _NAMES[kind])} expected, {len(have)} found")
            continue
        for number, (want, got) in enumerate(zip(wanted, have, strict=True), start=1):
            if want != got:
                problems.append(
                    f"{_NAMES[kind]} track {number}: language {want} expected, {got} found"
                )
    if plan is not None:
        in_place = plan.job_type == "metadata_edit"
        fixup = not in_place and any(step.kind == "mkvpropedit" for step in plan.steps)
        if in_place or fixup:
            problems += metadata_problems(
                job, source, output, container, definitions, in_place=in_place, fixup=fixup,
                title=planned_title(plan),
            )  # fmt: skip
    return problems
