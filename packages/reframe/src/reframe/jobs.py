"""The jobs service: a job from a source and a preset, its issues and its plan.

Expected failures are values. A source that cannot be probed is a :class:`~reframe.probe.ProbeError`
where the method returns one, else a ``source.probe_failed`` issue. The service reads the file
system through one :class:`~reframe.validation.FileSystemView`, in worker threads, so tests can
replace it.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

from reframe import metadata, preview
from reframe.batch import draft_tracks, output_size, video_metadata
from reframe.batch.resolve import resolve
from reframe.command import PlanError, build_plan, job_type_info, output_chapters
from reframe.command.metadata import rendered_tags
from reframe.definitions import Definitions, EncoderOption, load_definitions
from reframe.definitions import hdr_options as _hdr_options
from reframe.definitions import search_options as _search_options
from reframe.jsonpatch import escape_token
from reframe.mediatask import MediaTaskContext
from reframe.models.capabilities import CapabilitySnapshot
from reframe.models.defaults import TrackDecision, TrackDraft
from reframe.models.draft import JobDraft
from reframe.models.issues import AddOp, JsonPatchOp, Severity, ValidationIssue
from reframe.models.job import Container, JobNaming, JobSettings
from reframe.models.media import MediaSource
from reframe.models.naming import NameResult, NamingOptions
from reframe.models.output import JobTypeInfo, OutputChapters, RenderedTags
from reframe.models.plan import EncodePlan
from reframe.models.preset import Preset
from reframe.models.settings import AppSettings, LanguageSettings
from reframe.models.tasks import TaskInfo
from reframe.models.template import JobTemplate
from reframe.models.tools import ToolSet
from reframe.naming import resolve_output_name
from reframe.probe import ProbeError
from reframe.probe.folder import list_media_files
from reframe.queue import files as queue_files
from reframe.validation import FileSystemView, LocalFileSystem, next_free_path, validate
from reframe.validation.dryrun import dry_run as _dry_run

__all__ = [
    "DETECTION_WAIT",
    "WAIT_CODES",
    "Capabilities",
    "JobService",
    "MediaFiles",
    "OutputClaims",
    "PresetLookup",
    "SourceProber",
    "ToolDiscovery",
    "draft_from_preset",
    "file_key",
    "find_media_files",
    "has_errors",
    "is_partial_output",
    "job_from_preset",
    "output_size",
    "video_metadata",
]

#: Seconds that :meth:`JobService.validate` waits for a running encoder detection. A detection
#: in which every hardware test times out ends well within this.
DETECTION_WAIT = 60.0

#: Issue codes that mean "not known until encoder detection has finished".
WAIT_CODES = frozenset({"encoder.checking", "filter.implementation_untested"})


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


def file_key(path: str | os.PathLike[str]) -> str:
    """One key per file: two spellings of one file have the same key.

    The string form of the queue's :class:`~reframe.queue.files.FileKey`. Blocking (``stat``):
    call it in a worker thread for many paths. Never raises.
    """
    key = queue_files.file_key(path)
    if key.identity is not None:
        return f"file:{key.identity[0]}:{key.identity[1]}"
    return "path:" + key.path.casefold()


@dataclass(frozen=True)
class MediaFiles:
    """The media files of the given paths (see :func:`find_media_files`)."""

    files: list[Path] = field(default_factory=list)
    """Absolute paths, in argument order (a folder's files in natural order), each file once
    (in the spelling it was first given)."""
    missing: list[Path] = field(default_factory=list)
    """Arguments that do not exist."""
    empty: list[Path] = field(default_factory=list)
    """Folders without media files."""


def is_partial_output(path: Path) -> bool:
    """``Name.part.mkv``: the partial output of a running or failed job, never a source."""
    return path.stem.endswith(".part")


def find_media_files(
    paths: Sequence[str | os.PathLike[str]], *, recursive: bool = False
) -> MediaFiles:
    """The media files of ``paths``, with folders expanded.

    A file is taken as it is (ffprobe decides whether it is media). A folder gives its media
    files (the media extensions, hidden files left out, natural order), without the partial
    outputs of Reframe (``*.part.*``); ``recursive`` also searches its subfolders (hidden
    folders left out). A file named twice is taken once, in the spelling it was first given:
    also through a folder, a link, a linked folder or a hard link (:func:`file_key`).
    """
    files: list[Path] = []
    missing: list[Path] = []
    empty: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        key = file_key(path)
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


class OutputClaims:
    """The outputs of the jobs that one command queues.

    No job writes another file of the command (it would replace a source, perhaps before its
    own job reads it) or the output of an earlier job of the command (the earlier output would
    be lost, or the later one renamed at run time).

    Paths are compared as files (:func:`file_key`): an output named through a linked folder,
    a link or a hard link to a file of the command is that file. Messages name the files as
    they were given. Blocking (``stat``): call it in a worker thread.

    :param files: every file of the command, mapped to its label for messages.
    """

    def __init__(self, files: Mapping[Path, str]) -> None:
        self._files = {file_key(path): label for path, label in files.items()}
        self._outputs: dict[str, str] = {}

    def check(self, job: JobSettings, label: str) -> list[ValidationIssue]:
        """The errors of ``job``'s output (``label`` names the job in messages).

        A job without errors claims its output, so call this only for a job that is queued.
        """
        path = job.output.path
        if path is None or job.output.edit_in_place:
            return []
        key = file_key(path)
        source = file_key(job.source.path)
        if key != source and key in self._files:
            return [
                _issue(
                    Severity.ERROR,
                    "batch.output_is_source",
                    "output.path",
                    f"The output {path.name} is a source file of this command "
                    f"({self._files[key]}): it is never overwritten. Choose another name or "
                    "output folder for this file.",
                )
            ]
        earlier = self._outputs.get(key)
        if earlier is not None:
            return [
                _issue(
                    Severity.ERROR,
                    "batch.name_collision",
                    "output.path",
                    f"{path.name} is also the output of {earlier} in this command: this file is "
                    "not queued, so that it does not replace that output. Use a naming template "
                    "with the episode ({episode_code} or {episode}) or another name.",
                )
            ]
        self._outputs[key] = label
        return []


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


def job_from_preset(
    source: MediaSource,
    preset: Preset,
    *,
    definitions: Definitions | None = None,
    languages: LanguageSettings | None = None,
) -> tuple[JobSettings, list[TrackDecision], list[str]]:
    """The job settings of ``source`` encoded with ``preset`` (without the output path), the
    audio track decisions, and notes about how preset options were applied. ``languages``:
    the preferred languages of the track selection. Pure."""
    job, tracks, notes = draft_from_preset(
        source, preset, definitions=definitions, languages=languages
    )
    return job, tracks.decisions, notes


def draft_from_preset(
    source: MediaSource,
    preset: Preset,
    *,
    definitions: Definitions | None = None,
    languages: LanguageSettings | None = None,
    container_codecs: bool = True,
) -> tuple[JobSettings, TrackDraft, list[str]]:
    """:func:`job_from_preset` with the whole :class:`~reframe.models.TrackDraft`: the audio and
    subtitle decisions and the issues of the track stage. Pure.

    ``container_codecs=False`` leaves out the defaults lint's ``defaults.codec_not_in_container``,
    for a job that is validated later, which reports ``container.codec_unsupported`` instead.
    """
    resolution = resolve(
        preset,
        source,
        definitions=definitions,
        languages=languages,
        container_codecs=container_codecs,
    )
    assert resolution.job is not None  # resolve always makes a job
    draft = TrackDraft(
        audio=resolution.job.audio,
        subtitles=resolution.job.subtitles,
        decisions=resolution.decisions,
        subtitle_decisions=resolution.subtitle_decisions,
        issues=resolution.issues,
    )
    return resolution.job, draft, resolution.notes


class JobService:
    """Draft, validate and plan jobs; name paths.

    :param sources: probes a source; probes are cached.
    :param presets: finds presets and the default one.
    :param tools: tool discovery.
    :param capabilities: encoder statuses.
    :param settings: the current settings: output naming and the collision policy.
    :param fs: every file-system read of naming and validation (default: the real one).
    :param detection_wait: seconds :meth:`validate` waits for a running encoder detection
        (default :data:`DETECTION_WAIT`, read when the service is made).
    :param clock: the time for the naming and tag date variables.
    :param media: what the preview-clip tasks need from the facade; set by
        :class:`~reframe.service.Reframe`.
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
        media: MediaTaskContext | None = None,
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
        self._media_context = media

    @property
    def definitions(self) -> Definitions:
        if self._definitions is None:
            self._definitions = load_definitions()
        return self._definitions

    @property
    def detection_wait(self) -> float:
        return self._detection_wait

    async def draft(
        self,
        source: str | os.PathLike[str] | MediaSource,
        preset: Preset | str | None = None,
        *,
        output: Path | None = None,
    ) -> JobDraft | ProbeError:
        """The job for ``source`` with ``preset`` (``None``: the default preset; a string: a
        preset id or name), validated.

        ``output``: a manual output name. A path with an extension is used as it is (validation
        warns when the extension does not fit the container); one without gets the container's
        extension; an existing folder gets the template name inside it. ``None``: the naming
        template, in the output folder of the naming options. A template name that is the
        source file itself gets the next free name.
        """
        media = source if isinstance(source, MediaSource) else await self._sources.probe(source)
        if isinstance(media, ProbeError):
            return media
        chosen, issues = self._resolve_preset(preset)
        naming = self._naming_options(chosen)
        job, tracks, name, notes = await asyncio.to_thread(
            self._compose, media, chosen, naming, output
        )
        # Errors of the track stage keep the draft out of the queue. The inexact track-rule
        # matches (``batch.*``) are shown with it; the defaults lint's warnings are in explain().
        track_issues = [
            i for i in tracks.issues if i.severity is Severity.ERROR or i.code.startswith("batch.")
        ]
        issues = [*issues, *track_issues, *await self._validate(job, media, naming)]
        return JobDraft(
            job=job,
            decisions=tracks.decisions,
            subtitle_decisions=tracks.subtitle_decisions,
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
    ) -> tuple[JobSettings, TrackDraft, NameResult, list[str]]:
        # Validation reports a codec the container cannot hold, so the defaults lint does not
        # say it again: one issue per problem.
        job, tracks, notes = draft_from_preset(
            media,
            preset,
            definitions=self.definitions,
            languages=self._settings().languages,
            container_codecs=False,
        )
        job, name, more = self._name(job, media, naming, output)
        return job, tracks, name, [*notes, *more]

    def _name(
        self,
        job: JobSettings,
        media: MediaSource,
        naming: NamingOptions,
        output: Path | None,
    ) -> tuple[JobSettings, NameResult, list[str]]:
        """Set ``job``'s output path (it is changed): ``output``, else the naming template;
        the name, and notes on what naming changed."""
        notes: list[str] = []
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
        return job, name, notes

    async def name_job(
        self,
        job: JobSettings,
        source: MediaSource,
        *,
        naming: NamingOptions | None = None,
        output: Path | None = None,
    ) -> tuple[JobSettings, NameResult, list[str]]:
        """Name ``job`` as :meth:`draft` names a draft: a copy with the output path, the name
        and notes. ``naming``: the naming options (``None``: the job's preset's, else the
        settings' output naming); ``output``: a manual name or folder."""
        options = naming if naming is not None else self._naming_options(self._job_preset(job))
        return await asyncio.to_thread(
            self._name, job.model_copy(deep=True), source, options, output
        )

    async def validate(
        self,
        job: JobSettings,
        source: MediaSource | None = None,
        *,
        naming: NamingOptions | None = None,
    ) -> list[ValidationIssue]:
        """Every issue of ``job``. ``source`` ``None``: the job's source is probed. ``naming``:
        the naming options the job was named with (``None``: its preset's, else the settings').

        When an encoder or filter is still being checked, encoder detection is awaited for at
        most ``detection_wait`` seconds and the job is validated again; after that time the
        issues say what is still unknown. Nothing waits longer.
        """
        media = await self._media(job, source)
        if not isinstance(media, MediaSource):
            return media
        options = naming if naming is not None else self._naming_options(self._job_preset(job))
        return await self._validate(job, media, options)

    async def plan(
        self, job: JobSettings, source: MediaSource | None = None, *, dry_run: bool = False
    ) -> EncodePlan | list[ValidationIssue]:
        """The plan of ``job``, or when it has errors, the issues instead (at least one is an
        ``error``). ``dry_run``: when validation finds no error, also encode one frame
        (:meth:`dry_run`) and return its errors (custom parameters FFmpeg refuses). A plan
        carries no issues, so the dry run's warnings are not returned with it; a caller that
        shows them calls :meth:`dry_run` itself.
        """
        media = await self._media(job, source)
        if not isinstance(media, MediaSource):
            return media
        naming = self._naming_options(self._job_preset(job))
        issues = await self._validate(job, media, naming)
        if not has_errors(issues) and dry_run:
            issues = [*issues, *await self.dry_run(job, media)]
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

    async def dry_run(
        self, job: JobSettings, source: MediaSource | None = None
    ) -> list[ValidationIssue]:
        """Encode one frame with the job's video settings and give what FFmpeg refuses as
        ``error`` issues. Validate first: a job with errors gives wrong dry-run errors."""
        media = await self._media(job, source)
        if not isinstance(media, MediaSource):
            return media
        tools = await self._tools.status()
        return await _dry_run(
            job, media, self._capabilities.snapshot, tools, definitions=self.definitions
        )

    async def explain(
        self,
        source: str | os.PathLike[str] | MediaSource,
        template: JobTemplate | str | None = None,
        *,
        container: Container | None = None,
    ) -> TrackDraft | ProbeError:
        """What the audio and subtitle defaults of ``template`` (a template, a preset id or
        name; ``None``: the default preset) do with ``source``: the drafted tracks and one
        decision per source track, with the reason. ``container`` replaces the template's
        container. An unknown preset name is a ``preset.not_found`` issue in the result.
        """
        media = source if isinstance(source, MediaSource) else await self._sources.probe(source)
        if isinstance(media, ProbeError):
            return media
        issues: list[ValidationIssue] = []
        chosen: JobTemplate
        if isinstance(template, JobTemplate):
            chosen = template
        else:
            chosen, issues = self._resolve_preset(template)
        if container is not None and container != chosen.output.container:
            chosen = chosen.model_copy(deep=True)
            chosen.output.container = container
        languages = self._settings().languages
        draft = await asyncio.to_thread(
            draft_tracks, media, chosen, definitions=self.definitions, languages=languages
        )
        if issues:
            draft.issues = [*issues, *draft.issues]
        return draft

    async def draft_remux(
        self,
        source: str | os.PathLike[str] | MediaSource,
        preset: Preset | str | None = None,
        *,
        edit_in_place: bool = True,
    ) -> JobDraft | ProbeError:
        """A remux-only job of ``source``: :meth:`draft` with ``preset``, then video passthrough
        and every track copied in source order with its metadata (``reframe.metadata.remux_job``),
        validated again. Change only metadata on the result and an MKV with ``edit_in_place``
        becomes a ``metadata_edit`` job.
        """
        draft = await self.draft(source, preset)
        if isinstance(draft, ProbeError):
            return draft
        media = source if isinstance(source, MediaSource) else await self._sources.probe(source)
        if isinstance(media, ProbeError):
            return media
        job = metadata.remux_job(
            draft.job, media, edit_in_place=edit_in_place, definitions=self.definitions
        )
        naming = self._naming_options(self._job_preset(job))
        issues = await self._validate(job, media, naming)
        keep = [issue for issue in draft.issues if issue.code == "preset.not_found"]
        return draft.model_copy(
            update={
                "job": job,
                "decisions": [],
                "subtitle_decisions": [],
                "issues": [*keep, *issues],
            }
        )

    def search_options(self, encoder_id: str, query: str) -> list[EncoderOption]:
        """The advanced options of ``encoder_id`` that match ``query`` in their label, CLI
        name or help text; empty for an unknown encoder."""
        encoder = self.definitions.video_encoders.get(encoder_id)
        if encoder is None:
            return []
        return _search_options(encoder.options, query)

    def hdr_metadata(self, job: JobSettings, source: MediaSource) -> list[JsonPatchOp]:
        """**Copy HDR metadata from source**: a JSON patch on ``job`` that sets the encoder's HDR
        options (``/video/advanced/<key>``) from the source's HDR10 metadata. Empty when the
        source has none or the encoder has no such options.
        """
        encoder = self.definitions.video_encoders.get(job.video.encoder)
        if encoder is None or not source.video:
            return []
        values = _hdr_options(encoder, source.video[0])
        return [
            AddOp(path=f"/video/advanced/{escape_token(key)}", value=value)
            for key, value in values.items()
        ]

    def job_type(
        self, job: JobSettings, source: MediaSource, *, write_blocker: str | None = None
    ) -> JobTypeInfo:
        """The job type of ``job`` and why, and why it could not edit its source in place.
        ``write_blocker``: why the caller may not write the source, as one more blocker."""
        return job_type_info(job, source, definitions=self.definitions, write_blocker=write_blocker)

    def output_chapters(self, job: JobSettings, source: MediaSource) -> OutputChapters:
        """The chapters the output of ``job`` gets, in output time, as the plan writes them."""
        return output_chapters(job, source, definitions=self.definitions)

    def rendered_tags(self, job: JobSettings, source: MediaSource) -> RenderedTags:
        """The tags of ``job`` as the plan writes them (the date and time variables as of now,
        the naming options of its preset, else the settings'), the source's values, and the
        tags' template errors."""
        return rendered_tags(
            job, source, options=self._naming_options(self._job_preset(job)),
            output_size=output_size(job, source), now=self._clock(), definitions=self.definitions,
        )  # fmt: skip

    def preview_clip(self, job: JobSettings, *, start: float, seconds: float) -> TaskInfo:
        """Encode ``seconds`` from ``start`` with the job's full settings into the preview cache,
        as a task whose result is a :class:`~reframe.models.PreviewClip`. Returns at once.
        """
        return preview.start_preview_clip(self._media_tasks(), job, start=start, seconds=seconds)

    async def preview_clip_path(self, clip_id: str) -> Path | None:
        """The cached clip of a :class:`~reframe.models.PreviewClip` id, else ``None``."""
        return await asyncio.to_thread(preview.clip_path, self._media_tasks(), clip_id)

    def _media_tasks(self) -> MediaTaskContext:
        if self._media_context is None:
            raise RuntimeError("JobService has no media task context (the facade sets it)")
        return self._media_context

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
        the default preset's, else the settings' output naming) and its container. ``template``
        replaces the movie and the episode template.
        """
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
