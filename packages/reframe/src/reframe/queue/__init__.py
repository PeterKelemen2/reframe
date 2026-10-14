"""The queue and job runner (C-11): ``Reframe.queue``.

- :class:`QueueService`: add, list, get, remove, reorder, retry, start, stop, pause, resume,
  cancel, wait, log_path, close (the M2 contract in ``docs/m2-breakdown.md``; ``start`` has
  the keyword-only ``job_ids``). ``Reframe.create()`` loads the saved queue with
  ``_restore()``.
- Modules: ``store`` (SQLite, ``<data dir>/queue.sqlite3``), ``runner`` (one job: prepare,
  steps, finalize), ``progress`` (``-progress`` parser, weighted percent, sleep-aware ETA),
  ``watchdog`` (stall check and step time limit), ``loudnorm`` (measurements and clamping),
  ``verify`` (the output check), ``logs`` (log file and ``job.log`` events), ``process``
  (suspend / resume of a process tree), ``files`` (rename, clean-up), ``errors``.

The choices the plan does not make are in decision 0016.
"""

from reframe.queue.errors import JobStateError, QueueError, UnknownJobError
from reframe.queue.service import ENDED, QueueService

__all__ = ["ENDED", "JobStateError", "QueueError", "QueueService", "UnknownJobError"]
