"""Tool discovery: search order, origins, ffprobe next to ffmpeg, broken overrides."""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

from reframe.models import RemoveOp, ToolOrigin, ToolStatus
from reframe.tools import discovery
from reframe.tools.discovery import (
    ALLOW_SCRIPT_TOOLS_ENV,
    TOOL_NAMES,
    check_tool,
    discover_tools,
    discover_tools_sync,
    locate_tools,
)
from reframe_testing import fake_tools as ft

WINDOWS = sys.platform == "win32"


@pytest.fixture(autouse=True)
def _isolate_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("REFRAME_") and not key.startswith("REFRAME_FAKE_"):
            monkeypatch.delenv(key)
    monkeypatch.delenv("LIBVA_DRIVERS_PATH", raising=False)


def _script_tool(directory: Path, name: str, text: str, exit_code: int = 0) -> Path:
    """An executable ``name`` (``name.cmd`` on Windows) that prints ``text``."""
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / f"_{name}_impl.py"
    script.write_text(
        f"import sys\nsys.stdout.write({text!r})\nsys.exit({exit_code})\n", encoding="utf-8"
    )
    if WINDOWS:
        launcher = directory / f"{name}.cmd"
        launcher.write_text(f'@"{ft.PYTHON}" -I "{script}" %*\r\n', encoding="utf-8")
        return launcher
    launcher = directory / name
    launcher.write_text(
        f'#!/bin/sh\nexec {shlex.quote(ft.PYTHON)} -I {shlex.quote(str(script))} "$@"\n',
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    return launcher


def _fake(directory: Path, *rules: ft.Rule) -> ft.FakeTools:
    return ft.make_fake_tools(directory, ft.Scenario(list(rules)))


def _linux_build(directory: Path) -> ft.FakeTools:
    """Tools named as on Linux, for ``platform="linux"`` on any OS (they are found, not run)."""
    return ft.make_fake_tools(directory, platform="linux")


def _env(**values: str) -> dict[str, str]:
    # On Windows the fake tools are .cmd launchers: allow script tools (test-only opt-in).
    env = {"PATHEXT": ".COM;.EXE;.BAT;.CMD", ALLOW_SCRIPT_TOOLS_ENV: "1"} if WINDOWS else {}
    env.update(values)
    return env


MKVPROPEDIT_OUT = "mkvpropedit v101.0 ('Time To Turn') 64-bit\n"
MEDIAINFO_OUT = "MediaInfo Command line, \nMediaInfoLib - v24.06\n"
TOO_OLD = ft.Rule(argv_has=["-version"], actions=[ft.version("n6.1.2-21-gac60bc2bb0-20250131")])


@pytest.fixture
def empty_path(tmp_path: Path) -> str:
    folder = tmp_path / "empty-path"
    folder.mkdir()
    return str(folder)


@pytest.mark.anyio
async def test_env_override_wins_over_settings_bundled_and_path(
    tmp_path: Path, empty_path: str
) -> None:
    env_tools = _fake(tmp_path / "env")
    settings_tools = _fake(tmp_path / "settings")
    _fake(tmp_path / "root" / "ffmpeg" / "bin")
    path_dir = tmp_path / "path"
    _fake(path_dir)
    tools = await discover_tools(
        {"ffmpeg": str(settings_tools.ffmpeg)},
        environ=_env(REFRAME_FFMPEG=str(env_tools.ffmpeg)),
        bundled_roots=[tmp_path / "root"],
        search_path=str(path_dir),
    )
    assert tools.ffmpeg.status is ToolStatus.FOUND
    assert tools.ffmpeg.origin is ToolOrigin.ENV
    assert tools.ffmpeg.path == env_tools.ffmpeg
    assert tools.ffmpeg.env_var == "REFRAME_FFMPEG"
    assert tools.ffmpeg.version == "n9.0.2-17-g2a571b6068-20260930"
    assert tools.ffmpeg.release == "9.0.2"
    assert tools.ffmpeg.release_series == "9.0"
    assert "--enable-libx265" in tools.ffmpeg.build_flags
    assert tools.ffmpeg.library_versions["libavcodec"] == "63.1.102"
    assert tools.ffmpeg.fixes == []
    # ffprobe next to the overridden ffmpeg beats the bundled ffprobe.
    assert tools.ffprobe.origin is ToolOrigin.ENV
    assert tools.ffprobe.path == env_tools.ffprobe
    assert tools.ffprobe.next_to_ffmpeg
    assert tools.ffprobe.status is ToolStatus.FOUND


@pytest.mark.anyio
async def test_settings_path_wins_over_bundled(tmp_path: Path, empty_path: str) -> None:
    settings_tools = _fake(tmp_path / "custom")
    _fake(tmp_path / "root" / "ffmpeg" / "bin")
    tools = await discover_tools(
        {"ffmpeg": str(settings_tools.ffmpeg)},
        environ=_env(),
        bundled_roots=[tmp_path / "root"],
        search_path=empty_path,
    )
    assert tools.ffmpeg.origin is ToolOrigin.SETTINGS
    assert tools.ffmpeg.path == settings_tools.ffmpeg
    assert tools.ffmpeg.status is ToolStatus.FOUND
    assert tools.ffmpeg.fixes == []  # a fix only when something is wrong
    assert tools.ffprobe.origin is ToolOrigin.SETTINGS
    assert tools.ffprobe.next_to_ffmpeg
    assert tools.ffprobe.path == settings_tools.ffprobe


@pytest.mark.anyio
async def test_a_bundled_build_is_reported_per_family_while_an_override_works(
    tmp_path: Path, empty_path: str
) -> None:
    settings_tools = _fake(tmp_path / "custom")
    mkv = _script_tool(tmp_path / "m", "mkvpropedit", MKVPROPEDIT_OUT)
    root = tmp_path / "root"
    _fake(root / "ffmpeg" / "bin")
    _script_tool(root / "mediainfo", "mediainfo", MEDIAINFO_OUT)
    tools = await discover_tools(
        {"ffmpeg": str(settings_tools.ffmpeg), "mediainfo": str(tmp_path / "gone")},
        environ=_env(REFRAME_MKVPROPEDIT=str(mkv)),
        bundled_roots=[root],
        search_path=empty_path,
    )
    assert tools.ffmpeg.origin is ToolOrigin.SETTINGS
    assert tools.ffmpeg.status is ToolStatus.FOUND
    assert tools.ffmpeg.bundled
    assert tools.ffprobe.bundled
    assert tools.mediainfo.status is ToolStatus.MISSING
    assert tools.mediainfo.bundled
    assert tools.mkvpropedit.origin is ToolOrigin.ENV
    assert not tools.mkvpropedit.bundled


def test_no_bundled_build_is_reported_without_one(tmp_path: Path) -> None:
    path_dir = tmp_path / "path"
    _fake(path_dir)
    tools = discover_tools_sync(
        environ=_env(), bundled_roots=[tmp_path / "no-root"], search_path=str(path_dir)
    )
    assert tools.ffmpeg.origin is ToolOrigin.PATH
    assert not tools.ffmpeg.bundled
    assert not tools.ffprobe.bundled


@pytest.mark.anyio
async def test_bundled_wins_over_path(tmp_path: Path) -> None:
    bundled = _fake(tmp_path / "root" / "ffmpeg" / "bin")
    path_dir = tmp_path / "path"
    _fake(path_dir)
    tools = await discover_tools(
        environ=_env(), bundled_roots=[tmp_path / "root"], search_path=str(path_dir)
    )
    for info in (tools.ffmpeg, tools.ffprobe):
        assert info.origin is ToolOrigin.BUNDLED
        assert info.status is ToolStatus.FOUND
        assert not info.next_to_ffmpeg
    assert tools.ffmpeg.path == bundled.ffmpeg
    assert tools.ffprobe.path == bundled.ffprobe


def test_path_is_used_without_a_bundled_build(tmp_path: Path) -> None:
    path_dir = tmp_path / "path"
    on_path = _fake(path_dir)
    tools = discover_tools_sync(
        environ=_env(), bundled_roots=[tmp_path / "no-root"], search_path=str(path_dir)
    )
    assert tools.ffmpeg.origin is ToolOrigin.PATH
    assert tools.ffmpeg.path is not None
    assert os.path.samefile(tools.ffmpeg.path, on_path.ffmpeg)
    assert tools.ffprobe.origin is ToolOrigin.PATH
    assert tools.ffmpeg.env == {}  # LIBVA_DRIVERS_PATH only for the bundled build


def test_bundled_build_in_the_folder_itself(tmp_path: Path, empty_path: str) -> None:
    bundled = _fake(tmp_path / "root" / "ffmpeg")  # no bin/ folder
    located = locate_tools(
        environ=_env(), bundled_roots=[tmp_path / "root"], search_path=empty_path
    )
    assert located["ffmpeg"].path == bundled.ffmpeg
    assert located["ffmpeg"].origin is ToolOrigin.BUNDLED


def test_bin_folder_before_the_folder_itself(tmp_path: Path, empty_path: str) -> None:
    in_bin = _fake(tmp_path / "root" / "ffmpeg" / "bin")
    _fake(tmp_path / "root" / "ffmpeg")
    located = locate_tools(
        environ=_env(), bundled_roots=[tmp_path / "root"], search_path=empty_path
    )
    assert located["ffmpeg"].path == in_bin.ffmpeg


def test_first_bundled_root_wins(tmp_path: Path, empty_path: str) -> None:
    first = _fake(tmp_path / "a" / "ffmpeg" / "bin")
    _fake(tmp_path / "b" / "ffmpeg" / "bin")
    located = locate_tools(
        environ=_env(),
        bundled_roots=[tmp_path / "missing", tmp_path / "a", tmp_path / "b"],
        search_path=empty_path,
    )
    assert located["ffmpeg"].path == first.ffmpeg
    assert located["ffprobe"].path == first.ffprobe


@pytest.mark.anyio
async def test_damaged_bundled_build_does_not_fall_back_to_path(tmp_path: Path) -> None:
    bundled = _fake(tmp_path / "root" / "ffmpeg" / "bin")
    bundled.ffprobe.unlink()
    path_dir = tmp_path / "path"
    _fake(path_dir)
    tools = await discover_tools(
        environ=_env(), bundled_roots=[tmp_path / "root"], search_path=str(path_dir)
    )
    assert tools.ffmpeg.origin is ToolOrigin.BUNDLED
    assert tools.ffmpeg.status is ToolStatus.FOUND
    assert tools.ffprobe.status is ToolStatus.MISSING
    assert tools.ffprobe.origin is ToolOrigin.BUNDLED
    assert tools.ffprobe.path is None
    assert tools.ffprobe.reason is not None
    assert "damaged" in tools.ffprobe.reason
    assert tools.ffprobe.bundled


@pytest.mark.anyio
async def test_mkvpropedit_from_path_next_to_a_bundled_ffmpeg(tmp_path: Path) -> None:
    _fake(tmp_path / "root" / "ffmpeg" / "bin")
    path_dir = tmp_path / "path"
    _script_tool(path_dir, "mkvpropedit", MKVPROPEDIT_OUT)
    _script_tool(path_dir, "mediainfo", MEDIAINFO_OUT)
    tools = await discover_tools(
        environ=_env(), bundled_roots=[tmp_path / "root"], search_path=str(path_dir)
    )
    assert tools.mkvpropedit.origin is ToolOrigin.PATH
    assert tools.mkvpropedit.status is ToolStatus.FOUND
    assert tools.mkvpropedit.version == "101.0"
    assert tools.mediainfo.origin is ToolOrigin.PATH
    assert tools.mediainfo.version == "24.06"


@pytest.mark.anyio
async def test_bundled_mkvpropedit_and_mediainfo(tmp_path: Path, empty_path: str) -> None:
    root = tmp_path / "root"
    _script_tool(root / "mkvtoolnix", "mkvpropedit", MKVPROPEDIT_OUT)
    _script_tool(root / "mediainfo" / "bin", "mediainfo", MEDIAINFO_OUT)
    tools = await discover_tools(environ=_env(), bundled_roots=[root], search_path=empty_path)
    assert tools.mkvpropedit.origin is ToolOrigin.BUNDLED
    assert tools.mkvpropedit.status is ToolStatus.FOUND
    assert tools.mediainfo.origin is ToolOrigin.BUNDLED
    assert tools.mediainfo.status is ToolStatus.FOUND
    assert tools.ffmpeg.status is ToolStatus.MISSING


@pytest.mark.anyio
async def test_env_overrides_for_mkvpropedit_and_mediainfo(tmp_path: Path, empty_path: str) -> None:
    mkv = _script_tool(tmp_path / "m", "mkvpropedit", MKVPROPEDIT_OUT)
    mi = _script_tool(tmp_path / "i", "mediainfo", MEDIAINFO_OUT)
    tools = await discover_tools(
        environ=_env(REFRAME_MKVPROPEDIT=str(mkv), REFRAME_MEDIAINFO=str(mi)),
        bundled_roots=[],
        search_path=empty_path,
    )
    assert tools.mkvpropedit.origin is ToolOrigin.ENV
    assert tools.mkvpropedit.env_var == "REFRAME_MKVPROPEDIT"
    assert tools.mediainfo.origin is ToolOrigin.ENV
    assert tools.mediainfo.status is ToolStatus.FOUND


@pytest.mark.anyio
async def test_nothing_found(tmp_path: Path, empty_path: str) -> None:
    tools = await discover_tools(environ=_env(), bundled_roots=[], search_path=empty_path)
    for name in TOOL_NAMES:
        info = tools.get(name)
        assert info.status is ToolStatus.MISSING
        assert info.origin is None
        assert info.path is None
        assert info.reason
    assert tools.ffmpeg.reason is not None
    assert "REFRAME_FFMPEG" in tools.ffmpeg.reason
    assert tools.mediainfo.reason is not None
    assert "optional" in tools.mediainfo.reason
    assert "REFRAME_MEDIAINFO" in tools.mediainfo.reason


@pytest.mark.anyio
async def test_own_ffprobe_override_beats_the_sibling(tmp_path: Path, empty_path: str) -> None:
    a = _fake(tmp_path / "a")
    b = _fake(tmp_path / "b")
    tools = await discover_tools(
        {"ffprobe": str(b.ffprobe)},
        environ=_env(REFRAME_FFMPEG=str(a.ffmpeg)),
        bundled_roots=[],
        search_path=empty_path,
    )
    assert tools.ffprobe.path == b.ffprobe
    assert tools.ffprobe.origin is ToolOrigin.SETTINGS
    assert not tools.ffprobe.next_to_ffmpeg


def test_no_sibling_falls_back_to_bundled_ffprobe(tmp_path: Path, empty_path: str) -> None:
    custom = _fake(tmp_path / "custom")
    custom.ffprobe.unlink()
    bundled = _fake(tmp_path / "root" / "ffmpeg" / "bin")
    located = locate_tools(
        {"ffmpeg": str(custom.ffmpeg)},
        environ=_env(),
        bundled_roots=[tmp_path / "root"],
        search_path=empty_path,
    )
    assert located["ffmpeg"].origin is ToolOrigin.SETTINGS
    assert located["ffprobe"].origin is ToolOrigin.BUNDLED
    assert located["ffprobe"].path == bundled.ffprobe


def test_no_sibling_search_next_to_a_missing_override(tmp_path: Path, empty_path: str) -> None:
    bundled = _fake(tmp_path / "root" / "ffmpeg" / "bin")
    located = locate_tools(
        environ=_env(REFRAME_FFMPEG=str(tmp_path / "gone" / "ffmpeg")),
        bundled_roots=[tmp_path / "root"],
        search_path=empty_path,
    )
    assert located["ffmpeg"].problem is not None
    assert located["ffprobe"].path == bundled.ffprobe


def test_sibling_with_a_renamed_ffmpeg(tmp_path: Path, empty_path: str) -> None:
    folder = tmp_path / "custom"
    ffmpeg = _script_tool(folder, "ffmpeg-9", "x")
    ffprobe = _script_tool(folder, "ffprobe-9", "x")
    located = locate_tools(
        {"ffmpeg": str(ffmpeg)}, environ=_env(), bundled_roots=[], search_path=empty_path
    )
    assert located["ffprobe"].path == ffprobe
    assert located["ffprobe"].next_to_ffmpeg


def _exe(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"MZ")
    return path


WIN_ENV = {"PATHEXT": ".COM;.EXE;.BAT;.CMD"}


def test_windows_accepts_only_exe(tmp_path: Path, empty_path: str) -> None:
    """On Windows only .exe programs are used (checked on Linux with platform="win32")."""
    custom = tmp_path / "custom"
    _exe(custom / "ffmpeg.cmd")
    _exe(custom / "ffprobe.cmd")
    bundled_bin = tmp_path / "root" / "ffmpeg" / "bin"
    _exe(bundled_bin / "ffmpeg.exe")
    _exe(bundled_bin / "ffprobe.exe")
    _exe(bundled_bin / "ffmpeg.cmd")  # never preferred, never used

    located = locate_tools(
        {"ffmpeg": str(custom / "ffmpeg.cmd")},
        environ=WIN_ENV,
        bundled_roots=[tmp_path / "root"],
        search_path=empty_path,
        platform="win32",
    )
    ffmpeg = located["ffmpeg"]
    assert ffmpeg.path == custom / "ffmpeg.cmd"
    assert ffmpeg.origin is ToolOrigin.SETTINGS  # reported, never silently replaced
    assert ffmpeg.problem is not None
    assert "not an .exe" in ffmpeg.problem
    assert ffmpeg.problem_status is ToolStatus.BROKEN
    assert [f.label for f in ffmpeg.fixes] == ["Use bundled FFmpeg"]
    # No sibling search next to a rejected override: the bundled ffprobe.exe.
    assert located["ffprobe"].path == bundled_bin / "ffprobe.exe"

    located = locate_tools(
        environ=WIN_ENV, bundled_roots=[tmp_path / "root"], search_path=empty_path, platform="win32"
    )
    assert located["ffmpeg"].path == bundled_bin / "ffmpeg.exe"
    assert located["ffprobe"].path == bundled_bin / "ffprobe.exe"
    assert located["ffmpeg"].env == {}  # no LIBVA_DRIVERS_PATH on Windows


@pytest.mark.anyio
async def test_windows_script_override_is_broken(tmp_path: Path, empty_path: str) -> None:
    script = _exe(tmp_path / "tools" / "mkvpropedit.bat")
    info = await check_tool(
        locate_tools(
            {"mkvpropedit": str(script)},
            environ=WIN_ENV,
            bundled_roots=[],
            search_path=empty_path,
            platform="win32",
        )["mkvpropedit"]
    )
    assert info.status is ToolStatus.BROKEN
    assert info.reason is not None
    assert "cmd.exe" in info.reason


def test_windows_path_search_ignores_scripts(tmp_path: Path) -> None:
    only_scripts = tmp_path / "scripts"
    _exe(only_scripts / "mkvpropedit.cmd")
    _exe(only_scripts / "mkvpropedit.bat")
    with_exe = tmp_path / "exe"
    _exe(with_exe / "mkvpropedit.exe")
    _exe(with_exe / "mkvpropedit.cmd")
    located = locate_tools(
        environ=WIN_ENV,
        bundled_roots=[],
        search_path=f"{only_scripts};{with_exe}",
        platform="win32",
    )
    assert located["mkvpropedit"].path == with_exe / "mkvpropedit.exe"
    assert located["mkvpropedit"].origin is ToolOrigin.PATH


def test_windows_script_tools_with_the_test_opt_in(tmp_path: Path, empty_path: str) -> None:
    custom = tmp_path / "custom"
    _exe(custom / "ffmpeg.cmd")
    _exe(custom / "ffprobe.cmd")
    env = {**WIN_ENV, ALLOW_SCRIPT_TOOLS_ENV: "1"}
    located = locate_tools(
        {"ffmpeg": str(custom / "ffmpeg.cmd")},
        environ=env,
        bundled_roots=[],
        search_path=empty_path,
        platform="win32",
    )
    assert located["ffmpeg"].problem is None
    assert located["ffprobe"].path == custom / "ffprobe.cmd"
    assert located["ffprobe"].next_to_ffmpeg
    scripts = tmp_path / "path"
    _exe(scripts / "mediainfo.cmd")
    located = locate_tools(
        environ=env, bundled_roots=[], search_path=str(scripts), platform="win32"
    )
    assert located["mediainfo"].path == scripts / "mediainfo.cmd"
    for off in ("0", "false", "no", ""):
        off_env = {**WIN_ENV, ALLOW_SCRIPT_TOOLS_ENV: off}
        located = locate_tools(
            environ=off_env, bundled_roots=[], search_path=str(scripts), platform="win32"
        )
        assert located["mediainfo"].path is None


def test_windows_folder_override_and_renamed_sibling(tmp_path: Path, empty_path: str) -> None:
    exe_dir = tmp_path / "exe"
    _exe(exe_dir / "ffmpeg.exe")
    _exe(exe_dir / "ffprobe.exe")
    located = locate_tools(
        environ={**WIN_ENV, "REFRAME_FFMPEG": str(exe_dir)},
        bundled_roots=[],
        search_path=empty_path,
        platform="win32",
    )
    assert located["ffmpeg"].path == exe_dir / "ffmpeg.exe"
    assert located["ffprobe"].path == exe_dir / "ffprobe.exe"

    renamed = tmp_path / "renamed"
    _exe(renamed / "ffmpeg-9.exe")
    _exe(renamed / "ffprobe-9.exe")
    located = locate_tools(
        {"ffmpeg": str(renamed / "ffmpeg-9.exe")},
        environ=WIN_ENV,
        bundled_roots=[],
        search_path=empty_path,
        platform="win32",
    )
    assert located["ffprobe"].path == renamed / "ffprobe-9.exe"


def test_path_search_never_uses_the_current_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """shutil.which searches the current folder first on Windows; discovery never does,
    and relative PATH entries are skipped."""
    cwd = tmp_path / "cwd"
    _fake(cwd)
    _exe(cwd / "ffmpeg.exe")
    _exe(cwd / "ffprobe.exe")
    monkeypatch.chdir(cwd)
    for platform in ("win32", "linux"):
        for search_path in ("", ".", "relative/bin", ";" if platform == "win32" else ":"):
            located = locate_tools(
                environ=WIN_ENV, bundled_roots=[], search_path=search_path, platform=platform
            )
            assert located["ffmpeg"].path is None, (platform, search_path)
    # Without PATH in the environment nothing is searched (not os.defpath, which has ".").
    located = locate_tools(environ={}, bundled_roots=[], platform="win32")
    assert located["ffmpeg"].path is None


@pytest.mark.skipif(WINDOWS, reason="POSIX file modes")
def test_path_search_skips_files_that_are_not_executable(tmp_path: Path) -> None:
    folder = tmp_path / "bin"
    folder.mkdir()
    (folder / "mkvpropedit").write_text("#!/bin/sh\n", encoding="utf-8")
    (folder / "mkvpropedit").chmod(0o644)
    located = locate_tools(environ={}, bundled_roots=[], search_path=str(folder))
    assert located["mkvpropedit"].path is None


def _use_bundled_patch(tool: str) -> list[RemoveOp]:
    return [RemoveOp(path=f"/tools/{tool}")]


@pytest.mark.anyio
async def test_missing_settings_path_offers_use_bundled(tmp_path: Path, empty_path: str) -> None:
    bundled = _fake(tmp_path / "root" / "ffmpeg" / "bin")
    bad = tmp_path / "nowhere" / "ffmpeg"
    tools = await discover_tools(
        {"ffmpeg": str(bad)},
        environ=_env(),
        bundled_roots=[tmp_path / "root"],
        search_path=empty_path,
    )
    info = tools.ffmpeg
    assert info.status is ToolStatus.MISSING
    assert info.origin is ToolOrigin.SETTINGS  # never silently the bundled build
    assert info.path == bad
    assert info.reason is not None
    assert str(bad) in info.reason
    assert [f.label for f in info.fixes] == ["Use bundled FFmpeg"]
    assert info.fixes[0].target == "settings"
    assert info.fixes[0].patch == _use_bundled_patch("ffmpeg")
    # ffprobe has no override and nothing next to the bad path: the bundled one.
    assert tools.ffprobe.path == bundled.ffprobe


@pytest.mark.anyio
async def test_missing_settings_path_without_bundled_build(tmp_path: Path, empty_path: str) -> None:
    tools = await discover_tools(
        {"mkvpropedit": str(tmp_path / "x")},
        environ=_env(),
        bundled_roots=[],
        search_path=empty_path,
    )
    assert tools.mkvpropedit.status is ToolStatus.MISSING
    assert [f.label for f in tools.mkvpropedit.fixes] == ["Remove the path override"]
    assert tools.mkvpropedit.fixes[0].patch == _use_bundled_patch("mkvpropedit")


@pytest.mark.anyio
async def test_missing_env_override_cannot_be_fixed_in_the_app(
    tmp_path: Path, empty_path: str
) -> None:
    _fake(tmp_path / "root" / "ffmpeg" / "bin")
    bad = tmp_path / "nowhere" / "ffmpeg"
    tools = await discover_tools(
        environ=_env(REFRAME_FFMPEG=str(bad)),
        bundled_roots=[tmp_path / "root"],
        search_path=empty_path,
    )
    info = tools.ffmpeg
    assert info.status is ToolStatus.MISSING
    assert info.origin is ToolOrigin.ENV
    assert info.fixes == []
    assert info.reason is not None
    assert "REFRAME_FFMPEG" in info.reason
    assert "cannot be changed in Reframe" in info.reason


@pytest.mark.anyio
async def test_folder_override_without_binary(tmp_path: Path, empty_path: str) -> None:
    folder = tmp_path / "empty-build"
    folder.mkdir()
    tools = await discover_tools(
        {"ffmpeg": str(folder)}, environ=_env(), bundled_roots=[], search_path=empty_path
    )
    assert tools.ffmpeg.status is ToolStatus.MISSING
    assert tools.ffmpeg.reason is not None
    assert "no ffmpeg executable" in tools.ffmpeg.reason


@pytest.mark.anyio
async def test_folder_override_with_bin(tmp_path: Path, empty_path: str) -> None:
    build = _fake(tmp_path / "my-build" / "bin")
    tools = await discover_tools(
        environ=_env(REFRAME_FFMPEG=str(tmp_path / "my-build")),
        bundled_roots=[],
        search_path=empty_path,
    )
    assert tools.ffmpeg.status is ToolStatus.FOUND
    assert tools.ffmpeg.path == build.ffmpeg
    assert tools.ffprobe.path == build.ffprobe
    assert tools.ffprobe.next_to_ffmpeg


@pytest.mark.anyio
async def test_too_old_settings_override(tmp_path: Path, empty_path: str) -> None:
    _fake(tmp_path / "root" / "ffmpeg" / "bin")
    old = _fake(tmp_path / "old", TOO_OLD)
    tools = await discover_tools(
        {"ffmpeg": str(old.ffmpeg)},
        environ=_env(),
        bundled_roots=[tmp_path / "root"],
        search_path=empty_path,
    )
    info = tools.ffmpeg
    assert info.status is ToolStatus.TOO_OLD
    assert info.origin is ToolOrigin.SETTINGS
    assert info.release == "6.1.2"
    assert info.reason is not None
    assert "7.0" in info.reason
    assert [f.label for f in info.fixes] == ["Use bundled FFmpeg"]
    # The sibling ffprobe of the old build is too old as well, with the same fix.
    assert tools.ffprobe.status is ToolStatus.TOO_OLD
    assert tools.ffprobe.next_to_ffmpeg
    assert tools.ffprobe.fixes == info.fixes


@pytest.mark.anyio
async def test_too_old_env_override(tmp_path: Path, empty_path: str) -> None:
    old = _fake(tmp_path / "old", TOO_OLD)
    tools = await discover_tools(
        environ=_env(REFRAME_FFMPEG=str(old.ffmpeg)), bundled_roots=[], search_path=empty_path
    )
    assert tools.ffmpeg.status is ToolStatus.TOO_OLD
    assert tools.ffmpeg.fixes == []
    assert tools.ffmpeg.reason is not None
    assert "REFRAME_FFMPEG" in tools.ffmpeg.reason


@pytest.mark.anyio
async def test_broken_override_exit_code(tmp_path: Path, empty_path: str) -> None:
    broken = _fake(
        tmp_path / "broken",
        ft.Rule(
            argv_has=["-version"],
            exit_code=127,
            actions=[ft.stderr("error while loading shared libraries: libavdevice.so.63\n")],
        ),
    )
    tools = await discover_tools(
        {"ffmpeg": str(broken.ffmpeg)}, environ=_env(), bundled_roots=[], search_path=empty_path
    )
    info = tools.ffmpeg
    assert info.status is ToolStatus.BROKEN
    assert info.reason is not None
    assert "code 127" in info.reason
    assert "libavdevice.so.63" in info.reason
    assert info.fixes[0].patch == _use_bundled_patch("ffmpeg")


@pytest.mark.anyio
async def test_broken_override_crash(tmp_path: Path, empty_path: str) -> None:
    broken = _fake(tmp_path / "broken", ft.Rule(argv_has=["-version"], actions=[ft.crash()]))
    tools = await discover_tools(
        {"ffmpeg": str(broken.ffmpeg)}, environ=_env(), bundled_roots=[], search_path=empty_path
    )
    assert tools.ffmpeg.status is ToolStatus.BROKEN


@pytest.mark.anyio
async def test_override_that_is_not_ffmpeg(tmp_path: Path, empty_path: str) -> None:
    other = _fake(
        tmp_path / "other", ft.Rule(argv_has=["-version"], actions=[ft.stdout("hello\n")])
    )
    tools = await discover_tools(
        {"ffmpeg": str(other.ffmpeg)}, environ=_env(), bundled_roots=[], search_path=empty_path
    )
    assert tools.ffmpeg.status is ToolStatus.BROKEN
    assert tools.ffmpeg.reason is not None
    assert "does not look like ffmpeg" in tools.ffmpeg.reason


@pytest.mark.anyio
async def test_ffprobe_override_pointing_at_ffmpeg(tmp_path: Path, empty_path: str) -> None:
    fake = _fake(tmp_path / "f")
    tools = await discover_tools(
        {"ffprobe": str(fake.ffmpeg)}, environ=_env(), bundled_roots=[], search_path=empty_path
    )
    assert tools.ffprobe.status is ToolStatus.BROKEN  # it answers "ffmpeg version …"


@pytest.mark.anyio
async def test_hanging_override_times_out(tmp_path: Path, empty_path: str) -> None:
    slow = _fake(tmp_path / "slow", ft.Rule(argv_has=["-version"], actions=[ft.hang()]))
    try:
        tools = await discover_tools(
            {"ffmpeg": str(slow.ffmpeg)},
            environ=_env(),
            bundled_roots=[],
            search_path=empty_path,
            timeout=1,
        )
    finally:
        slow.kill_leftovers()
    assert tools.ffmpeg.status is ToolStatus.BROKEN
    assert tools.ffmpeg.reason is not None
    assert "within 1 s" in tools.ffmpeg.reason


@pytest.mark.skipif(WINDOWS, reason="POSIX file modes")
@pytest.mark.anyio
async def test_not_executable_override(tmp_path: Path, empty_path: str) -> None:
    fake = _fake(tmp_path / "f")
    fake.ffmpeg.chmod(0o644)
    tools = await discover_tools(
        {"ffmpeg": str(fake.ffmpeg)}, environ=_env(), bundled_roots=[], search_path=empty_path
    )
    assert tools.ffmpeg.status is ToolStatus.BROKEN
    assert tools.ffmpeg.reason is not None
    assert "cannot run" in tools.ffmpeg.reason
    assert "PermissionError" in tools.ffmpeg.reason


@pytest.mark.anyio
async def test_broken_mkvpropedit(tmp_path: Path, empty_path: str) -> None:
    junk = _script_tool(tmp_path / "j", "mkvpropedit", "something else\n")
    tools = await discover_tools(
        {"mkvpropedit": str(junk)}, environ=_env(), bundled_roots=[], search_path=empty_path
    )
    assert tools.mkvpropedit.status is ToolStatus.BROKEN
    assert tools.mkvpropedit.reason is not None
    assert "does not look like mkvpropedit" in tools.mkvpropedit.reason


@pytest.mark.anyio
async def test_master_build_is_accepted(tmp_path: Path, empty_path: str) -> None:
    master = _fake(
        tmp_path / "master",
        ft.Rule(argv_has=["-version"], actions=[ft.version("N-127032-g6ae491a26c-20260930")]),
    )
    tools = await discover_tools(
        {"ffmpeg": str(master.ffmpeg)}, environ=_env(), bundled_roots=[], search_path=empty_path
    )
    assert tools.ffmpeg.status is ToolStatus.FOUND
    assert tools.ffmpeg.release is None
    assert tools.ffmpeg.release_series == "9.0"  # from libavcodec 63


@pytest.mark.anyio
async def test_unknown_version_is_found_with_a_note(tmp_path: Path, empty_path: str) -> None:
    odd = _fake(
        tmp_path / "odd",
        ft.Rule(argv_has=["-version"], actions=[ft.stdout("ffmpeg version custom-build\n")]),
    )
    tools = await discover_tools(
        {"ffmpeg": str(odd.ffmpeg)}, environ=_env(), bundled_roots=[], search_path=empty_path
    )
    assert tools.ffmpeg.status is ToolStatus.FOUND
    assert tools.ffmpeg.reason is not None
    assert "could not be checked" in tools.ffmpeg.reason


@pytest.fixture
def driver_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    first = tmp_path / "dri-missing"
    second = tmp_path / "dri"
    second.mkdir()
    monkeypatch.setattr(discovery, "LIBVA_DRIVER_DIRS", (first, second))
    return first, second


def test_libva_drivers_path_for_the_bundled_build(
    tmp_path: Path, empty_path: str, driver_dirs: tuple[Path, Path]
) -> None:
    _linux_build(tmp_path / "root" / "ffmpeg" / "bin")
    located = locate_tools(
        environ=_env(), bundled_roots=[tmp_path / "root"], search_path=empty_path, platform="linux"
    )
    assert located["ffmpeg"].env == {"LIBVA_DRIVERS_PATH": str(driver_dirs[1])}
    assert located["ffprobe"].env == {"LIBVA_DRIVERS_PATH": str(driver_dirs[1])}


def test_libva_drivers_path_names_every_driver_folder_in_order(
    tmp_path: Path, empty_path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirs = [tmp_path / "dri-freeworld", tmp_path / "missing", tmp_path / "dri"]
    dirs[0].mkdir()
    dirs[2].mkdir()
    monkeypatch.setattr(discovery, "LIBVA_DRIVER_DIRS", tuple(dirs))
    _linux_build(tmp_path / "root" / "ffmpeg" / "bin")
    located = locate_tools(
        environ=_env(), bundled_roots=[tmp_path / "root"], search_path=empty_path, platform="linux"
    )
    assert located["ffmpeg"].env == {"LIBVA_DRIVERS_PATH": f"{dirs[0]}:{dirs[2]}"}


def test_rpm_fusions_driver_folders_come_before_fedoras_own() -> None:
    """RPM Fusion's VA drivers replace Fedora's and live in these folders (Fedora's libva
    searches them in this order)."""
    names = [str(d) for d in discovery.LIBVA_DRIVER_DIRS]
    fedora = ["/usr/lib64/dri-nonfree", "/usr/lib64/dri-freeworld", "/usr/lib64/dri"]
    assert [n for n in names if n.startswith("/usr/lib64/")] == fedora


def test_libva_drivers_path_is_not_changed_when_set(
    tmp_path: Path, empty_path: str, driver_dirs: tuple[Path, Path]
) -> None:
    _linux_build(tmp_path / "root" / "ffmpeg" / "bin")
    located = locate_tools(
        environ=_env(LIBVA_DRIVERS_PATH="/custom/dri"),
        bundled_roots=[tmp_path / "root"],
        search_path=empty_path,
        platform="linux",
    )
    assert located["ffmpeg"].env == {}


def test_libva_drivers_path_not_for_overrides(
    tmp_path: Path, empty_path: str, driver_dirs: tuple[Path, Path]
) -> None:
    custom = _linux_build(tmp_path / "custom")
    located = locate_tools(
        environ=_env(REFRAME_FFMPEG=str(custom.ffmpeg)),
        bundled_roots=[],
        search_path=empty_path,
        platform="linux",
    )
    assert located["ffmpeg"].env == {}
    assert located["ffprobe"].env == {}


def test_libva_drivers_path_none_found(
    tmp_path: Path, empty_path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(discovery, "LIBVA_DRIVER_DIRS", (tmp_path / "x",))
    _linux_build(tmp_path / "root" / "ffmpeg" / "bin")
    located = locate_tools(
        environ=_env(), bundled_roots=[tmp_path / "root"], search_path=empty_path, platform="linux"
    )
    assert located["ffmpeg"].env == {}


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="LIBVA_DRIVERS_PATH is Linux only")
@pytest.mark.anyio
async def test_tool_env_reaches_the_version_check(
    tmp_path: Path, empty_path: str, driver_dirs: tuple[Path, Path]
) -> None:
    _fake(
        tmp_path / "root" / "ffmpeg" / "bin",
        ft.Rule(argv_has=["-version"], actions=[ft.version()]),
    )
    tools = await discover_tools(
        environ=_env(), bundled_roots=[tmp_path / "root"], search_path=empty_path
    )
    assert tools.ffmpeg.env == {"LIBVA_DRIVERS_PATH": str(driver_dirs[1])}
    assert tools.ffmpeg.status is ToolStatus.FOUND


def test_empty_env_variable_counts_as_unset(tmp_path: Path, empty_path: str) -> None:
    bundled = _fake(tmp_path / "root" / "ffmpeg" / "bin")
    located = locate_tools(
        {"ffmpeg": "  "},
        environ=_env(REFRAME_FFMPEG=""),
        bundled_roots=[tmp_path / "root"],
        search_path=empty_path,
    )
    assert located["ffmpeg"].origin is ToolOrigin.BUNDLED
    assert located["ffmpeg"].path == bundled.ffmpeg


def test_settings_as_a_model(tmp_path: Path, empty_path: str) -> None:
    class Paths(BaseModel):
        ffmpeg: str | None = None
        ffprobe: str | None = None

    custom = _fake(tmp_path / "custom")
    located = locate_tools(
        Paths(ffmpeg=str(custom.ffmpeg)), environ=_env(), bundled_roots=[], search_path=empty_path
    )
    assert located["ffmpeg"].origin is ToolOrigin.SETTINGS


def test_default_roots_use_the_data_dir(tmp_path: Path, empty_path: str) -> None:
    data = tmp_path / "data"
    bundled = _fake(data / "tools" / "ffmpeg" / "bin")
    located = locate_tools(environ=_env(REFRAME_DATA_DIR=str(data)), search_path=empty_path)
    assert located["ffmpeg"].origin is ToolOrigin.BUNDLED
    assert located["ffmpeg"].path == bundled.ffmpeg


@pytest.mark.anyio
async def test_check_tool_of_a_location_without_path() -> None:
    info = await check_tool(discovery.ToolLocation("ffmpeg", None, None))
    assert info.status is ToolStatus.MISSING
    assert info.reason == "ffmpeg was not found."


def test_main_reports_and_checks_the_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from reframe.tools.__main__ import main

    data = tmp_path / "data"
    _fake(data / "tools" / "ffmpeg" / "bin")
    monkeypatch.setenv("REFRAME_DATA_DIR", str(data))
    monkeypatch.setenv(ALLOW_SCRIPT_TOOLS_ENV, "1")  # the fake tools are .cmd files on Windows
    assert main(["--require", "ffmpeg,ffprobe", "--expect-origin", "bundled"]) == 0
    out = capsys.readouterr().out
    assert "ffmpeg       found    bundled" in out

    assert main(["--require", "ffmpeg", "--expect-origin", "env"]) == 1
    assert "expected env" in capsys.readouterr().err

    assert main(["--json"]) == 0
    assert '"ffprobe"' in capsys.readouterr().out

    monkeypatch.setenv("REFRAME_FFMPEG", str(tmp_path / "missing"))
    assert main(["--require", "ffmpeg"]) == 1
    assert "ffmpeg is missing" in capsys.readouterr().err

    with pytest.raises(SystemExit):
        main(["--require", "ffmpeeg"])


def _alive(pid: int) -> bool:
    import psutil

    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


@pytest.mark.anyio
async def test_cancelled_discovery_leaves_no_process(tmp_path: Path, empty_path: str) -> None:
    """Cancelling discovery leaves no version-check process behind.

    ``asyncio.gather`` once returned at the first finished check and dropped the other kills.
    """
    import asyncio
    import time

    fake = _fake(tmp_path / "fake", ft.Rule(argv_has=["-version"], actions=[ft.hang()]))
    env = _env(REFRAME_FFMPEG=str(fake.ffmpeg), REFRAME_FFPROBE=str(fake.ffprobe))
    task = asyncio.ensure_future(
        discover_tools(environ=env, bundled_roots=[], search_path=empty_path, timeout=60)
    )
    deadline = time.monotonic() + 30
    while len(fake.pids()) < 2:
        assert time.monotonic() < deadline, "the fake tools did not start"
        await asyncio.sleep(0.02)
    pids = fake.pids()
    task.cancel()
    await asyncio.wait({task})
    assert [pid for pid in pids if _alive(pid)] == []
