"""The queue's job keys through links (core-complete review R4-1; decisions 0016 and 0034).

One file reached through a symbolic link, a hard link or a linked folder is one file for the
queue's rules: an encode never reads a file while it is edited in place, two in-place edits of
one file run one after the other, and two jobs that write the same ``.part`` file never run at
once. The keys are the paths with their links resolved; two keys are the same file when they
are equal, equal without case, or ``os.path.samefile`` (hard links; on Windows ``os.stat``
gives the volume serial number and the file index, mocked here).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

from reframe.metadata import remux_job
from reframe.models import JobSettings, JobState, SourceRef
from reframe.queue import service
from reframe.queue.service import _conflicts, _output_key, _source_key
from reframe_testing import fake_tools as ft

from .conftest import Harness, encode_rule, tool_set
from .test_in_place_scheduling import active_for, ended_before_started, in_place_job, queued

pytestmark = pytest.mark.anyio

needs_symlinks = pytest.mark.skipif(
    sys.platform == "win32", reason="creating a symbolic link needs a privilege on Windows"
)


def _in_place_job_at(h: Harness, path: Path, name: str) -> JobSettings:
    """An in-place edit of the harness source, spelled as ``path``."""
    source = h.sources.source.model_copy(update={"ref": SourceRef(path=path)}, deep=True)
    job = remux_job(JobSettings(source=SourceRef(path=path)), source)
    job.audio[0].metadata.name = name
    return job


# --------------------------------------------------------------------------- the rule


@needs_symlinks
async def test_a_symlink_to_the_source_is_the_same_file(harness: Harness, tmp_path: Path) -> None:
    """An encode that reads the source through a link must not run while the source is
    edited in place (0034 follow-up: no job reads a file while it is edited in place)."""
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
    """0016: two jobs with the same output never run at once (both write the same .part)."""
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
    """``os.stat`` of each of ``paths`` gives one ``(st_ino, st_dev)``: what Windows reports
    (the file index and the volume serial number) for two hard links of one file."""
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
    """Two paths whose ``os.stat`` gives the same ``(st_dev, st_ino)`` are one file. On
    Windows that pair is the volume serial number and the file index (a hard link there has
    the same index); mocked, so it runs on every OS."""
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


# --------------------------------------------------------------------------- the queue


@needs_symlinks
async def test_two_in_place_edits_through_a_link_run_one_after_the_other(
    harness: Harness, tmp_path: Path
) -> None:
    h = harness
    h.settings.queue.parallel_jobs = 2
    h.tools.tools = tool_set(h.fake.ffmpeg, mkvpropedit=h.fake.ffmpeg)
    link = tmp_path / "media" / "link-to-source.mkv"
    link.symlink_to(h.source_path)
    first = await h.queue.add(in_place_job(h, "One"))
    second = await h.queue.add(_in_place_job_at(h, link, "Two"))
    assert second.state is JobState.WAITING, second.issues
    h.queue.start()
    await h.queue.wait([first.id, second.id])
    assert ended_before_started(h, first.id, second.id)


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
