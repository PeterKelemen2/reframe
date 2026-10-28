"""A front end's use of the server that owns the queue of its data folder: finding it (or
starting one) and its queue over the server's REST routes and event WebSocket. Needs the
``[cli]`` extra (``httpx``, ``websockets``); nothing else in the core imports this package."""

from reframe.remote.owner import API_VERSION, NoOwner, Owner, find_owner
from reframe.remote.queue import OwnerStopping, RemoteError, RemotePower, RemoteQueue

__all__ = [
    "API_VERSION",
    "NoOwner",
    "Owner",
    "OwnerStopping",
    "RemoteError",
    "RemotePower",
    "RemoteQueue",
    "find_owner",
]
