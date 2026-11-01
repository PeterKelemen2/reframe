"""External subtitle files with the real tools: ``/api/subtitles/inspect``, and the encoding
checks of ``/api/jobs/validate`` and the queue."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from reframe.models import JobDraft
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


async def test_a_file_without_events_says_so(api: Api) -> None:
    """ffprobe leaves nb_read_packets out when it read no packet."""
    api.use_real_tools()
    file = api.media / "Film.vtt"
    file.write_bytes(b"WEBVTT\n\n")
    answer = await inspect(api, file)
    assert (answer["format"], answer["events"]) == ("webvtt", 0)
    assert issue_codes(answer) == ["subtitle.no_events"]


async def test_a_fifo_named_like_a_subtitle_file_is_refused_at_once(api: Api) -> None:
    if sys.platform == "win32":
        pytest.skip("needs FIFOs")
    else:
        api.use_real_tools()
        fifo = api.media / "Film.srt"
        os.mkfifo(fifo)
        response = await asyncio.wait_for(
            api.client.post("/api/subtitles/inspect", json={"path": str(fifo)}), 10
        )
        assert (response.status_code, response.json()["code"]) == (404, "probe.not_a_file")


async def drafted(api: Api, fixture_media: Callable[[str], Path], *subtitles: Any) -> Any:
    """A job of the real ``multitrack`` that copies the video and has ``subtitles`` added."""
    film = api.add_fixture("multitrack", fixture_media)
    draft = await api.reframe.jobs.draft(film)
    assert isinstance(draft, JobDraft)
    job: dict[str, Any] = draft.job.model_dump(mode="json")
    job["output"]["path"] = str(api.output / "Film.mkv")
    job["video"]["passthrough"] = True
    job["subtitles"] += [{"source": source} for source in subtitles]
    return job


async def queue_ended(api: Api, job: dict[str, Any]) -> Any:
    response = await api.client.post("/api/queue", json={"jobs": [job]})
    assert response.status_code == 201, response.text
    [added] = response.json()
    if added["state"] == "failed":
        return added
    await api.client.post("/api/queue/start", json={"job_ids": [added["id"]]})
    [ended] = await asyncio.wait_for(api.reframe.queue.wait([added["id"]]), 60)
    return ended.model_dump(mode="json")


@pytest.mark.parametrize(
    ("data", "code"),
    [
        pytest.param(SRT.encode("cp1250"), "subtitle.charset_unknown", id="cp1250"),
        pytest.param(b"\xff\xfe" + SRT.encode("utf-16-le"), "subtitle.utf16", id="utf-16le"),
    ],
)
async def test_an_external_file_ffmpeg_would_write_broken_blocks_the_job(
    api: Api, fixture_media: Callable[[str], Path], data: bytes, code: str
) -> None:
    srt = api.media / "Film.hu.srt"
    srt.write_bytes(data)
    job = await drafted(api, fixture_media, {"path": str(srt), "language": "hu"})
    at = f"subtitles[{len(job['subtitles']) - 1}].source.charset"
    response = await api.client.post("/api/jobs/validate", json={"job": job})
    assert [(i["code"], i["severity"]) for i in response.json() if i["path"] == at] == [
        (code, "error")
    ]
    ended = await queue_ended(api, job)
    assert ended["state"] == "failed"
    assert [i["code"] for i in ended["issues"] if i["path"] == at] == [code]


async def test_a_chosen_encoding_writes_the_text_right(
    api: Api, fixture_media: Callable[[str], Path]
) -> None:
    srt = api.media / "Film.hu.srt"
    srt.write_bytes(SRT.encode("cp1250"))
    source = {"path": str(srt), "language": "hu", "charset": "CP1250"}
    job = await drafted(api, fixture_media, source)
    response = await api.client.post("/api/jobs/validate", json={"job": job})
    assert [i["code"] for i in response.json() if i["severity"] == "error"] == []
    ended = await queue_ended(api, job)
    assert ended["state"] == "done", ended["error"]
    ffmpeg = api.real_tools[0]
    assert ffmpeg is not None
    last = f"0:s:{len(job['subtitles']) - 1}"
    argv = [ffmpeg, "-v", "error", "-i", job["output"]["path"], "-map", last, "-f", "srt", "-"]
    done = await asyncio.to_thread(subprocess.run, argv, capture_output=True, timeout=60)
    assert "Árvíztűrő tükörfúrógép." in done.stdout.decode()
