"""The OpenAPI document that ``scripts/gen-api.sh`` turns into the frontend's TypeScript types."""

from __future__ import annotations

import importlib
import json
import os
import pkgutil
import subprocess
import sys

import pytest
from fastapi.routing import APIRoute

import reframe_server.routers
from reframe_server.app import create_app
from reframe_server.config import ServerConfig
from reframe_testing.server import ROOT, Api

pytestmark = pytest.mark.anyio

EXPORT = ROOT / "scripts" / "export-openapi.py"


def _ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


async def test_the_event_websocket_messages_are_in_the_components(api: Api) -> None:
    document = (await api.client.get("/api/openapi.json")).json()
    schemas = document["components"]["schemas"]
    assert schemas["ServerMessage"]["discriminator"]["mapping"] == {
        "hello": _ref("Hello")["$ref"],
        "event": _ref("EventMessage")["$ref"],
        "heartbeat": _ref("Heartbeat")["$ref"],
    }
    assert _ref("JobProgressEvent") in schemas["EventMessage"]["properties"]["event"]["oneOf"]
    assert set(schemas["AuthMessage"]["properties"]) == {"type", "token"}
    # No HTTP operation for the WebSocket: a generated client would call it.
    assert "webhooks" not in document
    assert not [path for path in document["paths"] if path.startswith("/api/events")]


async def test_operation_ids_are_unique_and_follow_tag_and_handler_name(api: Api) -> None:
    handlers = {}
    for info in pkgutil.iter_modules(reframe_server.routers.__path__):
        module = importlib.import_module(f"reframe_server.routers.{info.name}")
        for route in module.router.routes:
            if isinstance(route, APIRoute):
                for method in route.methods or ():
                    handlers[("/api" + route.path, method.lower())] = route.name
    operations = [
        (operation["operationId"], operation["tags"], handlers[(path, method)])
        for path, item in api.app.openapi()["paths"].items()
        for method, operation in item.items()
    ]
    ids = [op for op, _, _ in operations]
    assert sorted(op for op in set(ids) if ids.count(op) > 1) == []
    assert [
        (op, tags) for op, tags, name in operations if [op] != [f"{t}_{name}" for t in tags]
    ] == []


def _export(**env: str) -> str:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("REFRAME_")
    }
    result = subprocess.run(
        [sys.executable, str(EXPORT)],
        env=environment | env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=60,
    )
    return result.stdout


def test_the_export_is_the_served_document_whatever_the_process_and_its_environment() -> None:
    """The committed types stay comparable: the same bytes in every run, whatever the
    developer's ``REFRAME_*`` variables (this host would need an auth mode)."""
    first = _export(PYTHONHASHSEED="1")
    second = _export(PYTHONHASHSEED="2", REFRAME_HOST="0.0.0.0", REFRAME_MODE="desktop")
    assert first == second
    served = create_app(ServerConfig(host="127.0.0.1", mode="web", auth="none")).openapi()
    assert json.loads(first) == served
