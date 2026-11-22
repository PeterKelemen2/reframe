"""The .deb and .rpm settings and package scripts of desktop/src-tauri/linux/, and the sources
release that build.sh hands to the build."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

skip_windows = pytest.mark.skipif(sys.platform == "win32", reason="Linux package scripts")

TAURI = Path(__file__).resolve().parents[2] / "desktop" / "src-tauri"


def test_the_linux_packages_use_the_desktop_template_and_ask_for_no_other_tool() -> None:
    config = json.loads((TAURI / "tauri.linux.conf.json").read_text())["bundle"]["linux"]
    template = (TAURI / "linux" / "Reframe.desktop.hbs").read_text().splitlines()

    for package in ("deb", "rpm"):
        assert config[package]["desktopTemplate"] == "linux/Reframe.desktop.hbs"
        # Reframe writes Matroska headers and probes files itself.
        assert "recommends" not in config[package]
        assert "depends" not in config[package]
    assert config["rpm"]["postRemoveScript"] == "linux/remove-app-dirs.sh"
    # File managers pass every selected file to one process only with %F.
    assert "Exec={{exec}} %F" in template
    assert "StartupWMClass={{exec}}" in template
    assert "MimeType={{mime_type}}" in template


def _remove_app_dirs(root: Path, argument: str) -> None:
    script = (TAURI / "linux" / "remove-app-dirs.sh").read_text()
    assert "app=/usr/lib/Reframe\n" in script
    script = script.replace("app=/usr/lib/Reframe\n", f"app={root}/usr/lib/Reframe\n")
    subprocess.run(["sh", "-c", script, "remove-app-dirs.sh", argument], check=True)


@pytest.fixture
def leftovers(tmp_path: Path) -> Path:
    """What rpm leaves after an erase: the package's empty folders, and a file it did not own."""
    app = tmp_path / "usr" / "lib" / "Reframe"
    (app / "sidecar" / "_internal" / "guessit" / "data").mkdir(parents=True)
    (app / "tools" / "ffmpeg" / "lib").mkdir(parents=True)
    (app / "notices").mkdir()
    (app / "tools" / "ffmpeg" / "local.txt").write_text("not the package's")
    return tmp_path


@skip_windows
def test_an_erase_removes_the_empty_folders_but_keeps_other_files(leftovers: Path) -> None:
    _remove_app_dirs(leftovers, "0")

    app = leftovers / "usr" / "lib" / "Reframe"
    assert sorted(p.relative_to(app).as_posix() for p in app.rglob("*")) == [
        "tools",
        "tools/ffmpeg",
        "tools/ffmpeg/local.txt",
    ]


@skip_windows
def test_an_erase_of_everything_removes_the_app_folder(leftovers: Path) -> None:
    (leftovers / "usr" / "lib" / "Reframe" / "tools" / "ffmpeg" / "local.txt").unlink()

    _remove_app_dirs(leftovers, "0")

    assert not (leftovers / "usr" / "lib" / "Reframe").exists()
    assert (leftovers / "usr" / "lib").is_dir()


def test_an_upgrade_keeps_the_folders(leftovers: Path) -> None:
    _remove_app_dirs(leftovers, "1")

    assert (
        leftovers / "usr" / "lib" / "Reframe" / "sidecar" / "_internal" / "guessit" / "data"
    ).is_dir()


BUILD = TAURI.parent / "packaging" / "linux"
FAKE_DOCKER = """#!/bin/sh
for arg in "$@"; do printf '%s\\n' "$arg"; done >> "$DOCKER_LOG"
echo -- >> "$DOCKER_LOG"
case "$*" in *"$DOCKER_FAIL_ON"*) [ -n "$DOCKER_FAIL_ON" ] && exit 1 ;; esac
exit 0
"""


def _docker_calls(
    tmp_path: Path, fail_on: str = "", **sources: str
) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    """Run build.sh with a docker that only logs its arguments (and fails a call that contains
    ``fail_on``); the arguments of each docker call."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(FAKE_DOCKER)
    (bin_dir / "docker").chmod(0o755)
    log = tmp_path / "docker.log"
    env = {k: v for k, v in os.environ.items() if not k.startswith("REFRAME_")}
    env |= {"PATH": f"{bin_dir}:{env['PATH']}", "DOCKER_LOG": str(log), "DOCKER_FAIL_ON": fail_on}
    result = subprocess.run(
        ["sh", str(BUILD / "build.sh"), str(tmp_path / "out")],
        env=env | sources,
        capture_output=True,
        text=True,
        check=False,
    )
    calls = log.read_text().split("--\n") if log.exists() else []
    return result, [call.splitlines() for call in calls if call]


def _build(tmp_path: Path, **sources: str) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Run build.sh with a docker that only logs its arguments; the arguments of its first run."""
    result, calls = _docker_calls(tmp_path, **sources)
    runs = [call for call in calls if call[0] == "run"]
    return result, runs[0] if runs else []


def _mounts(run: list[str]) -> dict[str, str]:
    """The run's ``-v`` mounts, target → source."""
    pairs = [run[i + 1].split(":") for i, arg in enumerate(run) if arg == "-v"]
    return {pair[1]: pair[0] for pair in pairs}


@pytest.fixture
def sources(tmp_path: Path) -> dict[str, str]:
    (tmp_path / "SHA256SUMS").write_text("")
    (tmp_path / "manifest.json").write_text("{}")
    (tmp_path / "licence-texts.json").write_text("{}")
    return {
        "REFRAME_SOURCES_URL": "https://example.invalid/releases/tag/sources-0123456789ab",
        "REFRAME_SOURCES_SUMS": str(tmp_path / "SHA256SUMS"),
        "REFRAME_SOURCES_MANIFEST": str(tmp_path / "manifest.json"),
        "REFRAME_SOURCES_TEXTS": str(tmp_path / "licence-texts.json"),
    }


@skip_windows
def test_a_release_build_mounts_the_sources_files_and_passes_the_url(
    tmp_path: Path, sources: dict[str, str]
) -> None:
    result, run = _build(tmp_path, **sources)

    assert result.returncode == 0, result.stderr
    mounts = _mounts(run)
    assert mounts["/sources/SHA256SUMS"] == str(tmp_path / "SHA256SUMS")
    assert mounts["/sources/manifest.json"] == str(tmp_path / "manifest.json")
    assert mounts["/sources/licence-texts.json"] == str(tmp_path / "licence-texts.json")
    assert f"REFRAME_SOURCES_URL={sources['REFRAME_SOURCES_URL']}" in run


@skip_windows
def test_a_build_without_a_sources_release_mounts_nothing_in_their_place(tmp_path: Path) -> None:
    result, run = _build(tmp_path)

    assert result.returncode == 0, result.stderr
    mounts = _mounts(run)
    assert mounts["/sources/SHA256SUMS"] == "/dev/null"
    assert mounts["/sources/manifest.json"] == "/dev/null"
    assert mounts["/sources/licence-texts.json"] == "/dev/null"
    assert "REFRAME_SOURCES_URL=" in run


@skip_windows
@pytest.mark.parametrize(
    "unset",
    [
        "REFRAME_SOURCES_URL",
        "REFRAME_SOURCES_SUMS",
        "REFRAME_SOURCES_MANIFEST",
        "REFRAME_SOURCES_TEXTS",
    ],
)
def test_the_sources_variables_are_set_all_four_or_none(
    tmp_path: Path, sources: dict[str, str], unset: str
) -> None:
    del sources[unset]

    result, run = _build(tmp_path, **sources)

    assert result.returncode == 1
    assert "REFRAME_SOURCES_TEXTS together, or none of them" in result.stderr
    assert run == []


@skip_windows
@pytest.mark.parametrize("variable", ["REFRAME_SOURCES_MANIFEST", "REFRAME_SOURCES_TEXTS"])
def test_a_missing_sources_file_stops_the_build_before_docker(
    tmp_path: Path, sources: dict[str, str], variable: str
) -> None:
    sources[variable] = str(tmp_path / "missing.json")

    result, run = _build(tmp_path, **sources)

    assert result.returncode == 1
    assert f"no file {tmp_path / 'missing.json'}" in result.stderr
    assert run == []


def test_the_notices_read_the_sources_files_where_build_sh_mounts_them() -> None:
    inside = (BUILD / "build-in-container.sh").read_text()
    outside = (BUILD / "build.sh").read_text()

    passed = re.findall(r"--sources-(sums|manifest|texts) (/sources/\S+)", inside)
    assert sorted(option for option, _ in passed) == ["manifest", "sums", "texts"]
    for _, path in passed:
        assert f':{path}:ro"' in outside


@skip_windows
def test_a_release_build_checks_the_appimage_against_the_manifests_package_list(
    tmp_path: Path,
) -> None:
    (tmp_path / "appimage-libs.json").write_text("{}")

    result, calls = _docker_calls(
        tmp_path, REFRAME_APPIMAGE_LIBS=str(tmp_path / "appimage-libs.json")
    )

    assert result.returncode == 0, result.stderr
    [_, check] = [call for call in calls if call[0] == "run"]
    assert _mounts(check)["/appimage-libs.json"] == str(tmp_path / "appimage-libs.json")
    # The sh -c script is the last argument; the log has one line per line of it.
    command = " ".join(" ".join(check[check.index("-c") + 1 :]).replace("\\", " ").split())
    assert command == (
        "uv run --no-project python /src/scripts/appimage-libs.py check"
        " /build/target/release/bundle/appimage/*.AppDir --expected /appimage-libs.json"
    )


@skip_windows
def test_a_failed_package_check_fails_the_build(tmp_path: Path) -> None:
    (tmp_path / "appimage-libs.json").write_text("{}")

    result, _ = _docker_calls(
        tmp_path, "appimage-libs.py", REFRAME_APPIMAGE_LIBS=str(tmp_path / "appimage-libs.json")
    )

    assert result.returncode != 0


@skip_windows
def test_a_missing_package_list_stops_the_build_before_docker(tmp_path: Path) -> None:
    result, calls = _docker_calls(tmp_path, REFRAME_APPIMAGE_LIBS=str(tmp_path / "missing.json"))

    assert result.returncode == 1
    assert f"no file {tmp_path / 'missing.json'}" in result.stderr
    assert calls == []


def _bundle_calls(tmp_path: Path, version: str) -> list[str]:
    """Run build-in-container.sh's bundling step with a node that answers ``version`` and an npx
    that only logs its arguments, one line per call."""
    lines = (BUILD / "build-in-container.sh").read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("version=$(node"))
    end = lines.index("esac", start)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "node").write_text(f"#!/bin/sh\necho {version}\n")
    (bin_dir / "npx").write_text('#!/bin/sh\necho "$*" >> "$NPX_LOG"\n')
    for tool in ("node", "npx"):
        (bin_dir / tool).chmod(0o755)
    (tmp_path / "desktop").mkdir()
    log = tmp_path / "npx.log"
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", NPX_LOG=str(log))
    script = "set -eu\n" + "\n".join(lines[start : end + 1])
    subprocess.run(["sh", "-c", script], cwd=tmp_path, env=env, check=True)
    return log.read_text().splitlines()


@skip_windows
def test_a_release_version_is_bundled_by_one_tauri_build(tmp_path: Path) -> None:
    assert _bundle_calls(tmp_path, "1.2.0") == ["tauri build --verbose"]


@skip_windows
@pytest.mark.parametrize(
    ("version", "rpm_version", "rpm_release"),
    [("0.1.0-dev.0", "0.1.0", "0.dev.0"), ("1.0.0-rc.1", "1.0.0", "0.rc.1")],
)
def test_the_rpm_of_a_pre_release_takes_the_pre_release_into_its_release(
    tmp_path: Path, version: str, rpm_version: str, rpm_release: str
) -> None:
    build, bundle = _bundle_calls(tmp_path, version)

    assert build == "tauri build --verbose --bundles deb,appimage"
    prefix = "tauri bundle --verbose --bundles rpm --config "
    assert bundle.startswith(prefix)
    config = json.loads(bundle.removeprefix(prefix))
    # rpm refuses a `-` in the version; release 0.x sorts before the final version's release 1.
    assert config == {
        "version": rpm_version,
        "bundle": {"linux": {"rpm": {"release": rpm_release}}},
    }


def test_the_bundler_gets_the_pinned_runtime_and_the_appimage_is_checked_against_it() -> None:
    lines = (BUILD / "build-in-container.sh").read_text().splitlines()

    fetch = next(i for i, line in enumerate(lines) if "appimage-runtime.sh" in line)
    export = lines.index("export LDAI_RUNTIME_FILE")
    build = next(i for i, line in enumerate(lines) if "tauri build" in line)
    check = next(i for i, line in enumerate(lines) if "check-runtime" in line)
    assert lines[fetch].startswith("LDAI_RUNTIME_FILE=$(")
    assert fetch < export < build < check
    assert '--runtime "$LDAI_RUNTIME_FILE"' in lines[check + 1]


def _runtime_tree(tmp_path: Path, content: bytes, sha256: str) -> tuple[Path, Path]:
    """A copy of appimage-runtime.sh with a static-builds.toml whose runtime is a local file."""
    script = tmp_path / "repo" / "desktop" / "packaging" / "linux" / "appimage-runtime.sh"
    script.parent.mkdir(parents=True)
    script.write_text((BUILD / "appimage-runtime.sh").read_text())
    upstream = tmp_path / "upstream" / "runtime-x86_64"
    upstream.parent.mkdir()
    upstream.write_bytes(content)
    (tmp_path / "repo" / "tools").mkdir()
    (tmp_path / "repo" / "tools" / "static-builds.toml").write_text(
        f'[binaries.appimage-runtime]\nurl = "{upstream.as_uri()}"\nsha256 = "{sha256}"\n'
    )
    return script, upstream


def _fetch_runtime(script: Path, cache: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(script), str(cache)],
        cwd=script.parent,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


@skip_windows
def test_the_pinned_runtime_is_downloaded_once_and_checked_each_time(tmp_path: Path) -> None:
    content = b"\x7fELF runtime"
    sha256 = hashlib.sha256(content).hexdigest()
    script, upstream = _runtime_tree(tmp_path, content, sha256)
    cache = tmp_path / "cache"

    first = _fetch_runtime(script, cache)
    upstream.unlink()
    second = _fetch_runtime(script, cache)

    assert first.returncode == 0, first.stderr
    assert first.stdout == second.stdout == f"{cache / f'appimage-runtime-{sha256}'}\n"
    assert (cache / f"appimage-runtime-{sha256}").read_bytes() == content
    (cache / f"appimage-runtime-{sha256}").write_bytes(b"damaged")
    assert _fetch_runtime(script, cache).returncode != 0


@skip_windows
def test_a_runtime_without_its_pinned_checksum_is_refused(tmp_path: Path) -> None:
    script, _ = _runtime_tree(tmp_path, b"another runtime", "0" * 64)
    cache = tmp_path / "cache"

    result = _fetch_runtime(script, cache)

    assert result.returncode == 1
    assert f"does not have the SHA-256 {'0' * 64}" in result.stderr
    assert result.stdout == ""
    assert sorted(p.name for p in cache.iterdir()) == []
