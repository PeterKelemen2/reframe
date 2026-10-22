"""The event WebSocket hub: one sender per connection, fed by the core's event bus.

Stub: a connection is accepted and closed at once until the event step is built.
"""

from __future__ import annotations

from fastapi import WebSocket

from reframe.events import EventBus
from reframe_server.config import ServerConfig

__all__ = ["EventHub"]


class EventHub:
    """Every open ``WS /api/events`` connection. Created and closed by the app's lifespan."""

    def __init__(self, bus: EventBus, config: ServerConfig) -> None:
        self._bus = bus
        self._config = config

    @property
    def connections(self) -> int:
        """Open, authenticated connections."""
        return 0

    def client_open(self, client_id: str) -> bool:
        """A connection that was given ``client_id`` is open (for ``attach``)."""
        return False

    async def serve(self, websocket: WebSocket) -> None:
        """Run one connection until it ends. Never raises for a client that goes away."""
        await websocket.accept()
        await websocket.close(code=1013)

    async def close(self) -> None:
        """End every connection. Safe to call more than once."""
