"""Lay out the pinned tools that a desktop package ships (the app's ``tools`` resource folder).

FFmpeg is the ``default`` build of ``tools/ffmpeg.toml``; the Windows layout also gets
MKVToolNix and MediaInfo from ``tools/bundled-tools.toml``. Each archive's size and SHA-256 are
checked before anything is extracted. A rerun keeps a tool folder whose files still have the
hashes recorded when it was laid out, and the destination holds nothing but its ``README.md``
and the platform's tool folders afterwards. On the platform the layout is for, tool discovery
must then find every bundled tool with its pinned version.
"""

from __future__ import annotations

import argparse
import json
import os
import posixpath
import re
import shutil
import sys
import tempfile
import tomllib
import urllib.parse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from reframe.models.tools import ToolOrigin, ToolStatus
from reframe.tools import fetch
from reframe.tools.discovery import ENV_VARS, discover_tools_sync
from reframe.tools.runner import CancelToken

REPO_ROOT = Path(__file__).resolve().parent.parent
FFMPEG_MANIFEST = REPO_ROOT / "tools" / "ffmpeg.toml"
TOOLS_MANIFEST = REPO_ROOT / "tools" / "bundled-tools.toml"
DEFAULT_DEST = REPO_ROOT / "desktop" / "src-tauri" / "resources" / "tools"

#: The committed file of the destination folder.
README = "README.md"
WORK_PREFIX = ".bundle-"
#: Every tool folder this script makes, with the tools that discovery finds in it.
FOLDER_TOOLS: Mapping[str, tuple[str, ...]] = {
    "ffmpeg": ("ffmpeg", "ffprobe"),
    "mkvtoolnix": ("mkvpropedit",),
    "mediainfo": ("mediainfo",),
}

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


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
    root: str | None
    """The archive's top folder (``None``: none); its contents become the tool folder."""
    files: tuple[str, ...] | None
    """The paths (relative to ``root``) to keep; ``None`` keeps everything."""
    required: tuple[str, ...]
    """Paths that must be in the laid-out folder: the binaries and the licence file."""


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
        files=None,
        required=(pbuild.ffmpeg, pbuild.ffprobe, license_file),
    )


def _tool_archive(folder: str, tool: Mapping[str, object], platform: str) -> Archive | None:
    where = f"tools.{folder}"
    version = _str(tool, "version", where)
    for key in ("license", "source_url"):
        _str(tool, key, where)
    license_file = _rel_path(tool.get("license_file"), f"{where}.license_file")
    platforms = tool.get("platforms")
    if not isinstance(platforms, dict) or not platforms:
        raise fetch.FetchError(f"{where}.platforms: expected a non-empty table")
    table = platforms.get(platform)
    if table is None:
        return None
    where = f"{where}.platforms.{platform}"
    if not isinstance(table, dict):
        raise fetch.FetchError(f"{where}: expected a table")
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
    if fmt not in fetch.FORMATS or not url.endswith("." + fmt):
        raise fetch.FetchError(
            f"{where}.format: {fmt!r} is not one of {fetch.FORMATS} or the URL's"
        )
    root = table.get("root")
    if root is not None:
        root = _rel_path(root, f"{where}.root")
        if "/" in root:
            raise fetch.FetchError(f"{where}.root: expected one folder name, got {root!r}")
    elif fmt != "zip":
        raise fetch.FetchError(f"{where}.root: a {fmt} archive needs its top folder")
    binary = _rel_path(table.get("binary"), f"{where}.binary")
    files_value = table.get("files")
    files: tuple[str, ...] | None = None
    if files_value is not None:
        if not isinstance(files_value, list) or not files_value:
            raise fetch.FetchError(f"{where}.files: expected a non-empty list")
        files = tuple(_rel_path(f, f"{where}.files") for f in files_value)
        missing = [p for p in (binary, license_file) if p not in files]
        if missing:
            raise fetch.FetchError(f"{where}.files: does not keep {', '.join(missing)}")
    return Archive(
        folder=folder,
        version=version,
        platform=platform,
        url=url,
        sha256=sha256,
        size=size,
        format=fmt,
        root=root,
        files=files,
        required=(binary, license_file),
    )


def tool_archives(manifest: Path, platform: str) -> list[Archive]:
    """The MKVToolNix and MediaInfo archives pinned for ``platform`` (none on Linux)."""
    data = _load_toml(manifest)
    if data.get("schema_version") != 1:
        raise fetch.FetchError(f"{manifest}: schema_version: expected 1")
    tools = data.get("tools")
    if not isinstance(tools, dict):
        raise fetch.FetchError(f"{manifest}: expected a [tools] table")
    archives = []
    for folder, table in tools.items():
        if folder not in FOLDER_TOOLS or folder == "ffmpeg" or not isinstance(table, dict):
            raise fetch.FetchError(f"{manifest}: unknown tool {folder!r}")
        try:
            archive = _tool_archive(folder, table, platform)
        except fetch.FetchError as e:
            raise fetch.FetchError(f"{manifest}: {e}") from e
        if archive is not None:
            archives.append(archive)
    return archives


def _is_laid_out(folder: Path, archive: Archive) -> bool:
    marker = fetch.installed_build(folder)
    if marker is None or marker.get("sha256") != archive.sha256:
        return False
    kept = None if archive.files is None else list(archive.files)
    if marker.get("kept") != kept:
        return False
    files = marker.get("files")
    return isinstance(files, dict) and bool(files) and fetch.tree_digest(folder) == files


def _clear_destination(dest: Path, wanted: Sequence[str]) -> None:
    """Remove what an earlier run left that this layout does not want (work folders, another
    platform's tool folders). :raises FetchError: ``dest`` holds anything this script did not
    make; nothing is removed then."""
    unknown: list[str] = []
    remove: list[Path] = []
    for entry in sorted(dest.iterdir()):
        if entry.name == README and entry.is_file():
            continue
        if entry.name.startswith(WORK_PREFIX) and entry.is_dir() and not entry.is_symlink():
            remove.append(entry)
        elif entry.name in FOLDER_TOOLS and not entry.is_symlink() and entry.is_dir():
            empty = not any(entry.iterdir())
            if not empty and fetch.installed_build(entry) is None:
                unknown.append(entry.name)
            elif entry.name not in wanted:
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


def _lay_out(archive: Archive, dest: Path) -> None:
    folder = dest / archive.folder
    if _is_laid_out(folder, archive):
        _log(f"{archive.folder} {archive.version} ({archive.platform}) is up to date")
        return
    work = Path(tempfile.mkdtemp(prefix=WORK_PREFIX, dir=dest))
    try:
        file_name = posixpath.basename(urllib.parse.urlsplit(archive.url).path)
        downloaded = work / file_name
        _log(f"downloading {archive.url}")
        fetch.download(archive.url, downloaded, size=archive.size, cancel=CancelToken())
        fetch.verify_file(downloaded, archive.sha256, archive.size)
        _log(f"SHA-256 verified: {archive.sha256}")
        extracted = work / "extract"
        extracted.mkdir()
        fetch.safe_extract(downloaded, archive.format, archive.root, extracted, CancelToken())
        downloaded.unlink()
        source = extracted / archive.root if archive.root is not None else extracted
        if archive.files is None:
            new = source
        else:
            new = work / "keep"
            for rel in archive.files:
                src = source.joinpath(*PurePosixPath(rel).parts)
                if not src.is_file():
                    raise fetch.FetchError(f"{file_name} has no {rel}")
                target = new.joinpath(*PurePosixPath(rel).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                src.replace(target)
        for rel in archive.required:
            if not new.joinpath(*PurePosixPath(rel).parts).is_file():
                raise fetch.FetchError(f"{file_name} has no {rel}")
        marker = {
            "build": archive.folder,
            "version": archive.version,
            "platform": archive.platform,
            "url": archive.url,
            "sha256": archive.sha256,
            "layout": "bundled",
            "kept": None if archive.files is None else list(archive.files),
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
    found = discover_tools_sync(environ=environ, bundled_roots=[dest], search_path="")
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
        pinned file, a destination with foreign files, or a tool that discovery does not find.
    """
    archives = [
        ffmpeg_archive(ffmpeg_manifest, platform),
        *tool_archives(tools_manifest, platform),
    ]
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
    parser.add_argument("--platform", required=True, choices=fetch.PLATFORMS)
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
