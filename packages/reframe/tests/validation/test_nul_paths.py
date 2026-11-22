"""A NUL character in a path: no ``LocalFileSystem`` method raises for it, and validation reports
a clean error."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from reframe.models import AppSettings, NamingOptions, Severity, SourceRef, ValidationIssue
from reframe.validation import LocalFileSystem, validate
from reframe.validation.dryrun import dry_run
from reframe.validation.output import output_path_issues

from . import scenario as sc

MKV = sc.DEFS.containers["mkv"]


def _raises_value_error(call: Callable[[], object]) -> bool:
    try:
        call()
    except ValueError:
        return True
    return False


def test_python_facts_behind_the_rule(tmp_path: Path) -> None:
    """Recorded with the project's interpreter: the ``exists`` / ``is*`` tests answer ``False``
    for a NUL path (since Python 3.8), every call that passes the path to the OS raises
    ``ValueError``, and ``abspath`` takes it unchanged. On Windows ``realpath`` and ``resolve``
    give the path back instead: they ignore the error unless ``strict``."""
    nul = tmp_path / "Mo\0vie.mkv"
    assert not os.path.exists(nul)
    assert not os.path.lexists(nul)
    assert not os.path.isdir(nul)
    assert not os.path.isfile(nul)
    assert not nul.exists()
    assert not nul.is_file()
    assert not nul.is_dir()
    assert os.path.abspath(nul) == str(nul)
    raising: dict[str, Callable[[], object]] = {
        "os.stat": lambda: os.stat(nul),
        "Path.stat": nul.stat,
        "os.path.samefile": lambda: os.path.samefile(nul, tmp_path),
        "os.access": lambda: os.access(nul, os.W_OK),
        "shutil.disk_usage": lambda: shutil.disk_usage(nul),
        "os.scandir": lambda: os.scandir(nul),
        "open": lambda: open(nul, "rb"),  # noqa: SIM115
        "tempfile.TemporaryFile": lambda: tempfile.TemporaryFile(dir=nul),  # noqa: SIM115
    }
    resolving: dict[str, Callable[[], object]] = {
        "os.path.realpath": lambda: os.path.realpath(nul),
        "Path.resolve": nul.resolve,
    }
    if sys.platform == "win32":
        assert [os.path.basename(str(call())) for call in resolving.values()] == [nul.name] * 2
    else:
        raising |= resolving
    assert [name for name, call in raising.items() if not _raises_value_error(call)] == []


@pytest.mark.parametrize("where", ["name", "folder"])
def test_no_local_file_system_method_raises_for_a_nul(tmp_path: Path, where: str) -> None:
    """A NUL path is a path that does not exist: ``False`` / ``None``, never ``ValueError``."""
    real = tmp_path / "Movie.mkv"
    real.write_bytes(b"x")
    nul = tmp_path / "Mo\0vie.mkv" if where == "name" else tmp_path / "fol\0der" / "Movie.mkv"
    fs = LocalFileSystem()
    assert fs.exists(nul) is False
    assert fs.is_dir(nul) is False
    assert fs.is_dir(nul.parent) is (where == "name")
    assert fs.writable_dir(nul) is False
    assert fs.writable_file(nul) is False
    assert fs.free_bytes(nul) is None
    assert fs.same_file(nul, real) is False
    assert fs.same_file(real, nul) is False
    assert fs.same_file(nul, nul) is False
    assert fs.list_files(nul) is None
    assert fs.list_files(tmp_path / "fol\0der") is None
    assert fs.file_times(nul) is None


@pytest.mark.parametrize("where", ["name", "folder"])
def test_no_local_file_system_method_raises_for_a_nul_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    """The Windows branches (a temporary file to test a folder, an open for update to test a
    file; mocked ``sys.platform``) do not raise either."""
    monkeypatch.setattr(sys, "platform", "win32")
    nul = tmp_path / "Mo\0vie.mkv" if where == "name" else tmp_path / "fol\0der" / "Movie.mkv"
    fs = LocalFileSystem()
    assert fs.writable_dir(nul) is False
    assert fs.writable_file(nul) is False


def _issues(job_output: Path | None, source: Path, settings: AppSettings | None = None) -> Any:
    media = sc.make_source(source)
    job = sc.make_job(media)
    job.output.path = job_output
    return validate(
        job,
        media,
        sc.make_caps(),
        sc.make_tools(),
        LocalFileSystem(),
        settings=settings,
        definitions=sc.DEFS,
    )


def _no_rule_failed(issues: list[ValidationIssue]) -> None:
    assert [i for i in issues if i.code == "validation.rule_failed"] == []


def test_a_nul_in_the_output_name_is_a_clean_error(tmp_path: Path) -> None:
    source = tmp_path / "Movie.mkv"
    source.write_bytes(b"x")
    output = tmp_path / "out" / "Mo\0vie.mkv"
    (tmp_path / "out").mkdir()
    issues = _issues(output, source)
    _no_rule_failed(issues)
    [issue] = [i for i in issues if i.severity is Severity.ERROR]
    assert issue.code == "output.not_writable"
    assert issue.path == "output.path"
    shown = str(output).replace("\0", "\\0")
    assert issue.message == (
        f"The output path {shown} has a NUL character, which no file system allows: the file "
        "cannot be created. Correct the path."
    )
    # The safe name drops the control character: the fix's path is a clean one.
    [fix] = issue.fixes
    assert fix.label == "Save as Movie.mkv"
    assert [op.model_dump(mode="json") for op in fix.patch] == [
        {"op": "replace", "path": "/output/path", "value": str(tmp_path / "out" / "Movie.mkv")}
    ]
    # No other output issue about the same path (a name that Windows does not allow).
    assert [i.code for i in issues if i.path == "output.path"] == ["output.not_writable"]


def test_a_nul_in_the_output_folder_is_a_clean_error(tmp_path: Path) -> None:
    """A NUL in a folder name: no fix (removing it names another folder)."""
    source = tmp_path / "Movie.mkv"
    source.write_bytes(b"x")
    output = tmp_path / "fol\0der" / "Movie.mkv"
    issues = _issues(output, source)
    _no_rule_failed(issues)
    [issue] = [i for i in issues if i.severity is Severity.ERROR]
    assert (issue.code, issue.path, issue.fixes) == ("output.not_writable", "output.path", [])
    assert "has a NUL character" in issue.message


def test_output_path_issues_with_a_nul_asks_the_view_nothing() -> None:
    """The check comes first and needs no file-system read (a fake view that fails on every
    call is never asked)."""

    class Refuse:
        def __getattr__(self, name: str) -> Any:
            raise AssertionError(f"the view was asked {name}")

    issues = output_path_issues(
        Path("/out/Mo\0vie.mkv"),
        sc.SOURCE,
        Refuse(),
        container=MKV,
        collision="ask",
    )
    assert [i.code for i in issues] == ["output.not_writable"]


def test_a_nul_in_the_source_path_is_a_clean_error(tmp_path: Path) -> None:
    source = tmp_path / "Mo\0vie.mkv"
    (tmp_path / "out").mkdir()
    issues = _issues(tmp_path / "out" / "Movie.mkv", source)
    _no_rule_failed(issues)
    [issue] = [i for i in issues if i.severity is Severity.ERROR]
    assert (issue.code, issue.path, issue.fixes) == ("source.path_unusable", "source", [])
    shown = str(source).replace("\0", "\\0")
    assert issue.message == (
        f"The source path {shown} has a NUL character, which no file system allows: no file "
        "can have this name. Correct the path."
    )
    assert issues[0] == issue  # before the issues of the rules


def test_a_nul_in_the_source_ref_of_the_given_source(tmp_path: Path) -> None:
    """The job's path is clean but the given ``MediaSource`` names a NUL path: the same
    error (the source would be read from that path)."""
    good = tmp_path / "Movie.mkv"
    good.write_bytes(b"x")
    media = sc.make_source(tmp_path / "Mo\0vie.mkv")
    job = sc.make_job(media)
    job.source = SourceRef(path=good)
    job.output.path = tmp_path / "Out.mkv"
    issues = validate(
        job, media, sc.make_caps(), sc.make_tools(), LocalFileSystem(), definitions=sc.DEFS
    )
    _no_rule_failed(issues)
    assert [i.code for i in issues if i.severity is Severity.ERROR] == ["source.path_unusable"]


def test_a_nul_in_the_output_folder_of_the_naming_options(tmp_path: Path) -> None:
    """The naming rule lists a fixed output folder through the view (``list_files``)."""
    source = tmp_path / "Movie.mkv"
    source.write_bytes(b"x")
    settings = AppSettings()
    settings.output.naming = NamingOptions(
        output_folder_mode="fixed", output_folder=tmp_path / "fol\0der"
    )
    issues = _issues(None, source, settings)
    _no_rule_failed(issues)
    assert "output.no_path" in [i.code for i in issues]


def test_an_in_place_edit_of_a_nul_source(tmp_path: Path) -> None:
    """An in-place edit compares the output with the source (``same_file``) and asks whether
    the source can be written: neither raises, the source is not writable."""
    source = tmp_path / "Mo\0vie.mkv"
    media = sc.make_source(source)
    job = sc.make_job(media)
    job.source = SourceRef(path=source)
    job.output.path = tmp_path / "Other.mkv"
    job.output.edit_in_place = True
    issues = validate(
        job, media, sc.make_caps(), sc.make_tools(), LocalFileSystem(), definitions=sc.DEFS
    )
    _no_rule_failed(issues)


@pytest.mark.anyio
async def test_the_dry_run_of_a_nul_source_does_not_start(tmp_path: Path) -> None:
    """The test encode of a NUL source path is skipped with a warning, so no process starts."""
    media = sc.make_source(tmp_path / "Mo\0vie.mkv")
    job = sc.make_job(media)
    job.output.path = tmp_path / "Movie.mkv"
    issues = await dry_run(job, media, sc.make_caps(), sc.make_tools(), definitions=sc.DEFS)
    assert [(i.code, i.severity, i.path) for i in issues] == [
        ("encoder.dry_run_skipped", Severity.WARNING, "video.encoder")
    ]
    assert issues[0].message == (
        "The test encode did not run: the source path has a NUL character, which no file "
        "system allows."
    )
