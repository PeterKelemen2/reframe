"""The distro packages whose files the Linux packages carry, with their source packages and
versions, for the source manifest (``sources-manifest.py --appimage-libs``).

The notices name the sources release, so the list must be known before the AppImage is built:
``resolve`` reads the committed package list (``desktop/packaging/linux/appimage-packages.txt``)
with ``dpkg-query`` in the build image. After ``tauri build``, ``check`` maps every distro file
in the real AppDir (the libraries linuxdeploy copies, and those the frozen sidecar of every Linux
package carries) to its package and fails unless the packages and versions are the ones the
manifest was made from; ``check-runtime`` fails unless the AppImage starts with the pinned
runtime. ``resolve`` and ``check`` run in the Linux build image (Ubuntu, dpkg)::

    uv run --no-project python scripts/appimage-libs.py resolve --out appimage-libs.json
    uv run --no-project python scripts/appimage-libs.py check APPDIR --expected appimage-libs.json
    uv run --no-project python scripts/appimage-libs.py check-runtime APPIMAGE --runtime FILE
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import struct
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PACKAGES = REPO_ROOT / "desktop" / "packaging" / "linux" / "appimage-packages.txt"
SCHEMA_VERSION = 1
DPKG_INFO = Path("/var/lib/dpkg/info")
OS_RELEASE = Path("/etc/os-release")
#: Reframe's own files and what the bundler and linuxdeploy write themselves (not distro files).
OWN_PREFIXES = (
    "usr/bin/reframe-desktop",
    "usr/lib/Reframe/",
    "usr/share/applications/",
    "usr/share/icons/",
    "apprun-hooks/",
)
#: PyInstaller copies the system libraries the sidecar needs here, next to wheel libraries; the
#: .deb and .rpm carry the same folder.
SIDECAR_LIBS = "usr/lib/Reframe/sidecar/_internal/"
_LIBRARY_DIRS = ("/lib/", "/usr/lib/")
#: Caches that linuxdeploy's GTK plugin generates in the AppDir.
GENERATED = frozenset({"loaders.cache", "immodules.cache", "giomodule.cache", "gschemas.compiled"})
#: Sections of the type 2 runtime that appimagetool fills in when it writes the AppImage.
RUNTIME_WRITTEN = frozenset({".digest_md5", ".upd_info", ".sha256_sig", ".sig_key"})
_FIELDS = ("package", "architecture", "version", "source", "source_version")


class AppImageLibsError(Exception):
    """The package data is missing or does not match; nothing is written."""


def read_package_list(path: Path) -> list[str]:
    """The package names of ``path``: one per line, ``#`` starts a comment."""
    names = []
    for line in path.read_text(encoding="utf-8").splitlines():
        name = line.split("#", 1)[0].strip()
        if name:
            names.append(name)
    if not names:
        raise AppImageLibsError(f"{path} lists no package")
    return sorted(set(names))


def distribution() -> dict[str, str]:
    fields = {}
    for line in OS_RELEASE.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep:
            fields[key] = value.strip().strip('"')
    return {"id": fields.get("ID", ""), "version_id": fields.get("VERSION_ID", "")}


def query_packages(names: Sequence[str]) -> list[dict[str, str]]:
    """Version, source package and source version of each installed package ``names``."""
    dpkg_query = shutil.which("dpkg-query")
    if dpkg_query is None:
        raise AppImageLibsError("dpkg-query is not on PATH: run this in the Linux build image")
    fmt = "\t".join(f"${{{f}}}" for f in ("Package", "Architecture", "Version")) + "\t"
    fmt += "${source:Package}\t${source:Version}\t${db:Status-Abbrev}\n"
    result = subprocess.run(
        [dpkg_query, "-W", f"-f={fmt}", *names], capture_output=True, text=True, check=False
    )
    rows: dict[str, dict[str, str]] = {}
    for line in result.stdout.splitlines():
        values = line.split("\t")
        if len(values) == 6 and values[5].startswith("ii"):
            rows[values[0]] = dict(zip(_FIELDS, values[:5], strict=True))
    missing = sorted(set(names) - set(rows))
    if missing:
        raise AppImageLibsError(f"not installed in this image: {', '.join(missing)}")
    return [rows[name] for name in sorted(rows)]


def document(packages: Sequence[Mapping[str, str]], dist: Mapping[str, str]) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "distribution": dict(dist), "packages": packages}


def file_index(dpkg_info: Path = DPKG_INFO) -> dict[str, list[tuple[str, str]]]:
    """Every path that an installed package owns, by base name: ``(path, package)`` pairs."""
    index: dict[str, list[tuple[str, str]]] = {}
    for listing in sorted(dpkg_info.glob("*.list")):
        package = listing.stem.split(":", 1)[0]
        for path in listing.read_text(encoding="utf-8", errors="replace").splitlines():
            index.setdefault(PurePosixPath(path).name, []).append((path, package))
    return index


def _is_own(relative: str) -> bool:
    return "/" not in relative or relative.startswith(OWN_PREFIXES)


def owner(relative: str, index: Mapping[str, Sequence[tuple[str, str]]]) -> set[str]:
    """The packages that own the file the AppDir has at ``relative``.

    linuxdeploy keeps the path of a file below ``usr/`` or copies a library flat into
    ``usr/lib/``, so the same path wins, then a path that ends like it."""
    candidates = index.get(PurePosixPath(relative).name, ())
    same = {pkg for path, pkg in candidates if path == f"/{relative}"}
    if same:
        return same
    tail = relative.removeprefix("usr/lib/")
    ending = {pkg for path, pkg in candidates if path.endswith(f"/{tail}")}
    if ending:
        return ending
    # A package whose doc folder is a symbolic link owns the link, not the files under it.
    for parent in PurePosixPath(relative).parents:
        linked = {pkg for path, pkg in index.get(parent.name, ()) if path == f"/{parent}"}
        if linked:
            return linked
    return set()


def sidecar_owner(name: str, index: Mapping[str, Sequence[tuple[str, str]]]) -> set[str]:
    """The packages that own a system library of the name ``name``: empty for the sidecar's
    other files (Python's own library, wheel libraries)."""
    return {pkg for path, pkg in index.get(name, ()) if path.startswith(_LIBRARY_DIRS)}


def appdir_packages(appdir: Path, index: Mapping[str, Sequence[tuple[str, str]]]) -> list[str]:
    """The packages of every distro file in ``appdir``.

    :raises AppImageLibsError: a file no package (or more than one) owns: its source unknown.
    """
    found: set[str] = set()
    unknown = []
    for path in sorted(appdir.rglob("*")):
        relative = path.relative_to(appdir).as_posix()
        if path.is_dir() and not path.is_symlink():
            continue
        if relative.startswith(SIDECAR_LIBS) and "/" not in relative.removeprefix(SIDECAR_LIBS):
            owners = sidecar_owner(path.name, index)
            if not owners:
                continue
        elif _is_own(relative):
            continue
        else:
            owners = owner(relative, index)
        if len(owners) == 1:
            found |= owners
        elif path.name not in GENERATED:
            unknown.append(f"{relative} ({', '.join(sorted(owners)) or 'no package'})")
    if unknown:
        raise AppImageLibsError(
            "no single package owns these AppImage files:\n  " + "\n  ".join(unknown)
        )
    return sorted(found)


def compare(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> list[str]:
    """What differs between two documents, one line each; empty when they agree."""
    problems = []
    if expected.get("distribution") != actual["distribution"]:
        problems.append(
            f"distribution: {expected.get('distribution')} expected, {actual['distribution']}"
        )
    want = {row["package"]: row for row in expected.get("packages", [])}
    have = {row["package"]: row for row in actual["packages"]}
    for name in sorted(set(want) - set(have)):
        problems.append(f"{name}: in the list, but the AppImage has no file of it")
    for name in sorted(set(have) - set(want)):
        problems.append(f"{name}: in the AppImage, but not in the list")
    for name in sorted(set(want) & set(have)):
        if want[name] != have[name]:
            problems.append(f"{name}: {want[name]} expected, the build image has {have[name]}")
    return problems


def _write(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    partial.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(partial, path)


def resolve(packages_file: Path, out: Path) -> dict[str, Any]:
    data = document(query_packages(read_package_list(packages_file)), distribution())
    _write(out, data)
    return data


def check(appdir: Path, expected_file: Path, packages_file: Path) -> list[str]:
    """The differences between the AppDir's packages and ``expected_file``; empty when equal."""
    if not appdir.is_dir():
        raise AppImageLibsError(f"no AppDir at {appdir}")
    expected = json.loads(expected_file.read_text(encoding="utf-8"))
    names = appdir_packages(appdir, file_index())
    problems = compare(expected, document(query_packages(names), distribution()))
    if set(names) != set(read_package_list(packages_file)):
        problems.append(
            f"update {packages_file.name} to the AppImage's packages:\n" + "\n".join(names)
        )
    return problems


def _elf_sections(data: bytes) -> dict[str, tuple[int, int]]:
    """``(offset, size)`` of each section of a 64-bit little-endian ELF file, by name."""
    try:
        if data[:6] != b"\x7fELF\x02\x01":
            raise AppImageLibsError("not a 64-bit little-endian ELF file")
        shoff = struct.unpack_from("<Q", data, 0x28)[0]
        entsize, count, names_index = struct.unpack_from("<HHH", data, 0x3A)
        headers = [struct.unpack_from("<I20xQQ", data, shoff + i * entsize) for i in range(count)]
        _, names_offset, _ = headers[names_index]
        sections = {}
        for name_offset, offset, size in headers:
            start = names_offset + name_offset
            sections[data[start : data.index(b"\0", start)].decode()] = (offset, size)
        return sections
    except (struct.error, IndexError, ValueError, UnicodeDecodeError) as e:
        raise AppImageLibsError(f"cannot read the ELF section headers: {e}") from e


def runtime_matches(appimage: bytes, runtime: bytes) -> bool:
    """Whether ``appimage`` starts with ``runtime``, apart from what appimagetool writes into it.

    :raises AppImageLibsError: ``runtime`` is not a type 2 runtime.
    """
    sections = _elf_sections(runtime)
    if not set(sections) >= RUNTIME_WRITTEN:
        raise AppImageLibsError("not an AppImage type 2 runtime: its data sections are missing")
    head, pinned = bytearray(appimage[: len(runtime)]), bytearray(runtime)
    for name in RUNTIME_WRITTEN:
        offset, size = sections[name]
        head[offset : offset + size] = pinned[offset : offset + size] = bytes(size)
    return head == pinned


def _print(lines: Iterable[str]) -> None:
    for line in lines:
        sys.stderr.write(f"appimage-libs: {line}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--packages", type=Path, default=DEFAULT_PACKAGES)
    commands = parser.add_subparsers(dest="command", required=True)
    resolve_parser = commands.add_parser("resolve", help="the list's packages and versions")
    resolve_parser.add_argument("--out", type=Path, required=True)
    check_parser = commands.add_parser("check", help="compare a built AppDir with the list")
    check_parser.add_argument("appdir", type=Path)
    check_parser.add_argument("--expected", type=Path, required=True)
    runtime_parser = commands.add_parser(
        "check-runtime", help="compare the AppImage's runtime with the pinned one"
    )
    runtime_parser.add_argument("appimage", type=Path)
    runtime_parser.add_argument("--runtime", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "resolve":
            data = resolve(args.packages, args.out)
            print(f"wrote {args.out} ({len(data['packages'])} packages)")
            return 0
        if args.command == "check-runtime":
            if not runtime_matches(args.appimage.read_bytes(), args.runtime.read_bytes()):
                _print([f"{args.appimage} does not start with the runtime {args.runtime}"])
                return 1
            print(f"{args.appimage} starts with the runtime {args.runtime}")
            return 0
        problems = check(args.appdir, args.expected, args.packages)
    except (AppImageLibsError, OSError, ValueError) as e:
        _print([str(e)])
        return 1
    if problems:
        _print(problems)
        return 1
    print(f"the AppImage's distro files match {args.expected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
