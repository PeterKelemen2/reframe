"""External subtitle files, read before they are added to a job."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from reframe.models import SubtitleFileInfo
from reframe.probe import ProbeError, ProbeErrorKind
from reframe_server import security
from reframe_server.api import api_router
from reframe_server.deps import ConfigDep, ReframeDep
from reframe_server.errors import ProblemError, probe_problem

router = api_router("subtitles")


class SubtitleInspectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    path: str


@router.post("/subtitles/inspect", name="inspect")
async def inspect(
    body: SubtitleInspectRequest, reframe: ReframeDep, config: ConfigDep
) -> SubtitleFileInfo:
    """The format, event count and character encoding of a subtitle file. A file that a job
    cannot take (another type, or no subtitles FFmpeg can read) is a 422
    ``subtitles.unsupported`` problem; a missing file a 404 ``probe.not_found``."""
    path = security.jail_read(config, body.path)
    result = await reframe.sources.inspect_subtitle(path)
    if not isinstance(result, ProbeError):
        return result
    if result.kind in (ProbeErrorKind.FAILED, ProbeErrorKind.INVALID_OUTPUT):
        raise ProblemError(
            422,
            "subtitles.unsupported",
            "The file is not a subtitle file that can be added",
            " ".join(part for part in (result.message, result.detail) if part),
        )
    raise probe_problem(result)
