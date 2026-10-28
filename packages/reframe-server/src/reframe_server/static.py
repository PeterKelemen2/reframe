"""The frontend's files in web mode: hashed assets cached for good, ``index.html`` for any
other path outside ``/api``. Desktop mode serves none: the shell bundles the frontend. A
path is resolved (links followed) and must stay inside the resolved folder."""

from __future__ import annotations

import logging
import ntpath
from pathlib import Path

import anyio.to_thread
from fastapi import FastAPI
from starlette.responses import FileResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from reframe_server.config import ServerConfig

__all__ = ["install"]

log = logging.getLogger(__name__)

ASSETS = "assets"
"""Vite's output folder for files with a content hash in their name."""
IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"

# Python takes these from the OS; the Windows registry may map .js to text/plain, and a
# browser refuses a module script of that type.
_MEDIA_TYPES = {
    ".css": "text/css",
    ".html": "text/html",
    ".js": "text/javascript",
    ".json": "application/json",
    ".mjs": "text/javascript",
    ".svg": "image/svg+xml",
    ".wasm": "application/wasm",
}


def install(app: FastAPI, config: ServerConfig) -> None:
    """Web mode with a ``static_dir``: serve it for every request that no route takes. Called
    after every API router; a request under ``/api`` keeps the 404 problem."""
    if config.mode != "web" or config.static_dir is None:
        return
    if not (config.static_dir / "index.html").is_file():
        log.warning("%s has no index.html: the frontend cannot load", config.static_dir)
    app.router.default = _Frontend(config.static_dir, app.router.default)


class _Frontend:
    def __init__(self, folder: Path, not_found: ASGIApp) -> None:
        self.folder = folder
        self.not_found = not_found

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        found = None
        if scope["type"] == "http" and scope["method"] in ("GET", "HEAD"):
            path: str = scope["path"]
            if path != "/api" and not path.startswith("/api/"):
                found = await anyio.to_thread.run_sync(self._lookup, path.lstrip("/"))
        if found is None:
            await self.not_found(scope, receive, send)
            return
        file, cache = found
        response = FileResponse(
            file, headers={"Cache-Control": cache}, media_type=_MEDIA_TYPES.get(file.suffix)
        )
        await response(scope, receive, send)

    def _lookup(self, relative: str) -> tuple[Path, str] | None:
        # Resolved per request, so that a deploy may swap a link to a new build.
        root = self.folder.resolve()
        file = _inside(root, relative)
        if file is not None:
            return file, IMMUTABLE if file.is_relative_to(root / ASSETS) else REVALIDATE
        if relative.partition("/")[0] == ASSETS:
            # HTML under a script's URL would fail in the browser with a misleading error.
            return None
        index = _inside(root, "index.html")
        return None if index is None else (index, REVALIDATE)


def _inside(root: Path, relative: str) -> Path | None:
    # On Windows a drive, UNC or device path replaces root in the join, and resolve() opens it
    # before the check below (a UNC path: an SMB session with the server's credentials).
    if "\\" in relative or ":" in relative or ntpath.isreserved(relative):
        return None
    try:
        file = (root / relative).resolve()
    except OSError:  # Windows: realpath raises the errors that it does not expect
        return None
    return file if file.is_relative_to(root) and file.is_file() else None
