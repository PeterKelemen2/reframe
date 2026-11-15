"""Metadata edits and the post-mux fix-up through the real queue and Reframe's own Matroska
header writer, on a copy of the ``multitrack`` fixture, with no MKVToolNix program for the
product to find. MediaInfo is off, so the BCP 47 languages that the re-probe shows come from
Reframe's own Matroska reader. MKVToolNix is only the oracle (``needs_mkvtoolnix``): the same
edit by mkvpropedit reads back the same in ``mkvmerge -J``."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from reframe.metadata import header
from reframe.metadata.header import HeaderEditResult
from reframe.models import (
    EncodePlan,
    HeaderEdit,
    JobDraft,
    JobSettings,
    JobState,
    MediaSource,
    QueueJob,
    resolve_argv,
)
from reframe.probe import mediainfo
from reframe.probe.matroska import read_matroska
from reframe.service import Reframe
from reframe.tools import ENV_VARS
from reframe_testing import media
from reframe_testing.mkvtoolnix import mkvtoolnix_tool

pytestmark = [pytest.mark.needs_ffmpeg, pytest.mark.anyio]

#: The time limit of a metadata edit, in seconds.
LIMIT = 1.0


def _writer_is_stub() -> bool:
    """The writer is still the stub, which raises for any edit (the real one refuses a file
    that does not exist)."""
    try:
        header.apply_header_edit(HeaderEdit(path=Path("/nonexistent/reframe/stub-check.mkv")))
    except NotImplementedError:
        return True
    return False


needs_writer = pytest.mark.skipif(
    _writer_is_stub(), reason="the Matroska header writer is not merged yet"
)


@dataclass
class Env:
    tmp: Path
    source: Path

    async def app(self) -> Reframe:
        return await Reframe.create()


def _settings(config: Path, **output: object) -> None:
    config.mkdir(parents=True, exist_ok=True)
    settings = {
        "encoders": {"hardware_tests": False},
        "queue": {"sleep_inhibit": False},
        "output": output,
    }
    (config / "settings.json").write_text(json.dumps(settings), encoding="utf-8")


@pytest.fixture
def env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fixture_media: Callable[[str], Path]
) -> Env:
    ffmpeg, ffprobe = media.find_ffmpeg(), media.find_ffprobe()
    if ffmpeg is None or ffprobe is None:
        pytest.skip("needs ffmpeg and ffprobe")
    for var in ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    for name in ("config", "data", "cache"):
        monkeypatch.setenv(f"REFRAME_{name.upper()}_DIR", str(tmp_path / name))
    monkeypatch.setenv("REFRAME_FFMPEG", ffmpeg)
    monkeypatch.setenv("REFRAME_FFPROBE", ffprobe)
    # Even an installed MKVToolNix is not found: no product path may need it.
    monkeypatch.setenv("REFRAME_MKVPROPEDIT", str(tmp_path / "no-mkvtoolnix" / "mkvpropedit"))
    monkeypatch.setattr(mediainfo, "mediainfo_available", lambda: False)
    _settings(tmp_path / "config")
    source = tmp_path / "media" / "Show.S01E01.mkv"
    source.parent.mkdir()
    shutil.copyfile(fixture_media("multitrack"), source)
    return Env(tmp_path, source)


async def draft_remux(app: Reframe, path: Path) -> JobSettings:
    draft = await app.jobs.draft_remux(path)
    assert isinstance(draft, JobDraft), draft
    assert [i for i in draft.issues if i.severity.value == "error"] == []
    return draft.job


async def run(app: Reframe, job: JobSettings) -> QueueJob:
    queued = await app.queue.add(job)
    assert queued.state is JobState.WAITING, (queued.error, queued.issues)
    app.queue.start(job_ids=[queued.id])
    [ended] = await app.queue.wait([queued.id])
    return ended


def seconds(job: QueueJob) -> float:
    assert job.started_at is not None
    assert job.finished_at is not None
    return (job.finished_at - job.started_at).total_seconds()


async def reprobe(app: Reframe, path: Path) -> MediaSource:
    source = await app.sources.probe(path, use_cache=False)
    assert isinstance(source, MediaSource), source
    return source


def mkvmerge_json(path: Path) -> dict[str, Any]:
    out = subprocess.run(
        [mkvtoolnix_tool("mkvmerge"), "-J", str(path)],
        capture_output=True, text=True, check=True, timeout=60,
    )  # fmt: skip
    data: dict[str, Any] = json.loads(out.stdout)
    return data


def mkvmerge(path: Path) -> list[dict[str, object]]:
    """The track properties as ``mkvmerge -J`` reads them; ``[]`` without MKVToolNix."""
    if shutil.which("mkvmerge") is None:
        return []
    return [t["properties"] for t in mkvmerge_json(path)["tracks"]]


_MKVPROPEDIT_FLAGS = {
    "default": "flag-default",
    "forced": "flag-forced",
    "commentary": "flag-commentary",
    "hearing_impaired": "flag-hearing-impaired",
    "visual_impaired": "flag-visual-impaired",
    "original": "flag-original",
}


def mkvpropedit_args(edit: HeaderEdit) -> list[str]:
    """The mkvpropedit command line (after the program) that makes ``edit``: the oracle."""
    args = [str(edit.path)]
    for track in edit.tracks:
        args += ["--edit", f"track:{track.track_type[0]}{track.number}"]
        if track.language is not None and track.language_ietf is not None:
            # In this order: a later ``--set language`` overwrites ``language-ietf``.
            args += ["--set", f"language={track.language}"]
            args += ["--set", f"language-ietf={track.language_ietf}"]
        if track.delete_name:
            args += ["--delete", "name"]
        elif track.name is not None:
            args += ["--set", f"name={track.name}"]
        for flag, value in track.flags.items():
            args += ["--set", f"{_MKVPROPEDIT_FLAGS[flag]}={int(value)}"]
    if edit.info is not None:
        args += ["--edit", "info"]
        if edit.info.title is None:
            args += ["--delete", "title"]
        else:
            args += ["--set", f"title={edit.info.title}"]
    return args


def same_as_mkvpropedit(edit: HeaderEdit, edited: Path, original: Path, scratch: Path) -> None:
    """``mkvpropedit`` makes ``edit`` on a copy of ``original``; ``edited`` (Reframe's) must read
    back the same in ``mkvmerge -J``, and ffprobe must still read every stream."""
    oracle = scratch / f"oracle-{edited.name}"
    shutil.copyfile(original, oracle)
    args = mkvpropedit_args(edit.model_copy(update={"path": oracle}))
    subprocess.run([mkvtoolnix_tool("mkvpropedit"), *args], check=True, capture_output=True)
    ours, theirs = mkvmerge_json(edited), mkvmerge_json(oracle)
    assert [t["properties"] for t in ours["tracks"]] == [t["properties"] for t in theirs["tracks"]]
    assert ours["container"]["properties"].get("title") == theirs["container"]["properties"].get(
        "title"
    )
    ffprobe = media.find_ffprobe()
    assert ffprobe is not None
    streams = subprocess.run(
        [ffprobe, "-v", "error", "-of", "json", "-show_streams", str(edited)],
        capture_output=True, text=True, check=True, timeout=60,
    )  # fmt: skip
    assert len(json.loads(streams.stdout)["streams"]) == len(theirs["tracks"])


@needs_writer
async def test_languages_and_flags_are_a_metadata_edit_under_a_second(env: Env) -> None:
    app = await env.app()
    try:
        job = await draft_remux(app, env.source)
        job.audio[0].metadata.language = "de"
        job.audio[1].metadata.language = "fr"
        job.audio[0].metadata.default = False
        job.audio[1].metadata.default = True
        job.subtitles[2].metadata.forced = False
        plan = await app.jobs.plan(job)
        assert not isinstance(plan, list), plan
        assert plan.job_type == "metadata_edit"
        assert [s.kind for s in plan.steps] == ["header_edit"]
        ended = await run(app, job)
        assert ended.state is JobState.DONE, ended.error
        assert ended.output_path == env.source
        assert seconds(ended) < LIMIT, seconds(ended)
        assert sorted(p.name for p in env.source.parent.iterdir()) == ["Show.S01E01.mkv"]
        out = await reprobe(app, env.source)
        assert [(a.language, a.language_ietf, a.disposition.default) for a in out.audio] == [
            ("ger", "de", False), ("fre", "fr", True), ("eng", None, False),
        ]  # fmt: skip
        assert [s.disposition.forced for s in out.subtitles] == [False, False, False]
        log = app.queue.log_path(ended.id).read_text(encoding="utf-8")
        assert f"header_edit {env.source}" in log
        assert "Step 1/1 ended: written" in log
        assert "Edited Show.S01E01.mkv in place" in log
    finally:
        await app.close()


@needs_writer
async def test_languages_names_and_flags_the_reprobe_shows_them_all(env: Env) -> None:
    app = await env.app()
    try:
        job = await draft_remux(app, env.source)
        hungarian, brazilian, commentary = job.audio
        hungarian.metadata.language = "hu"
        hungarian.metadata.name = "Magyar 5.1"
        hungarian.metadata.original = True
        brazilian.metadata.language = "pt-BR"
        brazilian.metadata.name = "Português (Brasil)"
        commentary.metadata.commentary = True
        commentary.metadata.name = "Kommentár"
        sdh = job.subtitles[0]
        sdh.metadata.language = "hu"
        sdh.metadata.name = "Magyar SDH"
        sdh.metadata.hearing_impaired = True
        job.tags.title = "{name} S{season:02}E{episode:02}"
        kind, reason = await job_type(app, job)
        assert kind == "metadata_edit", reason
        ended = await run(app, job)
        assert ended.state is JobState.DONE, ended.error
        assert seconds(ended) < LIMIT, seconds(ended)
        out = await reprobe(app, env.source)
        assert out.container.title == "Show S01E01"
        rows = [
            (s.language, s.language_ietf, s.title, s.disposition.original, s.disposition.comment,
             s.disposition.hearing_impaired)
            for s in [*out.audio, out.subtitles[0]]
        ]  # fmt: skip
        assert rows == [
            ("hun", "hu", "Magyar 5.1", True, False, False),
            ("por", "pt-BR", "Português (Brasil)", False, False, False),
            ("eng", None, "Kommentár", False, True, False),
            ("hun", "hu", "Magyar SDH", False, False, True),
        ]
    finally:
        await app.close()


@needs_writer
async def test_only_flags_is_a_metadata_edit_under_a_second(env: Env) -> None:
    app = await env.app()
    try:
        job = await draft_remux(app, env.source)
        job.subtitles[0].metadata.default = False
        job.subtitles[1].metadata.default = True
        job.audio[2].metadata.visual_impaired = True
        kind, reason = await job_type(app, job)
        assert kind == "metadata_edit", reason
        ended = await run(app, job)
        assert ended.state is JobState.DONE, ended.error
        assert seconds(ended) < LIMIT, seconds(ended)
        out = await reprobe(app, env.source)
        assert [s.disposition.default for s in out.subtitles] == [False, True, False]
        assert out.audio[2].disposition.visual_impaired
    finally:
        await app.close()


@needs_writer
@pytest.mark.needs_mkvtoolnix
async def test_an_in_place_edit_reads_back_as_mkvpropedits(
    env: Env, fixture_media: Callable[[str], Path]
) -> None:
    app = await env.app()
    try:
        job = await draft_remux(app, env.source)
        job.video.metadata.name = "Main"
        job.audio[0].metadata.language = "hu"
        job.audio[0].metadata.name = "Magyar 5.1"
        job.audio[0].metadata.default = False
        job.audio[1].metadata.language = "pt-BR"
        job.audio[1].metadata.original = True
        job.audio[2].metadata.name = ""
        job.subtitles[1].metadata.visual_impaired = True
        job.subtitles[2].metadata.forced = False
        job.tags.title = "Új cím"
        plan = await app.jobs.plan(job)
        assert not isinstance(plan, list), plan
        [step] = plan.steps
        assert step.header_edit is not None
        ended = await run(app, job)
        assert ended.state is JobState.DONE, ended.error
    finally:
        await app.close()
    same_as_mkvpropedit(step.header_edit, env.source, fixture_media("multitrack"), env.tmp)


async def job_type(app: Reframe, job: JobSettings) -> tuple[str, str]:
    from reframe.command import job_type as detect

    source = await app.sources.probe(job.source.path)
    assert isinstance(source, MediaSource)
    return detect(job, source)


async def test_nothing_to_change_is_done_without_a_write(env: Env) -> None:
    app = await env.app()
    try:
        job = await draft_remux(app, env.source)
        before = env.source.stat().st_mtime_ns
        ended = await run(app, job)
        assert ended.state is JobState.DONE, ended.error
        assert env.source.stat().st_mtime_ns == before
        assert "nothing to change" in app.queue.log_path(ended.id).read_text(encoding="utf-8")
    finally:
        await app.close()


@needs_writer
async def test_post_mux_fixup_writes_bcp47_and_is_checked_before_the_rename(env: Env) -> None:
    app = await env.app()
    try:
        draft = await app.jobs.draft_remux(env.source, edit_in_place=False)
        assert isinstance(draft, JobDraft)
        job = draft.job
        job.output.container = "mkv"
        job.output.path = env.tmp / "out" / "Fixed.mkv"
        job.audio[1].metadata.language = "pt-BR"
        job.audio[0].metadata.language = "hu"
        plan = await app.jobs.plan(job)
        assert not isinstance(plan, list), plan
        assert plan.job_type == "remux"
        assert [s.kind for s in plan.steps] == ["encode", "header_edit", "finalize"]
        ended = await run(app, job)
        assert ended.state is JobState.DONE, ended.error
        out = await reprobe(app, env.tmp / "out" / "Fixed.mkv")
        assert [(a.language, a.language_ietf) for a in out.audio][:2] == [
            ("hun", None), ("por", "pt-BR"),
        ]  # fmt: skip
    finally:
        await app.close()


@needs_writer
@pytest.mark.needs_mkvtoolnix
async def test_the_fixup_reads_back_as_mkvpropedits(env: Env) -> None:
    """The plan's encode step makes the muxed file; mkvpropedit and the writer each make the
    fix-up on a copy of it."""
    app = await env.app()
    try:
        draft = await app.jobs.draft_remux(env.source, edit_in_place=False)
        assert isinstance(draft, JobDraft)
        job = draft.job
        job.output.container = "mkv"
        job.output.path = env.tmp / "out" / "Fixed.mkv"
        job.audio[1].metadata.language = "pt-BR"
        job.subtitles[0].metadata.language = "zh-Hant"
        plan = await app.jobs.plan(job)
        assert not isinstance(plan, list), plan
        tools = await app.tools.status()
    finally:
        await app.close()
    assert tools.ffmpeg.path is not None
    fixup_both_ways(plan, tools.ffmpeg.path, env.tmp)
    tracks = mkvmerge(plan.output_tmp)
    assert [(t.get("language"), t.get("language_ietf")) for t in (tracks[2], tracks[4])] == [
        ("por", "pt-BR"), ("chi", "zh-Hant"),
    ]  # fmt: skip


def fixup_both_ways(plan: EncodePlan, ffmpeg: Path, scratch: Path) -> None:
    encode, fixup, _ = plan.steps
    assert fixup.header_edit is not None
    plan.output_tmp.parent.mkdir(parents=True)
    subprocess.run([str(ffmpeg), *resolve_argv(encode.argv, {})], check=True, capture_output=True)
    muxed = scratch / "muxed.mkv"
    shutil.copyfile(plan.output_tmp, muxed)
    written = header.apply_header_edit(fixup.header_edit)
    assert written.ok, written
    same_as_mkvpropedit(fixup.header_edit, plan.output_tmp, muxed, scratch)


def fake_writer(
    monkeypatch: pytest.MonkeyPatch, result: HeaderEditResult
) -> list[tuple[HeaderEdit, bytes]]:
    """The writer replaced: it writes nothing and returns ``result``; each call's edit and the
    file's bytes at that moment."""
    calls: list[tuple[HeaderEdit, bytes]] = []

    def write(edit: HeaderEdit) -> HeaderEditResult:
        calls.append((edit, edit.path.read_bytes()))
        return result

    monkeypatch.setattr(header, "apply_header_edit", write)
    return calls


async def test_an_edit_that_changed_nothing_fails_the_reprobe_check(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = fake_writer(monkeypatch, HeaderEditResult("written"))
    _settings(env.tmp / "config", partial_file="delete")
    app = await env.app()
    try:
        job = await draft_remux(app, env.source)
        job.audio[1].metadata.language = "pt-BR"
        job.audio[1].metadata.original = True
        ended = await run(app, job)
        assert ended.state is JobState.FAILED
        assert ended.error == (
            "The edited source does not have the values of the job: audio track 2: language "
            "por expected, eng found; audio track 2: BCP 47 language pt-BR expected, en found; "
            "audio track 2: the original flag should be set."
        )
        assert [edit.path for edit, _ in calls] == [env.source]
        assert env.source.exists()  # never removed, whatever the partial-file setting
    finally:
        await app.close()


@pytest.mark.parametrize(
    ("result", "error"),
    [
        (
            HeaderEditResult("refused", "header.no_room", "The SeekHead has no room."),
            "Reframe cannot edit the Matroska header of Show.S01E01.mkv: The SeekHead has no "
            "room. Nothing was changed in the file.",
        ),
        (
            HeaderEditResult("failed", "header.write_error", "Input/output error"),
            "Writing the Matroska header of Show.S01E01.mkv failed: Input/output error. The "
            "file holds either all its old values or all the new ones.",
        ),
    ],
)
async def test_a_write_that_is_refused_or_fails_fails_the_job_and_keeps_the_source(
    env: Env, monkeypatch: pytest.MonkeyPatch, result: HeaderEditResult, error: str
) -> None:
    fake_writer(monkeypatch, result)
    _settings(env.tmp / "config", partial_file="delete")
    before = env.source.read_bytes()
    app = await env.app()
    try:
        job = await draft_remux(app, env.source)
        job.audio[0].metadata.name = "X"
        ended = await run(app, job)
        assert (ended.state, ended.error) == (JobState.FAILED, error)
        assert env.source.read_bytes() == before
        log = app.queue.log_path(ended.id).read_text(encoding="utf-8")
        assert f"Step 1/1 ended: {result.status} ({result.code})" in log
        assert "Clean-up" not in log
        assert "partial output" not in log
    finally:
        await app.close()


@pytest.mark.skipif(
    sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="POSIX permissions (root can write a read-only file)",
)
async def test_a_read_only_source_is_a_validation_error(env: Env) -> None:
    app = await env.app()
    try:
        job = await draft_remux(app, env.source)
        job.audio[0].metadata.name = "X"
        env.source.chmod(0o444)
        queued = await app.queue.add(job)
        assert queued.state is JobState.FAILED
        assert [i.code for i in queued.issues if i.severity.value == "error"] == [
            "inplace.source_not_writable"
        ]
    finally:
        env.source.chmod(0o644)
        await app.close()


@needs_writer
async def test_cancelling_an_in_place_edit_lets_the_writer_finish(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cancel does not stop the writer while it writes the source. The real writer waits at
    a gate, so the cancel always comes during the step."""
    real = header.apply_header_edit
    gate, started = threading.Event(), threading.Event()

    def gated(edit: HeaderEdit) -> HeaderEditResult:
        started.set()
        gate.wait(30)
        return real(edit)

    monkeypatch.setattr(header, "apply_header_edit", gated)
    _settings(env.tmp / "config", partial_file="delete")
    app = await env.app()
    try:
        job = await draft_remux(app, env.source)
        job.audio[0].metadata.name = "Renamed"
        queued = await app.queue.add(job)
        app.queue.start(job_ids=[queued.id])
        cancel: asyncio.Task[None] | None = None
        try:
            assert await asyncio.to_thread(started.wait, 30)
            cancel = asyncio.create_task(app.queue.cancel(queued.id))

            def stop_requested() -> bool:
                active = app.queue._active.get(queued.id)
                return active is None or active.token.cancelled

            await poll(stop_requested)
        finally:
            gate.set()
        assert cancel is not None
        await cancel
        [ended] = await app.queue.wait([queued.id])
        assert ended.state is JobState.CANCELLED
        assert ended.error == (
            "The edit was already written to Show.S01E01.mkv when the job was cancelled: "
            "Reframe never stops a write into the source. The check of the edited file did "
            "not run."
        )
        out = await reprobe(app, env.source)
        assert out.audio[0].title == "Renamed"  # the real writer wrote it
        assert len(read_matroska(env.source).tracks) == 7
        log = app.queue.log_path(ended.id).read_text(encoding="utf-8")
        assert "it is let finish" in log
        assert "Clean-up" not in log
    finally:
        await app.close()


async def poll(condition: Callable[[], bool], limit: float = 20.0) -> None:
    deadline = asyncio.get_running_loop().time() + limit
    while not condition():
        assert asyncio.get_running_loop().time() < deadline, "condition not met in time"
        await asyncio.sleep(0.01)
