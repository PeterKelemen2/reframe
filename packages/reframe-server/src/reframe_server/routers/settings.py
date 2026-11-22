"""App settings. In web mode a client cannot choose which programs the server runs or pass
options to a hardware device, and a folder it sets must be below an output root."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import PurePath

from pydantic import BaseModel, ConfigDict

from reframe.models import (
    AppSettings,
    AppWarningEvent,
    FieldChange,
    JsonPatch,
    Severity,
    ToolPaths,
    ValidationIssue,
)
from reframe.queue.whendone import POWER_LABELS
from reframe.tools import ENV_VARS
from reframe_server import security
from reframe_server.api import api_router
from reframe_server.config import ServerConfig
from reframe_server.deps import ConfigDep, ReframeDep
from reframe_server.errors import ProblemError

router = api_router("settings")

# FFmpeg reads device options after a comma in the device text (`driver=` makes libva load
# a library by a relative name), so a web client may name only a render node.
_RENDER_NODE = re.compile(r"/dev/dri/renderD[0-9]+")


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
    update = await reframe.settings.update(patch, check=lambda old, new: _check(config, old, new))
    if update.issues:
        first = update.issues[0]
        raise ProblemError(422, first.code, first.message, issues=update.issues)
    return SettingsChange(
        settings=update.settings,
        changes=update.changes,
        saved=update.saved,
        warnings=update.warnings,
    )


def check_when_done(config: ServerConfig, old: AppSettings, new: AppSettings) -> None:
    """:raises ProblemError: 403 when the patch sets a when-done action that this server cannot
    carry out (``quit`` in web mode, ``sleep`` and ``shutdown`` in a container)."""
    action = new.queue.when_done
    reason = config.unavailable_when_done.get(action)
    if reason is None or action == old.queue.when_done:
        return
    label = POWER_LABELS[action][1]
    message = f"When done: “{label}” is not available here"
    issue = ValidationIssue(
        severity=Severity.ERROR,
        code="queue.when_done_unavailable",
        path="queue.when_done",
        message=f"{message}. {reason}",
    )
    raise ProblemError(403, issue.code, message, reason, issues=[issue])


def _check(config: ServerConfig, old: AppSettings, new: AppSettings) -> None:
    """Runs under the store's lock on the settings the patch was applied to, so a concurrent
    change cannot slip a patch past it. A value the patch does not change is not checked."""
    check_when_done(config, old, new)
    if config.mode == "web":
        programs = _programs_set(old.tools, new.tools)
        if programs:
            variables = [variable for tool, variable in ENV_VARS.items() if tool in programs]
            raise ProblemError(
                403,
                "settings.tools_forbidden",
                "A web client cannot choose the programs the server runs",
                f"Set {' / '.join(variables)} on the server instead."
                if variables
                else "Tool paths are set on the server.",
            )
        device = (new.encoders.vaapi_device or "").strip()
        changed = new.encoders.vaapi_device != old.encoders.vaapi_device
        if changed and device and not _RENDER_NODE.fullmatch(device):
            raise ProblemError(
                403,
                "settings.vaapi_device_forbidden",
                "A web client can only choose a VAAPI render node",
                "Name a render node such as /dev/dri/renderD128, or none to test every node.",
            )
    before = dict(_folders(old))
    for where, folder in _folders(new):
        if before.get(where) != folder:
            security.jail_write(config, folder)


def _programs_set(old: ToolPaths, new: ToolPaths) -> set[str]:
    # Removing an override ("Use bundled") lets discovery choose again: allowed.
    before, after = old.model_dump(mode="json"), new.model_dump(mode="json")
    return {
        name for name, value in after.items() if value is not None and before.get(name) != value
    }


def _folders(settings: AppSettings) -> Iterator[tuple[str, PurePath]]:
    """Every folder of the settings but the tool paths, by its dotted name."""
    return (
        (".".join(map(str, where)), path)
        for where, path in security.model_paths(settings, ())
        if where[0] != "tools"
    )
