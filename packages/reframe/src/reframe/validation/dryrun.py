"""The dry run of a job (03 §Advanced encoder options: custom parameters are "validated by a
dry run (``-frames:v 1 -f null``)").

Not a registered rule: it runs FFmpeg, so it is async and only runs on request
(``Reframe.jobs.dry_run``, ``Reframe.jobs.plan(…, dry_run=True)``).

Contract stub: built by the C-6 option-sets task (wave 1e).
"""

from __future__ import annotations

from reframe.definitions import Definitions
from reframe.models.capabilities import CapabilitySnapshot
from reframe.models.issues import ValidationIssue
from reframe.models.job import JobSettings
from reframe.models.media import MediaSource
from reframe.models.tools import ToolSet
from reframe.tools import CancelToken

__all__ = ["dry_run"]


async def dry_run(
    job: JobSettings,
    source: MediaSource,
    caps: CapabilitySnapshot,
    tools: ToolSet,
    *,
    definitions: Definitions | None = None,
    cancel: CancelToken | None = None,
) -> list[ValidationIssue]:
    """Encode one frame with the job's video settings (``-frames:v 1 -f null -``) and turn what
    FFmpeg refuses (an unknown or invalid custom parameter, an option the encoder rejects)
    into ``error`` issues with the path of the field (``video.custom_params``,
    ``video.advanced.<key>``). Through ``reframe.tools.run`` with a short timeout. The caller
    validates first; a job with errors is not dry-run."""
    raise NotImplementedError("C-6 dry run")
