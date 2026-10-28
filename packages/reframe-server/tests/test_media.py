"""The frame and clip files behind the signed URLs: ETag, byte ranges, access."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import Request

from reframe.preview.cache import PreviewCache
from reframe_server import security
from reframe_server.errors import ProblemError
from reframe_testing.server import Api

pytestmark = pytest.mark.anyio

KEY = "0123456789abcdef-1500-fedcba9876543210"
CLIP = "c" * 32
DATA = bytes(range(250)) * 4
HUGE = "9" * 5000
"""More digits than Python's ``int()`` takes from a string."""


def _frame(api: Api) -> bytes:
    png = b"\x89PNG\r\n\x1a\n" + b"pixels"
    file = PreviewCache(api.reframe.cache_dir).frame(KEY)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(png)
    return png


def _clip(api: Api) -> Path:
    file = PreviewCache(api.reframe.cache_dir).clip(CLIP, ".mp4")
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(DATA)
    return file


async def test_a_frame_is_served_with_its_key_as_etag(api: Api) -> None:
    png = _frame(api)
    response = await api.client.get(f"/api/preview/frames/{KEY}.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == png
    etag = response.headers["etag"]
    again = await api.client.get(f"/api/preview/frames/{KEY}.png", headers={"if-none-match": etag})
    assert (again.status_code, again.content) == (304, b"")


async def test_a_frame_not_in_the_cache_is_404(api: Api) -> None:
    _frame(api)
    response = await api.client.get(
        "/api/preview/frames/0123456789abcdef-1500-0000000000000000.png"
    )
    assert (response.status_code, response.json()["code"]) == (404, "preview.unknown_frame")


async def test_a_frame_evicted_after_the_lookup_is_404(
    api: Api, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def evicted(_key: str) -> Path:
        return tmp_path / "gone.png"

    monkeypatch.setattr(api.reframe.sources, "frame", evicted)
    response = await api.client.get(f"/api/preview/frames/{KEY}.png")
    assert (response.status_code, response.json()["code"]) == (404, "preview.unknown_frame")


@pytest.mark.parametrize("url", [f"/api/preview/frames/{KEY}.png", f"/api/preview/clips/{CLIP}"])
async def test_media_urls_need_media_access(api: Api, url: str) -> None:
    async def refuse(_request: Request) -> None:
        raise ProblemError(401, "auth.required", "Sign in")

    _frame(api)
    _clip(api)
    api.app.dependency_overrides[security.require_media_access] = refuse
    response = await api.anonymous.get(url)
    assert (response.status_code, response.json()["code"]) == (401, "auth.required")


@pytest.mark.parametrize(
    ("header", "status", "first", "last"),
    [
        (None, 200, 0, 999),
        ("bytes=0-99", 206, 0, 99),
        ("bytes=900-", 206, 900, 999),
        ("bytes=-100", 206, 900, 999),
        ("bytes=990-" + HUGE, 206, 990, 999),
        ("bytes=-" + HUGE, 206, 0, 999),
        ("bytes=0-1,5-6", 200, 0, 999),
        ("bytes=50-10", 200, 0, 999),
        ("bytes=-", 200, 0, 999),
    ],
)
async def test_a_clip_is_served_whole_or_as_one_byte_range(
    api: Api, header: str | None, status: int, first: int, last: int
) -> None:
    _clip(api)
    headers = {"range": header} if header is not None else {}
    response = await api.client.get(f"/api/preview/clips/{CLIP}", headers=headers)
    assert response.status_code == status
    assert response.content == DATA[first : last + 1]
    assert response.headers["content-length"] == str(last - first + 1)
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-type"] == "video/mp4"
    if status == 206:
        assert response.headers["content-range"] == f"bytes {first}-{last}/1000"


@pytest.mark.parametrize("header", ["bytes=1000-", f"bytes={HUGE}-", "bytes=-0"])
async def test_a_range_outside_the_clip_is_416(api: Api, header: str) -> None:
    _clip(api)
    response = await api.client.get(f"/api/preview/clips/{CLIP}", headers={"range": header})
    assert (response.status_code, response.json()["code"]) == (
        416,
        "preview.range_not_satisfiable",
    )
    assert response.headers["content-range"] == "bytes */1000"


@pytest.mark.parametrize("evicted", [False, True])
async def test_a_clip_not_in_the_cache_is_404(
    api: Api, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, evicted: bool
) -> None:
    if evicted:

        async def gone(_clip_id: str) -> Path:
            return tmp_path / "gone.mp4"

        monkeypatch.setattr(api.reframe.jobs, "preview_clip_path", gone)
    response = await api.client.get(f"/api/preview/clips/{CLIP}")
    assert (response.status_code, response.json()["code"]) == (404, "preview.unknown_clip")
