"""App settings. In web mode a client cannot choose which programs the server runs, and a
folder it sets must be below an output root."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from reframe.jsonpatch import apply_patch
from reframe.models import AppSettings, AppWarningEvent, FieldChange, JsonPatch, ToolPaths
from reframe_server import security
from reframe_server.api import api_router
from reframe_server.config import ServerConfig
from reframe_server.deps import ConfigDep, ReframeDep
from reframe_server.errors import ProblemError

router = api_router("settings")


class SettingsChange(BaseModel):
    """A settings change that took effect."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    settings: AppSettings
    """The settings now in effect."""
    changes: list[FieldChange]
    saved: bool
    """The file was written. ``False`` with no ``changes``: nothing changed."""
    warnings: list[AppWarningEvent]
    """Why the change was not saved (it is in effect until the server stops)."""


@router.get("/settings", name="get")
async def read(reframe: ReframeDep) -> AppSettings:
    return reframe.settings.get()


@router.put("/settings", name="update")
async def change(patch: JsonPatch, reframe: ReframeDep, config: ConfigDep) -> SettingsChange:
    """Change the settings with a JSON patch (RFC 6902), all or nothing. An invalid change is
    a 422 problem whose ``issues`` say why; nothing changes then."""
    current = reframe.settings.get()
    patched = _patched(current, patch)
    if patched is not None:
        _check(config, current, patched)
    update = await reframe.settings.update(patch)
    if update.issues:
        first = update.issues[0]
        raise ProblemError(422, first.code, first.message, issues=update.issues)
    return SettingsChange(
        settings=update.settings,
        changes=update.changes,
        saved=update.saved,
        warnings=update.warnings,
    )


def _patched(current: AppSettings, patch: JsonPatch) -> AppSettings | None:
    """The settings ``patch`` would give, to check before the update; ``None`` when it is not
    valid (the update then refuses it with the reason)."""
    try:
        return AppSettings.model_validate(apply_patch(current.model_dump(mode="json"), patch))
    except (RecursionError, ValueError):  # a bad op, a bad value, or nested far too deep
        return None


def _check(config: ServerConfig, old: AppSettings, new: AppSettings) -> None:
    if config.mode == "web" and _sets_a_program(old.tools, new.tools):
        raise ProblemError(
            403,
            "settings.tools_forbidden",
            "A web client cannot choose the programs the server runs",
            "Set REFRAME_FFMPEG / REFRAME_FFPROBE on the server instead.",
        )
    before = dict(_folders(old))
    for where, folder in _folders(new):
        if before.get(where) != folder:
            security.jail_write(config, folder)


def _sets_a_program(old: ToolPaths, new: ToolPaths) -> bool:
    # Removing an override ("Use bundled") lets discovery choose again: allowed.
    before, after = old.model_dump(mode="json"), new.model_dump(mode="json")
    return any(value is not None and before.get(name) != value for name, value in after.items())


def _folders(model: BaseModel, where: str = "") -> Iterator[tuple[str, Path]]:
    """Every folder of the settings but the tool paths, by its dotted name."""
    for name in type(model).model_fields:
        value = getattr(model, name)
        if isinstance(value, Path):
            yield f"{where}{name}", value
        elif isinstance(value, BaseModel) and not isinstance(value, ToolPaths):
            yield from _folders(value, f"{where}{name}.")
