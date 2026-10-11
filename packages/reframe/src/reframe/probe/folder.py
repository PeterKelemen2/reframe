"""Probe a folder (C-3): media files only, natural order, a concurrency limit, progress.

- :func:`list_media_files`: the files of a folder whose extension is in
  :data:`MEDIA_EXTENSIONS` (case-insensitive), hidden files (``.name``) left out, sorted
  naturally (``E2`` before ``E10``, case-insensitive).
- :func:`probe_folder`: probes them with at most ``concurrency`` (default 4) ffprobe processes
  at a time; reports ``done / total`` after each file. A file that cannot be probed is an
  entry in :attr:`FolderProbeResult.errors`, not an exception.
- :func:`start_probe_folder`: the same as a background task of kind ``probe_folder``
  (:mod:`reframe.tasks`). Progress events say ``"3/24 files"``; the result
  (``TaskInfo.result``) is :meth:`FolderProbeResult.to_json`: the folder, the probed paths and
  the errors. The sources themselves are in the probe cache and in
  ``TaskManager.value(task_id)``.
"""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import JsonValue

from reframe.models.media import MediaSource
from reframe.models.tasks import TaskInfo
from reframe.probe.ffprobe import ProbeError, ProbeErrorKind
from reframe.probe.prober import Prober
from reframe.tasks import TaskContext, TaskManager
from reframe.tools import CancelToken

__all__ = [
    "DEFAULT_CONCURRENCY",
    "MEDIA_EXTENSIONS",
    "TASK_KIND",
    "FolderProbeResult",
    "list_media_files",
    "natural_key",
    "probe_folder",
    "start_probe_folder",
]

DEFAULT_CONCURRENCY = 4
TASK_KIND = "probe_folder"

#: Video files that a folder probe picks up (lower case, with the dot).
MEDIA_EXTENSIONS = frozenset(
    {
        ".mkv",
        ".mp4",
        ".m4v",
        ".mov",
        ".avi",
        ".webm",
        ".ts",
        ".m2ts",
        ".mts",
        ".mpg",
        ".mpeg",
        ".vob",
        ".wmv",
        ".asf",
        ".flv",
        ".ogm",
        ".ogv",
        ".3gp",
        ".divx",
        ".mxf",
    }
)

_DIGITS = re.compile(r"(\d+)")

#: Called after each file: ``(done, total, path)``.
ProgressCallback = Callable[[int, int, Path], object]


def natural_key(name: str) -> tuple[tuple[int, int | str], ...]:
    """Sort key: digit runs compare as numbers, the rest case-insensitively."""
    parts: list[tuple[int, int | str]] = []
    for i, part in enumerate(_DIGITS.split(name)):
        if i % 2:
            parts.append((0, int(part)))
        elif part:
            parts.append((1, part.casefold()))
    return tuple(parts)


def list_media_files(folder: Path, *, recursive: bool = False) -> list[Path]:
    """Media files in ``folder`` (or below it), naturally sorted by their relative path."""
    found: list[Path] = []
    if recursive:
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            found += [Path(root, f) for f in files if _is_media(f)]
    else:
        with os.scandir(folder) as entries:
            found = [
                Path(entry.path) for entry in entries if _is_media(entry.name) and entry.is_file()
            ]

    def key(path: Path) -> tuple[tuple[tuple[int, int | str], ...], ...]:
        return tuple(natural_key(part) for part in path.relative_to(folder).parts)

    return sorted(found, key=key)


def _is_media(name: str) -> bool:
    return not name.startswith(".") and os.path.splitext(name)[1].lower() in MEDIA_EXTENSIONS


@dataclass
class FolderProbeResult:
    folder: Path
    sources: list[MediaSource] = field(default_factory=list)
    """In file order (natural sort)."""
    errors: list[ProbeError] = field(default_factory=list)
    """In file order."""

    def to_json(self) -> JsonValue:
        return {
            "folder": str(self.folder),
            "total": len(self.sources) + len(self.errors),
            "probed": [str(s.ref.path) for s in self.sources],
            "errors": [dict(e.to_json()) for e in self.errors],
        }


async def probe_folder(
    prober: Prober,
    folder: str | os.PathLike[str],
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
    recursive: bool = False,
    cancel: CancelToken | None = None,
    on_progress: ProgressCallback | None = None,
) -> FolderProbeResult:
    """Probe every media file in ``folder``, ``concurrency`` at a time.

    A folder that cannot be listed gives a result with one error for the folder. Cancelling
    (the token or the calling task) kills the running ffprobe processes.
    """
    if concurrency < 1:
        raise ValueError(f"concurrency must be at least 1, got {concurrency}")
    root = Path(os.fspath(folder))
    result = FolderProbeResult(root)
    try:
        # A network share can be slow to list: do not block the event loop.
        root = await asyncio.to_thread(Path.absolute, root)
        result.folder = root
        files = await asyncio.to_thread(list_media_files, root, recursive=recursive)
    except FileNotFoundError:
        result.errors.append(
            ProbeError(root, ProbeErrorKind.NOT_FOUND, "The folder does not exist.")
        )
        return result
    except NotADirectoryError:
        result.errors.append(
            ProbeError(root, ProbeErrorKind.NOT_A_FILE, "The path is not a folder.")
        )
        return result
    except OSError as exc:
        result.errors.append(
            ProbeError(root, ProbeErrorKind.UNREADABLE, "The folder cannot be read.", str(exc))
        )
        return result

    total = len(files)
    outcomes: list[MediaSource | ProbeError | None] = [None] * total
    semaphore = asyncio.Semaphore(concurrency)
    done = 0

    async def one(i: int, path: Path) -> None:
        nonlocal done
        async with semaphore:
            outcomes[i] = await prober.probe(path, cancel=cancel)
        done += 1
        if on_progress is not None:
            on_progress(done, total, path)

    # A TaskGroup, not gather(): a cancelled gather() returns as soon as its first child ends,
    # and the other probes' process kills can then be dropped when the loop stops (orphaned
    # ffprobe). A TaskGroup returns only after every probe has finished.
    async with asyncio.TaskGroup() as group:
        for i, path in enumerate(files):
            group.create_task(one(i, path))
    for outcome in outcomes:
        if isinstance(outcome, MediaSource):
            result.sources.append(outcome)
        elif outcome is not None:
            result.errors.append(outcome)
    return result


def start_probe_folder(
    tasks: TaskManager,
    prober: Prober,
    folder: str | os.PathLike[str],
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
    recursive: bool = False,
) -> TaskInfo:
    """Start :func:`probe_folder` as a ``probe_folder`` task; returns its info at once."""
    root = Path(os.path.abspath(folder))

    async def work(ctx: TaskContext) -> FolderProbeResult:
        def report(done: int, total: int, path: Path) -> None:
            ctx.progress(done=done, total=total, message=f"{done}/{total} files")

        ctx.progress(0.0, "Listing files")
        return await probe_folder(
            prober,
            root,
            concurrency=concurrency,
            recursive=recursive,
            cancel=ctx.cancel,
            on_progress=report,
        )

    def to_json(value: object) -> JsonValue:
        return value.to_json() if isinstance(value, FolderProbeResult) else None

    return tasks.start(TASK_KIND, work, message=f"Probing {root.name}", result_json=to_json)
