"""One value template rendered with the naming variables (03 §Tags: "Tag fields can use the same
variables as Output naming"; C-16).

:func:`render_value` fills a template such as ``{name}< - S{season:02}E{episode:02}>`` with the
values that output naming computes for the job's source (the parsed release name, the job's
codecs and languages, the output size …). It is what the command builder (C-7) writes as a
tag value and what an in-place metadata edit (C-13) writes as the container title. Unlike a
file name, the text is not made safe for a file system: a ``/`` stays a ``/``.

Pure by default: without ``fs`` no folder is listed and no file time is read (``{source}``
from a folder name that needs a listing falls back as naming does when a folder cannot be
read, and ``{modification-date}`` is empty); without ``now`` the variables ``{date}`` and
``{time}`` are empty. A template with errors is returned as typed.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from reframe.definitions import Definitions, load_definitions
from reframe.models.job import JobSettings
from reframe.models.media import MediaSource
from reframe.models.naming import NamingOptions
from reframe.naming.context import NameContext, build_values
from reframe.naming.fs import FileTimes, NamingFs
from reframe.naming.resolve import apply_overrides
from reframe.naming.source import choose_source, split_extension
from reframe.naming.template import Template, Value, parse_template, render, template_variables

__all__ = ["NoFiles", "render_value"]

#: ``now`` for the value builder when the caller gives none (``{date}``/``{time}`` are then
#: emptied again).
_PLACEHOLDER_NOW = datetime(2000, 1, 1, tzinfo=UTC)


class NoFiles:
    """A :class:`~reframe.naming.NamingFs` that can read nothing (pure callers)."""

    def list_files(self, folder: Path) -> list[str] | None:
        return None

    def file_times(self, file: Path) -> FileTimes | None:
        return None


def _text(parsed: Template, values: Mapping[str, Value]) -> str:
    segments = render(parsed, values)
    return "/".join("".join(piece.text for piece in segment) for segment in segments)


def render_value(
    template: str,
    job: JobSettings,
    source: MediaSource | None = None,
    *,
    options: NamingOptions | None = None,
    output_size: tuple[int, int] | None = None,
    now: datetime | None = None,
    fs: NamingFs | None = None,
    root: Path | None = None,
    definitions: Definitions | None = None,
) -> str:
    """``template`` with the naming variables of ``job`` (and its probed ``source``) filled
    in (see the module doc).

    :param options: the effective naming options (the preset's, else Settings → Output);
        ``None`` = the defaults. The job's own name source and per-file field overrides win.
    :param output_size: the scaled size of the output picture (``{width}``, ``{resolution}``).
    :param now: the time of ``{date}`` and ``{time}``; ``None`` leaves them empty.
    :param fs: the file-system reads of naming; ``None`` reads nothing.
    :param root: the opened folder (generic-folder skipping never goes above it).
    """
    parsed = parse_template(template)
    if parsed.errors:
        return template
    if not any(True for _ in template_variables(parsed.nodes)):
        return _text(parsed, {})
    reader: NamingFs = fs if fs is not None else NoFiles()
    naming = job.output.naming
    effective = options if options is not None else NamingOptions()
    mode = naming.name_source or effective.name_source
    file = Path(job.source.path)
    choice = choose_source(file, mode, root=root, fs=reader)
    fields, _, _ = apply_overrides(choice.fields, naming.field_overrides)
    stem, _ = split_extension(file.name)
    values = build_values(
        NameContext(
            fields=fields,
            source_text=choice.text,
            source_separator=choice.separator,
            file=file,
            file_stem=stem,
            options=effective,
            container=job.output.container,
            now=now if now is not None else _PLACEHOLDER_NOW,
            fs=reader,
            definitions=definitions if definitions is not None else load_definitions(),
            job=job,
            source=source,
            output_size=output_size,
        )
    )
    if now is None:
        values["date"] = values["time"] = None
    return _text(parsed, values)
