"""The Windows installer's hooks against the bundle settings they depend on."""

from __future__ import annotations

import json
import re
from pathlib import Path

TAURI = Path(__file__).resolve().parents[2] / "desktop" / "src-tauri"


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
