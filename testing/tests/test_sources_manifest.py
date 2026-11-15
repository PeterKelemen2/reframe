"""scripts/sources-manifest.py: which sources the manifest names for each platform, and its tag."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "sources-manifest.py"

FFMPEG_COMMIT = "2a571b606854520cf89804d8030c8b328e621689"
SCRIPTS_COMMIT = "6c9aec5fc9a72ec3abedd1fa84db141fa18cf52b"
X264_COMMIT = "0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee"
MINGW_COMMIT = "57b595039040eaa15bece85b7cc71d952281b269"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sources_manifest", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sm = _load_script()

# A build-scripts tree in BtbN's shape: generate.sh writes a RUN line with the download archive
# of every enabled stage, named by the SHA-256 of its download commands, as BtbN's does.
GENERATE = r"""#!/bin/bash
set -e
source util/vars.sh "$@"
rm -f Dockerfile
for SCRIPT in scripts.d/*.sh; do
    (
        source util/dl_functions.sh
        source "$SCRIPT"
        ffbuild_enabled || exit 0
        STG="$(ffbuild_dockerdl)"
        NAME="$(basename "$SCRIPT" .sh)"
        if [[ -z "$STG" ]]; then
            echo "RUN --mount=src=$SCRIPT,dst=/stage.sh run_stage /stage.sh" >> Dockerfile
            exit 0
        fi
        HASH="$(sha256sum <<<"$STG" | cut -d" " -f1)"
        [[ -f "corrupt-$SCRIPT" ]] && HASH="$(sha256sum <<<"other" | cut -d" " -f1)"
        CACHE=".cache/downloads/${NAME}_${HASH}.tar.xz"
        PATCHES=""
        [[ -d "patches/$NAME" ]] && PATCHES=" --mount=src=patches/$NAME,dst=/patches"
        echo "RUN --mount=src=$SCRIPT,dst=/stage.sh --mount=src=$CACHE,dst=/cache.tar.xz\
$PATCHES run_stage /stage.sh" >> Dockerfile
    )
done
"""
VARS = 'TARGET="$1"\nVARIANT="$2"\nshift 2\n'
DL_FUNCTIONS = r"""default_dl() {
    echo "git-mini-clone \"$SCRIPT_REPO\" \"$SCRIPT_COMMIT\" \"$1\""
}
ffbuild_dockerdl() {
    default_dl .
}
"""


def _stage(repo: str, commit: str, enabled: str = "return 0") -> str:
    return (
        f'SCRIPT_REPO="{repo}"\nSCRIPT_COMMIT="{commit}"\nffbuild_enabled() {{\n    {enabled}\n}}\n'
    )


def _btbn_tree(root: Path) -> Path:
    (root / "util").mkdir(parents=True)
    (root / "scripts.d").mkdir()
    (root / "generate.sh").write_text(GENERATE)
    (root / "util" / "vars.sh").write_text(VARS)
    (root / "util" / "dl_functions.sh").write_text(DL_FUNCTIONS)
    (root / "scripts.d" / "50-x264.sh").write_text(
        _stage("https://code.videolan.org/videolan/x264.git", X264_COMMIT)
    )
    (root / "scripts.d" / "10-mingw.sh").write_text(
        _stage("https://example.invalid/mingw-w64.git", MINGW_COMMIT, "[[ $TARGET == win* ]]")
    )
    (root / "scripts.d" / "99-finalize.sh").write_text(
        'SCRIPT_SKIP="1"\nffbuild_enabled() {\n    return 0\n}\nffbuild_dockerdl() {\n    true\n}\n'
    )
    (root / "patches" / "50-x264").mkdir(parents=True)
    return root


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
    arm64: bool = False,
    static_builds: str = STATIC_BUILDS,
) -> Path:
    root.mkdir(parents=True)
    base = "https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-09-30-13-08"
    platforms = {"linux-x64": "linux64", "windows-x64": "win64"}
    if arm64:
        platforms["linux-arm64"] = "linuxarm64"
    tables = "".join(
        f"[builds.default.platforms.{key}]\n"
        f'url = "{base}/ffmpeg-n9.0.2-{target}-gpl-shared-9.0.tar.xz"\n'
        for key, target in platforms.items()
    )
    (root / "ffmpeg.toml").write_text(
        "[builds.default]\n"
        'license = "GPL-3.0-or-later"\nvariant = "gpl-shared"\nsource_branch = "release/9.0"\n'
        'source_repository = "https://github.com/FFmpeg/FFmpeg"\n'
        f'source_commit = "{FFMPEG_COMMIT}"\n'
        'build_scripts_repository = "https://github.com/BtbN/FFmpeg-Builds"\n'
        f'build_scripts_commit = "{SCRIPTS_COMMIT}"\n' + tables
    )
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
    tree = tmp_path / "btbn"
    if not tree.exists():
        _btbn_tree(tree)
    result: dict[str, Any] = sm.build(_tools(tmp_path / "tools", **tools), tree, libs)
    return result


def _entries(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {entry["archive"]: entry for entry in document["entries"]}


def test_each_dependency_download_is_named_with_the_platforms_that_build_it(
    tmp_path: Path,
) -> None:
    entries = _entries(_build(tmp_path))

    repo = "https://code.videolan.org/videolan/x264.git"
    commands = f'git-mini-clone "{repo}" "{X264_COMMIT}" "."\n'
    x264_hash = hashlib.sha256(commands.encode()).hexdigest()
    x264 = entries[f"btbn-50-x264-{x264_hash[:12]}.tar.xz"]
    assert x264["platforms"] == ["linux-x64", "windows-x64"]
    assert x264["download_hash"] == x264_hash
    assert x264["variables"] == {
        "SCRIPT_COMMIT": X264_COMMIT,
        "SCRIPT_REPO": "https://code.videolan.org/videolan/x264.git",
    }
    assert x264["build_files"] == ["patches/50-x264"]
    assert not [e for e in entries.values() if "finalize" in e["name"]]
    [mingw] = [e for e in entries.values() if e["name"].startswith("btbn-10-mingw-")]
    assert mingw["platforms"] == ["windows-x64"]


def test_ffmpeg_and_its_build_scripts_are_named_by_commit(tmp_path: Path) -> None:
    entries = _entries(_build(tmp_path))

    ffmpeg = entries[f"ffmpeg-{FFMPEG_COMMIT[:12]}.tar.xz"]
    scripts = entries[f"ffmpeg-builds-{SCRIPTS_COMMIT[:12]}.tar.xz"]
    assert (ffmpeg["kind"], ffmpeg["commit"], ffmpeg["license"]) == (
        "git",
        FFMPEG_COMMIT,
        "GPL-3.0-or-later",
    )
    assert (scripts["repository"], scripts["commit"]) == (
        "https://github.com/BtbN/FFmpeg-Builds",
        SCRIPTS_COMMIT,
    )


def test_an_arm64_pin_brings_its_own_target(tmp_path: Path) -> None:
    pin = sm.ffmpeg_pin(_tools(tmp_path / "tools", arm64=True))

    assert pin.targets == {
        "linux-arm64": "linuxarm64",
        "linux-x64": "linux64",
        "windows-x64": "win64",
    }
    assert pin.addin == "9.0"


def test_the_repositorys_pins_name_the_btbn_targets_of_their_archives() -> None:
    pin = sm.ffmpeg_pin(REPO_ROOT / "tools")

    assert pin.variant == "gpl-shared"
    assert {pin.targets["linux-x64"], pin.targets["windows-x64"]} == {"linux64", "win64"}
    assert pin.targets.get("linux-arm64", "linuxarm64") == "linuxarm64"


def test_an_archive_of_another_branch_is_an_error(tmp_path: Path) -> None:
    tools = _tools(tmp_path / "tools")
    text = (tools / "ffmpeg.toml").read_text().replace('"release/9.0"', '"release/8.1"')
    (tools / "ffmpeg.toml").write_text(text)

    with pytest.raises(sm.ManifestError, match=r"is not a gpl-shared build of release/8\.1"):
        sm.ffmpeg_pin(tools)


def test_a_stage_whose_commands_are_not_the_builds_is_an_error(tmp_path: Path) -> None:
    tree = _btbn_tree(tmp_path / "btbn")
    (tree / "corrupt-scripts.d").mkdir()
    (tree / "corrupt-scripts.d" / "50-x264.sh").write_text("")

    with pytest.raises(sm.ManifestError, match=r"50-x264\.sh: its download commands hash to"):
        _build(tmp_path)


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
    entry = {"kind": "git", "name": "ffmpeg-x"}

    with pytest.raises(sm.ManifestError, match=r"both be the archive ffmpeg-x\.tar\.xz"):
        sm.manifest([entry, dict(entry)])


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
    tree = _btbn_tree(tmp_path / "b" / "btbn")
    stage = tree / "scripts.d" / "50-x264.sh"
    stage.write_text(stage.read_text().replace(X264_COMMIT, "1" * 40))

    assert sm.tag(sm.encode(_build(tmp_path / "b"))) != before


def test_main_writes_the_manifest_and_prints_its_tag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tools = _tools(tmp_path / "tools")
    tree = _btbn_tree(tmp_path / "btbn")
    out = tmp_path / "out" / "manifest.json"

    code = sm.main(["--out", str(out), "--tools-dir", str(tools), "--build-scripts", str(tree)])

    assert code == 0
    assert capsys.readouterr().out == sm.tag(out.read_bytes()) + "\n"
    assert json.loads(out.read_text())["schema_version"] == 1


def test_a_stage_line_the_script_cannot_read_is_an_error(tmp_path: Path) -> None:
    tree = _btbn_tree(tmp_path / "btbn")
    (tree / "generate.sh").write_text(
        "echo 'RUN --mount=src=scripts.d/50-x264.sh,dst=/stage.sh "
        "--mount=src=.cache/downloads/50-x264.tar.xz,dst=/cache.tar.xz run_stage /stage.sh'"
        " > Dockerfile\n"
    )

    with pytest.raises(sm.ManifestError, match="cannot read the stage"):
        sm.btbn_stages(tree, "linux64", "gpl-shared", "9.0")


def test_the_callers_script_variables_do_not_change_the_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clean = sm.encode(_build(tmp_path / "a"))
    monkeypatch.setenv("SCRIPT_TOKEN", "from the runner")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/reframe")

    leaky = _build(tmp_path / "b")

    x264 = next(e for e in leaky["entries"] if e["name"].startswith("btbn-50-x264-"))
    assert set(x264["variables"]) == {"SCRIPT_COMMIT", "SCRIPT_REPO"}
    assert sm.encode(leaky) == clean


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
    """The installers bundle FFmpeg only: no MKVToolNix or MediaInfo source in the release."""
    entries = sm.library_entries(REPO_ROOT / "tools")

    assert [e["name"] for e in entries if "windows-x64" in e["platforms"]] == []
    assert [e["name"] for e in entries] == ["libva-2.24.1.tar.bz2"]
