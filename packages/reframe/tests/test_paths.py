"""reframe.paths: user folders and bundled tool roots."""

from __future__ import annotations

from pathlib import Path

import platformdirs
import pytest

from reframe import paths


def test_env_variables_override_the_folders(tmp_path: Path) -> None:
    env = {
        "REFRAME_CONFIG_DIR": str(tmp_path / "c"),
        "REFRAME_DATA_DIR": str(tmp_path / "d"),
        "REFRAME_CACHE_DIR": str(tmp_path / "x"),
    }
    assert paths.config_dir(env) == tmp_path / "c"
    assert paths.data_dir(env) == tmp_path / "d"
    assert paths.cache_dir(env) == tmp_path / "x"


def test_defaults_come_from_platformdirs() -> None:
    assert paths.config_dir({}) == platformdirs.user_config_path(paths.APP_NAME, appauthor=False)
    assert paths.data_dir({}) == platformdirs.user_data_path(paths.APP_NAME, appauthor=False)
    assert paths.cache_dir({"REFRAME_CACHE_DIR": "  "}) == platformdirs.user_cache_path(
        paths.APP_NAME, appauthor=False
    )


def test_relative_override_is_made_absolute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert paths.data_dir({"REFRAME_DATA_DIR": "rel"}) == tmp_path / "rel"


def test_default_environment_is_os_environ(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("REFRAME_DATA_DIR", str(tmp_path))
    assert paths.data_dir() == tmp_path


def test_bundled_roots_from_source_on_linux(tmp_path: Path) -> None:
    roots = paths.bundled_tool_roots(
        environ={"REFRAME_DATA_DIR": str(tmp_path)}, frozen=False, platform="linux"
    )
    assert roots == [
        Path("/usr/lib/reframe/tools"),
        Path("/opt/reframe/tools"),
        tmp_path / "tools",
    ]


def test_bundled_roots_of_a_frozen_app_on_windows(tmp_path: Path) -> None:
    exe = tmp_path / "Reframe" / "resources" / "sidecar" / "reframe-server.exe"
    roots = paths.bundled_tool_roots(
        environ={"REFRAME_DATA_DIR": str(tmp_path / "data")},
        executable=str(exe),
        frozen=True,
        platform="win32",
    )
    assert roots == [
        exe.parent / "tools",
        tmp_path / "Reframe" / "resources" / "tools",  # the Tauri layout
        tmp_path / "data" / "tools",
    ]


def test_bundled_roots_have_no_duplicates(tmp_path: Path) -> None:
    exe = tmp_path / "app" / "reframe-server"
    roots = paths.bundled_tool_roots(
        environ={"REFRAME_DATA_DIR": str(tmp_path / "app")},
        executable=str(exe),
        frozen=True,
        platform="linux",
    )
    assert roots.count(tmp_path / "app" / "tools") == 1
    assert roots[0] == tmp_path / "app" / "tools"


def test_bundled_subdirs() -> None:
    assert paths.BUNDLED_SUBDIRS["ffmpeg"] == paths.BUNDLED_SUBDIRS["ffprobe"] == "ffmpeg"
