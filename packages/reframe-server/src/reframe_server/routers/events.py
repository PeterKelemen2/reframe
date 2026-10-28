"""``WS /api/events``: the client authenticates in its first message, then receives events."""

from __future__ import annotations

from fastapi import WebSocket

from reframe_server.api import api_router
from reframe_server.deps import HubDep

router = api_router("events")


@router.websocket("/events")
async def stream(websocket: WebSocket, hub: HubDep) -> None:
    await hub.serve(websocket)
