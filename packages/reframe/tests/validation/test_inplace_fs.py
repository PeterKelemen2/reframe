"""``writable_file`` of the file-system views, as validation and the queue's runner use it."""

from __future__ import annotations

import os
import sys
from pathlib import Path, PurePath, PureWindowsPath
from typing import Any

import pytest

from reframe.metadata import remux_job
from reframe.models import ReplaceOp
from reframe.queue import files
from reframe.validation import FileSystemView, LocalFileSystem
from reframe.validation.inplace import source_writable

from . import scenario as sc

root_user = hasattr(os, "geteuid") and os.geteuid() == 0


def test_local_writable_file(tmp_path: Path) -> None:
    local = LocalFileSystem()
    file = tmp_path / "a.mkv"
    assert not local.writable_file(file)  # missing
    file.write_bytes(b"x")
    assert local.writable_file(file)
    assert not local.writable_file(tmp_path)  # a folder
    if sys.platform != "win32" and not root_user:
        file.chmod(0o444)
        try:
            assert not local.writable_file(file)
        finally:
            file.chmod(0o644)


@pytest.mark.skipif(root_user, reason="root can open a read-only file for writing")
def test_local_writable_file_on_windows_opens_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On Windows ``os.access`` sees only the read-only attribute, so the file is opened for
    update instead."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(os, "access", lambda *a, **k: True)
    file = tmp_path / "a.mkv"
    file.write_bytes(b"content")
    local = LocalFileSystem()
    assert local.writable_file(file)
    assert file.read_bytes() == b"content"  # opened for update: not truncated
    file.chmod(0o444)
    try:
        assert not local.writable_file(file)  # the open fails: not writable
    finally:
        file.chmod(0o644)


class WindowsView:
    """A view of a Windows file system: read-only files by case-insensitive name."""

    def __init__(self, readonly: set[str]) -> None:
        self.readonly = {name.casefold() for name in readonly}

    def writable_file(self, path: PurePath) -> bool:
        return str(PureWindowsPath(path)).casefold() not in self.readonly


def test_source_writable_asks_the_view_with_windows_paths() -> None:
    view = WindowsView({r"C:\Media\Show.mkv"})
    assert not source_writable(view, PureWindowsPath(r"c:\media\SHOW.mkv"))  # type: ignore[arg-type]
    assert source_writable(view, PureWindowsPath(r"C:\Media\Other.mkv"))  # type: ignore[arg-type]


def test_every_view_answers_writable_file() -> None:
    source = PurePath("/media/Show.mkv")
    fake: FileSystemView = sc.FakeFs(files=[source], readonly=[PurePath("/media/Locked.mkv")])
    assert fake.writable_file(source)
    assert not fake.writable_file(PurePath("/media"))  # a folder
    assert not fake.writable_file(PurePath("/media/Missing.mkv"))
    locked = sc.FakeFs(
        files=[PurePath("/media/Locked.mkv")], readonly=[PurePath("/media/Locked.mkv")]
    )
    assert not locked.writable_file(PurePath("/media/Locked.mkv"))
    assert not source_writable(locked, PurePath("/media/Locked.mkv"))


@pytest.mark.skipif(root_user, reason="root can open a read-only file for writing")
def test_runner_check_is_the_local_view(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The queue's run-time check is the validation view's test, also on Windows."""
    file = tmp_path / "a.mkv"
    file.write_bytes(b"content")
    assert files.writable_file(file)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(os, "access", lambda *a, **k: True)
    assert files.writable_file(file)
    file.chmod(0o444)
    try:
        assert not files.writable_file(file)
    finally:
        file.chmod(0o644)
    assert file.read_bytes() == b"content"


def in_place() -> Any:
    s = sc.base()
    s.job = remux_job(s.job, s.source, edit_in_place=True)
    return s


def test_read_only_source_fix_writes_a_new_file_with_a_new_path() -> None:
    s = in_place()
    s.fs.writable_file = lambda path: False
    [issue] = [i for i in s.validate() if i.code == "inplace.source_not_writable"]
    fix = issue.fixes[0]
    assert fix.label.startswith("Write a new file (")
    ops = {op.path: op.value for op in fix.patch if isinstance(op, ReplaceOp)}
    assert ops["/output/edit_in_place"] is False
    assert ops["/output/path"] != str(s.source.ref.path)
    after = s.apply(fix).validate()
    assert not sc.found(after, "inplace.source_not_writable")
    assert not sc.found(after, "output.same_as_source")


def test_read_only_source_through_the_view() -> None:
    s = in_place()
    s.fs.writable_file = lambda path: False
    assert sc.found(s.validate(), "inplace.source_not_writable")
