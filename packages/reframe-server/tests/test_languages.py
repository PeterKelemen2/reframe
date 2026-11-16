"""The language list of the picker."""

from __future__ import annotations

import pytest

from reframe_testing.server import Api

pytestmark = pytest.mark.anyio


async def test_the_language_list(api: Api) -> None:
    response = await api.client.get("/api/languages")
    assert response.status_code == 200
    languages = {entry["tag"]: entry for entry in response.json()["languages"]}
    hungarian = languages["hu"]
    assert (hungarian["iso639_2b"], hungarian["iso639_2t"], hungarian["native_name"]) == (
        "hun",
        "hun",
        "magyar",
    )
    assert languages["pt-BR"]["variant"] is True


async def test_a_client_with_the_current_list_gets_304(api: Api) -> None:
    etag = (await api.client.get("/api/languages")).headers["etag"]
    response = await api.client.get("/api/languages", headers={"If-None-Match": etag})
    assert response.status_code == 304
