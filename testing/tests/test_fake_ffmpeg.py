"""The fake ffmpeg/ffprobe, run through its launchers on the current OS."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

from reframe_testing import fake_tools as ft
from reframe_testing.fake_tools import FakeTools

POSIX = os.name != "nt"
posix_only = pytest.mark.skipif(not POSIX, reason="POSIX signals")


def run(
    tools: FakeTools, *args: str, tool: ft.Tool = "ffmpeg", timeout: float = 30
) -> subprocess.CompletedProcess[bytes]:
    exe = tools.ffmpeg if tool == "ffmpeg" else tools.ffprobe
    return subprocess.run([str(exe), *args], capture_output=True, timeout=timeout, check=False)


def data(name: str) -> bytes:
    return (ft.DATA_DIR / name).read_bytes()


def wait_for(predicate: object, timeout: float = 10.0) -> None:
    assert callable(predicate)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition not met in time")


def kill_tree(pid: int) -> list[psutil.Process]:
    """Kill a process and all its descendants (collected first); return them."""
    try:
        root = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return []
    procs = [root, *root.children(recursive=True)]
    for p in procs:
        with contextlib.suppress(psutil.NoSuchProcess):
            p.kill()
    return procs


def gone(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return True


# --------------------------------------------------------------------------- defaults


def test_version_defaults_are_the_real_captures(fake_tools: FakeTools) -> None:
    r = run(fake_tools, "-version")
    assert r.returncode == 0
    assert r.stdout == data("ffmpeg_version.stdout.txt")
    assert r.stdout.startswith(b"ffmpeg version n9.0.2")
    assert b"configuration: " in r.stdout
    p = run(fake_tools, "-version", tool="ffprobe")
    assert p.stdout == data("ffprobe_version.stdout.txt")
    assert p.stdout.startswith(b"ffprobe version")


def test_encoders_and_banner(fake_tools: FakeTools) -> None:
    r = run(fake_tools, "-hide_banner", "-encoders")
    assert r.stdout == data("encoders.stdout.txt")
    assert b" libx265 " in r.stdout
    assert b" hevc_nvenc " in r.stdout
    assert r.stderr == b""
    with_banner = run(fake_tools, "-encoders")
    assert with_banner.stderr.startswith(b"ffmpeg version")


def test_help_encoder_known_and_unknown(fake_tools: FakeTools) -> None:
    r = run(fake_tools, "-hide_banner", "-h", "encoder=libx264")
    assert r.stdout == data("help_encoder/libx264.stdout.txt")
    assert b"Encoder libx264" in r.stdout
    unknown = run(fake_tools, "-hide_banner", "-h", "encoder=foo_bar")
    assert unknown.returncode == 0
    assert unknown.stdout.startswith(b"Codec 'foo_bar' is not recognized by FFmpeg.")


def test_ffprobe_default_prints_empty_json(fake_tools: FakeTools) -> None:
    r = run(fake_tools, "-of", "json", "-show_streams", "x.mkv", tool="ffprobe")
    assert r.returncode == 0
    assert json.loads(r.stdout) == {}


def test_default_encode_emits_progress_and_writes_output(
    fake_tools: FakeTools, tmp_path: Path
) -> None:
    out = tmp_path / "out.mkv"
    r = run(
        fake_tools, "-i", "in.mkv", "-progress", "pipe:1", "-nostats", "-c:v", "libx264", str(out)
    )
    assert r.returncode == 0
    assert out.stat().st_size == 1024
    assert r.stdout.decode().splitlines()[-1] == "progress=end"


def test_no_defaults_means_silent_success(fake_tools: FakeTools) -> None:
    fake_tools.set_scenario(ft.Scenario(defaults=False))
    r = run(fake_tools, "-version")
    assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")


# --------------------------------------------------------------------------- rules and actions


def test_version_with_chosen_version_and_build_flags(fake_tools: FakeTools) -> None:
    fake_tools.set_scenario(
        ft.Scenario(
            [
                ft.Rule(
                    argv_has=["-version"],
                    actions=[ft.version("6.1.1", "--enable-gpl --enable-libx264")],
                )
            ]
        )
    )
    text = run(fake_tools, "-version").stdout.decode()
    lines = text.splitlines()
    assert lines[0] == "ffmpeg version 6.1.1 Copyright (c) 2000-2026 the FFmpeg developers"
    assert "  configuration: --enable-gpl --enable-libx264" not in text  # indentation is kept
    assert any(line.strip() == "configuration: --enable-gpl --enable-libx264" for line in lines)
    assert "libavcodec" in text


def test_rule_matching(fake_tools: FakeTools) -> None:
    fake_tools.set_scenario(
        ft.Scenario(
            [
                ft.Rule(tool="ffprobe", actions=[ft.stdout("probe\n")]),
                ft.Rule(argv_has=["-c:v", "hevc_nvenc"], actions=[ft.stderr("has\n")], exit_code=3),
                ft.Rule(argv_contains=["_qsv"], actions=[ft.stderr("contains\n")], exit_code=4),
                ft.Rule(
                    argv_regex=r"-h encoder=\S+_amf", actions=[ft.stdout("regex\n")], exit_code=5
                ),
            ]
        )
    )
    assert run(fake_tools, "-version", tool="ffprobe").stdout == b"probe\n"
    r = run(fake_tools, "-i", "x", "-c:v", "hevc_nvenc", "-f", "null", "-")
    assert (r.returncode, r.stderr) == (3, b"has\n")
    r = run(fake_tools, "-i", "x", "-c:v", "hevc_qsv", "-f", "null", "-")
    assert (r.returncode, r.stderr) == (4, b"contains\n")
    r = run(fake_tools, "-h", "encoder=hevc_amf")
    assert (r.returncode, r.stdout) == (5, b"regex\n")
    # no rule matches: defaults
    assert run(fake_tools, "-version").stdout == data("ffmpeg_version.stdout.txt")


def test_captured_driver_error_replays_real_stderr_and_exit_code(fake_tools: FakeTools) -> None:
    fake_tools.set_scenario(
        ft.Scenario([ft.captured("hw_hevc_nvenc_no_driver"), ft.captured("hw_hevc_qsv_no_device")])
    )
    argv = ["-hide_banner", "-f", "lavfi", "-i", "color=size=640x360", "-frames:v", "3"]
    nv = run(fake_tools, *argv, "-c:v", "hevc_nvenc", "-f", "null", "-")
    assert nv.returncode == ft.captures()["hw_hevc_nvenc_no_driver"].exit_code == 255
    assert b"Cannot load libcuda.so.1" in nv.stderr
    qsv = run(fake_tools, *argv, "-c:v", "hevc_qsv", "-f", "null", "-")
    assert b"Error creating a MFX session" in qsv.stderr
    # an encoder without a rule: defaults (success)
    assert run(fake_tools, *argv, "-c:v", "libx264", "-f", "null", "-").returncode == 0


def test_every_capture_has_its_files() -> None:
    caps = ft.captures()
    assert {
        "ffmpeg_version",
        "encoders",
        "hw_hevc_nvenc_no_driver",
        "hw_h264_vaapi_bad_device",
    } <= caps.keys()
    for cap in caps.values():
        for name in (cap.stdout, cap.stderr):
            if name is not None:
                assert (ft.DATA_DIR / name).is_file(), name
    assert b"No VA display found" in data("hw_h264_vaapi_bad_device.stderr.txt")


def test_sleep(fake_tools: FakeTools) -> None:
    fake_tools.set_scenario(ft.Scenario([ft.Rule(actions=[ft.sleep(0.4), ft.stdout("done\n")])]))
    t = time.monotonic()
    r = run(fake_tools, "-encoders")
    assert time.monotonic() - t >= 0.4
    assert r.stdout == b"done\n"


def test_hang_times_out(fake_tools: FakeTools) -> None:
    fake_tools.set_scenario(ft.Scenario([ft.Rule(actions=[ft.hang()])]))
    proc = subprocess.Popen([str(fake_tools.ffmpeg), "-encoders"])
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            proc.wait(timeout=0.5)
    finally:
        kill_tree(proc.pid)
        proc.wait(timeout=10)


@posix_only
def test_crash_by_signal(fake_tools: FakeTools) -> None:
    fake_tools.set_scenario(
        ft.Scenario([ft.Rule(actions=[ft.stderr("about to crash\n"), ft.crash()])])
    )
    r = run(fake_tools, "-i", "x", "y.mkv")
    assert r.returncode == -signal.SIGSEGV
    assert r.stderr == b"about to crash\n"


def test_crash_with_exit_code_and_plain_failure(fake_tools: FakeTools) -> None:
    fake_tools.set_scenario(
        ft.Scenario(
            [
                ft.Rule(argv_has=["a"], actions=[ft.crash(exit_code=134)]),
                ft.Rule(argv_has=["b"], actions=[ft.stderr("Conversion failed!\n")], exit_code=1),
            ]
        )
    )
    assert run(fake_tools, "a").returncode == 134
    r = run(fake_tools, "b")
    assert (r.returncode, r.stderr) == (1, b"Conversion failed!\n")


def test_flood_prints_64_mib(fake_tools: FakeTools) -> None:
    size = 64 * 2**20
    fake_tools.set_scenario(
        ft.Scenario([ft.Rule(actions=[ft.flood(size, "stdout"), ft.flood(1000, "stderr")])])
    )
    r = run(fake_tools, "-i", "x", "y.mkv", timeout=60)
    assert r.returncode == 0
    assert len(r.stdout) == size
    assert len(r.stderr) == 1000
    assert r.stdout[:64] == b"x" * 63 + b"\n"


def test_flood_stops_when_the_reader_goes_away(fake_tools: FakeTools) -> None:
    fake_tools.set_scenario(ft.Scenario([ft.Rule(actions=[ft.flood(512 * 2**20)])]))
    proc = subprocess.Popen([str(fake_tools.ffmpeg)], stdout=subprocess.PIPE)
    assert proc.stdout is not None
    assert len(proc.stdout.read(2**20)) == 2**20
    proc.stdout.close()  # an output limit was reached
    assert proc.wait(timeout=20) != 0


def test_progress_blocks_then_output(fake_tools: FakeTools, tmp_path: Path) -> None:
    fake_tools.set_scenario(
        ft.Scenario(
            [
                ft.Rule(
                    argv_has=["-progress"],
                    actions=[
                        ft.progress(
                            blocks=4,
                            interval=0.05,
                            media_seconds=8.0,
                            fps=25,
                            bytes_per_second=1000,
                        ),
                        ft.write_output(2048),
                    ],
                )
            ]
        )
    )
    out = tmp_path / "sub" / "out.mkv.part"
    t = time.monotonic()
    r = run(
        fake_tools, "-i", "in.mkv", "-progress", "pipe:1", "-nostats", "-c:v", "libx265", str(out)
    )
    assert time.monotonic() - t >= 0.2
    assert out.stat().st_size == 2048
    blocks: list[dict[str, str]] = [{}]
    for line in r.stdout.decode().splitlines():
        key, _, value = line.partition("=")
        blocks[-1][key] = value
        if key == "progress":
            blocks.append({})
    blocks.pop()
    assert len(blocks) == 4
    assert [b["progress"] for b in blocks] == ["continue", "continue", "continue", "end"]
    assert [int(b["out_time_us"]) for b in blocks] == [2_000_000, 4_000_000, 6_000_000, 8_000_000]
    assert blocks[-1]["frame"] == "200"
    assert blocks[-1]["total_size"] == "8000"
    assert blocks[-1]["out_time"] == "00:00:08.000000"
    assert blocks[-1]["speed"].endswith("x")
    assert float(blocks[-1]["fps"]) > 0
    # the field order is the one real ffmpeg n9.0.2 prints
    real = [
        line.partition("=")[0] for line in data("progress_encode.stdout.txt").decode().splitlines()
    ]
    assert list(blocks[0]) == real[: len(blocks[0])]


def test_progress_to_stderr(fake_tools: FakeTools) -> None:
    fake_tools.set_scenario(ft.Scenario([ft.Rule(actions=[ft.progress(blocks=2, end=False)])]))
    r = run(fake_tools, "-i", "x", "-progress", "pipe:2", "-f", "null", "-")
    assert r.stdout == b""
    assert r.stderr.decode().splitlines()[-1] == "progress=continue"


def test_invocation_log_records_tool_pid_and_argv(fake_tools: FakeTools) -> None:
    run(fake_tools, "-hide_banner", "-encoders")
    run(fake_tools, "-version", tool="ffprobe")
    calls = fake_tools.invocations()
    assert [(c.tool, c.argv) for c in calls] == [
        ("ffmpeg", ("-hide_banner", "-encoders")),
        ("ffprobe", ("-version",)),
    ]
    assert all(c.role == "main" and c.pid > 0 for c in calls)
    assert fake_tools.calls("ffprobe") == [("-version",)]
    fake_tools.clear_log()
    assert fake_tools.invocations() == []


def test_environment_overrides_the_baked_scenario(fake_tools: FakeTools, tmp_path: Path) -> None:
    other = ft.make_fake_tools(
        tmp_path / "other", ft.Scenario([ft.Rule(actions=[ft.stdout("other\n")])])
    )
    r = subprocess.run(
        [str(fake_tools.ffmpeg), "-version"],
        capture_output=True,
        env=other.env(),
        timeout=30,
        check=False,
    )
    assert r.stdout == b"other\n"
    assert other.calls() == [("-version",)]  # the env also selects the log


def test_direct_argv_without_launcher(fake_tools: FakeTools) -> None:
    fake_tools.set_scenario(
        ft.Scenario([ft.Rule(argv_has=["a|b&c"], actions=[ft.stdout("odd\n")])])
    )
    r = subprocess.run(
        [*fake_tools.argv("ffprobe"), "a|b&c"],
        capture_output=True,
        env=fake_tools.env(),
        timeout=30,
        check=False,
    )
    assert r.stdout == b"odd\n"
    assert fake_tools.invocations()[0].tool == "ffprobe"


def test_unknown_data_name_is_rejected() -> None:
    with pytest.raises(FileNotFoundError):
        ft.stderr_data("does-not-exist.txt")


# ------------------------------------------------------------------- process trees and signals


def test_tree_kill_leaves_no_process(fake_tools: FakeTools) -> None:
    fake_tools.set_scenario(ft.Scenario([ft.Rule(actions=[ft.spawn_grandchild(), ft.hang()])]))
    proc = subprocess.Popen([str(fake_tools.ffmpeg), "-i", "x", "y.mkv"])
    try:
        wait_for(lambda: any(i.role == "grandchild" for i in fake_tools.invocations()))
        pids = fake_tools.pids()
        assert len(pids) == 2
        main_pid = next(i.pid for i in fake_tools.invocations() if i.role == "main")
        grandchild = next(i for i in fake_tools.invocations() if i.role == "grandchild")
        assert grandchild.ppid == main_pid
        # on POSIX the launcher execs python, so the launcher pid is the fake's pid; on Windows
        # it is cmd.exe, the parent of the fake
        assert main_pid == proc.pid or psutil.Process(main_pid).ppid() == proc.pid
        killed = kill_tree(proc.pid)
        assert {p.pid for p in killed} >= set(pids)
        _, alive = psutil.wait_procs(killed, timeout=10)
        assert alive == []
    finally:
        kill_tree(proc.pid)
        proc.wait(timeout=10)
    wait_for(lambda: all(gone(pid) for pid in pids))


def test_killing_only_the_parent_orphans_the_grandchild(fake_tools: FakeTools) -> None:
    """Why a tree kill must collect the children first: they outlive their parent."""
    fake_tools.set_scenario(ft.Scenario([ft.Rule(actions=[ft.spawn_grandchild(), ft.hang()])]))
    proc = subprocess.Popen([str(fake_tools.ffmpeg), "-i", "x", "y.mkv"])
    grandchild_pid = 0
    try:
        wait_for(lambda: any(i.role == "grandchild" for i in fake_tools.invocations()))
        grandchild_pid = next(i.pid for i in fake_tools.invocations() if i.role == "grandchild")
        main = next(i.pid for i in fake_tools.invocations() if i.role == "main")
        psutil.Process(main).kill()
        # POSIX: proc is the fake itself. Windows: proc is cmd.exe, which ends with its child.
        proc.wait(timeout=10)
        time.sleep(0.1)
        assert not gone(grandchild_pid)
    finally:
        kill_tree(proc.pid)
        if grandchild_pid:
            kill_tree(grandchild_pid)
        proc.wait(timeout=10)
    wait_for(lambda: gone(grandchild_pid))


@posix_only
def test_ignore_sigterm_needs_sigkill(fake_tools: FakeTools) -> None:
    fake_tools.set_scenario(
        ft.Scenario([ft.Rule(actions=[ft.ignore_sigterm(), ft.stdout("ready\n"), ft.hang()])])
    )
    proc = subprocess.Popen([str(fake_tools.ffmpeg)], stdout=subprocess.PIPE)
    assert proc.stdout is not None
    assert proc.stdout.readline() == b"ready\n"
    proc.terminate()
    with pytest.raises(subprocess.TimeoutExpired):
        proc.wait(timeout=0.3)
    proc.kill()
    assert proc.wait(timeout=10) == -signal.SIGKILL
    proc.stdout.close()


@posix_only
def test_exit_on_sigterm_like_real_ffmpeg(fake_tools: FakeTools) -> None:
    fake_tools.set_scenario(
        ft.Scenario([ft.Rule(actions=[ft.exit_on_sigterm(), ft.stdout("ready\n"), ft.hang()])])
    )
    proc = subprocess.Popen(
        [str(fake_tools.ffmpeg)], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    assert proc.stdout is not None
    assert proc.stdout.readline() == b"ready\n"
    proc.terminate()
    _, err = proc.communicate(timeout=10)
    assert proc.returncode == 255
    assert err == b"Exiting normally, received signal 15.\n"


# --------------------------------------------------------------------------- asyncio


@pytest.mark.anyio
async def test_launcher_works_with_asyncio_create_subprocess_exec(fake_tools: FakeTools) -> None:
    proc = await asyncio.create_subprocess_exec(
        fake_tools.ffmpeg,
        "-hide_banner",
        "-encoders",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    assert proc.returncode == 0
    assert out == data("encoders.stdout.txt")
    assert err == b""


@pytest.mark.anyio
async def test_asyncio_timeout_and_tree_kill(fake_tools: FakeTools) -> None:
    fake_tools.set_scenario(ft.Scenario([ft.Rule(actions=[ft.spawn_grandchild(), ft.hang()])]))
    proc = await asyncio.create_subprocess_exec(fake_tools.ffmpeg, "-i", "x", "y.mkv")
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(proc.wait(), timeout=0.5)
    for _ in range(200):
        if len(fake_tools.pids()) == 2:
            break
        await asyncio.sleep(0.02)
    pids = fake_tools.pids()
    assert len(pids) == 2
    killed = kill_tree(proc.pid)
    await proc.wait()
    _, alive = psutil.wait_procs(killed, timeout=10)
    assert alive == []
    assert all(gone(pid) for pid in pids)


# --------------------------------------------------------------------------- launchers


def test_posix_launcher_falls_back_to_sh_for_a_spaced_interpreter(tmp_path: Path) -> None:
    text = ft.posix_launcher(
        "ffmpeg",
        python="/opt/my python/bin/python3",
        script=ft.SCRIPT,
        scenario=tmp_path / "s.json",
        log=tmp_path / "l",
    )
    assert text.startswith("#!/bin/sh\n")
    assert "exec '/opt/my python/bin/python3' -I -c" in text


@posix_only
def test_sh_fallback_launcher_runs(tmp_path: Path) -> None:
    spaced = tmp_path / "dir with space"
    spaced.mkdir()
    link = spaced / "python"
    link.symlink_to(sys.executable)
    tools = ft.make_fake_tools(tmp_path / "tools", python=str(link))
    assert tools.ffmpeg.read_text().startswith("#!/bin/sh\n")
    r = subprocess.run(
        [str(tools.ffmpeg), "-hide_banner", "-h", "encoder=aac"],
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert r.stdout == data("help_encoder/aac.stdout.txt")
    assert tools.invocations()[0].argv == ("-hide_banner", "-h", "encoder=aac")


def test_posix_launcher_uses_a_python_shebang(fake_tools: FakeTools) -> None:
    if not POSIX:
        pytest.skip("POSIX launcher")
    text = fake_tools.ffmpeg.read_text()
    assert text.splitlines()[0] == f"#!{sys.executable} -I"
    assert os.access(fake_tools.ffmpeg, os.X_OK)


def test_windows_launcher_written_on_any_os(tmp_path: Path) -> None:
    tools = ft.make_fake_tools(
        tmp_path / "100% fake",
        ft.Scenario(),
        platform="win32",
        python=r"C:\Program Files\Python313\python.exe",
    )
    assert tools.ffmpeg.name == "ffmpeg.cmd"
    assert tools.ffprobe.name == "ffprobe.cmd"
    raw = tools.ffmpeg.read_bytes()
    assert raw.endswith(b"\r\n")
    assert b"\n" not in raw.replace(b"\r\n", b"")
    lines = raw.decode().split("\r\n")
    assert lines[0] == "@echo off"
    assert "setlocal" in lines
    scen = str(tools.scenario_path).replace("%", "%%")
    assert (
        f'if not defined REFRAME_FAKE_FFMPEG_SCENARIO set "REFRAME_FAKE_FFMPEG_SCENARIO={scen}"'
        in lines
    )
    run_line = next(line for line in lines if "--fake-tool" in line)
    assert run_line == (
        '"C:\\Program Files\\Python313\\python.exe" -I '
        f'"{str(ft.SCRIPT).replace("%", "%%")}" --fake-tool ffmpeg %*'
    )
    assert lines[-2] == "exit /b %ERRORLEVEL%"
    assert "--fake-tool ffprobe %*" in tools.ffprobe.read_text()


def test_windows_launcher_rejects_double_quotes(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="double quote"):
        ft.windows_launcher(
            "ffmpeg",
            python='C:\\a"b\\python.exe',
            script=ft.SCRIPT,
            scenario=tmp_path,
            log=tmp_path,
        )


def test_script_cli_entry_point(fake_tools: FakeTools) -> None:
    """The form the Windows launcher uses: ``python fake_ffmpeg.py --fake-tool ffmpeg ...``."""
    r = subprocess.run(
        [sys.executable, str(ft.SCRIPT), "--fake-tool", "ffmpeg", "-version"],
        capture_output=True,
        env=fake_tools.env(),
        timeout=30,
        check=False,
    )
    assert r.stdout == data("ffmpeg_version.stdout.txt")
    bad = subprocess.run(
        [sys.executable, str(ft.SCRIPT)], capture_output=True, timeout=30, check=False
    )
    assert bad.returncode == 2
