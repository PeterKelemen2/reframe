"""What a job's output gets, before it is encoded: ``jobs/type``, ``jobs/chapters``,
``jobs/chapters/export`` and ``jobs/tags``; and ``chapters/import``."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from reframe.models import JobDraft, JobState, MediaSource
from reframe_testing import fake_tools as ft
from reframe_testing.server import PROBE_RULE, ROOT, Api, ApiFactory

pytestmark = pytest.mark.anyio

PROBES = ROOT / "testdata" / "probes" / "fixtures"
FAST_X264: dict[str, Any] = {
    "encoder": "libx264", "preset": "ultrafast", "profile": None, "tune": None, "level": None,
    "bit_depth": 8, "advanced": {}, "custom_params": "",
}  # fmt: skip
Media = Callable[[str], Path]
DASH = " \N{EN DASH} "


def serve(api: Api, recordings: dict[Path, str]) -> None:
    """The fake ffprobe answers for each path with its recording, for the rest with
    ``multitrack``."""
    rules = [
        ft.Rule(
            tool="ffprobe",
            argv_has=["-show_streams", str(path)],
            actions=[{"stdout_file": str(PROBES / f"{recording}.json")}],
        )
        for path, recording in recordings.items()
    ]
    api.fake.set_scenario(ft.Scenario([*rules, PROBE_RULE]))


async def recorded(api: Api, name: str, recording: str, *, root: Path | None = None) -> Path:
    path = (root or api.media) / name
    path.write_bytes(b"not really matroska")
    serve(api, {path: recording})
    assert isinstance(await api.reframe.sources.probe(path), MediaSource)
    return path


async def drafted(api: Api, path: Path, *, remux: bool = False, in_place: bool = False) -> Any:
    if remux:
        draft = await api.reframe.jobs.draft_remux(path, edit_in_place=in_place)
    else:
        draft = await api.reframe.jobs.draft(path)
    assert isinstance(draft, JobDraft)
    job: dict[str, Any] = draft.job.model_dump(mode="json")
    if not in_place:
        job["output"]["path"] = str(api.output / f"{path.stem}.mkv")
    return job


def ok(response: httpx.Response) -> Any:
    assert response.status_code == 200, response.text
    return response.json()


# ---- jobs/type


async def test_an_encode_says_why_and_why_it_cannot_be_edited_in_place(api: Api) -> None:
    path = await recorded(api, "Show S01E01.mkv", "multitrack.mkv")
    answer = ok(await api.client.post("/api/jobs/type", json={"job": await drafted(api, path)}))
    assert answer["job_type"] == "encode"
    assert answer["reason"].startswith("Encode: the video is encoded with ")
    blockers = answer["in_place_blockers"]
    assert blockers[0] == "Show S01E01.mkv is in a folder that this server may only read"
    assert "the video is encoded" in blockers


async def test_a_remux_says_that_every_track_is_copied(api: Api) -> None:
    path = await recorded(api, "Show S01E01.mkv", "multitrack.mkv")
    answer = ok(
        await api.client.post("/api/jobs/type", json={"job": await drafted(api, path, remux=True)})
    )
    assert answer["job_type"] == "remux"
    assert answer["reason"] == (
        "Remux: the video and every audio and subtitle track are copied without re-encoding."
    )


async def test_a_flags_only_change_edited_in_place_is_a_metadata_edit(
    make_api: ApiFactory, tmp_path: Path
) -> None:
    """A source in a folder that is a media and an output root may be edited in place."""
    async with make_api(media_roots=[tmp_path / "media", tmp_path / "output"]) as api:
        path = await recorded(api, "Show.mkv", "multitrack.mkv", root=api.output)
        job = await drafted(api, path, remux=True, in_place=True)
        job["audio"][0]["metadata"]["commentary"] = True
        answer = ok(await api.client.post("/api/jobs/type", json={"job": job}))
    assert answer == {
        "job_type": "metadata_edit",
        "reason": "Metadata edit: only the track metadata changes, so mkvpropedit edits "
        "Show.mkv in place, in seconds.",
        "in_place_blockers": [],
    }


async def test_an_in_place_edit_of_a_source_the_server_may_only_read_is_not_refused(
    api: Api,
) -> None:
    """The answer says why it cannot be a metadata edit; validation gives the issue."""
    path = await recorded(api, "Show S01E01.mkv", "multitrack.mkv")
    job = await drafted(api, path, remux=True, in_place=True)
    answer = ok(await api.client.post("/api/jobs/type", json={"job": job}))
    blocker = "Show S01E01.mkv is in a folder that this server may only read"
    assert answer["job_type"] == "remux"
    assert answer["reason"].endswith(f"It cannot be edited in place: {blocker}.")
    assert answer["in_place_blockers"] == [blocker]


async def test_a_source_that_is_not_mkv_is_the_first_blocker(api: Api) -> None:
    path = await recorded(api, "Clip.mp4", "vfr.mp4")
    answer = ok(
        await api.client.post("/api/jobs/type", json={"job": await drafted(api, path, remux=True)})
    )
    assert answer["in_place_blockers"][:2] == [
        "the source is not an MKV file",
        "Clip.mp4 is in a folder that this server may only read",
    ]


# ---- jobs/chapters and export


def chapters_of(answer: dict[str, Any]) -> list[tuple[Any, ...]]:
    return [
        (c["number"], c["start"], c["end"], c["name"], c["source_name"], c["source_index"])
        for c in answer["chapters"]
    ]


async def test_a_chapter_range_with_renamed_chapters_names_their_source_slots(api: Api) -> None:
    path = await recorded(api, "Film.mkv", "chapters.mkv")
    job = await drafted(api, path)
    job["range"] = {"kind": "chapters", "start": 2, "end": 3}
    job["chapters"]["names"] = ["", "Erste", "", "End"]
    answer = ok(await api.client.post("/api/jobs/chapters", json={"job": job}))
    assert (answer["origin"], answer["reason"]) == ("source", "")
    assert chapters_of(answer) == [
        (1, 0.0, 1.5, "Erste", "Part One", 1),
        (2, 1.5, 3.0, "Part Two", "Part Two", 2),
    ]


async def test_generated_chapters_have_no_source_slot(api: Api) -> None:
    path = await recorded(api, "Clip.mkv", "multitrack.mkv")
    job = await drafted(api, path)
    job["chapters"]["generate_every"] = 1.5 / 60
    job["chapters"]["names"] = ["Intro"]
    answer = ok(await api.client.post("/api/jobs/chapters", json={"job": job}))
    assert answer["origin"] == "generated"
    assert chapters_of(answer) == [
        (1, 0.0, 1.5, "Intro", None, None),
        (2, 1.5, 3.0, "Chapter 2", None, None),
        (3, 3.0, 4.021, "Chapter 3", None, None),
    ]


async def test_chapter_markers_off_give_none_with_the_reason(api: Api) -> None:
    path = await recorded(api, "Film.mkv", "chapters.mkv")
    job = await drafted(api, path)
    job["chapters"]["enabled"] = False
    answer = ok(await api.client.post("/api/jobs/chapters", json={"job": job}))
    assert answer == {"origin": "none", "chapters": [], "reason": "Create chapter markers is off."}


async def test_export_writes_the_output_chapters_named_after_the_output(api: Api) -> None:
    path = await recorded(api, "Film.mkv", "chapters.mkv")
    job = await drafted(api, path)
    job["output"]["path"] = str(api.output / "Film (2001).mkv")
    job["chapters"]["names"] = ["Intro, part 1"]
    answer = ok(
        await api.client.post("/api/jobs/chapters/export", json={"job": job, "format": "csv"})
    )
    assert answer == {
        "format": "csv",
        "file_name": "Film (2001).chapters.csv",
        "content": '1,"Intro, part 1"\n2,Part One\n3,Part Two\n4,Credits\n',
    }


async def test_export_of_a_job_without_chapters_is_a_problem(api: Api) -> None:
    path = await recorded(api, "Clip.mkv", "multitrack.mkv")
    job = await drafted(api, path)
    response = await api.client.post(
        "/api/jobs/chapters/export", json={"job": job, "format": "xml"}
    )
    problem = response.json()
    assert (response.status_code, problem["code"]) == (422, "chapters.none")
    assert problem["detail"] == "The source has no chapters."


@pytest.mark.parametrize("chapter_format", ["csv", "ogm", "xml"])
async def test_an_exported_file_is_imported_with_the_same_names(
    api: Api, chapter_format: str
) -> None:
    path = await recorded(api, "Film.mkv", "chapters.mkv")
    job = await drafted(api, path)
    names = ['Árvíztűrő, "tükör"', "Part = 1; #2", "<Two> & more", "End"]
    job["chapters"]["names"] = names
    exported = ok(
        await api.client.post(
            "/api/jobs/chapters/export", json={"job": job, "format": chapter_format}
        )
    )
    file = api.media / exported["file_name"]
    file.write_text(exported["content"], encoding="utf-8")
    imported = ok(await api.client.post("/api/chapters/import", json={"path": str(file)}))
    assert imported["format"] == chapter_format
    assert [c["name"] for c in imported["chapters"]] == names
    assert imported["issues"] == []
    starts = None if chapter_format == "csv" else 0.0
    assert imported["chapters"][0]["start"] == starts


# ---- jobs/tags


@pytest.mark.parametrize(
    ("name", "title"),
    [
        (
            "The.Sopranos.S03E02.Proshai.Livushka.1080p.BluRay.x264-GRP.mkv",
            f"The.Sopranos{DASH}S03E02",
        ),
        ("Hacksaw.Ridge.2016.2160p.UHD.BluRay.x265-GRP.mkv", "Hacksaw.Ridge"),
    ],
)
async def test_a_title_template_renders_the_episode_code_only_for_an_episode(
    api: Api, name: str, title: str
) -> None:
    path = await recorded(api, name, "multitrack.mkv")
    job = await drafted(api, path)
    job["tags"]["title"] = f"{{name}}<{DASH}S{{season:02}}E{{episode:02}}>"
    answer = ok(await api.client.post("/api/jobs/tags", json={"job": job}))
    assert answer["values"]["title"] == title
    assert answer["issues"] == []


async def test_tags_show_the_source_values_and_the_template_errors(api: Api) -> None:
    path = await recorded(api, "Film.mkv", "chapters.mkv")
    job = await drafted(api, path)
    job["tags"] = {"title": None, "genre": "{nme}", "comment": "Plain", "plot": "{name"}
    answer = ok(await api.client.post("/api/jobs/tags", json={"job": job}))
    assert answer["values"] == {
        "title": None, "actors": None, "director": None, "release_date": None,
        "comment": "Plain", "genre": "", "description": None, "plot": "{name",
    }  # fmt: skip
    assert answer["source"]["title"] == "Reframe chapters fixture"
    assert answer["source"]["genre"] is None
    unknown, syntax = answer["issues"]
    assert (unknown["code"], unknown["path"]) == ("naming.unknown_variable", "tags.genre")
    assert unknown["fixes"][0]["patch"] == [{"op": "add", "path": "/tags/genre", "value": "{name}"}]
    assert (syntax["code"], syntax["path"]) == ("naming.template_syntax", "tags.plot")


async def test_validation_reports_the_tag_errors_that_jobs_tags_shows(api: Api) -> None:
    path = await recorded(api, "Film.mkv", "chapters.mkv")
    job = await drafted(api, path)
    job["tags"] = {"genre": "{nme}", "plot": "{name", "release_date": "{year:%Y}"}
    shown = ok(await api.client.post("/api/jobs/tags", json={"job": job}))["issues"]
    issues = ok(await api.client.post("/api/jobs/validate", json={"job": job}))
    assert [i for i in issues if i["path"].startswith("tags.")] == shown
    assert {(i["code"], i["path"], i["severity"]) for i in shown} == {
        ("naming.unknown_variable", "tags.genre", "error"),
        ("naming.template_syntax", "tags.plot", "error"),
        ("naming.bad_format_spec", "tags.release_date", "error"),
    }
    [queued] = (await api.client.post("/api/queue", json={"jobs": [job]})).json()
    assert queued["state"] == "failed"


@pytest.mark.parametrize(
    ("value", "code"),
    [("a\0b", "metadata.nul_character"), ("x" * 200_000, "metadata.tag_too_long")],
    ids=["nul", "200000-characters"],
)
async def test_a_tag_the_command_line_cannot_carry_is_an_error(
    api: Api, value: str, code: str
) -> None:
    path = await recorded(api, "Film.mkv", "chapters.mkv")
    job = await drafted(api, path)
    job["tags"]["description"] = value
    issues = ok(await api.client.post("/api/jobs/validate", json={"job": job}))
    assert [(i["code"], i["severity"]) for i in issues if i["path"] == "tags.description"] == [
        (code, "error")
    ]
    [queued] = (await api.client.post("/api/queue", json={"jobs": [job]})).json()
    assert queued["state"] == "failed"


# ---- chapters/import


@pytest.mark.parametrize(
    ("text", "chapter_format", "expected"),
    [
        ('1,Opening\r\n2,"Part, one"\r\n', "csv", [(None, "Opening"), (None, "Part, one")]),
        (
            "CHAPTER01=00:00:00.000\nCHAPTER01NAME=Opening\nCHAPTER02=00:01:02.500\n"
            "CHAPTER02NAME=Part one\n",
            "ogm",
            [(0.0, "Opening"), (62.5, "Part one")],
        ),
        (
            "<?xml version='1.0'?><Chapters><EditionEntry><ChapterAtom>"
            "<ChapterTimeStart>00:00:01.000000000</ChapterTimeStart><ChapterDisplay>"
            "<ChapterString>Opening</ChapterString></ChapterDisplay></ChapterAtom>"
            "</EditionEntry></Chapters>",
            "xml",
            [(1.0, "Opening")],
        ),
    ],
)
async def test_import_tells_the_format_from_the_content(
    api: Api, text: str, chapter_format: str, expected: list[tuple[float | None, str]]
) -> None:
    file = api.media / "chapters.txt"
    file.write_text(text, encoding="utf-8")
    answer = ok(await api.client.post("/api/chapters/import", json={"path": str(file)}))
    assert answer["format"] == chapter_format
    assert [(c["start"], c["name"]) for c in answer["chapters"]] == expected


async def test_a_file_that_is_not_a_chapter_file_is_a_problem_with_the_line(api: Api) -> None:
    file = api.media / "chapters.txt"
    file.write_text("CHAPTER01=00:00:00.000\nCHAPTER01NAME=One\nnonsense\n", encoding="utf-8")
    response = await api.client.post("/api/chapters/import", json={"path": str(file)})
    problem = response.json()
    assert (response.status_code, problem["code"]) == (422, "chapters.invalid")
    assert problem["detail"].startswith("Line 3: ")


async def test_a_chapter_file_that_cannot_be_read_is_a_problem(api: Api) -> None:
    response = await api.client.post(
        "/api/chapters/import", json={"path": str(api.media / "gone.xml")}
    )
    problem = response.json()
    assert (response.status_code, problem["code"]) == (422, "chapters.unreadable")
    assert problem["detail"] == "The file does not exist."


async def test_the_format_named_in_the_request_is_used(api: Api) -> None:
    file = api.media / "chapters.csv"
    file.write_text("CHAPTER01=00:00:00.000\n", encoding="utf-8")
    response = await api.client.post(
        "/api/chapters/import", json={"path": str(file), "format": "csv"}
    )
    assert (response.status_code, response.json()["code"]) == (422, "chapters.invalid")


# ---- against the real tools


async def encode(api: Api, job: dict[str, Any]) -> MediaSource:
    [added] = (await api.client.post("/api/queue", json={"jobs": [job]})).json()
    await api.client.post("/api/queue/start", json={"job_ids": [added["id"]]})
    [ended] = await asyncio.wait_for(api.reframe.queue.wait([added["id"]]), 60)
    assert ended.state is JobState.DONE, ended.error
    out = await api.reframe.sources.probe(job["output"]["path"], use_cache=False)
    assert isinstance(out, MediaSource)
    return out


def _range(start: int, end: int) -> Callable[[dict[str, Any]], None]:
    def change(job: dict[str, Any]) -> None:
        job["range"] = {"kind": "chapters", "start": start, "end": end}

    return change


def _times(start: float, end: float) -> Callable[[dict[str, Any]], None]:
    def change(job: dict[str, Any]) -> None:
        job["range"] = {"kind": "time", "start": start, "end": end}

    return change


def _names(*names: str) -> Callable[[dict[str, Any]], None]:
    def change(job: dict[str, Any]) -> None:
        job["chapters"]["names"] = list(names)

    return change


def _every(minutes: float) -> Callable[[dict[str, Any]], None]:
    def change(job: dict[str, Any]) -> None:
        job["chapters"]["generate_every"] = minutes

    return change


@pytest.mark.needs_ffmpeg
@pytest.mark.parametrize(
    ("fixture", "changes"),
    [
        pytest.param("chapters", [_names("Intro", "", "Zwei; #2 = b", "End")], id="renamed"),
        pytest.param("chapters", [_range(2, 3), _names("", "Erste")], id="chapter-range"),
        pytest.param("chapters", [_times(1.2, 3.2)], id="time-range-copied"),
        pytest.param("multitrack", [_every(1.5 / 60)], id="generated"),
    ],
)
async def test_the_chapters_route_equals_the_chapters_of_the_encoded_file(
    api: Api,
    fixture_media: Media,
    fixture: str,
    changes: list[Callable[[dict[str, Any]], None]],
) -> None:
    path = api.add_fixture(fixture, fixture_media)
    job = await drafted(api, path)
    job["video"].update(FAST_X264)
    job["subtitles"] = []
    for change in changes:
        change(job)
    answer = ok(await api.client.post("/api/jobs/chapters", json={"job": job}))
    out = await encode(api, job)
    assert answer["chapters"]
    assert [
        (c["name"] or None, round(c["start"], 2), round(c["end"], 2)) for c in answer["chapters"]
    ] == [(c.title, round(c.start, 2), round(c.end, 2)) for c in out.chapters]


@pytest.mark.needs_ffmpeg
@pytest.mark.skipif(shutil.which("mkvmerge") is None, reason="needs mkvmerge")
@pytest.mark.parametrize("chapter_format", ["ogm", "xml"])
async def test_mkvmerge_reads_the_exported_ogm_and_xml_files(
    api: Api, fixture_media: Media, chapter_format: str
) -> None:
    path = api.add_fixture("chapters", fixture_media)
    job = await drafted(api, path)
    job["chapters"]["names"] = ["Árvíztűrő", "Part = 1; #2", "<Two> & more"]
    exported = ok(
        await api.client.post(
            "/api/jobs/chapters/export", json={"job": job, "format": chapter_format}
        )
    )
    file = api.output / exported["file_name"]
    file.write_text(exported["content"], encoding="utf-8")
    merged = api.output / "merged.mkv"
    argv = ["mkvmerge", "-q", "-o", str(merged), "--chapters", str(file), "--no-chapters"]
    await asyncio.to_thread(subprocess.run, [*argv, str(path)], check=True, timeout=60)
    out = await api.reframe.sources.probe(merged, use_cache=False)
    assert isinstance(out, MediaSource)
    assert [(c.title, round(c.start, 2)) for c in out.chapters] == [
        ("Árvíztűrő", 0.0),
        ("Part = 1; #2", 1.0),
        ("<Two> & more", 2.5),
        ("Credits", 4.0),
    ]
