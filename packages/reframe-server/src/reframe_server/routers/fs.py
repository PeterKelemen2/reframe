"""The server-side file browser: media files and folders. Web mode shows only what is below
the media and output roots; desktop mode the user's whole file system."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

from reframe.probe import MEDIA_EXTENSIONS, natural_key
from reframe_server import security
from reframe_server.api import api_router
from reframe_server.config import ServerConfig
from reframe_server.deps import ConfigDep
from reframe_server.errors import ProblemError

router = api_router("fs")

RootKind = Literal["media", "output", "home", "drive"]


class FsRoot(BaseModel):
    """A place the browser starts from."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    name: str
    path: Path
    kind: RootKind
    """``media``: sources are read from here; ``output``: outputs may be written here
    (web mode). ``home`` and ``drive``: desktop mode."""


class FsRoots(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    roots: list[FsRoot]


class FsEntry(BaseModel):
    """A folder or a media file (other files and hidden entries are left out)."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    name: str
    path: Path
    kind: Literal["folder", "file"]
    size: int | None = None
    """Bytes (files only)."""
    modified: AwareDatetime | None = None


class FsListing(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    path: Path
    """The folder, resolved (links followed)."""
    parent: Path | None
    """``None`` at a root: the browser cannot go higher."""
    entries: list[FsEntry]
    """Folders first, then files, each in natural order."""


@router.get("/fs/roots")
async def roots(config: ConfigDep) -> FsRoots:
    """Where browsing starts: the media and output roots (web mode), or the home folder and
    the file system roots (desktop mode)."""
    return FsRoots(roots=await asyncio.to_thread(_roots, config))


@router.get("/fs/list", name="list")
async def list_folder(path: str, config: ConfigDep) -> FsListing:
    """The folders and media files in ``path``."""
    folder = _jailed(config, path)
    return await asyncio.to_thread(_listing, config, folder)


def _jailed(config: ServerConfig, path: str) -> Path:
    # Below an output root is fine too: the output folder picker browses there.
    try:
        return security.jail_read(config, path)
    except ProblemError:
        pass
    try:
        return security.jail_write(config, path)
    except ProblemError as refused:
        problem = refused.problem
        if problem.code != "path.outside_roots":
            raise
        # The write check's own text would say "may write to" while the user only browses.
        detail = (
            f"{path} is outside the server's media and output folders. Browse from one of them."
        )
        raise ProblemError(problem.status, problem.code, problem.title, detail) from None


def _roots(config: ServerConfig) -> list[FsRoot]:
    if config.mode == "web":
        kinds: list[tuple[RootKind, list[Path]]] = [
            ("media", config.media_roots),
            ("output", config.output_roots),
        ]
        return [
            FsRoot(name=root.name or str(root), path=root.resolve(), kind=kind)
            for kind, folders in kinds
            for root in folders
        ]
    home = Path.home()
    found = [FsRoot(name=home.name or str(home), path=home, kind="home")]
    if sys.platform == "win32":
        drives = [Path(drive) for drive in os.listdrives()]
    else:
        drives = [Path("/")]
    return found + [FsRoot(name=str(drive), path=drive, kind="drive") for drive in drives]


def _listing(config: ServerConfig, folder: Path) -> FsListing:
    try:
        with os.scandir(folder) as scan:
            entries = [entry for entry in (_entry(item) for item in scan) if entry is not None]
    except FileNotFoundError:
        raise ProblemError(404, "fs.not_found", "The folder does not exist") from None
    except NotADirectoryError:
        raise ProblemError(422, "fs.not_a_folder", "The path is not a folder") from None
    except OSError as exc:
        detail = exc.strerror
        raise ProblemError(403, "fs.unreadable", "The folder cannot be read", detail) from None
    entries.sort(key=lambda entry: (entry.kind != "folder", natural_key(entry.name)))
    return FsListing(path=folder, parent=_parent(config, folder), entries=entries)


def _entry(item: os.DirEntry[str]) -> FsEntry | None:
    if item.name.startswith("."):
        return None
    try:
        if item.is_dir():
            kind: Literal["folder", "file"] = "folder"
        elif item.is_file() and os.path.splitext(item.name)[1].lower() in MEDIA_EXTENSIONS:
            kind = "file"
        else:
            return None
        stat = item.stat()
    except OSError:  # gone since the listing
        return None
    return FsEntry(
        name=item.name,
        path=Path(item.path),
        kind=kind,
        size=stat.st_size if kind == "file" else None,
        modified=datetime.fromtimestamp(stat.st_mtime, UTC),
    )


def _parent(config: ServerConfig, folder: Path) -> Path | None:
    if folder.parent == folder:
        return None
    if config.mode == "web":
        roots = {root.resolve() for root in (*config.media_roots, *config.output_roots)}
        if folder in roots:
            return None
    return folder.parent
