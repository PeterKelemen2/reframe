"""Presets: read, create, change, delete, import, export, diff, and the defaults preview."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import Query, Request, Response
from pydantic import BaseModel, ConfigDict

from reframe.models import (
    AudioDefaults,
    Container,
    FieldChange,
    JobTemplate,
    Preset,
    SubtitleDefaults,
    TrackDraft,
    ValidationIssue,
)
from reframe.presets.store import ConflictPolicy
from reframe_server import security
from reframe_server.api import api_router
from reframe_server.config import ServerConfig
from reframe_server.deps import ConfigDep, ReframeDep, SourcesDep
from reframe_server.errors import ProblemError, issue_problem
from reframe_server.routers.jobs import jail_naming, jail_template, sources_of, unwrap

router = api_router("presets")

IMPORT_LIMIT = 4 * 1024 * 1024
"""Largest preset file ``POST /api/presets/import`` reads, in bytes."""

_ISSUE_STATUS = {
    "preset.not_found": 404,
    "preset.built_in": 409,
    "preset.name_conflict": 409,
    "preset.newer_version": 409,
    "presets.read_only": 409,
    "presets.write_failed": 503,
}


_STORE_MESSAGES = {
    "presets.read_only": (
        "The presets were not saved: the presets file of this server cannot be changed (it "
        "is damaged, unreadable or from a newer Reframe)."
    ),
    "presets.write_failed": "The presets could not be saved: this server cannot write them.",
}
"""Messages for the store's refusals, whose own messages name the server's presets file."""


def shown(config: ServerConfig, issue: ValidationIssue) -> ValidationIssue:
    """``issue`` without the server's folders in web mode; the desktop user is shown where
    the file is."""
    message = _STORE_MESSAGES.get(issue.code)
    if config.mode != "web" or message is None:
        return issue
    return issue.model_copy(update={"message": message})


def preset_problem(config: ServerConfig, issue: ValidationIssue) -> ProblemError:
    """A preset change the store refused; anything not listed is a 422."""
    return issue_problem(shown(config, issue), _ISSUE_STATUS.get(issue.code, 422))


def stored(config: ServerConfig, result: Preset | ValidationIssue) -> Preset:
    if isinstance(result, ValidationIssue):
        raise preset_problem(config, result)
    return result


def created(config: ServerConfig, response: Response, result: Preset | ValidationIssue) -> Preset:
    """A new preset, with its URL in ``Location``."""
    preset = stored(config, result)
    response.headers["Location"] = f"/api/presets/{preset.id}"
    return preset


class PresetList(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    presets: list[Preset]
    """Built-ins first, in their order, then the user presets."""
    default_id: str
    """The preset a new job uses."""


class PresetCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    template: JobTemplate
    name: str
    category: str = "Custom"
    description: str = ""


class PresetDiffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    template: JobTemplate
    preset_id: str


class DefaultsPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    audio_defaults: AudioDefaults
    subtitle_defaults: SubtitleDefaults
    source_ids: list[str]
    container: Container | None = None
    """The output container the codec rules check against; ``null``: a new template's."""


class RenamedPreset(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    name: str
    """The name in the file."""
    new_name: str
    """The name it was stored under."""


class PresetImportReport(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    imported: list[Preset]
    """The presets as stored, with their new id or name."""
    renamed: list[RenamedPreset]
    replaced: list[str]
    """Names of user presets that were overwritten."""
    skipped: list[str]
    """Names that were not imported: a clash with ``skip``, or a damaged or newer preset
    (see ``issues``)."""
    issues: list[ValidationIssue]


class PresetExportDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    document: dict[str, Any]
    """The export file: save it as it is."""
    issues: list[ValidationIssue]
    """One ``preset.newer_version`` warning for each preset of a newer Reframe in it."""


@router.get("/presets", name="list")
async def list_presets(reframe: ReframeDep) -> PresetList:
    """Every preset and the default."""
    return PresetList(presets=reframe.presets.list(), default_id=reframe.presets.default().id)


@router.post("/presets", status_code=201)
async def create(
    body: PresetCreateRequest, reframe: ReframeDep, config: ConfigDep, response: Response
) -> Preset:
    """Save a template as a new user preset."""
    jail_naming(config, body.template.naming)
    result = await reframe.presets.create(
        body.template, body.name, category=body.category, description=body.description
    )
    return created(config, response, result)


@router.get("/presets/export")
async def export(
    reframe: ReframeDep, ids: Annotated[list[str] | None, Query()] = None
) -> PresetExportDocument:
    """The export file of the presets with ``ids`` (unknown ids are left out); without
    ``ids``, every user preset."""
    result = reframe.presets.export(ids)
    return PresetExportDocument(document=result.document(), issues=result.issues)


@router.post(
    "/presets/import",
    name="import",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": {"type": "object"}}},
        }
    },
)
async def import_presets(
    request: Request,
    reframe: ReframeDep,
    config: ConfigDep,
    on_conflict: ConflictPolicy = "rename",
) -> PresetImportReport:
    """Import a preset export file (at most 4 MiB). ``on_conflict``: ``rename`` gives a
    clashing preset a new name, ``replace`` overwrites the user preset, ``skip`` leaves it out.
    What was refused is in ``issues``."""
    data = _import_document(await _read_limited(request))
    _jail_import(config, data)
    result = await reframe.presets.import_(data, on_conflict)
    return PresetImportReport(
        imported=result.imported,
        renamed=[RenamedPreset(name=old, new_name=new) for old, new in result.renamed],
        replaced=result.replaced,
        skipped=result.skipped,
        issues=[shown(config, issue) for issue in result.issues],
    )


@router.post("/presets/diff")
async def diff(
    body: PresetDiffRequest, reframe: ReframeDep, config: ConfigDep
) -> list[FieldChange]:
    """What the template changes against the preset (the "modified" marker)."""
    jail_naming(config, body.template.naming)
    changes = reframe.presets.diff(body.template, body.preset_id)
    if changes is None:
        raise ProblemError(404, "preset.not_found", f"No preset {body.preset_id}")
    return changes


@router.post("/presets/defaults/preview")
async def preview_defaults(
    body: DefaultsPreviewRequest, reframe: ReframeDep, registry: SourcesDep
) -> list[TrackDraft]:
    """What the audio and subtitle defaults do with each source, in the order of
    ``source_ids``: one decision per source track, with the reason."""
    template = JobTemplate(
        audio_defaults=body.audio_defaults, subtitle_defaults=body.subtitle_defaults
    )
    sources = await sources_of(reframe, registry, body.source_ids)
    return [
        unwrap(await reframe.jobs.explain(source, template, container=body.container))
        for source in sources
    ]


@router.get("/presets/{preset_id}")
async def get(preset_id: str, reframe: ReframeDep) -> Preset:
    preset = reframe.presets.get(preset_id)
    if preset is None:
        raise ProblemError(404, "preset.not_found", f"No preset {preset_id}")
    return preset


@router.put("/presets/{preset_id}")
async def save(preset_id: str, body: Preset, reframe: ReframeDep, config: ConfigDep) -> Preset:
    """Create or replace the user preset ``preset_id`` (a rename is a save with a new name).
    The body's ``id`` must be ``preset_id``."""
    if body.id != preset_id:
        raise ProblemError(422, "presets.id_mismatch", "The preset's id is not the one in the URL")
    jail_template(config, body)
    return stored(config, await reframe.presets.save(body))


@router.delete("/presets/{preset_id}")
async def delete(preset_id: str, reframe: ReframeDep, config: ConfigDep) -> Preset:
    """Delete a user preset; the answer is the deleted preset. When it was the default, the
    built-in default is the default again."""
    return stored(config, await reframe.presets.delete(preset_id))


@router.post("/presets/{preset_id}/default")
async def set_default(preset_id: str, reframe: ReframeDep, config: ConfigDep) -> Preset:
    """Make the preset the default; the answer is the default now in effect."""
    return stored(config, await reframe.presets.set_default(preset_id))


async def _read_limited(request: Request) -> bytes:
    too_large = ProblemError(
        413, "presets.import_too_large", f"A preset file is at most {IMPORT_LIMIT} bytes"
    )
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > IMPORT_LIMIT:
            raise too_large
    return bytes(body)


def _import_document(raw: bytes) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError):
        data = None
    if not isinstance(data, dict):
        raise ProblemError(422, "presets.import_invalid", "The preset file is not a JSON object")
    return data


def _jail_import(config: ServerConfig, data: dict[str, Any]) -> None:
    """The naming folder of each preset in the file passes the write jail. A preset of
    another shape is left to the store, which refuses it."""
    presets = data.get("presets")
    for entry in presets if isinstance(presets, list) else ():
        naming = entry.get("naming") if isinstance(entry, dict) else None
        folder = naming.get("output_folder") if isinstance(naming, dict) else None
        if isinstance(folder, str):
            security.jail_write(config, folder)
