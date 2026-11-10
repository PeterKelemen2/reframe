"""Assemble the tools that the desktop app ships, in ``desktop/src-tauri/resources/tools/``.

FFmpeg comes from ``tools/ffmpeg.toml`` (through ``fetch-tools.py``). On Linux the libva of
``tools/libva.toml`` is built from source in its ``build_image`` and goes into
``ffmpeg/libva/``; on Windows ``mkvpropedit.exe`` comes from ``tools/mkvtoolnix.toml``. Every
download is checked against its pinned size and SHA-256 before it is used. The destination is
replaced as a whole, and holds only what Reframe runs, plus the licence files. Standard library
only.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"
DEFAULT_DEST = REPO_ROOT / "desktop" / "src-tauri" / "resources" / "tools"
CACHE = REPO_ROOT / ".tools"
#: Written into the destination; it lists what was bundled, from which pin.
MARKER_NAME = "bundle.json"
#: The committed file that keeps the destination in git: the app does not build without it.
KEEP_NAME = "README.md"
#: The folder in ``ffmpeg/`` that Reframe's discovery takes the shipped libva from.
LIBVA_DIR = "libva"


def _fetch_tools() -> ModuleType:
    script = Path(__file__).with_name("fetch-tools.py")
    spec = importlib.util.spec_from_file_location("fetch_tools", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["fetch_tools"] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


ft = _fetch_tools()
BundleError = ft.FetchError


def _log(message: str) -> None:
    print(f"bundle-tools: {message}", file=sys.stderr, flush=True)


@dataclass(frozen=True)
class Download:
    url: str
    sha256: str
    size: int

    @property
    def file_name(self) -> str:
        return self.url.rsplit("/", 1)[-1]


@dataclass(frozen=True)
class Libva:
    version: str
    source: Download
    root: str
    license_file: str
    build_image: str
    driver_dirs: tuple[str, ...]
    libraries: tuple[str, ...]


@dataclass(frozen=True)
class Mkvtoolnix:
    version: str
    archive: Download
    files: Mapping[str, str]


def _str(table: Mapping[str, object], key: str, where: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value:
        raise BundleError(f"{where}: {key} must be a non-empty string")
    return value


def _strs(table: Mapping[str, object], key: str, where: str) -> tuple[str, ...]:
    value = table.get(key)
    if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
        raise BundleError(f"{where}: {key} must be a non-empty list of strings")
    return tuple(value)


def _download(table: Mapping[str, object], where: str) -> Download:
    size = table.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise BundleError(f"{where}: size must be a positive integer")
    sha256 = _str(table, "sha256", where)
    if not ft._SHA256_RE.match(sha256):
        raise BundleError(f"{where}: sha256 must be 64 lowercase hex digits")
    return Download(_str(table, "url", where), sha256, size)


def _load(path: Path) -> dict[str, object]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise BundleError(f"cannot read {path}: {e}") from e
    if data.get("schema_version") != 1:
        raise BundleError(f"{path.name}: schema_version must be 1")
    return data


def load_libva(path: Path = TOOLS_DIR / "libva.toml") -> Libva:
    data = _load(path)
    where = path.name
    return Libva(
        version=_str(data, "version", where),
        source=_download(data, where),
        root=_str(data, "root", where),
        license_file=_str(data, "license_file", where),
        build_image=_str(data, "build_image", where),
        driver_dirs=_strs(data, "driver_dirs", where),
        libraries=_strs(data, "libraries", where),
    )


def load_mkvtoolnix(platform: str, path: Path = TOOLS_DIR / "mkvtoolnix.toml") -> Mkvtoolnix:
    data = _load(path)
    platforms = data.get("platforms")
    table = platforms.get(platform) if isinstance(platforms, dict) else None
    where = f"{path.name} [platforms.{platform}]"
    if not isinstance(table, dict):
        raise BundleError(f"{path.name}: no [platforms.{platform}]")
    files = table.get("files")
    if not isinstance(files, dict) or not files:
        raise BundleError(f"{where}: files must be a non-empty table")
    for member, name in files.items():
        if not isinstance(name, str) or "/" in name or "\\" in name or name in ("", ".", ".."):
            raise BundleError(f"{where}: {member} must map to a plain file name")
    return Mkvtoolnix(_str(data, "version", path.name), _download(table, where), files)


def fetch(download: Download, folder: Path) -> Path:
    """The verified archive in ``folder`` (kept between runs, checked every time)."""
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / download.file_name
    if archive.is_file():
        try:
            ft.verify_file(archive, download.sha256, download.size)
            return archive
        except ft.ChecksumError:
            archive.unlink()
    _log(f"downloading {download.url}")
    ft.download(download.url, archive, max_bytes=download.size)
    ft.verify_file(archive, download.sha256, download.size)
    return archive


def _copy_file(src: Path, dst: Path) -> None:
    """Copy the file a link points to, under the link's name: an installer may not keep links."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src.resolve(), dst)
    shutil.copymode(src.resolve(), dst)


def bundle_ffmpeg(platform: str, dest: Path) -> dict[str, str]:
    """Copy the binaries, the shared libraries (each under its soname) and the licence."""
    builds = ft.load_manifest(TOOLS_DIR / "ffmpeg.toml")
    build = builds["default"]
    pbuild = build.platforms[platform]
    root = ft.install(build, pbuild, CACHE) / pbuild.root
    out = dest / "ffmpeg"
    for tool in (pbuild.ffmpeg, pbuild.ffprobe):
        _copy_file(root / tool, out / tool)
    if platform == "windows-x64":
        for dll in sorted((root / pbuild.bin_dir).glob("*.dll")):
            _copy_file(dll, out / pbuild.bin_dir / dll.name)
    else:
        for library in sorted((root / "lib").glob("lib*.so.*")):
            # The binaries load the soname (libavcodec.so.63), not the full version.
            if library.name.split(".so.", 1)[1].isdigit():
                _copy_file(library, out / "lib" / library.name)
    _copy_file(root / "LICENSE.txt", out / "LICENSE.txt")
    return {"ffmpeg": build.version}


def _libva_build_script(libva: Libva) -> str:
    """The build, for ``sh`` in the build image; ``$WORK`` holds the source archive."""
    driverdir = ":".join(libva.driver_dirs)
    return f"""set -eu
cd "$WORK"
tar xjf {libva.source.file_name}
cd {libva.root}
meson setup build --prefix=/opt/libva --libdir=lib --sysconfdir=/etc --buildtype=release \\
  -Ddriverdir={driverdir} -Dwith_x11=no -Dwith_glx=no -Dwith_wayland=no
ninja -C build
DESTDIR="$WORK/stage" ninja -C build install
"""


_BUILD_DEPENDENCIES = "meson ninja-build pkg-config gcc libc6-dev libdrm-dev bzip2"


def _run(argv: Sequence[str], env: Mapping[str, str] | None = None) -> None:
    _log(" ".join(argv))
    try:
        subprocess.run(argv, check=True, env=None if env is None else {**os.environ, **env})
    except (OSError, subprocess.CalledProcessError) as e:
        raise BundleError(f"{argv[0]} failed: {e}") from e


def build_libva(libva: Libva, work: Path, *, docker: bool) -> Path:
    """Build libva in ``work`` and return the folder with the installed ``lib``."""
    shutil.copyfile(fetch(libva.source, CACHE / "libva"), work / libva.source.file_name)
    (work / "build.sh").write_text(_libva_build_script(libva), encoding="utf-8")
    if docker:
        inner = (
            "apt-get update >/dev/null && DEBIAN_FRONTEND=noninteractive apt-get install -y "
            f"--no-install-recommends {_BUILD_DEPENDENCIES} >/dev/null && sh /work/build.sh; "
            'status=$?; chown -R "$OWNER" /work; exit $status'
        )
        owner = "0:0"
        if sys.platform != "win32":
            owner = f"{os.getuid()}:{os.getgid()}"
        _run(
            ["docker", "run", "--rm", "-e", "WORK=/work", "-e", f"OWNER={owner}",
             "-v", f"{work}:/work", libva.build_image, "sh", "-c", inner]
        )  # fmt: skip
    else:
        _run(["sh", str(work / "build.sh")], env={"WORK": str(work)})
    return work / "stage" / "opt" / "libva"


def bundle_libva(libva: Libva, ffmpeg_dir: Path, *, docker: bool) -> dict[str, str]:
    out = ffmpeg_dir / LIBVA_DIR
    with tempfile.TemporaryDirectory(prefix="libva-") as tmp:
        installed = build_libva(libva, Path(tmp), docker=docker)
        for name in libva.libraries:
            library = installed / "lib" / name
            if not library.exists():
                raise BundleError(f"the libva build has no {name}")
            _copy_file(library, out / name)
        shutil.copyfile(Path(tmp) / libva.root / libva.license_file, out / libva.license_file)
    return {"libva": libva.version}


def bundle_mkvtoolnix(mkv: Mkvtoolnix, dest: Path) -> dict[str, str]:
    archive = fetch(mkv.archive, CACHE / "mkvtoolnix")
    out = dest / "mkvtoolnix"
    out.mkdir(parents=True)
    with zipfile.ZipFile(archive) as z:
        for member, name in mkv.files.items():
            try:
                data = z.read(member)
            except KeyError as e:
                raise BundleError(f"{archive.name} has no {member}") from e
            (out / name).write_bytes(data)
    return {"mkvtoolnix": mkv.version}


def bundle(
    platform: str,
    dest: Path,
    *,
    libva_build: str = "docker",
) -> dict[str, str]:
    """Replace ``dest`` with the tools for ``platform``; return the versions bundled."""
    keep = dest / KEEP_NAME
    others = [p for p in dest.iterdir() if p != keep] if dest.is_dir() else []
    if dest.exists() and not (dest / MARKER_NAME).is_file() and others:
        raise BundleError(f"refusing to replace {dest}: it was not made by bundle-tools")
    dest.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".tmp-tools-", dir=dest.parent))
    try:
        versions = bundle_ffmpeg(platform, staging)
        if platform == "linux-x64":
            if libva_build != "skip":
                docker = libva_build == "docker"
                versions |= bundle_libva(load_libva(), staging / "ffmpeg", docker=docker)
        else:
            versions |= bundle_mkvtoolnix(load_mkvtoolnix(platform), staging)
        marker = {"platform": platform, "versions": versions}
        (staging / MARKER_NAME).write_text(json.dumps(marker, indent=1), encoding="utf-8")
        if keep.is_file():
            shutil.copyfile(keep, staging / KEEP_NAME)
        if dest.exists():
            shutil.rmtree(dest)
        staging.replace(dest)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return versions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--platform", default="auto", choices=("auto", *ft.PLATFORMS))
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    parser.add_argument(
        "--libva-build",
        choices=("docker", "native", "skip"),
        default="docker",
        help="Linux: build libva in its build image with Docker (default), here (inside that "
        "image, with the build tools installed), or not at all",
    )
    args = parser.parse_args(argv)
    try:
        platform = ft.detect_platform() if args.platform == "auto" else args.platform
        versions = bundle(platform, Path(args.dest).resolve(), libva_build=args.libva_build)
    except BundleError as e:
        _log(f"error: {e}")
        return 1
    _log(f"{args.dest}: " + ", ".join(f"{k} {v}" for k, v in versions.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
