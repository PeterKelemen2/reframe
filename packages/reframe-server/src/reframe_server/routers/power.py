"""The when-done power countdown: read it and cancel it. Only the queue starts one."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from reframe.models import PowerCountdownEvent
from reframe_server.api import api_router
from reframe_server.deps import ReframeDep

router = api_router("power")


class PowerState(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    pending: PowerCountdownEvent | None
    """The last event of the running countdown, or ``phase: executing`` while its action runs
    (too late to cancel); ``null``: neither."""


class PowerCancel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    cancelled: bool
    """``false``: no countdown was running, or its action already runs."""


@router.get("/power")
async def pending(reframe: ReframeDep) -> PowerState:
    """The pending when-done power action."""
    return PowerState(pending=reframe.power.pending)


@router.post("/power/cancel")
async def cancel(reframe: ReframeDep) -> PowerCancel:
    """Cancel the running countdown: its action never runs."""
    return PowerCancel(cancelled=reframe.power.cancel())
