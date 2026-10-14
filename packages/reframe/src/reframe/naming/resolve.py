"""The output name of one source file (C-16): name source, template, safe file name, path."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from reframe.definitions import Definitions, load_definitions
from reframe.jsonpatch import format_pointer
from reframe.models.issues import Fix, RemoveOp, Severity, ValidationIssue
from reframe.models.job import Container, JobNaming, JobSettings
from reframe.models.media import MediaSource
from reframe.models.naming import NameResult, NamingOptions, ParsedName, TemplateKind
from reframe.naming.context import NameContext, build_values
from reframe.naming.fs import NamingFs, RealNamingFs
from reframe.naming.sanitize import (
    UNDECODABLE_NOTE,
    UNDECODABLE_REPLACEMENT,
    Piece,
    replace_undecodable,
    sanitize_segments,
)
from reframe.naming.source import choose_source, split_extension
from reframe.naming.template import (
    check_template,
    format_value,
    parse_template,
    render,
)
from reframe.naming.variables import VARIABLE_KINDS

__all__ = ["OVERRIDE_FIELDS", "apply_overrides", "output_extension", "resolve_output_name"]

_TEXT_OVERRIDES = (
    "name",
    "main_title",
    "sub_title",
    "episode_code",
    "edition",
    "source_type",
    "release_group",
)
_NUMBER_OVERRIDES = ("season", "episode", "year")
#: The parsed-name fields a job can override (``JobNaming.field_overrides``).
OVERRIDE_FIELDS = _TEXT_OVERRIDES + _NUMBER_OVERRIDES
_OVERRIDES_PATH = "output.naming.field_overrides"
#: Most digits of a number override. ``str.isdigit`` is not the check: it accepts ``²``,
#: which ``int`` refuses, and Arabic-Indic or full-width digits.
MAX_NUMBER_DIGITS = 9
_NUMBER = re.compile(rf"[0-9]{{1,{MAX_NUMBER_DIGITS}}}")
#: Most characters of an override value quoted in an issue message.
_SHOWN_CHARS = 40


def _shown(value: str) -> str:
    return value if len(value) <= _SHOWN_CHARS else value[: _SHOWN_CHARS - 1] + "…"


def output_extension(
    container: Container,
    options: NamingOptions,
    job: JobSettings | None = None,
    source: MediaSource | None = None,
    *,
    definitions: Definitions | None = None,
) -> str:
    """The extension (no dot). Other containers: the first extension of the container's
    definition (C-6). MP4: ``mp4``, ``m4v``, or *Auto* (HandBrake): ``m4v`` with AC-3 audio
    (encoded or passed through), chapter markers, or 3GPP (``mov_text``) subtitles."""
    if container != "mp4":
        defs = definitions if definitions is not None else load_definitions()
        return defs.containers[container].extensions[0].lstrip(".")
    if options.mp4_extension == "m4v":
        return "m4v"
    if options.mp4_extension == "mp4" or job is None:
        return "mp4"
    audio = {a.index: a for a in source.audio} if source else {}
    for track in job.audio:
        src = audio.get(track.source_stream) if track.source_stream is not None else None
        if track.action == "encode" and track.encoder == "ac3":
            return "m4v"
        if track.action == "passthru" and src is not None and src.codec == "ac3":
            return "m4v"
    has_chapters = job.chapters.generate_every is not None or bool(source and source.chapters)
    if job.chapters.enabled and has_chapters:
        return "m4v"
    subtitles = {s.index: s for s in source.subtitles} if source else {}
    for sub in job.subtitles:
        if sub.action == "convert" and sub.convert_to == "mov_text":
            return "m4v"
        if sub.action == "copy" and isinstance(sub.source, int):
            stream = subtitles.get(sub.source)
            if stream is not None and stream.codec == "mov_text":
                return "m4v"
    return "mp4"


def _replace_part(text: str | None, old: str | None, new: str | None) -> str | None:
    if text is None or not old or old not in text:
        return text
    return text.replace(old, new or "", 1)


def apply_overrides(
    fields: ParsedName, overrides: dict[str, str]
) -> tuple[ParsedName, list[ValidationIssue], list[str]]:
    """Apply the per-file overrides of the naming editor. An edited ``name``, ``sub_title``
    or ``episode_code`` is also changed inside ``main_title`` (unless that is edited too).
    Unknown names and bad numbers are warnings."""
    if not overrides:
        return fields, [], []
    fields = fields.model_copy(deep=True)
    issues: list[ValidationIssue] = []
    applied: list[str] = []
    for key, value in overrides.items():
        path = f"{_OVERRIDES_PATH}.{key}"
        pointer = format_pointer(["output", "naming", "field_overrides", key])
        remove = Fix(label=f"Remove the override of {key}", patch=[RemoveOp(path=pointer)])
        if key in _TEXT_OVERRIDES:
            old = getattr(fields, key)
            new = value or None
            setattr(fields, key, new)
            if key != "main_title" and "main_title" not in overrides:
                fields.main_title = _replace_part(fields.main_title, old, new)
            applied.append(key)
        elif key in _NUMBER_OVERRIDES:
            number = value.strip()
            if number and not _NUMBER.fullmatch(number):
                issues.append(
                    ValidationIssue(
                        severity=Severity.WARNING,
                        code="naming.bad_override",
                        path=path,
                        message=(
                            f"The {key} override '{_shown(value)}' is not a number of 1 to "
                            f"{MAX_NUMBER_DIGITS} digits (0-9); it is ignored."
                        ),
                        fixes=[remove],
                    )
                )
                continue
            parsed = int(number) if number else None
            setattr(fields, key, parsed)
            if key == "episode":
                fields.episodes = [parsed] if parsed is not None else []
            applied.append(key)
        else:
            issues.append(
                ValidationIssue(
                    severity=Severity.WARNING,
                    code="naming.unknown_override",
                    path=path,
                    message=f"'{key}' is not a name field that can be overridden; it is ignored.",
                    fixes=[remove],
                )
            )
    if fields.season is not None or fields.episode is not None:
        fields.kind = "episode"
    notes = [f"Edited for this file: {', '.join(applied)}."] if applied else []
    return fields, issues, notes


def resolve_output_name(
    file: Path,
    options: NamingOptions,
    *,
    job: JobSettings | None = None,
    source: MediaSource | None = None,
    output_size: tuple[int, int] | None = None,
    container: Container | None = None,
    root: Path | None = None,
    now: datetime | None = None,
    title_index: int = 1,
    fs: NamingFs | None = None,
    definitions: Definitions | None = None,
) -> NameResult:
    """The output name of ``file`` (03 §Output naming).

    Works from the path alone: ``job`` and ``source`` are optional, and variables that need
    missing data are empty. ``options`` are the effective naming options (the preset's, else
    Settings → Output); the job's own template, name source, manual name and per-file
    overrides (``job.output.naming``) win over them. ``output_size`` is the scaled size
    (C-5) for ``{width}``, ``{height}`` and ``{resolution}``. ``container`` is used when
    there is no job (default ``mkv``). ``root`` is the opened folder or media root: generic
    folder skipping never goes above it. ``fs`` replaces the file-system reads (folder
    listing, file times) in tests. A bad template gives issues, never an exception.
    """
    fs = fs if fs is not None else RealNamingFs()
    definitions = definitions if definitions is not None else load_definitions()
    now = now if now is not None else datetime.now().astimezone()
    naming: JobNaming | None = job.output.naming if job is not None else None

    mode = options.name_source
    forced_by = "the naming options"
    if naming is not None and naming.name_source is not None:
        mode, forced_by = naming.name_source, "this job"
    choice = choose_source(file, mode, root=root, fs=fs, forced_by=forced_by)
    notes = list(choice.notes)
    fields, issues, override_notes = apply_overrides(
        choice.fields, naming.field_overrides if naming is not None else {}
    )
    notes.extend(override_notes)

    target: Container = job.output.container if job is not None else (container or "mkv")
    extension = output_extension(target, options, job, source, definitions=definitions)
    file_stem, _ = split_extension(file.name)
    values = build_values(
        NameContext(
            fields=fields,
            source_text=choice.text,
            source_separator=choice.separator,
            file=file,
            file_stem=file_stem,
            options=options,
            container=target,
            now=now,
            fs=fs,
            definitions=definitions,
            job=job,
            source=source,
            output_size=output_size,
            title_index=title_index,
        )
    )

    is_episode = fields.season is not None or fields.episode is not None
    template_kind: TemplateKind = "episode" if is_episode else "movie"
    manual = naming.manual_name if naming is not None and naming.mode == "manual" else None
    if manual is not None and manual.strip():
        template = manual
        template_kind = "manual"
        if manual.lower().endswith("." + extension):
            manual = manual[: -len(extension) - 1]
        segments = [[Piece(manual)]]
    else:
        if naming is not None and naming.mode == "manual":
            issues.append(
                ValidationIssue(
                    severity=Severity.WARNING,
                    code="naming.manual_name_empty",
                    path="output.naming.manual_name",
                    message="The manual output name is empty: the naming template is used.",
                )
            )
        if naming is not None and naming.template is not None:
            template = naming.template
        else:
            template = options.episode_template if is_episode else options.movie_template
        template_issues = check_template(template)
        issues.extend(template_issues)
        if any(issue.severity is Severity.ERROR for issue in template_issues):
            notes.append("The naming template has errors: the source file name is used.")
            segments = [[Piece(file_stem, "file_name")]]
        else:
            segments = render(parse_template(template), values)

    parts, sanitize_notes = sanitize_segments(segments, extension=extension, fallback=file_stem)
    notes.extend(sanitize_notes)
    relative = "/".join(parts)
    # Bytes of the source names that are not UTF-8 were replaced before parsing (parse_name):
    # say so when the output name shows them.
    names = [file.name, *([choice.folder.name] if choice.folder is not None else [])]
    if (
        UNDECODABLE_REPLACEMENT in relative
        and UNDECODABLE_NOTE not in notes
        and any(replace_undecodable(name) != name for name in names)
    ):
        notes.insert(0, UNDECODABLE_NOTE)

    folder: Path | None = file.parent
    if options.output_folder_mode == "fixed":
        folder = options.output_folder
        if folder is None:
            issues.append(
                ValidationIssue(
                    severity=Severity.WARNING,
                    code="naming.no_output_folder",
                    path="naming.output_folder",
                    message="The output folder is set to a fixed folder, but no folder is chosen.",
                )
            )
    path = folder.joinpath(*parts) if folder is not None else None

    variables: dict[str, str] = {}
    for name in VARIABLE_KINDS:
        variables[name] = format_value(name, values.get(name), None)

    return NameResult(
        source=choice.kind,
        reason=choice.reason,
        season_pack=choice.season_pack,
        candidates=choice.candidates,
        skipped_folders=choice.skipped,
        fields=fields,
        template=template,
        template_kind=template_kind,
        relative_path=relative,
        path=path,
        extension=extension,
        variables=variables,
        notes=notes,
        issues=issues,
    )
