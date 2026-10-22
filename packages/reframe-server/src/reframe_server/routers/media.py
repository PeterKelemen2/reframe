"""The frame and clip files. ``<img>`` and ``<video>`` cannot send a token, so these routes
take a signed URL instead (``require_media_access``)."""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import BinaryIO

from fastapi import Depends, Request, Response
from fastapi.responses import StreamingResponse

from reframe_server import security
from reframe_server.api import api_router
from reframe_server.deps import ReframeDep
from reframe_server.errors import ProblemError

router = api_router("preview")

CHUNK = 256 * 1024
_RANGE = re.compile(r"bytes=(\d*)-(\d*)")
_VIDEO_TYPES = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
}


@router.get(
    "/preview/frames/{key}.png",
    dependencies=[Depends(security.require_media_access)],
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}, 304: {"description": "Not modified"}},
)
async def frame_file(key: str, request: Request, reframe: ReframeDep) -> Response:
    """A cached frame. Its key names its content, so the key is its ETag."""
    path = await reframe.sources.frame(key)
    if path is None:
        raise _unknown_frame()
    etag = f'"{key}"'
    headers = {"ETag": etag, "Cache-Control": "private, max-age=3600"}
    if _matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    try:
        data = await asyncio.to_thread(path.read_bytes)
    except OSError:  # evicted from the cache since the lookup
        raise _unknown_frame() from None
    return Response(data, media_type="image/png", headers=headers)


@router.get(
    "/preview/clips/{clip_id}",
    dependencies=[Depends(security.require_media_access)],
    response_class=Response,
    responses={200: {"content": {"video/*": {}}}, 206: {"description": "Partial content"}},
)
async def clip_file(clip_id: str, request: Request, reframe: ReframeDep) -> Response:
    """A cached clip; one byte range (``Range: bytes=…``) gives a ``206``."""
    path = await reframe.jobs.preview_clip_path(clip_id)
    opened = None if path is None else await asyncio.to_thread(_open, path)
    if path is None or opened is None:
        raise ProblemError(404, "preview.unknown_clip", "The clip is not in the cache")
    file, size = opened
    try:
        wanted = _byte_range(request.headers.get("range"), size)
    except ProblemError:
        file.close()
        raise
    headers = {
        "Accept-Ranges": "bytes",
        "ETag": f'"{clip_id}"',
        "Cache-Control": "private, max-age=3600",
    }
    media_type = _VIDEO_TYPES.get(path.suffix.lower(), "application/octet-stream")
    if wanted is None:
        start, end, status = 0, size - 1, 200
    else:
        (start, end), status = wanted, 206
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    headers["Content-Length"] = str(end - start + 1)
    return StreamingResponse(
        _chunks(file, start, end - start + 1),
        status_code=status,
        media_type=media_type,
        headers=headers,
    )


def _unknown_frame() -> ProblemError:
    return ProblemError(404, "preview.unknown_frame", "The frame is not in the cache")


def _matches(if_none_match: str | None, etag: str) -> bool:
    return if_none_match is not None and etag in (tag.strip() for tag in if_none_match.split(","))


def _open(path: Path) -> tuple[BinaryIO, int] | None:
    """The open clip and its size; the open file stays readable if the cache evicts it."""
    try:
        file = path.open("rb")
    except OSError:
        return None
    return file, os.fstat(file.fileno()).st_size


def _byte_range(header: str | None, size: int) -> tuple[int, int] | None:
    """The first and last byte of a single ``bytes`` range, ``None`` for the whole file (no
    range, several ranges or one that does not parse: a server may ignore those)."""
    match = _RANGE.fullmatch(header.strip()) if header is not None else None
    if match is None or match.groups() == ("", ""):
        return None
    first, last = match.groups()
    if first == "":
        start, end = max(size - int(last), 0), size - 1
        satisfiable = int(last) > 0 and size > 0
    else:
        start = int(first)
        end = size - 1 if last == "" else min(int(last), size - 1)
        if last != "" and int(last) < start:
            return None
        satisfiable = start < size
    if not satisfiable:
        raise ProblemError(
            416,
            "preview.range_not_satisfiable",
            "The range is outside the clip",
            headers={"Content-Range": f"bytes */{size}"},
        )
    return start, end


async def _chunks(file: BinaryIO, start: int, length: int) -> AsyncIterator[bytes]:
    try:
        await asyncio.to_thread(file.seek, start)
        while length > 0:
            chunk = await asyncio.to_thread(file.read, min(CHUNK, length))
            if not chunk:
                return
            length -= len(chunk)
            yield chunk
    finally:
        file.close()
