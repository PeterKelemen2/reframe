"""scripts/sources-fetch.py: one checked archive per manifest entry, the rerun, SHA256SUMS."""

from __future__ import annotations

import fnmatch
import hashlib
import importlib.util
import io
import json
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
    commit = _repo(
        origin, {"configure": "#!/bin/sh\n", ".gitignore": "*.o\n", "COPYING.GPLv3": "GPL"}
    )
    out = tmp_path / "out"

    sf.fetch_all([_git_entry(origin, commit)], out)

    archive = out / "ffmpeg-1234.tar.xz"
    assert _members(archive) == [
        "ffmpeg-1234/.gitignore",
        "ffmpeg-1234/COPYING.GPLv3",
        "ffmpeg-1234/configure",
    ]
    texts = out / "licence-texts.json"
    assert _sums(out) == {
        "ffmpeg-1234.tar.xz": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "licence-texts.json": hashlib.sha256(texts.read_bytes()).hexdigest(),
    }
    assert sorted(p.name for p in out.iterdir()) == [
        "SHA256SUMS",
        "ffmpeg-1234.tar.xz",
        "licence-texts.json",
    ]


def test_a_commit_that_cannot_be_fetched_leaves_no_archive(tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    _repo(origin, {"configure": "", "COPYING": ""})
    out = tmp_path / "out"

    with pytest.raises(sf.SourcesError):
        sf.fetch_all([_git_entry(origin, "1" * 40)], out)

    assert list(out.iterdir()) == []


def test_a_rerun_skips_the_archives_already_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    origin = tmp_path / "origin"
    entry = _git_entry(origin, _repo(origin, {"configure": "", "COPYING": "GPL"}))
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
    commit = _repo(origin, {"x264.c": "int main;\n", "COPYING": "GPL"})
    out = tmp_path / "out"

    sf.fetch_all([_stage_entry(tmp_path, origin, commit)], out)

    assert _members(out / "btbn-50-x264-abcdef.tar.xz") == [
        "btbn-50-x264-abcdef/COPYING",
        "btbn-50-x264-abcdef/x264.c",
    ]
    assert f"checked {origin.as_uri()}@{commit}" in capsys.readouterr().err


@pytest.mark.usefixtures("helper_checkout")
def test_a_stage_may_pin_one_repository_at_several_commits(tmp_path: Path) -> None:
    origin = tmp_path / "nv-codec-headers"
    first = _repo(origin, {"sdk.h": "13\n", "LICENSE": "MIT"})
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
        "btbn-50-x264-abcdef/sdk11/LICENSE",
        "btbn-50-x264-abcdef/sdk11/sdk.h",
        "btbn-50-x264-abcdef/sdk13/LICENSE",
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


def _tarball(path: Path, files: Mapping[str, bytes], mode: str = "w:xz") -> bytes:
    """A tarball of ``files`` at ``path`` (its parent made); its bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, mode) as tar:  # type: ignore[call-overload]
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path.read_bytes()


def test_a_tarball_must_have_its_pinned_checksum(tmp_path: Path) -> None:
    tarball = tmp_path / "upstream" / "mediainfo-26.10.tar.xz"
    source = _tarball(tarball, {"MediaInfo/LICENSE": b"BSD-2-Clause"})
    out = tmp_path / "out"

    with pytest.raises(sf.SourcesError, match="the SHA-256 is"):
        sf.fetch_all([_url_entry(tarball, "0" * 64)], out)
    assert not (out / tarball.name).exists()

    sf.fetch_all([_url_entry(tarball, hashlib.sha256(source).hexdigest())], out)
    assert (out / tarball.name).read_bytes() == source


def test_a_damaged_tarball_is_fetched_again(tmp_path: Path) -> None:
    tarball = tmp_path / "upstream" / "libva-2.24.1.tar.bz2"
    source = _tarball(tarball, {"libva-2.24.1/COPYING": b"MIT"}, mode="w:bz2")
    out = tmp_path / "out"
    out.mkdir()
    (out / tarball.name).write_bytes(b"truncated")

    sf.fetch_all([_url_entry(tarball, hashlib.sha256(source).hexdigest())], out)

    assert (out / tarball.name).read_bytes() == source


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
    # Its licence comes from the build image's /usr/share/doc, not from this archive.
    assert _texts(out) == {}


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


def test_a_static_builds_tree_is_fetched_by_commit_like_a_git_source(tmp_path: Path) -> None:
    origin = tmp_path / "type2-runtime"
    entry = _git_entry(origin, _repo(origin, {"src/runtime.c": "", "LICENSE": "MIT"}))
    entry |= {
        "kind": "repository",
        "name": "type2-runtime-dd6cebedcbdd",
        "archive": "type2-runtime-dd6cebedcbdd.tar.xz",
    }
    out = tmp_path / "out"

    sf.fetch_all([entry], out)

    assert _members(out / entry["archive"]) == [
        "type2-runtime-dd6cebedcbdd/LICENSE",
        "type2-runtime-dd6cebedcbdd/src/runtime.c",
    ]


# Answers `svn info --show-item url|revision PATH` from PATH/.svn/info (url, then revision).
FAKE_SVN = """#!/bin/sh
case "$3" in url) sed -n 1p "$4/.svn/info" ;; revision) sed -n 2p "$4/.svn/info" ;; esac
"""
LAME = "https://svn.code.sf.net/p/lame/svn/trunk/lame"


@pytest.fixture
def fake_svn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir = tmp_path / "svn-bin"
    bin_dir.mkdir()
    (bin_dir / "svn").write_text(FAKE_SVN)
    (bin_dir / "svn").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


def _svn_entry(tmp_path: Path, checked_out: str) -> dict[str, Any]:
    commands = (
        f"mkdir -p lame/.svn && printf '%s\\n%s\\n' '{LAME}' '{checked_out}' > lame/.svn/info"
        " && echo LGPL > lame/COPYING"
    )
    return {
        "kind": "btbn-stage",
        "name": "btbn-50-lame-abcdef",
        "archive": "btbn-50-lame-abcdef.tar.xz",
        "build_scripts_repository": _build_scripts(tmp_path),
        "build_scripts_commit": "",
        "commands": commands,
        "download_hash": hashlib.sha256((commands + "\n").encode()).hexdigest(),
        "variables": {"SCRIPT_REPO": LAME, "SCRIPT_REV": "6835"},
    }


@pytest.mark.usefixtures("helper_checkout", "fake_svn")
def test_an_svn_checkout_must_be_at_its_pinned_revision(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(sf.SourcesError, match="is at 6834, the pin is 6835"):
        sf.fetch_all([_svn_entry(tmp_path / "a", "6834")], tmp_path / "out-a")

    sf.fetch_all([_svn_entry(tmp_path / "b", "6835")], tmp_path / "out-b")
    assert f"checked {LAME}@6835" in capsys.readouterr().err
    assert _members(tmp_path / "out-b" / "btbn-50-lame-abcdef.tar.xz") == [
        "btbn-50-lame-abcdef/lame/COPYING"
    ]


@pytest.mark.usefixtures("helper_checkout")
def test_a_checkout_from_the_stages_mirror_must_be_at_the_pinned_commit(tmp_path: Path) -> None:
    mirror = tmp_path / "libiconv"
    first = _repo(mirror, {"iconv.c": "1\n"})
    (mirror / "iconv.c").write_text("2\n")
    _git("commit", "-q", "-am", "newer", cwd=mirror)
    commands = f"git clone -q '{mirror.as_uri()}' iconv && git -C iconv checkout -q HEAD"
    entry = _stage_entry(tmp_path, mirror, first)
    entry |= {
        "commands": commands,
        "download_hash": hashlib.sha256((commands + "\n").encode()).hexdigest(),
        "variables": {
            "SCRIPT_REPO": "https://example.invalid/libiconv.git",
            "SCRIPT_MIRROR": mirror.as_uri(),
            "SCRIPT_COMMIT": first,
        },
    }

    with pytest.raises(sf.SourcesError, match=f"{mirror.as_uri()} is at .*, the pin is {first}"):
        sf.fetch_all([entry], tmp_path / "out")


def test_the_same_tree_packs_to_the_same_bytes_at_any_time(tmp_path: Path) -> None:
    tree = tmp_path / "x264"
    (tree / "common").mkdir(parents=True)
    (tree / "common" / "x.c").write_text("int x;\n")
    sf.pack(tree, tmp_path / "first.tar.xz")
    for path in (tree, tree / "common", tree / "common" / "x.c"):
        os.utime(path, (1_700_000_000, 1_700_000_000))

    sf.pack(tree, tmp_path / "second.tar.xz")

    assert (tmp_path / "first.tar.xz").read_bytes() == (tmp_path / "second.tar.xz").read_bytes()


def test_an_ubuntu_archive_keeps_no_owner_or_time_of_the_fetching_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _launchpad(tmp_path, monkeypatch)

    sf.fetch_all([entry], tmp_path / "out")

    with tarfile.open(tmp_path / "out" / entry["archive"]) as tar:
        members = tar.getmembers()
    assert members
    assert {(m.uid, m.gid, m.uname, m.gname, m.mtime) for m in members} == {(0, 0, "", "", 0)}


@pytest.mark.parametrize("name", ["../../etc/cron.d/x", "sub/x.tar.xz", ".hidden"])
def test_a_dsc_that_names_a_file_outside_its_folder_is_refused(name: str) -> None:
    fields = {"Checksums-Sha256": f"\n{'a' * 64} 10 x.orig.tar.xz\n{'b' * 64} 5 {name}"}

    with pytest.raises(sf.SourcesError, match="outside its folder"):
        sf.dsc_files(fields)


def _texts(out: Path) -> dict[str, dict[str, str]]:
    document = json.loads((out / "licence-texts.json").read_text(encoding="utf-8"))
    return {
        archive: {item["path"]: item["text"] for item in items}
        for archive, items in document["archives"].items()
    }


def test_the_licence_texts_hold_the_licence_files_at_the_top_of_each_archive(
    tmp_path: Path,
) -> None:
    """The packages' notices carry these texts: a missed file is a licence they lack."""
    origin = tmp_path / "origin"
    files = {
        "COPYING.LGPLv2.1": "LGPL\r\n",
        "LICENSE.md": "FFmpeg is LGPL",
        "LGPL2.txt": "LGPL 2",
        "COPYING.MinGW-w64-runtime/COPYING.MinGW-w64-runtime.txt": "ZPL",
        "LICENSES/MIT.txt": "MIT",
        "libavutil/LICENSE": "a vendored part",
        "license.c": "int code;",
        "COPYING.in": "@VERSION@",
        "README.md": "readme",
    }
    sf.fetch_all([_git_entry(origin, _repo(origin, files))], tmp_path / "out")

    assert _texts(tmp_path / "out") == {
        "ffmpeg-1234.tar.xz": {
            "COPYING.LGPLv2.1": "LGPL\n",
            "COPYING.MinGW-w64-runtime/COPYING.MinGW-w64-runtime.txt": "ZPL",
            "LGPL2.txt": "LGPL 2",
            "LICENSE.md": "FFmpeg is LGPL",
            "LICENSES/MIT.txt": "MIT",
        }
    }


@pytest.mark.usefixtures("helper_checkout")
def test_a_stage_that_checks_out_into_sub_folders_gives_each_ones_licence(
    tmp_path: Path,
) -> None:
    headers, loader = tmp_path / "headers", tmp_path / "loader"
    first = _repo(headers, {"cl.h": "", "LICENSE": "Apache headers"})
    second = _repo(loader, {"icd.c": "", "LICENSE": "Apache loader"})
    entry = _stage_entry(tmp_path, headers, first)
    entry["commands"] = (
        f'git-mini-clone "{headers.as_uri()}" "{first}" headers\n'
        f'git-mini-clone "{loader.as_uri()}" "{second}" loader'
    )
    entry["download_hash"] = hashlib.sha256((entry["commands"] + "\n").encode()).hexdigest()
    entry["variables"] |= {"SCRIPT_REPO2": loader.as_uri(), "SCRIPT_COMMIT2": second}

    sf.fetch_all([entry], tmp_path / "out")

    assert _texts(tmp_path / "out")[entry["archive"]] == {
        "headers/LICENSE": "Apache headers",
        "loader/LICENSE": "Apache loader",
    }


def test_an_archive_without_a_licence_file_stops_the_fetch_and_is_kept(tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    entry = _git_entry(origin, _repo(origin, {"configure": "", "doc/manual/COPYING": "deeper"}))
    out = tmp_path / "out"

    with pytest.raises(sf.SourcesError, match="no licence file found at the top of ffmpeg-1234"):
        sf.fetch_all([entry], out)

    assert (out / "ffmpeg-1234.tar.xz").is_file()
    assert not (out / "licence-texts.json").exists()
    assert not (out / "SHA256SUMS").exists()


def test_a_latin_1_licence_and_a_link_to_a_licence_are_read(tmp_path: Path) -> None:
    tarball = tmp_path / "upstream" / "musl-1.2.5.tar.gz"
    tarball.parent.mkdir()
    with tarfile.open(tarball, "w:gz") as tar:
        data = "Copyright © Rich Felker".encode("latin-1")
        info = tarfile.TarInfo("musl-1.2.5/COPYRIGHT")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
        link = tarfile.TarInfo("musl-1.2.5/LICENSE")
        link.type, link.linkname = tarfile.SYMTYPE, "COPYRIGHT"
        tar.addfile(link)
    out = tmp_path / "out"

    sf.fetch_all([_url_entry(tarball, hashlib.sha256(tarball.read_bytes()).hexdigest())], out)

    assert _texts(out)["musl-1.2.5.tar.gz"] == {
        "COPYRIGHT": "Copyright © Rich Felker",
        "LICENSE": "Copyright © Rich Felker",
    }


@pytest.mark.parametrize(
    ("paths", "chosen"),
    [
        (["COPYING", "src/LICENSE"], ["COPYING"]),
        (["a/LICENSE", "b/COPYING.LIB", "b/src/COPYING"], ["a/LICENSE", "b/COPYING.LIB"]),
        (["NOTICE", "notices.txt", "PATENTS", "Unlicense", "AGPL-3.0.txt"], None),
        (["licensing.c", "COPYING.am", "LICENSE.json", "copyright.h", "license.py"], []),
    ],
)
def test_which_files_are_licence_files(paths: list[str], chosen: list[str] | None) -> None:
    assert sf.select_licence_files(paths) == (sorted(paths) if chosen is None else chosen)


def test_vendored_components_bring_their_licence_files(tmp_path: Path) -> None:
    """librsvg vendors its crates, libjxl has highway as a submodule: their code is linked too."""
    origin = tmp_path / "origin"
    files = {
        "COPYING.LIB": "LGPL",
        "vendor/smallvec-1.13.2/LICENSE-MIT": "MIT smallvec",
        "third_party/highway/LICENSE": "Apache highway",
        "subprojects/proxy-libintl/COPYING": "LGPL intl",
        "third_party/highway/hwy/LICENSE": "deeper, not read",
        "src/vendor/x/LICENSE": "not at the top",
    }
    sf.fetch_all([_git_entry(origin, _repo(origin, files))], tmp_path / "out")

    assert sorted(_texts(tmp_path / "out")["ffmpeg-1234.tar.xz"]) == [
        "COPYING.LIB",
        "subprojects/proxy-libintl/COPYING",
        "third_party/highway/LICENSE",
        "vendor/smallvec-1.13.2/LICENSE-MIT",
    ]


def test_an_archive_whose_licence_is_committed_needs_no_licence_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    committed = tmp_path / "licence-texts.toml"
    committed.write_text('[sources."ffmpeg-*.tar.xz"]\ntext = "MIT, in each header"\n')
    monkeypatch.setattr(sf, "LICENCE_TEXTS", committed)
    origin = tmp_path / "origin"
    entry = _git_entry(origin, _repo(origin, {"include/sdk.h": "/* MIT */"}))

    sf.fetch_all([entry], tmp_path / "out")

    assert _texts(tmp_path / "out") == {"ffmpeg-1234.tar.xz": {}}


def test_the_committed_texts_cover_the_real_sources_without_a_licence_file() -> None:
    patterns = sf.committed_texts(sf.LICENCE_TEXTS)

    assert any(fnmatch.fnmatchcase("btbn-50-ffnvcodec-ef2a38b483ab.tar.xz", p) for p in patterns)
