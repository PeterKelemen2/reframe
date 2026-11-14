"""Fetch one archive for each entry of a source manifest (``sources-manifest.py``) into a folder,
check each against its pin, write the licence files of the archives to ``licence-texts.json``
(the packages' notices carry them), and write the folder's ``SHA256SUMS``.

An archive appears under its final name only after its check passed, so a rerun skips it. Git
sources and trees are fetched by commit; a BtbN dependency runs the build scripts' own download
commands (with their ``git-mini-clone`` and ``retry-tool``) after checking that they are the
ones the build used; tarballs must have their pinned SHA-256; an Ubuntu source package is its
``.dsc`` from Launchpad and every file the ``.dsc`` lists, with the checksums it gives. Git and
SVN metadata stay out of the archives. An Ubuntu source package's licence is read from the build
image's ``/usr/share/doc`` instead. Linux only: ``git``, GNU ``tar``, ``xz``, ``bash`` and the
tools the download commands call (:data:`STAGE_TOOLS`) must be on ``PATH``::

    uv run python scripts/sources-fetch.py --manifest sources/manifest.json --out sources/files
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import urllib.parse
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from reframe.tools import fetch
from reframe.tools.runner import CancelToken

SUMS = "SHA256SUMS"
TEXTS = "licence-texts.json"
LICENCE_TEXTS = Path(__file__).resolve().parent.parent / "tools" / "licence-texts.toml"
WORK_PREFIX = ".work-"
#: What the BtbN download commands call besides git.
STAGE_TOOLS = ("svn", "cargo", "meson", "python3", "autoreconf", "automake", "libtoolize")
LAUNCHPAD_FILES = "https://launchpad.net/ubuntu/+archive/primary/+sourcefiles/{source}/{version}/"
MAX_TARBALL = 4 << 30
MAX_DSC = 1 << 20
#: A licence file larger than this is not read: no licence text is that long.
MAX_TEXT = 1 << 20
STAGE_TIMEOUT = 2 * 3600
GIT_TIMEOUT = 1800
#: Attempts of a clone or a stage's commands: dozens of clones in a row meet network errors.
ATTEMPTS = 3
RETRY_PAUSE = 30.0

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_REV = re.compile(r"^[0-9]+$")
# The way BtbN's download.sh runs a stage's commands.
_STAGE_SHELL = 'set -xe -o pipefail\nshopt -s dotglob\neval "set -e; $REFRAME_STAGE_COMMANDS"\n'
_LICENCE_FILE = re.compile(
    r"^(?:(?:licen[cs]es?|copying|copyright|notices?|unlicense|patents)(?:[-_.].*)?"
    r"|[al]?gpl[-_.]?v?[0-9.]*(?:\.txt|\.md)?)$",
    re.IGNORECASE,
)
# REUSE's LICENSES/, and folders such as mingw-w64's COPYING.MinGW-w64-runtime/.
_LICENCE_DIR = re.compile(r"^(?:licen[cs]es|(?:copying|licen[cs]e)[-_.].+)$", re.IGNORECASE)
# Folders of vendored components (cargo vendor, git submodules, meson subprojects): each one's
# licence goes with the code it puts into the build.
_VENDOR_DIR = re.compile(
    r"^(?:vendor|vendored|third[-_]?party|3rd[-_]?party|external|extern|subprojects|deps)$",
    re.IGNORECASE,
)
# Code and build files named like a licence (license.c, COPYING.in) are not one.
_NOT_TEXT = re.compile(
    r"\.(?:c|h|cc|cpp|hpp|py|js|ts|rs|go|java|rb|pl|pm|sh|m4|in|am|ac|cmake|json|xml|ya?ml|toml"
    r"|pc|mk|png|svg|ico|o|a|so|dll|exe|gz|xz|bz2|zip|sig|asc)$",
    re.IGNORECASE,
)


class SourcesError(Exception):
    """A source cannot be fetched or does not match its pin."""


def _log(message: str) -> None:
    sys.stderr.write(f"sources-fetch: {message}\n")
    sys.stderr.flush()


def _run(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float = GIT_TIMEOUT,
    capture: bool = True,
) -> str:
    executable = shutil.which(argv[0], path=(env or os.environ).get("PATH"))
    if executable is None:
        raise SourcesError(f"{argv[0]} is not on PATH")
    try:
        result = subprocess.run(
            [executable, *argv[1:]],
            cwd=cwd,
            env=env,
            # A long command's output goes to the log (file descriptor 2) as it comes.
            stdout=subprocess.PIPE if capture else 2,
            stderr=subprocess.PIPE if capture else None,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise SourcesError(f"{' '.join(argv[:3])} took longer than {timeout} s") from e
    if result.returncode != 0:
        detail = (result.stderr or "").strip()[-2000:]
        raise SourcesError(f"{' '.join(argv[:3])} failed (exit {result.returncode}) {detail}")
    return result.stdout or ""


def git_checkout(repository: str, commit: str, dest: Path) -> None:
    """Check out ``commit`` of ``repository`` into the new folder ``dest`` (history depth 1).
    Git checks each object against its hash, so the tree is the commit's."""
    dest.mkdir(parents=True)
    _run(["git", "init", "-q", str(dest)])
    _run(["git", "-C", str(dest), "fetch", "-q", "--depth=1", repository, commit])
    _run(["git", "-C", str(dest), "checkout", "-q", "FETCH_HEAD"])


def pack(folder: Path, archive: Path) -> None:
    """``folder`` as a ``.tar.xz`` with the folder's name as its top folder, without VCS data,
    in name order with fixed owners and times (the same tree gives the same bytes)."""
    _run(
        [
            "tar",
            "--sort=name",
            "--owner=0",
            "--group=0",
            "--numeric-owner",
            "--mtime=@0",
            "--exclude=.git",
            "--exclude=.svn",
            "-I",
            "xz -T0",
            "-cf",
            str(archive),
            "-C",
            str(folder.parent),
            folder.name,
        ],
        timeout=STAGE_TIMEOUT,
    )


def _checkouts(tree: Path, marker: str) -> list[Path]:
    return sorted(path.parent for path in tree.rglob(marker))


def check_stage_pins(tree: Path, variables: Mapping[str, str]) -> list[str]:
    """The checkouts in ``tree`` that match a pin of the stage, as ``url@revision`` lines.

    :raises SourcesError: a checkout of a pinned repository is at none of its pinned commits
        or revisions (a stage may pin one repository more than once).
    """
    pins: dict[str, set[str]] = {}
    for name, value in variables.items():
        for prefix in ("SCRIPT_REPO", "SCRIPT_MIRROR"):
            if name.startswith(prefix):
                suffix = name.removeprefix(prefix)
                ref = variables.get(f"SCRIPT_COMMIT{suffix}") or variables.get(
                    f"SCRIPT_REV{suffix}"
                )
                if ref and (_HEX40.match(ref) or _REV.match(ref)):
                    pins.setdefault(value.removesuffix(".git").rstrip("/"), set()).add(ref)
    found = []
    checkouts = [(path, "git") for path in _checkouts(tree, ".git")]
    checkouts += [(path, "svn") for path in _checkouts(tree, ".svn")]
    for path, vcs in checkouts:
        if vcs == "git":
            url = _run(["git", "-C", str(path), "config", "--get", "remote.origin.url"], timeout=60)
            head = _run(["git", "-C", str(path), "rev-parse", "HEAD"], timeout=60)
        else:
            url = _run(["svn", "info", "--show-item", "url", str(path)], timeout=60)
            head = _run(["svn", "info", "--show-item", "revision", str(path)], timeout=60)
        url, head = url.strip().removesuffix(".git").rstrip("/"), head.strip()
        if url in pins:
            if head not in pins[url]:
                pinned = ", ".join(sorted(pins[url]))
                raise SourcesError(f"{path.name}: {url} is at {head}, the pin is {pinned}")
            found.append(f"{url}@{head}")
    return found


def _stage_hash(commands: str) -> str:
    return hashlib.sha256((commands + "\n").encode()).hexdigest()


def stage_helpers(build_scripts: Path, into: Path) -> Path:
    """A folder with BtbN's download helpers as commands, as its build image installs them."""
    into.mkdir(parents=True, exist_ok=True)
    for name in ("git-mini-clone", "retry-tool"):
        source = build_scripts / "images" / "base" / f"{name}.sh"
        if not source.is_file():
            raise SourcesError(f"{source} is missing: not a checkout of the BtbN build scripts")
        target = into / name
        shutil.copyfile(source, target)
        target.chmod(target.stat().st_mode | stat.S_IXUSR)
    return into


def fetch_stage(entry: Mapping[str, Any], helpers: Path, work: Path) -> None:
    """Run the stage's download commands in ``work/<name>`` and check the pins."""
    commands = str(entry["commands"])
    if _stage_hash(commands) != entry["download_hash"]:
        raise SourcesError(f"{entry['name']}: the commands do not hash to {entry['download_hash']}")
    folder = work / entry["name"]
    env = {
        **os.environ,
        "PATH": f"{helpers}{os.pathsep}{os.environ.get('PATH', '')}",
        "REFRAME_STAGE_COMMANDS": commands,
    }

    def run() -> None:
        folder.mkdir(parents=True)
        _run(
            ["bash", "-c", _STAGE_SHELL], cwd=folder, env=env, timeout=STAGE_TIMEOUT, capture=False
        )

    _with_retries(run, folder)
    for line in check_stage_pins(folder, entry.get("variables", {})):
        _log(f"{entry['name']}: checked {line}")


def _with_retries(action: Callable[[], None], folder: Path) -> None:
    """``action`` until it succeeds, from an empty ``folder`` each time."""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            action()
            return
        except SourcesError as e:
            shutil.rmtree(folder, ignore_errors=True)
            if attempt == ATTEMPTS:
                raise
            _log(f"attempt {attempt} failed, retrying in {RETRY_PAUSE:.0f} s: {e}")
            time.sleep(RETRY_PAUSE)


def fetch_git(entry: Mapping[str, Any], work: Path) -> None:
    folder = work / entry["name"]
    _with_retries(
        lambda: git_checkout(str(entry["repository"]), str(entry["commit"]), folder), folder
    )


def fetch_url(entry: Mapping[str, Any], dest: Path) -> None:
    _log(f"downloading {entry['url']}")
    fetch.download(str(entry["url"]), dest, size=MAX_TARBALL, cancel=CancelToken())
    actual = fetch.sha256_file(dest)
    if actual != entry["sha256"]:
        dest.unlink()
        raise SourcesError(f"{entry['url']}: the SHA-256 is {actual}, the pin is {entry['sha256']}")


def parse_dsc(text: str) -> dict[str, str]:
    """The fields of a Debian source control file (a signed one too); continuation lines are
    joined with newlines."""
    if text.startswith("-----BEGIN PGP SIGNED MESSAGE-----"):
        text = text.split("\n\n", 1)[1].split("-----BEGIN PGP SIGNATURE-----", 1)[0]
    fields: dict[str, str] = {}
    key = ""
    for line in text.splitlines():
        if line.startswith((" ", "\t")) and key:
            fields[key] += "\n" + line.strip()
        elif ":" in line:
            key, _, value = line.partition(":")
            fields[key] = value.strip()
    return fields


def dsc_files(fields: Mapping[str, str]) -> list[tuple[str, int, str]]:
    """``(sha256, size, name)`` of each file the ``.dsc`` lists."""
    files = []
    for line in fields.get("Checksums-Sha256", "").splitlines():
        parts = line.split()
        if len(parts) == 3:
            files.append((parts[0], int(parts[1]), parts[2]))
    if not files or any("/" in name or name.startswith(".") for _, _, name in files):
        raise SourcesError("the .dsc lists no file, or a file outside its folder")
    return files


def ubuntu_dsc_name(source: str, version: str) -> str:
    return f"{source}_{version.split(':', 1)[-1]}.dsc"


def fetch_ubuntu(entry: Mapping[str, Any], work: Path) -> Path:
    """The ``.dsc`` and its files from Launchpad in ``work/<source>_<version>/``."""
    source, version = str(entry["source"]), str(entry["version"])
    base = LAUNCHPAD_FILES.format(
        source=urllib.parse.quote(source, safe=""), version=urllib.parse.quote(version, safe=":")
    )
    folder = work / ubuntu_dsc_name(source, version).removesuffix(".dsc")
    folder.mkdir(parents=True)
    dsc_name = ubuntu_dsc_name(source, version)
    dsc = folder / dsc_name
    fetch.download(base + urllib.parse.quote(dsc_name), dsc, size=MAX_DSC, cancel=CancelToken())
    fields = parse_dsc(dsc.read_text(encoding="utf-8", errors="replace"))
    if (fields.get("Source"), fields.get("Version")) != (source, version):
        raise SourcesError(
            f"{dsc_name}: it is {fields.get('Source')} {fields.get('Version')}, "
            f"the pin is {source} {version}"
        )
    for sha256, size, name in dsc_files(fields):
        path = folder / name
        fetch.download(base + urllib.parse.quote(name), path, size=size, cancel=CancelToken())
        try:
            fetch.verify_file(path, sha256, size)
        except fetch.FetchError as e:
            raise SourcesError(f"{source} {version}: {e}") from e
    return folder


def _tar_files(folder: Path, archive: Path) -> None:
    with tarfile.open(archive, "w", format=tarfile.PAX_FORMAT) as tar:
        for path in sorted(folder.iterdir()):
            info = tar.gettarinfo(path, f"{folder.name}/{path.name}")
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            with path.open("rb") as f:
                tar.addfile(info, f)


def fetch_entry(entry: Mapping[str, Any], out: Path, helpers: Path | None) -> None:
    """Fetch and check one entry into ``out/<archive>`` through a work folder."""
    archive = out / str(entry["archive"])
    partial = archive.with_name(archive.name + ".part")
    work = out / f"{WORK_PREFIX}{entry['name']}"
    shutil.rmtree(work, ignore_errors=True)
    partial.unlink(missing_ok=True)
    work.mkdir()
    try:
        kind = entry["kind"]
        if kind == "url":
            fetch_url(entry, partial)
        elif kind == "ubuntu-source":
            _tar_files(fetch_ubuntu(entry, work), partial)
        elif kind in ("git", "repository"):
            fetch_git(entry, work)
            pack(work / entry["name"], partial)
        elif kind == "btbn-stage":
            if helpers is None:
                raise SourcesError("no BtbN build scripts for the download helpers")
            fetch_stage(entry, helpers, work)
            pack(work / entry["name"], partial)
        else:
            raise SourcesError(f"{entry['name']}: unknown kind {kind!r}")
        os.replace(partial, archive)
    except fetch.FetchError as e:
        raise SourcesError(str(e)) from e
    finally:
        partial.unlink(missing_ok=True)
        shutil.rmtree(work, ignore_errors=True)


def is_fetched(entry: Mapping[str, Any], out: Path) -> bool:
    archive = out / str(entry["archive"])
    if not archive.is_file():
        return False
    return entry["kind"] != "url" or fetch.sha256_file(archive) == str(entry["sha256"])


def load_manifest(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise SourcesError(f"cannot read the manifest {path}: {e}") from e
    if data.get("schema_version") != 1 or not data.get("entries"):
        raise SourcesError(f"{path}: not a source manifest with entries")
    entries: list[dict[str, Any]] = data["entries"]
    names = [str(entry.get("archive", "")) for entry in entries]
    bad = [
        n for n in names if not n or Path(n).name != n or n.startswith(".") or n in (SUMS, TEXTS)
    ]
    if bad or len(set(names)) != len(names):
        raise SourcesError(f"{path}: archive names must be unique plain file names: {bad}")
    return entries


def check_out_dir(out: Path, entries: Iterable[Mapping[str, Any]]) -> None:
    """:raises SourcesError: ``out`` holds a file that is not one of the manifest's archives."""
    wanted = {str(entry["archive"]) for entry in entries} | {SUMS, TEXTS}
    if not out.is_dir():
        return
    stray = sorted(
        p.name for p in out.iterdir() if p.name not in wanted and not p.name.startswith(WORK_PREFIX)
    )
    if stray:
        raise SourcesError(f"{out} holds files of no manifest entry: {', '.join(stray)}")


def _is_licence_path(parts: Sequence[str], *, vendored: bool = True) -> bool:
    """A licence file at the top of ``parts`` (a path below one folder), a file in a licence
    folder there, or the same one level into a folder of vendored components."""
    if not parts or _NOT_TEXT.search(parts[-1]):
        return False
    if len(parts) == 1:
        return bool(_LICENCE_FILE.match(parts[0]))
    if len(parts) == 2 and _LICENCE_DIR.match(parts[0]):
        return True
    return (
        vendored
        and len(parts) > 2
        and bool(_VENDOR_DIR.match(parts[0]))
        and _is_licence_path(parts[2:], vendored=False)
    )


def select_licence_files(paths: Iterable[str]) -> list[str]:
    """The licence files among ``paths`` (``/``-separated, below the archive's top folder): those
    at the top, else those one folder down (a stage that checks its sources out into
    sub-folders)."""
    top: list[str] = []
    below: list[str] = []
    for path in paths:
        parts = path.split("/")
        if _is_licence_path(parts):
            top.append(path)
        elif len(parts) > 1 and _is_licence_path(parts[1:]):
            below.append(path)
    return sorted(top or below)


def _decode(data: bytes) -> str:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def archive_licence_texts(archive: Path) -> dict[str, str]:
    """The licence files of a source archive by their path below its top folder (one pass, so a
    ``.tar.xz`` is read once). A link to a licence file gets that file's text.

    :raises SourcesError: the archive cannot be read.
    """
    texts: dict[str, str] = {}
    links: dict[str, str] = {}
    tops: set[str] = set()
    try:
        with tarfile.open(archive, "r|*") as tar:
            for member in tar:
                name = member.name.removeprefix("./").strip("/")
                top, _, below = name.partition("/")
                tops.add(top)
                if not below or not select_licence_files([below]):
                    continue
                if member.issym() or member.islnk():
                    target = member.linkname.removeprefix("./")
                    if member.issym():
                        target = os.path.normpath(os.path.join(os.path.dirname(name), target))
                    links[below] = target.partition("/")[2]
                elif member.isfile() and member.size <= MAX_TEXT:
                    file = tar.extractfile(member)
                    data = file.read() if file is not None else b""
                    if b"\0" not in data:
                        texts[below] = _decode(data)
    except (OSError, tarfile.TarError, EOFError) as e:
        raise SourcesError(f"{archive.name}: cannot read it: {e}") from e
    if len(tops) != 1:
        raise SourcesError(f"{archive.name}: not one top folder ({len(tops)} at the top)")
    for path, target in links.items():
        if target in texts:
            texts[path] = texts[target]
    return {path: texts[path] for path in select_licence_files(texts)}


def committed_texts(path: Path) -> list[str]:
    """The archive name patterns that ``tools/licence-texts.toml`` gives a text for (a source
    whose licence is only in its files' headers)."""
    sources = tomllib.loads(path.read_text(encoding="utf-8")).get("sources", {})
    return [str(pattern) for pattern in sources]


def write_texts(out: Path, entries: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """``out/licence-texts.json``: the licence files of each archive but the Ubuntu source
    packages.

    :raises SourcesError: an archive has no licence file and ``tools/licence-texts.toml`` no
        text for it: its part's notices would lack it.
    """
    archives: dict[str, list[dict[str, str]]] = {}
    for entry in sorted(entries, key=lambda entry: str(entry["archive"])):
        if entry["kind"] == "ubuntu-source":
            continue
        name = str(entry["archive"])
        texts = archive_licence_texts(out / name)
        archives[name] = [{"path": path, "text": text} for path, text in texts.items()]
    patterns = committed_texts(LICENCE_TEXTS)
    missing = sorted(
        name
        for name, texts in archives.items()
        if not texts and not any(fnmatch.fnmatchcase(name, p) for p in patterns)
    )
    if missing:
        raise SourcesError(
            f"no licence file found at the top of {', '.join(missing)}: look in the archive, "
            "then extend the rule of select_licence_files or add its text to "
            f"{LICENCE_TEXTS.name} [sources]"
        )
    document = {"schema_version": 1, "archives": archives}
    partial = out / f"{WORK_PREFIX}{TEXTS}"
    partial.write_text(
        json.dumps(document, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    os.replace(partial, out / TEXTS)
    return document


def write_sums(out: Path, entries: Iterable[Mapping[str, Any]]) -> str:
    names = sorted([*(str(entry["archive"]) for entry in entries), TEXTS])
    lines = [f"{fetch.sha256_file(out / name)}  {name}\n" for name in names]
    text = "".join(lines)
    partial = out / f"{SUMS}.part"
    partial.write_text(text, encoding="utf-8")
    os.replace(partial, out / SUMS)
    return text


def fetch_all(entries: Sequence[Mapping[str, Any]], out: Path) -> None:
    check_out_dir(out, entries)
    out.mkdir(parents=True, exist_ok=True)
    todo = [entry for entry in entries if not is_fetched(entry, out)]
    for entry in entries:
        if entry not in todo:
            _log(f"{entry['archive']}: already fetched and checked")
    stages = [entry for entry in todo if entry["kind"] == "btbn-stage"]
    missing = [tool for tool in ("git", "tar", "xz", "bash") if shutil.which(tool) is None]
    if stages:
        missing += [tool for tool in STAGE_TOOLS if shutil.which(tool) is None]
    if missing:
        raise SourcesError(f"not on PATH: {', '.join(missing)}")
    with tempfile.TemporaryDirectory(prefix="sources-fetch-") as folder:
        helpers = None
        if stages:
            scripts = Path(folder) / "ffmpeg-builds"
            repository = str(stages[0]["build_scripts_repository"])
            commit = str(stages[0]["build_scripts_commit"])
            _with_retries(lambda: git_checkout(repository, commit, scripts), scripts)
            helpers = stage_helpers(scripts, Path(folder) / "bin")
        for number, entry in enumerate(todo, 1):
            _log(f"[{number}/{len(todo)}] {entry['archive']}")
            fetch_entry(entry, out, helpers)
    write_texts(out, entries)
    write_sums(out, entries)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        entries = load_manifest(args.manifest)
        fetch_all(entries, args.out)
    except SourcesError as e:
        _log(str(e))
        return 1
    total = sum((args.out / str(entry["archive"])).stat().st_size for entry in entries)
    print(f"{len(entries)} archives, {total} bytes, in {args.out}; sums in {args.out / SUMS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
