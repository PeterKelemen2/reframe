"""scripts/sources-manifest.py: which sources the manifest names for each platform, and its tag."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from reframe_testing.scripts import load_script

REPO_ROOT = Path(__file__).resolve().parents[2]

sm = load_script("sources-manifest.py")

RUNTIME_COMMIT = "dd6cebedcbddde9c82f89b011e8e1d40b6e43868"
TREE_COMMIT = "02b82ecfdc5a63decc4e64e06ca2dc8f0b7158f1"
STATIC_BUILDS = f"""
[binaries.appimage-runtime]
description = "AppImage runtime"
platforms = ["linux-x64"]
license = "MIT"
source_repository = "https://github.com/AppImage/type2-runtime"
source_commit = "{RUNTIME_COMMIT}"

[[binaries.appimage-runtime.parts]]
name = "libfuse"
version = "3.15.0"
license = "LGPL-2.1-only"
url = "https://github.com/libfuse/libfuse/releases/download/fuse-3.15.0/fuse-3.15.0.tar.xz"
sha256 = "{"c" * 64}"

[[binaries.appimage-runtime.parts]]
name = "squashfuse"
version = "0.5.2"
license = "BSD-2-Clause"
url = "https://github.com/vasi/squashfuse/archive/0.5.2.tar.gz"
sha256 = "{"d" * 64}"
archive = "squashfuse-0.5.2.tar.gz"

[binaries.example]
description = "example.exe, a static build"
platforms = ["windows-x64"]
license = "GPL-2.0-only"
source_repository = "https://example.invalid/static-tree"
source_commit = "{TREE_COMMIT}"

[[binaries.example.parts]]
name = "GNU MP"
version = "6.3.0"
license = "LGPL-3.0-or-later OR GPL-2.0-or-later"
url = "https://gmplib.org/download/gmp/gmp-6.3.0.tar.xz"
sha256 = "{"e" * 64}"
"""


def _tools(
    root: Path,
    *,
    libva_sha: str = "b" * 64,
    static_builds: str = STATIC_BUILDS,
) -> Path:
    root.mkdir(parents=True)
    (root / "bundled-tools.toml").write_text(
        "[libraries.libva]\n"
        'description = "libva 2.24.1"\nlicense = "MIT"\n'
        + "".join(
            f"[libraries.libva.platforms.{platform}]\n"
            'url = "https://github.com/intel/libva/releases/download/2.24.1/libva-2.24.1.tar.bz2"\n'
            f'sha256 = "{libva_sha}"\n'
            for platform in ("linux-x64", "linux-arm64")
        )
    )
    (root / "static-builds.toml").write_text(static_builds)
    return root


APPIMAGE_LIBS = {
    "schema_version": 1,
    "distribution": {"id": "ubuntu", "version_id": "22.04"},
    "packages": [
        {"package": "libgtk-3-0", "source": "gtk+3.0", "source_version": "3.24.33-1ubuntu2.2"},
        {"package": "libgtk-3-common", "source": "gtk+3.0", "source_version": "3.24.33-1ubuntu2.2"},
        {"package": "libxau6", "source": "libxau", "source_version": "1:1.0.9-1build5"},
    ],
}


def _build(tmp_path: Path, **tools: Any) -> dict[str, Any]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    libs = tmp_path / "appimage-libs.json"
    libs.write_text(json.dumps(APPIMAGE_LIBS))
    result: dict[str, Any] = sm.build(_tools(tmp_path / "tools", **tools), libs)
    return result


def _entries(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {entry["archive"]: entry for entry in document["entries"]}


def test_the_manifest_names_no_ffmpeg_source_and_needs_no_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No artefact conveys FFmpeg: neither its commit, nor BtbN's build scripts or stages."""
    libs = tmp_path / "appimage-libs.json"
    libs.write_text(json.dumps(APPIMAGE_LIBS))
    empty = tmp_path / "no-tools"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))  # no git, no bash
    out = tmp_path / "manifest.json"

    code = sm.main(
        ["--out", str(out), "--tools-dir", str(REPO_ROOT / "tools"), "--appimage-libs", str(libs)]
    )

    assert code == 0, capsys.readouterr().err
    entries = json.loads(out.read_text())["entries"]
    assert {entry["kind"] for entry in entries} == {"url", "repository", "ubuntu-source"}
    assert not [e for e in entries if "ffmpeg" in json.dumps(e).lower() or "btbn" in e["name"]]


def test_the_library_sources_have_their_pinned_checksums(tmp_path: Path) -> None:
    entries = _entries(_build(tmp_path))

    libva = entries["libva-2.24.1.tar.bz2"]
    assert libva["kind"] == "url"
    assert (libva["sha256"], libva["platforms"], libva["license"]) == (
        "b" * 64,
        ["linux-arm64", "linux-x64"],
        "MIT",
    )


def test_a_library_source_without_a_pinned_checksum_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(sm.ManifestError, match=r"libva: the SHA-256 of .* is not pinned"):
        _build(tmp_path, libva_sha="not a checksum")


def test_the_appimage_libraries_give_one_entry_per_ubuntu_source_package(tmp_path: Path) -> None:
    entries = _entries(_build(tmp_path))

    gtk = entries["ubuntu-gtk_3.0_3.24.33-1ubuntu2.2.tar"]
    xau = entries["ubuntu-libxau_1_1.0.9-1build5.tar"]
    assert (gtk["source"], gtk["version"], gtk["binary_packages"]) == (
        "gtk+3.0",
        "3.24.33-1ubuntu2.2",
        ["libgtk-3-0", "libgtk-3-common"],
    )
    assert (xau["version"], xau["platforms"]) == ("1:1.0.9-1build5", ["linux-x64"])


def test_appimage_libraries_of_another_distribution_are_an_error() -> None:
    with pytest.raises(sm.ManifestError, match="only Ubuntu"):
        sm.appimage_entries(APPIMAGE_LIBS | {"distribution": {"id": "debian"}})


def test_two_sources_with_the_same_archive_name_are_an_error() -> None:
    entry = {"kind": "repository", "name": "tree-x", "commit": "1" * 40, "platforms": []}

    with pytest.raises(sm.ManifestError, match=r"both be the archive tree-x\.tar\.xz"):
        sm.manifest([entry, entry | {"commit": "2" * 40}])


@pytest.mark.parametrize(
    ("text", "name"),
    [("ubuntu-gtk+3.0_3.24", "ubuntu-gtk_3.0_3.24"), ("ubuntu-x_1:2~rc1", "ubuntu-x_1_2_rc1")],
)
def test_archive_names_keep_only_what_github_keeps(text: str, name: str) -> None:
    assert sm.asset_name(text) == name


def test_the_same_pins_give_the_same_manifest_and_tag(tmp_path: Path) -> None:
    first = sm.encode(_build(tmp_path / "a"))
    second = sm.encode(_build(tmp_path / "b"))

    assert first == second
    assert sm.tag(first) == f"sources-{hashlib.sha256(first).hexdigest()[:12]}"


def test_a_changed_source_pin_changes_the_tag(tmp_path: Path) -> None:
    before = sm.tag(sm.encode(_build(tmp_path / "a")))

    assert sm.tag(sm.encode(_build(tmp_path / "b", libva_sha="c" * 64))) != before


def test_main_writes_the_manifest_and_prints_its_tag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tools = _tools(tmp_path / "tools")
    out = tmp_path / "out" / "manifest.json"

    code = sm.main(["--out", str(out), "--tools-dir", str(tools)])

    assert code == 0
    assert capsys.readouterr().out == sm.tag(out.read_bytes()) + "\n"
    assert json.loads(out.read_text())["schema_version"] == 1


def test_each_static_build_brings_its_tree_and_every_linked_library(tmp_path: Path) -> None:
    entries = _entries(_build(tmp_path))

    runtime = entries[f"type2-runtime-{RUNTIME_COMMIT[:12]}.tar.xz"]
    tree = entries[f"static-tree-{TREE_COMMIT[:12]}.tar.xz"]
    assert (runtime["kind"], runtime["commit"], runtime["platforms"]) == (
        "repository",
        RUNTIME_COMMIT,
        ["linux-x64"],
    )
    assert (tree["repository"], tree["platforms"]) == (
        "https://example.invalid/static-tree",
        ["windows-x64"],
    )
    fuse = entries["fuse-3.15.0.tar.xz"]
    assert (fuse["kind"], fuse["sha256"], fuse["license"], fuse["platforms"]) == (
        "url",
        "c" * 64,
        "LGPL-2.1-only",
        ["linux-x64"],
    )
    assert entries["squashfuse-0.5.2.tar.gz"]["url"].endswith("/archive/0.5.2.tar.gz")
    assert entries["gmp-6.3.0.tar.xz"]["platforms"] == ["windows-x64"]


def test_a_static_build_part_without_a_pinned_checksum_is_an_error(tmp_path: Path) -> None:
    static = STATIC_BUILDS.replace(f'sha256 = "{"e" * 64}"', "")

    with pytest.raises(sm.ManifestError, match=r"GNU MP 6\.3\.0: the SHA-256 of .* is not pinned"):
        _build(tmp_path, static_builds=static)


def test_a_tarball_that_two_static_builds_link_is_one_entry_for_both(tmp_path: Path) -> None:
    gmp = STATIC_BUILDS.split("[[binaries.example.parts]]")[1]
    static = STATIC_BUILDS + "\n[[binaries.appimage-runtime.parts]]" + gmp

    entries = _entries(_build(tmp_path, static_builds=static))

    assert entries["gmp-6.3.0.tar.xz"]["platforms"] == ["linux-x64", "windows-x64"]


def test_two_different_tarballs_with_one_archive_name_are_an_error(tmp_path: Path) -> None:
    gmp = STATIC_BUILDS.split("[[binaries.example.parts]]")[1].replace("e" * 64, "f" * 64)
    static = STATIC_BUILDS + "\n[[binaries.appimage-runtime.parts]]" + gmp

    with pytest.raises(sm.ManifestError, match=r"both be the archive gmp-6\.3\.0\.tar\.xz"):
        _build(tmp_path, static_builds=static)


def test_the_repositorys_static_builds_name_the_gpl_and_lgpl_parts() -> None:
    entries = sm.static_entries(REPO_ROOT / "tools")

    names = {
        platform: {e["component"].split(",")[0] for e in entries if platform in e["platforms"]}
        for platform in ("linux-x64", "windows-x64")
    }
    for part in ("libfuse 3.15.0", "squashfuse 0.5.2", "musl 1.2.5", "zstd 1.5.6", "zlib 1.3.1"):
        assert part in names["linux-x64"]
    assert names["windows-x64"] == set()
    trees = [e for e in entries if e["kind"] == "repository"]
    assert {(e["name"], tuple(e["platforms"])) for e in trees} == {
        (f"type2-runtime-{RUNTIME_COMMIT[:12]}", ("linux-x64",)),
    }
    assert len(sm.manifest(entries)["entries"]) == len(entries)


def test_the_repositorys_installers_bundle_no_library_source() -> None:
    """No MKVToolNix or MediaInfo source in the release; libva is for Linux only."""
    entries = sm.library_entries(REPO_ROOT / "tools")

    assert [e["name"] for e in entries if "windows-x64" in e["platforms"]] == []
    assert [e["name"] for e in entries] == ["libva-2.24.1.tar.bz2"]
