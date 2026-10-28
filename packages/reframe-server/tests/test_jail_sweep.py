"""Every place in a request where a client names a path goes through the real jail of a web
server: a symbolic link below a root that points out of it is refused, and the refused request
changes nothing. The jail itself (each kind of escape) is tested in ``test_security_jail.py``;
this sweep is about each route using it."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pytest

from reframe.models import MediaSource
from reframe_server.app import create_app
from reframe_server.config import ServerConfig
from reframe_testing.server import Api

pytestmark = pytest.mark.anyio

NO_SOURCE = "0" * 24
"""A source id the server never gave: the jail must refuse the request before the lookup."""
FOLDER = "/output/naming/output_folder"


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
    request: Callable[[Api, str, list[str]], Request]
    """``(api, path, source_ids)`` → the request with ``path`` in this place. In a list, an
    entry the jail allows goes before ``path``, so a route that checks only the first fails."""
    source: bool = False
    """``source_ids`` names two probed sources, else it is empty."""


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
    def request(api: Api, path: str, sids: list[str]) -> Request:
        def ops(subtitle: str) -> list[dict[str, Any]]:
            value = {"source": {"path": subtitle}}
            return [{"op": "add", "path": "/job/subtitles/-", "value": value}]

        allowed, hostile = str(api.media / "a.srt"), path.removesuffix(".mkv") + ".srt"
        overrides = {sids[0]: ops(allowed), sids[1]: ops(hostile)}
        return Request("post", url, {"source_ids": sids, "overrides": overrides})

    return PathInput(operation, "overrides", "media", request, source=True)


INPUTS = [
    PathInput(
        "fs_list",
        "path",
        "media",
        lambda _, p, __: Request("get", "/api/fs/list", params={"path": str(Path(p).parent)}),
    ),
    PathInput(
        "sources_probe",
        "paths",
        "media",
        lambda api, p, _: Request("post", "/api/sources", {"paths": [str(api.media), p]}),
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
        lambda api, p, _: Request(
            "post",
            "/api/presets/import",
            {
                "presets": [
                    {"id": "ours", "name": "Ours", "naming": naming(str(api.output / "Shows"))},
                    {"id": "mine", "name": "Mine", "naming": naming(p)},
                ]
            },
            raw=True,
        ),
    ),
    PathInput(
        "queue_add",
        "jobs",
        "media",
        lambda api, p, _: Request(
            "post", "/api/queue", {"jobs": [job(api, str(api.media / "a.mkv")), job(api, p)]}
        ),
    ),
    PathInput(
        "settings_update",
        "patch",
        "output",
        lambda api, p, _: Request(
            "put",
            "/api/settings",
            [
                {"op": "replace", "path": FOLDER, "value": str(api.output / "Shows")},
                {"op": "replace", "path": FOLDER, "value": p},
            ],
        ),
    ),
]


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


@pytest.fixture(scope="module")
def document() -> dict[str, Any]:
    return create_app(ServerConfig(host="127.0.0.1", mode="web", auth="none")).openapi()


def test_the_sweep_covers_every_route_that_takes_a_path(document: dict[str, Any]) -> None:
    """A new route with a path in its request must get a row in ``INPUTS``."""
    assert operations_with_paths(document) == {i.operation for i in INPUTS}


@pytest.fixture
def outside_film(api: Api) -> Path:
    film = api.outside / "film.mkv"
    film.write_bytes(b"not really matroska")
    return film


def symlink(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except OSError as exc:  # Windows without the symlink privilege
        pytest.skip(f"cannot make a symbolic link: {exc}")


async def probed_sources(api: Api) -> list[str]:
    ids = []
    for name in ("Show S01E01.mkv", "Show S01E02.mkv"):
        path = api.media_file(name)
        assert isinstance(await api.reframe.sources.probe(path), MediaSource)
        ids.append(api.app.state.sources.add(path))
    return ids


async def send(api: Api, request: Request) -> Any:
    if request.raw:
        return await api.client.request(
            request.method, request.url, content=json.dumps(request.body), params=request.params
        )
    return await api.client.request(
        request.method, request.url, json=request.body, params=request.params
    )


def state(api: Api, escape: Path) -> dict[str, Any]:
    """What a request could change: tool runs on a path through ``escape`` or in the outside
    folder, tasks, the queue, presets, settings, and the files below the output root, the
    outside folder and the config folder. Tool runs on other paths are the server's own (the
    capability checks)."""
    assert api.config.config_dir is not None
    folders = (api.output, api.outside, api.config.config_dir)
    named = (str(escape), str(api.outside), str(api.outside.resolve()))
    return {
        "tool runs": [
            call for call in api.fake.calls() if any(n in a for a in call for n in named)
        ],
        "tasks": [task.id for task in api.reframe.tasks.list()],
        "queue": [queued.id for queued in api.reframe.queue.list()],
        "presets": [preset.model_dump(mode="json") for preset in api.reframe.presets.list()],
        "settings": api.reframe.settings.get().model_dump(mode="json"),
        "files": {
            file: file.stat().st_mtime_ns
            for folder in folders
            for file in folder.rglob("*")
            if file.is_file()
        },
    }


@pytest.mark.parametrize("item", [pytest.param(i, id=f"{i.operation}.{i.name}") for i in INPUTS])
async def test_a_link_out_of_a_root_is_refused_and_changes_nothing(
    api: Api, outside_film: Path, item: PathInput
) -> None:
    sids = await probed_sources(api) if item.source else []
    escape = (api.media if item.root == "media" else api.output) / "escape"
    symlink(escape, api.outside)
    path = escape / outside_film.name
    before = state(api, escape)
    response = await send(api, item.request(api, str(path), sids))
    body = response.json()
    code = body.get("code") if isinstance(body, dict) else None
    assert (response.status_code, code) == (403, "path.outside_roots")
    assert state(api, escape) == before


async def test_a_link_out_of_a_root_in_a_probed_folder_is_not_probed(
    api: Api, outside_film: Path
) -> None:
    link = api.media / "film.mkv"
    symlink(link, outside_film)
    response = await api.client.post("/api/sources", json={"paths": [str(api.media)]})
    if response.status_code == 202:
        await api.reframe.tasks.wait(response.json()["task_id"])
    named = (str(link), str(api.outside), str(api.outside.resolve()))
    probed = api.fake.calls("ffprobe")
    assert [call for call in probed if any(n in a for a in call for n in named)] == []
    listed = (await api.client.get("/api/sources")).json()
    assert [s["path"] for s in listed if any(n in s["path"] for n in named)] == []
