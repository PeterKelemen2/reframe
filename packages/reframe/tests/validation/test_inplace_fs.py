"""``writable_file`` of the file-system views (C-13 follow-up of decision 0034): the real file
system on POSIX and (mocked) on Windows, a fake view with Windows paths, and how
``inplace.source_writable`` and the ``tool.mkvpropedit_missing`` fix use it."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path, PurePath, PureWindowsPath
from types import ModuleType
from typing import Any

import pytest

from reframe.metadata import remux_job
from reframe.models import ReplaceOp, ToolStatus
from reframe.validation import LocalFileSystem
from reframe.validation.fs import WritableFiles
from reframe.validation.inplace import source_writable


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"_reframe_validation_{name}", Path(__file__).with_name(f"{name}.py")
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sc = _load("scenario")

root_user = hasattr(os, "geteuid") and os.geteuid() == 0


def test_local_writable_file(tmp_path: Path) -> None:
    local = LocalFileSystem()
    assert isinstance(local, WritableFiles)
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
    update instead (mocked: ``sys.platform`` and ``os.access`` that would say yes)."""
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
    assert isinstance(view, WritableFiles)
    assert not source_writable(view, PureWindowsPath(r"c:\media\SHOW.mkv"))  # type: ignore[arg-type]
    assert source_writable(view, PureWindowsPath(r"C:\Media\Other.mkv"))  # type: ignore[arg-type]
    assert source_writable(object(), PureWindowsPath(r"C:\x.mkv"))  # type: ignore[arg-type]


def in_place() -> Any:
    s = sc.base()
    s.job = remux_job(s.job, s.source, edit_in_place=True)
    return s


def test_mkvpropedit_missing_fix_writes_a_new_file_with_a_new_path() -> None:
    s = in_place()
    s.tools = sc.make_tools(mkvpropedit=sc.tool("mkvpropedit", ToolStatus.MISSING))
    [issue] = [i for i in s.validate() if i.code == "tool.mkvpropedit_missing"]
    fix = issue.fixes[0]
    assert fix.label.startswith("Write a new file (")
    ops = {op.path: op.value for op in fix.patch if isinstance(op, ReplaceOp)}
    assert ops["/output/edit_in_place"] is False
    assert ops["/output/path"] != str(s.source.ref.path)
    after = s.apply(fix).validate()
    assert not sc.found(after, "tool.mkvpropedit_missing")
    assert not sc.found(after, "output.same_as_source")


def test_read_only_source_through_the_view() -> None:
    s = in_place()
    s.fs.writable_file = lambda path: False
    assert sc.found(s.validate(), "inplace.source_not_writable")
