"""The .deb and .rpm settings and package scripts of desktop/src-tauri/linux/, and the sources
release that build.sh hands to the build."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

skip_windows = pytest.mark.skipif(sys.platform == "win32", reason="Linux package scripts")

TAURI = Path(__file__).resolve().parents[2] / "desktop" / "src-tauri"


def test_the_linux_packages_use_the_desktop_template_and_recommend_the_tools() -> None:
    config = json.loads((TAURI / "tauri.linux.conf.json").read_text())["bundle"]["linux"]
    template = (TAURI / "linux" / "Reframe.desktop.hbs").read_text().splitlines()

    for package in ("deb", "rpm"):
        assert config[package]["desktopTemplate"] == "linux/Reframe.desktop.hbs"
        assert config[package]["recommends"] == ["mkvtoolnix", "mediainfo"]
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
"""


def _build(tmp_path: Path, **sources: str) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Run build.sh with a docker that only logs its arguments; the arguments of its run."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(FAKE_DOCKER)
    (bin_dir / "docker").chmod(0o755)
    log = tmp_path / "docker.log"
    env = {k: v for k, v in os.environ.items() if not k.startswith("REFRAME_")}
    env |= {"PATH": f"{bin_dir}:{env['PATH']}", "DOCKER_LOG": str(log), **sources}
    result = subprocess.run(
        ["sh", str(BUILD / "build.sh"), str(tmp_path / "out")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    calls = log.read_text().split("--\n") if log.exists() else []
    runs = [call.splitlines() for call in calls if call.startswith("run\n")]
    return result, runs[0] if runs else []


def _mounts(run: list[str]) -> dict[str, str]:
    """The run's ``-v`` mounts, target → source."""
    pairs = [run[i + 1].split(":") for i, arg in enumerate(run) if arg == "-v"]
    return {pair[1]: pair[0] for pair in pairs}


@pytest.fixture
def sources(tmp_path: Path) -> dict[str, str]:
    (tmp_path / "SHA256SUMS").write_text("")
    (tmp_path / "manifest.json").write_text("{}")
    return {
        "REFRAME_SOURCES_URL": "https://example.invalid/releases/tag/sources-0123456789ab",
        "REFRAME_SOURCES_SUMS": str(tmp_path / "SHA256SUMS"),
        "REFRAME_SOURCES_MANIFEST": str(tmp_path / "manifest.json"),
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
    assert f"REFRAME_SOURCES_URL={sources['REFRAME_SOURCES_URL']}" in run


@skip_windows
def test_a_build_without_a_sources_release_mounts_nothing_in_their_place(tmp_path: Path) -> None:
    result, run = _build(tmp_path)

    assert result.returncode == 0, result.stderr
    mounts = _mounts(run)
    assert mounts["/sources/SHA256SUMS"] == "/dev/null"
    assert mounts["/sources/manifest.json"] == "/dev/null"
    assert "REFRAME_SOURCES_URL=" in run


@skip_windows
@pytest.mark.parametrize(
    "unset", ["REFRAME_SOURCES_URL", "REFRAME_SOURCES_SUMS", "REFRAME_SOURCES_MANIFEST"]
)
def test_the_sources_variables_are_set_all_three_or_none(
    tmp_path: Path, sources: dict[str, str], unset: str
) -> None:
    del sources[unset]

    result, run = _build(tmp_path, **sources)

    assert result.returncode == 1
    assert "REFRAME_SOURCES_MANIFEST together, or none of them" in result.stderr
    assert run == []


@skip_windows
def test_a_missing_sources_file_stops_the_build_before_docker(
    tmp_path: Path, sources: dict[str, str]
) -> None:
    sources["REFRAME_SOURCES_MANIFEST"] = str(tmp_path / "missing.json")

    result, run = _build(tmp_path, **sources)

    assert result.returncode == 1
    assert f"no file {tmp_path / 'missing.json'}" in result.stderr
    assert run == []


def test_the_notices_read_the_sources_files_where_build_sh_mounts_them() -> None:
    inside = (BUILD / "build-in-container.sh").read_text()
    outside = (BUILD / "build.sh").read_text()

    passed = re.findall(r"--sources-(sums|manifest) (/sources/\S+)", inside)
    assert sorted(option for option, _ in passed) == ["manifest", "sums"]
    for _, path in passed:
        assert f':{path}:ro"' in outside
