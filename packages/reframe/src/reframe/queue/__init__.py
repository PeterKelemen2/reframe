"""The queue and job runner. :class:`QueueService` is the entry point; a front end uses it
through :class:`QueueLike`.

The store is opened at the first use, by the one process that holds ``queue.lock``.
"""

from reframe.queue.client import QueueLike, SavedQueue, read_saved_queue
from reframe.queue.errors import JobStateError, QueueError, UnknownJobError
from reframe.queue.service import ACTIVE, ENDED, QueueService

__all__ = [
    "ACTIVE",
    "ENDED",
    "JobStateError",
    "QueueError",
    "QueueLike",
    "QueueService",
    "SavedQueue",
    "UnknownJobError",
    "read_saved_queue",
]
