"""``reframe tools status`` and ``reframe tools fetch`` against a local HTTP server."""

from __future__ import annotations

import asyncio
import io
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner, Result

from reframe import cli
from reframe.cli import (
    EXIT_FAILED,
    EXIT_INTERRUPTED,
    EXIT_NO_TOOL,
    EXIT_OK,
    EXIT_USAGE,
    FetchView,
    build_app,
    fetched_text,
    task_error,
)
from reframe.models import TaskInfo, TaskState
from reframe.probe import mediainfo
from reframe.tools import ENV_VARS
from reframe.tools import fetch as fetch_module
from reframe.tools.__main__ import status_lines
from reframe.tools.fetch import host_platform, install_dir_for, installed_build
from reframe_testing import fake_tools as ft

from .fetch_server import (
    FAKE_VERSION,
    Archive,
    LocalServer,
    fake_archive,
    foreign_platform,
    local_server,
    sha256,
    write_manifest,
)

WIDTH = "200"
POSIX_ONLY = pytest.mark.skipif(
    sys.platform == "win32" or host_platform() != "linux-x64",
    reason="the fake Linux build runs only on a linux-x64 host",
)


def invoke(*args: str) -> Result:
    return CliRunner().invoke(build_app(), list(args), env={"COLUMNS": WIDTH})


def assert_clean_failure(result: Result, code: int) -> list[str]:
    assert result.exit_code == code, (result.stdout, result.stderr)
    assert "Traceback" not in result.stderr
    errors = [line for line in result.stderr.splitlines() if line.startswith("error: ")]
    assert errors, result.stderr
    return errors


@pytest.fixture
def server() -> Iterator[LocalServer]:
    yield from local_server()


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for var in ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    for name in ("config", "data", "cache"):
        monkeypatch.setenv(f"REFRAME_{name.upper()}_DIR", str(tmp_path / name))
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.setattr(mediainfo, "mediainfo_available", lambda: False)
    return tmp_path / "data"


@pytest.fixture
def fake(env: Path, fake_tools: ft.FakeTools, monkeypatch: pytest.MonkeyPatch) -> ft.FakeTools:
    monkeypatch.setenv("REFRAME_FFMPEG", str(fake_tools.ffmpeg))
    monkeypatch.setenv("REFRAME_FFPROBE", str(fake_tools.ffprobe))
    return fake_tools


def _ext(platform: str) -> str:
    return "zip" if platform == "windows-x64" else "tar.xz"


def use_manifest(monkeypatch: pytest.MonkeyPatch, manifest: Path) -> None:
    monkeypatch.setattr(fetch_module, "DEFAULT_MANIFEST", manifest)


def test_status_prints_the_lines_of_python_m_reframe_tools(fake: ft.FakeTools, env: Path) -> None:
    result = invoke("tools", "status")
    assert result.exit_code == EXIT_OK, result.output
    lines = result.stdout.splitlines()
    assert lines[0] == f"ffmpeg       found    env      {fake.ffmpeg}  {FAKE_VERSION}"
    assert lines[1] == f"ffprobe      found    env      {fake.ffprobe}  {FAKE_VERSION}"
    assert lines[2].startswith("mkvpropedit  missing  -        -  (")
    assert lines[3].startswith("mediainfo    missing  -        -  (")
    install = env / "tools" / "ffmpeg"
    assert lines[4] == f'Fetched build: none ("reframe tools fetch" installs it into {install}).'
    assert result.stderr == ""


def test_status_json_is_the_toolset(fake: ft.FakeTools) -> None:
    import json

    result = invoke("tools", "status", "--json")
    assert result.exit_code == EXIT_OK, result.output
    data = json.loads(result.stdout)
    assert set(data) == {"ffmpeg", "ffprobe", "mkvpropedit", "mediainfo"}
    assert data["ffmpeg"]["origin"] == "env"
    assert data["ffmpeg"]["status"] == "found"


def test_status_without_ffmpeg_exits_4(env: Path) -> None:
    result = invoke("tools", "status")
    errors = assert_clean_failure(result, EXIT_NO_TOOL)
    assert len(errors) == 2
    assert errors[0].startswith("error: ffmpeg is not usable (missing, not found anywhere)")
    assert errors[0].endswith('"reframe tools fetch" installs the pinned FFmpeg build.')
    assert errors[1].startswith("error: ffprobe is not usable (missing")
    assert result.stdout.startswith("ffmpeg       missing  -        -")


def test_status_with_a_broken_override_does_not_suggest_fetch(
    env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("REFRAME_FFPROBE", str(tmp_path / "nope"))
    result = invoke("tools", "status")
    errors = assert_clean_failure(result, EXIT_NO_TOOL)
    probe = next(e for e in errors if e.startswith("error: ffprobe"))
    assert "set by REFRAME_FFPROBE" in probe
    assert "reframe tools fetch" not in probe


def test_status_json_still_exits_4(env: Path) -> None:
    result = invoke("tools", "status", "--json")
    assert result.exit_code == EXIT_NO_TOOL
    assert result.stdout.lstrip().startswith("{")


def test_status_lines_are_shared_with_python_m_reframe_tools(fake: ft.FakeTools) -> None:
    from reframe.tools import discover_tools_sync

    tools = discover_tools_sync()
    lines = status_lines(tools)
    result = invoke("tools", "status")
    assert result.stdout.splitlines()[:4] == lines


def test_fetched_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    host = host_platform()
    if host is None:
        assert "no FFmpeg build is pinned" in fetched_text(tmp_path)
        return
    install = install_dir_for(tmp_path, host, host)
    install.mkdir(parents=True)
    (install / fetch_module.MARKER_NAME).write_text(
        '{"build": "default", "version": "n9", "platform": "linux-x64"}', encoding="utf-8"
    )
    assert fetched_text(tmp_path) == f"Fetched build: n9 (default, linux-x64) in {install}."
    monkeypatch.setattr(cli, "host_platform", lambda: None)
    assert fetched_text(tmp_path) == "Fetched build: no FFmpeg build is pinned for this computer."


def test_status_help() -> None:
    result = invoke("tools", "status", "--help")
    assert result.exit_code == 0
    for text in ("--json", "REFRAME_FFMPEG", "bundled", "Exit codes"):
        assert text in result.stdout
    assert "status" in invoke("tools", "--help").stdout
    assert "fetch" in invoke("tools", "--help").stdout


@POSIX_ONLY
def test_fetch_installs_the_build_that_discovery_then_uses(
    env: Path, server: LocalServer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    data = fake_archive("linux-x64", tmp_path / "work")
    route = server.add("/ffmpeg-test.tar.xz", data)
    url = server.url("/ffmpeg-test.tar.xz")
    use_manifest(
        monkeypatch,
        write_manifest(tmp_path / "m.toml", {"default": [Archive(url, data, "linux-x64")]}),
    )
    result = invoke("tools", "fetch")
    assert result.exit_code == EXIT_OK, (result.stdout, result.stderr)
    out = result.stdout.splitlines()
    assert out[0] == f"FFmpeg {FAKE_VERSION} (default, linux-x64): {url}"
    install = env / "tools" / "ffmpeg"
    assert f"Installed FFmpeg {FAKE_VERSION} into {install}." in out
    assert f"ffmpeg       found    bundled  {install / 'bin' / 'ffmpeg'}  {FAKE_VERSION}" in out
    assert f"ffprobe      found    bundled  {install / 'bin' / 'ffprobe'}  {FAKE_VERSION}" in out
    # Plain lines (not a terminal). Earlier steps may be coalesced away, never the last one.
    installed = out.index(f"Installed FFmpeg {FAKE_VERSION} into {install}.")
    assert out[installed - 1] == "Running tool discovery (99%)"
    assert result.stderr == ""
    assert route.requests == 1

    status = invoke("tools", "status")
    assert status.exit_code == EXIT_OK
    assert (
        f"Fetched build: {FAKE_VERSION} (default, linux-x64) in {install}."
        in status.stdout.splitlines()
    )
    assert "ffmpeg       found    bundled" in status.stdout

    again = invoke("tools", "fetch")
    assert again.exit_code == EXIT_OK, again.output
    assert (
        f"FFmpeg {FAKE_VERSION} is already installed in {install} and every file is intact: "
        "nothing was downloaded." in again.stdout
    )
    assert route.requests == 1


@POSIX_ONLY
def test_fetch_warns_when_an_override_takes_precedence(
    fake: ft.FakeTools, server: LocalServer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    data = fake_archive("linux-x64", tmp_path / "work")
    server.add("/a.tar.xz", data)
    use_manifest(
        monkeypatch,
        write_manifest(
            tmp_path / "m.toml",
            {"default": [Archive(server.url("/a.tar.xz"), data, "linux-x64")]},
        ),
    )
    result = invoke("tools", "fetch")
    assert result.exit_code == EXIT_OK, result.output
    warnings = result.stderr.splitlines()
    assert warnings[0].startswith(
        f"warning: ffmpeg is not the fetched build: set by REFRAME_FFMPEG: {fake.ffmpeg}."
    )
    assert "takes precedence" in warnings[0]


def test_fetch_for_another_platform(
    env: Path, server: LocalServer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    other = foreign_platform()
    ext = "zip" if other == "windows-x64" else "tar.xz"
    data = fake_archive(other, tmp_path / "work")
    server.add(f"/a.{ext}", data)
    use_manifest(
        monkeypatch,
        write_manifest(
            tmp_path / "m.toml", {"default": [Archive(server.url(f"/a.{ext}"), data, other)]}
        ),
    )
    result = invoke("tools", "fetch", "--platform", other)
    assert result.exit_code == EXIT_OK, result.output
    install = env / "tools" / f"ffmpeg-{other}"
    assert f"Installed FFmpeg {FAKE_VERSION} into {install}." in result.stdout
    assert (
        f"This build is for {other}: tool discovery on this computer does not use it. "
        f"Copy {install} to <data dir>/tools/ffmpeg on that computer." in result.stdout
    )
    assert not (env / "tools" / "ffmpeg").exists()


def test_a_bad_checksum_is_one_error_line(
    env: Path, server: LocalServer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    other = foreign_platform()
    ext = "zip" if other == "windows-x64" else "tar.xz"
    data = fake_archive(other, tmp_path / "work")
    server.add(f"/a.{ext}", data)
    pinned = sha256(b"something else")
    use_manifest(
        monkeypatch,
        write_manifest(
            tmp_path / "m.toml",
            {"default": [Archive(server.url(f"/a.{ext}"), data, other, sha=pinned)]},
        ),
    )
    result = invoke("tools", "fetch", "--platform", other)
    errors = assert_clean_failure(result, EXIT_FAILED)
    assert errors == [
        f"error: the fetch failed: a.{ext}: the SHA-256 is {sha256(data)}, expected {pinned}"
    ]
    assert not (env / "tools" / f"ffmpeg-{other}").exists()
    assert [p.name for p in (env / "tools").iterdir()] == []


def test_unknown_build_and_platform_are_usage_errors(
    env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    other = foreign_platform()
    use_manifest(
        monkeypatch,
        write_manifest(
            tmp_path / "m.toml",
            {"default": [Archive(f"https://example.invalid/a.{_ext(other)}", b"x", other)]},
        ),
    )
    result = invoke("tools", "fetch", "--build", "nightly")
    assert assert_clean_failure(result, EXIT_USAGE) == [
        'error: there is no build "nightly" in the manifest. Builds: "default".'
    ]
    host = "linux-x64" if other == "windows-x64" else "windows-x64"
    result = invoke("tools", "fetch", "--platform", host)
    assert assert_clean_failure(result, EXIT_USAGE) == [
        f'error: the build "default" has no archive for {host}.'
    ]
    result = invoke("tools", "fetch", "--platform", "mac-arm64")
    assert result.exit_code == EXIT_USAGE
    assert "Traceback" not in result.output


def test_an_unsupported_host_without_platform(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "host_platform", lambda: None)
    result = invoke("tools", "fetch")
    errors = assert_clean_failure(result, EXIT_FAILED)
    assert errors[0].startswith("error: no FFmpeg build is pinned for this computer")


@pytest.mark.anyio
async def test_ctrl_c_stops_the_download(
    env: Path,
    server: LocalServer,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Cancelling the task is what asyncio.run does on Ctrl+C."""
    other = foreign_platform()
    ext = _ext(other)
    data = fake_archive(other, tmp_path / "work") + b"\0" * (2 << 20)
    route = server.add(f"/a.{ext}", data, delay=0.05)
    use_manifest(
        monkeypatch,
        write_manifest(
            tmp_path / "m.toml", {"default": [Archive(server.url(f"/a.{ext}"), data, other)]}
        ),
    )
    task = asyncio.create_task(cli.run_tools_fetch(build="default", platform=other))
    deadline = asyncio.get_running_loop().time() + 30
    while route.requests == 0:
        assert asyncio.get_running_loop().time() < deadline
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.2)
    task.cancel()
    assert await asyncio.wait_for(task, 60) == EXIT_INTERRUPTED
    tools = env / "tools"
    assert list(tools.iterdir()) == []
    assert "Nothing was installed." in capsys.readouterr().err


@POSIX_ONLY
@pytest.mark.anyio
async def test_the_cli_says_what_was_installed_after_an_interrupt(
    env: Path,
    server: LocalServer,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data = fake_archive("linux-x64", tmp_path / "work")
    server.add("/a.tar.xz", data)
    use_manifest(
        monkeypatch,
        write_manifest(
            tmp_path / "m.toml", {"default": [Archive(server.url("/a.tar.xz"), data, "linux-x64")]}
        ),
    )
    loop = asyncio.get_running_loop()
    command: list[asyncio.Task[int]] = []
    swap = fetch_module._swap_into_place

    def swap_then_interrupt(new: Path, install_dir: Path, aside: Path) -> None:
        swap(new, install_dir, aside)
        loop.call_soon_threadsafe(command[0].cancel)  # what asyncio.run does on Ctrl+C

    monkeypatch.setattr(fetch_module, "_swap_into_place", swap_then_interrupt)
    command.append(asyncio.create_task(cli.run_tools_fetch(build="default", platform=None)))
    assert await asyncio.wait_for(command[0], 60) == EXIT_INTERRUPTED
    err = capsys.readouterr().err
    install = env / "tools" / "ffmpeg"
    assert installed_build(install) is not None
    assert "Nothing was installed." not in err
    assert f"was installed into {install} before the interrupt." in err


def test_fetch_help() -> None:
    result = invoke("tools", "fetch", "--help")
    assert result.exit_code == 0
    for text in ("--build", "--platform", "linux-x64", "windows-x64", "SHA-256", "Exit codes"):
        assert text in result.stdout


def _task(message: str, progress: float | None) -> TaskInfo:
    return TaskInfo(
        id="t-1", kind="tools_fetch", state=TaskState.RUNNING, progress=progress, message=message
    )


def test_fetch_view_lines() -> None:
    out = io.StringIO()
    view = FetchView(Console(file=out, width=100), live=False)
    view.update(_task("Reading the manifest", None))
    view.update(_task("Downloading a.tar.xz", 0.0))
    for percent in (3.0, 9.9, 10.5, 15.0, 21.0, 85.0):
        view.update(_task("Downloading a.tar.xz", percent))
    view.update(_task("Extracting a.tar.xz", 90.0))
    view.close()
    assert out.getvalue().splitlines() == [
        "Reading the manifest",
        "Downloading a.tar.xz",
        "  10%",
        "  21%",
        "  85%",
        "Extracting a.tar.xz (90%)",
    ]


def test_fetch_view_bar() -> None:
    out = io.StringIO()
    view = FetchView(Console(file=out, width=100, force_terminal=True), live=True)
    view.update(_task("Downloading a.tar.xz", 42.0))
    view.close()
    view.close()
    assert "Downloading a.tar.xz" in out.getvalue()


def test_task_error_drops_the_expected_failure_prefix() -> None:
    info = _task("x", None).model_copy(update={"error": "TaskFailed: the SHA-256 is wrong"})
    assert task_error(info) == "the SHA-256 is wrong"
    info = info.model_copy(update={"error": "ValueError: boom"})
    assert task_error(info) == "ValueError: boom"
    assert task_error(info.model_copy(update={"error": None})) == "no reason given"


def test_an_expected_task_failure_is_not_logged_with_a_traceback() -> None:
    """With no logging configured, the task manager's ``log.exception`` would print a traceback."""
    import logging

    from reframe.mediatask import TaskFailed

    cli._quiet_expected_failures()
    cli._quiet_expected_failures()
    logger = logging.getLogger("reframe.tasks")
    filters = [f for f in logger.filters if isinstance(f, cli._ExpectedTaskFailure)]
    assert len(filters) == 1

    def record(exc: BaseException) -> logging.LogRecord:
        return logging.LogRecord(
            "reframe.tasks", logging.ERROR, __file__, 1, "task failed", (), (type(exc), exc, None)
        )

    assert not filters[0].filter(record(TaskFailed("the SHA-256 is wrong")))
    assert filters[0].filter(record(ValueError("a bug")))
    plain = logging.LogRecord("reframe.tasks", logging.ERROR, __file__, 1, "x", (), None)
    assert filters[0].filter(plain)
