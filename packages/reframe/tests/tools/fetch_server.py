"""Helpers of the ``reframe tools fetch`` tests: fake archives and manifests served by a local
HTTP server. Never the network."""

from __future__ import annotations

import hashlib
import io
import sys
import tarfile
import threading
import time
import zipfile
from collections.abc import Collection, Iterator, Mapping
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from reframe.tools.fetch import host_platform
from reframe_testing import fake_tools as ft

#: What the fake ffmpeg / ffprobe print after ``ffmpeg version``.
FAKE_VERSION = "n9.0.2-17-g2a571b6068-20260930"
LINUX_ROOT = "ffmpeg-test-linux64"
WINDOWS_ROOT = "ffmpeg-test-win64"
ROOTS = {"linux-x64": LINUX_ROOT, "windows-x64": WINDOWS_ROOT}
FORMATS = {"linux-x64": "tar.xz", "windows-x64": "zip"}
BLOCK = 64 * 1024

POSIX_ONLY = pytest.mark.skipif(
    sys.platform == "win32" or host_platform() != "linux-x64",
    reason="the fake Linux build runs only on a linux-x64 host",
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def archive_ext(platform: str) -> str:
    return "zip" if platform == "windows-x64" else "tar.xz"


def foreign_platform() -> str:
    """A manifest platform that is not this computer's."""
    return "windows-x64" if host_platform() == "linux-x64" else "linux-x64"


def tar_xz(members: list[tuple[tarfile.TarInfo, bytes | None]]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz") as tf:
        for info, data in members:
            if data is not None:
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
            else:
                tf.addfile(info)
    return buf.getvalue()


def tar_file(name: str, mode: int = 0o644) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.mode = mode
    return info


def tar_dir(name: str) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    info.mode = 0o755
    return info


def tar_link(name: str, target: str, *, hard: bool = False) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = tarfile.LNKTYPE if hard else tarfile.SYMTYPE
    info.linkname = target
    return info


def zip_bytes(files: Mapping[str, bytes], *, symlink: str | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
        if symlink is not None:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (0o120777 << 16) | 0
            zf.writestr(info, "../../outside")
    return buf.getvalue()


def fake_archive(platform: str, work: Path, *, version_ok: bool = True) -> bytes:
    """A small build for ``platform`` in the layout of the BtbN archives. ``version_ok=False``:
    the Linux ffmpeg prints another version."""
    if platform == "windows-x64":
        root = WINDOWS_ROOT
        return zip_bytes(
            {
                f"{root}/bin/ffmpeg.exe": b"MZ fake ffmpeg",
                f"{root}/bin/ffprobe.exe": b"MZ fake ffprobe",
                f"{root}/bin/avcodec-62.dll": b"MZ fake dll",
                f"{root}/LICENSE.txt": b"GPL",
            }
        )
    root = LINUX_ROOT
    scenario = None if version_ok else ft.Scenario([ft.Rule(actions=[ft.version("n8.0")])])
    tools = ft.make_fake_tools(work / "launchers", scenario, platform="linux")
    return tar_xz(
        [
            (tar_dir(root), None),
            (tar_dir(f"{root}/bin"), None),
            (tar_file(f"{root}/bin/ffmpeg", 0o755), tools.ffmpeg.read_bytes()),
            (tar_file(f"{root}/bin/ffprobe", 0o755), tools.ffprobe.read_bytes()),
            (tar_dir(f"{root}/lib"), None),
            (tar_file(f"{root}/lib/libavfake.so.62.1"), b"\x7fELF fake"),
            (tar_link(f"{root}/lib/libavfake.so.62", "libavfake.so.62.1"), None),
            (tar_file(f"{root}/LICENSE.txt"), b"GPL"),
        ]
    )


@dataclass(frozen=True)
class Archive:
    """One platform entry of a test manifest."""

    url: str
    data: bytes
    platform: str
    sha: str | None = None
    """``None``: the archive's real SHA-256."""
    size: int | None = None
    """``None``: the archive's real size."""

    @property
    def root(self) -> str:
        return ROOTS[self.platform]


def write_manifest(
    path: Path,
    archives: Mapping[str, list[Archive]],
    *,
    version: str = FAKE_VERSION,
    versions: Mapping[str, str] | None = None,
    offered: Collection[str] = (),
) -> Path:
    """A manifest with one build per key of ``archives`` (``default`` must be one); ``versions``
    by build name override ``version``; the builds in ``offered`` are offered."""
    lines = ["schema_version = 1", ""]
    for name, entries in archives.items():
        lines += [
            f"[builds.{name}]",
            f'version = "{(versions or {}).get(name, version)}"',
            'release_version = "9.0.2"',
            'release_tag = "test"',
            'license = "GPL-3.0-or-later"',
            'source_repository = "https://example.invalid/ffmpeg"',
            'source_commit = "0000000"',
        ]
        if name in offered:
            lines += [
                "offered = true",
                f'label = "Label of {name}"',
                f'summary = "Summary of {name}."',
            ]
        lines.append("")
        for entry in entries:
            exe = ".exe" if entry.platform == "windows-x64" else ""
            lines += [
                f"[builds.{name}.platforms.{entry.platform}]",
                f'url = "{entry.url}"',
                f'sha256 = "{entry.sha or sha256(entry.data)}"',
                f"size = {entry.size if entry.size is not None else len(entry.data)}",
                f'format = "{FORMATS[entry.platform]}"',
                f'root = "{entry.root}"',
                'bin_dir = "bin"',
                f'ffmpeg = "bin/ffmpeg{exe}"',
                f'ffprobe = "bin/ffprobe{exe}"',
                "",
            ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


@dataclass
class Route:
    data: bytes
    fail: list[int] = field(default_factory=list)
    """HTTP statuses for the first requests (one per request), then the data."""
    delay: float = 0.0
    """Seconds before each 64 KiB block."""
    extra: bytes = b""
    """Bytes sent after ``data`` (a response longer than the pinned size)."""
    requests: int = 0


class LocalServer:
    """``http.server`` on 127.0.0.1 (a free port) in a thread."""

    def __init__(self) -> None:
        self.routes: dict[str, Route] = {}
        routes = self.routes

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                route = routes.get(self.path)
                if route is None:
                    self.send_error(404)
                    return
                route.requests += 1
                if route.fail:
                    self.send_error(route.fail.pop(0))
                    return
                body = route.data + route.extra
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    for start in range(0, len(body), BLOCK):
                        if route.delay:
                            time.sleep(route.delay)
                        self.wfile.write(body[start : start + BLOCK])
                except (BrokenPipeError, ConnectionResetError):  # the client stopped
                    pass

            def log_message(self, format: str, *args: object) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )
        self._thread.start()

    def url(self, path: str) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host!s}:{port}{path}"

    def add(self, path: str, data: bytes, **kwargs: object) -> Route:
        route = Route(data, **kwargs)  # type: ignore[arg-type]
        self.routes[path] = route
        return route

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(10)


def local_server() -> Iterator[LocalServer]:
    """The body of a fixture: a server that is closed after the test."""
    server = LocalServer()
    try:
        yield server
    finally:
        server.close()
