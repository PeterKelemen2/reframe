"""The power routes. The session's PowerGuard fails any test that reaches a real power action."""

from __future__ import annotations

import pytest

from reframe_testing.server import Api

pytestmark = pytest.mark.anyio


async def test_the_pending_countdown_is_shown_and_cancelled(api: Api) -> None:
    assert (await api.client.get("/api/power")).json() == {"pending": None}
    countdown = api.reframe.power.schedule("sleep", reason="2 jobs done")
    pending = (await api.client.get("/api/power")).json()["pending"]
    assert (pending["countdown_id"], pending["action"]) == (countdown, "sleep")
    assert pending["seconds_left"] > 0
    cancel = await api.client.post("/api/power/cancel")
    assert (cancel.status_code, cancel.json()) == (200, {"cancelled": True})
    assert (await api.client.get("/api/power")).json() == {"pending": None}
    assert (await api.client.post("/api/power/cancel")).json() == {"cancelled": False}
