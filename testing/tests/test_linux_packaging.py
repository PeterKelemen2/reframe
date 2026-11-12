"""The .deb and .rpm settings and package scripts of desktop/src-tauri/linux/."""

from __future__ import annotations

import json
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
