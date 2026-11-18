"""Lay out what a desktop package ships next to its sidecar (the app's ``tools`` resource folder).

The packages contain no FFmpeg: the app downloads it, or installs it from an archive, at the
first run. The Linux layout holds libva, built from its pinned source (``tools/bundled-tools.toml``)
into ``libva/``, which the core copies into a downloaded build's ``lib/`` (the libva of older
distros lacks functions the BtbN build calls); the Windows layout holds nothing. Each source
archive's size and SHA-256 are checked before anything is extracted. A rerun keeps a library
folder whose files still have the hashes recorded when it was laid out, and the destination
holds nothing but its ``README.md`` and the platform's library folders afterwards.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.parse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from reframe.tools import fetch
from reframe.tools.discovery import LIBVA_DRIVER_DIRS
from reframe.tools.runner import CancelToken

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_MANIFEST = REPO_ROOT / "tools" / "bundled-tools.toml"
DEFAULT_DEST = REPO_ROOT / "desktop" / "src-tauri" / "resources" / "tools"
#: The desktop packages are built for x64 only.
PLATFORMS = ("linux-x64", "windows-x64")

#: The committed file of the destination folder.
README = "README.md"
WORK_PREFIX = ".bundle-"
#: Folders that earlier layouts made for tools no package ships any more: a rerun removes them
#: when they carry the layout marker or are empty.
RETIRED_FOLDERS = ("ffmpeg", "mkvtoolnix", "mediainfo")
#: Archive formats of the pins in ``tools/bundled-tools.toml``.
FORMATS = ("tar.xz", "tar.bz2", "zip")
#: The libraries of the libva build that FFmpeg loads, in load order.
LIBVA_SONAMES = ("libva.so.2", "libva-drm.so.2")

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class Library:
    """A library built from a pinned source archive into the folder ``<dest>/<name>``."""

    name: str
    version: str
    url: str
    sha256: str
    size: int
    format: str
    root: str
    license_file: str
    """Relative to ``root``; copied as ``LICENSE-<name>.txt`` next to the libraries."""


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


def libraries(manifest: Path, platform: str) -> list[Library]:
    """The libraries laid out for ``platform`` (libva on Linux)."""
    data = _load_toml(manifest)
    if data.get("schema_version") != 1:
        raise fetch.FetchError(f"{manifest}: schema_version: expected 1")
    tables = data.get("libraries", {})
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


def _is_laid_out(folder: Path, library: Library) -> bool:
    marker = fetch.installed_build(folder)
    if marker is None or marker.get("sha256") != library.sha256:
        return False
    files = marker.get("files")
    return isinstance(files, dict) and bool(files) and fetch.tree_digest(folder) == files


def _made_here(folder: Path) -> bool:
    """A folder with a layout marker, or an empty one of a retired tool: the bundler ships every
    folder here, so one an earlier layout left must go too."""
    if folder.name in RETIRED_FOLDERS and not any(folder.iterdir()):
        return True
    marker = fetch.installed_build(folder)
    return marker is not None and marker.get("layout") == "bundled"


def _clear_destination(dest: Path, wanted: Sequence[str]) -> None:
    """Remove what an earlier run left that this layout does not want (work folders, another
    platform's folders, an FFmpeg). :raises FetchError: ``dest`` holds anything this script did
    not make; nothing is removed then."""
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


def _fetch(library: Library, into: Path) -> Path:
    """Download, verify and extract the source archive into the new folder ``into``; the
    folder that holds its contents."""
    into.mkdir()
    downloaded = into.with_name(into.name + "." + library.format)
    _log(f"downloading {library.url}")
    fetch.download(library.url, downloaded, size=library.size, cancel=CancelToken())
    fetch.verify_file(downloaded, library.sha256, library.size)
    _log(f"SHA-256 verified: {library.sha256}")
    fetch.safe_extract(downloaded, library.format, library.root, into, CancelToken())
    downloaded.unlink()
    return into / library.root


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


def _lay_out(library: Library, dest: Path) -> None:
    """Build ``library`` into ``dest/<name>``: each file under its own name, linked from its
    soname, with the licence as ``LICENSE-<name>.txt``."""
    folder = dest / library.name
    if _is_laid_out(folder, library):
        _log(f"{library.name} {library.version} is up to date")
        return
    work = Path(tempfile.mkdtemp(prefix=WORK_PREFIX, dir=dest))
    try:
        source = _fetch(library, work / "src")
        built = LIBRARY_BUILDERS[library.name](source, work / "build")
        new = work / "out"
        new.mkdir()
        for soname, path in built.items():
            if not path.is_file():
                raise fetch.FetchError(f"the {library.name} build made no {soname}")
            shutil.copyfile(path, new / path.name)
            if path.name != soname:
                (new / soname).symlink_to(path.name)
        shutil.copyfile(source / library.license_file, new / f"LICENSE-{library.name}.txt")
        marker = {
            "build": library.name,
            "version": library.version,
            "url": library.url,
            "sha256": library.sha256,
            "layout": "bundled",
            "files": fetch.tree_digest(new),
        }
        (new / fetch.MARKER_NAME).write_text(json.dumps(marker, indent=1), encoding="utf-8")
        if folder.exists():
            shutil.rmtree(folder)
        new.rename(folder)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    _log(f"built {library.name} {library.version} into {folder}")


def check_loads(folder: Path, sonames: Sequence[str]) -> None:
    """Each library of ``folder`` must load on this computer, in order (a later one needs the
    earlier ones). :raises FetchError:"""
    for soname in sonames:
        try:
            ctypes.CDLL(str(folder / soname))
        except OSError as e:
            raise fetch.FetchError(f"{folder / soname} does not load: {e}") from e
        _log(f"{folder / soname} loads")


def bundle(platform: str, dest: Path, *, tools_manifest: Path = TOOLS_MANIFEST) -> list[Library]:
    """Lay out every library of ``platform`` in ``dest``; the libraries laid out.

    :raises FetchError: a bad manifest, a download or checksum failure, a failed library build,
        a destination with foreign files, or (on the platform the layout is for) a library
        that does not load.
    """
    found = libraries(tools_manifest, platform)
    dest.mkdir(parents=True, exist_ok=True)
    _clear_destination(dest, [lib.name for lib in found])
    for library in found:
        _lay_out(library, dest)
    if fetch.host_platform() == platform and "libva" in {lib.name for lib in found}:
        check_loads(dest / "libva", LIBVA_SONAMES)
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--platform", required=True, choices=PLATFORMS)
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST, help="default: %(default)s")
    parser.add_argument(
        "--tools-manifest", type=Path, default=TOOLS_MANIFEST, help=argparse.SUPPRESS
    )
    args = parser.parse_args(argv)
    try:
        bundle(args.platform, Path(args.dest).absolute(), tools_manifest=args.tools_manifest)
    except (fetch.FetchError, OSError) as e:
        _log(f"error: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
