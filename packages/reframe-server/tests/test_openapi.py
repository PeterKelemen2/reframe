"""The OpenAPI document that ``scripts/gen-api.sh`` turns into the frontend's TypeScript types."""

from __future__ import annotations

import importlib
import json
import os
import pkgutil
import subprocess
import sys
from typing import Any

import pytest
from fastapi.routing import APIRoute

import reframe_server.routers
from reframe_server.app import create_app
from reframe_server.config import ServerConfig
from reframe_testing.server import ROOT

EXPORT = ROOT / "scripts" / "export-openapi.py"


@pytest.fixture(scope="module")
def document() -> dict[str, Any]:
    return create_app(ServerConfig(host="127.0.0.1", mode="web", auth="none")).openapi()


def _ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


def test_the_event_websocket_messages_are_in_the_components(document: dict[str, Any]) -> None:
    schemas = document["components"]["schemas"]
    assert schemas["ServerMessage"]["discriminator"]["mapping"] == {
        "hello": _ref("Hello")["$ref"],
        "event": _ref("EventMessage")["$ref"],
        "heartbeat": _ref("Heartbeat")["$ref"],
    }
    assert _ref("JobProgressEvent") in schemas["EventMessage"]["properties"]["event"]["oneOf"]
    assert set(schemas["AuthMessage"]["properties"]) == {"type", "token"}
    assert schemas["ClientMessage"]["discriminator"]["mapping"] == {
        "auth": _ref("AuthMessage")["$ref"],
        "detach": _ref("DetachMessage")["$ref"],
    }
    assert "client_id" in schemas["Hello"]["required"]
    # No HTTP operation for the WebSocket: a generated client would call it.
    assert "webhooks" not in document
    assert not [path for path in document["paths"] if path.startswith("/api/events")]


def test_operation_ids_are_unique_and_follow_tag_and_handler_name(
    document: dict[str, Any],
) -> None:
    handlers = {}
    for info in pkgutil.iter_modules(reframe_server.routers.__path__):
        module = importlib.import_module(f"reframe_server.routers.{info.name}")
        for route in module.router.routes:
            if isinstance(route, APIRoute):
                for method in route.methods or ():
                    handlers[("/api" + route.path, method.lower())] = route.name
    operations = [
        (operation["operationId"], operation["tags"], handlers[(path, method)])
        for path, item in document["paths"].items()
        for method, operation in item.items()
    ]
    ids = [op for op, _, _ in operations]
    assert sorted(op for op in set(ids) if ids.count(op) > 1) == []
    assert [
        (op, tags) for op, tags, name in operations if [op] != [f"{t}_{name}" for t in tags]
    ] == []


def test_the_export_is_the_served_document_whatever_the_process_and_its_environment(
    document: dict[str, Any],
) -> None:
    """The committed types stay comparable: the same document, in the same order, from a
    process with another hash seed and the developer's ``REFRAME_*`` variables (this host
    would need an auth mode), as UTF-8 with LF line ends on every platform."""
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("REFRAME_")
    }
    seed = "1" if os.environ.get("PYTHONHASHSEED") == "0" else "0"
    exported = subprocess.run(
        [sys.executable, str(EXPORT)],
        env=environment | {"PYTHONHASHSEED": seed, "REFRAME_HOST": "0.0.0.0"},
        capture_output=True,
        check=True,
        timeout=60,
    ).stdout
    assert b"\r" not in exported
    # Compared as text so that the order of the keys counts.
    assert json.dumps(json.loads(exported.decode("utf-8"))) == json.dumps(document)
