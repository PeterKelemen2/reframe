"""Regression tests for ``reframe tools fetch``: cancels, slow servers, links, stale folders."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from reframe import cli
from reframe.cli import EXIT_INTERRUPTED
from reframe.models import TaskState, ToolInfo, ToolSet, ToolStatus
from reframe.probe import mediainfo
from reframe.tasks import TaskManager
from reframe.tools import ENV_VARS
from reframe.tools import fetch as fetch_module
from reframe.tools.fetch import FetchError, host_platform, installed_build, start_fetch
from reframe.tools.runner import CancelToken

from .fetch_server import (
    LINUX_ROOT,
    Archive,
    LocalServer,
    fake_archive,
    foreign_platform,
    local_server,
    tar_dir,
    tar_file,
    tar_link,
    tar_xz,
    write_manifest,
)

POSIX_ONLY = pytest.mark.skipif(
    sys.platform == "win32" or host_platform() != "linux-x64",
    reason="the fake Linux build runs only on a linux-x64 host",
)


@pytest.fixture
def server() -> Iterator[LocalServer]:
    yield from local_server()


def _toolset() -> ToolSet:
    def info(name: str) -> ToolInfo:
        return ToolInfo(name=name, status=ToolStatus.MISSING)  # type: ignore[arg-type]

    return ToolSet(
        ffmpeg=info("ffmpeg"),
        ffprobe=info("ffprobe"),
        mkvpropedit=info("mkvpropedit"),
        mediainfo=info("mediainfo"),
    )


def _ext(platform: str) -> str:
    return "zip" if platform == "windows-x64" else "tar.xz"


def _leftovers(data_dir: Path) -> list[str]:
    tools = data_dir / "tools"
    return sorted(p.name for p in tools.glob(".fetch-*")) if tools.exists() else []


@POSIX_ONLY
@pytest.mark.anyio
@pytest.mark.parametrize("when", ["during discovery", "during the swap"])
async def test_r5_5_a_cancel_after_the_swap_finishes_and_says_so(
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
            loop.call_soon_threadsafe(tasks.cancel, task_id[0], "interrupted")

        monkeypatch.setattr(fetch_module, "_swap_into_place", swap_then_cancel)

    data_dir = tmp_path / "data"
    info = start_fetch(tasks, data_dir=data_dir, rescan=rescan, manifest=manifest)
    task_id.append(info.id)
    if when == "during discovery":
        await asyncio.wait_for(in_rescan.wait(), 60)
        tasks.cancel(info.id, "interrupted")  # what Ctrl+C in `reframe tools fetch` does
    final = await asyncio.wait_for(tasks.wait(info.id), 60)
    marker = installed_build(data_dir / "tools" / "ffmpeg")
    assert final.state is TaskState.CANCELLED
    assert marker is not None
    assert rescans == ["done"]
    assert final.message is not None
    assert final.message.startswith("Installed FFmpeg")
    assert _leftovers(data_dir) == []


@pytest.fixture
def cli_fetch_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for var in ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    for name in ("config", "data", "cache"):
        monkeypatch.setenv(f"REFRAME_{name.upper()}_DIR", str(tmp_path / name))
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.setattr(mediainfo, "mediainfo_available", lambda: False)
    return tmp_path / "data"


@POSIX_ONLY
@pytest.mark.anyio
async def test_r5_5_the_cli_says_what_was_installed_after_an_interrupt(
    cli_fetch_env: Path,
    server: LocalServer,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data = fake_archive("linux-x64", tmp_path / "work")
    server.add("/a.tar.xz", data)
    monkeypatch.setattr(
        fetch_module,
        "DEFAULT_MANIFEST",
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
    install = cli_fetch_env / "tools" / "ffmpeg"
    assert installed_build(install) is not None
    assert "Nothing was installed." not in err
    assert f"was installed into {install} before the interrupt." in err


@pytest.mark.anyio
async def test_r5_5_an_interrupt_before_the_swap_still_installs_nothing(
    cli_fetch_env: Path,
    server: LocalServer,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    other = foreign_platform()
    ext = _ext(other)
    data = fake_archive(other, tmp_path / "work") + b"\0" * (2 << 20)
    route = server.add(f"/a.{ext}", data, delay=0.05)
    monkeypatch.setattr(
        fetch_module,
        "DEFAULT_MANIFEST",
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
    assert "Nothing was installed." in capsys.readouterr().err


@pytest.mark.anyio
async def test_a_cancel_stops_a_slow_download_at_once(tmp_path: Path, server: LocalServer) -> None:
    other = foreign_platform()
    url = f"/slow.{_ext(other)}"
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
    tasks.cancel(info.id, "interrupted")
    final = await asyncio.wait_for(tasks.wait(info.id), 60)
    elapsed = time.monotonic() - started
    assert final.state is TaskState.CANCELLED
    assert elapsed < 2.5, elapsed
    assert _leftovers(data_dir) == []


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


@pytest.mark.anyio
async def test_a_killed_fetchs_work_folder_is_removed_by_the_next_fetch(
    tmp_path: Path, server: LocalServer
) -> None:
    """A killed fetch leaves its work folder. A fresh one stays: another fetch may be running."""
    other = foreign_platform()
    url = f"/a.{_ext(other)}"
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
    assert _leftovers(data_dir) == [".fetch-running"]
