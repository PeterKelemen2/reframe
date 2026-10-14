"""The jobs service (C-15, ``Reframe.jobs``): a job from a source and a preset, its issues and
its plan.

- :meth:`JobService.draft` turns a source and a preset into a :class:`~reframe.models.JobDraft`:
  the preset's output options, dimensions, filters, video, chapter and tag settings; every
  audio track through the preset's codec rules and every subtitle copied (C-12
  ``draft_tracks``, decision 0018); the video track's metadata from the source with the
  default flag (decision 0024 item 5); and the output path: ``output`` as a manual name, else
  the naming template (C-16) with the preset's naming options (or Settings → Output) and the
  scaled size (C-5).
- :meth:`JobService.validate` runs C-8's ``validate``. When an encoder is still being checked
  (``encoder.checking``) it waits for encoder detection, but at most ``detection_wait``
  seconds (decision 0017), and validates again.
- :meth:`JobService.plan` gives the issues when there is an error, else C-7's plan.
- :meth:`JobService.name` names one path without probing it (``reframe name``), and
  :func:`find_media_files` lists the media files of files and folders (``reframe encode``).

Expected failures are values: a source that cannot be probed is a
:class:`~reframe.probe.ProbeError` (``draft``) or a ``source.probe_failed`` error
(``validate``, ``plan``); an unknown preset name is a ``preset.not_found`` error in the draft.
The service reads the file system through one :class:`~reframe.validation.FileSystemView`
(in worker threads), so tests can replace it.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

from reframe import languages
from reframe.batch import draft_tracks
from reframe.command import PlanError, build_plan
from reframe.definitions import Definitions, load_definitions
from reframe.dimensions import compute_geometry, source_geometry
from reframe.models.capabilities import CapabilitySnapshot
from reframe.models.defaults import TrackDecision
from reframe.models.draft import JobDraft
from reframe.models.issues import Severity, ValidationIssue
from reframe.models.job import (
    ChapterSettings,
    JobNaming,
    JobSettings,
    OutputSettings,
    TrackMetadata,
)
from reframe.models.media import MediaSource, VideoStream
from reframe.models.naming import NameResult, NamingOptions
from reframe.models.plan import EncodePlan
from reframe.models.preset import Preset
from reframe.models.settings import AppSettings
from reframe.models.tools import ToolSet
from reframe.naming import resolve_output_name
from reframe.probe import ProbeError
from reframe.probe.folder import list_media_files
from reframe.validation import FileSystemView, LocalFileSystem, next_free_path, validate

__all__ = [
    "DETECTION_WAIT",
    "WAIT_CODES",
    "Capabilities",
    "JobService",
    "MediaFiles",
    "PresetLookup",
    "SourceProber",
    "ToolDiscovery",
    "find_media_files",
    "has_errors",
    "is_partial_output",
    "job_from_preset",
    "output_size",
    "video_metadata",
]

#: Seconds that :meth:`JobService.validate` waits for a running encoder detection. C-4's
#: hardware tests have a 10 s timeout each, three at a time (decision 0008), so a detection
#: with every hardware encoder failing slowly ends well within this.
DETECTION_WAIT = 60.0

#: Issue codes that mean "not known until encoder detection has finished".
WAIT_CODES = frozenset({"encoder.checking", "filter.implementation_untested"})


# --------------------------------------------------------------------------- the services it uses


class SourceProber(Protocol):
    """What the jobs service needs from ``Reframe.sources``."""

    async def probe(self, path: str | os.PathLike[str]) -> MediaSource | ProbeError: ...


class PresetLookup(Protocol):
    """What the jobs service needs from ``Reframe.presets``."""

    def get(self, preset_id: str) -> Preset | None: ...

    def find(self, name_or_id: str) -> Preset | None: ...

    def default(self) -> Preset: ...


class ToolDiscovery(Protocol):
    """What the jobs service needs from ``Reframe.tools``."""

    async def status(self) -> ToolSet: ...


class Capabilities(Protocol):
    """What the jobs service needs from ``Reframe.capabilities``."""

    @property
    def snapshot(self) -> CapabilitySnapshot: ...

    async def wait(self) -> CapabilitySnapshot: ...


# --------------------------------------------------------------------------- media files


@dataclass(frozen=True)
class MediaFiles:
    """The media files of the paths given to ``reframe encode`` (see
    :func:`find_media_files`)."""

    files: list[Path] = field(default_factory=list)
    """Absolute paths, in argument order (a folder's files in natural order), each once."""
    missing: list[Path] = field(default_factory=list)
    """Arguments that do not exist."""
    empty: list[Path] = field(default_factory=list)
    """Folders without media files."""


def is_partial_output(path: Path) -> bool:
    """``Name.part.mkv``: the partial output of a running or failed job (03 §Queue), never a
    source."""
    return path.stem.endswith(".part")


def find_media_files(
    paths: Sequence[str | os.PathLike[str]], *, recursive: bool = False
) -> MediaFiles:
    """The files to encode for ``reframe encode FILE|DIR…`` (decision 0018).

    A file is taken as it is (ffprobe decides whether it is media). A folder gives its media
    files (C-3's extension list, hidden files left out, natural order), without the partial
    outputs of Reframe (``*.part.*``); ``recursive`` also searches its subfolders (hidden
    folders left out). A file named twice (also through a folder) is taken once.
    """
    files: list[Path] = []
    missing: list[Path] = []
    empty: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        key = os.path.normcase(str(path))
        if key not in seen:
            seen.add(key)
            files.append(path)

    for raw in paths:
        path = Path(os.path.abspath(raw))
        if path.is_dir():
            try:
                found = [
                    f
                    for f in list_media_files(path, recursive=recursive)
                    if not is_partial_output(f)
                ]
            except OSError:
                found = []
            if not found:
                empty.append(path)
            for file in found:
                add(file)
        elif path.exists():
            add(path)
        else:
            missing.append(path)
    return MediaFiles(files=files, missing=missing, empty=empty)


# --------------------------------------------------------------------------- helpers


def _issue(severity: Severity, code: str, path: str, message: str) -> ValidationIssue:
    return ValidationIssue(severity=severity, code=code, path=path, message=message)


def has_errors(issues: Sequence[ValidationIssue]) -> bool:
    return any(issue.severity is Severity.ERROR for issue in issues)


def _probe_issue(error: ProbeError) -> ValidationIssue:
    detail = f" ({error.detail})" if error.detail else ""
    return _issue(
        Severity.ERROR,
        "source.probe_failed",
        "source",
        f"{error.path.name} cannot be read: {error.message}{detail}",
    )


def video_metadata(stream: VideoStream) -> TrackMetadata:
    """The source video track's language, title and flags, with the default flag set
    (decision 0024 item 5: what mkvmerge writes; FFmpeg-written sources often have no
    default flag on their only video stream)."""
    value = stream.language_ietf or stream.language
    language = (languages.normalize(value) or value) if value else None
    d = stream.disposition
    return TrackMetadata(
        language=language,
        name=stream.title,
        default=True,
        forced=d.forced,
        commentary=d.comment,
        hearing_impaired=d.hearing_impaired,
        visual_impaired=d.visual_impaired,
        original=d.original,
    )


def output_size(job: JobSettings, source: MediaSource) -> tuple[int, int] | None:
    """C-5's scaled size of the encoded picture (the source size for video passthrough)."""
    if not source.video:
        return None
    stream = source.video[0]
    if job.video.passthrough:
        return (stream.width, stream.height)
    geometry = compute_geometry(source_geometry(stream), job.dimensions)
    return (geometry.scaled_width, geometry.scaled_height)


def job_from_preset(
    source: MediaSource, preset: Preset, *, definitions: Definitions | None = None
) -> tuple[JobSettings, list[TrackDecision], list[str]]:
    """The job settings of ``source`` encoded with ``preset`` (without the output path), the
    audio track decisions, and notes about how preset options were applied. Pure."""
    notes: list[str] = []
    tracks = draft_tracks(source, preset, definitions=definitions)
    video = preset.video.model_copy(deep=True)
    if source.video:
        video.metadata = video_metadata(source.video[0])
    names: list[str] | None = None
    if preset.chapter_name_policy == "generated" and source.chapters:
        names = [f"Chapter {i}" for i in range(1, len(source.chapters) + 1)]
        notes.append("Chapter names: generated (Chapter 1, Chapter 2, …), as the preset says.")
    job = JobSettings(
        source=source.ref.model_copy(deep=True),
        preset_id=preset.id,
        preset_name=preset.name,
        output=OutputSettings.model_validate(preset.output.model_dump()),
        dimensions=preset.dimensions.model_copy(deep=True),
        filters=preset.filters.model_copy(deep=True),
        video=video,
        audio=tracks.audio,
        subtitles=tracks.subtitles,
        chapters=ChapterSettings(
            enabled=preset.chapters.enabled,
            names=names,
            generate_every=preset.chapters.generate_every,
        ),
        tags=preset.tags.model_copy(deep=True),
    )
    return job, tracks.decisions, notes


# --------------------------------------------------------------------------- the service


class JobService:
    """``Reframe.jobs`` (C-15): draft, validate and plan jobs; name paths.

    :param sources: probes a source (``Reframe.sources``; probes are cached).
    :param presets: finds presets and the default one (``Reframe.presets``).
    :param tools: tool discovery (``Reframe.tools``).
    :param capabilities: encoder statuses (``Reframe.capabilities``).
    :param settings: the current settings (Settings → Output naming, collision policy).
    :param fs: every file-system read of naming and validation (default: the real one).
    :param detection_wait: seconds :meth:`validate` waits for a running encoder detection
        (default :data:`DETECTION_WAIT`, read when the service is made).
    :param clock: the time for the naming and tag date variables.
    """

    def __init__(
        self,
        *,
        sources: SourceProber,
        presets: PresetLookup,
        tools: ToolDiscovery,
        capabilities: Capabilities,
        settings: Callable[[], AppSettings],
        definitions: Definitions | None = None,
        fs: FileSystemView | None = None,
        detection_wait: float | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._sources = sources
        self._presets = presets
        self._tools = tools
        self._capabilities = capabilities
        self._settings = settings
        self._definitions = definitions
        self._fs: FileSystemView = fs if fs is not None else LocalFileSystem()
        self._detection_wait = DETECTION_WAIT if detection_wait is None else detection_wait
        self._clock = clock or (lambda: datetime.now().astimezone())

    @property
    def definitions(self) -> Definitions:
        if self._definitions is None:
            self._definitions = load_definitions()
        return self._definitions

    @property
    def detection_wait(self) -> float:
        return self._detection_wait

    # ------------------------------------------------------------------ draft

    async def draft(
        self,
        source: str | os.PathLike[str] | MediaSource,
        preset: Preset | str | None = None,
        *,
        output: Path | None = None,
    ) -> JobDraft | ProbeError:
        """The job for ``source`` with ``preset`` (``None``: the default preset; a string: a
        preset id or name), validated.

        ``output``: a manual output name (``reframe … -o OUT``). A path with an extension is
        used as it is (validation warns when the extension does not fit the container); one
        without gets the container's extension; an existing folder gets the template name
        inside it. ``None``: the naming template, in the output folder of the naming options.
        A template name that is the source file itself becomes ``Name (1).ext``.
        """
        media = source if isinstance(source, MediaSource) else await self._sources.probe(source)
        if isinstance(media, ProbeError):
            return media
        chosen, issues = self._resolve_preset(preset)
        naming = self._naming_options(chosen)
        job, decisions, name, notes = await asyncio.to_thread(
            self._compose, media, chosen, naming, output
        )
        issues = [*issues, *await self._validate(job, media, naming)]
        return JobDraft(
            job=job,
            decisions=decisions,
            naming=name,
            issues=issues,
            notes=notes,
        )

    def _resolve_preset(self, preset: Preset | str | None) -> tuple[Preset, list[ValidationIssue]]:
        if isinstance(preset, Preset):
            return preset, []
        if preset is None:
            return self._presets.default(), []
        found = self._presets.find(preset)
        if found is not None:
            return found, []
        fallback = self._presets.default()
        return fallback, [
            _issue(
                Severity.ERROR,
                "preset.not_found",
                "preset_id",
                f'There is no preset "{preset}". The job was drafted with the default preset '
                f'"{fallback.name}" so that its other issues can be shown.',
            )
        ]

    def _naming_options(self, preset: Preset | None) -> NamingOptions:
        if preset is not None and preset.naming is not None:
            return preset.naming
        return self._settings().output.naming

    def _compose(
        self,
        media: MediaSource,
        preset: Preset,
        naming: NamingOptions,
        output: Path | None,
    ) -> tuple[JobSettings, list[TrackDecision], NameResult, list[str]]:
        job, decisions, notes = job_from_preset(media, preset, definitions=self.definitions)
        file = Path(media.ref.path)
        size = output_size(job, media)
        folder: Path | None = None
        if output is not None:
            target = Path(os.path.abspath(output))
            if self._fs.is_dir(target):
                folder = target
                notes.append(f"The output folder is {target}; the naming template gives the name.")
            else:
                job.output.naming = JobNaming(mode="manual", manual_name=target.name)

        def name_of(job: JobSettings) -> NameResult:
            return resolve_output_name(
                file,
                naming,
                job=job,
                source=media,
                output_size=size,
                now=self._clock(),
                fs=self._fs,
                definitions=self.definitions,
            )

        name = name_of(job)
        path: Path | None
        if output is not None and folder is None:
            target = Path(os.path.abspath(output))
            path = target if target.suffix else target.with_name(f"{target.name}.{name.extension}")
        elif folder is not None:
            path = folder.joinpath(*name.relative_path.split("/"))
        else:
            path = name.path
            if path is not None and self._fs.same_file(path, file):
                free = next_free_path(path, self._fs)
                notes.append(
                    f"The name {path.name} is the source file itself: the output is saved as "
                    f"{free.name}."
                )
                path = free
        job.output.path = path
        return job, decisions, name, notes

    # ------------------------------------------------------------------ validate, plan

    async def validate(
        self, job: JobSettings, source: MediaSource | None = None
    ) -> list[ValidationIssue]:
        """Every issue of ``job`` (C-8). ``source`` ``None``: the job's source is probed (the
        probe cache makes this cheap).

        When an encoder or filter is still being checked, encoder detection is awaited for at
        most ``detection_wait`` seconds and the job is validated again; after that time the
        issues say what is still unknown (``encoder.checking`` and
        ``encoder.detection_timeout``, both info). Nothing waits longer.
        """
        media = await self._media(job, source)
        if not isinstance(media, MediaSource):
            return media
        return await self._validate(job, media, self._naming_options(self._job_preset(job)))

    async def plan(
        self, job: JobSettings, source: MediaSource | None = None
    ) -> EncodePlan | list[ValidationIssue]:
        """C-7's plan of ``job``; when it has errors, every issue instead (at least one is an
        ``error``)."""
        media = await self._media(job, source)
        if not isinstance(media, MediaSource):
            return media
        naming = self._naming_options(self._job_preset(job))
        issues = await self._validate(job, media, naming)
        if has_errors(issues):
            return issues
        tools = await self._tools.status()
        try:
            return build_plan(
                job,
                media,
                self._capabilities.snapshot,
                tools,
                definitions=self.definitions,
                naming=naming,
                now=self._clock(),
            )
        except PlanError as exc:  # validation and the builder disagree: a bug, shown as data
            return [
                *issues,
                _issue(
                    Severity.ERROR,
                    "plan.failed",
                    "",
                    f"The FFmpeg command cannot be built: {exc}. Please report this.",
                ),
            ]

    def _job_preset(self, job: JobSettings) -> Preset | None:
        return self._presets.get(job.preset_id) if job.preset_id else None

    async def _media(
        self, job: JobSettings, source: MediaSource | None
    ) -> MediaSource | list[ValidationIssue]:
        if source is not None:
            return source
        probed = await self._sources.probe(job.source.path)
        return [_probe_issue(probed)] if isinstance(probed, ProbeError) else probed

    async def _validate(
        self, job: JobSettings, media: MediaSource, naming: NamingOptions
    ) -> list[ValidationIssue]:
        tools = await self._tools.status()
        settings = self._settings()

        def check(caps: CapabilitySnapshot) -> list[ValidationIssue]:
            return validate(
                job,
                media,
                caps,
                tools,
                self._fs,
                settings=settings,
                definitions=self.definitions,
                naming=naming,
            )

        caps = self._capabilities.snapshot
        issues = await asyncio.to_thread(check, caps)
        if not any(issue.code in WAIT_CODES for issue in issues):
            return issues
        if not caps.detecting and caps.checked_at is not None:
            return issues  # nothing runs that could change it (hardware tests are off)
        try:
            async with asyncio.timeout(self._detection_wait):
                caps = await self._capabilities.wait()
        except TimeoutError:
            seconds = f"{self._detection_wait:g}"
            return [
                *issues,
                _issue(
                    Severity.INFO,
                    "encoder.detection_timeout",
                    "video.encoder",
                    f"Encoder detection did not finish within {seconds} s: the job was checked "
                    "with the encoder statuses known now.",
                ),
            ]
        return await asyncio.to_thread(check, caps)

    # ------------------------------------------------------------------ naming

    async def name(
        self,
        path: str | os.PathLike[str],
        *,
        preset: Preset | None = None,
        template: str | None = None,
        root: Path | None = None,
    ) -> NameResult:
        """The output name of ``path`` from the path alone (no probe: the media variables
        such as ``{resolution}`` are empty), with the naming options of ``preset`` (default:
        the default preset's, else Settings → Output) and its container. ``template``
        replaces the movie and the episode template."""
        chosen = preset if preset is not None else self._presets.default()
        options = self._naming_options(chosen)
        if template is not None:
            options = options.model_copy(
                update={"movie_template": template, "episode_template": template}
            )
        container = chosen.output.container
        now = self._clock()

        def resolve() -> NameResult:
            return resolve_output_name(
                Path(os.path.abspath(path)),
                options,
                container=container,
                root=root,
                now=now,
                fs=self._fs,
                definitions=self.definitions,
            )

        return await asyncio.to_thread(resolve)

    async def media_files(
        self, paths: Sequence[str | os.PathLike[str]], *, recursive: bool = False
    ) -> MediaFiles:
        """:func:`find_media_files` in a worker thread."""
        return await asyncio.to_thread(find_media_files, paths, recursive=recursive)
