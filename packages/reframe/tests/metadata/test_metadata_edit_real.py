"""Metadata edits and the post-mux fix-up through the real queue and Reframe's own Matroska
header writer, on a copy of the ``multitrack`` fixture, with no MKVToolNix program for the
product to find. The BCP 47 languages that the re-probe shows come from Reframe's own
Matroska reader. MKVToolNix is only the oracle (``needs_mkvtoolnix``): the same
edit by mkvpropedit reads back the same in ``mkvmerge -J``."""

from __future__ import annotations

import asyncio
import errno
import json
import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from reframe.command.header import edit_line
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
from reframe.probe.matroska import read_matroska
from reframe.queue import runner as runner_module
from reframe.service import Reframe
from reframe.tools import ENV_VARS
from reframe_testing import media
from reframe_testing.mkvtoolnix import mkvpropedit_args, mkvtoolnix_tool
from reframe_testing.waiting import wait_until

pytestmark = [pytest.mark.needs_ffmpeg, pytest.mark.anyio]

#: The time limit of a metadata edit, in seconds.
LIMIT = 1.0


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


async def test_an_encode_with_a_track_name_template_passes_the_fixup_check(env: Env) -> None:
    app = await env.app()
    try:
        draft = await app.jobs.draft_remux(env.source, edit_in_place=False)
        assert isinstance(draft, JobDraft)
        job = draft.job
        job.output.path = env.tmp / "out" / "Named.mkv"
        japanese = job.audio[0]
        japanese.action, japanese.encoder, japanese.mixdown = "encode", "aac", "5.1"
        japanese.metadata.language = "pt-BR"
        japanese.metadata.name = "{lang_name} {channels} {codec}"
        job.subtitles[0].metadata.name = "{lang_native} {codec}"
        plan = await app.jobs.plan(job)
        assert not isinstance(plan, list), plan
        assert [s.kind for s in plan.steps] == ["encode", "header_edit", "finalize"]
        ended = await run(app, job)
        assert ended.state is JobState.DONE, ended.error
        out = await reprobe(app, env.tmp / "out" / "Named.mkv")
        assert (out.audio[0].language_ietf, out.audio[0].title) == (
            "pt-BR",
            "Portuguese (Brazil) 5.1 AAC",
        )
        assert out.subtitles[0].title == "English SRT"
    finally:
        await app.close()


async def test_an_in_place_edit_with_a_track_name_template_passes_the_check(env: Env) -> None:
    app = await env.app()
    try:
        job = await draft_remux(app, env.source)
        job.audio[1].metadata.language = "es-419"
        job.audio[1].metadata.name = "{lang_name} {channels} {codec}"
        job.video.metadata.name = "{codec}"
        kind, reason = await job_type(app, job)
        assert kind == "metadata_edit", reason
        ended = await run(app, job)
        assert ended.state is JobState.DONE, ended.error
        out = await reprobe(app, env.source)
        assert out.audio[1].title == "Spanish (Latin America) 2.0 AAC-LC"
        assert out.video[0].title == "H.264 Constrained Baseline"
    finally:
        await app.close()


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
            HeaderEditResult(
                "failed", "header.write_error", "Input/output error", file_state="old"
            ),
            "Writing the Matroska header of Show.S01E01.mkv failed: Input/output error. The "
            "file holds all its old values.",
        ),
        (
            HeaderEditResult("failed", "header.write_error", "Input/output error"),
            "Writing the Matroska header of Show.S01E01.mkv failed: Input/output error. "
            "Reframe cannot tell what the file holds now.",
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

            await wait_until(stop_requested)
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


def changed_under_the_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real writer, with the file touched between its read and its write: it writes
    nothing and fails with ``header.changed``."""
    prepare = header._prepare

    def touching(handle: Any, edit: HeaderEdit) -> Any:
        steps = prepare(handle, edit)
        os.utime(edit.path, ns=(0, 1))
        return steps

    monkeypatch.setattr(header, "_prepare", touching)


async def test_a_header_that_may_be_damaged_is_said_first_and_its_old_bytes_are_kept(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defect: the disk fails during the switch and while its old bytes are written back, and
    the job hides that the header may be damaged, or loses the bytes that would repair it."""
    writes = [0]

    class FailingIO(header._FileIO):
        def write(self, pos: int, data: bytes) -> None:
            writes[0] += 1
            if writes[0] > 1:
                raise OSError(errno.ENOSPC, "No space left on device")
            super().write(pos, data[: len(data) // 2])
            raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(header, "_FileIO", FailingIO)
    original = env.source.read_bytes()
    app = await env.app()
    try:
        job = await draft_remux(app, env.source)
        job.audio[0].metadata.name = "X"
        ended = await run(app, job)
        assert ended.state is JobState.FAILED
        assert ended.error is not None
        head = (
            "Writing the Matroska header of Show.S01E01.mkv failed: The header of the file may "
            "be damaged. Writing the header failed ([Errno 28] No space left on device), and "
            "writing its old bytes back failed too ([Errno 28] No space left on device). Its old "
            "bytes at offset "
        )
        assert ended.error.startswith(head), ended.error
        offset = int(ended.error[len(head) :].split(" ", 1)[0])
        saved = app.queue.log_path(ended.id).parent / f"{ended.id}.header-at-{offset}.bin"
        assert f"are saved in {saved}: writing them back at that offset restores" in ended.error
        data = saved.read_bytes()
        assert data == original[offset : offset + len(data)]
        assert env.source.read_bytes() != original
        put_back(env.source, offset, data)
        assert env.source.read_bytes() == original
    finally:
        await app.close()


def put_back(path: Path, offset: int, data: bytes) -> None:
    with open(path, "r+b") as handle:
        handle.seek(offset)
        handle.write(data)


async def test_a_failure_that_wrote_nothing_says_so_and_only_so(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defect: the job says the file "is unchanged" and then that it "holds either all its old
    values or all the new ones"."""
    changed_under_the_writer(monkeypatch)
    before = env.source.read_bytes()
    app = await env.app()
    try:
        job = await draft_remux(app, env.source)
        job.audio[0].metadata.name = "X"
        ended = await run(app, job)
        assert ended.state is JobState.FAILED
        assert ended.error == (
            "Writing the Matroska header of Show.S01E01.mkv failed: The file changed while "
            "its header was read. Nothing was changed in the file."
        )
        assert env.source.read_bytes() == before
    finally:
        await app.close()


async def test_a_cancel_during_a_write_that_wrote_nothing_says_so_and_only_so(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defect: the same contradiction in the error of a job cancelled during the write."""
    changed_under_the_writer(monkeypatch)
    real = header.apply_header_edit
    gate, started = threading.Event(), threading.Event()

    def gated(edit: HeaderEdit) -> HeaderEditResult:
        started.set()
        gate.wait(30)
        return real(edit)

    monkeypatch.setattr(header, "apply_header_edit", gated)
    app = await env.app()
    try:
        job = await draft_remux(app, env.source)
        job.audio[0].metadata.name = "X"
        queued = await app.queue.add(job)
        app.queue.start(job_ids=[queued.id])
        try:
            assert await asyncio.to_thread(started.wait, 30)
            task = app.queue._active[queued.id].task
            assert task is not None
            task.cancel()  # as an event loop that shuts down does
            await asyncio.sleep(0.2)
        finally:
            gate.set()
        [ended] = await app.queue.wait([queued.id])
        assert ended.error is not None
        assert ended.error.endswith(
            "the write was let finish (failed (header.changed): The file changed while its "
            "header was read.). Nothing was changed in the file."
        ), ended.error
    finally:
        await app.close()


async def test_the_writer_does_not_wait_behind_other_blocked_threads(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defect: the writer waits for a worker of the shared default executor, which slow
    shares can hold; a cancel in that time cannot stop it, and the source is written after the
    cancel."""
    loop = asyncio.get_running_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
    gate = threading.Event()
    ran = asyncio.Event()
    real = header.apply_header_edit

    def recording(edit: HeaderEdit) -> HeaderEditResult:
        result = real(edit)
        loop.call_soon_threadsafe(ran.set)
        return result

    monkeypatch.setattr(header, "apply_header_edit", recording)

    def then_busy(edit: HeaderEdit, shell: Any) -> str:
        loop.run_in_executor(None, gate.wait, 60)  # a hung share holds the only worker
        return edit_line(edit, shell)

    monkeypatch.setattr(runner_module, "edit_line", then_busy)
    app = await env.app()
    try:
        job = await draft_remux(app, env.source)
        job.audio[0].metadata.name = "Renamed"
        queued = await app.queue.add(job)
        app.queue.start(job_ids=[queued.id])
        try:
            await asyncio.wait_for(ran.wait(), 10)
        finally:
            gate.set()
        [ended] = await app.queue.wait([queued.id])
        assert ended.state is JobState.DONE, ended.error
        assert (await reprobe(app, env.source)).audio[0].title == "Renamed"
    finally:
        gate.set()
        await app.close()


class HeldThread(threading.Thread):
    """A writer thread that the test holds before it runs (as a busy machine may)."""

    hold = threading.Event()
    waiting = threading.Event()

    def run(self) -> None:
        HeldThread.waiting.set()
        HeldThread.hold.wait(30)
        super().run()


@pytest.mark.parametrize("how", ["cancel", "close"])
async def test_a_stop_before_the_writer_starts_writes_nothing_and_ends_at_once(
    env: Env, monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    """Defect: a cancel or ``close()`` while the writer has not started yet waits for it, and
    the writer then writes the source of a job that was stopped."""
    from reframe.metadata import own_thread

    HeldThread.hold, HeldThread.waiting = threading.Event(), threading.Event()
    monkeypatch.setattr(own_thread, "Thread", HeldThread)
    calls = fake_writer(monkeypatch, HeaderEditResult("written"))
    before = env.source.read_bytes()
    app = await env.app()
    closed = False
    try:
        job = await draft_remux(app, env.source)
        job.audio[0].metadata.name = "Renamed"
        queued = await app.queue.add(job)
        app.queue.start(job_ids=[queued.id])
        try:
            assert await asyncio.to_thread(HeldThread.waiting.wait, 30)
            if how == "cancel":
                await asyncio.wait_for(app.queue.cancel(queued.id), 5)
                [ended] = await asyncio.wait_for(app.queue.wait([queued.id]), 5)
                assert ended.state is JobState.CANCELLED
                assert ended.error is None
            else:
                await asyncio.wait_for(app.close(), 5)
                closed = True
        finally:
            HeldThread.hold.set()
        await asyncio.sleep(0.2)
        assert calls == []
        assert env.source.read_bytes() == before
        if how == "cancel":
            log = app.queue.log_path(queued.id).read_text(encoding="utf-8")
            assert "before Reframe started to write the header" in log
    finally:
        HeldThread.hold.set()
        if not closed:
            await app.close()
