"""The queue's job keys: a file reached by a link, a hard link or a linked folder is one file,
the keys are read off the event loop, and a path with a NUL character fails only its job."""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from reframe.metadata import remux_job
from reframe.models import JobSettings, JobState, SourceRef
from reframe.queue import files, runner, service
from reframe.queue.service import _conflicts, _output_key, _source_key
from reframe_testing import fake_tools as ft

from .conftest import Harness, encode_rule, queue_at, restore_together, store_rows, tool_set
from .test_in_place_scheduling import active_for, ended_before_started, in_place_job, queued

pytestmark = pytest.mark.anyio

needs_symlinks = pytest.mark.skipif(
    sys.platform == "win32", reason="creating a symbolic link needs a privilege on Windows"
)


def _in_place_job_at(h: Harness, path: Path, name: str) -> JobSettings:
    source = h.sources.source.model_copy(update={"ref": SourceRef(path=path)}, deep=True)
    job = remux_job(JobSettings(source=SourceRef(path=path)), source)
    job.audio[0].metadata.name = name
    return job


@needs_symlinks
async def test_a_symlink_to_the_source_is_the_same_file(harness: Harness, tmp_path: Path) -> None:
    h = harness
    link = tmp_path / "media" / "link-to-source.mkv"
    link.symlink_to(h.source_path)
    edit = queued(in_place_job(h), "edit")
    encode = queued(h.job("Encode"), "encode")
    encode.settings.source = SourceRef(path=link)  # the same file, another path
    assert _conflicts(encode, [active_for(edit)])  # it reads the file being edited
    assert _conflicts(edit, [active_for(encode)])  # the file to edit is being read
    linked_edit = queued(_in_place_job_at(h, link, "Linked"), "linked-edit")
    assert _conflicts(linked_edit, [active_for(edit)])  # two edits of one file
    assert _conflicts(edit, [active_for(linked_edit)])


async def test_a_hard_link_to_the_source_is_the_same_file(harness: Harness, tmp_path: Path) -> None:
    h = harness
    link = tmp_path / "media" / "hardlink.mkv"
    try:
        os.link(h.source_path, link)
    except OSError as exc:  # pragma: no cover - a file system without hard links
        pytest.skip(f"no hard links here: {exc}")
    edit = queued(in_place_job(h), "edit")
    encode = queued(h.job("Encode"), "encode")
    encode.settings.source = SourceRef(path=link)
    assert _conflicts(encode, [active_for(edit)])
    assert _conflicts(edit, [active_for(encode)])
    linked_edit = queued(_in_place_job_at(h, link, "Linked"), "linked-edit")
    assert _conflicts(linked_edit, [active_for(edit)])
    # A copy is another file: no conflict.
    copy = tmp_path / "media" / "copy.mkv"
    copy.write_bytes(h.source_path.read_bytes())
    other = queued(h.job("Other"), "other")
    other.settings.source = SourceRef(path=copy)
    assert not _conflicts(other, [active_for(edit)])


@needs_symlinks
async def test_the_same_output_through_a_linked_folder(harness: Harness, tmp_path: Path) -> None:
    """Two jobs with the same output never run at once: both write the same .part file."""
    h = harness
    out = tmp_path / "out"  # the harness made it
    (tmp_path / "out-link").symlink_to(out, target_is_directory=True)
    first = queued(h.job("A"), "a")
    second = queued(h.job("B"), "b")
    first.settings.output.path = out / "Movie.mkv"
    second.settings.output.path = tmp_path / "out-link" / "Movie.mkv"
    assert _conflicts(second, [active_for(first)])
    # A folder that does not exist yet below the link resolves the same way.
    first.settings.output.path = out / "new" / "Movie.mkv"
    second.settings.output.path = tmp_path / "out-link" / "new" / "Movie.mkv"
    assert _conflicts(second, [active_for(first)])
    second.settings.output.path = tmp_path / "out-link" / "new" / "Other.mkv"
    assert not _conflicts(second, [active_for(first)])


async def test_keys_differ_only_in_case_are_the_same_output(harness: Harness) -> None:
    """Windows and macOS file systems ignore case; on Linux this errs on the safe side (the
    rule of ``files.same_file``)."""
    h = harness
    first = queued(h.job("Movie"), "a")
    second = queued(h.job("MOVIE"), "b")
    assert _output_key(first) != _output_key(second)
    assert _conflicts(second, [active_for(first)])


def _one_file_index(monkeypatch: pytest.MonkeyPatch, *paths: Path) -> None:
    real_stat = os.stat
    linked = {os.path.realpath(path) for path in paths}

    def same_index(path: str | os.PathLike[str], *args: Any, **kwargs: Any) -> os.stat_result:
        result = real_stat(path, *args, **kwargs)
        if os.path.realpath(path) in linked:
            fields = list(result)
            fields[1], fields[2] = 4242, 7  # st_ino (file index), st_dev (volume serial)
            return os.stat_result(fields)
        return result

    monkeypatch.setattr(os, "stat", same_index)


async def test_file_identity_is_what_os_stat_reports(
    harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two paths with the same ``(st_dev, st_ino)`` are one file. On Windows that pair is the
    volume serial number and the file index, so a hard link has the same pair. Mocked, so it
    runs on every OS."""
    h = harness
    other = tmp_path / "media" / "Other.Name.mkv"
    other.write_bytes(b"another file")
    edit = queued(in_place_job(h), "edit")
    encode = queued(h.job("Encode"), "encode")
    encode.settings.source = SourceRef(path=other)
    assert not _conflicts(encode, [active_for(edit)])

    _one_file_index(monkeypatch, other, h.source_path)
    assert _conflicts(encode, [active_for(edit)])
    assert _conflicts(edit, [active_for(encode)])


async def test_a_key_of_a_missing_file_is_its_resolved_path(
    harness: Harness, tmp_path: Path
) -> None:
    h = harness
    job = queued(h.job("Missing"), "m")
    job.settings.source = SourceRef(path=tmp_path / "media" / ".." / "media" / "gone.mkv")
    assert _source_key(job) == service._path_key(tmp_path / "media" / "gone.mkv")
    assert not _conflicts(job, [active_for(queued(in_place_job(h), "edit"))])


@needs_symlinks
async def test_two_in_place_edits_through_a_link_run_one_after_the_other(
    harness: Harness, tmp_path: Path
) -> None:
    h = harness
    h.settings.queue.parallel_jobs = 2
    h.tools.tools = tool_set(h.fake.ffmpeg, mkvpropedit=h.fake.ffmpeg)
    link = tmp_path / "media" / "link-to-source.mkv"
    link.symlink_to(h.source_path)
    first, second = await restore_together(
        h, in_place_job(h, "One"), _in_place_job_at(h, link, "Two")
    )
    h.queue.start()
    await h.queue.wait([first, second])
    assert ended_before_started(h, first, second)


async def test_an_encode_of_a_hard_link_waits_for_the_in_place_edit(
    harness: Harness, tmp_path: Path
) -> None:
    h = harness
    link = tmp_path / "media" / "hardlink.mkv"
    try:
        os.link(h.source_path, link)
    except OSError as exc:  # pragma: no cover - a file system without hard links
        pytest.skip(f"no hard links here: {exc}")
    h.settings.queue.parallel_jobs = 2
    h.tools.tools = tool_set(h.fake.ffmpeg, mkvpropedit=h.fake.ffmpeg)
    h.scenario(encode_rule(ft.progress(blocks=1, end=True)))
    edit = await h.queue.add(in_place_job(h))
    job = h.job("Encode")
    job.source = SourceRef(path=link)
    encode = await h.queue.add(job)
    assert encode.state is JobState.WAITING, encode.issues
    h.queue.start()
    await h.queue.wait([edit.id, encode.id])
    assert ended_before_started(h, edit.id, encode.id)


DONE_QUICKLY = encode_rule(ft.progress(blocks=2, interval=0.01), ft.write_output())


#: How long a ``stat`` / ``lstat`` of the share takes on the event-loop thread: longer than
#: any pause the loop takes on its own, so one such call shows in the heartbeat.
LOOP_DELAY = 0.3
#: The same in a worker thread (the share is slow there too, but that waits only the caller).
THREAD_DELAY = 0.01


def slow_share(monkeypatch: pytest.MonkeyPatch, share: Path, loop_thread: int) -> list[str]:
    """``os.stat`` and ``os.lstat`` of a path under ``share`` are slow; each call made on the
    event-loop thread is recorded (the list returned)."""
    on_loop: list[str] = []
    prefix = str(share)

    def slow(real: Callable[..., os.stat_result]) -> Callable[..., os.stat_result]:
        def call(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
            text = os.fspath(path) if isinstance(path, (str, os.PathLike)) else None
            if isinstance(text, str) and text.startswith(prefix):
                if threading.get_ident() == loop_thread:
                    on_loop.append(f"{real.__name__}({text})")
                    time.sleep(LOOP_DELAY)
                else:
                    time.sleep(THREAD_DELAY)
            return real(path, *args, **kwargs)

        return call

    monkeypatch.setattr(os, "stat", slow(os.stat))
    monkeypatch.setattr(os, "lstat", slow(os.lstat))
    return on_loop


async def test_choosing_a_job_never_reads_a_slow_share_on_the_event_loop(
    harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With a slow share and ``parallel_jobs`` 2, ``add``, ``start``, ``retry``, ``reorder`` and
    every job end must not ``stat`` the share on the event loop."""
    h = harness
    h.settings.queue.parallel_jobs = 2
    h.scenario(DONE_QUICKLY)
    share = tmp_path / "share"
    (share / "deep").mkdir(parents=True)
    on_loop = slow_share(monkeypatch, share, threading.get_ident())
    gaps: list[float] = []
    beating = True

    async def heartbeat() -> None:
        last = time.monotonic()
        while beating:
            await asyncio.sleep(0.01)
            now = time.monotonic()
            gaps.append(now - last)
            last = now

    beat = asyncio.ensure_future(heartbeat())
    ids: list[str] = []
    for name in ("S0", "S1", "S2"):
        job = h.job(name)
        job.output.path = share / "deep" / "er" / f"{name}.mkv"
        ids.append((await h.queue.add(job)).id)
    later = h.job("Later")
    later.output.path = share / "deep" / "Later.mkv"
    retried = await h.queue.add(later)
    await h.queue.cancel(retried.id)  # waiting → cancelled; retried below, while jobs run
    await h.queue.reorder(list(reversed(ids)))
    began = time.monotonic()
    h.queue.start()
    start_took = time.monotonic() - began
    await h.queue.retry(retried.id)
    ended = await h.queue.wait([*ids, retried.id])
    beating = False
    await beat
    monkeypatch.undo()
    print(f"start() took {start_took:.3f} s; the longest event-loop pause {max(gaps):.3f} s")
    assert on_loop == []
    assert start_took < LOOP_DELAY
    assert max(gaps) < LOOP_DELAY
    assert [job.state for job in ended] == [JobState.DONE] * 4


async def test_a_restored_job_gets_its_keys_off_the_event_loop(
    harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A restored waiting job has no keys yet: they are read in the background when the store
    is opened, and the job runs once they are there."""
    h = harness
    h.scenario(DONE_QUICKLY)
    share = tmp_path / "share"
    share.mkdir()
    job = h.job("Restored")
    job.output.path = share / "Restored.mkv"
    waiting = await h.queue.add(job)
    await h.queue.close()
    on_loop = slow_share(monkeypatch, share, threading.get_ident())
    again = queue_at(h)
    try:
        assert [j.state for j in again.list()] == [JobState.WAITING]  # opens the store
        again.start()
        [ended] = await again.wait([waiting.id])
    finally:
        await again.close()
    monkeypatch.undo()
    assert on_loop == []
    assert ended.state is JobState.DONE


async def test_busy_while_a_restored_job_waits_for_its_keys(
    harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A started queue whose restored job is still having its keys read (a share that does not
    answer) runs nothing yet, but the start targets the job, so idle exit must wait."""
    h = harness
    h.scenario(DONE_QUICKLY)
    share = tmp_path / "share"
    share.mkdir()
    job = h.job("Restored")
    job.output.path = share / "Restored.mkv"
    waiting = await h.queue.add(job)
    await h.queue.close()
    answer = threading.Event()
    loop_thread = threading.get_ident()

    def held(real: Callable[..., os.stat_result]) -> Callable[..., os.stat_result]:
        def call(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
            text = os.fspath(path) if isinstance(path, (str, os.PathLike)) else None
            on_share = isinstance(text, str) and text.startswith(str(share))
            if on_share and threading.get_ident() != loop_thread:
                answer.wait(10)
            return real(path, *args, **kwargs)

        return call

    monkeypatch.setattr(os, "stat", held(os.stat))
    monkeypatch.setattr(os, "lstat", held(os.lstat))
    again = queue_at(h)
    try:
        again.list()
        again.start()
        await asyncio.sleep(0.1)
        assert again.busy
        assert again.get(waiting.id).state is JobState.WAITING  # type: ignore[union-attr]
        answer.set()
        [ended] = await again.wait([waiting.id])
    finally:
        answer.set()
        await again.close()
    monkeypatch.undo()
    assert ended.state is JobState.DONE


async def test_the_keys_are_what_the_rule_compares(harness: Harness, tmp_path: Path) -> None:
    """``_conflicts`` with the keys the queue keeps gives what it gives with keys read now, and
    the keys of an in-place edit are its source."""
    h = harness
    edit = queued(in_place_job(h), "edit")
    encode = queued(h.job("Encode"), "encode")
    other = queued(h.job("Other"), "other")
    other.settings.source = SourceRef(path=tmp_path / "media" / "Another.mkv")
    job_keys = service._job_keys
    keys = job_keys(edit)
    assert keys.output == keys.source == _source_key(edit) == _output_key(edit)
    for job, expected in ((encode, True), (other, False)):
        assert _conflicts(job, [active_for(edit)], job_keys(job)) is expected
        assert _conflicts(job, [active_for(edit)]) is expected


NUL_MESSAGE = "has a NUL character, which no file system allows, so the job cannot run"


def test_python_facts_behind_the_rule(tmp_path: Path) -> None:
    """``abspath`` takes a NUL character; ``stat`` and, on POSIX, ``realpath`` raise
    ``ValueError``, not ``OSError``."""
    bad = tmp_path / "Mo\0vie.mkv"
    assert "\0" in os.path.abspath(bad)
    with pytest.raises(ValueError, match="embedded null"):
        os.stat(bad)
    if os.name != "nt":
        with pytest.raises(ValueError, match="embedded null"):
            os.path.realpath(bad)


def test_no_key_function_raises_for_a_path_with_a_nul(tmp_path: Path) -> None:
    bad = tmp_path / "Mo\0vie.mkv"
    assert files.same_file(bad, bad)
    assert not files.same_file(bad, tmp_path / "Movie.mkv")
    assert files.remove_files([bad]) == [f"{os.fspath(bad)!r} could not be removed: " + _nul(bad)]
    key = files.file_key(bad)
    assert key.identity is None


def _nul(path: Path) -> str:
    try:
        path.unlink(missing_ok=True)
    except ValueError as exc:
        return str(exc)
    raise AssertionError("unlink accepted a NUL character")


async def test_a_nul_in_a_path_fails_its_job_and_the_queue_goes_on(harness: Harness) -> None:
    h = harness
    h.scenario(DONE_QUICKLY)
    bad = await h.queue.add(h.job("Mo\0vie"))
    assert bad.state is JobState.FAILED
    assert [issue.code for issue in bad.issues] == ["queue.path_unusable"]
    assert NUL_MESSAGE in (bad.error or "")
    h.queue.start()
    assert (await h.queue.retry(bad.id)).state is JobState.WAITING
    good = await h.queue.add(h.job("Good"))
    h.queue.start()
    ended = {job.id: job for job in await h.queue.wait([bad.id, good.id])}
    assert ended[good.id].state is JobState.DONE
    assert ended[bad.id].state is JobState.FAILED
    assert "The output path" in (ended[bad.id].error or "")
    assert NUL_MESSAGE in (ended[bad.id].error or "")


async def test_a_nul_in_the_source_path_is_a_clean_failure(harness: Harness) -> None:
    h = harness
    job = h.job("Movie")
    job.source = SourceRef(path=Path(f"{h.source_path}\0x"))
    added = await h.queue.add(job)
    assert added.state is JobState.FAILED
    assert [issue.code for issue in added.issues] == ["queue.path_unusable"]
    assert (added.error or "").startswith("The job has errors: The source path")


async def test_a_restored_job_with_a_nul_in_its_path(harness: Harness) -> None:
    h = harness
    h.scenario(DONE_QUICKLY)
    bad = await h.queue.add(h.job("Mo\0vie"))
    await h.queue.retry(bad.id)  # waiting: the queue was never started
    crashed = await h.queue.add(h.job("Cr\0shed"))
    good = await h.queue.add(h.job("Good"))
    await h.queue.close()
    stored = h.queue.get(crashed.id)
    assert stored is not None
    stored.state = JobState.RUNNING
    stored.plan = h.plan(h.job("Cr\0shed"))
    assert "\0" in str(stored.plan.output_tmp)
    store_rows(h, stored)
    again = queue_at(h)
    try:
        states = {job.id: job.state for job in again.list()}  # opens the store
        assert states == {
            bad.id: JobState.WAITING,
            crashed.id: JobState.INTERRUPTED,
            good.id: JobState.WAITING,
        }
        restored = again.get(crashed.id)
        assert restored is not None
        again._remove_leftovers([restored])  # what the background clean-up runs
        again.start()
        ended = {job.id: job for job in await again.wait([bad.id, good.id])}
    finally:
        await again.close()
    assert ended[good.id].state is JobState.DONE
    assert ended[bad.id].state is JobState.FAILED
    assert NUL_MESSAGE in (ended[bad.id].error or "")


async def test_the_conflict_rule_takes_a_nul_path(harness: Harness) -> None:
    h = harness
    bad = queued(h.job("Mo\0vie"), "bad")
    other = queued(h.job("Mo\0vie"), "other")
    assert _conflicts(bad, [active_for(other)])  # the same path, as written
    assert not _conflicts(bad, [active_for(queued(h.job("Good"), "good"))])


def zero_file_index(monkeypatch: pytest.MonkeyPatch, volume: Path) -> None:
    real_stat = os.stat
    prefix = str(volume)

    def stat(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
        result = real_stat(path, *args, **kwargs)
        if isinstance(path, (str, os.PathLike)) and os.fspath(path).startswith(prefix):
            fields = list(result)
            fields[1], fields[2] = 0, 7  # st_ino, st_dev
            return os.stat_result(fields)
        return result

    monkeypatch.setattr(os, "stat", stat)


async def test_a_zero_file_index_is_no_identity(
    harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness
    other = tmp_path / "media" / "Other.mkv"
    other.write_bytes(b"another file")
    part = tmp_path / "out" / "Movie.part.mkv"
    part.write_bytes(b"part")
    edit = queued(in_place_job(h), "edit")
    encode = queued(h.job("Encode"), "encode")
    encode.settings.source = SourceRef(path=other)
    zero_file_index(monkeypatch, tmp_path)
    assert not _conflicts(encode, [active_for(edit)])
    assert not files.same_file(other, h.source_path)
    assert runner._writes_source(h.plan(h.job("Movie")), h.source_path) is None
    assert files.remove_files([part], keep=h.source_path) == []
    assert not part.exists()
    assert files.same_file(h.source_path, h.source_path)  # the path still decides
    assert files.file_key(other).identity is None
