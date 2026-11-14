"""Write the source manifest of the third-party code that Reframe's packages bundle, and print the
tag of its sources release: ``sources-`` and the first 12 hex digits of the manifest's SHA-256.

The manifest names, for every pinned FFmpeg platform, the FFmpeg commit, the BtbN build scripts'
commit and each dependency download those scripts make for that platform (found by running the
scripts' own ``generate.sh``), the MKVToolNix and MediaInfo source tarballs, the libva source,
and the Ubuntu source package of each distro package the AppImage carries. The same pins give
the same bytes, so the tag changes only when a source changes. ``bash`` and ``git`` must be on
``PATH``::

    uv run python scripts/sources-manifest.py --out sources/manifest.json \\
        --appimage-libs appimage-libs.json
"""

from __future__ import annotations

import argparse
import hashlib
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
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TOOLS = REPO_ROOT / "tools"
SCHEMA_VERSION = 1
TAG_PREFIX = "sources-"
#: The FFmpeg platform whose packages carry the AppImage's distro libraries.
APPIMAGE_PLATFORM = "linux-x64"
GIT_TIMEOUT = 600
GENERATE_TIMEOUT = 300

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ASSET_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")
_MOUNT = re.compile(r"--mount=src=([^,\s]+),dst=(\S+)")
_DOWNLOAD = re.compile(r"^\.cache/downloads/(?P<stage>.+)_(?P<hash>[0-9a-f]{64})\.tar\.xz$")
# Prints the stage's download commands as the build hashes them, then its SCRIPT_* variables,
# each NUL-terminated.
_EVALUATE = r"""
set -e
source util/vars.sh "$1" "$2" "$3" >/dev/null
source util/dl_functions.sh
source "$4"
commands="$(ffbuild_dockerdl)"
printf '%s\0' "$commands"
for name in $(compgen -v SCRIPT_); do printf '%s\0%s\0' "$name" "${!name}"; done
"""


class ManifestError(Exception):
    """A pin is missing or the build scripts disagree with it; nothing is written."""


@dataclass(frozen=True, slots=True)
class Stage:
    """One dependency download of the BtbN build (its ``.cache/downloads`` archive)."""

    stage: str
    script: str
    download_hash: str
    commands: str
    variables: Mapping[str, str]
    build_files: Sequence[str] = ()
    """Other files of the build scripts that the stage mounts (its patches)."""


def asset_name(text: str) -> str:
    """``text`` with only the characters that GitHub keeps in a release asset's name."""
    return _ASSET_UNSAFE.sub("_", text).strip(".")


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise ManifestError(f"cannot read {path}: {e}") from e


def _str(table: Mapping[str, Any], key: str, where: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value:
        raise ManifestError(f"{where}.{key}: missing")
    return value


def _run(argv: Sequence[str], *, cwd: Path | None = None, timeout: float) -> str:
    executable = shutil.which(argv[0])
    if executable is None:
        raise ManifestError(f"{argv[0]} is not on PATH")
    try:
        result = subprocess.run(
            [executable, *argv[1:]],
            cwd=cwd,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise ManifestError(f"{' '.join(argv[:3])} took longer than {timeout} s") from e
    if result.returncode != 0:
        raise ManifestError(f"{' '.join(argv[:3])} failed: {result.stderr.strip()[-2000:]}")
    return result.stdout


def git_checkout(repository: str, commit: str, dest: Path) -> None:
    """Check out ``commit`` of ``repository`` into the new folder ``dest`` (history depth 1)."""
    dest.mkdir(parents=True)
    _run(["git", "init", "-q", str(dest)], timeout=GIT_TIMEOUT)
    _run(
        ["git", "-C", str(dest), "fetch", "-q", "--depth=1", repository, commit],
        timeout=GIT_TIMEOUT,
    )
    _run(["git", "-C", str(dest), "checkout", "-q", "FETCH_HEAD"], timeout=GIT_TIMEOUT)


@dataclass(frozen=True, slots=True)
class FfmpegPin:
    license: str
    source_repository: str
    source_commit: str
    build_scripts_repository: str
    build_scripts_commit: str
    variant: str
    addin: str
    """The BtbN addin of the release branch (``9.0`` for ``release/9.0``)."""
    targets: Mapping[str, str]
    """The BtbN target of each platform's archive."""


def ffmpeg_pin(tools: Path) -> FfmpegPin:
    """The shipped build of ``tools/ffmpeg.toml``. Each platform's BtbN target and the branch
    come from its archive's name, which BtbN's build writes from both."""
    path = tools / "ffmpeg.toml"
    where = f"{path.name}: builds.default"
    build = _load_toml(path).get("builds", {}).get("default")
    if not isinstance(build, dict):
        raise ManifestError(f"{where}: missing")
    variant = _str(build, "variant", where)
    branch = _str(build, "source_branch", where)
    addin = branch.removeprefix("release/")
    commits = {key: _str(build, key, where) for key in ("source_commit", "build_scripts_commit")}
    for key, value in commits.items():
        if not _HEX40.match(value):
            raise ManifestError(f"{where}.{key}: expected a full commit hash, got {value!r}")
    name = re.compile(rf"-(?P<target>[a-z0-9]+)-{re.escape(variant)}-(?P<addin>[0-9.]+)\.")
    targets = {}
    for platform, archive in sorted(build.get("platforms", {}).items()):
        url = _str(archive, "url", f"{where}.platforms.{platform}")
        found = name.search(posixpath.basename(urllib.parse.urlsplit(url).path))
        if found is None or found["addin"] != addin:
            raise ManifestError(
                f"{where}.platforms.{platform}: {url} is not a {variant} build of {branch}"
            )
        targets[platform] = found["target"]
    if not targets:
        raise ManifestError(f"{where}.platforms: none")
    return FfmpegPin(
        license=_str(build, "license", where),
        source_repository=_str(build, "source_repository", where),
        source_commit=commits["source_commit"],
        build_scripts_repository=_str(build, "build_scripts_repository", where),
        build_scripts_commit=commits["build_scripts_commit"],
        variant=variant,
        addin=addin,
        targets=targets,
    )


def _evaluate(tree: Path, script: str, target: str, variant: str, addin: str) -> Stage:
    output = _run(
        ["bash", "-c", _EVALUATE, "evaluate", target, variant, addin, script],
        cwd=tree,
        timeout=GENERATE_TIMEOUT,
    )
    fields = output.split("\0")
    if len(fields) < 2 or len(fields) % 2 != 0:
        raise ManifestError(f"{script}: unexpected output of its download function")
    variables = dict(zip(fields[1:-1:2], fields[2::2], strict=True))
    return Stage(stage="", script=script, download_hash="", commands=fields[0], variables=variables)


def btbn_stages(tree: Path, target: str, variant: str, addin: str) -> list[Stage]:
    """Every dependency download that BtbN's ``generate.sh`` gives the build of ``target``.

    :raises ManifestError: a stage's download commands do not hash to the archive name the
        build uses (this script would then name other sources than the build's).
    """
    with tempfile.TemporaryDirectory(prefix="sources-btbn-") as folder:
        work = Path(folder) / "tree"
        shutil.copytree(tree, work, ignore=shutil.ignore_patterns(".git"), symlinks=True)
        _run(["bash", "generate.sh", target, variant, addin], cwd=work, timeout=GENERATE_TIMEOUT)
        dockerfile = (work / "Dockerfile").read_text(encoding="utf-8")
        stages = []
        for line in dockerfile.splitlines():
            if not line.startswith("RUN ") or " run_stage " not in line:
                continue
            mounts = {dst: src for src, dst in _MOUNT.findall(line)}
            script = mounts.pop("/stage.sh", None)
            cache = mounts.pop("/cache.tar.xz", None)
            if cache is None:
                continue
            download = _DOWNLOAD.match(cache)
            if script is None or download is None:
                raise ManifestError(f"generate.sh {target}: cannot read the stage {line!r}")
            evaluated = _evaluate(work, script, target, variant, addin)
            digest = hashlib.sha256((evaluated.commands + "\n").encode()).hexdigest()
            if digest != download["hash"]:
                raise ManifestError(
                    f"{script}: its download commands hash to {digest}, the {target} "
                    f"build uses {download['hash']}"
                )
            stages.append(
                Stage(
                    stage=download["stage"],
                    script=script,
                    download_hash=download["hash"],
                    commands=evaluated.commands,
                    variables=evaluated.variables,
                    build_files=sorted(mounts.values()),
                )
            )
    if not stages:
        raise ManifestError(f"generate.sh {target} {variant} {addin}: no dependency download")
    return stages


def ffmpeg_entries(pin: FfmpegPin, tree: Path) -> list[dict[str, Any]]:
    platforms = sorted(pin.targets)
    entries: list[dict[str, Any]] = [
        {
            "kind": "git",
            "name": f"ffmpeg-{pin.source_commit[:12]}",
            "component": "FFmpeg",
            "license": pin.license,
            "repository": pin.source_repository,
            "commit": pin.source_commit,
            "platforms": platforms,
        },
        {
            "kind": "git",
            "name": f"ffmpeg-builds-{pin.build_scripts_commit[:12]}",
            "component": "FFmpeg build scripts (BtbN/FFmpeg-Builds)",
            "repository": pin.build_scripts_repository,
            "commit": pin.build_scripts_commit,
            "platforms": platforms,
        },
    ]
    stages: dict[tuple[str, str], tuple[Stage, set[str]]] = {}
    for platform, target in sorted(pin.targets.items()):
        for stage in btbn_stages(tree, target, pin.variant, pin.addin):
            key = (stage.stage, stage.download_hash)
            stages.setdefault(key, (stage, set()))[1].add(platform)
    for stage, used_by in stages.values():
        entries.append(
            {
                "kind": "btbn-stage",
                "name": f"btbn-{stage.stage}-{stage.download_hash[:12]}",
                "component": f"FFmpeg dependency {stage.stage}",
                "build_scripts_repository": pin.build_scripts_repository,
                "build_scripts_commit": pin.build_scripts_commit,
                "script": stage.script,
                "build_files": list(stage.build_files),
                "download_hash": stage.download_hash,
                "commands": stage.commands,
                "variables": dict(stage.variables),
                "platforms": sorted(used_by),
            }
        )
    return entries


def _url_entry(name: str, component: str, license: str, url: str, sha256: str) -> dict[str, Any]:
    if not _HEX64.match(sha256):
        raise ManifestError(f"{name}: the SHA-256 of {url} is not pinned")
    archive = posixpath.basename(urllib.parse.urlsplit(url).path)
    return {
        "kind": "url",
        "name": asset_name(archive),
        "component": component,
        "license": license,
        "url": url,
        "sha256": sha256,
    }


def tool_entries(tools: Path) -> list[dict[str, Any]]:
    """The source tarball of each tool and library that ``tools/bundled-tools.toml`` pins."""
    path = tools / "bundled-tools.toml"
    data = _load_toml(path)
    entries: dict[str, dict[str, Any]] = {}
    for name, pin in sorted(data.get("tools", {}).items()):
        where = f"{path.name}: tools.{name}"
        platforms = sorted(pin.get("platforms", {}))
        if not platforms:
            continue
        entry = _url_entry(
            name,
            str(pin.get("description", name)),
            _str(pin, "license", where),
            _str(pin, "source_url", where),
            str(pin.get("source_sha256", "")),
        )
        entries[entry["name"]] = entry | {"platforms": platforms}
    for name, pin in sorted(data.get("libraries", {}).items()):
        where = f"{path.name}: libraries.{name}"
        for platform, archive in sorted(pin.get("platforms", {}).items()):
            entry = _url_entry(
                name,
                str(pin.get("description", name)),
                _str(pin, "license", where),
                _str(archive, "url", f"{where}.platforms.{platform}"),
                _str(archive, "sha256", f"{where}.platforms.{platform}"),
            )
            used_by = entries.get(entry["name"], {}).get("platforms", [])
            entries[entry["name"]] = entry | {"platforms": sorted({*used_by, platform})}
    return list(entries.values())


def appimage_entries(libs: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One Ubuntu source package per source and version in the ``appimage-libs.py`` list."""
    distribution = libs.get("distribution", {})
    if distribution.get("id") != "ubuntu":
        raise ManifestError(f"AppImage libraries: only Ubuntu is supported, not {distribution}")
    sources: dict[tuple[str, str], set[str]] = {}
    for row in libs.get("packages", []):
        key = (str(row["source"]), str(row["source_version"]))
        sources.setdefault(key, set()).add(str(row["package"]))
    if not sources:
        raise ManifestError("AppImage libraries: the list is empty")
    return [
        {
            "kind": "ubuntu-source",
            "name": asset_name(f"ubuntu-{source}_{version}"),
            "component": f"Ubuntu {distribution.get('version_id', '')} source package {source}",
            "source": source,
            "version": version,
            "binary_packages": sorted(binaries),
            "platforms": [APPIMAGE_PLATFORM],
        }
        for (source, version), binaries in sorted(sources.items())
    ]


def _archive_name(entry: Mapping[str, Any]) -> str:
    if entry["kind"] == "url":
        return str(entry["name"])
    if entry["kind"] == "ubuntu-source":
        return f"{entry['name']}.tar"
    return f"{entry['name']}.tar.xz"


def manifest(entries: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """The manifest document: the entries by name, each with the file name of its archive.

    :raises ManifestError: two entries would have the same archive name.
    """
    named: dict[str, dict[str, Any]] = {}
    for entry in entries:
        archive = _archive_name(entry)
        if archive in named:
            raise ManifestError(f"two sources would both be the archive {archive}")
        named[archive] = entry | {"archive": archive}
    return {"schema_version": SCHEMA_VERSION, "entries": [named[k] for k in sorted(named)]}


def encode(document: Mapping[str, Any]) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode()


def tag(data: bytes) -> str:
    return TAG_PREFIX + hashlib.sha256(data).hexdigest()[:12]


def build(tools: Path, build_scripts: Path | None, appimage_libs: Path | None) -> dict[str, Any]:
    pin = ffmpeg_pin(tools)
    entries = tool_entries(tools)
    if appimage_libs is not None:
        try:
            libs = json.loads(appimage_libs.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise ManifestError(f"cannot read {appimage_libs}: {e}") from e
        entries += appimage_entries(libs)
    if build_scripts is not None:
        return manifest([*ffmpeg_entries(pin, build_scripts), *entries])
    with tempfile.TemporaryDirectory(prefix="sources-manifest-") as folder:
        tree = Path(folder) / "ffmpeg-builds"
        git_checkout(pin.build_scripts_repository, pin.build_scripts_commit, tree)
        return manifest([*ffmpeg_entries(pin, tree), *entries])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--appimage-libs",
        type=Path,
        help="the AppImage's distro packages, from scripts/appimage-libs.py resolve",
    )
    parser.add_argument("--tools-dir", type=Path, default=DEFAULT_TOOLS)
    parser.add_argument(
        "--build-scripts",
        type=Path,
        help="a checkout of the pinned BtbN build scripts (default: fetched)",
    )
    args = parser.parse_args(argv)
    try:
        data = encode(build(args.tools_dir, args.build_scripts, args.appimage_libs))
    except ManifestError as e:
        sys.stderr.write(f"sources-manifest: {e}\n")
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    partial = args.out.with_name(args.out.name + ".part")
    partial.write_bytes(data)
    os.replace(partial, args.out)
    print(tag(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
