"""Metadata edits and the post-mux fix-up through the real queue and mkvpropedit, on a copy of
the ``multitrack`` fixture. MediaInfo is off, so the BCP 47 languages that the re-probe shows
come from Reframe's own Matroska reader. Failures use fake mkvpropedit scripts (POSIX only)."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from reframe.models import JobDraft, JobSettings, JobState, MediaSource, QueueJob
from reframe.probe import mediainfo
from reframe.probe.matroska import read_matroska
from reframe.service import Reframe
from reframe.tools import ENV_VARS
from reframe_testing import media

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
    mkvpropedit = shutil.which("mkvpropedit")
    ffmpeg, ffprobe = media.find_ffmpeg(), media.find_ffprobe()
    if mkvpropedit is None or ffmpeg is None or ffprobe is None:
        pytest.skip("needs mkvpropedit, ffmpeg and ffprobe")
    for var in ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    for name in ("config", "data", "cache"):
        monkeypatch.setenv(f"REFRAME_{name.upper()}_DIR", str(tmp_path / name))
    monkeypatch.setenv("REFRAME_FFMPEG", ffmpeg)
    monkeypatch.setenv("REFRAME_FFPROBE", ffprobe)
    monkeypatch.setenv("REFRAME_MKVPROPEDIT", mkvpropedit)
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


def mkvmerge(path: Path) -> list[dict[str, object]]:
    tool = shutil.which("mkvmerge")
    if tool is None:
        return []
    out = subprocess.run([tool, "-J", str(path)], capture_output=True, text=True, check=True)
    return [t["properties"] for t in json.loads(out.stdout)["tracks"]]


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
        assert "mkvpropedit" in log
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
        tracks = mkvmerge(env.source)
        if tracks:  # MKVToolNix reads the same values
            assert [(t.get("language"), t.get("language_ietf")) for t in tracks[1:3]] == [
                ("hun", "hu"), ("por", "pt-BR"),
            ]  # fmt: skip
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


async def job_type(app: Reframe, job: JobSettings) -> tuple[str, str]:
    from reframe.command import job_type as detect

    source = await app.sources.probe(job.source.path)
    assert isinstance(source, MediaSource)
    return detect(job, source)


async def test_nothing_to_change_is_done_without_running_mkvpropedit(env: Env) -> None:
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


FAKE_VERSION = "mkvpropedit v101.0 ('Time To Turn') 64-bit"


def fake_mkvpropedit(folder: Path, body: str) -> Path:
    """A POSIX shell mkvpropedit: ``--version`` prints the fake version, else runs ``body``."""
    script = folder / "mkvpropedit"
    folder.mkdir(parents=True, exist_ok=True)
    script.write_text(
        f'#!/bin/sh\nif [ "$1" = "--version" ]; then echo "{FAKE_VERSION}"; exit 0; fi\n{body}\n',
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


posix_only = pytest.mark.skipif(sys.platform == "win32", reason="the fake mkvpropedit is sh")


@posix_only
async def test_an_edit_that_changed_nothing_fails_the_reprobe_check(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REFRAME_MKVPROPEDIT", str(fake_mkvpropedit(env.tmp / "bin", "exit 0")))
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
        assert env.source.exists()  # never removed, whatever the partial-file setting
    finally:
        await app.close()


@posix_only
async def test_a_failing_mkvpropedit_fails_the_job_and_keeps_the_source(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = 'echo "Error: The file could not be opened for writing." ; exit 2'
    monkeypatch.setenv("REFRAME_MKVPROPEDIT", str(fake_mkvpropedit(env.tmp / "bin", body)))
    _settings(env.tmp / "config", partial_file="delete")
    app = await env.app()
    try:
        job = await draft_remux(app, env.source)
        job.audio[0].metadata.name = "X"
        ended = await run(app, job)
        assert ended.state is JobState.FAILED
        assert ended.error is not None
        assert ended.error.startswith("mkvpropedit failed (exit code 2)")
        assert env.source.exists()
        log = app.queue.log_path(ended.id).read_text(encoding="utf-8")
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


@posix_only
async def test_cancelling_an_in_place_edit_lets_mkvpropedit_finish(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cancel does not stop mkvpropedit while it writes the source: a kill can destroy the
    track headers. The fake waits at a gate, so the cancel always comes during the step."""
    real = shutil.which("mkvpropedit")
    assert real is not None
    gate, started = env.tmp / "gate", env.tmp / "started"
    body = f'touch "{started}"\nwhile [ ! -e "{gate}" ]; do sleep 0.01; done\nexec "{real}" "$@"'
    monkeypatch.setenv("REFRAME_MKVPROPEDIT", str(fake_mkvpropedit(env.tmp / "bin", body)))
    _settings(env.tmp / "config", partial_file="delete")
    app = await env.app()
    try:
        job = await draft_remux(app, env.source)
        job.audio[0].metadata.name = "Renamed"
        queued = await app.queue.add(job)
        app.queue.start(job_ids=[queued.id])
        cancel: asyncio.Task[None] | None = None
        try:
            await poll(started.exists)
            cancel = asyncio.create_task(app.queue.cancel(queued.id))

            def stop_requested() -> bool:
                active = app.queue._active.get(queued.id)
                return active is None or active.token.cancelled

            await poll(stop_requested)
        finally:
            gate.touch()
        assert cancel is not None
        await cancel
        [ended] = await app.queue.wait([queued.id])
        assert ended.state is JobState.CANCELLED
        assert ended.error == (
            "The edit was already written to Show.S01E01.mkv when the job was cancelled: "
            "mkvpropedit is never stopped while it writes the source (that can damage the "
            "file). The check of the edited file did not run."
        )
        out = await reprobe(app, env.source)
        assert out.audio[0].title == "Renamed"  # the real mkvpropedit wrote it
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
