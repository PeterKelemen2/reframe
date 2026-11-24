"""Write THIRD_PARTY_NOTICES for a desktop package or the Docker image: the licences of the
Python packages that the frozen sidecar (or the image) ships, of the frontend's production
packages and of the desktop app's Rust crates, of the data in Reframe's language tables, the
libraries that the tools layout builds (libva on Linux) with their licences and source links,
and the sources release with the SHA-256 and the licence texts of each of its archives that the
package's platform bundles. No package conveys FFmpeg: Reframe downloads it. Every part must
come with a licence text: a part without one stops the run.

Run it after the sidecar build and the tools layout, in the project environment with
pip-licenses next to it; ``npx`` and ``cargo about`` must be on ``PATH``. The Linux packages'
notices read the Ubuntu packages' ``/usr/share/doc/*/copyright``, so they run in the build image::

    uv run --with pip-licenses==5.5.5 python scripts/third-party-notices.py --platform linux-x64 \\
        --sources-url URL --sources-sums SHA256SUMS --sources-manifest manifest.json \\
        --sources-texts licence-texts.json

The Windows installers and the Docker image bundle nothing from the sources release, so their
notices take no ``--sources-*`` options. For the image the interpreter must be the one the image
installs (``uv run --python``).
"""

from __future__ import annotations

import argparse
import dataclasses
import fnmatch
import importlib.metadata
import json
import os
import platform as host_platform
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import tomllib
import urllib.parse
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
TAURI_DIR = REPO_ROOT / "desktop" / "src-tauri"
DEFAULT_OUT = TAURI_DIR / "resources" / "notices" / "THIRD_PARTY_NOTICES"
DEFAULT_SIDECAR = TAURI_DIR / "resources" / "sidecar"
DEFAULT_TOOLS = TAURI_DIR / "resources" / "tools"
TOOL_MANIFESTS = REPO_ROOT / "tools"
#: Licence texts of bundled packages that ship without one, and of sources whose licence is only
#: in their files' headers.
LICENCE_TEXTS = TOOL_MANIFESTS / "licence-texts.toml"
FRONTEND = REPO_ROOT / "frontend"
#: The sources release's licence texts (sources-fetch.py writes it next to the archives).
TEXTS = "licence-texts.json"
DOC_ROOT = Path("/usr/share/doc")
#: A licence that a Debian copyright file names (it ends a sentence: the dot is not the name's).
_COMMON_LICENCE = re.compile(
    r"/usr/share/common-licenses/([A-Za-z0-9][A-Za-z0-9.+_-]*[A-Za-z0-9+])"
)

LICENSE_CHECKER = "license-checker@25.0.1"
RUST_TARGETS = {"linux-x64": "x86_64-unknown-linux-gnu", "windows-x64": "x86_64-pc-windows-msvc"}
#: The Docker image's platforms and the machine of each.
DOCKER_PLATFORMS = {"docker-linux-x64": "x86_64", "docker-linux-arm64": "aarch64"}
DOCKERFILE = REPO_ROOT / "docker" / "Dockerfile"
#: The packages the image's ``uv sync`` installs, as ``uv export`` options.
DOCKER_EXPORT = ("--frozen", "--no-dev", "--all-packages", "--extra", "cli")
_DOCKER_PYTHON_RE = re.compile(r"uv python install (\S+)")
_SUMS_LINE_RE = re.compile(r"^([0-9a-f]{64}) [ *]([A-Za-z0-9._-]+)$")
# Reframe's own distributions: their licence is not a third party's.
OWN_DISTRIBUTIONS = frozenset({"reframe", "reframe-server"})
# The bootloader and its runtime modules are inside every frozen executable.
ALWAYS_SHIPPED = ("pyinstaller",)
# A new licence among the crates fails the run until someone has read it and added it here.
ACCEPTED_RUST_LICENSES = (
    "0BSD",
    "Apache-2.0",
    "BSD-3-Clause",
    "GPL-3.0-or-later",
    "ISC",
    "MIT",
    "MPL-2.0",
    "Unicode-3.0",
    "Zlib",
)
_LICENSE_FILE_RE = re.compile(r"^(licen[cs]e|copying|notice)", re.IGNORECASE)
_RULE = "=" * 78
_LINE = "-" * 78


class NoticesError(Exception):
    """A source of licence data is missing or incomplete; no file is written."""


@dataclass(frozen=True)
class Entry:
    """One licensed component and the text that goes with it."""

    name: str
    version: str
    license: str
    url: str = ""
    text: str = ""


def _run(argv: Sequence[str], *, cwd: Path | None = None) -> str:
    executable = shutil.which(argv[0])
    if executable is None:
        raise NoticesError(f"{argv[0]} is not on PATH")
    # The tools write UTF-8 (licence texts have names in every script); Windows' default
    # would decode with the ANSI code page and fail.
    result = subprocess.run(
        [executable, *argv[1:]], cwd=cwd, capture_output=True, encoding="utf-8", check=False
    )
    if result.returncode != 0:
        raise NoticesError(f"{' '.join(argv[:3])} failed: {result.stderr.strip()[-2000:]}")
    return result.stdout


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _executables(sidecar: Path) -> list[Path]:
    suffix = ".exe" if (sidecar / "reframe-server.exe").exists() else ""
    found = [sidecar / f"{name}{suffix}" for name in ("reframe-server", "reframe")]
    missing = [str(path) for path in found if not path.is_file()]
    if missing:
        raise NoticesError(f"no frozen sidecar: {', '.join(missing)} missing (build it first)")
    return found


def shipped_top_level_names(sidecar: Path) -> set[str]:
    """The top-level module and folder names in the frozen executables' archives and in
    ``_internal/``."""
    from PyInstaller.archive.readers import CArchiveReader  # type: ignore[import-untyped]

    names: set[str] = set()
    for executable in _executables(sidecar):
        archive = CArchiveReader(str(executable))
        for entry, info in archive.toc.items():
            if info[-1] == "z":
                modules = archive.open_embedded_archive(entry).toc
                names |= {module.split(".")[0] for module in modules}
    internal = sidecar / "_internal"
    if internal.is_dir():
        names |= {path.name.split(".")[0] for path in internal.iterdir()}
    return names


def shipped_distributions(
    top_level_names: Iterable[str], packages: Mapping[str, Sequence[str]]
) -> list[str]:
    """The distributions that provide ``top_level_names`` (standard library modules provide
    none), without Reframe's own, plus PyInstaller."""
    found = {_canonical(name) for name in ALWAYS_SHIPPED}
    for top in top_level_names:
        found |= {_canonical(dist) for dist in packages.get(top, ())}
    return sorted(found - OWN_DISTRIBUTIONS)


def python_entries(distributions: Sequence[str]) -> list[Entry]:
    try:
        import piplicenses  # type: ignore[import-not-found]  # noqa: F401
    except ImportError as e:
        raise NoticesError("pip-licenses is missing: run with uv run --with pip-licenses") from e
    output = _run(
        [
            sys.executable,
            "-m",
            "piplicenses",
            "--format=json",
            "--from=mixed",
            "--with-urls",
            "--with-license-file",
            "--no-license-path",
            "--with-notice-file",
            "--with-system",
            "--packages",
            *distributions,
        ]
    )
    return with_texts(parse_pip_licenses(json.loads(output), distributions), "pypi")


def parse_pip_licenses(rows: Sequence[Mapping[str, str]], wanted: Sequence[str]) -> list[Entry]:
    """Entries for pip-licenses' JSON rows. A wanted distribution without a row is an error:
    pip-licenses skips names it cannot find."""
    entries: dict[str, Entry] = {}
    for row in rows:
        texts = [row.get("LicenseText", ""), row.get("NoticeText", "")]
        text = "\n\n".join(t.strip() for t in texts if t and t.strip() != "UNKNOWN")
        entries[_canonical(row["Name"])] = Entry(
            name=row["Name"],
            version=row["Version"],
            license=row["License"],
            url=row.get("URL", "") if row.get("URL") != "UNKNOWN" else "",
            text=text,
        )
    missing = sorted(set(wanted) - set(entries))
    if missing:
        raise NoticesError(f"pip-licenses has no data for {', '.join(missing)}")
    return [entries[name] for name in sorted(entries)]


def python_interpreter_entry() -> Entry:
    """CPython itself, whose library the sidecar ships."""
    base = Path(sys.base_prefix)
    major_minor = f"{sys.version_info.major}.{sys.version_info.minor}"
    for candidate in (base / "lib" / f"python{major_minor}" / "LICENSE.txt", base / "LICENSE.txt"):
        if candidate.is_file():
            return Entry(
                name="CPython",
                version=host_platform.python_version(),
                license="PSF-2.0 (and the licences of the libraries below in the text)",
                url="https://www.python.org/",
                text=candidate.read_text(encoding="utf-8", errors="replace"),
            )
    raise NoticesError(f"no LICENSE.txt in the Python installation {base}")


def parse_uv_export(text: str, machine: str) -> list[str]:
    """The distributions of ``uv export`` requirement lines whose markers hold on Linux on
    ``machine``, without Reframe's own."""
    from packaging.markers import Marker

    environment = {
        "sys_platform": "linux",
        "platform_system": "Linux",
        "os_name": "posix",
        "platform_machine": machine,
    }
    found = set()
    for line in text.splitlines():
        requirement, _, marker = line.partition(";")
        name, sep, _version = requirement.strip().partition("==")
        if not sep or line.startswith((" ", "#", "-")):
            continue
        if marker.strip() and not Marker(marker.strip()).evaluate(environment):
            continue
        found.add(_canonical(name))
    return sorted(found - OWN_DISTRIBUTIONS)


def docker_distributions(machine: str) -> list[str]:
    """The third-party distributions that the image's ``uv sync`` installs on ``machine``."""
    export = _run(
        [
            "uv",
            "export",
            *DOCKER_EXPORT,
            "--no-hashes",
            "--no-emit-workspace",
            "--no-header",
            "--no-annotate",
        ],
        cwd=REPO_ROOT,
    )
    return parse_uv_export(export, machine)


def docker_python_version(dockerfile: Path = DOCKERFILE) -> str:
    """The CPython version that the image installs."""
    found = _DOCKER_PYTHON_RE.findall(dockerfile.read_text(encoding="utf-8"))
    if not found:
        raise NoticesError(f"{dockerfile} installs no Python with uv")
    return str(found[-1])


def read_sources_sums(path: Path) -> list[tuple[str, str]]:
    """``(sha256, archive)`` of each line of a ``SHA256SUMS`` file (``sha256sum`` format).

    :raises NoticesError: the file is empty or has a line in another format.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        raise NoticesError(f"cannot read {path}: {e}") from e
    sums = []
    for line in lines:
        match = _SUMS_LINE_RE.match(line)
        if match is None:
            raise NoticesError(f"{path}: not a SHA256SUMS line: {line!r}")
        sums.append((match[1], match[2]))
    if not sums:
        raise NoticesError(f"{path} lists no archive")
    return sums


def read_sources_manifest(path: Path) -> list[Mapping[str, Any]]:
    """The entries of a ``sources-manifest.py`` manifest.

    :raises NoticesError: the file is not such a manifest.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise NoticesError(f"cannot read the source manifest {path}: {e}") from e
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries or data.get("schema_version") != 1:
        raise NoticesError(f"{path}: not a source manifest with entries")
    for entry in entries:
        if not (
            isinstance(entry, dict)
            and isinstance(entry.get("archive"), str)
            and isinstance(entry.get("platforms"), list)
        ):
            raise NoticesError(f"{path}: an entry without an archive or platforms: {entry}")
    return entries


def bundles(entry: Mapping[str, Any], platform: str) -> bool:
    """Whether a package of ``platform`` bundles the source of a manifest entry. The FFmpeg
    build's sources (``git``, ``btbn-stage``) go to none: no package conveys FFmpeg.

    :raises NoticesError: the entry is of a kind this script does not know.
    """
    kind = entry.get("kind")
    if kind in ("git", "btbn-stage"):
        return False
    if kind in ("url", "repository", "ubuntu-source"):
        return platform in entry["platforms"]
    raise NoticesError(f"{entry['archive']}: unknown source kind {kind!r}")


def platform_sources(
    entries: Sequence[Mapping[str, Any]], sums: Sequence[tuple[str, str]], platform: str
) -> list[tuple[str, str]]:
    """``(sha256, archive)`` of each archive in ``sums`` that ``platform`` bundles.

    :raises NoticesError: ``sums`` has an archive of no entry, a bundled entry has no sum, or
        ``platform`` bundles nothing (its notices need no sources release).
    """
    archives = {str(entry["archive"]) for entry in entries} | {TEXTS}
    unknown = sorted(name for _, name in sums if name not in archives)
    if unknown:
        raise NoticesError(f"the sums list archives of no manifest entry: {', '.join(unknown)}")
    checksums = {name: sha256 for sha256, name in sums if name != TEXTS}
    wanted = sorted(str(entry["archive"]) for entry in entries if bundles(entry, platform))
    if not wanted:
        raise NoticesError(
            f"the source manifest has no source of {platform}: its notices take no --sources-*"
        )
    missing = [name for name in wanted if name not in checksums]
    if missing:
        raise NoticesError(f"the sums have no line for {', '.join(missing)}")
    return [(checksums[name], name) for name in wanted]


def read_sources_texts(path: Path) -> dict[str, list[tuple[str, str]]]:
    """The licence files of each archive, from the sources release's ``licence-texts.json``.

    :raises NoticesError: the file is not one.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema_version") != 1:
            raise ValueError("schema_version is not 1")
        return {
            str(archive): [(str(item["path"]), str(item["text"])) for item in items]
            for archive, items in data["archives"].items()
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        raise NoticesError(f"{path}: not the licence texts of a sources release ({e})") from e


def _copyright_texts(entry: Mapping[str, Any], doc_root: Path) -> list[tuple[str, str]]:
    """The ``copyright`` file of each binary package of an Ubuntu source package, as dpkg
    installed it: the text the binary package ships under, and the full text of each common
    licence it names (``/usr/share/common-licenses/LGPL``) instead of carrying it."""

    def read(path: Path) -> tuple[str, str]:
        try:
            return path.as_posix(), path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            raise NoticesError(
                f"{entry['archive']}: cannot read {path} ({e.strerror or e}): the Linux "
                "packages' notices run in their build image, which has these packages"
            ) from e

    texts = [
        read(doc_root / str(package).partition(":")[0] / "copyright")
        for package in entry.get("binary_packages", [])
    ]
    common = doc_root.parent / "common-licenses"

    def common_licence(name: str) -> Path:
        # Some copyright files add ".0" to the file's name (Ubuntu 22.04's pango: GPL-2.0).
        short = common / name.removesuffix(".0")
        return short if not (common / name).exists() and short.exists() else common / name

    named = dict.fromkeys(
        common_licence(name) for _, text in texts for name in _COMMON_LICENCE.findall(text)
    )
    return texts + [read(path) for path in named]


def source_text_entries(
    entries: Sequence[Mapping[str, Any]],
    texts: Mapping[str, Sequence[tuple[str, str]]],
    platform: str,
    doc_root: Path = DOC_ROOT,
) -> list[Entry]:
    """One entry per archive that ``platform`` bundles, with its licence files' texts (or the
    committed text of a source whose licence is only in its files' headers); a text seen
    before is named, not repeated.

    :raises NoticesError: an archive has no licence text.
    """
    committed = read_licence_texts().get("sources", [])
    first: dict[str, str] = {}
    found = []
    for entry in sorted(entries, key=lambda entry: str(entry["archive"])):
        if not bundles(entry, platform):
            continue
        archive = str(entry["archive"])
        if entry["kind"] == "ubuntu-source":
            files = _copyright_texts(entry, doc_root)
        else:
            files = (
                list(texts.get(archive, ()))
                or [
                    (LICENCE_TEXTS.name, text)
                    for pattern, text in committed
                    if fnmatch.fnmatchcase(archive, pattern)
                ][:1]
            )
        if not files:
            raise NoticesError(
                f"the licence texts have none for {archive}, and {LICENCE_TEXTS.name} "
                "[sources] neither"
            )
        parts = []
        for path, text in files:
            text = text.strip()
            where = f"{path} in {archive}"
            if text in first:
                parts.append(f"{path}: the same text as {first[text]}.")
            else:
                first[text] = where
                parts.append(f"{path}:\n\n{text}")
        found.append(
            Entry(
                name=str(entry.get("component") or archive),
                version="",
                license=str(entry.get("license", "")) or "see the texts",
                url="",
                text=f"Source archive: {archive}\n\n" + "\n\n".join(parts),
            )
        )
    return found


def sources_text(url: str, sums: Sequence[tuple[str, str]]) -> str:
    lines = [
        "The source code of the third-party parts under the GPL or LGPL that this package",
        "bundles is in this sources release:",
        "",
        f"  {url}",
        "",
        "It holds the sources of every Reframe package and a manifest of them. This",
        "package's parts are these archives, with the SHA-256 of each (their licence",
        "texts are in the last section):",
        "",
    ]
    return "\n".join(lines + [f"  {sha256}  {name}" for sha256, name in sums])


def javascript_entries(frontend: Path) -> list[Entry]:
    output = _run(
        [
            "npx",
            "--yes",
            LICENSE_CHECKER,
            "--production",
            "--json",
            "--excludePrivatePackages",
            "--start",
            str(frontend),
        ]
    )
    return with_texts(parse_license_checker(json.loads(output)), "npm")


def parse_license_checker(packages: Mapping[str, Mapping[str, Any]]) -> list[Entry]:
    """Entries for license-checker's JSON. Its ``licenseFile`` is sometimes the README, which is
    not a licence text, so only a file named like a licence is read."""
    entries = []
    for key, info in sorted(packages.items()):
        name, _, version = key.rpartition("@")
        licenses = info.get("licenses", "UNKNOWN")
        if isinstance(licenses, list):
            licenses = " AND ".join(licenses)
        text = ""
        license_file = info.get("licenseFile")
        if license_file and _LICENSE_FILE_RE.match(Path(license_file).name):
            text = Path(license_file).read_text(encoding="utf-8", errors="replace")
        entries.append(
            Entry(
                name=name,
                version=version,
                license=str(licenses),
                url=str(info.get("repository", "")),
                text=text,
            )
        )
    return entries


def read_licence_texts(path: Path = LICENCE_TEXTS) -> dict[str, list[tuple[str, str]]]:
    """``[registry."name"]`` tables of ``tools/licence-texts.toml``: ``(name pattern, text)`` by
    registry (``npm``, ``pypi``, ``sources`` for archive names, and ``data``)."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return {
        registry: [(str(name), str(table["text"])) for name, table in sorted(packages.items())]
        for registry, packages in data.items()
        if isinstance(packages, dict)
    }


def data_entries(path: Path = LICENCE_TEXTS) -> list[Entry]:
    """The ``[data."name"]`` tables of ``tools/licence-texts.toml``: the sources of the language
    tables in ``reframe/definitions/data``, which every package ships.

    :raises NoticesError: there is none, or one lacks its licence or text.
    """
    tables = tomllib.loads(path.read_text(encoding="utf-8")).get("data", {})
    entries = []
    for name, table in tables.items():
        if not str(table.get("license", "")).strip() or not str(table.get("text", "")).strip():
            raise NoticesError(f"{path.name}: data.{name} needs its license and text")
        entries.append(
            Entry(
                name=name,
                version=str(table.get("version", "")),
                license=str(table["license"]),
                url=str(table.get("url", "")),
                text=str(table["text"]),
            )
        )
    if not entries:
        raise NoticesError(f"{path.name} has no [data] tables: the language tables need them")
    return entries


def with_texts(entries: Sequence[Entry], registry: str) -> list[Entry]:
    """``entries``, each without a licence text given the committed one of its package.

    :raises NoticesError: a package has none: its licence could not be shipped.
    """
    known = read_licence_texts().get(registry, [])
    done, missing = [], []
    for entry in entries:
        if not entry.text.strip():
            text = next((t for name, t in known if fnmatch.fnmatchcase(entry.name, name)), "")
            if not text:
                missing.append(f"{entry.name} {entry.version}")
            entry = dataclasses.replace(entry, text=text)
        done.append(entry)
    if missing:
        raise NoticesError(
            f"no licence text for the {registry} packages {', '.join(missing)}: find each one's "
            f"licence upstream and add it to {LICENCE_TEXTS.relative_to(REPO_ROOT).as_posix()}"
        )
    return done


def _about_config(target: str) -> str:
    accepted = ", ".join(json.dumps(license) for license in ACCEPTED_RUST_LICENSES)
    return (
        f"accepted = [{accepted}]\n"
        f"targets = [{json.dumps(target)}]\n"
        "ignore-build-dependencies = true\n"
        "ignore-dev-dependencies = true\n"
    )


def rust_entries(manifest: Path, platform: str) -> list[Entry]:
    with tempfile.TemporaryDirectory() as folder:
        config = Path(folder) / "about.toml"
        config.write_text(_about_config(RUST_TARGETS[platform]), encoding="utf-8")
        output = _run(
            [
                "cargo",
                "about",
                "generate",
                "--format",
                "json",
                "--locked",
                "--manifest-path",
                str(manifest),
                "--config",
                str(config),
            ]
        )
    return parse_cargo_about(json.loads(output))


def parse_cargo_about(report: Mapping[str, Any]) -> list[Entry]:
    """One entry per licence text, with the crates that use it, without Reframe's own crate."""
    entries = []
    for license in report["licenses"]:
        crates = sorted(
            {
                f"{used['crate']['name']} {used['crate']['version']}"
                for used in license["used_by"]
                if used["crate"]["name"] != "reframe-desktop"
            }
        )
        if crates:
            used_by = textwrap.fill("Used by: " + ", ".join(crates), width=78)
            entries.append(
                Entry(
                    name=license["name"],
                    version="",
                    license=license["id"],
                    text=f"{used_by}\n\n{license['text']}",
                )
            )
    return entries


def _strings(table: Mapping[str, Any], skip: Iterable[str] = ()) -> list[tuple[str, str]]:
    return [
        (key, str(value))
        for key, value in table.items()
        if isinstance(value, str | int) and not isinstance(value, bool) and key not in skip
    ]


def _pin_entry(
    name: str,
    pin: Mapping[str, Any],
    archive: Mapping[str, Any],
    manifest: Path,
    license_file: Path,
    tools: Path,
    platform: str,
) -> Entry:
    lines = [
        str(pin.get("description", "")),
        "",
        f"Pinned in {manifest.relative_to(manifest.parent.parent).as_posix()}:",
    ]
    lines += [f"  {key}: {value}" for key, value in _strings(pin, skip=("description",))]
    lines += [f"  {platform}.{key}: {value}" for key, value in _strings(archive)]
    lines += [
        "",
        f"The licence text is below and in tools/{license_file.relative_to(tools).as_posix()}.",
        "",
        license_file.read_text(encoding="utf-8", errors="replace"),
    ]
    return Entry(
        name=name,
        version=str(pin.get("version", "")),
        license=str(pin.get("license", "see below")),
        url=str(pin.get("release_url", "")),
        text="\n".join(lines),
    )


def library_entries(tools: Path, manifests: Path, platform: str) -> list[Entry]:
    """One entry per library pinned for ``platform`` that the tools layout builds into
    ``tools/<name>/``, with every field of its pin and its ``LICENSE-<name>.txt``.

    :raises NoticesError: a pinned library has no licence file there, or ``tools`` holds a
        folder that no pin names (an FFmpeg of an older layout would ship without notices).
    """
    entries = []
    pinned: set[str] = set()
    for manifest in sorted(manifests.glob("*.toml")):
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        for name, pin in data.get("libraries", {}).items():
            archive = pin.get("platforms", {}).get(platform)
            if not isinstance(archive, dict):
                continue
            pinned.add(name)
            licence = tools / name / f"LICENSE-{name}.txt"
            if not licence.is_file():
                raise NoticesError(
                    f"{manifest}: {name} is pinned for {platform}, but there is no {licence}: "
                    f"run scripts/bundle-tools.py --platform {platform}"
                )
            entries.append(_pin_entry(name, pin, archive, manifest, licence, tools, platform))
    folders = sorted(p.name for p in tools.iterdir() if p.is_dir()) if tools.is_dir() else []
    for folder in folders:
        if folder not in pinned:
            raise NoticesError(
                f"{tools / folder} is bundled but no manifest in {manifests} pins it for {platform}"
            )
    return entries


def static_entries(manifests: Path, platform: str) -> list[Entry]:
    """One entry per static build pinned for ``platform`` in ``static-builds.toml``, with every
    library it links and that library's licence and source archive."""
    data = tomllib.loads((manifests / "static-builds.toml").read_text(encoding="utf-8"))
    entries = []
    for pin in data.get("binaries", {}).values():
        if platform not in pin.get("platforms", ()):
            continue
        lines = [
            f"Built from {pin['source_repository']} at commit {pin['source_commit']}.",
            "It contains these libraries, linked statically (licence; source archive):",
            "",
        ]
        for part in pin["parts"]:
            archive = part.get("archive") or Path(urllib.parse.urlsplit(part["url"]).path).name
            lines.append(f"  {part['name']} {part['version']} ({part['license']}); {archive}")
        lines += ["", "Each source archive in the sources release holds its part's licence text."]
        entries.append(
            Entry(
                name=str(pin["description"]),
                version="",
                license=str(pin["license"]),
                url=str(pin.get("release_url", "")),
                text="\n".join(lines),
            )
        )
    return entries


def render(
    sections: Sequence[tuple[str, Sequence[Entry]]],
    *,
    version: str,
    platform: str,
    preface: Sequence[str] = (),
) -> str:
    """The notices file; each ``preface`` paragraph follows the introduction."""
    out = [
        f"Third-party notices for Reframe {version} ({platform})",
        "",
        "This package contains the third-party software listed below. Each part keeps its own",
        "licence; the licence texts follow each entry.",
    ]
    for paragraph in preface:
        out += ["", paragraph]
    for title, entries in sections:
        out += ["", _RULE, title, _RULE]
        for entry in entries:
            heading = f"{entry.name} {entry.version}".strip()
            out += ["", _LINE, heading, _LINE]
            out.append(f"Licence: {entry.license}")
            if entry.url:
                out.append(f"URL: {entry.url}")
            if entry.text:
                out += ["", entry.text.strip()]
    return "\n".join(out) + "\n"


LANGUAGE_DATA = "Language data (in Reframe's language tables)"


def desktop_sections(platform: str, tools: Path) -> list[tuple[str, list[Entry]]]:
    names = shipped_top_level_names(DEFAULT_SIDECAR)
    distributions = shipped_distributions(names, importlib.metadata.packages_distributions())
    return [
        ("Bundled libraries", library_entries(tools, TOOL_MANIFESTS, platform)),
        ("Statically linked libraries", static_entries(TOOL_MANIFESTS, platform)),
        ("Python (the sidecar's interpreter)", [python_interpreter_entry()]),
        ("Python packages (the sidecar)", python_entries(distributions)),
        (LANGUAGE_DATA, data_entries()),
        ("JavaScript packages (the user interface)", javascript_entries(FRONTEND)),
        ("Rust crates (the desktop app)", rust_entries(TAURI_DIR / "Cargo.toml", platform)),
    ]


def docker_sections(platform: str) -> list[tuple[str, list[Entry]]]:
    """The image's Python and its packages, and the frontend's packages. The Python entry
    describes this interpreter, so it must be the image's version."""
    machine = DOCKER_PLATFORMS[platform]
    wanted = docker_python_version()
    if host_platform.python_version() != wanted:
        raise NoticesError(
            f"the image ships Python {wanted}: run this with it (uv run --python {wanted})"
        )
    return [
        ("Python (the image's interpreter)", [python_interpreter_entry()]),
        ("Python packages (the server)", python_entries(docker_distributions(machine))),
        (LANGUAGE_DATA, data_entries()),
        ("JavaScript packages (the user interface)", javascript_entries(FRONTEND)),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--platform", required=True, choices=sorted([*RUST_TARGETS, *DOCKER_PLATFORMS])
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--tools", type=Path, default=DEFAULT_TOOLS, help="the desktop packages' tools layout"
    )
    parser.add_argument("--sources-url", help="the sources release that the notices name")
    parser.add_argument("--sources-sums", type=Path, help="that release's SHA256SUMS")
    parser.add_argument("--sources-manifest", type=Path, help="that release's manifest.json")
    parser.add_argument("--sources-texts", type=Path, help=f"that release's {TEXTS}")
    parser.add_argument("--doc-root", type=Path, default=DOC_ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    given = [args.sources_url, args.sources_sums, args.sources_manifest, args.sources_texts]
    if None in given and any(value is not None for value in given):
        parser.error(
            "--sources-url, --sources-sums, --sources-manifest and --sources-texts go together"
        )
    # The packages carry the desktop app's version, not the core's.
    config = json.loads((TAURI_DIR / "tauri.conf.json").read_text(encoding="utf-8"))

    try:
        preface = []
        texts_section: list[tuple[str, list[Entry]]] = []
        if args.sources_url is not None:
            manifest = read_sources_manifest(args.sources_manifest)
            sources = platform_sources(
                manifest, read_sources_sums(args.sources_sums), args.platform
            )
            preface.append(sources_text(args.sources_url, sources))
            texts = read_sources_texts(args.sources_texts)
            texts_section.append(
                (
                    "Licence texts of the parts in the sources release",
                    source_text_entries(manifest, texts, args.platform, args.doc_root),
                )
            )
        if args.platform in DOCKER_PLATFORMS:
            preface.append(
                "The Debian packages installed in the image are listed, with their source\n"
                "packages, versions and source links, in a file next to this one. Their\n"
                "copyright files are at the end of this file."
            )
            sections = docker_sections(args.platform)
        else:
            sections = desktop_sections(args.platform, args.tools)
        sections = [*sections, *texts_section]
    except NoticesError as e:
        sys.stderr.write(f"third-party-notices: {e}\n")
        return 1
    text = render(sections, version=config["version"], platform=args.platform, preface=preface)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    partial = args.out.with_name(args.out.name + ".part")
    partial.write_text(text, encoding="utf-8")
    os.replace(partial, args.out)
    counts = "; ".join(f"{title}: {len(entries)}" for title, entries in sections)
    print(f"wrote {args.out} (entries: {counts})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
