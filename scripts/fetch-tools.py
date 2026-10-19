"""Download, verify and extract a pinned FFmpeg build from ``tools/ffmpeg.toml``.

The archive's size and SHA-256 are checked before anything is extracted. Only the absolute
``bin`` folder goes to stdout, so CI can append it to ``$GITHUB_PATH``. The script uses only
the standard library, so it runs before ``uv sync``.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import platform
import posixpath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = REPO_ROOT / "tools" / "ffmpeg.toml"
DEFAULT_DEST = REPO_ROOT / ".tools"

SCHEMA_VERSION = 1
PLATFORMS = ("linux-x64", "windows-x64")
FORMATS = ("tar.xz", "zip")
# Reframe needs at least FFmpeg 7.0. A pinned build below that is a manifest error.
MIN_FFMPEG_VERSION = (7, 0)
MARKER_NAME = ".fetch-tools.json"
USER_AGENT = "reframe-fetch-tools/1"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RELEASE_VERSION_RE = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


class FetchError(Exception):
    """An expected failure: bad manifest, download error, checksum mismatch, bad archive."""


class ManifestError(FetchError):
    """``tools/ffmpeg.toml`` is missing a field or has a field with a bad value."""


class ChecksumError(FetchError):
    """The downloaded file does not have the pinned size or SHA-256."""


class UnsafeArchiveError(FetchError):
    """The archive has a member that would land outside the destination folder."""


@dataclass(frozen=True)
class PlatformBuild:
    """One downloadable archive of a build."""

    platform: str
    url: str
    sha256: str
    size: int
    format: str
    root: str
    bin_dir: str
    ffmpeg: str
    ffprobe: str

    @property
    def file_name(self) -> str:
        return posixpath.basename(self.url)


@dataclass(frozen=True)
class Build:
    """One pinned FFmpeg build (``[builds.<name>]``)."""

    name: str
    version: str
    release_version: str
    license: str
    source_commit: str
    platforms: Mapping[str, PlatformBuild]


def _get_str(table: Mapping[str, object], key: str, where: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{where}.{key}: expected a non-empty string, got {value!r}")
    return value


def _get_table(table: Mapping[str, object], key: str, where: str) -> Mapping[str, object]:
    value = table.get(key)
    if not isinstance(value, dict) or not value:
        raise ManifestError(f"{where}.{key}: expected a non-empty table")
    return value


def _get_rel_path(table: Mapping[str, object], key: str, where: str) -> str:
    value = _get_str(table, key, where)
    if value.startswith("/") or "\\" in value or _DRIVE_RE.match(value):
        raise ManifestError(f"{where}.{key}: expected a relative POSIX path, got {value!r}")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ManifestError(f"{where}.{key}: path must not contain '', '.' or '..': {value!r}")
    return value


def _parse_platform(name: str, table: Mapping[str, object], where: str) -> PlatformBuild:
    if name not in PLATFORMS:
        raise ManifestError(f"{where}: unknown platform {name!r} (expected one of {PLATFORMS})")
    url = _get_str(table, "url", where)
    if not url.startswith("https://"):
        raise ManifestError(f"{where}.url: expected an https:// URL, got {url!r}")
    sha256 = _get_str(table, "sha256", where)
    if not _SHA256_RE.match(sha256):
        raise ManifestError(f"{where}.sha256: expected 64 lowercase hex digits, got {sha256!r}")
    size = table.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise ManifestError(f"{where}.size: expected a positive integer, got {size!r}")
    fmt = _get_str(table, "format", where)
    if fmt not in FORMATS:
        raise ManifestError(f"{where}.format: expected one of {FORMATS}, got {fmt!r}")
    if not url.endswith("." + fmt):
        raise ManifestError(f"{where}.url: does not end with .{fmt}: {url!r}")
    root = _get_rel_path(table, "root", where)
    if "/" in root:
        raise ManifestError(f"{where}.root: expected one folder name, got {root!r}")
    bin_dir = _get_rel_path(table, "bin_dir", where)
    tools: dict[str, str] = {}
    for tool in ("ffmpeg", "ffprobe"):
        path = _get_rel_path(table, tool, where)
        if posixpath.dirname(path) != bin_dir:
            raise ManifestError(f"{where}.{tool}: {path!r} is not in bin_dir {bin_dir!r}")
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
        raise ManifestError(f"{where}.version: must not contain spaces: {version!r}")
    release_version = _get_str(table, "release_version", where)
    match = _RELEASE_VERSION_RE.match(release_version)
    if match is None:
        raise ManifestError(f"{where}.release_version: expected X.Y[.Z], got {release_version!r}")
    if (int(match[1]), int(match[2])) < MIN_FFMPEG_VERSION:
        minimum = ".".join(map(str, MIN_FFMPEG_VERSION))
        raise ManifestError(f"{where}.release_version: {release_version} is below {minimum}")
    for key in ("license", "source_repository", "source_commit", "release_tag"):
        _get_str(table, key, where)
    platforms_table = _get_table(table, "platforms", where)
    platforms: dict[str, PlatformBuild] = {}
    for platform_name, platform_table in platforms_table.items():
        if not isinstance(platform_table, dict):
            raise ManifestError(f"{where}.platforms.{platform_name}: expected a table")
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
    """Validate the parsed TOML of ``tools/ffmpeg.toml`` and return the builds by name."""
    schema_version = data.get("schema_version")
    if schema_version != SCHEMA_VERSION:
        raise ManifestError(f"schema_version: expected {SCHEMA_VERSION}, got {schema_version!r}")
    builds_table = _get_table(data, "builds", "manifest")
    builds: dict[str, Build] = {}
    for name, table in builds_table.items():
        if not isinstance(table, dict):
            raise ManifestError(f"builds.{name}: expected a table")
        builds[name] = _parse_build(name, table)
    if "default" not in builds:
        raise ManifestError("builds.default: missing (the build that ships)")
    return builds


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, Build]:
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except OSError as e:
        raise ManifestError(f"cannot read {path}: {e}") from e
    except tomllib.TOMLDecodeError as e:
        raise ManifestError(f"{path}: invalid TOML: {e}") from e
    return parse_manifest(data)


def detect_platform(sys_platform: str | None = None, machine: str | None = None) -> str:
    """Map the host to a manifest platform key, or raise FetchError if there is no build."""
    sys_platform = sys.platform if sys_platform is None else sys_platform
    machine = (platform.machine() if machine is None else machine).lower()
    if machine in ("x86_64", "amd64"):
        if sys_platform.startswith("linux"):
            return "linux-x64"
        if sys_platform == "win32":
            return "windows-x64"
    raise FetchError(f"no pinned FFmpeg build for {sys_platform}/{machine}; use --platform")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path: Path, sha256: str, size: int) -> None:
    """Raise ChecksumError unless ``path`` has exactly the pinned size and SHA-256."""
    actual_size = path.stat().st_size
    if actual_size != size:
        raise ChecksumError(f"{path.name}: size {actual_size} bytes, expected {size}")
    actual = sha256_file(path)
    if actual != sha256:
        raise ChecksumError(f"{path.name}: SHA-256 {actual}, expected {sha256}")


def _log(message: str) -> None:
    print(f"fetch-tools: {message}", file=sys.stderr, flush=True)


def download(
    url: str,
    dest: Path,
    *,
    attempts: int = 4,
    timeout: float = 60.0,
    sleep: Callable[[float], None] = time.sleep,
    max_bytes: int | None = None,
) -> None:
    """Download ``url`` to ``dest``. Retry network errors and HTTP 429/5xx with back-off.

    With ``max_bytes``, stop reading as soon as the response is longer than that (the pinned
    size), so a wrong or hostile server cannot fill the disk. That is not retried.
    """
    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=timeout) as response, dest.open("wb") as f:
                written = 0
                for chunk in iter(lambda: response.read(1 << 20), b""):
                    written += len(chunk)
                    if max_bytes is not None and written > max_bytes:
                        raise ChecksumError(
                            f"{url}: response is larger than the pinned size of {max_bytes} bytes"
                        )
                    f.write(chunk)
            return
        except ChecksumError:
            dest.unlink(missing_ok=True)
            raise
        except urllib.error.HTTPError as e:
            retryable = e.code == 429 or e.code >= 500
            error: Exception = e
            e.close()  # an HTTPError holds the response body open
        except (OSError, http.client.HTTPException) as e:  # URLError is an OSError
            retryable = True
            error = e
        dest.unlink(missing_ok=True)
        if not retryable or attempt == attempts:
            raise FetchError(f"download failed after {attempt} attempt(s): {url}: {error}")
        delay = 2.0**attempt
        _log(f"download error ({error}); retry {attempt}/{attempts - 1} in {delay:.0f} s")
        sleep(delay)


def member_path(name: str, root: str) -> PurePosixPath:
    """Return the safe relative path of an archive member, or raise UnsafeArchiveError.

    Every member must be inside the folder ``root``. A ``:`` is refused: it names an NTFS stream.
    """
    if not name or name.startswith("/") or "\\" in name or "\x00" in name or _DRIVE_RE.match(name):
        raise UnsafeArchiveError(f"unsafe archive member name: {name!r}")
    parts = [part for part in name.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." or ":" in part for part in parts):
        raise UnsafeArchiveError(f"unsafe archive member name: {name!r}")
    if parts[0] != root:
        raise UnsafeArchiveError(f"archive member {name!r} is outside the folder {root!r}")
    return PurePosixPath(*parts)


def _check_link_target(member: PurePosixPath, link: str, root: str) -> None:
    if link.startswith("/") or "\\" in link or _DRIVE_RE.match(link):
        raise UnsafeArchiveError(f"link {member} -> {link!r} is absolute")
    target = posixpath.normpath(posixpath.join(str(member.parent), link))
    parts = target.split("/")
    if ".." in parts or parts[0] != root:
        raise UnsafeArchiveError(f"link {member} -> {link!r} points outside {root!r}")


def _extract_tar(archive: Path, root: str, dest: Path) -> None:
    with tarfile.open(archive, "r:xz") as tf:
        members = tf.getmembers()
        for m in members:
            path = member_path(m.name, root)
            if m.issym():
                _check_link_target(path, m.linkname, root)
            elif m.islnk():
                member_path(m.linkname, root)
            elif not (m.isfile() or m.isdir()):
                raise UnsafeArchiveError(f"unsupported archive member type: {m.name!r}")
        # The "data" filter repeats the checks above and drops setuid/setgid and group/other
        # write bits. It keeps the executable bits.
        tf.extractall(dest, members=members, filter="data")


def _extract_zip(archive: Path, root: str, dest: Path) -> None:
    with zipfile.ZipFile(archive) as zf:
        infos = zf.infolist()
        paths = []
        for info in infos:
            path = member_path(info.filename, root)
            if stat.S_ISLNK(info.external_attr >> 16):
                raise UnsafeArchiveError(f"symbolic link in zip archive: {info.filename!r}")
            paths.append(path)
        for info, path in zip(infos, paths, strict=True):
            target = dest.joinpath(*path.parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
            mode = (info.external_attr >> 16) & 0o777
            if os.name == "posix" and mode & 0o111:
                target.chmod(0o755)


def safe_extract(archive: Path, fmt: str, root: str, dest: Path) -> None:
    """Extract ``archive`` into ``dest``. Validate every member before writing any file."""
    if fmt == "tar.xz":
        _extract_tar(archive, root, dest)
    elif fmt == "zip":
        _extract_zip(archive, root, dest)
    else:
        raise FetchError(f"unsupported archive format {fmt!r}")


def tree_digest(directory: Path) -> dict[str, str]:
    """Map each file (SHA-256) and symbolic link (target) under ``directory`` by relative path."""
    result: dict[str, str] = {}
    for path in sorted(directory.rglob("*")):
        rel = path.relative_to(directory).as_posix()
        if rel == MARKER_NAME:
            continue
        if path.is_symlink():
            result[rel] = "link:" + os.readlink(path)
        elif path.is_file():
            result[rel] = "sha256:" + sha256_file(path)
    return result


def _is_installed(install_dir: Path, pbuild: PlatformBuild) -> bool:
    try:
        marker = json.loads((install_dir / MARKER_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(marker, dict) or marker.get("sha256") != pbuild.sha256:
        return False
    files = marker.get("files")
    if not isinstance(files, dict) or not files:
        return False
    return tree_digest(install_dir) == files


def _move_into_place(src: Path, dst: Path, *, attempts: int = 5) -> None:
    """Replace ``dst`` with ``src``. Retry: on Windows a virus scanner can hold new files."""
    for attempt in range(1, attempts + 1):
        try:
            if dst.exists():
                shutil.rmtree(dst)
            src.replace(dst)
            return
        except PermissionError:
            if attempt == attempts:
                raise
            time.sleep(attempt)


def install_dir_for(build: Build, pbuild: PlatformBuild, dest: Path) -> Path:
    return dest / "ffmpeg" / f"{build.name}-{pbuild.platform}"


def _download_and_extract(
    build: Build,
    pbuild: PlatformBuild,
    work: Path,
    downloader: Callable[[str, Path], None] | None,
) -> Path:
    """Download into ``work``, verify, extract. Return the staging folder (it holds the root)."""
    archive = work / pbuild.file_name
    _log(f"downloading {pbuild.url}")
    if downloader is None:
        download(pbuild.url, archive, max_bytes=pbuild.size)
    else:
        downloader(pbuild.url, archive)
    verify_file(archive, pbuild.sha256, pbuild.size)
    _log(f"SHA-256 verified: {pbuild.sha256}")
    staging = work / "extract"
    staging.mkdir()
    safe_extract(archive, pbuild.format, pbuild.root, staging)
    archive.unlink()
    for tool in (pbuild.ffmpeg, pbuild.ffprobe):
        if not (staging / pbuild.root / tool).is_file():
            raise FetchError(f"{tool} not found in the archive under {pbuild.root}/")
    return staging


def _write_marker(folder: Path, build: Build, pbuild: PlatformBuild, layout: str) -> None:
    marker = {
        "build": build.name,
        "version": build.version,
        "platform": pbuild.platform,
        "url": pbuild.url,
        "sha256": pbuild.sha256,
        "layout": layout,
        "files": tree_digest(folder),
    }
    (folder / MARKER_NAME).write_text(json.dumps(marker, indent=1), encoding="utf-8")


def install(
    build: Build,
    pbuild: PlatformBuild,
    dest: Path,
    *,
    downloader: Callable[[str, Path], None] | None = None,
) -> Path:
    """Make sure the build is extracted and verified under ``dest``.

    Return the folder that holds the archive's root folder (``<dest>/ffmpeg/<build>-<platform>``).
    """
    install_dir = install_dir_for(build, pbuild, dest)
    if _is_installed(install_dir, pbuild):
        _log(f"{build.name} ({build.version}, {pbuild.platform}) already extracted and verified")
        return install_dir

    install_dir.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".tmp-", dir=install_dir.parent))
    try:
        staging = _download_and_extract(build, pbuild, work, downloader)
        _write_marker(staging, build, pbuild, "archive")
        _move_into_place(staging, install_dir)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    _log(f"extracted to {install_dir}")
    return install_dir


def _check_replaceable(install_dir: Path) -> None:
    """Refuse to delete a folder that is not empty and was not made by this script."""
    if not install_dir.exists():
        return
    if not install_dir.is_dir():
        raise FetchError(f"--install-dir {install_dir} exists and is not a folder")
    if (install_dir / MARKER_NAME).is_file() or not any(install_dir.iterdir()):
        return
    raise FetchError(
        f"refusing to replace {install_dir}: it is not empty and was not installed by "
        f"fetch-tools (no {MARKER_NAME})"
    )


def install_bundled(
    build: Build,
    pbuild: PlatformBuild,
    install_dir: Path,
    *,
    downloader: Callable[[str, Path], None] | None = None,
) -> Path:
    """Install the build in the layout of a bundled build: ``install_dir/bin/ffmpeg`` …

    The contents of the archive's root folder become ``install_dir`` (``bin/``, and ``lib/``
    with the shared libraries on Linux; on Windows the DLLs are in ``bin/``). This is where
    Reframe's tool discovery looks for the bundled build, for example
    ``$REFRAME_DATA_DIR/tools/ffmpeg`` (``reframe.paths``). Idempotent like :func:`install`.
    """
    if _is_installed(install_dir, pbuild):
        _log(f"{build.name} ({build.version}, {pbuild.platform}) already installed and verified")
        return install_dir
    _check_replaceable(install_dir)
    install_dir.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".tmp-", dir=install_dir.parent))
    try:
        staging = _download_and_extract(build, pbuild, work, downloader)
        layout = staging / pbuild.root
        _write_marker(layout, build, pbuild, "bundled")
        _move_into_place(layout, install_dir)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    _log(f"installed to {install_dir}")
    return install_dir


def check_version(executable: Path, tool: str, version: str) -> None:
    """Run ``<tool> -version`` and check that it prints the pinned version string."""
    try:
        result = subprocess.run(
            [str(executable), "-version"], capture_output=True, text=True, timeout=60, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise FetchError(f"cannot run {executable}: {e}") from e
    first_line = result.stdout.splitlines()[0] if result.stdout else ""
    if result.returncode != 0 or first_line.split()[:3] != [tool, "version", version]:
        raise FetchError(
            f"{executable} -version: exit code {result.returncode}, first line {first_line!r}, "
            f"expected '{tool} version {version}'. stderr: {result.stderr.strip()[:500]}"
        )
    _log(first_line)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--build", default="default", help="build name in the manifest")
    parser.add_argument("--platform", default="auto", choices=("auto", *PLATFORMS))
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST, help="default: <repo>/.tools")
    parser.add_argument(
        "--install-dir",
        type=Path,
        default=None,
        help="install in the bundled layout (DIR/bin, DIR/lib) instead of under --dest",
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    try:
        builds = load_manifest(args.manifest)
        if args.build not in builds:
            raise FetchError(f"unknown build {args.build!r} (manifest has {sorted(builds)})")
        build = builds[args.build]
        target = detect_platform() if args.platform == "auto" else args.platform
        if target not in build.platforms:
            raise FetchError(f"build {build.name!r} has no archive for {target}")
        pbuild = build.platforms[target]
        if args.install_dir is not None:
            base = install_bundled(build, pbuild, Path(args.install_dir).resolve())
        else:
            base = install(build, pbuild, Path(args.dest).resolve()) / pbuild.root
        bin_dir = (base / pbuild.bin_dir).resolve()
        try:
            host = detect_platform()
        except FetchError:
            host = None
        if host == target:
            check_version(base / pbuild.ffmpeg, "ffmpeg", build.version)
            check_version(base / pbuild.ffprobe, "ffprobe", build.version)
        else:
            _log(f"not running the {target} binaries on this host: version check skipped")
    except FetchError as e:
        _log(f"error: {e}")
        return 1

    # stdout carries only the bin folder. Write bytes so Windows does not add "\r".
    sys.stdout.flush()
    sys.stdout.buffer.write(f"{bin_dir}\n".encode())
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
