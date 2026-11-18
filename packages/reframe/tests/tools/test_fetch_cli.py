"""``reframe tools status`` and ``reframe tools fetch`` against a local HTTP server."""

from __future__ import annotations

import asyncio
import io
import socket
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import Result

from reframe import cli
from reframe.cli import (
    EXIT_FAILED,
    EXIT_INTERRUPTED,
    EXIT_NO_TOOL,
    EXIT_OK,
    EXIT_USAGE,
    FetchView,
    fetched_text,
)
from reframe.models import TaskInfo, TaskState, ToolInfo, ToolSet, ToolStatus
from reframe.models.tools import InstalledToolBuild, ToolBuildOffer, ToolBuilds
from reframe.tools import ENV_VARS
from reframe.tools import fetch as fetch_module
from reframe.tools.__main__ import status_lines
from reframe.tools.fetch import host_platform, install_dir_for, installed_build
from reframe_testing import fake_tools as ft
from reframe_testing.cli import invoke, run_cli

from .fetch_server import (
    FAKE_VERSION,
    POSIX_ONLY,
    Archive,
    LocalServer,
    archive_ext,
    fake_archive,
    foreign_platform,
    sha256,
    write_manifest,
)


def assert_clean_failure(result: Result, code: int) -> list[str]:
    assert result.exit_code == code, (result.stdout, result.stderr)
    assert "Traceback" not in result.stderr
    errors = [line for line in result.stderr.splitlines() if line.startswith("error: ")]
    assert errors, result.stderr
    return errors


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for var in ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    for name in ("config", "data", "cache"):
        monkeypatch.setenv(f"REFRAME_{name.upper()}_DIR", str(tmp_path / name))
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    return tmp_path / "data"


@pytest.fixture
def fake(env: Path, fake_tools: ft.FakeTools, monkeypatch: pytest.MonkeyPatch) -> ft.FakeTools:
    monkeypatch.setenv("REFRAME_FFMPEG", str(fake_tools.ffmpeg))
    monkeypatch.setenv("REFRAME_FFPROBE", str(fake_tools.ffprobe))
    return fake_tools


def use_manifest(monkeypatch: pytest.MonkeyPatch, manifest: Path) -> None:
    monkeypatch.setattr(fetch_module, "DEFAULT_MANIFEST", manifest)


def test_status_json_is_the_toolset(fake: ft.FakeTools) -> None:
    import json

    result = invoke("tools", "status", "--json")
    assert result.exit_code == EXIT_OK, result.output
    data = json.loads(result.stdout)
    assert set(data) == {"ffmpeg", "ffprobe"}
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


def test_status_lines_are_shared_with_python_m_reframe_tools(fake: ft.FakeTools, env: Path) -> None:
    from reframe.tools import discover_tools

    tools = asyncio.run(discover_tools())
    lines = status_lines(tools)
    result = invoke("tools", "status")
    assert result.exit_code == EXIT_OK, result.output
    assert [line.split()[0] for line in lines] == ["ffmpeg", "ffprobe"]
    assert result.stdout.splitlines()[: len(lines)] == lines
    out = result.stdout.splitlines()
    assert out[0] == f"ffmpeg       found    env      {fake.ffmpeg}  {FAKE_VERSION}"
    assert out[1] == f"ffprobe      found    env      {fake.ffprobe}  {FAKE_VERSION}"
    install = env / "tools" / "ffmpeg"
    assert out[2] == f'Fetched build: none ("reframe tools fetch" installs it into {install}).'
    assert result.stderr == ""


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
            {"default": [Archive(f"https://example.invalid/a.{archive_ext(other)}", b"x", other)]},
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
    ext = archive_ext(other)
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
    assert "--file" in result.stdout
    assert "Builds to choose:" in result.stdout
    assert "default (Recommended): The build Reframe is tested with." in result.stdout
    assert "compat (Compatibility): FFmpeg 8.1" in result.stdout
    assert "override-test" not in result.stdout


def test_offered_builds_text_lists_only_the_offered_builds() -> None:
    assert cli.offered_builds_text().split("\n\n") == [
        "Builds to choose:",
        "default (Recommended): The build Reframe is tested with. NVIDIA NVENC needs driver 610 "
        "or newer.",
        "compat (Compatibility): FFmpeg 8.1, for NVIDIA drivers older than 610 (GeForce 10 "
        "series and older). Checked with driver 582.78.",
    ]


NAME = "ffmpeg-test-linux64.tar.xz"


def file_manifest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, data: bytes) -> str:
    """The packaged manifest replaced by one whose offered ``default`` archive is ``data``,
    named NAME; returns its URL."""
    url = f"https://downloads.example/{NAME}"
    use_manifest(
        monkeypatch,
        write_manifest(
            tmp_path / "m.toml", {"default": [Archive(url, data, "linux-x64")]}, offered=["default"]
        ),
    )
    return url


@POSIX_ONLY
def test_fetch_file_installs_the_archive_that_discovery_then_uses(
    env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    data = fake_archive("linux-x64", tmp_path / "work")
    file_manifest(monkeypatch, tmp_path, data)
    archive = tmp_path / NAME
    archive.write_bytes(data)
    result = invoke("tools", "fetch", "--file", str(archive))
    assert result.exit_code == EXIT_OK, (result.stdout, result.stderr)
    out = result.stdout.splitlines()
    assert out[0] == f"FFmpeg {FAKE_VERSION} (default, linux-x64): {archive}"
    install = env / "tools" / "ffmpeg"
    assert f"Installed FFmpeg {FAKE_VERSION} into {install}." in out
    assert f"ffmpeg       found    bundled  {install / 'bin' / 'ffmpeg'}  {FAKE_VERSION}" in out
    assert result.stderr == ""
    again = invoke("tools", "fetch", "--file", str(archive), "--build", "default")
    assert again.exit_code == EXIT_OK, again.output
    assert (
        f"FFmpeg {FAKE_VERSION} is already installed in {install} and every file is intact: "
        "nothing was installed." in again.stdout.splitlines()
    )
    assert "downloaded" not in again.stdout


def test_fetch_file_refuses_a_wrong_archive(
    env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    data = b"the pinned archive"
    file_manifest(monkeypatch, tmp_path, data)
    host = host_platform()
    wrong = tmp_path / NAME
    wrong.write_bytes(b"the pinned archivE")
    result = invoke("tools", "fetch", "--file", str(wrong), "--build", "default")
    if host != "linux-x64":  # the test manifest has only a linux-x64 archive
        assert result.exit_code == EXIT_USAGE
        return
    error = (
        f"error: the install failed: {NAME} is not the archive of the FFmpeg build 'default' "
        f"for linux-x64 ({NAME}), or it is damaged: the SHA-256 is "
        f"{sha256(wrong.read_bytes())}, expected {sha256(data)}"
    )
    assert assert_clean_failure(result, EXIT_FAILED) == [error]
    assert result.stderr.splitlines() == [error]
    assert not (env / "tools" / "ffmpeg").exists()


def test_a_failed_install_is_one_line_in_a_real_process(
    fake_tools: ft.FakeTools, tmp_path: Path
) -> None:
    """The task's log record does not repeat the error: the command sets up no logging, and
    Python would print it on stderr."""
    wrong = tmp_path / "ffmpeg.tar.xz"
    wrong.write_bytes(b"not the pinned archive")
    result = run_cli(
        fake_tools, tmp_path, "tools", "fetch", "--file", str(wrong), "--build", "default",
        encoding="utf-8",
    )  # fmt: skip
    assert result.returncode == EXIT_FAILED
    stderr = result.stderr.decode("utf-8").splitlines()
    assert len(stderr) == 1, stderr
    assert stderr[0].startswith(
        "error: the install failed: ffmpeg.tar.xz is not the archive of the FFmpeg build "
        "'default' for "
    )
    assert "or it is damaged: the size is 22 bytes, expected " in stderr[0]


def test_fetch_file_usage_errors(
    env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    file_manifest(monkeypatch, tmp_path, b"x")
    missing = invoke("tools", "fetch", "--file", str(tmp_path / "nope.tar.xz"))
    assert assert_clean_failure(missing, cli.EXIT_NOT_FOUND) == [
        f"error: {tmp_path / 'nope.tar.xz'}: there is no such file."
    ]
    other = tmp_path / "other.tar.xz"
    other.write_bytes(b"x")
    platform = invoke("tools", "fetch", "--file", str(other), "--platform", "windows-x64")
    assert assert_clean_failure(platform, EXIT_USAGE) == [
        "error: --file installs a build for this computer: leave out --platform."
    ]
    if host_platform() != "linux-x64":
        return
    unnamed = invoke("tools", "fetch", "--file", str(other))
    assert assert_clean_failure(unnamed, EXIT_USAGE) == [
        f"error: other.tar.xz is not the file name of an offered build's archive for linux-x64 "
        f"({NAME}): name the build it is (--build NAME)."
    ]
    unknown = invoke("tools", "fetch", "--file", str(other), "--build", "nightly")
    assert assert_clean_failure(unknown, EXIT_USAGE) == [
        'error: there is no build "nightly" in the manifest. Builds: "default".'
    ]


def test_an_offline_fetch_names_the_file_install(
    env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    host = host_platform()
    if host is None:
        pytest.skip("no build is pinned for this computer")
    url = f"https://downloads.example/ffmpeg.{archive_ext(host)}"
    use_manifest(
        monkeypatch,
        write_manifest(tmp_path / "m.toml", {"default": [Archive(url, b"x", host)]}),
    )
    monkeypatch.setattr(fetch_module, "_sleep", lambda seconds, cancel: None)

    def unreachable(*args: object, **kwargs: object) -> None:
        raise urllib.error.URLError(socket.gaierror(-2, "Name or service not known"))

    monkeypatch.setattr(urllib.request, "urlopen", unreachable)
    result = invoke("tools", "fetch")
    errors = assert_clean_failure(result, EXIT_FAILED)
    assert errors[0].startswith(
        "error: the fetch failed: cannot reach the download server downloads.example (Name or "
        "service not known; 1 attempt(s)). Without a connection, install the build from its "
        "archive file"
    )
    assert result.stderr.splitlines()[-1] == (
        f'hint: download {url} on another computer, then run "reframe tools fetch --file '
        'ARCHIVE" here.'
    )
    assert not (env / "tools" / "ffmpeg").exists()


def test_fetched_text_says_when_the_build_is_outdated(tmp_path: Path) -> None:
    host = host_platform()
    if host is None:
        pytest.skip("no build is pinned for this computer")
    install = install_dir_for(tmp_path, host, host)
    install.mkdir(parents=True)
    (install / fetch_module.MARKER_NAME).write_text(
        f'{{"build": "default", "version": "n9", "platform": "{host}"}}', encoding="utf-8"
    )
    offer = ToolBuildOffer(
        name="default",
        label="Recommended",
        summary="…",
        version="n10",
        release_version="10.0",
        license="GPL-3.0-or-later",
    )
    current = ToolBuilds(builds=[offer], installed=InstalledToolBuild(name="default", version="n9"))
    line = f"Fetched build: n9 (default, {host}) in {install}."
    assert fetched_text(tmp_path, current) == line
    outdated = current.model_copy(
        update={"installed": InstalledToolBuild(name="default", version="n9", outdated=True)}
    )
    assert fetched_text(tmp_path, outdated) == (
        f'{line} It is outdated: this release pins n10 as "default" ("reframe tools fetch '
        '--build default" installs it).'
    )
    unoffered = outdated.model_copy(update={"builds": []})
    assert 'pins another version of "default"' in fetched_text(tmp_path, unoffered)


def test_status_says_when_the_downloaded_build_is_outdated(
    fake: ft.FakeTools, env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    host = host_platform()
    if host is None:
        pytest.skip("no build is pinned for this computer")
    install = install_dir_for(env, host, host)
    install.mkdir(parents=True)
    (install / fetch_module.MARKER_NAME).write_text(
        f'{{"build": "default", "version": "n9.0.1", "platform": "{host}"}}', encoding="utf-8"
    )
    url = f"https://downloads.example/ffmpeg.{archive_ext(host)}"
    use_manifest(
        monkeypatch,
        write_manifest(
            tmp_path / "m.toml",
            {"default": [Archive(url, b"x", host)]},
            version="n9.0.2",
            offered=["default"],
        ),
    )
    result = invoke("tools", "status")
    assert result.exit_code == EXIT_OK, result.output
    assert (
        f"Fetched build: n9.0.1 (default, {host}) in {install}. It is outdated: this release "
        'pins n9.0.2 as "default" ("reframe tools fetch --build default" installs it).'
    ) in result.stdout.splitlines()


def _builds(*names: str, installed: str | None = None) -> ToolBuilds:
    offers = [
        ToolBuildOffer(
            name=name, label=name, summary="", version="v", release_version="9.0", license="GPL"
        )
        for name in names
    ]
    done = InstalledToolBuild(name=installed, version="v") if installed else None
    return ToolBuilds(builds=offers, installed=done)


@pytest.mark.parametrize(
    ("in_use", "builds", "other"),
    [
        (None, _builds("default", "compat"), "compat"),  # the user's own or a packaged FFmpeg
        ("default", _builds("default", "compat"), "compat"),
        ("compat", _builds("default", "compat"), "default"),
        ("default", _builds("default"), "compat"),
        (None, _builds("default"), "default"),
        (None, None, "compat"),
    ],
)
def test_the_hint_names_another_offered_build(
    in_use: str | None, builds: ToolBuilds | None, other: str
) -> None:
    assert cli.other_build(in_use, builds) == other


def test_the_build_in_use_is_the_downloaded_one_only_when_discovery_picked_it(
    tmp_path: Path,
) -> None:
    host = host_platform()
    if host is None:
        pytest.skip("no build is pinned for this computer")
    install = install_dir_for(tmp_path, host, host)
    builds = _builds("default", "compat", installed="compat")

    def tools(path: Path) -> ToolSet:
        return ToolSet(
            ffmpeg=ToolInfo(name="ffmpeg", status=ToolStatus.FOUND, path=path),
            ffprobe=ToolInfo(name="ffprobe", status=ToolStatus.FOUND, path=path),
        )

    assert cli.build_in_use(tools(install / "bin" / "ffmpeg"), builds, tmp_path) == "compat"
    assert cli.build_in_use(tools(tmp_path / "own" / "ffmpeg"), builds, tmp_path) is None
    assert cli.build_in_use(tools(install / "bin" / "ffmpeg"), _builds("default"), tmp_path) is None


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
