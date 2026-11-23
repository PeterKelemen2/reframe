"""``reframe.tools.fetch``: the manifest, the download, the safe extraction and the install."""

from __future__ import annotations

import asyncio
import errno
import http.client
import json
import logging
import os
import re
import shutil
import socket
import ssl
import sys
import tarfile
import threading
import time
import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from reframe import Reframe
from reframe.events import EventBus
from reframe.models import Event, TaskInfo, TaskState, ToolInfo, ToolOrigin, ToolSet, ToolStatus
from reframe.models.events import TaskProgressEvent
from reframe.tasks import TaskManager
from reframe.tools import ENV_VARS, CancelToken
from reframe.tools import fetch as fetch_module
from reframe.tools.fetch import (
    DEFAULT_MANIFEST,
    MARKER_NAME,
    FetchError,
    host_platform,
    install_dir_for,
    installed_build,
    load_manifest,
    member_path,
    parse_manifest,
    start_fetch,
)
from reframe_testing.scripts import load_script

from .fetch_server import (
    FAKE_VERSION,
    LINUX_ROOT,
    POSIX_ONLY,
    WINDOWS_ROOT,
    Archive,
    LocalServer,
    archive_ext,
    fake_archive,
    foreign_platform,
    sha256,
    tar_dir,
    tar_file,
    tar_link,
    tar_xz,
    write_manifest,
    zip_bytes,
)

REPO = Path(__file__).resolve().parents[4]
REPO_MANIFEST = REPO / "tools" / "ffmpeg.toml"


def _toolset() -> ToolSet:
    def info(name: Any) -> ToolInfo:
        return ToolInfo(name=name, status=ToolStatus.MISSING)

    return ToolSet(
        ffmpeg=info("ffmpeg"),
        ffprobe=info("ffprobe"),
    )


class Fetch:
    """``start_fetch`` with a task manager, a counting ``rescan`` and the progress messages."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.rescans = 0
        self.messages: list[str] = []
        self.percents: list[float] = []

    async def rescan(self) -> ToolSet:
        self.rescans += 1
        return _toolset()

    def _record(self, event: Event) -> None:
        if not isinstance(event, TaskProgressEvent):
            return
        if event.task.message and event.task.message not in self.messages:
            self.messages.append(event.task.message)
        if event.task.progress is not None:
            self.percents.append(event.task.progress)

    async def __call__(
        self, manifest: Path, *, platform: str | None = None, build: str = "default"
    ) -> tuple[TaskInfo, Any]:
        # Every progress event as it is published: a subscription keeps only the newest
        # ``task.progress`` of a task, so a step's message can be replaced before it is read.
        events = _RecordingBus(self._record)
        tasks = TaskManager(events)
        info = start_fetch(
            tasks,
            data_dir=self.data_dir,
            rescan=self.rescan,
            build=build,
            platform=platform,
            manifest=manifest,
        )
        assert info.kind == "tools_fetch"
        final = await asyncio.wait_for(tasks.wait(info.id), 120)
        events.close()
        return final, tasks.value(info.id)


class _RecordingBus(EventBus):
    """An event bus that hands every published event to ``record`` at once (no queue, so no
    coalescing)."""

    def __init__(self, record: Callable[[Event], None]) -> None:
        super().__init__()
        self._record = record

    def publish(self, event: Event) -> None:
        self._record(event)
        super().publish(event)


@pytest.fixture
def fetch(tmp_path: Path) -> Fetch:
    return Fetch(tmp_path / "data")


def leftovers(data_dir: Path) -> list[str]:
    """Temporary folders of a fetch that were not removed."""
    tools = data_dir / "tools"
    return sorted(p.name for p in tools.glob(".fetch-*")) if tools.exists() else []


def test_packaged_manifest_is_a_copy_of_tools_ffmpeg_toml() -> None:
    """The installed package carries a copy of ``tools/ffmpeg.toml``: the two must stay equal."""
    packaged = DEFAULT_MANIFEST.read_text(encoding="utf-8").replace("\r\n", "\n")
    repo = REPO_MANIFEST.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert packaged == repo, "copy tools/ffmpeg.toml to packages/reframe/src/reframe/tools/"


def test_the_core_and_the_script_read_the_manifest_alike() -> None:
    script = load_script("fetch-tools.py", "fetch_tools_script")
    ours = load_manifest()
    theirs = script.load_manifest(REPO_MANIFEST)
    assert sorted(ours) == sorted(theirs) == ["compat", "default", "override-test"]
    for name, build in ours.items():
        other = theirs[name]
        assert (build.version, build.release_version, build.license, build.source_commit) == (
            other.version,
            other.release_version,
            other.license,
            other.source_commit,
        )
        assert sorted(build.platforms) == sorted(other.platforms)
        for platform, entry in build.platforms.items():
            mine = (entry.url, entry.sha256, entry.size, entry.format, entry.root)
            script_entry = other.platforms[platform]
            assert mine == (
                script_entry.url,
                script_entry.sha256,
                script_entry.size,
                script_entry.format,
                script_entry.root,
            )
            assert (entry.ffmpeg, entry.ffprobe, entry.file_name) == (
                script_entry.ffmpeg,
                script_entry.ffprobe,
                script_entry.file_name,
            )
    assert fetch_module.MARKER_NAME == script.MARKER_NAME


def _manifest_data() -> dict[str, Any]:
    with REPO_MANIFEST.open("rb") as f:
        return tomllib.load(f)


def _linux(data: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = data["builds"]["default"]["platforms"]["linux-x64"]
    return entry


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d.update(schema_version=2), "schema_version"),
        (lambda d: d["builds"].pop("default"), "builds.default: missing (the recommended build)"),
        (lambda d: d.update(builds={}), "builds: expected a non-empty table"),
        (lambda d: d["builds"]["default"].update(version="n9 x"), "must not contain spaces"),
        (lambda d: d["builds"]["default"].update(release_version="6.1"), "is below 7.0"),
        (lambda d: d["builds"]["default"].update(release_version="nine"), "expected X.Y"),
        (lambda d: d["builds"]["default"].pop("license"), "license"),
        (lambda d: d["builds"]["default"]["platforms"].update(mac={}), "unknown platform"),
        (lambda d: _linux(d).update(url="http://example.com/a.tar.xz"), "https://"),
        (lambda d: _linux(d).update(url="ftp://example.com/a.tar.xz"), "https://"),
        (lambda d: _linux(d).update(sha256="ABC"), "64 lowercase hex"),
        (lambda d: _linux(d).update(size=0), "positive integer"),
        (lambda d: _linux(d).update(size=True), "positive integer"),
        (lambda d: _linux(d).update(format="7z"), "format"),
        (lambda d: _linux(d).update(url="https://example.com/a.zip"), "does not end with"),
        (lambda d: _linux(d).update(root="a/b"), "one folder name"),
        (lambda d: _linux(d).update(root="../x"), "must not contain"),
        (lambda d: _linux(d).update(bin_dir="/bin"), "relative POSIX path"),
        (lambda d: _linux(d).update(ffmpeg="lib/ffmpeg"), "is not in bin_dir"),
        (lambda d: _linux(d).update(ffprobe=7), "non-empty string"),
    ],
)
def test_a_bad_manifest_is_refused(change: Any, message: str) -> None:
    data = _manifest_data()
    change(data)
    with pytest.raises(FetchError, match=re.escape(message)):
        parse_manifest(data)


@pytest.mark.parametrize(
    "url",
    [
        "file:///srv/mirror/ffmpeg.tar.xz",
        "http://127.0.0.1:8000/ffmpeg.tar.xz",
        "http://localhost/ffmpeg.tar.xz",
        "https://mirror.example/ffmpeg.tar.xz?x=1",
    ],
)
def test_file_and_loopback_urls_are_allowed(url: str) -> None:
    data = _manifest_data()
    _linux(data)["url"] = url
    assert parse_manifest(data)["default"].platforms["linux-x64"].url == url


def test_load_manifest_errors(tmp_path: Path) -> None:
    with pytest.raises(FetchError, match="cannot read the manifest"):
        load_manifest(tmp_path / "missing.toml")
    bad = tmp_path / "bad.toml"
    bad.write_text("schema_version = ", encoding="utf-8")
    with pytest.raises(FetchError, match="not valid TOML"):
        load_manifest(bad)


@pytest.mark.parametrize(
    ("sys_platform", "machine", "expected"),
    [
        ("linux", "x86_64", "linux-x64"),
        ("win32", "AMD64", "windows-x64"),
        ("linux", "aarch64", "linux-arm64"),
        ("win32", "ARM64", None),
        ("darwin", "x86_64", None),
    ],
)
def test_host_platform(sys_platform: str, machine: str, expected: str | None) -> None:
    assert host_platform(sys_platform, machine) == expected


def test_install_dir_for(tmp_path: Path) -> None:
    assert install_dir_for(tmp_path, "linux-x64", "linux-x64") == tmp_path / "tools" / "ffmpeg"
    other = install_dir_for(tmp_path, "windows-x64", "linux-x64")
    assert other == tmp_path / "tools" / "ffmpeg-windows-x64"
    assert install_dir_for(tmp_path, "linux-x64", None).name == "ffmpeg-linux-x64"


@pytest.mark.parametrize(
    "name",
    ["", "/etc/passwd", "C:/x", "root\\bin", "root/../x", "root/a:b", "other/x", "root/\x00"],
)
def test_unsafe_member_names(name: str) -> None:
    with pytest.raises(FetchError):
        member_path(name, "root")


def test_safe_member_names() -> None:
    assert str(member_path("root/./bin//ffmpeg", "root")) == "root/bin/ffmpeg"
    assert str(member_path("root/", "root")) == "root"


def test_an_archive_without_a_top_folder_still_refuses_unsafe_names() -> None:
    assert str(member_path("tool.exe", None)) == "tool.exe"
    assert str(member_path("./Plugin/x.csv", None)) == "Plugin/x.csv"
    for name in ("../x", "/etc/passwd", "C:/x", "a\\b", "a:b"):
        with pytest.raises(FetchError):
            member_path(name, None)


def test_a_zip_without_a_top_folder_is_extracted_as_it_is(tmp_path: Path) -> None:
    archive = tmp_path / "a.zip"
    archive.write_bytes(zip_bytes({"tool.exe": b"MZ", "Plugin/x.csv": b"csv"}))
    dest = tmp_path / "out"
    dest.mkdir()
    fetch_module.safe_extract(archive, "zip", None, dest, CancelToken())
    assert (dest / "tool.exe").read_bytes() == b"MZ"
    assert (dest / "Plugin" / "x.csv").read_bytes() == b"csv"


def test_a_tar_without_a_top_folder_is_refused(tmp_path: Path) -> None:
    archive = tmp_path / "a.tar.xz"
    archive.write_bytes(_archive_with())
    with pytest.raises(FetchError, match="needs a top folder"):
        fetch_module.safe_extract(archive, "tar.xz", None, tmp_path, CancelToken())
    assert list(tmp_path.iterdir()) == [archive]


@pytest.mark.anyio
async def test_the_fetch_helper_sees_every_step_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def two_steps(tasks: TaskManager, **kwargs: object) -> TaskInfo:
        async def fn(ctx: Any) -> None:
            ctx.progress(10.0, "first step")
            ctx.progress(20.0, "second step")

        return tasks.start("tools_fetch", fn, message="Fetching")

    monkeypatch.setattr(sys.modules[__name__], "start_fetch", two_steps)
    fetch = Fetch(tmp_path / "data")
    final, _ = await fetch(tmp_path / "unused.toml")
    assert final.state is TaskState.DONE
    assert fetch.messages[-2:] == ["first step", "second step"]
    assert fetch.percents == [10.0, 20.0]


@POSIX_ONLY
@pytest.mark.anyio
async def test_fetch_installs_the_build_and_skips_an_intact_install(
    tmp_path: Path, server: LocalServer, fetch: Fetch
) -> None:
    data = fake_archive("linux-x64", tmp_path / "work")
    route = server.add("/ffmpeg-test-linux64.tar.xz", data)
    manifest = write_manifest(
        tmp_path / "ffmpeg.toml",
        {"default": [Archive(server.url("/ffmpeg-test-linux64.tar.xz"), data, "linux-x64")]},
    )
    final, result = await fetch(manifest)
    assert final.state is TaskState.DONE, final.error
    install = tmp_path / "data" / "tools" / "ffmpeg"
    assert result.install_dir == install
    assert result.ffmpeg == install / "bin" / "ffmpeg"
    assert result.ffprobe == install / "bin" / "ffprobe"
    assert (result.build, result.platform, result.version) == ("default", "linux-x64", FAKE_VERSION)
    assert result.downloaded is True
    assert final.result == result.model_dump(mode="json")
    # The archive's root folder became the install folder (bin/, lib/ with its link).
    assert os.access(install / "bin" / "ffmpeg", os.X_OK)
    assert (install / "lib" / "libavfake.so.62").is_symlink()
    assert os.readlink(install / "lib" / "libavfake.so.62") == "libavfake.so.62.1"
    assert (install / "LICENSE.txt").read_text() == "GPL"
    marker = installed_build(install)
    assert marker is not None
    assert marker["sha256"] == sha256(data)
    assert marker["version"] == FAKE_VERSION
    assert marker["layout"] == "bundled"
    assert "bin/ffmpeg" in marker["files"]
    assert fetch.rescans == 1
    assert route.requests == 1
    assert leftovers(fetch.data_dir) == []
    assert fetch.messages[0] == "Fetching the FFmpeg build 'default'"
    for expected in (
        "Reading the manifest",
        f"Checking the build in {install}",
        "Downloading ffmpeg-test-linux64.tar.xz",
        "Checking the size and SHA-256",
        "Extracting ffmpeg-test-linux64.tar.xz",
        "Checking ffmpeg -version and ffprobe -version",
        f"Installing into {install}",
        "Running tool discovery",
    ):
        assert expected in fetch.messages
    assert fetch.percents == sorted(fetch.percents)
    assert final.progress == 100.0

    # Idempotent: an intact install is not downloaded again.
    final, again = await fetch(manifest)
    assert final.state is TaskState.DONE, final.error
    assert again.downloaded is False
    assert route.requests == 1
    assert fetch.rescans == 2

    # A changed file is a damaged install: it is downloaded and replaced.
    (install / "LICENSE.txt").write_text("changed")
    final, third = await fetch(manifest)
    assert final.state is TaskState.DONE, final.error
    assert third.downloaded is True
    assert route.requests == 2
    assert (install / "LICENSE.txt").read_text() == "GPL"
    assert leftovers(fetch.data_dir) == []


@pytest.mark.anyio
async def test_another_platform_goes_next_to_the_bundled_folder(
    tmp_path: Path, server: LocalServer, fetch: Fetch
) -> None:
    """A foreign platform is downloaded and verified, not run, and installed where discovery
    never looks; ``rescan`` is not called."""
    other = foreign_platform()
    data = fake_archive(other, tmp_path / "work")
    server.add(f"/a.{'zip' if other == 'windows-x64' else 'tar.xz'}", data)
    url = server.url(f"/a.{'zip' if other == 'windows-x64' else 'tar.xz'}")
    manifest = write_manifest(tmp_path / "m.toml", {"default": [Archive(url, data, other)]})
    final, result = await fetch(manifest, platform=other)
    assert final.state is TaskState.DONE, final.error
    install = tmp_path / "data" / "tools" / f"ffmpeg-{other}"
    assert result.install_dir == install
    assert result.platform == other
    assert fetch.rescans == 0
    assert not (tmp_path / "data" / "tools" / "ffmpeg").exists()
    assert result.ffmpeg.is_file()
    assert "Checking ffmpeg -version and ffprobe -version" not in fetch.messages


@pytest.mark.anyio
async def test_a_file_url(tmp_path: Path, fetch: Fetch) -> None:
    other = foreign_platform()
    data = fake_archive(other, tmp_path / "work")
    archive = tmp_path / "mirror" / f"build.{'zip' if other == 'windows-x64' else 'tar.xz'}"
    archive.parent.mkdir()
    archive.write_bytes(data)
    manifest = write_manifest(
        tmp_path / "m.toml", {"default": [Archive(archive.as_uri(), data, other)]}
    )
    final, result = await fetch(manifest, platform=other)
    assert final.state is TaskState.DONE, final.error
    assert result.downloaded is True
    assert installed_build(result.install_dir) is not None


async def _installed_foreign(
    tmp_path: Path, server: LocalServer, fetch: Fetch
) -> tuple[str, Path, dict[str, Any]]:
    """A foreign build installed first (the "old" build of the failure tests)."""
    other = foreign_platform()
    data = fake_archive(other, tmp_path / "work")
    path = f"/old.{archive_ext(other)}"
    server.add(path, data)
    manifest = write_manifest(
        tmp_path / "old.toml", {"default": [Archive(server.url(path), data, other)]}
    )
    final, result = await fetch(manifest, platform=other)
    assert final.state is TaskState.DONE, final.error
    marker = installed_build(result.install_dir)
    assert marker is not None
    return other, result.install_dir, marker


@pytest.mark.anyio
async def test_a_bad_checksum_installs_nothing_and_keeps_the_old_build(
    tmp_path: Path, server: LocalServer, fetch: Fetch
) -> None:
    other, install, marker = await _installed_foreign(tmp_path, server, fetch)
    # The pinned hash is of another archive (so the old install does not count), and the
    # server sends the old archive: the same size, another SHA-256.
    data = fake_archive(other, tmp_path / "work")
    files = sorted(p.relative_to(install) for p in install.rglob("*") if p.is_file())
    server.add(f"/new.{archive_ext(other)}", data)
    pinned = sha256(b"another build")
    manifest = write_manifest(
        tmp_path / "new.toml",
        {"default": [Archive(server.url(f"/new.{archive_ext(other)}"), data, other, sha=pinned)]},
    )
    final, result = await fetch(manifest, platform=other)
    assert final.state is TaskState.FAILED
    assert result is None
    assert final.error is not None
    assert f"the SHA-256 is {sha256(data)}, expected {pinned}" in final.error
    assert installed_build(install) == marker
    assert sorted(p.relative_to(install) for p in install.rglob("*") if p.is_file()) == files
    assert leftovers(fetch.data_dir) == []


@pytest.mark.anyio
async def test_a_longer_download_stops_at_the_pinned_size(
    tmp_path: Path, server: LocalServer, fetch: Fetch
) -> None:
    other = foreign_platform()
    data = fake_archive(other, tmp_path / "work")
    route = server.add(f"/a.{archive_ext(other)}", data, extra=b"x" * 200_000)
    manifest = write_manifest(
        tmp_path / "m.toml",
        {"default": [Archive(server.url(f"/a.{archive_ext(other)}"), data, other)]},
    )
    final, _ = await fetch(manifest, platform=other)
    assert final.state is TaskState.FAILED
    assert final.error is not None
    assert "larger than the pinned size" in final.error
    assert route.requests == 1  # not retried
    assert not install_dir_for(fetch.data_dir, other, host_platform()).exists()
    assert leftovers(fetch.data_dir) == []


@pytest.mark.anyio
async def test_a_short_download_fails_the_size_check(
    tmp_path: Path, server: LocalServer, fetch: Fetch
) -> None:
    other = foreign_platform()
    data = fake_archive(other, tmp_path / "work")
    server.add(f"/a.{archive_ext(other)}", data[:100])
    manifest = write_manifest(
        tmp_path / "m.toml",
        {"default": [Archive(server.url(f"/a.{archive_ext(other)}"), data, other)]},
    )
    final, _ = await fetch(manifest, platform=other)
    assert final.state is TaskState.FAILED
    assert final.error is not None
    assert f"the size is 100 bytes, expected {len(data)}" in final.error


@pytest.mark.anyio
async def test_server_errors_are_retried(
    tmp_path: Path, server: LocalServer, fetch: Fetch, monkeypatch: pytest.MonkeyPatch
) -> None:
    waits: list[float] = []
    monkeypatch.setattr(fetch_module, "_sleep", lambda seconds, cancel: waits.append(seconds))
    other = foreign_platform()
    data = fake_archive(other, tmp_path / "work")
    route = server.add(f"/a.{archive_ext(other)}", data, fail=[503, 500])
    manifest = write_manifest(
        tmp_path / "m.toml",
        {"default": [Archive(server.url(f"/a.{archive_ext(other)}"), data, other)]},
    )
    final, _ = await fetch(manifest, platform=other)
    assert final.state is TaskState.DONE, final.error
    assert route.requests == 3
    assert waits == [2.0, 4.0]


@pytest.mark.anyio
async def test_not_found_is_not_retried(tmp_path: Path, server: LocalServer, fetch: Fetch) -> None:
    other = foreign_platform()
    data = fake_archive(other, tmp_path / "work")
    route = server.add(f"/a.{archive_ext(other)}", data, fail=[404])
    manifest = write_manifest(
        tmp_path / "m.toml",
        {"default": [Archive(server.url(f"/a.{archive_ext(other)}"), data, other)]},
    )
    final, _ = await fetch(manifest, platform=other)
    assert final.state is TaskState.FAILED
    assert final.error is not None
    assert "the download failed after 1 attempt(s)" in final.error
    assert "404" in final.error
    assert final.error_code is None  # the server was reached
    assert route.requests == 1


@pytest.mark.anyio
async def test_a_refused_connection_is_tried_twice(
    tmp_path: Path, fetch: Fetch, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fetch_module, "_sleep", lambda seconds, cancel: None)
    other = foreign_platform()
    data = b"x"
    # A loopback port that nothing listens on: connection refused at once.
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}/a.{archive_ext(other)}"
    manifest = write_manifest(tmp_path / "m.toml", {"default": [Archive(url, data, other)]})
    final, _ = await fetch(manifest, platform=other)
    assert final.state is TaskState.FAILED
    assert final.error is not None
    # The reason in the brackets is the system's text for a refused connection.
    assert re.match(
        r"cannot reach the download server 127\.0\.0\.1 \([^;]+; 2 attempt\(s\)\)", final.error
    )
    assert final.error_code == "tools.fetch_offline"


def _transport(error: BaseException, calls: list[str]) -> Callable[..., Any]:
    """A fake ``urlopen``: every request fails with ``error``, as without a network."""

    def urlopen(request: urllib.request.Request, *args: object, **kwargs: object) -> Any:
        calls.append(request.full_url)
        raise error

    return urlopen


#: An error before the response: (error, its reason text, the attempts it gets).
OFFLINE_ERRORS = {
    "no-name-resolution": (
        urllib.error.URLError(socket.gaierror(-3, "Temporary failure in name resolution")),
        "Temporary failure in name resolution",
        1,
    ),
    "network-unreachable": (
        urllib.error.URLError(OSError(errno.ENETUNREACH, "Network is unreachable")),
        "Network is unreachable",
        1,
    ),
    "host-unreachable": (
        urllib.error.URLError(OSError(errno.EHOSTUNREACH, "No route to host")),
        "No route to host",
        1,
    ),
    "network-down": (
        urllib.error.URLError(OSError(errno.ENETDOWN, "Network is down")),
        "Network is down",
        1,
    ),
    "connect-timeout": (urllib.error.URLError(TimeoutError("timed out")), "timed out", 2),
    "response-timeout": (TimeoutError("timed out"), "timed out", 2),
    "refused": (
        ConnectionRefusedError(errno.ECONNREFUSED, "Connection refused"),
        "Connection refused",
        2,
    ),
}


@pytest.mark.anyio
@pytest.mark.parametrize("case", sorted(OFFLINE_ERRORS))
async def test_without_a_network_the_fetch_is_offline_and_installs_nothing(
    tmp_path: Path,
    fetch: Fetch,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    case: str,
) -> None:
    error, why, attempts = OFFLINE_ERRORS[case]
    calls: list[str] = []
    waits: list[float] = []
    monkeypatch.setattr(urllib.request, "urlopen", _transport(error, calls))
    monkeypatch.setattr(fetch_module, "_sleep", lambda seconds, cancel: waits.append(seconds))
    host = host_platform() or "linux-x64"
    url = f"https://downloads.example/ffmpeg.{archive_ext(host)}"
    manifest = write_manifest(tmp_path / "m.toml", {"default": [Archive(url, b"x", host)]})
    caplog.set_level(logging.INFO, logger="reframe.tools.fetch")
    final, result = await fetch(manifest, platform=host)
    assert final.state is TaskState.FAILED
    assert final.error_code == "tools.fetch_offline"
    assert final.error is not None
    assert final.error.startswith(
        f"cannot reach the download server downloads.example ({why}; {attempts} attempt(s)). "
    )
    # The message names what to do instead.
    assert "install the build from its archive file" in final.error
    assert "REFRAME_FFMPEG" in final.error
    assert "Settings > Tools" in final.error
    assert result is None
    assert len(calls) == attempts
    assert waits == [2.0, 4.0, 8.0][: attempts - 1]
    assert not (fetch.data_dir / "tools" / "ffmpeg").exists()
    assert leftovers(fetch.data_dir) == []
    assert fetch.rescans == 0
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert [r.name for r in errors] == ["reframe.tools.fetch"]
    assert (
        errors[0].getMessage()
        == f"FFmpeg download of build 'default' for {host} failed: {final.error}"
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error", "attempts"),
    [
        (urllib.error.URLError(ssl.SSLCertVerificationError(1, "certificate verify failed")), 1),
        (urllib.error.URLError(ssl.SSLError(1, "[SSL: WRONG_VERSION_NUMBER]")), 1),
        (ssl.SSLError(1, "[SSL: SSLV3_ALERT_HANDSHAKE_FAILURE]"), 1),
        (ConnectionResetError(errno.ECONNRESET, "Connection reset by peer"), fetch_module.ATTEMPTS),
        (urllib.error.URLError("unknown url type: ftp"), fetch_module.ATTEMPTS),
    ],
    ids=["certificate", "tls", "tls-unwrapped", "reset", "url"],
)
async def test_other_download_errors_have_no_code(
    tmp_path: Path,
    fetch: Fetch,
    monkeypatch: pytest.MonkeyPatch,
    error: BaseException,
    attempts: int,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(urllib.request, "urlopen", _transport(error, calls))
    monkeypatch.setattr(fetch_module, "_sleep", lambda seconds, cancel: None)
    other = foreign_platform()
    url = f"https://downloads.example/ffmpeg.{archive_ext(other)}"
    manifest = write_manifest(tmp_path / "m.toml", {"default": [Archive(url, b"x", other)]})
    final, _ = await fetch(manifest, platform=other)
    assert final.state is TaskState.FAILED
    assert final.error is not None
    assert final.error.startswith(f"the download failed after {attempts} attempt(s): ")
    assert final.error_code is None
    assert len(calls) == attempts


class _BrokenResponse:
    """A response whose body breaks with ``error`` after its first bytes."""

    def __init__(self, error: BaseException) -> None:
        self._error = error
        self._sent = False

    def read1(self, size: int) -> bytes:
        if not self._sent:
            self._sent = True
            return b"abc"
        raise self._error

    def __enter__(self) -> _BrokenResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        pass


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("timed out"),
        ConnectionResetError(errno.ECONNRESET, "Connection reset by peer"),
        http.client.IncompleteRead(b"abc", 97),
        ssl.SSLEOFError(8, "EOF occurred in violation of protocol"),
    ],
    ids=["read-timeout", "reset", "incomplete", "tls-eof"],
)
def test_an_error_in_the_middle_of_the_transfer_is_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    calls: list[str] = []

    def urlopen(request: urllib.request.Request, *args: object, **kwargs: object) -> Any:
        calls.append(request.full_url)
        return _BrokenResponse(error)

    waits: list[float] = []
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(fetch_module, "_sleep", lambda seconds, cancel: waits.append(seconds))
    with pytest.raises(FetchError, match=r"\b4 attempt\(s\)"):
        fetch_module.download(
            "https://downloads.example/a.tar.xz", tmp_path / "a", size=100, cancel=CancelToken()
        )
    assert len(calls) == fetch_module.ATTEMPTS
    assert waits == [2.0, 4.0, 8.0]
    assert not (tmp_path / "a").exists()


def test_a_tls_failure_with_a_real_server_is_not_retried(tmp_path: Path) -> None:
    """A server that answers the TLS handshake with plain text: ssl's own error."""
    connections: list[int] = []
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()

        def serve() -> None:
            while True:
                try:
                    conn, _ = listener.accept()
                except OSError:
                    return
                connections.append(1)
                with conn:
                    conn.recv(4096)
                    conn.sendall(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        port = listener.getsockname()[1]
        started = time.monotonic()
        with pytest.raises(FetchError) as caught:
            fetch_module.download(
                f"https://127.0.0.1:{port}/a.tar.xz", tmp_path / "a", size=100,
                cancel=CancelToken(), timeout=5.0,
            )  # fmt: skip
        took = time.monotonic() - started
    assert caught.value.code is None
    assert str(caught.value).startswith("the download failed after 1 attempt(s): ")
    assert "SSL" in str(caught.value)
    assert connections == [1]
    assert took < 2.0


def _tar_case(kind: str) -> bytes:
    root = LINUX_ROOT
    good = [
        (tar_dir(root), None),
        (tar_file(f"{root}/bin/ffmpeg", 0o755), b"x"),
        (tar_file(f"{root}/bin/ffprobe", 0o755), b"x"),
    ]
    bad: dict[str, Any] = {
        "absolute": (tar_file("/tmp/reframe-evil"), b"x"),
        "dotdot": (tar_file(f"{root}/../evil"), b"x"),
        "outside": (tar_file("other/evil"), b"x"),
        "symlink-out": (tar_link(f"{root}/lib/evil", "../../outside"), None),
        "symlink-abs": (tar_link(f"{root}/lib/evil", "/etc/passwd"), None),
        "hardlink-out": (tar_link(f"{root}/lib/evil", "other/x", hard=True), None),
    }
    if kind == "device":
        info = tarfile.TarInfo(f"{root}/dev")
        info.type = tarfile.CHRTYPE
        return tar_xz([*good, (info, None)])
    return tar_xz([*good, bad[kind]])


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("kind", "message"),
    [
        ("absolute", "unsafe archive member name"),
        ("dotdot", "unsafe archive member name"),
        ("outside", "is outside the folder"),
        ("symlink-out", "points outside"),
        ("symlink-abs", "is absolute"),
        ("hardlink-out", "is outside the folder"),
        ("device", "unsupported archive member type"),
        ("zip-symlink", "symbolic link in the zip archive"),
        ("garbage", "is not a valid"),
        ("no-ffprobe", "bin/ffprobe is not in the archive"),
    ],
)
async def test_an_unsafe_or_broken_archive_installs_nothing(
    tmp_path: Path, server: LocalServer, fetch: Fetch, kind: str, message: str
) -> None:
    """Checked before any file is written; the archive is downloaded for the host platform's
    format but installed as a foreign build, so nothing runs."""
    if kind == "zip-symlink":
        platform, data = (
            "windows-x64",
            zip_bytes({f"{WINDOWS_ROOT}/bin/ffmpeg.exe": b"x"}, symlink=f"{WINDOWS_ROOT}/x"),
        )
    elif kind == "garbage":
        platform, data = "linux-x64", b"not an xz archive at all"
    elif kind == "no-ffprobe":
        platform = "linux-x64"
        data = tar_xz([(tar_dir(LINUX_ROOT), None), (tar_file(f"{LINUX_ROOT}/bin/ffmpeg"), b"x")])
    else:
        platform, data = "linux-x64", _tar_case(kind)
    server.add(f"/a.{archive_ext(platform)}", data)
    manifest = write_manifest(
        tmp_path / "m.toml",
        {"default": [Archive(server.url(f"/a.{archive_ext(platform)}"), data, platform)]},
    )
    host = host_platform()
    final, _ = await fetch(manifest, platform=platform)
    assert final.state is TaskState.FAILED
    assert final.error is not None
    assert message in final.error
    assert not install_dir_for(fetch.data_dir, platform, host).exists()
    assert leftovers(fetch.data_dir) == []
    assert not (tmp_path / "data" / "outside").exists()
    assert not (tmp_path / "evil").exists()


def _archive_with(*links: tuple[str, str]) -> bytes:
    root = LINUX_ROOT
    members = [
        (tar_dir(root), None),
        (tar_dir(f"{root}/bin"), None),
        (tar_file(f"{root}/bin/ffmpeg", 0o755), b"#!/bin/sh\n"),
        (tar_file(f"{root}/bin/ffprobe", 0o755), b"#!/bin/sh\n"),
        (tar_dir(f"{root}/s"), None),
    ]
    members += [(tar_link(f"{root}/{name}", target), None) for name, target in links]
    return tar_xz(members)


@pytest.mark.parametrize(
    "links",
    [
        # Each link is lexically inside the root; u points above it.
        (("s/t", ".."), ("s/u", "t/..")),
        # The same in the other order (links are checked against all others).
        (("s/u", "t/.."), ("s/t", "..")),
        # Leaves the root and comes back by its name: after the install the root is renamed.
        (("s/v", "../../" + LINUX_ROOT + "/bin"),),
        # A loop.
        (("s/a", "b"), ("s/b", "a")),
    ],
)
def test_a_link_chain_that_leaves_the_build_folder_is_refused(
    tmp_path: Path, links: tuple[tuple[str, str], ...]
) -> None:
    archive = tmp_path / "a.tar.xz"
    archive.write_bytes(_archive_with(*links))
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(FetchError, match="points outside"):
        fetch_module.safe_extract(archive, "tar.xz", LINUX_ROOT, dest, CancelToken())
    assert list(dest.iterdir()) == []


def test_a_member_inside_a_linked_folder_is_refused(tmp_path: Path) -> None:
    """``s/t/evil -> ../x`` is written through the link ``s/t -> ..``, and it points
    above the folder."""
    root = LINUX_ROOT
    members = [
        (tar_dir(root), None),
        (tar_dir(f"{root}/bin"), None),
        (tar_file(f"{root}/bin/ffmpeg", 0o755), b"#!/bin/sh\n"),
        (tar_file(f"{root}/bin/ffprobe", 0o755), b"#!/bin/sh\n"),
        (tar_dir(f"{root}/s"), None),
        (tar_link(f"{root}/s/t", ".."), None),
        (tar_link(f"{root}/s/t/evil", "../x"), None),
    ]
    archive = tmp_path / "a.tar.xz"
    archive.write_bytes(tar_xz(members))
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(FetchError, match="inside the link"):
        fetch_module.safe_extract(archive, "tar.xz", LINUX_ROOT, dest, CancelToken())
    assert list(dest.iterdir()) == []


def test_links_inside_the_build_folder_are_kept(tmp_path: Path) -> None:
    archive = tmp_path / "a.tar.xz"
    archive.write_bytes(_archive_with(("s/t", ".."), ("s/w", "t/bin/ffmpeg"), ("s/x", "w")))
    dest = tmp_path / "out"
    dest.mkdir()
    fetch_module.safe_extract(archive, "tar.xz", LINUX_ROOT, dest, CancelToken())
    assert os.readlink(dest / LINUX_ROOT / "s" / "x") == "w"
    assert (dest / LINUX_ROOT / "s" / "x").resolve() == (dest / LINUX_ROOT / "bin" / "ffmpeg")


@POSIX_ONLY
@pytest.mark.anyio
async def test_a_build_that_prints_another_version_is_not_installed(
    tmp_path: Path, server: LocalServer, fetch: Fetch
) -> None:
    data = fake_archive("linux-x64", tmp_path / "work", version_ok=False)
    server.add("/a.tar.xz", data)
    manifest = write_manifest(
        tmp_path / "m.toml", {"default": [Archive(server.url("/a.tar.xz"), data, "linux-x64")]}
    )
    final, _ = await fetch(manifest)
    assert final.state is TaskState.FAILED
    assert final.error is not None
    assert "the downloaded ffmpeg does not work on this computer" in final.error
    assert "it prints 'ffmpeg version n8.0" in final.error
    assert not (tmp_path / "data" / "tools" / "ffmpeg").exists()
    assert fetch.rescans == 0
    assert leftovers(fetch.data_dir) == []


@pytest.mark.anyio
async def test_a_folder_that_fetch_did_not_install_is_never_replaced(
    tmp_path: Path, server: LocalServer, fetch: Fetch
) -> None:
    other = foreign_platform()
    install = install_dir_for(fetch.data_dir, other, host_platform())
    install.mkdir(parents=True)
    (install / "my-build.txt").write_text("mine")
    data = fake_archive(other, tmp_path / "work")
    route = server.add(f"/a.{archive_ext(other)}", data)
    manifest = write_manifest(
        tmp_path / "m.toml",
        {"default": [Archive(server.url(f"/a.{archive_ext(other)}"), data, other)]},
    )
    final, _ = await fetch(manifest, platform=other)
    assert final.state is TaskState.FAILED
    assert final.error is not None
    assert "is never replaced" in final.error
    assert (install / "my-build.txt").read_text() == "mine"
    assert route.requests == 0
    # An empty folder is fine.
    (install / "my-build.txt").unlink()
    final, _ = await fetch(manifest, platform=other)
    assert final.state is TaskState.DONE, final.error


@pytest.mark.anyio
async def test_a_file_at_the_install_path_is_refused(
    tmp_path: Path, server: LocalServer, fetch: Fetch
) -> None:
    other = foreign_platform()
    install = install_dir_for(fetch.data_dir, other, host_platform())
    install.parent.mkdir(parents=True)
    install.write_text("a file")
    data = fake_archive(other, tmp_path / "work")
    server.add(f"/a.{archive_ext(other)}", data)
    manifest = write_manifest(
        tmp_path / "m.toml",
        {"default": [Archive(server.url(f"/a.{archive_ext(other)}"), data, other)]},
    )
    final, _ = await fetch(manifest, platform=other)
    assert final.state is TaskState.FAILED
    assert final.error is not None
    assert "is not a folder" in final.error


@pytest.mark.anyio
async def test_unknown_build_and_platform(
    tmp_path: Path, server: LocalServer, fetch: Fetch
) -> None:
    other = foreign_platform()
    data = b"x"
    manifest = write_manifest(
        tmp_path / "m.toml",
        {"default": [Archive(server.url(f"/a.{archive_ext(other)}"), data, other)]},
    )
    final, _ = await fetch(manifest, build="nightly")
    assert final.state is TaskState.FAILED
    assert final.error is not None
    assert "the manifest has no build 'nightly' (it has default)" in final.error
    host = "linux-x64" if other == "windows-x64" else "windows-x64"
    final, _ = await fetch(manifest, platform=host)
    assert final.error is not None
    assert f"the build 'default' has no archive for {host}" in final.error
    final, _ = await fetch(tmp_path / "missing.toml")
    assert final.error is not None
    assert "cannot read the manifest" in final.error


@pytest.mark.anyio
async def test_an_unsupported_host_needs_a_platform(
    tmp_path: Path, fetch: Fetch, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fetch_module, "host_platform", lambda: None)
    manifest = write_manifest(
        tmp_path / "m.toml",
        {"default": [Archive("https://example.invalid/a.tar.xz", b"x", "linux-x64")]},
    )
    final, _ = await fetch(manifest)
    assert final.error is not None
    assert "no FFmpeg build is pinned for this computer" in final.error


@pytest.mark.anyio
async def test_a_cancel_stops_a_slow_download_at_once(tmp_path: Path, server: LocalServer) -> None:
    other = foreign_platform()
    url = f"/slow.{archive_ext(other)}"
    data = fake_archive(other, tmp_path / "work") + b"\0" * (4 << 20)
    route = server.add(url, data, delay=0.4)
    manifest = write_manifest(
        tmp_path / "m.toml", {"default": [Archive(server.url(url), data, other)]}
    )
    tasks = TaskManager()
    data_dir = tmp_path / "data"
    info = start_fetch(
        tasks, data_dir=data_dir, rescan=lambda: asyncio.sleep(0, _toolset()), platform=other,
        manifest=manifest,
    )  # fmt: skip
    deadline = time.monotonic() + 30
    while route.requests == 0:
        assert time.monotonic() < deadline
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.6)
    started = time.monotonic()
    assert tasks.cancel(info.id)
    final = await asyncio.wait_for(tasks.wait(info.id), 60)
    elapsed = time.monotonic() - started
    assert final.state is TaskState.CANCELLED
    assert elapsed < 2.5, elapsed
    assert leftovers(data_dir) == []
    assert not install_dir_for(data_dir, other, host_platform()).exists()


@POSIX_ONLY
@pytest.mark.anyio
@pytest.mark.parametrize("when", ["during discovery", "during the swap"])
async def test_a_cancel_after_the_swap_finishes_and_says_so(
    tmp_path: Path, server: LocalServer, monkeypatch: pytest.MonkeyPatch, when: str
) -> None:
    data = fake_archive("linux-x64", tmp_path / "work")
    server.add("/ffmpeg-test-linux64.tar.xz", data)
    manifest = write_manifest(
        tmp_path / "ffmpeg.toml",
        {"default": [Archive(server.url("/ffmpeg-test-linux64.tar.xz"), data, "linux-x64")]},
    )
    tasks = TaskManager()
    loop = asyncio.get_running_loop()
    in_rescan = asyncio.Event()
    rescans: list[str] = []
    task_id: list[str] = []

    async def rescan() -> ToolSet:  # tool discovery takes a moment (ffmpeg -version …)
        in_rescan.set()
        await asyncio.sleep(0.3)
        rescans.append("done")
        return _toolset()

    if when == "during the swap":
        swap = fetch_module._swap_into_place

        def swap_then_cancel(new: Path, install_dir: Path, aside: Path) -> None:
            swap(new, install_dir, aside)
            loop.call_soon_threadsafe(tasks.cancel, task_id[0])

        monkeypatch.setattr(fetch_module, "_swap_into_place", swap_then_cancel)

    data_dir = tmp_path / "data"
    info = start_fetch(tasks, data_dir=data_dir, rescan=rescan, manifest=manifest)
    task_id.append(info.id)
    if when == "during discovery":
        await asyncio.wait_for(in_rescan.wait(), 60)
        tasks.cancel(info.id)  # what Ctrl+C in `reframe tools fetch` does
    final = await asyncio.wait_for(tasks.wait(info.id), 60)
    marker = installed_build(data_dir / "tools" / "ffmpeg")
    assert final.state is TaskState.CANCELLED
    assert marker is not None
    assert rescans == ["done"]
    assert final.message is not None
    assert final.message.startswith("Installed FFmpeg")
    assert leftovers(data_dir) == []


@pytest.mark.anyio
async def test_a_killed_fetchs_work_folder_is_removed_by_the_next_fetch(
    tmp_path: Path, server: LocalServer
) -> None:
    """A killed fetch leaves its work folder. A fresh one stays: another fetch may be running."""
    other = foreign_platform()
    url = f"/a.{archive_ext(other)}"
    data = fake_archive(other, tmp_path / "work")
    server.add(url, data)
    manifest = write_manifest(
        tmp_path / "m.toml", {"default": [Archive(server.url(url), data, other)]}
    )
    data_dir = tmp_path / "data"
    tools = data_dir / "tools"
    stale = tools / ".fetch-killed"
    (stale / "extract").mkdir(parents=True)
    (stale / "extract" / "ffmpeg.tar.xz").write_bytes(b"x" * 1000)
    old = time.time() - 7 * 3600
    for path in (stale / "extract" / "ffmpeg.tar.xz", stale / "extract", stale):
        os.utime(path, (old, old))
    fresh = tools / ".fetch-running"
    fresh.mkdir()
    (fresh / "part").write_bytes(b"y")
    tasks = TaskManager()
    info = start_fetch(
        tasks, data_dir=data_dir, rescan=lambda: asyncio.sleep(0, _toolset()), platform=other,
        manifest=manifest,
    )  # fmt: skip
    final = await asyncio.wait_for(tasks.wait(info.id), 60)
    assert final.state is TaskState.DONE, final.error
    assert leftovers(data_dir) == [".fetch-running"]


def test_swap_puts_the_old_build_back_when_the_new_one_cannot_move(tmp_path: Path) -> None:
    install = tmp_path / "ffmpeg"
    install.mkdir()
    (install / "old.txt").write_text("old")
    with pytest.raises(FetchError, match="cannot replace"):
        fetch_module._swap_into_place(tmp_path / "missing", install, tmp_path / "aside")
    assert (install / "old.txt").read_text() == "old"


def test_permission_errors_are_retried() -> None:
    waits: list[float] = []
    calls: list[int] = []

    def flaky() -> None:
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError("in use")

    fetch_module._retry_on_permission(flaky, sleep=waits.append)
    assert len(calls) == 3
    assert waits == [0.5, 1.0]
    with pytest.raises(PermissionError):
        fetch_module._retry_on_permission(
            lambda: (_ for _ in ()).throw(PermissionError("x")), sleep=waits.append
        )


def test_installed_build_and_damaged_markers(tmp_path: Path) -> None:
    assert installed_build(tmp_path) is None
    (tmp_path / MARKER_NAME).write_text("[1]")
    assert installed_build(tmp_path) is None
    (tmp_path / MARKER_NAME).write_text("{not json")
    assert installed_build(tmp_path) is None
    (tmp_path / MARKER_NAME).write_text(json.dumps({"sha256": "a", "files": {}}))
    entry = load_manifest().get("default")
    assert entry is not None
    pbuild = entry.platforms["linux-x64"]
    assert not fetch_module.is_installed(tmp_path, pbuild)  # another archive
    (tmp_path / MARKER_NAME).write_text(json.dumps({"sha256": pbuild.sha256, "files": {}}))
    assert not fetch_module.is_installed(tmp_path, pbuild)  # no files recorded


def test_sleep_ends_at_a_cancel() -> None:
    token = CancelToken()
    token.cancel()
    with pytest.raises(fetch_module._Stopped):
        fetch_module._sleep(30, token)
    fetch_module._sleep(0.01, CancelToken())


@pytest.mark.anyio
async def test_the_script_and_the_core_recognise_each_others_install(
    tmp_path: Path, server: LocalServer, fetch: Fetch
) -> None:
    """The script and ``reframe tools fetch`` recognise each other's install by its marker."""
    script = load_script("fetch-tools.py", "fetch_tools_script")
    other = foreign_platform()
    data = fake_archive(other, tmp_path / "work")
    https = f"https://example.invalid/build.{archive_ext(other)}"
    script_manifest = write_manifest(
        tmp_path / "s.toml", {"default": [Archive(https, data, other)]}
    )
    route = server.add(f"/build.{archive_ext(other)}", data)
    local = server.url(f"/build.{archive_ext(other)}")
    manifest = write_manifest(tmp_path / "m.toml", {"default": [Archive(local, data, other)]})
    build = script.load_manifest(script_manifest)["default"]
    install = install_dir_for(fetch.data_dir, other, host_platform())
    downloads: list[str] = []

    def downloader(source: str, dest: Path) -> None:
        downloads.append(source)
        dest.write_bytes(data)

    script.install_bundled(build, build.platforms[other], install, downloader=downloader)
    assert downloads == [https]
    final, result = await fetch(manifest, platform=other)
    assert final.state is TaskState.DONE, final.error
    assert result.downloaded is False
    assert route.requests == 0

    # The other way round: our install, then the script finds it installed and verified.
    shutil.rmtree(install)
    final, result = await fetch(manifest, platform=other)
    assert final.state is TaskState.DONE, final.error
    assert result.downloaded is True
    script.install_bundled(build, build.platforms[other], install, downloader=downloader)
    assert downloads == [https]


@POSIX_ONLY
@pytest.mark.anyio
async def test_facade_fetch_makes_the_build_the_bundled_one(
    tmp_path: Path, server: LocalServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``Reframe.tools.fetch``: after the task, tool discovery picks the fetched build
    (origin ``bundled``), also over an ffmpeg on ``PATH``."""
    for var in ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    data = fake_archive("linux-x64", tmp_path / "work")
    server.add("/a.tar.xz", data)
    manifest = write_manifest(
        tmp_path / "m.toml", {"default": [Archive(server.url("/a.tar.xz"), data, "linux-x64")]}
    )
    async with await Reframe.create(
        tmp_path / "config", tmp_path / "data", cache_dir=tmp_path / "cache"
    ) as app:
        before = await app.tools.status()
        assert before.ffmpeg.status is ToolStatus.MISSING
        info = app.tools.fetch(manifest=manifest)
        final = await asyncio.wait_for(app.tasks.wait(info.id), 120)
        assert final.state is TaskState.DONE, final.error
        tools = app.tools.current
        assert tools is not None
        bundled = tmp_path / "data" / "tools" / "ffmpeg" / "bin"
        for name in ("ffmpeg", "ffprobe"):
            found = tools.get(name)
            assert found.status is ToolStatus.FOUND, found.reason
            assert found.origin is ToolOrigin.BUNDLED
            assert found.path == bundled / name
            assert found.version == FAKE_VERSION
