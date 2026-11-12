"""``reframe tools fetch``: download the pinned FFmpeg build of the manifest, check its size and
SHA-256, and install it as the bundled build in ``<data dir>/tools/ffmpeg``, where tool
discovery finds it.

The work runs as the task ``tools_fetch`` (see :func:`start_fetch`). Nothing is extracted before
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
import hashlib
import http.client
import json
import lzma
import os
import platform as platform_module
import posixpath
import re
import shutil
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
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from reframe import __version__
from reframe.mediatask import TaskFailed
from reframe.models.tasks import TaskInfo
from reframe.models.tools import ToolFetchResult, ToolSet
from reframe.tasks import TaskContext, TaskManager
from reframe.tools.runner import CancelToken, run
from reframe.tools.versions import MIN_FFMPEG

__all__ = [
    "DEFAULT_MANIFEST",
    "MARKER_NAME",
    "PLATFORMS",
    "Build",
    "FetchError",
    "PlatformBuild",
    "host_platform",
    "install_dir_for",
    "installed_build",
    "load_manifest",
    "member_path",
    "parse_manifest",
    "start_fetch",
]

#: The pinned builds, shipped with the package (a copy of ``tools/ffmpeg.toml``).
DEFAULT_MANIFEST = Path(__file__).with_name("ffmpeg.toml")
SCHEMA_VERSION = 1
PLATFORMS = ("linux-x64", "windows-x64")
FORMATS = ("tar.xz", "zip")
_TAR_MODES: dict[str, Literal["r:xz", "r:bz2"]] = {"tar.xz": "r:xz", "tar.bz2": "r:bz2"}
#: The marker that ``scripts/fetch-tools.py`` writes too (same name and format).
MARKER_NAME = ".fetch-tools.json"
USER_AGENT = f"reframe/{__version__} (tools fetch)"
#: Hosts that may serve a manifest URL over plain ``http`` (tests with a local server).
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

#: Download attempts (network errors and HTTP 429 / 5xx are retried with back-off).
ATTEMPTS = 4
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

#: Progress ranges of the steps (percent of the task).
_DOWNLOAD = (0.0, 85.0)
_EXTRACT = 90.0
_CHECK = 97.0

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RELEASE_VERSION_RE = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


class FetchError(Exception):
    """An expected failure: a bad manifest, a download error, a checksum mismatch, an unsafe
    or broken archive, a build that does not run. The task ends ``failed`` with the text."""


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
    return Build(
        name=name,
        version=version,
        release_version=release_version,
        license=_get_str(table, "license", where),
        source_commit=_get_str(table, "source_commit", where),
        platforms=platforms,
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
    """Download ``url`` to ``dest`` (worker thread). Network errors and HTTP 429 / 5xx are
    retried with back-off; a response longer than ``size`` stops at once (a wrong or hostile
    server cannot fill the disk) and is not retried."""
    for attempt in range(1, attempts + 1):
        error: Exception
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=timeout) as response, dest.open("wb") as f:
                written = 0
                # read1 returns what has arrived, so a slow server does not keep a cancel
                # waiting for a whole block.
                while chunk := response.read1(CHUNK):
                    _check_cancel(cancel)
                    written += len(chunk)
                    if written > size:
                        raise FetchError(
                            f"{url}: the download is larger than the pinned size of {size} bytes"
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
            retryable = e.code == 429 or e.code >= 500
            error = e
            e.close()  # an HTTPError holds the response body open
        except (OSError, http.client.HTTPException, ValueError) as e:  # URLError is an OSError
            retryable = not isinstance(e, ValueError)
            error = e
        dest.unlink(missing_ok=True)
        if not retryable or attempt == attempts:
            raise FetchError(f"the download failed after {attempt} attempt(s): {url}: {error}")
        _sleep(2.0**attempt, cancel)


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
    install_dir: Path, pbuild: PlatformBuild, cancel: CancelToken | None = None
) -> bool:
    """The archive ``pbuild`` is installed in ``install_dir`` and every file still has the hash
    recorded at install time."""
    marker = installed_build(install_dir)
    if marker is None or marker.get("sha256") != pbuild.sha256:
        return False
    files = marker.get("files")
    if not isinstance(files, dict) or not files:
        return False
    return tree_digest(install_dir, cancel) == files


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
    the work folder) and moved back if the new one cannot be moved."""
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


@dataclass(slots=True)
class _Job:
    """One fetch: what to install, where, and how to report."""

    build: Build
    pbuild: PlatformBuild
    install_dir: Path
    native: bool
    ctx: TaskContext
    loop: asyncio.AbstractEventLoop
    #: The new build is in place (set by the worker thread right after the swap).
    swapped: bool = False

    def report(self, percent: float | None, message: str) -> None:
        """Progress from the worker thread (thread-safe)."""
        with contextlib.suppress(RuntimeError):  # the loop is closed: nobody listens
            self.loop.call_soon_threadsafe(self.ctx.progress, percent, message)

    def download_and_extract(self, work: Path) -> Path:
        """Worker thread: download into ``work``, verify, extract. The extracted root folder."""
        pbuild, cancel = self.pbuild, self.ctx.cancel
        archive = work / (pbuild.file_name or f"ffmpeg.{pbuild.format}")
        message = f"Downloading {archive.name}"
        self.report(0.0, message)
        start, end = _DOWNLOAD
        last = [-1]

        def progress(done: int) -> None:
            percent = start + (end - start) * min(done / pbuild.size, 1.0)
            if int(percent) != last[0]:
                last[0] = int(percent)
                self.report(percent, message)

        download(pbuild.url, archive, size=pbuild.size, cancel=cancel, progress=progress)
        self.report(end, "Checking the size and SHA-256")
        verify_file(archive, pbuild.sha256, pbuild.size, cancel)
        self.report(_EXTRACT, f"Extracting {archive.name}")
        staging = work / "extract"
        staging.mkdir()
        safe_extract(archive, pbuild.format, pbuild.root, staging, cancel)
        archive.unlink()
        root = staging / pbuild.root
        for tool in (pbuild.ffmpeg, pbuild.ffprobe):
            if not (root / tool).is_file():
                raise FetchError(f"{tool} is not in the archive under {pbuild.root}/")
        return root

    def install(self, root: Path, work: Path) -> None:
        """Worker thread: the marker, then the swap."""
        self.report(_CHECK + 1, f"Installing into {self.install_dir}")
        _write_marker(root, self.build, self.pbuild, self.ctx.cancel)
        _check_cancel(self.ctx.cancel)
        _swap_into_place(root, self.install_dir, work / "previous")
        self.swapped = True


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
        cancel.cancel("cancelled")
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
            cancel.cancel("cancelled")
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


async def _fetch(
    ctx: TaskContext,
    *,
    data_dir: Path,
    rescan: Callable[[], Awaitable[ToolSet]],
    build: str,
    platform: str | None,
    manifest: Path | None,
) -> ToolFetchResult:
    try:
        return await _fetch_steps(
            ctx,
            data_dir=data_dir,
            rescan=rescan,
            build=build,
            platform=platform,
            manifest=manifest,
        )
    except FetchError as e:
        raise TaskFailed(str(e)) from None
    except OSError as e:  # the data folder cannot be written, the disk is full, …
        where = f" ({e.filename})" if e.filename else ""
        raise TaskFailed(f"{e.strerror or e}{where}") from None


async def _fetch_steps(
    ctx: TaskContext,
    *,
    data_dir: Path,
    rescan: Callable[[], Awaitable[ToolSet]],
    build: str,
    platform: str | None,
    manifest: Path | None,
) -> ToolFetchResult:
    cancel = ctx.cancel
    ctx.progress(None, "Reading the manifest")
    builds = await asyncio.to_thread(load_manifest, manifest)
    chosen = builds.get(build)
    if chosen is None:
        raise FetchError(
            f"the manifest has no build {build!r} (it has {', '.join(sorted(builds))})"
        )
    host = host_platform()
    target = platform or host
    if target is None:
        raise FetchError(
            f"no FFmpeg build is pinned for this computer ({sys.platform}, "
            f"{platform_module.machine()}); the manifest has {', '.join(PLATFORMS)}"
        )
    pbuild = chosen.platforms.get(target)
    if pbuild is None:
        raise FetchError(f"the build {build!r} has no archive for {target}")
    install_dir = install_dir_for(data_dir, target, host)
    native = target == host
    job = _Job(chosen, pbuild, install_dir, native, ctx, asyncio.get_running_loop())

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
    if await _in_thread(cancel, is_installed, install_dir, pbuild, cancel):
        if native:
            ctx.progress(_CHECK + 2, "Running tool discovery")
            await rescan()
        return result(downloaded=False)
    check_replaceable(install_dir)
    install_dir.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(remove_stale_work, install_dir.parent)
    work = Path(tempfile.mkdtemp(prefix=".fetch-", dir=install_dir.parent))
    try:
        root = await _in_thread(cancel, job.download_and_extract, work)
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
) -> TaskInfo:
    """Task ``tools_fetch``: the build ``build`` of ``manifest`` (default: the pinned manifest
    shipped with Reframe) for ``platform`` (``None``: this one), downloaded with progress,
    verified, installed into ``data_dir / "tools" / "ffmpeg"``; then ``rescan()`` (tool
    discovery). Result: :class:`~reframe.models.ToolFetchResult`. A download or checksum
    failure ends the task ``failed`` with the reason; nothing half-installed is left."""

    async def fn(ctx: TaskContext) -> ToolFetchResult:
        return await _fetch(
            ctx,
            data_dir=Path(data_dir),
            rescan=rescan,
            build=build,
            platform=platform,
            manifest=manifest,
        )

    label = f"FFmpeg build {build!r}" + (f" for {platform}" if platform else "")
    return tasks.start("tools_fetch", fn, message=f"Fetching the {label}")
