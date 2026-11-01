"""``/api/subtitles/inspect``: an external subtitle file read with the real ffprobe."""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from reframe_testing.server import Api

pytestmark = [pytest.mark.anyio, pytest.mark.needs_ffmpeg]

SRT = (
    "1\n00:00:00,500 --> 00:00:01,800\nÁrvíztűrő tükörfúrógép.\n\n"
    "2\n00:00:02,000 --> 00:00:03,600\nŐszi szél, ősz.\n\n"
    "3\n00:00:04,000 --> 00:00:05,000\nHárom.\n"
)


async def inspect(api: Api, file: Path) -> Any:
    response = await api.client.post("/api/subtitles/inspect", json={"path": str(file)})
    assert response.status_code == 200, response.text
    return response.json()


def issue_codes(answer: dict[str, Any]) -> list[str]:
    return [issue["code"] for issue in answer["issues"]]


@pytest.mark.parametrize(
    ("data", "charset", "codes"),
    [
        pytest.param(SRT.encode("utf-8"), "UTF-8", [], id="utf-8"),
        pytest.param(b"\xef\xbb\xbf" + SRT.encode("utf-8"), "UTF-8", [], id="utf-8-bom"),
        pytest.param(SRT.encode("cp1250"), None, ["subtitle.charset_unknown"], id="cp1250"),
        pytest.param(
            b"\xff\xfe" + SRT.encode("utf-16-le"), "UTF-16LE", ["subtitle.utf16"], id="utf-16le"
        ),
    ],
)
async def test_an_srt_file_gives_its_format_events_and_encoding(
    api: Api, data: bytes, charset: str | None, codes: list[str]
) -> None:
    api.use_real_tools()
    file = api.media / "Film.hu.srt"
    file.write_bytes(data)
    answer = await inspect(api, file)
    assert (answer["format"], answer["bitmap"], answer["events"]) == ("subrip", False, 3)
    assert answer["charset"] == charset
    assert issue_codes(answer) == codes


async def test_an_ass_and_an_ssa_file_are_ass(
    api: Api, fixture_media: Callable[[str], Path]
) -> None:
    ass = api.add_fixture("text-subs-ass", fixture_media)
    ssa = api.media / "Film.ssa"
    ssa.write_bytes(ass.read_bytes())
    for file in (ass, ssa):
        answer = await inspect(api, file)
        assert (answer["format"], answer["charset"], answer["events"]) == ("ass", "UTF-8", 3)
        assert answer["issues"] == []


async def test_a_sup_file_is_a_bitmap_counted_in_display_sets(
    api: Api, fixture_media: Callable[[str], Path]
) -> None:
    """The subtitle scan's count: 12 display sets (6 events, each shown and cleared)."""
    source = api.add_fixture("pgs", fixture_media)
    sup = api.media / "Film.sup"
    ffmpeg = api.real_tools[0]
    assert ffmpeg is not None
    argv = [ffmpeg, "-v", "error", "-i", str(source), "-map", "0:1", "-c", "copy", "-f", "sup"]
    await asyncio.to_thread(subprocess.run, [*argv, str(sup)], check=True, timeout=60)
    answer = await inspect(api, sup)
    assert answer == {
        "path": str(sup), "format": "hdmv_pgs_subtitle", "bitmap": True, "charset": None,
        "events": 12, "issues": [],
    }  # fmt: skip


async def test_a_file_named_for_another_format_says_so(api: Api) -> None:
    api.use_real_tools()
    file = api.media / "Film.srt"
    file.write_text("WEBVTT\n\n00:00.500 --> 00:01.800\nHello\n", encoding="utf-8")
    answer = await inspect(api, file)
    assert answer["format"] == "webvtt"
    assert issue_codes(answer) == ["subtitle.format_mismatch"]


@pytest.mark.parametrize(
    ("name", "data"),
    [("notes.txt", b"1\n00:00:00,500 --> 00:00:01,800\nHello\n"), ("Film.srt", b"no subtitles")],
)
async def test_a_file_a_job_cannot_take_is_unsupported(api: Api, name: str, data: bytes) -> None:
    api.use_real_tools()
    file = api.media / name
    file.write_bytes(data)
    response = await api.client.post("/api/subtitles/inspect", json={"path": str(file)})
    assert (response.status_code, response.json()["code"]) == (422, "subtitles.unsupported")


async def test_a_missing_file_is_not_found(api: Api) -> None:
    api.use_real_tools()
    response = await api.client.post(
        "/api/subtitles/inspect", json={"path": str(api.media / "gone.srt")}
    )
    assert (response.status_code, response.json()["code"]) == (404, "probe.not_found")
