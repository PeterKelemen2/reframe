"""The FFmpeg builds: the offered list, the install from a file, the offline fetch, and the
start-up download of ``REFRAME_FFMPEG_BUILD``."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import socket
import sys
import tarfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from reframe.mediatask import TaskFailed
from reframe.models import TaskInfo, TaskState
from reframe.queue.lock import LOCK_FILE, StoreLock
from reframe.service import ToolsService
from reframe.tasks import TaskContext
from reframe.tools import ENV_VARS
from reframe.tools.fetch import MARKER_NAME, host_platform, install_dir_for, load_manifest
from reframe_server.__main__ import ConsoleFilter, _log_config
from reframe_testing import fake_tools as ft
from reframe_testing.server import Api, ApiFactory

pytestmark = pytest.mark.anyio

#: What the fake ffmpeg and ffprobe print after ``ffmpeg version``.
FAKE_VERSION = "n9.0.2-17-g2a571b6068-20260930"
ROOT = "ffmpeg-test-linux64"
ARCHIVE_NAME = "ffmpeg-test-linux64-gpl-shared.tar.xz"

POSIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="shell-script tools")
LINUX_X64_ONLY = pytest.mark.skipif(
    host_platform() != "linux-x64", reason="the fake build archive runs only on a linux-x64 host"
)


def _no_tools_found(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Discovery finds no FFmpeg: no override and an empty ``PATH``."""
    for var in ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    empty = tmp_path / "empty-path"
    empty.mkdir(exist_ok=True)
    monkeypatch.setenv("PATH", str(empty))


def _broken_on_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Discovery finds an ffmpeg and an ffprobe on ``PATH`` that do not run."""
    for var in ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    folder = tmp_path / "broken-path"
    folder.mkdir()
    for name in ("ffmpeg", "ffprobe"):
        tool = folder / name
        tool.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        tool.chmod(0o755)
    monkeypatch.setenv("PATH", str(folder))


def _autofetch_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "reframe_server.autofetch"]


def _tar_xz(members: list[tuple[str, int, bytes | None]]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz") as archive:
        for name, mode, data in members:
            info = tarfile.TarInfo(name)
            info.mode = mode
            if data is None:
                info.type = tarfile.DIRTYPE
                archive.addfile(info)
            else:
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _build_archive(work: Path) -> Path:
    """A small FFmpeg build in the layout of the BtbN archives: the fake tools."""
    tools = ft.make_fake_tools(work / "launchers", platform="linux")
    data = _tar_xz(
        [
            (ROOT, 0o755, None),
            (f"{ROOT}/bin", 0o755, None),
            (f"{ROOT}/bin/ffmpeg", 0o755, tools.ffmpeg.read_bytes()),
            (f"{ROOT}/bin/ffprobe", 0o755, tools.ffprobe.read_bytes()),
            (f"{ROOT}/LICENSE.txt", 0o644, b"GPL"),
        ]
    )
    archive = work / ARCHIVE_NAME
    archive.write_bytes(data)
    return archive


def _write_manifest(path: Path, archive: Path) -> Path:
    data = archive.read_bytes()
    path.write_text(
        f"""schema_version = 1

[builds.default]
offered = true
label = "Recommended"
summary = "The test build."
version = "{FAKE_VERSION}"
release_version = "9.0.2"
release_tag = "test"
license = "GPL-3.0-or-later"
source_repository = "https://example.invalid/ffmpeg"
source_commit = "0000000"

[builds.default.platforms.linux-x64]
url = "https://example.invalid/{ARCHIVE_NAME}"
sha256 = "{hashlib.sha256(data).hexdigest()}"
size = {len(data)}
format = "tar.xz"
root = "{ROOT}"
bin_dir = "bin"
ffmpeg = "bin/ffmpeg"
ffprobe = "bin/ffprobe"
""",
        encoding="utf-8",
    )
    return path


async def test_builds_lists_the_offered_builds_with_this_platforms_size(api: Api) -> None:
    response = await api.client.get("/api/system/tools/builds")
    assert response.status_code == 200
    body = response.json()
    names = [build["name"] for build in body["builds"]]
    assert names[:2] == ["default", "compat"]
    default = body["builds"][0]
    assert default["license"] == "GPL-3.0-or-later"
    assert default["label"]
    assert default["summary"]
    assert any("github.com/FFmpeg/FFmpeg/commit/" in link for link in default["source_links"])
    platform = host_platform()
    if platform is not None:
        pinned = load_manifest()["default"].platforms[platform]
        assert (default["size"], default["archive_url"], default["sha256"]) == (
            pinned.size,
            pinned.url,
            pinned.sha256,
        )
    assert body["installed"] is None


@LINUX_X64_ONLY
async def test_a_build_installed_from_a_file_through_the_api_is_found_by_get_system(
    make_api: ApiFactory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _no_tools_found(monkeypatch, tmp_path)
    async with make_api() as api:
        archive = _build_archive(api.media)
        manifest = _write_manifest(tmp_path / "ffmpeg.toml", archive)
        asked: list[tuple[Path, str | None]] = []

        def install_file(path: Path, *, build: str | None = None) -> TaskInfo:
            asked.append((path, build))
            return ToolsService.install_file(
                api.reframe.tools, path, build=build, manifest=manifest
            )

        monkeypatch.setattr(api.reframe.tools, "install_file", install_file)
        before = (await api.client.get("/api/system")).json()
        assert before["tools"]["ffmpeg"]["status"] == "missing"

        response = await api.client.post(
            "/api/system/tools/install-file", json={"path": str(archive)}
        )
        assert response.status_code == 202, response.text
        task = await api.reframe.tasks.wait(response.json()["task_id"])
        assert (task.state, task.error) == (TaskState.DONE, None)
        assert asked == [(archive, None)]

        tools = (await api.client.get("/api/system")).json()["tools"]
        install_dir = api.reframe.data_dir / "tools" / "ffmpeg"
        for name in ("ffmpeg", "ffprobe"):
            assert tools[name]["status"] == "found"
            assert tools[name]["origin"] == "bundled"
            assert Path(tools[name]["path"]).is_relative_to(install_dir)
        # The client sees the result's paths under "<data>": it matches the build in use by
        # the origin and the version.
        result = (await api.client.get(f"/api/tasks/{task.id}")).json()["result"]
        assert result["ffmpeg"] == "<data>/tools/ffmpeg/bin/ffmpeg"
        assert result["version"] == tools["ffmpeg"]["version"] == FAKE_VERSION
        builds = (await api.client.get("/api/system/tools/builds")).json()
        assert builds["installed"]["name"] == "default"


async def test_install_file_in_web_mode_refuses_a_path_outside_the_media_roots(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Path] = []
    monkeypatch.setattr(api.reframe.tools, "install_file", lambda path, **_: calls.append(path))
    archive = api.outside / ARCHIVE_NAME
    archive.write_bytes(b"x")
    response = await api.client.post("/api/system/tools/install-file", json={"path": str(archive)})
    assert (response.status_code, response.json()["code"]) == (403, "path.outside_roots")
    assert calls == []


async def test_install_file_in_desktop_mode_takes_any_path_and_the_build(
    make_api: ApiFactory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async with make_api(mode="desktop") as api:
        asked: list[tuple[Path, str | None]] = []

        async def nothing(_ctx: TaskContext) -> None:
            return None

        def install_file(path: Path, *, build: str | None = None) -> TaskInfo:
            asked.append((path, build))
            return api.reframe.tasks.start("tools_fetch", nothing)

        monkeypatch.setattr(api.reframe.tools, "install_file", install_file)
        archive = api.outside / ARCHIVE_NAME
        response = await api.client.post(
            "/api/system/tools/install-file", json={"path": str(archive), "build": "compat"}
        )
        assert response.status_code == 202
        assert response.headers["location"] == f"/api/tasks/{response.json()['task_id']}"
    assert asked == [(archive.resolve(), "compat")]


@pytest.mark.parametrize(
    ("route", "body"),
    [
        ("/api/system/tools/fetch", {"build": "override-test"}),
        ("/api/system/tools/install-file", {"path": "ARCHIVE", "build": "override-test"}),
        ("/api/system/tools/fetch", {"build": "nightly"}),
    ],
)
async def test_the_api_refuses_a_build_that_is_not_offered(
    make_api: ApiFactory, monkeypatch: pytest.MonkeyPatch, route: str, body: dict[str, str]
) -> None:
    started = _fake_fetch(monkeypatch)
    monkeypatch.setattr(
        ToolsService, "install_file", lambda self, _path, **kw: ToolsService.fetch(self, **kw)
    )
    async with make_api(mode="desktop") as api:
        archive = api.outside / ARCHIVE_NAME
        archive.write_bytes(b"x")
        if "path" in body:
            body = {**body, "path": str(archive)}
        response = await api.client.post(route, json=body)
    assert response.status_code == 422, response.text
    problem = response.json()
    assert problem["code"] == "tools.build_not_offered"
    assert problem["title"] == f"{body['build']!r} is not an FFmpeg build that Reframe offers"
    assert problem["detail"] == "The offered builds are default, compat."
    assert started == []


def _refused_url() -> str:
    """A loopback URL where nothing listens: the connection is refused."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"http://127.0.0.1:{port}/{ARCHIVE_NAME}"


async def test_a_fetch_that_cannot_reach_the_download_server_fails_with_fetch_offline(
    api: Api, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    platform = host_platform()
    assert platform is not None
    archive = _build_archive(tmp_path)
    manifest = _write_manifest(tmp_path / "ffmpeg.toml", archive)
    text = manifest.read_text(encoding="utf-8").replace("linux-x64", platform)
    manifest.write_text(
        text.replace(f"https://example.invalid/{ARCHIVE_NAME}", _refused_url()), encoding="utf-8"
    )
    # No back-off between the attempts: every one is refused at once.
    monkeypatch.setattr("reframe.tools.fetch._sleep", lambda _seconds, _cancel: None)
    fetch = api.reframe.tools.fetch
    monkeypatch.setattr(
        api.reframe.tools, "fetch", lambda *, build: fetch(build=build, manifest=manifest)
    )
    response = await api.client.post("/api/system/tools/fetch", json={"build": "default"})
    assert response.status_code == 202
    task = (await api.client.get(f"/api/tasks/{response.json()['task_id']}")).json()
    while task["state"] not in ("done", "failed", "cancelled"):
        await api.reframe.tasks.wait(task["id"])
        task = (await api.client.get(f"/api/tasks/{task['id']}")).json()
    assert task["state"] == "failed"
    assert task["error_code"] == "tools.fetch_offline"


FetchFn = Callable[[TaskContext], Any]


def _fake_fetch(monkeypatch: pytest.MonkeyPatch, work: FetchFn | None = None) -> list[str]:
    """``ToolsService.fetch`` starts ``work`` as the task (default: nothing); the builds it was
    asked for."""
    asked: list[str] = []

    async def nothing(_ctx: TaskContext) -> None:
        return None

    def fetch(self: ToolsService, *, build: str = "default", **_: Any) -> TaskInfo:
        asked.append(build)
        return self._tasks.start("tools_fetch", work or nothing)

    monkeypatch.setattr(ToolsService, "fetch", fetch)
    return asked


async def test_ffmpeg_build_downloads_that_build_when_no_ffmpeg_is_found_and_says_so(
    make_api: ApiFactory,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _no_tools_found(monkeypatch, tmp_path)
    asked = _fake_fetch(monkeypatch)
    caplog.set_level(logging.INFO, logger="reframe_server.autofetch")
    async with make_api(ffmpeg_build="compat") as api:
        await api.app.state.autofetch.wait()
        problems = (await api.client.get("/api/system")).json()["problems"]
    assert asked == ["compat"]
    assert [p for p in problems if p["code"].startswith("tools.")] == []
    [line] = [
        r.getMessage() for r in caplog.records if r.getMessage().startswith("REFRAME_FFMPEG_BUILD")
    ]
    assert "the download of the FFmpeg build 'compat' starts" in line


async def test_a_start_without_ffmpeg_warns_that_reframe_cannot_encode_and_names_the_ways_out(
    make_api: ApiFactory,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _no_tools_found(monkeypatch, tmp_path)
    asked = _fake_fetch(monkeypatch)
    async with make_api() as api:
        await api.app.state.autofetch.wait()
    assert asked == []
    [warning] = [
        r for r in caplog.records if r.getMessage().startswith("Reframe cannot encode yet")
    ]
    assert warning.levelno == logging.WARNING
    text = warning.getMessage()
    for way_out in ("first-run screen", "REFRAME_FFMPEG_BUILD=default", "set REFRAME_FFMPEG"):
        assert way_out in text
    # The tools' reasons end with a full stop; joined, they must not stack punctuation.
    assert ".;" not in text
    assert ".)" not in text


async def test_a_start_with_ffmpeg_does_not_warn(
    api: Api, caplog: pytest.LogCaptureFixture
) -> None:
    await api.app.state.autofetch.wait()
    assert not [r for r in caplog.records if r.name == "reframe_server.autofetch"]


async def test_a_start_with_an_outdated_downloaded_build_warns(
    make_api: ApiFactory, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    platform = host_platform()
    if platform is None:
        pytest.skip("no build is pinned for this computer")
    install_dir = install_dir_for(tmp_path / "data", platform, platform)
    install_dir.mkdir(parents=True)
    marker = {"build": "default", "version": "n8.0-old"}
    (install_dir / MARKER_NAME).write_text(json.dumps(marker), encoding="utf-8")
    async with make_api() as api:
        await api.app.state.autofetch.wait()
    [warning] = [r for r in caplog.records if "is not the one this release pins" in r.getMessage()]
    assert warning.levelno == logging.WARNING
    assert "'default' (version n8.0-old)" in warning.getMessage()


@pytest.mark.parametrize(
    ("name", "level", "shown"),
    [
        ("reframe.tools.fetch", logging.INFO, True),
        ("reframe_server.autofetch", logging.INFO, True),
        ("reframe.queue", logging.INFO, False),
        ("reframe.queue", logging.WARNING, True),
        ("httpx", logging.DEBUG, False),
    ],
)
def test_the_console_shows_the_download_lines_and_every_warning(
    name: str, level: int, shown: bool
) -> None:
    record = logging.LogRecord(name, level, __file__, 1, "x", None, None)
    assert ConsoleFilter().filter(record) is shown
    config = _log_config()
    assert config["root"]["handlers"] == ["console"]
    assert config["handlers"]["console"]["stream"] == "ext://sys.stderr"
    assert config["loggers"]["reframe.tools.fetch"]["level"] == "INFO"


async def test_ffmpeg_build_downloads_nothing_when_ffmpeg_is_found(
    make_api: ApiFactory, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    asked = _fake_fetch(monkeypatch)
    caplog.set_level(logging.INFO, logger="reframe_server.autofetch")
    async with make_api(ffmpeg_build="default") as api:
        await api.app.state.autofetch.wait()
        problems = (await api.client.get("/api/system")).json()["problems"]
    assert asked == []
    assert problems == []
    assert _autofetch_lines(caplog) == [
        "REFRAME_FFMPEG_BUILD=default: FFmpeg is found, so nothing is downloaded"
    ]


@POSIX_ONLY
async def test_ffmpeg_build_downloads_when_the_ffmpeg_on_path_does_not_work(
    make_api: ApiFactory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _broken_on_path(monkeypatch, tmp_path)
    asked = _fake_fetch(monkeypatch)
    async with make_api(ffmpeg_build="compat") as api:
        await api.app.state.autofetch.wait()
        tools = (await api.client.get("/api/system")).json()["tools"]
    assert (tools["ffmpeg"]["origin"], tools["ffmpeg"]["status"]) == ("path", "broken")
    assert asked == ["compat"]


@pytest.mark.parametrize("where", ["env", "settings"])
async def test_ffmpeg_build_never_replaces_an_override_and_says_why(
    make_api: ApiFactory,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    where: str,
) -> None:
    _no_tools_found(monkeypatch, tmp_path)
    missing = tmp_path / "gone" / "ffmpeg"
    if where == "env":
        monkeypatch.setenv("REFRAME_FFMPEG", str(missing))
    else:
        settings = tmp_path / "config" / "settings.json"
        document = json.loads(settings.read_text(encoding="utf-8"))
        document["tools"] = {"ffmpeg": str(missing)}
        settings.write_text(json.dumps(document), encoding="utf-8")
    asked = _fake_fetch(monkeypatch)
    async with make_api(ffmpeg_build="default") as api:
        await api.app.state.autofetch.wait()
        body = (await api.client.get("/api/system")).json()
    assert body["tools"]["ffmpeg"]["origin"] == where
    assert asked == []
    named = "REFRAME_FFMPEG" if where == "env" else "Settings → Tools"
    [problem] = [p for p in body["problems"] if p["code"] == "tools.fetch_skipped"]
    assert named in problem["message"]
    lines = _autofetch_lines(caplog)
    [skipped] = [line for line in lines if line.startswith("REFRAME_FFMPEG_BUILD")]
    assert named in skipped
    assert "never replaces" in skipped
    [cannot] = [line for line in lines if line.startswith("Reframe cannot encode yet")]
    assert "REFRAME_FFMPEG_BUILD" not in cannot


async def test_ffmpeg_build_downloads_nothing_in_a_server_that_does_not_own_the_data_folder(
    make_api: ApiFactory,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _no_tools_found(monkeypatch, tmp_path)
    asked = _fake_fetch(monkeypatch)
    lock = StoreLock(tmp_path / "data" / LOCK_FILE)
    assert lock.acquire().owned
    try:
        async with make_api(ffmpeg_build="default") as api:
            await api.app.state.autofetch.wait()
            body = (await api.client.get("/api/system")).json()
    finally:
        lock.release()
    assert asked == []
    [problem] = [p for p in body["problems"] if p["code"] == "tools.fetch_skipped"]
    assert "another Reframe process" in problem["message"]
    lines = _autofetch_lines(caplog)
    [skipped] = [line for line in lines if line.startswith("REFRAME_FFMPEG_BUILD")]
    assert "another Reframe process" in skipped


async def test_ffmpeg_build_with_a_wrong_name_is_a_problem_of_the_system_info(
    make_api: ApiFactory,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _no_tools_found(monkeypatch, tmp_path)
    asked = _fake_fetch(monkeypatch)
    async with make_api(ffmpeg_build="nightly") as api:
        await api.app.state.autofetch.wait()
        body = (await api.client.get("/api/system")).json()
    assert asked == []
    [problem] = [p for p in body["problems"] if p["code"] == "tools.build_unknown"]
    assert "'nightly'" in problem["message"]
    assert "default" in problem["detail"]
    assert body["tools"]["ffmpeg"]["status"] == "missing"
    lines = _autofetch_lines(caplog)
    [line] = [line for line in lines if line.startswith("REFRAME_FFMPEG_BUILD")]
    assert line == (
        "REFRAME_FFMPEG_BUILD=nightly names no offered FFmpeg build (the offered builds: "
        "default, compat), so nothing is downloaded"
    )


async def test_a_failed_start_up_download_is_a_problem_and_the_server_runs_on(
    make_api: ApiFactory,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _no_tools_found(monkeypatch, tmp_path)

    async def fail(_ctx: TaskContext) -> None:
        raise TaskFailed("the download failed after 4 attempt(s)")

    _fake_fetch(monkeypatch, fail)
    async with make_api(ffmpeg_build="default") as api:
        await api.app.state.autofetch.wait()
        response = await api.client.get("/api/system")
    assert response.status_code == 200
    [problem] = [p for p in response.json()["problems"] if p["code"] == "tools.fetch_failed"]
    assert "'default'" in problem["message"]
    assert problem["detail"] == "the download failed after 4 attempt(s)"
    # The download's own error line has the reason; this one only says what it means.
    [line] = [line for line in _autofetch_lines(caplog) if "failed" in line]
    assert "4 attempt(s)" not in line
