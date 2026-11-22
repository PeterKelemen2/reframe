"""The Windows installer's hooks against the bundle settings they depend on, and the check
that the Windows packages contain no FFmpeg."""

from __future__ import annotations

import importlib.util
import json
import re
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TAURI = REPO_ROOT / "desktop" / "src-tauri"


def test_the_hooks_restore_every_associated_extension() -> None:
    associations = json.loads((TAURI / "tauri.conf.json").read_text())["bundle"]["fileAssociations"]
    configured = {(ext, entry["name"]) for entry in associations for ext in entry["ext"]}
    hooks = (TAURI / "windows" / "hooks.nsh").read_text()
    listed = set(re.findall(r'!insertmacro \$\{MACRO\} "([^"]+)" "([^"]+)"', hooks))

    # One missing would be left pointing at a deleted class after an update and an uninstall.
    assert listed == configured


def test_the_per_user_installer_avoids_the_data_folder() -> None:
    windows = json.loads((TAURI / "tauri.windows.conf.json").read_text())["bundle"]["windows"]
    hooks = (TAURI / "windows" / "hooks.nsh").read_text()

    assert windows["nsis"]["installMode"] == "currentUser"
    # Tauri's per-user default is <LOCALAPPDATA>\<productName>, which is Reframe's data folder.
    product = json.loads((TAURI / "tauri.conf.json").read_text())["productName"]
    assert f'${{If}} $INSTDIR == "$LOCALAPPDATA\\{product}"' in hooks
    assert f'StrCpy $INSTDIR "$LOCALAPPDATA\\Programs\\{product}"' in hooks


CHECK = REPO_ROOT / "desktop" / "packaging" / "windows" / "no-ffmpeg-check.py"


@pytest.fixture
def no_ffmpeg_check() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("no_ffmpeg_check", CHECK)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _package(root: Path, *extra: str) -> Path:
    """An installed Reframe without FFmpeg (the files that 7-Zip or ``msiexec /a`` extract)."""
    for rel in (
        "Reframe.exe",
        "resources/sidecar/reframe-sidecar.exe",
        "resources/sidecar/_internal/python314.dll",
        "resources/sidecar/_internal/reframe/tools/ffmpeg.toml",
        "resources/sidecar/_internal/avrt.dll",
        "resources/tools/README.txt",
        *extra,
    ):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(b"x")
    return root


def test_the_ffmpeg_check_passes_a_package_without_ffmpeg(
    tmp_path: Path, no_ffmpeg_check: types.ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    nsis, msi = _package(tmp_path / "nsis"), _package(tmp_path / "msi")

    assert no_ffmpeg_check.main([str(nsis), str(msi)]) == 0
    assert capsys.readouterr().out.splitlines() == [
        f"{nsis}: no FFmpeg (2 .exe files)",
        f"{msi}: no FFmpeg (2 .exe files)",
    ]


@pytest.mark.parametrize(
    "rel",
    [
        "resources/tools/ffmpeg/bin/ffmpeg.exe",
        "bin/FFPROBE.EXE",
        "resources/tools/ffmpeg/bin/avcodec-62.dll",
        "avformat-62.dll",
        "resources/tools/ffmpeg/LICENSE.txt",
    ],
)
def test_the_ffmpeg_check_fails_a_package_with_ffmpeg(
    tmp_path: Path, no_ffmpeg_check: types.ModuleType, capsys: pytest.CaptureFixture[str], rel: str
) -> None:
    clean = _package(tmp_path / "clean")
    package = _package(tmp_path / "package", rel)

    assert no_ffmpeg_check.main([str(clean), str(package)]) == 1
    errors = capsys.readouterr().err.splitlines()
    assert errors
    assert all(line.startswith("::error::FFmpeg in the package: ") for line in errors)
    assert any(str(package / Path(rel).parts[0]) in line for line in errors)


def test_an_empty_or_failed_extraction_is_no_pass(
    tmp_path: Path, no_ffmpeg_check: types.ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    assert no_ffmpeg_check.main([str(empty), str(tmp_path / "missing")]) == 1
    assert capsys.readouterr().err.splitlines() == [
        f"::error::{empty} holds no .exe: not a package's contents",
        f"::error::{tmp_path / 'missing'} holds no .exe: not a package's contents",
    ]


def _windows_job() -> str:
    workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    return workflow.split("\n  windows:\n", 1)[1].split("\n  docker:\n", 1)[0]


def test_the_release_checks_the_windows_layout_and_both_installers_for_ffmpeg() -> None:
    job = _windows_job()
    check = "uv run python desktop/packaging/windows/no-ffmpeg-check.py"
    layout = job.index(f"{check} desktop/src-tauri/resources")
    assert job.index("desktop/sidecar/build.py") < layout < job.index("npx tauri build")
    installers = job.index(f'{check} "$work\\nsis" "$work\\msi"')
    assert job.index("npx tauri build") < installers < job.index("actions/upload-artifact")
    extraction = job[job.index("npx tauri build") : installers]
    assert "& 7z x -y" in extraction  # NSIS
    assert "'/a'" in extraction  # MSI: an administrative install extracts the files
