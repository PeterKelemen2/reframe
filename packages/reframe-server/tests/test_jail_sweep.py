"""Every route that takes a path refuses one outside the roots, with the real jail of a web
server; every router refuses a foreign ``Host``. The jail functions themselves are tested in
``test_security_jail.py``; this sweep is about each route using them."""

from __future__ import annotations

import importlib
import json
import pkgutil
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pytest
from fastapi.routing import APIRoute, APIWebSocketRoute
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

import reframe_server.routers
from reframe.models import MediaSource
from reframe_testing.server import Api

pytestmark = pytest.mark.anyio

NO_SOURCE = "0" * 24
"""A source id the server never gave: the jail must refuse the request before the lookup."""


@dataclass(frozen=True)
class Request:
    method: str
    url: str
    body: Any = None
    params: dict[str, str] | None = None
    raw: bool = False
    """``body`` is sent as JSON text without a declared model (the preset import)."""


@dataclass(frozen=True)
class PathInput:
    """One place of a route's request where a client names a path."""

    operation: str
    name: str
    root: Literal["media", "output"]
    """The root the path belongs below: reading from media, writing to output."""
    request: Callable[[Api, str, str], Request]
    """``(api, path, source_id)`` → the request with ``path`` in this place."""


def job(api: Api, source: str) -> dict[str, Any]:
    """A job that reads ``source`` and writes below the output root."""
    return {"source": {"path": source}, "output": {"path": str(api.output / "a.mkv")}}


def naming(folder: str) -> dict[str, Any]:
    return {"output_folder": folder}


def single_job(operation: str, url: str) -> PathInput:
    return PathInput(
        operation, "job", "media", lambda api, p, _: Request("post", url, {"job": job(api, p)})
    )


def override(operation: str, url: str) -> PathInput:
    def request(api: Api, path: str, sid: str) -> Request:
        subtitle = {"source": {"path": path.removesuffix(".mkv") + ".srt"}}
        ops = [{"op": "add", "path": "/job/subtitles/-", "value": subtitle}]
        return Request("post", url, {"source_ids": [sid], "overrides": {sid: ops}})

    return PathInput(operation, "overrides", "media", request)


INPUTS = [
    PathInput(
        "fs_list",
        "path",
        "media",
        lambda _, p, __: Request("get", "/api/fs/list", params={"path": p}),
    ),
    PathInput(
        "sources_probe",
        "paths",
        "media",
        lambda _, p, __: Request("post", "/api/sources", {"paths": [p]}),
    ),
    PathInput(
        "preview_render",
        "job",
        "media",
        lambda api, p, _: Request(
            "post", "/api/preview/render", {"job": job(api, p), "timestamp": 0}
        ),
    ),
    PathInput(
        "preview_clip",
        "job",
        "media",
        lambda api, p, _: Request(
            "post", "/api/preview/clip", {"job": job(api, p), "start": 0, "seconds": 1}
        ),
    ),
    single_job("jobs_validate", "/api/jobs/validate"),
    single_job("jobs_plan", "/api/jobs/plan"),
    single_job("jobs_geometry", "/api/jobs/geometry"),
    single_job("jobs_dry_run", "/api/jobs/dry-run"),
    single_job("jobs_hdr_metadata", "/api/jobs/hdr-metadata"),
    PathInput(
        "jobs_explain",
        "template",
        "output",
        lambda _, p, __: Request(
            "post", "/api/jobs/explain", {"source_id": NO_SOURCE, "template": {"naming": naming(p)}}
        ),
    ),
    PathInput(
        "naming_preview",
        "naming",
        "output",
        lambda _, p, __: Request(
            "post", "/api/naming/preview", {"naming": naming(p), "source_ids": []}
        ),
    ),
    PathInput(
        "naming_preview",
        "job",
        "media",
        lambda api, p, _: Request(
            "post", "/api/naming/preview", {"job": job(api, p), "source_ids": []}
        ),
    ),
    PathInput(
        "batch_derive",
        "job",
        "media",
        lambda api, p, _: Request(
            "post",
            "/api/batch/derive",
            {"job": job(api, p), "source_id": NO_SOURCE, "sections": ["video"]},
        ),
    ),
    PathInput(
        "batch_derive",
        "base",
        "output",
        lambda api, p, _: Request(
            "post",
            "/api/batch/derive",
            {
                "job": job(api, str(api.media / "a.mkv")),
                "source_id": NO_SOURCE,
                "sections": ["video"],
                "base": {"naming": naming(p)},
            },
        ),
    ),
    PathInput(
        "batch_resolve",
        "template",
        "output",
        lambda _, p, __: Request(
            "post", "/api/batch/resolve", {"template": {"naming": naming(p)}, "source_ids": []}
        ),
    ),
    override("batch_resolve", "/api/batch/resolve"),
    PathInput(
        "batch_resolve_run",
        "template",
        "output",
        lambda _, p, __: Request(
            "post", "/api/batch/resolve-run", {"template": {"naming": naming(p)}, "source_ids": []}
        ),
    ),
    override("batch_resolve_run", "/api/batch/resolve-run"),
    PathInput(
        "batch_save_preset",
        "template",
        "output",
        lambda _, p, __: Request(
            "post", "/api/batch/save-preset", {"template": {"naming": naming(p)}, "name": "Mine"}
        ),
    ),
    PathInput(
        "presets_create",
        "template",
        "output",
        lambda _, p, __: Request(
            "post", "/api/presets", {"template": {"naming": naming(p)}, "name": "Mine"}
        ),
    ),
    PathInput(
        "presets_save",
        "preset",
        "output",
        lambda _, p, __: Request(
            "put", "/api/presets/mine", {"id": "mine", "name": "Mine", "naming": naming(p)}
        ),
    ),
    PathInput(
        "presets_diff",
        "template",
        "output",
        lambda _, p, __: Request(
            "post", "/api/presets/diff", {"template": {"naming": naming(p)}, "preset_id": "mine"}
        ),
    ),
    PathInput(
        "presets_import",
        "file",
        "output",
        lambda _, p, __: Request(
            "post",
            "/api/presets/import",
            {"presets": [{"id": "mine", "name": "Mine", "naming": naming(p)}]},
            raw=True,
        ),
    ),
    PathInput(
        "queue_add",
        "jobs",
        "media",
        lambda api, p, _: Request("post", "/api/queue", {"jobs": [job(api, p)]}),
    ),
    PathInput(
        "settings_update",
        "patch",
        "output",
        lambda _, p, __: Request(
            "put",
            "/api/settings",
            [{"op": "replace", "path": "/output/naming/output_folder", "value": p}],
        ),
    ),
]

_UNJAILED_OVERRIDES = (
    "the per-file overrides are not jailed: an override adds an external subtitle file outside "
    "the media roots, and the answer tells whether that file exists (subtitle.external_missing)"
)
BROKEN = {
    ("batch_resolve", "overrides"): _UNJAILED_OVERRIDES,
    ("batch_resolve_run", "overrides"): _UNJAILED_OVERRIDES,
}
"""Inputs whose route does not jail them: (operation, input) → the defect."""


_PATH_NAME = re.compile(r"^paths?$|_(path|paths|folder|file|dir)$")


def _carries_a_path(schema: Any, schemas: dict[str, Any], seen: set[str]) -> bool:
    """``schema`` has a path in it: a ``format: path`` string, a field named like a path, or
    a value of any shape (a JSON patch value, a raw document)."""
    if not isinstance(schema, dict):
        return False
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[1]
        if name in seen:
            return False
        seen.add(name)
        return _carries_a_path(schemas[name], schemas, seen)
    if schema == {} or schema.get("format") == "path":
        return True
    open_object = schema.get("type") == "object" and "properties" not in schema
    if open_object and schema.get("additionalProperties", True) in (True, {}):
        return True
    properties = schema.get("properties", {})
    if any(_PATH_NAME.search(name) for name in properties):
        return True
    parts = [*properties.values(), schema.get("items"), schema.get("additionalProperties")]
    for key in ("anyOf", "oneOf", "allOf", "prefixItems"):
        parts += schema.get(key, [])
    return any(_carries_a_path(part, schemas, seen) for part in parts)


def operations_with_paths(document: dict[str, Any]) -> set[str]:
    schemas = document["components"]["schemas"]
    found = set()
    for item in document["paths"].values():
        for operation in item.values():
            parts = [
                content.get("schema")
                for content in operation.get("requestBody", {}).get("content", {}).values()
            ]
            for parameter in operation.get("parameters", []):
                if parameter["in"] != "path":
                    if _PATH_NAME.search(parameter["name"]):
                        found.add(operation["operationId"])
                    parts.append(parameter.get("schema"))
            if any(_carries_a_path(part, schemas, set()) for part in parts):
                found.add(operation["operationId"])
    return found


async def test_the_sweep_covers_every_route_that_takes_a_path(api: Api) -> None:
    """A new route with a path in its request must get a row in ``INPUTS``."""
    assert operations_with_paths(api.app.openapi()) == {i.operation for i in INPUTS}


def hostile_paths(api: Api, root: Path) -> dict[str, str]:
    """A path in the outside folder, a ``../`` escape from ``root`` and a link below ``root``
    to the outside folder; each names a file, which a folder input takes as a folder."""
    link = root / "escape"
    if not link.exists():
        link.symlink_to(api.outside, target_is_directory=True)
    return {
        "outside": str(api.outside / "film.mkv"),
        "traversal": f"{root}/../{api.outside.name}/film.mkv",
        "symlink": str(link / "film.mkv"),
    }


async def probed_source(api: Api) -> str:
    path = api.media_file()
    assert isinstance(await api.reframe.sources.probe(path), MediaSource)
    sid: str = api.app.state.sources.add(path)
    return sid


async def send(api: Api, request: Request) -> Any:
    if request.raw:
        return await api.client.request(
            request.method, request.url, content=json.dumps(request.body), params=request.params
        )
    return await api.client.request(
        request.method, request.url, json=request.body, params=request.params
    )


def _cases() -> list[Any]:
    cases = []
    for item in INPUTS:
        defect = BROKEN.get((item.operation, item.name))
        marks = [pytest.mark.xfail(strict=True, reason=defect)] if defect else []
        cases.append(pytest.param(item, id=f"{item.operation}.{item.name}", marks=marks))
    return cases


@pytest.mark.parametrize("item", _cases())
async def test_a_path_outside_the_roots_is_refused(api: Api, item: PathInput) -> None:
    sid = await probed_source(api)
    root = api.media if item.root == "media" else api.output
    answers = {}
    for attack, path in hostile_paths(api, root).items():
        response = await send(api, item.request(api, path, sid))
        body = response.json()
        answers[attack] = (
            response.status_code,
            body.get("code") if isinstance(body, dict) else None,
        )
    expected = (403, "path.outside_roots")
    assert answers == dict.fromkeys(answers, expected)


def first_routes() -> list[tuple[str, str, str]]:
    """``(router module, method, path)`` of the first route of each router."""
    found = []
    for info in pkgutil.iter_modules(reframe_server.routers.__path__):
        module = importlib.import_module(f"reframe_server.routers.{info.name}")
        route = module.router.routes[0]
        if isinstance(route, APIRoute):
            method = sorted(route.methods or ())[0]
        else:
            assert isinstance(route, APIWebSocketRoute)
            method = "websocket"
        found.append((info.name, method, "/api" + re.sub(r"\{[^}]+\}", "x", route.path)))
    return found


@pytest.mark.parametrize(("router", "method", "path"), first_routes(), ids=lambda v: str(v))
async def test_a_foreign_host_is_refused_by_every_router(
    api: Api, router: str, method: str, path: str
) -> None:
    if method != "websocket":
        response = await api.client.request(method, path, headers={"Host": "evil.example"})
        assert (response.status_code, response.json()["code"]) == (400, "request.host")
        return
    async with api.live() as server:
        uri = f"ws://evil.example:{server.port}{path}"
        with pytest.raises(InvalidStatus) as refused:
            async with connect(uri, host="127.0.0.1", port=server.port, open_timeout=10):
                pass
        assert refused.value.response.status_code == 403
