"""Lay out the pinned tools that a desktop package ships (the app's ``tools`` resource folder).

FFmpeg is the ``default`` build of ``tools/ffmpeg.toml``; the Linux layout also gets a libva
built from its pinned source (``tools/bundled-tools.toml``) into FFmpeg's ``lib/`` (the libva of
older distros lacks functions the build calls). Each archive's size and SHA-256 are checked
before anything is extracted. A rerun keeps a tool folder
whose files still have the hashes recorded when it was laid out, and the destination holds
nothing but its ``README.md`` and the platform's tool folders afterwards. On the platform the
layout is for, tool discovery must then find every bundled tool with its pinned version.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.parse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from reframe.models.tools import ToolOrigin, ToolStatus
from reframe.tools import fetch
from reframe.tools.discovery import ENV_VARS, LIBVA_DRIVER_DIRS, discover_tools
from reframe.tools.runner import CancelToken

REPO_ROOT = Path(__file__).resolve().parent.parent
FFMPEG_MANIFEST = REPO_ROOT / "tools" / "ffmpeg.toml"
TOOLS_MANIFEST = REPO_ROOT / "tools" / "bundled-tools.toml"
DEFAULT_DEST = REPO_ROOT / "desktop" / "src-tauri" / "resources" / "tools"
#: The desktop packages are built for x64 only.
PLATFORMS = ("linux-x64", "windows-x64")

#: The committed file of the destination folder.
README = "README.md"
WORK_PREFIX = ".bundle-"
#: Every tool folder this script makes, with the tools that discovery finds in it.
FOLDER_TOOLS: Mapping[str, tuple[str, ...]] = {"ffmpeg": ("ffmpeg", "ffprobe")}
#: Archive formats of the pins in ``tools/bundled-tools.toml``.
FORMATS = ("tar.xz", "tar.bz2", "zip")
#: The libraries of the libva build that FFmpeg loads.
LIBVA_SONAMES = ("libva.so.2", "libva-drm.so.2")

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class Library:
    """A library built from a pinned source archive into the FFmpeg folder's ``lib/``."""

    name: str
    version: str
    url: str
    sha256: str
    size: int
    format: str
    root: str
    license_file: str
    """Relative to ``root``; copied as ``LICENSE-<name>.txt`` next to FFmpeg's licence."""


@dataclass(frozen=True, slots=True)
class Archive:
    """One archive to lay out as the tool folder ``folder``."""

    folder: str
    version: str
    platform: str
    url: str
    sha256: str
    size: int
    format: str
    root: str
    """The archive's top folder; its contents become the tool folder."""
    required: tuple[str, ...]
    """Paths that must be in the laid-out folder: the binaries and the licence file."""
    libraries: tuple[Library, ...] = ()


def _log(message: str) -> None:
    print(f"bundle-tools: {message}", file=sys.stderr, flush=True)


def _str(table: Mapping[str, object], key: str, where: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise fetch.FetchError(f"{where}.{key}: expected a non-empty string, got {value!r}")
    return value


def _rel_path(value: object, where: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.startswith("/")
        or "\\" in value
        or ":" in value
        or any(part in ("", ".", "..") for part in value.split("/"))
    ):
        raise fetch.FetchError(f"{where}: expected a relative POSIX path, got {value!r}")
    return value


def _load_toml(path: Path) -> dict[str, object]:
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except OSError as e:
        raise fetch.FetchError(f"cannot read {path}: {e.strerror or e}") from e
    except tomllib.TOMLDecodeError as e:
        raise fetch.FetchError(f"{path} is not valid TOML: {e}") from e


def ffmpeg_archive(manifest: Path, platform: str) -> Archive:
    """The ``default`` build of the FFmpeg manifest for ``platform``. :raises FetchError:"""
    build = fetch.load_manifest(manifest)["default"]
    pbuild = build.platforms.get(platform)
    if pbuild is None:
        raise fetch.FetchError(f"{manifest}: the default build has no archive for {platform}")
    table = _load_toml(manifest)["builds"]
    assert isinstance(table, dict)  # load_manifest checked it
    license_file = _rel_path(table["default"].get("license_file"), "builds.default.license_file")
    return Archive(
        folder="ffmpeg",
        version=build.version,
        platform=platform,
        url=pbuild.url,
        sha256=pbuild.sha256,
        size=pbuild.size,
        format=pbuild.format,
        root=pbuild.root,
        required=(pbuild.ffmpeg, pbuild.ffprobe, license_file),
    )


def _pin(table: Mapping[str, object], where: str) -> tuple[str, str, int, str, str]:
    """``(url, sha256, size, format, root)`` of one pinned archive."""
    url = _str(table, "url", where)
    scheme = urllib.parse.urlsplit(url).scheme
    if scheme not in ("https", "file"):
        raise fetch.FetchError(f"{where}.url: expected an https:// URL, got {url!r}")
    sha256 = _str(table, "sha256", where)
    if not _SHA256_RE.match(sha256):
        raise fetch.FetchError(f"{where}.sha256: expected 64 lowercase hex digits")
    size = table.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise fetch.FetchError(f"{where}.size: expected a positive integer, got {size!r}")
    fmt = _str(table, "format", where)
    if fmt not in FORMATS or not url.endswith("." + fmt):
        raise fetch.FetchError(f"{where}.format: {fmt!r} is not one of {FORMATS} or the URL's")
    if table.get("root") is None:
        raise fetch.FetchError(f"{where}.root: a source archive needs its top folder")
    root = _rel_path(table.get("root"), f"{where}.root")
    if "/" in root:
        raise fetch.FetchError(f"{where}.root: expected one folder name, got {root!r}")
    return url, sha256, size, fmt, root


def _load_tools_manifest(manifest: Path) -> dict[str, object]:
    data = _load_toml(manifest)
    if data.get("schema_version") != 1:
        raise fetch.FetchError(f"{manifest}: schema_version: expected 1")
    return data


def libraries(manifest: Path, platform: str) -> list[Library]:
    """The libraries built into the FFmpeg folder for ``platform`` (libva on Linux)."""
    tables = _load_tools_manifest(manifest).get("libraries", {})
    if not isinstance(tables, dict):
        raise fetch.FetchError(f"{manifest}: libraries: expected a table")
    found = []
    for name, lib in tables.items():
        where = f"{manifest}: libraries.{name}"
        if name not in LIBRARY_BUILDERS or not isinstance(lib, dict):
            raise fetch.FetchError(f"{where}: no build is known for this library")
        platforms = lib.get("platforms")
        table = platforms.get(platform) if isinstance(platforms, dict) else None
        if not isinstance(table, dict):
            continue
        version = _str(lib, "version", where)
        for key in ("license", "source_repository"):
            _str(lib, key, where)
        license_file = _rel_path(lib.get("license_file"), f"{where}.license_file")
        url, sha256, size, fmt, root = _pin(table, f"{where}.platforms.{platform}")
        found.append(Library(name, version, url, sha256, size, fmt, root, license_file))
    return found


def _is_laid_out(folder: Path, archive: Archive) -> bool:
    marker = fetch.installed_build(folder)
    if marker is None or marker.get("sha256") != archive.sha256:
        return False
    if marker.get("libraries", {}) != {lib.name: lib.sha256 for lib in archive.libraries}:
        return False
    files = marker.get("files")
    return isinstance(files, dict) and bool(files) and fetch.tree_digest(folder) == files


def _made_here(folder: Path) -> bool:
    """An empty tool folder, or one with a layout marker: the bundler ships every folder here,
    so one left by an earlier layout of a tool that is no longer pinned must go too."""
    if folder.name in FOLDER_TOOLS and not any(folder.iterdir()):
        return True
    marker = fetch.installed_build(folder)
    return marker is not None and marker.get("layout") == "bundled"


def _clear_destination(dest: Path, wanted: Sequence[str]) -> None:
    """Remove what an earlier run left that this layout does not want (work folders, another
    platform's tool folders, a tool that is no longer bundled). :raises FetchError: ``dest``
    holds anything this script did not make; nothing is removed then."""
    unknown: list[str] = []
    remove: list[Path] = []
    for entry in sorted(dest.iterdir()):
        if entry.name == README and entry.is_file():
            continue
        folder = entry.is_dir() and not entry.is_symlink()
        if folder and entry.name.startswith(WORK_PREFIX):
            remove.append(entry)
        elif folder and _made_here(entry):
            if entry.name not in wanted:
                remove.append(entry)
        else:
            unknown.append(entry.name)
    if unknown:
        raise fetch.FetchError(
            f"{dest} holds {', '.join(unknown)}, which bundle-tools did not make: move it away"
        )
    for entry in remove:
        _log(f"removing {entry}")
        shutil.rmtree(entry)


def _fetch(url: str, sha256: str, size: int, fmt: str, root: str, into: Path) -> Path:
    """Download, verify and extract one archive into the new folder ``into``; the folder that
    holds its contents (``into/root``)."""
    into.mkdir()
    downloaded = into.with_name(into.name + "." + fmt)
    _log(f"downloading {url}")
    fetch.download(url, downloaded, size=size, cancel=CancelToken())
    fetch.verify_file(downloaded, sha256, size)
    _log(f"SHA-256 verified: {sha256}")
    fetch.safe_extract(downloaded, fmt, root, into, CancelToken())
    downloaded.unlink()
    return into / root


def _run(argv: list[str]) -> None:
    _log(" ".join(argv))
    result = subprocess.run(argv, stdout=sys.stderr, check=False)
    if result.returncode != 0:
        raise fetch.FetchError(f"{' '.join(argv[:2])} failed with exit code {result.returncode}")


def _build_libva(source: Path, build: Path) -> dict[str, Path]:
    """Build libva with DRM only (FFmpeg needs no X11 or Wayland); its libraries by soname."""
    missing = [tool for tool in ("meson", "ninja", "pkg-config", "cc") if not shutil.which(tool)]
    if missing:
        raise fetch.FetchError(
            f"building libva needs {', '.join(missing)} and libdrm's headers "
            "(Debian/Ubuntu: apt install meson ninja-build pkg-config gcc libdrm-dev)"
        )
    _run(
        [
            "meson", "setup", str(build), str(source), "--buildtype=release", "--prefix=/usr",
            "-Ddisable_drm=false", "-Dwith_x11=no", "-Dwith_glx=no", "-Dwith_wayland=no",
            f"-Ddriverdir={':'.join(d.as_posix() for d in LIBVA_DRIVER_DIRS)}",
        ]
    )  # fmt: skip
    _run(["meson", "compile", "-C", str(build)])
    return {soname: (build / "va" / soname).resolve() for soname in LIBVA_SONAMES}


#: How each library of the manifest is built: ``(source folder, build folder)`` → its shared
#: libraries by soname.
LIBRARY_BUILDERS: dict[str, Callable[[Path, Path], dict[str, Path]]] = {"libva": _build_libva}


def _add_library(library: Library, work: Path, folder: Path) -> None:
    """Build ``library`` into ``folder/lib`` (each file under its own name, linked from its
    soname) and put its licence next to FFmpeg's."""
    source = _fetch(
        library.url,
        library.sha256,
        library.size,
        library.format,
        library.root,
        work / f"src-{library.name}",
    )
    built = LIBRARY_BUILDERS[library.name](source, work / f"build-{library.name}")
    lib = folder / "lib"
    lib.mkdir(exist_ok=True)
    for soname, path in built.items():
        if not path.is_file():
            raise fetch.FetchError(f"the {library.name} build made no {soname}")
        shutil.copyfile(path, lib / path.name)
        if path.name != soname:
            (lib / soname).unlink(missing_ok=True)
            (lib / soname).symlink_to(path.name)
    shutil.copyfile(source / library.license_file, folder / f"LICENSE-{library.name}.txt")
    _log(f"built {library.name} {library.version} into {lib}")


def _lay_out(archive: Archive, dest: Path) -> None:
    folder = dest / archive.folder
    if _is_laid_out(folder, archive):
        _log(f"{archive.folder} {archive.version} ({archive.platform}) is up to date")
        return
    work = Path(tempfile.mkdtemp(prefix=WORK_PREFIX, dir=dest))
    try:
        file_name = posixpath.basename(urllib.parse.urlsplit(archive.url).path)
        new = _fetch(
            archive.url, archive.sha256, archive.size, archive.format, archive.root, work / "x"
        )
        for rel in archive.required:
            if not new.joinpath(*PurePosixPath(rel).parts).is_file():
                raise fetch.FetchError(f"{file_name} has no {rel}")
        for library in archive.libraries:
            _add_library(library, work, new)
        marker = {
            "build": archive.folder,
            "version": archive.version,
            "platform": archive.platform,
            "url": archive.url,
            "sha256": archive.sha256,
            "layout": "bundled",
            "libraries": {lib.name: lib.sha256 for lib in archive.libraries},
            "files": fetch.tree_digest(new),
        }
        (new / fetch.MARKER_NAME).write_text(json.dumps(marker, indent=1), encoding="utf-8")
        if folder.exists():
            shutil.rmtree(folder)
        new.rename(folder)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    _log(f"laid out {folder}")


def check_discovery(dest: Path, archives: Sequence[Archive]) -> None:
    """Tool discovery, as the installed app runs it on this computer, must find each tool of
    ``archives`` in ``dest`` with its pinned version. :raises FetchError:"""
    environ = {k: v for k, v in os.environ.items() if k not in ENV_VARS.values()}
    found = asyncio.run(discover_tools(environ=environ, bundled_roots=[dest], search_path=""))
    problems = []
    for archive in archives:
        for name in FOLDER_TOOLS[archive.folder]:
            info = getattr(found, name)
            if info.status != ToolStatus.FOUND or info.origin != ToolOrigin.BUNDLED:
                problems.append(f"{name}: {info.status.value} ({info.reason})")
            elif info.version != archive.version:
                problems.append(f"{name}: version {info.version!r}, expected {archive.version!r}")
            else:
                _log(f"{name} {info.version} found as bundled: {info.path}")
    if problems:
        raise fetch.FetchError("tool discovery: " + "; ".join(problems))


def bundle(
    platform: str,
    dest: Path,
    *,
    ffmpeg_manifest: Path = FFMPEG_MANIFEST,
    tools_manifest: Path = TOOLS_MANIFEST,
) -> list[Archive]:
    """Lay out every tool of ``platform`` in ``dest``; the archives laid out.

    :raises FetchError: a bad manifest, a download or checksum failure, an archive without a
        pinned file, a failed library build, a destination with foreign files, or a tool that
        discovery does not find.
    """
    ffmpeg = ffmpeg_archive(ffmpeg_manifest, platform)
    archives = [replace(ffmpeg, libraries=tuple(libraries(tools_manifest, platform)))]
    dest.mkdir(parents=True, exist_ok=True)
    _clear_destination(dest, [a.folder for a in archives])
    for archive in archives:
        _lay_out(archive, dest)
    if fetch.host_platform() == platform:
        check_discovery(dest, archives)
    else:
        _log(f"not running the {platform} tools on this computer: discovery check skipped")
    return archives


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--platform", required=True, choices=PLATFORMS)
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST, help="default: %(default)s")
    parser.add_argument(
        "--ffmpeg-manifest", type=Path, default=FFMPEG_MANIFEST, help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--tools-manifest", type=Path, default=TOOLS_MANIFEST, help=argparse.SUPPRESS
    )
    args = parser.parse_args(argv)
    try:
        bundle(
            args.platform,
            Path(args.dest).absolute(),
            ffmpeg_manifest=args.ffmpeg_manifest,
            tools_manifest=args.tools_manifest,
        )
    except (fetch.FetchError, OSError) as e:
        _log(f"error: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
