"""scripts/sources-fetch.py: one checked archive per manifest entry, the rerun, SHA256SUMS."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
import sys
import tarfile
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "sources-fetch.py"

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the sources fetch runs on Linux")


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sources_fetch", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sf = _load_script()

# BtbN's helpers (images/base at the pinned commit), as the build image installs them.
GIT_MINI_CLONE = """#!/bin/bash
set -xe
REPO="$1"
REF="$2"
DEST="$3"
git init "$DEST"
git -C "$DEST" remote add origin "$REPO"

retry-tool git -C "$DEST" fetch --depth=1 origin "$REF"

git -C "$DEST" config advice.detachedHead false
git -C "$DEST" checkout FETCH_HEAD
"""
RETRY_TOOL = '#!/bin/bash\nset -xe -o pipefail\n"$@"\n'
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


@pytest.fixture(autouse=True)
def _quick(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sf, "RETRY_PAUSE", 0.0)
    monkeypatch.setattr(sf, "STAGE_TOOLS", ())
    for key, value in GIT_ENV.items():
        monkeypatch.setenv(key, value)


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _repo(path: Path, files: Mapping[str, str]) -> str:
    """A git repository at ``path`` with one commit of ``files``; the commit's hash."""
    path.mkdir(parents=True)
    _git("init", "-q", cwd=path)
    for name, text in files.items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(text)
    _git("add", "-A", cwd=path)
    _git("commit", "-q", "-m", "c", cwd=path)
    return _git("rev-parse", "HEAD", cwd=path)


def _members(archive: Path) -> list[str]:
    with tarfile.open(archive) as tar:
        return sorted(m.name for m in tar.getmembers() if m.isfile())


def _sums(out: Path) -> dict[str, str]:
    lines = (out / "SHA256SUMS").read_text().splitlines()
    return {name: sha for sha, name in (line.split("  ") for line in lines)}


def _git_entry(origin: Path, commit: str) -> dict[str, Any]:
    return {
        "kind": "git",
        "name": "ffmpeg-1234",
        "archive": "ffmpeg-1234.tar.xz",
        "repository": origin.as_uri(),
        "commit": commit,
    }


def test_a_git_source_is_the_commits_tree_without_git_data(tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    commit = _repo(origin, {"configure": "#!/bin/sh\n", ".gitignore": "*.o\n"})
    out = tmp_path / "out"

    sf.fetch_all([_git_entry(origin, commit)], out)

    archive = out / "ffmpeg-1234.tar.xz"
    assert _members(archive) == ["ffmpeg-1234/.gitignore", "ffmpeg-1234/configure"]
    assert _sums(out) == {"ffmpeg-1234.tar.xz": hashlib.sha256(archive.read_bytes()).hexdigest()}
    assert sorted(p.name for p in out.iterdir()) == ["SHA256SUMS", "ffmpeg-1234.tar.xz"]


def test_a_commit_that_cannot_be_fetched_leaves_no_archive(tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    _repo(origin, {"configure": ""})
    out = tmp_path / "out"

    with pytest.raises(sf.SourcesError):
        sf.fetch_all([_git_entry(origin, "1" * 40)], out)

    assert list(out.iterdir()) == []


def test_a_rerun_skips_the_archives_already_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    origin = tmp_path / "origin"
    entry = _git_entry(origin, _repo(origin, {"configure": ""}))
    out = tmp_path / "out"
    sf.fetch_all([entry], out)

    def refetch(*args: object) -> None:
        raise AssertionError("fetched again")

    monkeypatch.setattr(sf, "fetch_entry", refetch)
    sf.fetch_all([entry], out)

    assert "ffmpeg-1234.tar.xz" in _sums(out)


def _build_scripts(tmp_path: Path) -> str:
    """A BtbN repository with its download helpers; its URL."""
    scripts = tmp_path / "btbn"
    _repo(
        scripts,
        {"images/base/git-mini-clone.sh": GIT_MINI_CLONE, "images/base/retry-tool.sh": RETRY_TOOL},
    )
    return str(scripts.as_uri())


def _stage_entry(
    tmp_path: Path, origin: Path, commit: str, pinned: str | None = None
) -> dict[str, Any]:
    commands = f'git-mini-clone "{origin.as_uri()}" "{commit}" "."'
    return {
        "kind": "btbn-stage",
        "name": "btbn-50-x264-abcdef",
        "archive": "btbn-50-x264-abcdef.tar.xz",
        "build_scripts_repository": _build_scripts(tmp_path),
        "build_scripts_commit": "",
        "commands": commands,
        "download_hash": hashlib.sha256((commands + "\n").encode()).hexdigest(),
        "variables": {"SCRIPT_REPO": f"{origin.as_uri()}.git", "SCRIPT_COMMIT": pinned or commit},
    }


@pytest.fixture
def helper_checkout(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fake BtbN repository has one commit: check out whatever its HEAD is."""
    checkout = sf.git_checkout

    def any_commit(repository: str, commit: str, dest: Path) -> None:
        if commit:
            checkout(repository, commit, dest)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "clone", "-q", repository, str(dest)], check=True)

    monkeypatch.setattr(sf, "git_checkout", any_commit)


@pytest.mark.usefixtures("helper_checkout")
def test_a_btbn_stage_runs_its_download_commands_and_checks_the_pin(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    origin = tmp_path / "x264"
    commit = _repo(origin, {"x264.c": "int main;\n"})
    out = tmp_path / "out"

    sf.fetch_all([_stage_entry(tmp_path, origin, commit)], out)

    assert _members(out / "btbn-50-x264-abcdef.tar.xz") == ["btbn-50-x264-abcdef/x264.c"]
    assert f"checked {origin.as_uri()}@{commit}" in capsys.readouterr().err


@pytest.mark.usefixtures("helper_checkout")
def test_a_stage_may_pin_one_repository_at_several_commits(tmp_path: Path) -> None:
    origin = tmp_path / "nv-codec-headers"
    first = _repo(origin, {"sdk.h": "13\n"})
    (origin / "sdk.h").write_text("11\n")
    _git("commit", "-q", "-am", "sdk 11", cwd=origin)
    second = _git("rev-parse", "HEAD", cwd=origin)
    entry = _stage_entry(tmp_path, origin, first)
    entry["commands"] = (
        f'git-mini-clone "{origin.as_uri()}" "{first}" sdk13\n'
        f'git-mini-clone "{origin.as_uri()}" "{second}" sdk11'
    )
    entry["download_hash"] = hashlib.sha256((entry["commands"] + "\n").encode()).hexdigest()
    entry["variables"] |= {"SCRIPT_REPO2": origin.as_uri(), "SCRIPT_COMMIT2": second}
    out = tmp_path / "out"

    sf.fetch_all([entry], out)

    assert _members(out / entry["archive"]) == [
        "btbn-50-x264-abcdef/sdk11/sdk.h",
        "btbn-50-x264-abcdef/sdk13/sdk.h",
    ]


@pytest.mark.usefixtures("helper_checkout")
def test_a_stage_checkout_at_another_commit_than_its_pin_is_an_error(tmp_path: Path) -> None:
    origin = tmp_path / "x264"
    commit = _repo(origin, {"x264.c": ""})
    out = tmp_path / "out"

    with pytest.raises(sf.SourcesError, match=f"is at {commit}, the pin is {'2' * 40}"):
        sf.fetch_all([_stage_entry(tmp_path, origin, commit, pinned="2" * 40)], out)

    assert not (out / "btbn-50-x264-abcdef.tar.xz").exists()


@pytest.mark.usefixtures("helper_checkout")
def test_stage_commands_that_are_not_the_builds_are_not_run(tmp_path: Path) -> None:
    origin = tmp_path / "x264"
    entry = _stage_entry(tmp_path, origin, _repo(origin, {"x264.c": ""}))
    entry["commands"] += "\ntouch /tmp/x"

    with pytest.raises(sf.SourcesError, match="the commands do not hash to"):
        sf.fetch_all([entry], tmp_path / "out")


def _url_entry(path: Path, sha256: str) -> dict[str, Any]:
    return {
        "kind": "url",
        "name": path.name,
        "archive": path.name,
        "url": path.as_uri(),
        "sha256": sha256,
    }


def test_a_tarball_must_have_its_pinned_checksum(tmp_path: Path) -> None:
    tarball = tmp_path / "upstream" / "mkvtoolnix-103.0.tar.xz"
    tarball.parent.mkdir()
    tarball.write_bytes(b"source")
    out = tmp_path / "out"

    with pytest.raises(sf.SourcesError, match="the SHA-256 is"):
        sf.fetch_all([_url_entry(tarball, "0" * 64)], out)
    assert not (out / tarball.name).exists()

    sf.fetch_all([_url_entry(tarball, hashlib.sha256(b"source").hexdigest())], out)
    assert (out / tarball.name).read_bytes() == b"source"


def test_a_damaged_tarball_is_fetched_again(tmp_path: Path) -> None:
    tarball = tmp_path / "upstream" / "libva-2.24.1.tar.bz2"
    tarball.parent.mkdir()
    tarball.write_bytes(b"libva")
    out = tmp_path / "out"
    out.mkdir()
    (out / tarball.name).write_bytes(b"truncated")

    sf.fetch_all([_url_entry(tarball, hashlib.sha256(b"libva").hexdigest())], out)

    assert (out / tarball.name).read_bytes() == b"libva"


DSC = """-----BEGIN PGP SIGNED MESSAGE-----
Hash: SHA512

Format: 3.0 (quilt)
Source: gtk+3.0
Version: {version}
Checksums-Sha256:
 {orig_sha} {orig_size} gtk+3.0_3.24.33.orig.tar.xz
 {debian_sha} {debian_size} gtk+3.0_3.24.33-1ubuntu2.2.debian.tar.xz
Files:
 00 1 gtk+3.0_3.24.33.orig.tar.xz
-----BEGIN PGP SIGNATURE-----

iQIzBAEBCgAdFiEE
-----END PGP SIGNATURE-----
"""


def _launchpad(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, version: str = "3.24.33-1ubuntu2.2"
) -> dict[str, Any]:
    """Launchpad's file URLs as a local folder with a .dsc and its two files."""
    folder = tmp_path / "launchpad" / "gtk+3.0" / "3.24.33-1ubuntu2.2"
    folder.mkdir(parents=True)
    orig, debian = b"upstream tarball", b"debian folder"
    (folder / "gtk+3.0_3.24.33.orig.tar.xz").write_bytes(orig)
    (folder / "gtk+3.0_3.24.33-1ubuntu2.2.debian.tar.xz").write_bytes(debian)
    (folder / "gtk+3.0_3.24.33-1ubuntu2.2.dsc").write_text(
        DSC.format(
            version=version,
            orig_sha=hashlib.sha256(orig).hexdigest(),
            orig_size=len(orig),
            debian_sha=hashlib.sha256(debian).hexdigest(),
            debian_size=len(debian),
        )
    )
    base = (tmp_path / "launchpad").as_uri()
    monkeypatch.setattr(sf, "LAUNCHPAD_FILES", base + "/{source}/{version}/")
    return {
        "kind": "ubuntu-source",
        "name": "ubuntu-gtk_3.0_3.24.33-1ubuntu2.2",
        "archive": "ubuntu-gtk_3.0_3.24.33-1ubuntu2.2.tar",
        "source": "gtk+3.0",
        "version": "3.24.33-1ubuntu2.2",
    }


def test_an_ubuntu_source_package_is_its_dsc_and_every_file_it_lists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _launchpad(tmp_path, monkeypatch)
    out = tmp_path / "out"

    sf.fetch_all([entry], out)

    assert _members(out / entry["archive"]) == [
        "gtk+3.0_3.24.33-1ubuntu2.2/gtk+3.0_3.24.33-1ubuntu2.2.debian.tar.xz",
        "gtk+3.0_3.24.33-1ubuntu2.2/gtk+3.0_3.24.33-1ubuntu2.2.dsc",
        "gtk+3.0_3.24.33-1ubuntu2.2/gtk+3.0_3.24.33.orig.tar.xz",
    ]


def test_a_dsc_of_another_version_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _launchpad(tmp_path, monkeypatch, version="3.24.33-1ubuntu2.1")

    with pytest.raises(sf.SourcesError, match=r"the pin is gtk\+3\.0 3\.24\.33-1ubuntu2\.2"):
        sf.fetch_all([entry], tmp_path / "out")


def test_a_source_file_that_differs_from_the_dsc_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _launchpad(tmp_path, monkeypatch)
    orig = tmp_path / "launchpad" / "gtk+3.0" / "3.24.33-1ubuntu2.2" / "gtk+3.0_3.24.33.orig.tar.xz"
    orig.write_bytes(b"UPSTREAM TARBALL")

    with pytest.raises(sf.SourcesError, match=r"orig\.tar\.xz: the SHA-256 is"):
        sf.fetch_all([entry], tmp_path / "out")
    assert not (tmp_path / "out" / entry["archive"]).exists()


def test_the_dsc_name_drops_the_epoch() -> None:
    assert sf.ubuntu_dsc_name("libxau", "1:1.0.9-1build5") == "libxau_1.0.9-1build5.dsc"


def test_a_folder_with_files_of_no_entry_is_refused(tmp_path: Path) -> None:
    (tmp_path / "old-source.tar.xz").write_bytes(b"")

    with pytest.raises(sf.SourcesError, match=r"files of no manifest entry: old-source\.tar\.xz"):
        sf.fetch_all([_url_entry(tmp_path / "x.tar.xz", "0" * 64)], tmp_path)


@pytest.mark.parametrize("archive", ["../escape.tar.xz", "SHA256SUMS", ".hidden", ""])
def test_a_manifest_with_an_archive_name_outside_the_folder_is_refused(
    tmp_path: Path, archive: str
) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(f'{{"schema_version": 1, "entries": [{{"archive": "{archive}"}}]}}')

    with pytest.raises(sf.SourcesError, match="plain file names"):
        sf.load_manifest(manifest)


def test_main_reports_a_failure_and_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = sf.main(["--manifest", str(tmp_path / "missing.json"), "--out", str(tmp_path / "o")])

    assert code == 1
    assert "cannot read the manifest" in capsys.readouterr().err
    assert os.listdir(tmp_path) == []
