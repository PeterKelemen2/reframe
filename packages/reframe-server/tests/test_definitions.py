"""The definitions document with its ETag, and the option search."""

from __future__ import annotations

import pytest

from reframe_testing.server import Api

pytestmark = pytest.mark.anyio


async def test_operation_ids(api: Api) -> None:
    paths = (await api.client.get("/api/openapi.json")).json()["paths"]
    assert paths["/api/definitions"]["get"]["operationId"] == "definitions_get"
    options = paths["/api/definitions/encoders/{encoder_id}/options"]["get"]
    assert options["operationId"] == "definitions_search_options"


async def test_definitions_hold_what_the_editor_needs(api: Api) -> None:
    response = await api.client.get("/api/definitions")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.headers["etag"].startswith('"')
    body = response.json()
    x265 = body["definitions"]["video_encoders"]["libx265"]
    assert "bframes" in [option["key"] for option in x265["options"]]
    assert {"mkv", "mp4", "webm"} <= set(body["definitions"]["containers"])
    assert "deinterlace" in body["definitions"]["filters"]
    assert "episode_code" in [variable["name"] for variable in body["naming_variables"]]


@pytest.mark.parametrize(
    ("if_none_match", "status"),
    [('"stale", W/{etag}', 304), ("*", 304), ('"stale"', 200)],
)
async def test_a_client_with_the_current_copy_gets_304(
    api: Api, if_none_match: str, status: int
) -> None:
    etag = (await api.client.get("/api/definitions")).headers["etag"]
    response = await api.client.get(
        "/api/definitions", headers={"If-None-Match": if_none_match.format(etag=etag)}
    )
    assert response.status_code == status
    assert response.headers["etag"] == etag
    assert (response.content == b"") is (status == 304)


async def test_option_search(api: Api) -> None:
    every = (await api.client.get("/api/definitions/encoders/libx265/options")).json()
    found = (
        await api.client.get("/api/definitions/encoders/libx265/options", params={"q": "b-frames"})
    ).json()
    assert found[0]["key"] == "bframes"
    assert 0 < len(found) < len(every)


async def test_options_of_an_unknown_encoder_are_404(api: Api) -> None:
    response = await api.client.get("/api/definitions/encoders/nope/options")
    assert response.status_code == 404
    assert response.json()["code"] == "definitions.unknown_encoder"
