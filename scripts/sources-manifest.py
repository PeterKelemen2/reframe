"""Write the source manifest of the third-party code that Reframe's packages bundle, and print the
tag of its sources release: ``sources-`` and the first 12 hex digits of the manifest's SHA-256.

The manifest names the libva source, the tree and the linked libraries of each static build in
``tools/static-builds.toml``, and the Ubuntu source package of each distro package the Linux
packages carry. No package conveys FFmpeg, so its sources are not in it. The same pins give the
same bytes, so the tag changes only when a source changes::

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
import sys
import tomllib
import urllib.parse
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TOOLS = REPO_ROOT / "tools"
SCHEMA_VERSION = 1
TAG_PREFIX = "sources-"
#: The package platform whose AppImage carries the distro libraries.
APPIMAGE_PLATFORM = "linux-x64"

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ASSET_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


class ManifestError(Exception):
    """A pin is missing or not usable; nothing is written."""


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


def _url_entry(
    name: str, component: str, license: str, url: str, sha256: str, archive: str = ""
) -> dict[str, Any]:
    if not _HEX64.match(sha256):
        raise ManifestError(f"{name}: the SHA-256 of {url} is not pinned")
    archive = archive or posixpath.basename(urllib.parse.urlsplit(url).path)
    return {
        "kind": "url",
        "name": asset_name(archive),
        "component": component,
        "license": license,
        "url": url,
        "sha256": sha256,
    }


def library_entries(tools: Path) -> list[dict[str, Any]]:
    """The source tarball of each library that ``tools/bundled-tools.toml`` pins."""
    path = tools / "bundled-tools.toml"
    data = _load_toml(path)
    entries: dict[str, dict[str, Any]] = {}
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


def static_entries(tools: Path) -> list[dict[str, Any]]:
    """For each binary of ``tools/static-builds.toml``: the tree it was built from and the source
    of each library it links, for the package platforms that ship it."""
    path = tools / "static-builds.toml"
    entries = []
    for name, pin in sorted(_load_toml(path).get("binaries", {}).items()):
        where = f"{path.name}: binaries.{name}"
        platforms = pin.get("platforms")
        if not isinstance(platforms, list) or not platforms:
            raise ManifestError(f"{where}.platforms: missing")
        repository = _str(pin, "source_repository", where)
        commit = _str(pin, "source_commit", where)
        if not _HEX40.match(commit):
            raise ManifestError(f"{where}.source_commit: expected a full commit hash")
        entries.append(
            {
                "kind": "repository",
                "name": asset_name(f"{posixpath.basename(repository)}-{commit[:12]}"),
                "component": _str(pin, "description", where),
                "license": _str(pin, "license", where),
                "repository": repository,
                "commit": commit,
                "platforms": sorted(platforms),
            }
        )
        parts = pin.get("parts")
        if not isinstance(parts, list) or not parts:
            raise ManifestError(f"{where}.parts: none")
        for number, part in enumerate(parts):
            at = f"{where}.parts[{number}]"
            label = f"{_str(part, 'name', at)} {_str(part, 'version', at)}"
            entry = _url_entry(
                label,
                f"{label}, linked into {name}",
                _str(part, "license", at),
                _str(part, "url", at),
                str(part.get("sha256", "")),
                str(part.get("archive", "")),
            )
            entries.append(entry | {"platforms": sorted(platforms)})
    return entries


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


def _same_source(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    keys = (set(a) | set(b)) - {"platforms", "component"}
    return a["kind"] in ("url", "repository") and all(a.get(k) == b.get(k) for k in keys)


def manifest(entries: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """The manifest document: the entries by name, each with the file name of its archive. A
    tarball or tree that two pins name is one entry with the platforms of both.

    :raises ManifestError: two different sources would have the same archive name.
    """
    named: dict[str, dict[str, Any]] = {}
    for entry in entries:
        archive = _archive_name(entry)
        entry = entry | {"archive": archive}
        other = named.get(archive)
        if other is None:
            named[archive] = entry
        elif _same_source(other, entry):
            other["platforms"] = sorted({*other["platforms"], *entry["platforms"]})
        else:
            raise ManifestError(f"two sources would both be the archive {archive}")
    return {"schema_version": SCHEMA_VERSION, "entries": [named[k] for k in sorted(named)]}


def encode(document: Mapping[str, Any]) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode()


def tag(data: bytes) -> str:
    return TAG_PREFIX + hashlib.sha256(data).hexdigest()[:12]


def build(tools: Path, appimage_libs: Path | None) -> dict[str, Any]:
    entries = library_entries(tools) + static_entries(tools)
    if appimage_libs is not None:
        try:
            libs = json.loads(appimage_libs.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise ManifestError(f"cannot read {appimage_libs}: {e}") from e
        entries += appimage_entries(libs)
    return manifest(entries)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--appimage-libs",
        type=Path,
        help="the AppImage's distro packages, from scripts/appimage-libs.py resolve",
    )
    parser.add_argument("--tools-dir", type=Path, default=DEFAULT_TOOLS)
    args = parser.parse_args(argv)
    try:
        data = encode(build(args.tools_dir, args.appimage_libs))
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
