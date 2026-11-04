"""The pytest plugin: needs_ffmpeg skip / REFRAME_REQUIRE_FFMPEG fail, fake_tools teardown."""

from __future__ import annotations

import time
from pathlib import Path

import psutil
import pytest

from reframe_testing import fake_tools as ft
from reframe_testing import media
from reframe_testing.pytest_plugin import REQUIRE_ENV

pytest_plugins = ["pytester"]

PLUGIN = ("-p", "reframe_testing.pytest_plugin")

NEEDS_FFMPEG_TESTS = """
import pytest

@pytest.mark.needs_ffmpeg
def test_real_tool():
    pass

def test_media(fixture_media):
    fixture_media("multitrack")

def test_plain():
    pass
"""


@pytest.fixture
def inner(pytester: pytest.Pytester) -> pytest.Pytester:
    pytester.makeini("[pytest]\nmarkers =\n    needs_ffmpeg: needs a real ffmpeg\n")
    pytester.makepyfile(test_inner=NEEDS_FFMPEG_TESTS)
    return pytester


def _missing_tools(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(media.FFMPEG_ENV, str(tmp_path / "nonexistent" / "ffmpeg"))
    monkeypatch.setenv(media.FFPROBE_ENV, str(tmp_path / "nonexistent" / "ffprobe"))


def test_missing_ffmpeg_skips_needs_ffmpeg_tests(
    inner: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _missing_tools(monkeypatch, tmp_path)
    for value in (None, "", "0", "false"):
        if value is None:
            monkeypatch.delenv(REQUIRE_ENV, raising=False)
        else:
            monkeypatch.setenv(REQUIRE_ENV, value)
        result = inner.runpytest(*PLUGIN, "-rs")
        result.assert_outcomes(passed=1, skipped=2)
        result.stdout.fnmatch_lines(["*needs ffmpeg and ffprobe: ffmpeg: REFRAME_FFMPEG=*"])
        assert result.ret == pytest.ExitCode.OK


def test_require_ffmpeg_fails_instead_of_skipping(
    inner: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _missing_tools(monkeypatch, tmp_path)
    monkeypatch.setenv(REQUIRE_ENV, "1")
    result = inner.runpytest(*PLUGIN)
    # needs_ffmpeg fails in its setup (error); fixture_media fails the test itself
    result.assert_outcomes(passed=1, errors=1, failed=1)
    result.stdout.fnmatch_lines(
        [
            "*REFRAME_REQUIRE_FFMPEG is set, so this test must not be skipped: needs ffmpeg and"
            " ffprobe: ffmpeg: REFRAME_FFMPEG=*nonexistent*ffmpeg is not a file; ffprobe:*"
        ]
    )
    assert result.ret == pytest.ExitCode.TESTS_FAILED


def test_require_ffmpeg_fails_when_ffmpeg_does_not_run(
    inner: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A binary that exists but cannot run ``-version`` (wrong platform, missing libraries)."""
    broken = ft.make_fake_tools(
        tmp_path / "broken",
        ft.Scenario(
            [
                ft.Rule(
                    tool="ffmpeg",
                    argv_has=["-version"],
                    actions=[ft.stderr("error while loading shared libraries\n")],
                    exit_code=127,
                )
            ]
        ),
    )
    monkeypatch.setenv(media.FFMPEG_ENV, str(broken.ffmpeg))
    monkeypatch.setenv(media.FFPROBE_ENV, str(broken.ffprobe))
    monkeypatch.setenv(REQUIRE_ENV, "1")
    result = inner.runpytest(*PLUGIN, "-k", "real_tool")
    result.assert_outcomes(errors=1, deselected=2)
    result.stdout.fnmatch_lines(  # the fake is ffmpeg.cmd on Windows
        ["*ffmpeg at *ffmpeg* does not run: -version exited with 127: error while loading*"]
    )
    assert "ffprobe at" not in result.stdout.str()  # the fake ffprobe -version works


def test_require_ffmpeg_with_working_tools_runs_the_tests(
    inner: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    working = ft.make_fake_tools(tmp_path / "working")  # prints the real -version texts
    monkeypatch.setenv(media.FFMPEG_ENV, str(working.ffmpeg))
    monkeypatch.setenv(media.FFPROBE_ENV, str(working.ffprobe))
    monkeypatch.setenv(REQUIRE_ENV, "1")
    result = inner.runpytest(*PLUGIN, "-k", "real_tool or plain")
    result.assert_outcomes(passed=2, deselected=1)


def test_fake_tools_teardown_kills_processes_of_a_failed_test(
    pytester: pytest.Pytester, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A separate pytest process: the leaked Popen objects must not reach this process.
    monkeypatch.setenv("PYTHONPATH", str(Path(ft.__file__).resolve().parents[1]))
    pid_file = tmp_path / "pids.txt"
    pytester.makepyfile(
        test_leak=f"""
import subprocess, time
from pathlib import Path
from reframe_testing import fake_tools as ft

def test_leaks(fake_tools):
    fake_tools.set_scenario(ft.Scenario([ft.Rule(actions=[ft.spawn_grandchild(), ft.hang()])]))
    subprocess.Popen([str(fake_tools.ffmpeg), "-i", "x", "y.mkv"])
    deadline = time.monotonic() + 10
    while len(fake_tools.pids()) < 2 and time.monotonic() < deadline:
        time.sleep(0.02)
    Path({str(pid_file)!r}).write_text(" ".join(map(str, fake_tools.pids())))
    assert False, "the test fails while the fakes still run"
"""
    )
    result = pytester.runpytest_subprocess(*PLUGIN, "-W", "ignore::ResourceWarning")
    result.assert_outcomes(failed=1)
    pids = [int(p) for p in pid_file.read_text().split()]
    assert len(pids) == 2
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        alive = [p for p in pids if psutil.pid_exists(p) and not _zombie(p)]
        if not alive:
            break
        time.sleep(0.05)
    assert alive == []


def _zombie(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return True
