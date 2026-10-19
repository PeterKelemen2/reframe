"""The queue and job runner. :class:`QueueService` is the entry point.

The store is opened at the first use, by the one process that holds ``queue.lock``.
"""

from reframe.queue.errors import JobStateError, QueueError, UnknownJobError
from reframe.queue.service import ENDED, QueueService

__all__ = ["ENDED", "JobStateError", "QueueError", "QueueService", "UnknownJobError"]
