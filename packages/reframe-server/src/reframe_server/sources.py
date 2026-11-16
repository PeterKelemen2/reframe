"""Source ids: the facade takes paths, the API takes ``source_id``. An id is a hash of the
absolute path, so probing the same file again gives the same id. The registry is memory only:
after a restart the client probes again."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from reframe.models import MediaSource
from reframe.service import Reframe
from reframe_server.errors import ProblemError

__all__ = ["SourceRegistry", "source_id"]


def source_id(path: Path) -> str:
    return hashlib.sha256(os.fsencode(path)).hexdigest()[:24]


class SourceRegistry:
    """The sources this server has probed, by id, in the order they were added."""

    def __init__(self) -> None:
        self._paths: dict[str, Path] = {}

    def add(self, path: Path) -> str:
        sid = source_id(path)
        self._paths[sid] = path
        return sid

    def remove(self, sid: str) -> bool:
        return self._paths.pop(sid, None) is not None

    def items(self) -> list[tuple[str, Path]]:
        return list(self._paths.items())

    async def get(self, reframe: Reframe, sid: str) -> MediaSource:
        """The probed source of ``sid``. Never runs ffprobe.

        Raises :class:`ProblemError`: 404 ``source.unknown`` for an id this server never
        gave, 409 ``source.stale`` when the file changed or is gone since it was probed.
        """
        path = self._paths.get(sid)
        if path is None:
            raise ProblemError(404, "source.unknown", f"No source {sid}")
        source = await reframe.sources.get(path)
        if source is None:
            raise ProblemError(
                409,
                "source.stale",
                "The file changed or is gone since it was probed",
                "Probe it again with POST /api/sources.",
            )
        return source
