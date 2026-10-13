"""The output path rules on both OSes (with the fake file system) and the real file system view.

Windows paths are :class:`~pathlib.PureWindowsPath` on a case-insensitive fake file system:
drive roots, a drive that is not connected, the same file through another spelling.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

import reframe.validation.fs as fs_module
from reframe.validation import LocalFileSystem, next_free_path
from reframe.validation.output import existing_ancestor, output_path_issues


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
#: chmod has no effect on Windows, and root ignores it.
NO_POSIX_PERMISSIONS = sys.platform == "win32" or getattr(os, "geteuid", lambda: 0)() == 0
MKV = sc.DEFS.containers["mkv"]
W = PureWindowsPath


def codes(issues: list[Any]) -> list[str]:
    return [i.code for i in issues]


def windows_fs(**kw: Any) -> Any:
    return sc.FakeFs(
        files=[W("C:\\Videos\\Movie.mkv")],
        dirs=[W("C:\\Out"), W("D:\\")],
        case_insensitive=True,
        **kw,
    )


def check(path: PurePath, source: PurePath, fs: Any, collision: str = "auto_rename") -> Any:
    return output_path_issues(
        path,
        source,
        fs,
        container=MKV,
        collision=collision,  # type: ignore[arg-type]
    )


SOURCE = W("C:\\Videos\\Movie.mkv")


def test_windows_drive_root_is_a_folder() -> None:
    assert check(W("D:\\Movie.mkv"), SOURCE, windows_fs()) == []
    assert existing_ancestor(W("D:\\"), windows_fs()) == W("D:\\")


def test_windows_drive_not_connected() -> None:
    issues = check(W("E:\\Movies\\Movie.mkv"), SOURCE, windows_fs())
    assert codes(issues) == ["output.folder_missing"]
    assert "E:\\ does not exist" in issues[0].message
    (fix,) = issues[0].fixes
    assert fix.label == "Save next to the source"
    assert fix.patch[0].value == "C:\\Videos\\Movie (1).mkv"


def test_windows_folders_below_the_drive_are_created() -> None:
    assert check(W("C:\\Out\\Films\\2019\\Movie.mkv"), SOURCE, windows_fs()) == []


def test_windows_same_file_through_another_spelling() -> None:
    issues = check(W("c:\\videos\\MOVIE.MKV"), SOURCE, windows_fs())
    assert codes(issues) == ["output.same_as_source"]
    assert issues[0].fixes[0].label == "Save as MOVIE (1).MKV"


def test_case_sensitive_file_system_other_spelling_is_another_file() -> None:
    fs = sc.FakeFs(files=[PurePosixPath("/v/Movie.mkv")])
    assert check(PurePosixPath("/v/movie.mkv"), PurePosixPath("/v/Movie.mkv"), fs) == []


def test_windows_collision_is_case_insensitive() -> None:
    fs = windows_fs()
    fs.add_file(W("C:\\Out\\Film.mkv"))
    fs.add_file(W("C:\\Out\\film (1).mkv"))
    issues = check(W("C:\\Out\\FILM.mkv"), SOURCE, fs, "ask")
    assert codes(issues) == ["output.exists"]
    assert issues[0].fixes[0].label == "Save as FILM (2).mkv"


def test_windows_read_only_folder() -> None:
    fs = windows_fs(readonly=[W("c:\\out")])
    issues = check(W("C:\\Out\\Movie.mkv"), SOURCE, fs)
    assert codes(issues) == ["output.not_writable"]
    assert "C:\\Out" in issues[0].message


def test_existing_ancestor_stops_at_the_root() -> None:
    empty = sc.FakeFs()
    assert existing_ancestor(W("E:\\a\\b"), empty) is None
    assert existing_ancestor(PurePosixPath("/a/b"), empty) is None


def test_next_free_path() -> None:
    fs = sc.FakeFs(files=[PurePosixPath("/o/a (1).mkv"), PurePosixPath("/o/a (2).mkv")])
    assert next_free_path(PurePosixPath("/o/a.mkv"), fs) == PurePosixPath("/o/a (3).mkv")
    assert next_free_path(PurePosixPath("/o/a.mkv"), fs, limit=1) == PurePosixPath("/o/a (2).mkv")


def test_no_fix_to_the_source_folder_when_it_is_read_only() -> None:
    fs = sc.FakeFs(
        files=[PurePosixPath("/v/Movie.mkv")],
        dirs=[PurePosixPath("/out")],
        readonly=[PurePosixPath("/v"), PurePosixPath("/out")],
    )
    issues = check(PurePosixPath("/out/Movie.mkv"), PurePosixPath("/v/Movie.mkv"), fs)
    assert codes(issues) == ["output.not_writable"]
    assert issues[0].fixes == []


# --------------------------------------------------------------------------- LocalFileSystem


def test_local_file_system(tmp_path: Path) -> None:
    local = LocalFileSystem()
    movie = tmp_path / "Movie.mkv"
    movie.write_bytes(b"x")
    assert local.exists(movie)
    assert not local.exists(tmp_path / "nope.mkv")
    assert local.is_dir(tmp_path)
    assert not local.is_dir(movie)
    assert local.writable_dir(tmp_path)
    assert not local.writable_dir(movie)
    assert not local.writable_dir(tmp_path / "missing")
    free = local.free_bytes(tmp_path)
    assert free is not None
    assert free > 0
    assert local.free_bytes(tmp_path / "missing") is None
    assert local.same_file(movie, tmp_path / "sub" / ".." / "Movie.mkv") is False  # no "sub"
    (tmp_path / "sub").mkdir()
    assert local.same_file(movie, tmp_path / "sub" / ".." / "Movie.mkv")
    os.link(movie, tmp_path / "hardlink.mkv")
    assert local.same_file(movie, tmp_path / "hardlink.mkv")
    assert not local.same_file(movie, tmp_path / "missing.mkv")
    assert local.list_files(tmp_path) == ["Movie.mkv", "hardlink.mkv"]


@pytest.mark.skipif(NO_POSIX_PERMISSIONS, reason="POSIX permissions")
def test_local_read_only_folder(tmp_path: Path) -> None:
    folder = tmp_path / "ro"
    folder.mkdir()
    folder.chmod(0o500)
    try:
        assert not LocalFileSystem().writable_dir(folder)
    finally:
        folder.chmod(0o700)


@pytest.mark.skipif(NO_POSIX_PERMISSIONS, reason="POSIX permissions")
def test_local_windows_branch_creates_a_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On Windows, ``writable_dir`` creates (and deletes) a temporary file, because
    ``os.access`` does not read ACLs there. The branch runs here with a patched platform."""
    monkeypatch.setattr(fs_module, "sys", SimpleNamespace(platform="win32"))
    local = LocalFileSystem()
    assert local.writable_dir(tmp_path)
    assert list(tmp_path.iterdir()) == []  # the probe file is gone
    folder = tmp_path / "ro"
    folder.mkdir()
    folder.chmod(0o500)
    try:
        assert not local.writable_dir(folder)
    finally:
        folder.chmod(0o700)
