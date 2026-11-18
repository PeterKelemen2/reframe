"""``reframe tools fetch``: download a pinned FFmpeg build of the manifest (or take its archive
file), check its size and SHA-256, and install it as the bundled build in
``<data dir>/tools/ffmpeg``, where tool discovery finds it.

The work runs as the task ``tools_fetch`` (see :func:`start_fetch`, :func:`start_install_file`)
and logs its start, progress and result on this module's logger. Nothing is extracted before
the size and SHA-256 match. A failure leaves nothing half-installed, and an installed build stays
as it was. A folder with files but no marker at the install path is never replaced.

The marker ``.fetch-tools.json`` has the format of ``scripts/fetch-tools.py``, so each recognises
the other's install. The manifest is validated as ``scripts/fetch-tools.py`` validates it, except
that a URL may also be a ``file:`` URL or an ``http:`` URL on the loopback address (tests).

A build for another platform goes to ``<data dir>/tools/ffmpeg-<platform>``: tool discovery never
looks there, so it cannot replace the build this computer uses.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import functools
import hashlib
import http.client
import json
import logging
import lzma
import os
import platform as platform_module
import posixpath
import re
import shutil
import socket
import ssl
import stat
import sys
import tarfile
import tempfile
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from reframe import __version__
from reframe.mediatask import TaskFailed
from reframe.models.tasks import TaskInfo
from reframe.models.tools import (
    InstalledToolBuild,
    ToolBuildOffer,
    ToolBuilds,
    ToolFetchResult,
    ToolSet,
)
from reframe.tasks import TaskContext, TaskManager
from reframe.tools.runner import CancelToken, run
from reframe.tools.versions import MIN_FFMPEG

__all__ = [
    "DEFAULT_MANIFEST",
    "FETCH_OFFLINE",
    "LIBVA_FOLDER",
    "LIBVA_SONAMES",
    "MARKER_NAME",
    "PLATFORMS",
    "Build",
    "FetchError",
    "PlatformBuild",
    "add_libva",
    "choose_build",
    "host_platform",
    "install_dir_for",
    "installed_build",
    "load_manifest",
    "member_path",
    "offered_builds",
    "packaged_libva",
    "parse_manifest",
    "restore_previous_build",
    "start_fetch",
    "start_install_file",
]

log = logging.getLogger(__name__)

#: The pinned builds, shipped with the package (a copy of ``tools/ffmpeg.toml``).
DEFAULT_MANIFEST = Path(__file__).with_name("ffmpeg.toml")
SCHEMA_VERSION = 1
PLATFORMS = ("linux-x64", "linux-arm64", "windows-x64")
FORMATS = ("tar.xz", "zip")
_TAR_MODES: dict[str, Literal["r:xz", "r:bz2"]] = {"tar.xz": "r:xz", "tar.bz2": "r:bz2"}
#: The marker that ``scripts/fetch-tools.py`` writes too (same name and format).
MARKER_NAME = ".fetch-tools.json"
USER_AGENT = f"reframe/{__version__} (tools fetch)"
#: Hosts that may serve a manifest URL over plain ``http`` (tests with a local server).
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

#: Download attempts for an error in the middle of the transfer, and for HTTP 429 / 5xx.
ATTEMPTS = 4
#: Attempts for a refused or timed-out connection: the server is most likely not there.
CONNECT_ATTEMPTS = 2
#: Socket timeout of the download (seconds without data).
SOCKET_TIMEOUT = 20.0
#: Seconds the ``-version`` check of each binary may take.
VERSION_TIMEOUT = 60.0
#: Seconds a cancelled task waits for its worker thread to stop and clean up.
STOP_WAIT = SOCKET_TIMEOUT + 10.0
CHUNK = 1 << 20
#: Seconds without a write after which a ``.fetch-*`` work folder is a killed fetch's.
STALE_WORK_AGE = 6 * 3600
#: Links followed in a row inside an archive before the chain counts as a loop.
MAX_LINK_DEPTH = 40
#: ``TaskInfo.error_code`` of a download that cannot reach the server.
FETCH_OFFLINE = "tools.fetch_offline"
#: What to do instead, appended to the message of :data:`FETCH_OFFLINE`.
OFFLINE_ALTERNATIVES = (
    "Without a connection, install the build from its archive file (downloaded on another "
    "computer), or use an FFmpeg that is already on this computer (its path in Settings > "
    "Tools, or REFRAME_FFMPEG and REFRAME_FFPROBE)."
)
#: The packaged libva of the Linux app: a folder of this name in a bundled tool root.
LIBVA_FOLDER = "libva"
#: The libva libraries that the BtbN Linux build loads at run time.
LIBVA_SONAMES = ("libva.so.2", "libva-drm.so.2")
#: Transfer progress is logged at every this many percent.
LOG_PROGRESS_STEP = 10

#: Progress ranges of the steps (percent of the task).
_DOWNLOAD = (0.0, 85.0)
_EXTRACT = 90.0
_CHECK = 97.0

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RELEASE_VERSION_RE = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_LIBVA_FILE_RE = re.compile(r"^libva(?:-drm)?\.so\.2(?:\.\d+)*$")
#: Socket errors of a computer without a network (the Windows codes too).
_OFFLINE_ERRNOS = frozenset(
    code
    for name in (
        "ENETUNREACH",
        "ENETDOWN",
        "EHOSTUNREACH",
        "EHOSTDOWN",
        "WSAENETUNREACH",
        "WSAENETDOWN",
        "WSAEHOSTUNREACH",
        "WSAEHOSTDOWN",
    )
    if (code := getattr(errno, name, None)) is not None
)


class FetchError(Exception):
    """An expected failure: a bad manifest, a download error, a checksum mismatch, an unsafe
    or broken archive, a build that does not run. The task ends ``failed`` with the text and
    ``code`` as its ``error_code``."""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PlatformBuild:
    """One downloadable archive of a build (``[builds.<name>.platforms.<platform>]``)."""

    platform: str
    url: str
    sha256: str
    size: int
    format: str
    root: str
    """The archive's top folder; its contents become the install folder."""
    bin_dir: str
    ffmpeg: str
    """Relative to the root: ``bin/ffmpeg`` (``bin/ffmpeg.exe``)."""
    ffprobe: str

    @property
    def file_name(self) -> str:
        return posixpath.basename(urllib.parse.urlsplit(self.url).path)


@dataclass(frozen=True, slots=True)
class Build:
    """One pinned FFmpeg build (``[builds.<name>]``)."""

    name: str
    version: str
    """What ``ffmpeg -version`` prints after ``ffmpeg version``."""
    release_version: str
    license: str
    source_commit: str
    platforms: Mapping[str, PlatformBuild]
    source_repository: str = ""
    build_scripts_repository: str = ""
    build_scripts_commit: str = ""
    offered: bool = False
    """The user may choose it (the first-run screen, Settings → Tools)."""
    label: str = ""
    summary: str = ""


def _get_str(table: Mapping[str, object], key: str, where: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise FetchError(f"{where}.{key}: expected a non-empty string, got {value!r}")
    return value


def _get_table(table: Mapping[str, object], key: str, where: str) -> Mapping[str, object]:
    value = table.get(key)
    if not isinstance(value, dict) or not value:
        raise FetchError(f"{where}.{key}: expected a non-empty table")
    return value


def _get_rel_path(table: Mapping[str, object], key: str, where: str) -> str:
    value = _get_str(table, key, where)
    if value.startswith("/") or "\\" in value or _DRIVE_RE.match(value):
        raise FetchError(f"{where}.{key}: expected a relative POSIX path, got {value!r}")
    if any(part in ("", ".", "..") for part in value.split("/")):
        raise FetchError(f"{where}.{key}: path must not contain '', '.' or '..': {value!r}")
    return value


def _check_url(url: str, where: str) -> None:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https" and parts.hostname:
        return
    if parts.scheme == "file":
        return
    if parts.scheme == "http" and (parts.hostname or "") in LOOPBACK_HOSTS:
        return
    raise FetchError(f"{where}.url: expected an https:// URL, got {url!r}")


def _parse_platform(name: str, table: Mapping[str, object], where: str) -> PlatformBuild:
    if name not in PLATFORMS:
        raise FetchError(f"{where}: unknown platform {name!r} (expected one of {PLATFORMS})")
    url = _get_str(table, "url", where)
    _check_url(url, where)
    sha256 = _get_str(table, "sha256", where)
    if not _SHA256_RE.match(sha256):
        raise FetchError(f"{where}.sha256: expected 64 lowercase hex digits, got {sha256!r}")
    size = table.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise FetchError(f"{where}.size: expected a positive integer, got {size!r}")
    fmt = _get_str(table, "format", where)
    if fmt not in FORMATS:
        raise FetchError(f"{where}.format: expected one of {FORMATS}, got {fmt!r}")
    if not urllib.parse.urlsplit(url).path.endswith("." + fmt):
        raise FetchError(f"{where}.url: does not end with .{fmt}: {url!r}")
    root = _get_rel_path(table, "root", where)
    if "/" in root:
        raise FetchError(f"{where}.root: expected one folder name, got {root!r}")
    bin_dir = _get_rel_path(table, "bin_dir", where)
    tools: dict[str, str] = {}
    for tool in ("ffmpeg", "ffprobe"):
        path = _get_rel_path(table, tool, where)
        if posixpath.dirname(path) != bin_dir:
            raise FetchError(f"{where}.{tool}: {path!r} is not in bin_dir {bin_dir!r}")
        tools[tool] = path
    return PlatformBuild(
        platform=name,
        url=url,
        sha256=sha256,
        size=size,
        format=fmt,
        root=root,
        bin_dir=bin_dir,
        ffmpeg=tools["ffmpeg"],
        ffprobe=tools["ffprobe"],
    )


def _parse_build(name: str, table: Mapping[str, object]) -> Build:
    where = f"builds.{name}"
    version = _get_str(table, "version", where)
    if any(ch.isspace() for ch in version):
        raise FetchError(f"{where}.version: must not contain spaces: {version!r}")
    release_version = _get_str(table, "release_version", where)
    match = _RELEASE_VERSION_RE.match(release_version)
    if match is None:
        raise FetchError(f"{where}.release_version: expected X.Y[.Z], got {release_version!r}")
    if (int(match[1]), int(match[2])) < MIN_FFMPEG:
        minimum = ".".join(map(str, MIN_FFMPEG))
        raise FetchError(f"{where}.release_version: {release_version} is below {minimum}")
    for key in ("license", "source_repository", "source_commit", "release_tag"):
        _get_str(table, key, where)
    platforms: dict[str, PlatformBuild] = {}
    for platform_name, platform_table in _get_table(table, "platforms", where).items():
        if not isinstance(platform_table, dict):
            raise FetchError(f"{where}.platforms.{platform_name}: expected a table")
        platforms[platform_name] = _parse_platform(
            platform_name, platform_table, f"{where}.platforms.{platform_name}"
        )
    offered = table.get("offered", False)
    if not isinstance(offered, bool):
        raise FetchError(f"{where}.offered: expected true or false")
    label = _get_str(table, "label", where) if offered else str(table.get("label", ""))
    summary = _get_str(table, "summary", where) if offered else str(table.get("summary", ""))
    return Build(
        name=name,
        version=version,
        release_version=release_version,
        license=_get_str(table, "license", where),
        source_commit=_get_str(table, "source_commit", where),
        platforms=platforms,
        source_repository=_get_str(table, "source_repository", where),
        build_scripts_repository=str(table.get("build_scripts_repository", "")),
        build_scripts_commit=str(table.get("build_scripts_commit", "")),
        offered=offered,
        label=label,
        summary=summary,
    )


def parse_manifest(data: Mapping[str, object]) -> dict[str, Build]:
    """Validate the parsed TOML of a manifest; the builds by name. :raises FetchError:"""
    schema_version = data.get("schema_version")
    if schema_version != SCHEMA_VERSION:
        raise FetchError(f"schema_version: expected {SCHEMA_VERSION}, got {schema_version!r}")
    builds: dict[str, Build] = {}
    for name, table in _get_table(data, "builds", "manifest").items():
        if not isinstance(table, dict):
            raise FetchError(f"builds.{name}: expected a table")
        builds[name] = _parse_build(name, table)
    if "default" not in builds:
        raise FetchError("builds.default: missing (the build that ships)")
    return builds


def load_manifest(path: Path | None = None) -> dict[str, Build]:
    """The builds of the manifest ``path`` (default: :data:`DEFAULT_MANIFEST`).

    :raises FetchError: the file cannot be read, is not TOML, or has a bad field.
    """
    path = DEFAULT_MANIFEST if path is None else Path(path)
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except OSError as e:
        raise FetchError(f"cannot read the manifest {path}: {e.strerror or e}") from e
    except tomllib.TOMLDecodeError as e:
        raise FetchError(f"the manifest {path} is not valid TOML: {e}") from e
    try:
        return parse_manifest(data)
    except FetchError as e:
        raise FetchError(f"{path}: {e}") from e


def host_platform(sys_platform: str | None = None, machine: str | None = None) -> str | None:
    """The manifest platform of this computer, or ``None`` when no build is pinned for it."""
    sys_platform = sys.platform if sys_platform is None else sys_platform
    machine = (platform_module.machine() if machine is None else machine).lower()
    if machine in ("x86_64", "amd64"):
        if sys_platform.startswith("linux"):
            return "linux-x64"
        if sys_platform == "win32":
            return "windows-x64"
    if machine in ("aarch64", "arm64") and sys_platform.startswith("linux"):
        return "linux-arm64"
    return None


def install_dir_for(data_dir: Path, target: str, host: str | None) -> Path:
    """``<data dir>/tools/ffmpeg`` for this computer's platform, else
    ``<data dir>/tools/ffmpeg-<platform>`` (where discovery never looks)."""
    tools = Path(data_dir) / "tools"
    return tools / "ffmpeg" if target == host else tools / f"ffmpeg-{target}"


def installed_build(install_dir: Path) -> dict[str, Any] | None:
    """The marker of the build installed in ``install_dir``, without checking its files;
    ``None`` when there is none."""
    try:
        data = json.loads((Path(install_dir) / MARKER_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


#: ``progress(done_bytes)``, called from the worker thread.
_Progress = Callable[[int], None]


def _check_cancel(cancel: CancelToken) -> None:
    if cancel.cancelled:
        raise _Stopped


class _Stopped(Exception):
    """The worker thread saw the cancel token (the task is being cancelled)."""


def download(
    url: str,
    dest: Path,
    *,
    size: int,
    cancel: CancelToken,
    progress: _Progress | None = None,
    attempts: int = ATTEMPTS,
    timeout: float = SOCKET_TIMEOUT,
) -> None:
    """Download ``url`` to ``dest`` (worker thread). Errors in the middle of the transfer and
    HTTP 429 / 5xx are retried with back-off, a refused or timed-out connection once, and no
    name resolution, an unreachable network and a TLS failure never. A response longer than
    ``size`` stops at once (a wrong or hostile server cannot fill the disk) and is not retried.
    A server that cannot be reached at all is a :class:`FetchError` with the code
    :data:`FETCH_OFFLINE`."""
    for attempt in range(1, attempts + 1):
        error: Exception
        connected = False
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                connected = True
                with dest.open("wb") as f:
                    written = 0
                    # read1 returns what has arrived, so a slow server does not keep a cancel
                    # waiting for a whole block.
                    while chunk := response.read1(CHUNK):
                        _check_cancel(cancel)
                        written += len(chunk)
                        if written > size:
                            raise FetchError(
                                f"{url}: the download is larger than the pinned size of "
                                f"{size} bytes"
                            )
                        f.write(chunk)
                        if progress is not None:
                            progress(written)
                    _check_cancel(cancel)
            return
        except (FetchError, _Stopped):
            dest.unlink(missing_ok=True)
            raise
        except urllib.error.HTTPError as e:
            limit = attempts if e.code == 429 or e.code >= 500 else 1
            error = e
            e.close()  # an HTTPError holds the response body open
        except ValueError as e:  # a URL that urllib cannot open
            limit = 1
            error = e
        except (OSError, http.client.HTTPException) as e:  # URLError is an OSError
            limit = attempts if connected else _connect_attempts(e, attempts)
            error = e
        dest.unlink(missing_ok=True)
        if attempt >= limit:
            why = _offline_reason(error)
            if why is not None:
                host = urllib.parse.urlsplit(url).hostname or url
                raise FetchError(
                    f"cannot reach the download server {host} ({why}; {attempt} attempt(s))",
                    code=FETCH_OFFLINE,
                )
            raise FetchError(f"the download failed after {attempt} attempt(s): {url}: {error}")
        _sleep(2.0**attempt, cancel)


def _connect_attempts(error: BaseException, attempts: int) -> int:
    """The attempts of a download whose connection failed with ``error``: another try cannot
    help without name resolution, without a route or with a failed TLS handshake."""
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    if isinstance(reason, (ssl.SSLError, socket.gaierror)) or (
        isinstance(reason, OSError) and reason.errno in _OFFLINE_ERRNOS
    ):
        return 1
    if isinstance(reason, (ConnectionRefusedError, TimeoutError)):
        return min(attempts, CONNECT_ATTEMPTS)
    return attempts


def _offline_reason(error: BaseException) -> str | None:
    """The reason text when ``error`` says that the server cannot be reached (no network or
    name resolution, a refused or timed-out connection); ``None`` for any other error."""
    if isinstance(error, urllib.error.HTTPError):
        return None
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    if not isinstance(reason, OSError):
        return None
    if isinstance(reason, (socket.gaierror, ConnectionRefusedError, TimeoutError)) or (
        reason.errno in _OFFLINE_ERRNOS
    ):
        return reason.strerror or str(reason) or type(reason).__name__
    return None


def _sleep(seconds: float, cancel: CancelToken) -> None:
    """A sleep in the worker thread that ends early (``_Stopped``) at a cancel."""
    deadline = time.monotonic() + seconds
    while (left := deadline - time.monotonic()) > 0:
        _check_cancel(cancel)
        time.sleep(min(left, 0.05))
    _check_cancel(cancel)


def sha256_file(path: Path, cancel: CancelToken | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            if cancel is not None:
                _check_cancel(cancel)
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path: Path, sha256: str, size: int, cancel: CancelToken | None = None) -> None:
    """:raises FetchError: unless ``path`` has exactly the pinned size and SHA-256."""
    actual_size = path.stat().st_size
    if actual_size != size:
        raise FetchError(f"{path.name}: the size is {actual_size} bytes, expected {size}")
    actual = sha256_file(path, cancel)
    if actual != sha256:
        raise FetchError(f"{path.name}: the SHA-256 is {actual}, expected {sha256}")


def archive_size(path: Path) -> int:
    """The size of the archive file ``path``. :raises FetchError: it does not exist, is not a
    file or cannot be read."""
    try:
        info = path.stat()
    except FileNotFoundError:
        raise FetchError(f"{path}: the file does not exist") from None
    except OSError as e:
        raise FetchError(f"{path}: cannot read it: {e.strerror or e}") from None
    if not stat.S_ISREG(info.st_mode):
        raise FetchError(f"{path} is not a file")
    return info.st_size


def copy_checked(
    source: Path,
    dest: Path,
    *,
    sha256: str,
    size: int,
    cancel: CancelToken,
    progress: _Progress | None = None,
) -> None:
    """Copy ``source`` to ``dest`` (worker thread); what was copied must have exactly the pinned
    size and SHA-256 (a file that changes meanwhile cannot slip through). :raises FetchError:"""
    digest = hashlib.sha256()
    written = 0
    try:
        with source.open("rb") as src, dest.open("wb") as dst:
            while chunk := src.read(CHUNK):
                _check_cancel(cancel)
                written += len(chunk)
                if written > size:
                    raise FetchError(
                        f"{source.name}: the file is larger than the pinned size of {size} bytes"
                    )
                digest.update(chunk)
                dst.write(chunk)
                if progress is not None:
                    progress(written)
        if written != size:
            raise FetchError(f"{source.name}: the size is {written} bytes, expected {size}")
        actual = digest.hexdigest()
        if actual != sha256:
            raise FetchError(f"{source.name}: the SHA-256 is {actual}, expected {sha256}")
    except BaseException:
        dest.unlink(missing_ok=True)
        raise


def member_path(name: str, root: str | None) -> PurePosixPath:
    """The safe relative path of an archive member. Every member must be inside the folder
    ``root`` (``None``: an archive without a top folder); absolute paths, drive letters,
    backslashes, NUL, ``..`` and ``:`` (NTFS streams) are refused. :raises FetchError:"""
    if not name or name.startswith("/") or "\\" in name or "\x00" in name or _DRIVE_RE.match(name):
        raise FetchError(f"unsafe archive member name: {name!r}")
    parts = [part for part in name.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." or ":" in part for part in parts):
        raise FetchError(f"unsafe archive member name: {name!r}")
    if root is not None and parts[0] != root:
        raise FetchError(f"archive member {name!r} is outside the folder {root!r}")
    return PurePosixPath(*parts)


def _check_link_target(member: PurePosixPath, link: str, root: str) -> None:
    """A link's text must be relative; where it points is checked by :func:`_check_links`."""
    if not link or link.startswith("/") or "\\" in link or "\x00" in link or _DRIVE_RE.match(link):
        raise FetchError(f"the link {member} -> {link!r} is absolute")


def _check_links(paths: list[PurePosixPath], links: Mapping[PurePosixPath, str], root: str) -> None:
    """Every link resolves inside ``root``, following the archive's other links as the file
    system does. A path that leaves ``root`` on the way is refused even when it comes back by
    the folder's name, because the folder is renamed when it is installed. A chain of more than
    :data:`MAX_LINK_DEPTH` links (a loop), and a member inside a linked folder (it would be
    written where the link points), are refused too. :raises FetchError:"""
    by_text = {member.as_posix(): text for member, text in links.items()}
    for path in paths:
        for parent in path.parents:
            if parent in links:
                raise FetchError(f"the archive member {path} is inside the link {parent}")

    def resolve(parent: list[str], text: str, depth: int) -> list[str] | None:
        if depth > MAX_LINK_DEPTH:
            return None
        parts = list(parent)
        for name in text.split("/"):
            if name in ("", "."):
                continue
            if name == "..":
                parts.pop()
                if not parts:  # above the root folder
                    return None
                continue
            parts.append(name)
            target = by_text.get("/".join(parts))
            if target is not None:
                resolved = resolve(parts[:-1], target, depth + 1)
                if resolved is None:
                    return None
                parts = resolved
                if not parts:
                    return None
        return parts

    for member, text in links.items():
        resolved = resolve(list(member.parent.parts), text, 0)
        if not resolved or resolved[0] != root:
            raise FetchError(f"the link {member} -> {text!r} points outside {root!r} (or loops)")


def _extract_tar(
    archive: Path, mode: Literal["r:xz", "r:bz2"], root: str, dest: Path, cancel: CancelToken
) -> None:
    with tarfile.open(archive, mode) as tf:
        members = tf.getmembers()
        links: dict[PurePosixPath, str] = {}
        paths = []
        for m in members:
            path = member_path(m.name, root)
            paths.append(path)
            if m.issym():
                _check_link_target(path, m.linkname, root)
                links[path] = m.linkname
            elif m.islnk():
                member_path(m.linkname, root)
            elif not (m.isfile() or m.isdir()):
                raise FetchError(f"unsupported archive member type: {m.name!r}")
        _check_links(paths, links, root)
        # The "data" filter repeats the checks above and drops setuid, setgid and group and
        # other write bits; it keeps the executable bits.
        for m in members:
            _check_cancel(cancel)
            tf.extract(m, dest, filter="data")


def _extract_zip(archive: Path, root: str | None, dest: Path, cancel: CancelToken) -> None:
    with zipfile.ZipFile(archive) as zf:
        infos = zf.infolist()
        paths = []
        for info in infos:
            path = member_path(info.filename, root)
            if stat.S_ISLNK(info.external_attr >> 16):
                raise FetchError(f"symbolic link in the zip archive: {info.filename!r}")
            paths.append(path)
        for info, path in zip(infos, paths, strict=True):
            _check_cancel(cancel)
            target = dest.joinpath(*path.parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst, CHUNK)
            mode = (info.external_attr >> 16) & 0o777
            if os.name == "posix" and mode & 0o111:
                target.chmod(0o755)


def safe_extract(
    archive: Path, fmt: str, root: str | None, dest: Path, cancel: CancelToken
) -> None:
    """Extract ``archive`` (``tar.xz``, ``tar.bz2`` or ``zip``) into ``dest``; every member is
    checked before a file is written. Only a zip archive may lack a top folder (``root``
    ``None``): a tar's links are checked against it. :raises FetchError: an unsafe member, or
    an archive that cannot be read."""
    try:
        if fmt in _TAR_MODES:
            if root is None:
                raise FetchError(f"{archive.name}: a {fmt} archive needs a top folder")
            _extract_tar(archive, _TAR_MODES[fmt], root, dest, cancel)
        elif fmt == "zip":
            _extract_zip(archive, root, dest, cancel)
        else:  # pragma: no cover - the manifest parser allows only these
            raise FetchError(f"unsupported archive format {fmt!r}")
    except (tarfile.TarError, zipfile.BadZipFile, EOFError, lzma.LZMAError) as e:
        raise FetchError(f"{archive.name} is not a valid {fmt} archive: {e}") from e


def tree_digest(directory: Path, cancel: CancelToken | None = None) -> dict[str, str]:
    """Each file (SHA-256) and symbolic link (its target) under ``directory`` by relative
    POSIX path, without the marker (``scripts/fetch-tools.py`` computes the same)."""
    result: dict[str, str] = {}
    for path in sorted(directory.rglob("*")):
        rel = path.relative_to(directory).as_posix()
        if rel == MARKER_NAME:
            continue
        if path.is_symlink():
            result[rel] = "link:" + os.readlink(path)
        elif path.is_file():
            result[rel] = "sha256:" + sha256_file(path, cancel)
    return result


def is_installed(
    install_dir: Path,
    pbuild: PlatformBuild,
    cancel: CancelToken | None = None,
    *,
    libva: Path | None = None,
) -> bool:
    """The archive ``pbuild`` is installed in ``install_dir``, every file still has the hash
    recorded at install time and, with ``libva``, its ``lib/`` has that packaged libva."""
    marker = installed_build(install_dir)
    if marker is None or marker.get("sha256") != pbuild.sha256:
        return False
    files = marker.get("files")
    if not isinstance(files, dict) or not files:
        return False
    if libva is not None and any(
        files.get(rel) != value for rel, value in libva_files(libva, cancel).items()
    ):
        return False
    return tree_digest(install_dir, cancel) == files


def packaged_libva(roots: Sequence[Path], data_dir: Path) -> Path | None:
    """The packaged libva folder: ``<root>/libva`` of the first of ``roots`` (the bundled tool
    roots) that has one, leaving out ``<data dir>/tools``; ``None`` when there is none."""
    own = Path(data_dir) / "tools"
    for root in roots:
        if Path(root) == own:
            continue
        folder = Path(root) / LIBVA_FOLDER
        if folder.is_dir():
            return folder
    return None


def _libva_layout(libva: Path) -> dict[str, str | None]:
    """The libva libraries of the folder ``libva`` by name: the target of a link to another of
    them, else ``None`` (copied as a file). :raises FetchError: a soname is missing, or links
    loop or leave the folder."""
    names = {entry.name: entry for entry in libva.iterdir() if _LIBVA_FILE_RE.match(entry.name)}
    layout: dict[str, str | None] = {}
    for name, entry in sorted(names.items()):
        _check_libva_links(libva, name)
        target = os.readlink(entry) if entry.is_symlink() else None
        if target is not None and target in names:
            layout[name] = target
        elif entry.is_file():
            layout[name] = None  # a file, or a link to another file of the folder: its content
    while dangling := [name for name, target in layout.items() if target and target not in layout]:
        for name in dangling:
            del layout[name]
    for soname in LIBVA_SONAMES:
        if soname not in layout:
            raise FetchError(f"the packaged libva in {libva} has no {soname}")
    return layout


def _check_libva_links(libva: Path, name: str) -> None:
    """:raises FetchError: the links from ``name`` loop or leave the folder ``libva``."""
    chain = [name]
    while (libva / chain[-1]).is_symlink():
        target = os.readlink(libva / chain[-1])
        if target in ("", ".", "..") or "/" in target or "\\" in target:
            raise FetchError(
                f"the packaged libva in {libva} is broken: the link {chain[-1]} -> {target!r} "
                "leaves the folder"
            )
        if target in chain:
            raise FetchError(
                f"the packaged libva in {libva} is broken: its links loop: "
                + " -> ".join([*chain, target])
            )
        chain.append(target)


def libva_files(libva: Path, cancel: CancelToken | None = None) -> dict[str, str]:
    """What :func:`add_libva` adds to a build, as :func:`tree_digest` records it."""
    return {
        f"lib/{name}": f"link:{target}"
        if target is not None
        else "sha256:" + sha256_file(libva / name, cancel)
        for name, target in _libva_layout(libva).items()
    }


def add_libva(root: Path, libva: Path) -> None:
    """Copy the libva libraries of the folder ``libva`` into ``root/lib``, each link as a link
    (the layout of the bundled Linux build). :raises FetchError: a soname is missing, or links
    loop or leave the folder (nothing is copied)."""
    layout = _libva_layout(libva)
    lib = root / "lib"
    lib.mkdir(exist_ok=True)
    for name, target in layout.items():
        dest = lib / name
        if dest.is_symlink() or dest.exists():
            dest.unlink()
        if target is None:
            shutil.copyfile(libva / name, dest)
        else:
            dest.symlink_to(target)


def check_replaceable(install_dir: Path) -> None:
    """:raises FetchError: ``install_dir`` is not a folder, or is a folder that is not empty
    and was not installed by ``reframe tools fetch`` / ``scripts/fetch-tools.py``."""
    if not install_dir.exists() and not install_dir.is_symlink():
        return
    if install_dir.is_symlink() or not install_dir.is_dir():
        raise FetchError(f"{install_dir} exists and is not a folder: move it away first")
    if (install_dir / MARKER_NAME).is_file() or not any(install_dir.iterdir()):
        return
    raise FetchError(
        f"{install_dir} holds files that reframe tools fetch did not install: it is never "
        "replaced. Move it away (or remove it) and fetch again"
    )


def _write_marker(folder: Path, build: Build, pbuild: PlatformBuild, cancel: CancelToken) -> None:
    marker = {
        "build": build.name,
        "version": build.version,
        "platform": pbuild.platform,
        "url": pbuild.url,
        "sha256": pbuild.sha256,
        "layout": "bundled",
        "files": tree_digest(folder, cancel),
    }
    (folder / MARKER_NAME).write_text(json.dumps(marker, indent=1), encoding="utf-8")


def _retry_on_permission(
    action: Callable[[], object],
    *,
    attempts: int = 5,
    sleep: Callable[[float], object] = time.sleep,
) -> None:
    """Retry ``action``: on Windows a virus scanner (or a running ffmpeg) can hold new files."""
    for attempt in range(1, attempts + 1):
        try:
            action()
            return
        except PermissionError:
            if attempt == attempts:
                raise
            sleep(0.5 * attempt)


def _swap_into_place(new: Path, install_dir: Path, aside: Path) -> None:
    """Move ``new`` to ``install_dir``; an old build is moved to ``aside`` first (removed with
    the work folder) and moved back if the new one cannot be moved, or by
    :func:`restore_previous_build` after a kill."""
    old = install_dir.exists() or install_dir.is_symlink()
    try:
        if old:
            _retry_on_permission(lambda: install_dir.rename(aside))
        try:
            _retry_on_permission(lambda: new.rename(install_dir))
        except OSError:
            if old:
                with contextlib.suppress(OSError):
                    aside.rename(install_dir)
            raise
    except OSError as e:
        raise FetchError(
            f"cannot replace {install_dir}: {e.strerror or e}. Close the programs that use "
            "it and fetch again"
        ) from e


def restore_previous_build(install_dir: Path, platform: str) -> Path | None:
    """Put back the build that a fetch killed between the two renames of its swap left in
    ``.fetch-*/previous``: only when ``install_dir`` is missing and that build's marker
    (for ``platform``) and files are intact. Never fails; returns the folder it came from."""
    if install_dir.exists() or install_dir.is_symlink():
        return None
    found: list[tuple[float, Path]] = []
    try:
        candidates = [work / "previous" for work in install_dir.parent.glob(".fetch-*")]
    except OSError:
        return None
    for previous in candidates:
        try:
            if previous.is_symlink() or not previous.is_dir():
                continue
            marker = installed_build(previous)
            files = marker.get("files") if marker is not None else None
            if marker is None or marker.get("platform") != platform or not files:
                continue
            if tree_digest(previous) == files:
                found.append(((previous / MARKER_NAME).stat().st_mtime, previous))
        except OSError:
            continue
    if not found:
        return None
    previous = max(found)[1]
    try:
        _retry_on_permission(functools.partial(previous.rename, install_dir))
    except OSError as e:
        log.warning("Cannot put back the FFmpeg build in %s: %s", previous, e.strerror or e)
        return None
    log.warning(
        "Put back the FFmpeg build that an interrupted install left in %s: %s",
        previous,
        install_dir,
    )
    return previous


@dataclass(slots=True)
class _Job:
    """One fetch: what to install, where, and how to report."""

    build: Build
    pbuild: PlatformBuild
    install_dir: Path
    native: bool
    ctx: TaskContext
    loop: asyncio.AbstractEventLoop
    source: Path | None = None
    """The archive file to install instead of the download."""
    libva: Path | None = None
    """The packaged libva folder whose libraries go into the build's ``lib/``."""
    #: The new build is in place (set by the worker thread right after the swap).
    swapped: bool = False
    #: The last transfer percentage logged.
    logged: int = 0

    def report(self, percent: float | None, message: str) -> None:
        """Progress from the worker thread (thread-safe)."""
        with contextlib.suppress(RuntimeError):  # the loop is closed: nobody listens
            self.loop.call_soon_threadsafe(self.ctx.progress, percent, message)

    def start_line(self) -> str:
        build, pbuild = self.build, self.pbuild
        links = _source_links(build)
        source = f"; source: {links[0]}" if links else ""
        origin = f"from the file {self.source}" if self.source else f"from {pbuild.url}"
        return (
            f"FFmpeg build {build.name!r} ({build.version}, {pbuild.platform}, "
            f"{_megabytes(pbuild.size)}): installing {origin} into {self.install_dir}. "
            f"Licence {build.license}{source}"
        )

    def _log_transfer(self, done: int) -> None:
        percent = int(100 * min(done / self.pbuild.size, 1.0))
        step = percent - percent % LOG_PROGRESS_STEP
        if step > self.logged:
            self.logged = step
            what = "downloaded" if self.source is None else "copied"
            log.info(
                "FFmpeg build %r: %s %d %% (%s of %s)",
                self.build.name,
                what,
                step,
                _megabytes(done),
                _megabytes(self.pbuild.size),
            )

    def prepare(self, work: Path) -> Path:
        """Worker thread: the archive (downloaded, or copied from the file) checked in ``work``,
        then extracted, with the packaged libva added. The extracted root folder."""
        pbuild, cancel = self.pbuild, self.ctx.cancel
        if self.source is None:
            archive = work / (pbuild.file_name or f"ffmpeg.{pbuild.format}")
            message = f"Downloading {archive.name}"
        else:
            (work / "archive").mkdir()
            archive = work / "archive" / self.source.name
            message = f"Checking {self.source.name}"
        self.report(0.0, message)
        start, end = _DOWNLOAD
        last = [-1]

        def progress(done: int) -> None:
            percent = start + (end - start) * min(done / pbuild.size, 1.0)
            if int(percent) != last[0]:
                last[0] = int(percent)
                self.report(percent, message)
            self._log_transfer(done)

        if self.source is None:
            download(pbuild.url, archive, size=pbuild.size, cancel=cancel, progress=progress)
            self.report(end, "Checking the size and SHA-256")
            verify_file(archive, pbuild.sha256, pbuild.size, cancel)
        else:
            copy_checked(
                self.source,
                archive,
                sha256=pbuild.sha256,
                size=pbuild.size,
                cancel=cancel,
                progress=progress,
            )
        self.report(_EXTRACT, f"Extracting {archive.name}")
        staging = work / "extract"
        staging.mkdir()
        safe_extract(archive, pbuild.format, pbuild.root, staging, cancel)
        archive.unlink()
        root = staging / pbuild.root
        for tool in (pbuild.ffmpeg, pbuild.ffprobe):
            if not (root / tool).is_file():
                raise FetchError(f"{tool} is not in the archive under {pbuild.root}/")
        if self.libva is not None:
            add_libva(root, self.libva)
            log.info(
                "FFmpeg build %r: added the packaged libva from %s", self.build.name, self.libva
            )
        return root

    def install(self, root: Path, work: Path) -> None:
        """Worker thread: the marker, then the swap."""
        self.report(_CHECK + 1, f"Installing into {self.install_dir}")
        _write_marker(root, self.build, self.pbuild, self.ctx.cancel)
        _check_cancel(self.ctx.cancel)
        _swap_into_place(root, self.install_dir, work / "previous")
        self.swapped = True


def _megabytes(size: int) -> str:
    return f"{size / 1e6:.1f} MB"


def _newest_write(folder: Path) -> float:
    """The newest modification time of ``folder`` and of everything in it (links not
    followed)."""
    newest = folder.lstat().st_mtime
    for dirpath, dirnames, filenames in os.walk(folder):
        for name in (*dirnames, *filenames):
            with contextlib.suppress(OSError):
                newest = max(newest, os.lstat(os.path.join(dirpath, name)).st_mtime)
    return newest


def remove_stale_work(tools_dir: Path, *, now: float | None = None) -> list[Path]:
    """Remove the ``.fetch-*`` work folders in ``tools_dir`` that a killed fetch left behind:
    those in which nothing was written for :data:`STALE_WORK_AGE` seconds (a running fetch
    writes into its folder all the time, so a fresh folder is never removed). Never fails;
    returns the folders removed."""
    now = time.time() if now is None else now
    removed: list[Path] = []
    try:
        entries = list(tools_dir.glob(".fetch-*"))
    except OSError:
        return removed
    for entry in entries:
        try:
            if entry.is_symlink() or not entry.is_dir():
                continue
            if now - _newest_write(entry) < STALE_WORK_AGE:
                continue
        except OSError:
            continue
        shutil.rmtree(entry, ignore_errors=True)
        removed.append(entry)
    return removed


async def _in_thread[T](cancel: CancelToken, fn: Callable[..., T], *args: object) -> T:
    """``fn(*args)`` in a worker thread that watches ``cancel``. When the task is cancelled,
    wait (at most :data:`STOP_WAIT`) for the thread to stop, so that the temporary files can be
    removed after it."""
    future = asyncio.ensure_future(asyncio.to_thread(fn, *args))
    # The exception of a thread that ends after a cancel is not wanted by anyone.
    future.add_done_callback(lambda f: f.cancelled() or f.exception())
    try:
        # Not shield(): it reports an exception of the thread after a cancel to the loop.
        await asyncio.wait({future})  # a cancel of this wait leaves the thread running
    except asyncio.CancelledError:
        cancel.cancel()
        await asyncio.wait({future}, timeout=STOP_WAIT)
        raise
    try:
        return future.result()
    except _Stopped:
        raise asyncio.CancelledError from None


async def _to_the_end[T](aw: Awaitable[T], cancel: CancelToken) -> tuple[T, bool]:
    """Await ``aw`` to its end even when the task is cancelled meanwhile (the step after the
    swap: the new build is in place). Returns its value and whether a cancel came; a cancel
    also sets ``cancel``, so that the task still ends ``cancelled``."""
    inner = asyncio.ensure_future(aw)
    cancelled = False
    while True:
        try:
            value = await asyncio.shield(inner)
        except asyncio.CancelledError:
            if inner.cancelled():
                raise  # ``aw`` itself was cancelled
            cancelled = True
            cancel.cancel()
            current = asyncio.current_task()
            if current is not None:
                current.uncancel()
            continue
        return value, cancelled


async def _check_version(executable: Path, tool: str, version: str, cancel: CancelToken) -> None:
    """``<tool> -version`` must print ``<tool> version <version>`` on its first line."""
    result = await run([str(executable), "-version"], timeout=VERSION_TIMEOUT, cancel=cancel)
    if result.cancelled or cancel.cancelled:
        raise asyncio.CancelledError
    lines = result.stdout.decode("utf-8", "replace").splitlines()
    first = lines[0].strip() if lines else ""
    if result.ok and first.split()[:3] == [tool, "version", version]:
        return
    if not result.started:
        why = f"it does not start ({result.error})"
    elif result.timed_out:
        why = f"it did not answer within {VERSION_TIMEOUT:g} s"
    elif not result.ok:
        stderr = " ".join(result.stderr.decode("utf-8", "replace").split())[:300]
        why = f"exit code {result.returncode}" + (f": {stderr}" if stderr else "")
    else:
        why = f"it prints {first[:200]!r}, expected '{tool} version {version}'"
    raise FetchError(f"the downloaded {tool} does not work on this computer: {why}")


def _describe(build: str | None, platform: str | None, source: Path | None) -> str:
    """The fetch in the log lines: ``FFmpeg download of build 'default'``."""
    if source is not None:
        return f"FFmpeg install from the file {source}"
    return f"FFmpeg download of build {build!r}" + (f" for {platform}" if platform else "")


async def _fetch(
    ctx: TaskContext,
    *,
    data_dir: Path,
    rescan: Callable[[], Awaitable[ToolSet]],
    build: str | None,
    platform: str | None,
    manifest: Path | None,
    source: Path | None = None,
    libva: Path | None = None,
) -> ToolFetchResult:
    what = _describe(build, platform, source)
    try:
        return await _fetch_steps(
            ctx,
            data_dir=data_dir,
            rescan=rescan,
            build=build,
            platform=platform,
            manifest=manifest,
            source=source,
            libva=libva,
        )
    except FetchError as e:
        message = str(e)
        if e.code == FETCH_OFFLINE:
            message = f"{message}. {OFFLINE_ALTERNATIVES}"
        log.error("%s failed: %s", what, message)
        raise TaskFailed(message, code=e.code) from None
    except OSError as e:  # the data folder cannot be written, the disk is full, …
        where = f" ({e.filename})" if e.filename else ""
        message = f"{e.strerror or e}{where}"
        log.error("%s failed: %s", what, message)
        raise TaskFailed(message) from None
    except asyncio.CancelledError:
        if not ctx.cancelled:
            raise
        log.info("%s was cancelled: nothing was installed", what)
        raise


def choose_build(
    builds: Mapping[str, Build], name: str | None, target: str, source: Path | None
) -> Build:
    """The build ``name``; for an archive file without a name, the offered build whose archive
    for ``target`` has the file's name. :raises FetchError:"""
    if name is not None or source is None:
        name = "default" if name is None else name
        chosen = builds.get(name)
        if chosen is None:
            raise FetchError(
                f"the manifest has no build {name!r} (it has {', '.join(sorted(builds))})"
            )
        return chosen
    offered = [b for b in builds.values() if b.offered and target in b.platforms]
    matches = [b for b in offered if b.platforms[target].file_name == source.name]
    if not matches:
        names = ", ".join(sorted({b.platforms[target].file_name for b in offered}))
        raise FetchError(
            f"{source.name} is not the file name of an offered build's archive for {target} "
            f"({names}): name the build it is"
        )
    if len({b.platforms[target].sha256 for b in matches}) > 1:
        names = ", ".join(b.name for b in matches)
        raise FetchError(f"{source.name} is the archive of several builds ({names}): name one")
    return matches[0]


async def _fetch_steps(
    ctx: TaskContext,
    *,
    data_dir: Path,
    rescan: Callable[[], Awaitable[ToolSet]],
    build: str | None,
    platform: str | None,
    manifest: Path | None,
    source: Path | None,
    libva: Path | None,
) -> ToolFetchResult:
    cancel = ctx.cancel
    ctx.progress(None, "Reading the manifest")
    builds = await asyncio.to_thread(load_manifest, manifest)
    host = host_platform()
    target = platform or host
    if target is None:
        raise FetchError(
            f"no FFmpeg build is pinned for this computer ({sys.platform}, "
            f"{platform_module.machine()}); the manifest has {', '.join(PLATFORMS)}"
        )
    size = None if source is None else await asyncio.to_thread(archive_size, source)
    chosen = choose_build(builds, build, target, source)
    pbuild = chosen.platforms.get(target)
    if pbuild is None:
        raise FetchError(f"the build {chosen.name!r} has no archive for {target}")
    install_dir = install_dir_for(data_dir, target, host)
    native = target == host
    if not (native and target.startswith("linux")):
        libva = None
    if libva is not None:
        await asyncio.to_thread(_libva_layout, libva)  # a broken one fails before the download
    job = _Job(
        chosen,
        pbuild,
        install_dir,
        native,
        ctx,
        asyncio.get_running_loop(),
        source=source,
        libva=libva,
    )
    log.info("%s", job.start_line())
    if source is not None and size != pbuild.size:
        # Refused before anything is copied or extracted.
        raise FetchError(f"{source.name}: the size is {size} bytes, expected {pbuild.size}")

    def result(downloaded: bool) -> ToolFetchResult:
        return ToolFetchResult(
            build=chosen.name,
            platform=target,
            version=chosen.version,
            install_dir=install_dir,
            ffmpeg=install_dir.joinpath(*pbuild.ffmpeg.split("/")),
            ffprobe=install_dir.joinpath(*pbuild.ffprobe.split("/")),
            downloaded=downloaded,
        )

    ctx.progress(None, f"Checking the build in {install_dir}")
    await asyncio.to_thread(restore_previous_build, install_dir, target)
    if await _in_thread(cancel, lambda: is_installed(install_dir, pbuild, cancel, libva=libva)):
        if source is not None:
            ctx.progress(None, f"Checking the SHA-256 of {source.name}")
            await _in_thread(cancel, verify_file, source, pbuild.sha256, pbuild.size, cancel)
        if native:
            ctx.progress(_CHECK + 2, "Running tool discovery")
            await rescan()
        log.info(
            "FFmpeg build %r (%s) is already installed in %s and every file is intact: "
            "nothing to do",
            chosen.name,
            chosen.version,
            install_dir,
        )
        return result(downloaded=False)
    check_replaceable(install_dir)
    install_dir.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(remove_stale_work, install_dir.parent)
    work = Path(tempfile.mkdtemp(prefix=".fetch-", dir=install_dir.parent))
    try:
        root = await _in_thread(cancel, job.prepare, work)
        if native:
            ctx.progress(_CHECK, "Checking ffmpeg -version and ffprobe -version")
            await _check_version(root / pbuild.ffmpeg, "ffmpeg", chosen.version, cancel)
            await _check_version(root / pbuild.ffprobe, "ffprobe", chosen.version, cancel)
        try:
            await _in_thread(cancel, job.install, root, work)
        except asyncio.CancelledError:
            if not job.swapped:
                raise
            # The cancel came after the swap: the new build is installed, so the steps after
            # it still run.
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                current.uncancel()
    finally:
        # Removing the work folder is never cut off by a cancel (it is quick, local).
        await _to_the_end(asyncio.to_thread(shutil.rmtree, work, True), cancel)
    if native:
        ctx.progress(_CHECK + 2, "Running tool discovery")
        await _to_the_end(rescan(), cancel)
    checks = "the size and SHA-256 of the archive" + (
        ", ffmpeg -version and ffprobe -version" if native else f" (not run: it is for {target})"
    )
    log.info(
        "Installed FFmpeg build %r (%s) into %s%s; checked: %s",
        chosen.name,
        chosen.version,
        install_dir,
        " before the cancel" if cancel.cancelled else "",
        checks,
    )
    if cancel.cancelled:
        # The task ends ``cancelled`` (the task manager sees the token), with this message.
        ctx.progress(
            100.0,
            f"Installed FFmpeg {chosen.version} into {install_dir} before the cancel",
        )
    return result(downloaded=True)


def start_fetch(
    tasks: TaskManager,
    *,
    data_dir: Path,
    rescan: Callable[[], Awaitable[ToolSet]],
    build: str = "default",
    platform: str | None = None,
    manifest: Path | None = None,
    libva: Path | None = None,
) -> TaskInfo:
    """Task ``tools_fetch``: the build ``build`` of ``manifest`` (default: the pinned manifest
    shipped with Reframe) for ``platform`` (``None``: this one), downloaded with progress,
    verified, installed into ``data_dir / "tools" / "ffmpeg"``; then ``rescan()`` (tool
    discovery). Result: :class:`~reframe.models.ToolFetchResult`. A download or checksum
    failure ends the task ``failed`` with the reason (``error_code`` :data:`FETCH_OFFLINE`
    when the server cannot be reached); nothing half-installed is left. ``libva``: a packaged
    libva folder, whose libraries a Linux build for this computer gets in its ``lib/``."""

    async def fn(ctx: TaskContext) -> ToolFetchResult:
        return await _fetch(
            ctx,
            data_dir=Path(data_dir),
            rescan=rescan,
            build=build,
            platform=platform,
            manifest=manifest,
            libva=libva,
        )

    label = f"FFmpeg build {build!r}" + (f" for {platform}" if platform else "")
    return tasks.start("tools_fetch", fn, message=f"Fetching the {label}")


def start_install_file(
    tasks: TaskManager,
    *,
    data_dir: Path,
    rescan: Callable[[], Awaitable[ToolSet]],
    archive: Path,
    build: str | None = None,
    manifest: Path | None = None,
    libva: Path | None = None,
) -> TaskInfo:
    """Task ``tools_fetch`` for an archive file of a build for this computer: checked like a
    download (size and SHA-256 against the manifest entry of ``build``; ``None``: the offered
    build whose archive has the file's name) before anything is extracted, then installed as
    :func:`start_fetch` installs a download."""

    async def fn(ctx: TaskContext) -> ToolFetchResult:
        return await _fetch(
            ctx,
            data_dir=Path(data_dir),
            rescan=rescan,
            build=build,
            platform=None,
            manifest=manifest,
            source=Path(archive),
            libva=libva,
        )

    name = Path(archive).name
    return tasks.start("tools_fetch", fn, message=f"Installing the FFmpeg archive {name}")


def offered_builds(
    data_dir: Path, *, manifest: Path | None = None, platform: str | None = None
) -> ToolBuilds:
    """The offered builds of ``manifest`` and the build installed in ``data_dir``. Reads two
    small files: call it from a worker thread in async code. :raises FetchError: a bad
    manifest."""
    builds = load_manifest(manifest)
    host = host_platform() if platform is None else platform
    offers = [
        ToolBuildOffer(
            name=build.name,
            label=build.label,
            summary=build.summary,
            version=build.version,
            release_version=build.release_version,
            license=build.license,
            source_links=_source_links(build),
            size=build.platforms[host].size
            if host is not None and host in build.platforms
            else None,
        )
        for build in builds.values()
        if build.offered
    ]
    installed: InstalledToolBuild | None = None
    if host is not None:
        marker = installed_build(install_dir_for(Path(data_dir), host, host))
        if marker is not None and isinstance(marker.get("build"), str):
            name, version = marker["build"], str(marker.get("version", ""))
            pinned = builds.get(name)
            outdated = pinned is not None and pinned.version != version
            installed = InstalledToolBuild(name=name, version=version, outdated=outdated)
    return ToolBuilds(builds=offers, installed=installed)


def _source_links(build: Build) -> list[str]:
    links = []
    if build.source_repository:
        links.append(f"{build.source_repository.rstrip('/')}/commit/{build.source_commit}")
    if build.build_scripts_repository and build.build_scripts_commit:
        scripts = build.build_scripts_repository.rstrip("/")
        links.append(f"{scripts}/tree/{build.build_scripts_commit}")
    return links
