"""The output path rules on both OSes (with the fake file system) and the real file system view.

Windows paths are :class:`~pathlib.PureWindowsPath` on a case-insensitive fake file system:
drive roots, a drive that is not connected, the same file through another spelling.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from types import SimpleNamespace
from typing import Any

import pytest

import reframe.validation.fs as fs_module
from reframe.command import build_plan
from reframe.models import AverageBitrate, ChapterSettings, ReplaceOp, Severity, SourceRef
from reframe.platform import longpath
from reframe.validation import LocalFileSystem, next_free_path
from reframe.validation.output import (
    existing_ancestor,
    output_path_issues,
    source_clash,
    written_paths,
)
from reframe_testing.links import needs_symlinks

from . import scenario as sc

#: chmod has no effect on Windows, and root ignores it.
NO_POSIX_PERMISSIONS = sys.platform == "win32" or getattr(os, "geteuid", lambda: 0)() == 0
MKV = sc.DEFS.containers["mkv"]
W = PureWindowsPath


def codes(issues: list[Any]) -> list[str]:
    return [i.code for i in issues]


def errors(issues: list[Any]) -> list[str]:
    return [i.code for i in issues if i.severity is Severity.ERROR]


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


def test_an_output_windows_refuses_is_not_writable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(longpath, "long_paths_enabled", lambda: False)
    near = W("C:\\Out\\" + "x" * 245 + ".mkv")  # 256 characters, its .part file 261
    issues = check(near, SOURCE, windows_fs())
    assert errors(issues) == ["output.not_writable"]
    assert ".part" in issues[0].message
    assert "Windows refuses this path" in issues[0].message
    deep = W("C:\\Out\\" + "y" * 241 + "\\Movie.mkv")  # a 248-character folder to make
    (issue,) = check(deep, SOURCE, windows_fs())
    assert issue.code == "output.not_writable"
    assert "makes the folder" in issue.message
    assert check(W("C:\\Out\\Movie.mkv"), SOURCE, windows_fs()) == []


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
    # Windows removes "sub\.." from the path before it looks for "sub".
    no_sub = tmp_path / "sub" / ".." / "Movie.mkv"
    assert local.same_file(movie, no_sub) is (sys.platform == "win32")
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
    """The Windows branch runs here with a patched platform."""
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


def test_the_partial_file_is_the_source() -> None:
    """The builder would write ``Foo.part.mkv`` (the source), and the queue would remove it."""
    source = Path("/media/Foo.part.mkv")
    fs = sc.FakeFs(files=[source], dirs=[Path("/media")])
    [issue] = check(Path("/media/Foo.mkv"), source, fs)
    assert (issue.code, issue.severity) == ("output.same_as_source", Severity.ERROR)
    assert "Foo.part.mkv" in issue.message
    [fix] = issue.fixes
    [op] = fix.patch
    assert isinstance(op, ReplaceOp)
    assert isinstance(op.value, str)
    assert source_clash(Path(op.value), source, fs) is None
    assert check(Path(op.value), source, fs) == []


@pytest.mark.parametrize(
    "source_name", ["Foo.part.chapters.txt", "Foo.part.passlog", "Foo.part.passlog-0.log"]
)
def test_plan_and_statistics_files_are_the_source(source_name: str) -> None:
    source = Path("/media") / source_name
    fs = sc.FakeFs(files=[source], dirs=[Path("/media")])
    assert codes(check(Path("/media/Foo.mkv"), source, fs)) == ["output.same_as_source"]


def test_written_paths_are_the_builders() -> None:
    s = sc.base()
    s.job.video.encoder = "libx265"
    s.job.video.rate_control = AverageBitrate(kbps=2000, two_pass=True)
    s.job.chapters = ChapterSettings(generate_every=60.0)
    plan = build_plan(s.job, s.source, s.caps, s.tools)
    planned = {plan.output_final, plan.output_tmp, *(f.path for f in plan.files), *plan.temp_files}
    assert planned <= set(written_paths(Path(str(s.job.output.path))))


def test_windows_spelling_of_the_partial_file() -> None:
    source = W("C:\\Videos\\FOO.PART.MKV")
    fs = sc.FakeFs(files=[source], dirs=[W("C:\\Videos")], case_insensitive=True)
    assert codes(check(W("c:\\videos\\foo.mkv"), source, fs)) == ["output.same_as_source"]


@needs_symlinks
@pytest.mark.parametrize("source_name", ["Foo.mkv", "Foo.part.mkv"])
def test_output_folder_linked_to_the_source_folder(tmp_path: Path, source_name: str) -> None:
    """The output folder is a symlink to the source's folder (a string compare misses it);
    the real file system finds the same file."""
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    os.symlink(real, link)
    source = real / source_name
    source.write_bytes(b"x")
    issues = check(link / "Foo.mkv", source, LocalFileSystem())
    assert errors(issues) == ["output.same_as_source"]


def test_reserved_name_is_an_error_for_a_windows_path() -> None:
    fs = sc.FakeFs(files=[W("C:\\Videos\\Movie.mkv")], dirs=[W("C:\\Out")], case_insensitive=True)
    issues = check(W("C:\\Out\\con.mkv"), W("C:\\Videos\\Movie.mkv"), fs)
    [issue] = [i for i in issues if i.code == "output.name_not_portable"]
    assert issue.severity is Severity.ERROR
    assert issue.fixes[0].label == "Save as con_.mkv"


def test_too_long_name_counts_the_partial_suffix() -> None:
    s = sc.base()
    s.job.output.path = Path("/out") / ("é" * 124 + ".mkv")  # 252 bytes; .part.mkv: 257
    [issue] = [i for i in sc.check(s) if i.code == "output.name_too_long"]
    assert "partial file name" in issue.message
    s.job.output.path = Path("/out") / ("é" * 123 + ".mkv")  # .part.mkv: 255 bytes
    assert "output.name_too_long" not in codes(sc.check(s))


def test_a_byte_that_is_not_utf8_in_the_name_is_not_portable() -> None:
    """``bad\\xffname.mkv`` on POSIX is ``bad\\udcffname.mkv`` in Python (PEP 383). An error for a
    Windows path."""
    s = sc.base()
    s.job.output.path = Path("/out/bad\udcffname.mkv")
    issues = sc.check(s)
    windows = sys.platform == "win32"
    assert sc.error_codes(issues) == ({"output.name_not_portable"} if windows else set())
    [issue] = [i for i in issues if i.code == "output.name_not_portable"]
    assert issue.severity is (Severity.ERROR if windows else Severity.WARNING)
    assert issue.fixes[0].label == "Save as bad�name.mkv"
    issue.model_dump_json()  # the message holds no lone surrogate


def test_a_byte_that_is_not_utf8_counts_as_one_byte() -> None:
    s = sc.base()
    s.job.output.path = Path("/out") / ("\udcff" * 246 + ".mkv")  # .part.mkv: 255 bytes
    assert not sc.found(s.validate(), "output.name_too_long")
    s.job.output.path = Path("/out") / ("\udcff" * 247 + ".mkv")
    assert sc.found(s.validate(), "output.name_too_long")


def test_source_ref_is_used_for_the_clash() -> None:
    s = sc.base()
    s.job.source = SourceRef(path=Path("/out/Movie (2019).part.mkv"))
    s.fs.add_file(Path("/out/Movie (2019).part.mkv"))
    assert "output.same_as_source" in errors(s.validate())
