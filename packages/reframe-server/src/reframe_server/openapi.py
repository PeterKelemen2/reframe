"""The OpenAPI document also carries the message models of ``WS /api/events``: OpenAPI has no
WebSocket operations, but the generated TypeScript types must cover these messages."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import FastAPI
from pydantic import Field, RootModel

from reframe_server.events import AuthMessage, DetachMessage, EventMessage, Heartbeat, Hello

__all__ = ["ClientMessage", "ServerMessage", "install"]


class ClientMessage(RootModel[Annotated[AuthMessage | DetachMessage, Field(discriminator="type")]]):
    """A message of ``WS /api/events`` from the client; ``type`` tells which. The first one is
    an ``AuthMessage``."""


class ServerMessage(
    RootModel[Annotated[Hello | EventMessage | Heartbeat, Field(discriminator="type")]]
):
    """A message of ``WS /api/events`` from the server; ``type`` tells which."""


async def _event_messages(message: ClientMessage) -> ServerMessage:
    raise NotImplementedError


def install(app: FastAPI) -> None:
    """Add the event WebSocket's messages to the components of ``app``'s OpenAPI document.

    They are generated as a webhook, so FastAPI names them in the same pass as the route
    models (one schema per model); the webhook itself is then left out of the document.
    """
    app.webhooks.add_api_route(
        "event-messages",
        _event_messages,
        methods=["POST"],
        response_model=ServerMessage,
        operation_id="events_messages",
    )
    generate = app.openapi

    def openapi() -> dict[str, Any]:
        document = generate()
        document.pop("webhooks", None)
        return document

    app.openapi = openapi  # type: ignore[method-assign]
