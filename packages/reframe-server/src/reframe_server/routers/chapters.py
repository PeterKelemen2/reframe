"""Chapter files read for the Chapters tab: HandBrake CSV, OGM text, Matroska XML."""

from __future__ import annotations

import asyncio

from pydantic import BaseModel, ConfigDict

from reframe.chapters import ChapterFileError, read_chapter_file
from reframe.models import ChapterFormat, ChapterImport
from reframe_server import security
from reframe_server.api import api_router
from reframe_server.deps import ConfigDep
from reframe_server.errors import ProblemError

router = api_router("chapters")


class ChapterImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    path: str
    format: ChapterFormat | None = None
    """``null``: from the file's content."""


@router.post("/chapters/import", name="import_file")
async def import_file(body: ChapterImportRequest, config: ConfigDep) -> ChapterImport:
    """The chapters of a chapter file: each name, and its start where the format has one. A
    file that cannot be read is a 422 problem: ``chapters.unreadable`` (missing, too large),
    ``chapters.invalid`` (its content; the detail names the line)."""
    path = security.jail_read(config, body.path)
    result = await asyncio.to_thread(read_chapter_file, path, body.format)
    if isinstance(result, ChapterFileError):
        title = (
            "The chapter file cannot be read"
            if result.kind == "unreadable"
            else "The file is not a chapter file that can be read"
        )
        raise ProblemError(422, f"chapters.{result.kind}", title, result.detail)
    return result
