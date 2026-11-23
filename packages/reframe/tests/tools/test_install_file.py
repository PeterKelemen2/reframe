"""Installing an FFmpeg archive file, the packaged libva of the Linux app, the offered builds
and the log lines of an install."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import pytest

from reframe import Reframe
from reframe.events import EventBus
from reframe.models import TaskInfo, TaskState, ToolInfo, ToolOrigin, ToolSet, ToolStatus
from reframe.models.settings import AppSettings
from reframe.service import ToolsService
from reframe.tasks import TaskManager
from reframe.tools import ENV_VARS
from reframe.tools import fetch as fetch_module
from reframe.tools.fetch import (
    MARKER_NAME,
    FetchError,
    add_libva,
    host_platform,
    install_dir_for,
    installed_build,
    offered_builds,
    packaged_libva,
    start_fetch,
    start_install_file,
)

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

#: The file name of the test build's archive (its URL ends with it).
NAME = "ffmpeg-test-linux64.tar.xz"
LIBVA_FILES = {
    "lib/libva.so.2": "link:libva.so.2.2400.0",
    "lib/libva.so.2.2400.0": "sha256:" + sha256(b"libva 2.24"),
    "lib/libva-drm.so.2": "link:libva-drm.so.2.2400.0",
    "lib/libva-drm.so.2.2400.0": "sha256:" + sha256(b"libva-drm 2.24"),
}


def _toolset() -> ToolSet:
    return ToolSet(
        ffmpeg=ToolInfo(name="ffmpeg", status=ToolStatus.MISSING),
        ffprobe=ToolInfo(name="ffprobe", status=ToolStatus.MISSING),
    )


class Runner:
    """Starts install tasks on one task manager and counts the ``rescan`` calls."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.tasks = TaskManager()
        self.rescans = 0

    async def rescan(self) -> ToolSet:
        self.rescans += 1
        return _toolset()

    async def wait(self, info: TaskInfo) -> tuple[TaskInfo, Any]:
        assert info.kind == "tools_fetch"
        final = await asyncio.wait_for(self.tasks.wait(info.id), 120)
        return final, self.tasks.value(info.id)

    async def file(self, archive: Path, manifest: Path, **kwargs: Any) -> tuple[TaskInfo, Any]:
        info = start_install_file(
            self.tasks,
            data_dir=self.data_dir,
            rescan=self.rescan,
            archive=archive,
            manifest=manifest,
            **kwargs,
        )
        return await self.wait(info)

    async def fetch(self, manifest: Path, **kwargs: Any) -> tuple[TaskInfo, Any]:
        info = start_fetch(
            self.tasks, data_dir=self.data_dir, rescan=self.rescan, manifest=manifest, **kwargs
        )
        return await self.wait(info)


@pytest.fixture
def runner(tmp_path: Path) -> Runner:
    return Runner(tmp_path / "data")


def leftovers(data_dir: Path) -> list[str]:
    tools = data_dir / "tools"
    return sorted(p.name for p in tools.glob(".fetch-*")) if tools.exists() else []


def host() -> str:
    found = host_platform()
    assert found is not None
    return found


def pinned_name() -> str:
    """The archive's file name for this platform in :func:`manifest_for`."""
    return NAME if host() == "linux-x64" else "w.zip"


def archive_file(tmp_path: Path, data: bytes, name: str = NAME) -> Path:
    folder = tmp_path / "downloads"
    folder.mkdir(exist_ok=True)
    path = folder / name
    path.write_bytes(data)
    return path


def manifest_for(tmp_path: Path, data: bytes, platform: str, **kwargs: Any) -> Path:
    """A manifest whose offered ``default`` build is ``data``, pinned under the name NAME."""
    url = f"https://downloads.example/{NAME if platform == 'linux-x64' else 'w.zip'}"
    return write_manifest(
        tmp_path / "m.toml",
        {"default": [Archive(url, data, platform)]},
        offered=("default",),
        **kwargs,
    )


def libva_folder(path: Path, *, links: bool = True) -> Path:
    """A packaged libva in the layout of the bundled Linux build: each library under its own
    name and linked from its soname (``links=False``: two plain files, as a bundler that
    follows links leaves them)."""
    path.mkdir(parents=True)
    for soname, data in (("libva.so.2", b"libva 2.24"), ("libva-drm.so.2", b"libva-drm 2.24")):
        if links:
            (path / f"{soname}.2400.0").write_bytes(data)
            (path / soname).symlink_to(f"{soname}.2400.0")
        else:
            (path / soname).write_bytes(data)
    (path / "COPYING").write_text("MIT")
    return path


@POSIX_ONLY
@pytest.mark.anyio
async def test_the_right_file_installs_and_discovery_finds_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    for var in ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    data = fake_archive("linux-x64", tmp_path / "work")
    # Copied in many small blocks: the log has every 10 % step, and no more.
    monkeypatch.setattr(fetch_module, "CHUNK", max(len(data) // 300, 1))
    archive = archive_file(tmp_path, data)
    manifest = manifest_for(tmp_path, data, "linux-x64")
    caplog.set_level(logging.INFO, logger="reframe.tools.fetch")
    async with await Reframe.create(
        tmp_path / "config", tmp_path / "data", cache_dir=tmp_path / "cache"
    ) as app:
        before = await app.tools.status()
        assert before.ffmpeg.status is ToolStatus.MISSING
        info = app.tools.install_file(archive, manifest=manifest)
        assert (info.kind, info.message) == ("tools_fetch", f"Installing the FFmpeg archive {NAME}")
        final = await asyncio.wait_for(app.tasks.wait(info.id), 120)
        assert final.state is TaskState.DONE, final.error
        result = app.tasks.value(info.id)
        tools = app.tools.current
    install = tmp_path / "data" / "tools" / "ffmpeg"
    assert (result.build, result.version, result.install_dir) == ("default", FAKE_VERSION, install)
    assert result.downloaded is True
    assert tools is not None
    for name in ("ffmpeg", "ffprobe"):
        found = tools.get(name)
        assert found.status is ToolStatus.FOUND, found.reason
        assert found.origin is ToolOrigin.BUNDLED
        assert found.path == install / "bin" / name
        assert found.version == FAKE_VERSION
    marker = installed_build(install)
    assert marker is not None
    assert (marker["build"], marker["sha256"]) == ("default", sha256(data))
    assert archive.read_bytes() == data  # the file itself is left as it was
    assert leftovers(tmp_path / "data") == []

    lines = [r.getMessage() for r in caplog.records if r.name == "reframe.tools.fetch"]
    assert all(r.levelno == logging.INFO for r in caplog.records if r.name == "reframe.tools.fetch")
    assert lines[0] == (
        f"FFmpeg build 'default' ({FAKE_VERSION}, linux-x64, {len(data) / 2**20:.1f} MiB): "
        f"installing from the file {archive} into {install}. Licence GPL-3.0-or-later; "
        "source: https://example.invalid/ffmpeg/commit/0000000"
    )
    percents = [int(m[1]) for line in lines if (m := re.search(r"copied (\d+) %", line))]
    assert percents == list(range(10, 101, 10))
    # The unit of the UI's size formatter.
    assert [line for line in lines if " % (" in line and not line.endswith(" MiB)")] == []
    assert lines[-1] == (
        f"Installed FFmpeg build 'default' ({FAKE_VERSION}) into {install}; checked: the size "
        "and SHA-256 of the archive, ffmpeg -version and ffprobe -version"
    )


@pytest.mark.anyio
async def test_a_wrong_sha256_is_refused_before_extraction(
    tmp_path: Path,
    runner: Runner,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    extracted: list[Path] = []
    monkeypatch.setattr(
        fetch_module, "safe_extract", lambda archive, *args: extracted.append(archive)
    )
    data = fake_archive(foreign_platform(), tmp_path / "work")  # never run
    manifest = manifest_for(tmp_path, data, host())
    wrong = bytes([data[0] ^ 1]) + data[1:]  # the same size
    archive = archive_file(tmp_path, wrong)
    caplog.set_level(logging.INFO, logger="reframe.tools.fetch")
    final, result = await runner.file(archive, manifest, build="default")
    assert final.state is TaskState.FAILED
    assert final.error == (
        f"{NAME} is not the archive of the FFmpeg build 'default' for {host()} "
        f"({pinned_name()}), or it is damaged: the SHA-256 is {sha256(wrong)}, "
        f"expected {sha256(data)}"
    )
    assert final.error_code is None
    assert result is None
    assert extracted == []
    assert not install_dir_for(runner.data_dir, host(), host()).exists()
    assert leftovers(runner.data_dir) == []
    assert runner.rescans == 0
    (error,) = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert error.getMessage() == (f"FFmpeg install from the file {archive} failed: {final.error}")


@pytest.mark.anyio
async def test_a_wrong_size_is_refused_before_anything_is_copied(
    tmp_path: Path, runner: Runner, monkeypatch: pytest.MonkeyPatch
) -> None:
    copies: list[Path] = []
    monkeypatch.setattr(fetch_module, "copy_checked", lambda source, *a, **k: copies.append(source))
    data = b"an archive"
    manifest = manifest_for(tmp_path, data, host())
    archive = archive_file(tmp_path, data + b"!")
    final, _ = await runner.file(archive, manifest, build="default")
    assert final.state is TaskState.FAILED
    assert final.error == (
        f"{NAME} is not the archive of the FFmpeg build 'default' for {host()} "
        f"({pinned_name()}), or it is damaged: the size is {len(data) + 1} bytes, "
        f"expected {len(data)}"
    )
    assert copies == []
    assert not (runner.data_dir / "tools").exists()


@pytest.mark.anyio
async def test_a_file_that_is_not_an_offered_builds_archive_needs_the_build(
    tmp_path: Path, runner: Runner
) -> None:
    data = b"an archive"
    manifest = manifest_for(tmp_path, data, host())
    archive = archive_file(tmp_path, data, name="ffmpeg (1).tar.xz")
    final, _ = await runner.file(archive, manifest)
    assert final.state is TaskState.FAILED
    pinned = pinned_name()
    assert final.error == (
        f"ffmpeg (1).tar.xz is not the file name of an offered build's archive for {host()} "
        f"({pinned}): name the build it is"
    )


@pytest.mark.anyio
async def test_a_missing_file_and_an_unknown_build(tmp_path: Path, runner: Runner) -> None:
    manifest = manifest_for(tmp_path, b"x", host())
    final, _ = await runner.file(tmp_path / "nope.tar.xz", manifest)
    assert final.error == f"{tmp_path / 'nope.tar.xz'}: the file does not exist"
    final, _ = await runner.file(tmp_path, manifest)
    assert final.error == f"{tmp_path} is not a file"
    final, _ = await runner.file(archive_file(tmp_path, b"x"), manifest, build="nightly")
    assert final.error == "the manifest has no build 'nightly' (it has default)"


@POSIX_ONLY
@pytest.mark.anyio
async def test_a_renamed_file_installs_with_its_build_and_an_installed_one_is_checked(
    tmp_path: Path, runner: Runner
) -> None:
    data = fake_archive("linux-x64", tmp_path / "work")
    manifest = manifest_for(tmp_path, data, "linux-x64")
    renamed = archive_file(tmp_path, data, name="ffmpeg (1).tar.xz")
    final, result = await runner.file(renamed, manifest, build="default")
    assert final.state is TaskState.DONE, final.error
    assert result.downloaded is True
    assert runner.rescans == 1

    # Installed and intact: nothing is extracted again, but the file is still checked.
    final, again = await runner.file(renamed, manifest, build="default")
    assert final.state is TaskState.DONE, final.error
    assert again.downloaded is False
    marker = installed_build(result.install_dir)
    broken = archive_file(tmp_path, bytes([data[0] ^ 1]) + data[1:], name="broken.tar.xz")
    final, _ = await runner.file(broken, manifest, build="default")
    assert final.state is TaskState.FAILED
    assert final.error is not None
    assert final.error.startswith(
        f"broken.tar.xz is not the archive of the FFmpeg build 'default' for linux-x64 ({NAME}), "
        "or it is damaged: the SHA-256 is"
    )
    assert installed_build(result.install_dir) == marker


def test_packaged_libva_is_the_first_app_root_with_one(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    roots = [tmp_path / "app" / "tools", tmp_path / "usr" / "tools", data_dir / "tools"]
    (data_dir / "tools" / "libva").mkdir(parents=True)
    assert packaged_libva(roots, data_dir) is None  # the data folder's own is not packaged
    (tmp_path / "usr" / "tools" / "libva").mkdir(parents=True)
    assert packaged_libva(roots, data_dir) == tmp_path / "usr" / "tools" / "libva"
    (tmp_path / "app" / "tools" / "libva").mkdir(parents=True)
    assert packaged_libva(roots, data_dir) == tmp_path / "app" / "tools" / "libva"


@POSIX_ONLY
def test_add_libva_keeps_the_links_of_the_bundled_layout(tmp_path: Path) -> None:
    libva = libva_folder(tmp_path / "libva")
    root = tmp_path / "build"
    (root / "lib").mkdir(parents=True)
    add_libva(root, libva)
    assert sorted(p.name for p in (root / "lib").iterdir()) == [
        "libva-drm.so.2",
        "libva-drm.so.2.2400.0",
        "libva.so.2",
        "libva.so.2.2400.0",
    ]
    assert os.readlink(root / "lib" / "libva.so.2") == "libva.so.2.2400.0"
    assert (root / "lib" / "libva-drm.so.2").read_bytes() == b"libva-drm 2.24"
    assert {
        rel: value for rel, value in fetch_module.tree_digest(root).items() if "libva" in rel
    } == LIBVA_FILES


@POSIX_ONLY
def test_add_libva_copies_plain_files(tmp_path: Path) -> None:
    libva = libva_folder(tmp_path / "libva", links=False)
    root = tmp_path / "build"
    root.mkdir()
    add_libva(root, libva)
    lib = root / "lib"
    assert sorted(p.name for p in lib.iterdir()) == ["libva-drm.so.2", "libva.so.2"]
    assert not any(p.is_symlink() for p in lib.iterdir())
    assert (lib / "libva-drm.so.2").read_bytes() == b"libva-drm 2.24"


def _relink(libva: Path, name: str, target: str | Path) -> None:
    (libva / name).unlink(missing_ok=True)
    (libva / name).symlink_to(target)


#: A packaged libva that is refused: its links (name, target; ``OUTSIDE``: a file next to the
#: folder) and the error.
OUTSIDE = "<outside>"
BROKEN_LIBVA: dict[str, tuple[list[tuple[str, str]], str]] = {
    "loop": (
        [("libva.so.2.2400.0", "libva.so.2")],
        r"its links loop: libva\.so\.2 -> libva\.so\.2\.2400\.0 -> libva\.so\.2",
    ),
    "self": (
        [("libva-drm.so.2", "libva-drm.so.2")],
        r"its links loop: libva-drm\.so\.2 -> libva-drm\.so\.2",
    ),
    "absolute": (
        [("libva-drm.so.2", OUTSIDE)],
        r"the link libva-drm\.so\.2 -> '/.*/elsewhere\.so' leaves the folder",
    ),
    "parent": (
        [("libva-drm.so.2", "../elsewhere.so")],
        r"the link libva-drm\.so\.2 -> '\.\./elsewhere\.so' leaves the folder",
    ),
    "through-another-link": (
        [("libva.so.2.2400", "../elsewhere.so"), ("libva.so.2", "libva.so.2.2400")],
        r"the link libva\.so\.2\.2400 -> '\.\./elsewhere\.so' leaves the folder",
    ),
}


@POSIX_ONLY
@pytest.mark.parametrize("case", sorted(BROKEN_LIBVA))
def test_a_packaged_libva_whose_links_loop_or_leave_the_folder_is_refused(
    tmp_path: Path, case: str
) -> None:
    libva = libva_folder(tmp_path / "libva")
    outside = tmp_path / "elsewhere.so"
    outside.write_bytes(b"libva-drm elsewhere")
    links, message = BROKEN_LIBVA[case]
    for name, target in links:
        _relink(libva, name, outside if target == OUTSIDE else target)
    root = tmp_path / "build"
    root.mkdir()
    with pytest.raises(FetchError, match=rf"^the packaged libva in {re.escape(str(libva))} is "
                       rf"broken: {message}"):  # fmt: skip
        add_libva(root, libva)
    assert list(root.iterdir()) == []


@POSIX_ONLY
@pytest.mark.anyio
async def test_a_broken_packaged_libva_fails_the_fetch_before_the_download(
    tmp_path: Path, server: LocalServer, runner: Runner
) -> None:
    data = fake_archive("linux-x64", tmp_path / "work")
    route = server.add(f"/{NAME}", data)
    manifest = write_manifest(
        tmp_path / "m.toml", {"default": [Archive(server.url(f"/{NAME}"), data, "linux-x64")]}
    )
    libva = libva_folder(tmp_path / "app" / "tools" / "libva")
    _relink(libva, "libva.so.2.2400.0", "libva.so.2")
    final, result = await runner.fetch(manifest, libva=libva)
    assert final.state is TaskState.FAILED
    assert final.error is not None
    assert final.error.startswith(f"the packaged libva in {libva} is broken: its links loop")
    assert result is None
    assert route.requests == 0
    assert not (runner.data_dir / "tools" / "ffmpeg").exists()
    assert leftovers(runner.data_dir) == []


@POSIX_ONLY
@pytest.mark.parametrize("broken", ["missing", "dangling"])
def test_a_packaged_libva_without_a_soname_is_refused(tmp_path: Path, broken: str) -> None:
    libva = libva_folder(tmp_path / "libva")
    (libva / "libva-drm.so.2.2400.0").unlink()
    if broken == "missing":
        (libva / "libva-drm.so.2").unlink()
    with pytest.raises(FetchError, match=r"the packaged libva in .* has no libva-drm\.so\.2"):
        add_libva(tmp_path / "build", libva)


@POSIX_ONLY
@pytest.mark.anyio
async def test_a_fetch_with_a_packaged_libva_puts_it_into_the_builds_lib(
    tmp_path: Path, server: LocalServer, runner: Runner
) -> None:
    data = fake_archive("linux-x64", tmp_path / "work")
    route = server.add(f"/{NAME}", data)
    manifest = write_manifest(
        tmp_path / "m.toml", {"default": [Archive(server.url(f"/{NAME}"), data, "linux-x64")]}
    )
    libva = libva_folder(tmp_path / "app" / "tools" / "libva")
    final, result = await runner.fetch(manifest, libva=libva)
    assert final.state is TaskState.DONE, final.error
    lib = result.install_dir / "lib"
    for soname in ("libva.so.2", "libva-drm.so.2"):
        assert (lib / soname).is_symlink()
        assert (lib / soname).resolve().is_file()
    marker = installed_build(result.install_dir)
    assert marker is not None
    assert LIBVA_FILES.items() <= marker["files"].items()
    assert (lib / "libavfake.so.62").is_symlink()  # the build's own files are still there

    final, again = await runner.fetch(manifest, libva=libva)
    assert again.downloaded is False
    assert route.requests == 1
    # Another packaged libva (an app update): the build is installed again with it.
    (libva / "libva.so.2.2400.0").write_bytes(b"libva 2.25")
    final, third = await runner.fetch(manifest, libva=libva)
    assert final.state is TaskState.DONE, final.error
    assert third.downloaded is True
    assert route.requests == 2
    assert (lib / "libva.so.2").read_bytes() == b"libva 2.25"


@pytest.mark.anyio
async def test_a_build_for_another_platform_gets_no_libva(
    tmp_path: Path, server: LocalServer, runner: Runner
) -> None:
    other = foreign_platform()
    data = fake_archive(other, tmp_path / "work")
    server.add(f"/a.{archive_ext(other)}", data)
    url = server.url(f"/a.{archive_ext(other)}")
    manifest = write_manifest(tmp_path / "m.toml", {"default": [Archive(url, data, other)]})
    libva = tmp_path / "libva"
    libva.mkdir()  # not even read: a folder without the libraries
    final, result = await runner.fetch(manifest, platform=other, libva=libva)
    assert final.state is TaskState.DONE, final.error
    assert not any("libva" in path.name for path in result.install_dir.rglob("*"))


@POSIX_ONLY
@pytest.mark.anyio
async def test_the_tools_service_installs_a_file_with_the_packaged_libva(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for var in ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    data_dir = tmp_path / "data"
    app_tools = tmp_path / "app" / "tools"
    libva_folder(app_tools / "libva")
    data = fake_archive("linux-x64", tmp_path / "work")
    archive = archive_file(tmp_path, data)
    manifest = manifest_for(tmp_path, data, "linux-x64")
    tasks = TaskManager()
    service = ToolsService(
        EventBus(),
        AppSettings,
        bundled_roots=[app_tools, data_dir / "tools"],
        tasks=tasks,
        data_dir=data_dir,
    )
    info = service.install_file(archive, manifest=manifest)
    final = await asyncio.wait_for(tasks.wait(info.id), 120)
    assert final.state is TaskState.DONE, final.error
    lib = data_dir / "tools" / "ffmpeg" / "lib"
    assert (lib / "libva.so.2").read_bytes() == b"libva 2.24"
    assert (lib / "libva-drm.so.2").read_bytes() == b"libva-drm 2.24"
    tools = service.current
    assert tools is not None
    assert tools.ffmpeg.path == data_dir / "tools" / "ffmpeg" / "bin" / "ffmpeg"
    await service.close()


def _marker(data_dir: Path, build: str, version: str) -> None:
    install = install_dir_for(data_dir, host(), host())
    install.mkdir(parents=True)
    marker = {"build": build, "version": version, "platform": host(), "files": {}}
    (install / MARKER_NAME).write_text(json.dumps(marker), encoding="utf-8")


def test_the_offered_builds_and_the_installed_one(tmp_path: Path) -> None:
    data = b"x" * 1000
    url = f"https://downloads.example/a.{archive_ext(host())}"
    other = f"https://downloads.example/a.{archive_ext(foreign_platform())}"
    manifest = write_manifest(
        tmp_path / "m.toml",
        {
            "default": [Archive(url, data, host())],
            "compat": [Archive(other, data, foreign_platform())],
            "override-test": [Archive(url, data, host())],
        },
        offered=("default", "compat"),
    )
    builds = offered_builds(tmp_path / "data", manifest=manifest)
    assert [b.name for b in builds.builds] == ["default", "compat"]
    default, compat = builds.builds
    assert (default.label, default.summary, default.version) == (
        "Label of default",
        "Summary of default.",
        FAKE_VERSION,
    )
    assert (default.license, default.size, compat.size) == ("GPL-3.0-or-later", 1000, None)
    assert default.source_links == ["https://example.invalid/ffmpeg/commit/0000000"]
    # What to download on another computer when this one has no connection.
    assert (default.archive_url, default.sha256) == (url, sha256(data))
    assert (compat.archive_url, compat.sha256) == (None, None)
    assert builds.installed is None


def test_an_installed_build_whose_pin_changed_is_outdated(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _marker(data_dir, "default", FAKE_VERSION)
    url = f"https://downloads.example/a.{archive_ext(host())}"
    archives = {"default": [Archive(url, b"x", host())]}
    same = write_manifest(tmp_path / "same.toml", archives, offered=("default",))
    installed = offered_builds(data_dir, manifest=same).installed
    assert installed is not None
    assert (installed.name, installed.version, installed.outdated) == (
        "default",
        FAKE_VERSION,
        False,
    )
    repinned = write_manifest(
        tmp_path / "new.toml", archives, version="n9.0.3-1-gabcdef-20261130", offered=("default",)
    )
    installed = offered_builds(data_dir, manifest=repinned).installed
    assert installed is not None
    assert (installed.name, installed.version, installed.outdated) == (
        "default",
        FAKE_VERSION,
        True,
    )


def _kill_during_the_swap(install: Path) -> Path:
    """The state that a fetch killed between the two renames of its swap leaves: the installed
    build in ``<work>/previous``, the new one in ``<work>/extract``, no install folder."""
    work = install.parent / ".fetch-killed"
    (work / "extract" / "new-build" / "bin").mkdir(parents=True)
    (work / "extract" / "new-build" / "bin" / "ffmpeg").write_bytes(b"the new build")
    install.rename(work / "previous")
    return work / "previous"


def _service(tmp_path: Path, data_dir: Path) -> ToolsService:
    return ToolsService(
        EventBus(),
        AppSettings,
        bundled_roots=[tmp_path / "app" / "tools", data_dir / "tools"],
        tasks=TaskManager(),
        data_dir=data_dir,
    )


@pytest.fixture
def no_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))


@POSIX_ONLY
@pytest.mark.anyio
@pytest.mark.usefixtures("no_tools")
async def test_the_build_that_a_killed_swap_left_aside_is_put_back_at_start(
    tmp_path: Path, runner: Runner, caplog: pytest.LogCaptureFixture
) -> None:
    data = fake_archive("linux-x64", tmp_path / "work")
    final, result = await runner.file(
        archive_file(tmp_path, data), manifest_for(tmp_path, data, "linux-x64")
    )
    assert final.state is TaskState.DONE, final.error
    install = result.install_dir
    marker = installed_build(install)
    previous = _kill_during_the_swap(install)
    caplog.set_level(logging.WARNING, logger="reframe.tools.fetch")
    caplog.clear()

    service = _service(tmp_path, runner.data_dir)
    service.start()
    tools = await service.status()
    await service.close()
    assert installed_build(install) == marker
    assert not previous.exists()
    assert tools.ffmpeg.status is ToolStatus.FOUND, tools.ffmpeg.reason
    assert tools.ffmpeg.path == install / "bin" / "ffmpeg"
    warnings = [r for r in caplog.records if r.name == "reframe.tools.fetch"]
    assert [(r.levelno, r.getMessage()) for r in warnings] == [
        (
            logging.WARNING,
            f"Put back the FFmpeg build that an interrupted install left in {previous}: {install}",
        )
    ]


@POSIX_ONLY
@pytest.mark.anyio
@pytest.mark.usefixtures("no_tools")
@pytest.mark.parametrize("damage", ["changed-file", "no-marker", "other-platform", "installed"])
async def test_a_build_left_aside_stays_there_unless_it_is_intact_and_missing(
    tmp_path: Path, runner: Runner, damage: str
) -> None:
    data = fake_archive("linux-x64", tmp_path / "work")
    final, result = await runner.file(
        archive_file(tmp_path, data), manifest_for(tmp_path, data, "linux-x64")
    )
    assert final.state is TaskState.DONE, final.error
    install = result.install_dir
    previous = _kill_during_the_swap(install)
    if damage == "changed-file":
        (previous / "LICENSE.txt").write_bytes(b"changed")
    elif damage == "no-marker":
        (previous / MARKER_NAME).unlink()
    elif damage == "other-platform":
        marker = json.loads((previous / MARKER_NAME).read_text())
        (previous / MARKER_NAME).write_text(json.dumps(marker | {"platform": "linux-arm64"}))
    else:
        install.mkdir()  # an empty folder at the install path: left as it is
    service = _service(tmp_path, runner.data_dir)
    tools = await service.status()
    await service.close()
    assert previous.is_dir()
    assert install.is_dir() is (damage == "installed")
    assert tools.ffmpeg.status is ToolStatus.MISSING


@pytest.mark.anyio
async def test_a_fetch_puts_the_build_left_aside_back_before_it_removes_old_work_folders(
    tmp_path: Path, server: LocalServer, runner: Runner
) -> None:
    """Even when the killed fetch's work folder is old enough to be removed."""
    other = foreign_platform()
    data = fake_archive(other, tmp_path / "work")
    route = server.add(f"/a.{archive_ext(other)}", data)
    url = server.url(f"/a.{archive_ext(other)}")
    manifest = write_manifest(tmp_path / "m.toml", {"default": [Archive(url, data, other)]})
    final, result = await runner.fetch(manifest, platform=other)
    assert final.state is TaskState.DONE, final.error
    install = result.install_dir
    marker = installed_build(install)
    previous = _kill_during_the_swap(install)
    old = time.time() - 7 * 3600
    for path in [previous.parent, *previous.parent.rglob("*")]:
        if os.utime in os.supports_follow_symlinks:
            os.utime(path, (old, old), follow_symlinks=False)
        elif not path.is_symlink():  # Windows cannot set a link's own time
            os.utime(path, (old, old))

    final, again = await runner.fetch(manifest, platform=other)
    assert final.state is TaskState.DONE, final.error
    assert again.downloaded is False
    assert route.requests == 1
    assert installed_build(install) == marker
    assert not previous.exists()
