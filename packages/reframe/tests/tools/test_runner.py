"""reframe.tools.runner: timeout, cancel, output limits, missing binaries, tree kill (C-1).

Most tests drive the fake FFmpeg (``reframe_testing.fake_tools``), so they run the same on
Linux and Windows (where the fake is a ``.cmd`` launcher: ``cmd.exe -> python``, a real
process tree).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import psutil
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from reframe.tools import CancelToken, RunResult, kill_process_tree, run, run_streaming
from reframe.tools import runner as runner_mod
from reframe_testing import fake_tools as ft

pytestmark = pytest.mark.anyio

POSIX = os.name == "posix"


def _alive(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


async def _wait_for(predicate: object, limit: float = 10.0) -> None:
    assert callable(predicate)
    deadline = time.monotonic() + limit
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.02)


def _scenario(tools: ft.FakeTools, *rules: ft.Rule) -> None:
    tools.set_scenario(ft.Scenario(list(rules)))


# --------------------------------------------------------------------------- basics


async def test_exit_code_and_output_are_returned(fake_tools: ft.FakeTools) -> None:
    _scenario(
        fake_tools,
        ft.Rule(
            argv_has=["-x"],
            exit_code=3,
            actions=[ft.stdout("out line\n"), ft.stderr("err line\n")],
        ),
    )
    result = await run([str(fake_tools.ffmpeg), "-x"], timeout=30)
    assert result.returncode == 3
    assert result.stdout == b"out line\n"
    assert result.stderr == b"err line\n"
    assert result.stdout_text == "out line\n"
    assert result.stderr_text == "err line\n"
    assert not result.ok
    assert result.started
    assert not result.timed_out
    assert not result.cancelled
    assert not result.truncated
    assert result.argv == (str(fake_tools.ffmpeg), "-x")
    assert result.duration > 0


async def test_version_of_the_fake_is_ok(fake_tools: ft.FakeTools) -> None:
    result = await run([str(fake_tools.ffmpeg), "-version"], timeout=30)
    assert result.ok
    assert result.stdout.startswith(b"ffmpeg version n9.0.2")


async def test_crash_is_a_normal_result(fake_tools: ft.FakeTools) -> None:
    _scenario(fake_tools, ft.Rule(argv_has=["-crash"], actions=[ft.crash()]))
    result = await run([str(fake_tools.ffmpeg), "-crash"], timeout=30)
    assert result.returncode not in (0, None)
    if POSIX:
        assert result.returncode == -11  # SIGSEGV
    assert not result.ok


async def test_stdin_cwd_and_extra_env(tmp_path: Path) -> None:
    code = (
        "import os, sys; data = sys.stdin.read(); "
        "sys.stdout.write(data.upper() + '|' + os.environ['REFRAME_TEST_X'] + '|' + os.getcwd())"
    )
    result = await run(
        [sys.executable, "-c", code],
        timeout=30,
        stdin=b"abc",
        cwd=tmp_path,
        extra_env={"REFRAME_TEST_X": "42"},
    )
    assert result.ok, result.stderr_text
    upper, value, cwd = result.stdout_text.split("|")
    assert (upper, value) == ("ABC", "42")
    assert await asyncio.to_thread(os.path.samefile, cwd, tmp_path)


async def test_stdin_is_the_null_device_by_default() -> None:
    result = await run(
        [sys.executable, "-c", "import sys; print(len(sys.stdin.read()))"], timeout=30
    )
    assert result.stdout_text.strip() == "0"


@pytest.mark.parametrize(
    ("argv", "kwargs", "error"),
    [
        ([], {"timeout": 1}, ValueError),
        ("ffmpeg -version", {"timeout": 1}, TypeError),
        (["x"], {"timeout": 0}, ValueError),
        (["x"], {"timeout": -1}, ValueError),
        (["x"], {"timeout": 1, "max_output": -1}, ValueError),
    ],
)
async def test_programming_errors_raise(
    argv: object, kwargs: dict[str, float], error: type[Exception]
) -> None:
    with pytest.raises(error):
        await run(argv, **kwargs)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- missing binary


async def test_missing_binary_is_a_result_not_an_exception(tmp_path: Path) -> None:
    result = await run([str(tmp_path / "no-such-ffmpeg"), "-version"], timeout=5)
    assert result.returncode is None
    assert not result.started
    assert not result.ok
    assert result.error is not None
    assert result.error.startswith("FileNotFoundError")
    assert result.stdout == result.stderr == b""


async def test_missing_binary_on_path_is_a_result() -> None:
    result = await run(["reframe-no-such-tool-4711", "-version"], timeout=5)
    assert result.error is not None
    assert result.returncode is None


@pytest.mark.skipif(not POSIX, reason="POSIX file modes")
async def test_not_executable_file_is_a_result(tmp_path: Path) -> None:
    script = tmp_path / "ffmpeg"
    script.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    script.chmod(0o644)
    result = await run([str(script)], timeout=5)
    assert result.error is not None
    assert result.error.startswith("PermissionError")


async def test_directory_is_a_result(tmp_path: Path) -> None:
    result = await run([str(tmp_path)], timeout=5)
    assert result.error is not None
    assert result.returncode is None


# --------------------------------------------------------------------------- timeout


async def test_timeout_kills_the_process(fake_tools: ft.FakeTools) -> None:
    _scenario(fake_tools, ft.Rule(argv_has=["-hang"], actions=[ft.stderr("started\n"), ft.hang()]))
    started = time.monotonic()
    result = await run([str(fake_tools.ffmpeg), "-hang"], timeout=1.5)
    elapsed = time.monotonic() - started
    assert result.timed_out
    assert not result.cancelled
    assert result.returncode not in (0, None)
    assert 1.4 <= elapsed < 10
    assert b"started" in result.stderr  # output before the kill is kept
    for pid in fake_tools.pids():
        assert not _alive(pid)


async def test_timeout_kills_the_whole_tree(fake_tools: ft.FakeTools) -> None:
    _scenario(
        fake_tools,
        ft.Rule(argv_has=["-tree"], actions=[ft.spawn_grandchild(), ft.hang()]),
    )
    result = await run([str(fake_tools.ffmpeg), "-tree"], timeout=3)
    assert result.timed_out
    roles = {inv.role for inv in fake_tools.invocations()}
    assert roles == {"main", "grandchild"}
    for pid in fake_tools.pids():
        assert not _alive(pid), f"process {pid} survived the tree kill"


async def test_process_that_finishes_in_time_is_not_timed_out(fake_tools: ft.FakeTools) -> None:
    _scenario(fake_tools, ft.Rule(argv_has=["-s"], actions=[ft.sleep(0.2), ft.stdout("done\n")]))
    result = await run([str(fake_tools.ffmpeg), "-s"], timeout=30)
    assert result.ok
    assert result.stdout == b"done\n"


@pytest.mark.skipif(not POSIX, reason="SIGTERM handling exists on POSIX only")
async def test_timeout_does_not_depend_on_sigterm(fake_tools: ft.FakeTools) -> None:
    _scenario(fake_tools, ft.Rule(argv_has=["-stubborn"], actions=[ft.ignore_sigterm(), ft.hang()]))
    result = await run([str(fake_tools.ffmpeg), "-stubborn"], timeout=1)
    assert result.timed_out
    assert result.returncode == -9  # SIGKILL


# --------------------------------------------------------------------------- cancel


async def test_cancel_from_a_coroutine(fake_tools: ft.FakeTools) -> None:
    _scenario(fake_tools, ft.Rule(argv_has=["-hang"], actions=[ft.spawn_grandchild(), ft.hang()]))
    token = CancelToken()
    task = asyncio.ensure_future(run([str(fake_tools.ffmpeg), "-hang"], timeout=60, cancel=token))
    await _wait_for(lambda: len(fake_tools.pids()) == 2)
    cancelled_at = time.monotonic()
    token.cancel("user")
    result = await task
    latency = time.monotonic() - cancelled_at
    assert result.cancelled
    assert not result.timed_out
    assert token.cancelled
    assert token.reason == "user"
    assert latency < 1.0, f"cancel took {latency:.3f} s"
    for pid in fake_tools.pids():
        assert not _alive(pid)


async def test_cancel_from_another_thread_reacts_quickly(fake_tools: ft.FakeTools) -> None:
    _scenario(fake_tools, ft.Rule(argv_has=["-hang"], actions=[ft.stdout("ready\n"), ft.hang()]))
    token = CancelToken()
    cancelled_at: list[float] = []

    def cancel_later() -> None:
        while not fake_tools.pids():
            time.sleep(0.01)
        time.sleep(0.2)
        cancelled_at.append(time.monotonic())
        token.cancel()

    thread = threading.Thread(target=cancel_later)
    thread.start()
    result = await run([str(fake_tools.ffmpeg), "-hang"], timeout=60, cancel=token)
    returned_at = time.monotonic()
    thread.join()
    assert result.cancelled
    latency = returned_at - cancelled_at[0]
    # The token wakes the loop at once; the rest is the kill and the reap.
    assert latency < 1.0, f"cancel took {latency:.3f} s"
    assert not any(_alive(pid) for pid in fake_tools.pids())


async def test_token_reaction_time_is_below_100_ms() -> None:
    token = CancelToken()
    waiter = asyncio.ensure_future(token.wait())
    await asyncio.sleep(0.05)
    started = time.monotonic()
    threading.Thread(target=token.cancel).start()
    await asyncio.wait_for(waiter, 5)
    assert time.monotonic() - started < 0.1


async def test_cancelled_token_does_not_start_the_process(fake_tools: ft.FakeTools) -> None:
    token = CancelToken()
    token.cancel()
    token.cancel("again")  # idempotent; the first reason stays
    assert token.reason is None
    result = await run([str(fake_tools.ffmpeg), "-version"], timeout=10, cancel=token)
    assert result.cancelled
    assert result.returncode is None
    assert fake_tools.pids() == []
    await token.wait()  # returns at once


async def test_one_token_cancels_several_runs(fake_tools: ft.FakeTools) -> None:
    _scenario(fake_tools, ft.Rule(argv_has=["-hang"], actions=[ft.hang()]))
    token = CancelToken()
    tasks = [
        asyncio.ensure_future(run([str(fake_tools.ffmpeg), "-hang"], timeout=60, cancel=token))
        for _ in range(3)
    ]
    await _wait_for(lambda: len(fake_tools.pids()) == 3)
    token.cancel()
    results = await asyncio.gather(*tasks)
    assert all(r.cancelled for r in results)


async def test_cancelling_the_calling_task_kills_the_tree(fake_tools: ft.FakeTools) -> None:
    _scenario(fake_tools, ft.Rule(argv_has=["-hang"], actions=[ft.spawn_grandchild(), ft.hang()]))
    task = asyncio.ensure_future(run([str(fake_tools.ffmpeg), "-hang"], timeout=60))
    await _wait_for(lambda: len(fake_tools.pids()) == 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await _wait_for(lambda: not any(_alive(pid) for pid in fake_tools.pids()), limit=10)


async def test_cancel_after_exit_is_a_normal_result(fake_tools: ft.FakeTools) -> None:
    token = CancelToken()
    result = await run([str(fake_tools.ffmpeg), "-version"], timeout=30, cancel=token)
    token.cancel()
    assert result.ok
    assert not result.cancelled


# --------------------------------------------------------------------------- output limits


async def test_large_output_is_limited_and_drained(fake_tools: ft.FakeTools) -> None:
    _scenario(
        fake_tools,
        ft.Rule(
            argv_has=["-flood"],
            exit_code=0,
            actions=[ft.flood(24 * 2**20, "stdout"), ft.flood(6 * 2**20, "stderr")],
        ),
    )
    result = await run([str(fake_tools.ffmpeg), "-flood"], timeout=120, max_output=2**20)
    assert result.returncode == 0  # the fake wrote everything: the pipes were drained
    assert result.truncated
    assert len(result.stdout) == 2**20
    assert len(result.stderr) == 2**20
    assert result.stdout.startswith(b"x" * 63 + b"\n")


async def test_default_output_limit_is_16_mib(fake_tools: ft.FakeTools) -> None:
    _scenario(fake_tools, ft.Rule(argv_has=["-flood"], actions=[ft.flood(20 * 2**20, "stdout")]))
    result = await run([str(fake_tools.ffmpeg), "-flood"], timeout=120)
    assert result.returncode == 0
    assert result.truncated
    assert len(result.stdout) == 16 * 2**20 == runner_mod.DEFAULT_MAX_OUTPUT


async def test_output_below_the_limit_is_complete(fake_tools: ft.FakeTools) -> None:
    _scenario(fake_tools, ft.Rule(argv_has=["-flood"], actions=[ft.flood(3 * 2**20, "stderr")]))
    result = await run([str(fake_tools.ffmpeg), "-flood"], timeout=120, max_output=4 * 2**20)
    assert not result.truncated
    assert len(result.stderr) == 3 * 2**20


async def test_a_grandchild_holding_the_pipe_does_not_block(tmp_path: Path) -> None:
    """The process exits, but a grandchild it left behind keeps stdout open: run() returns
    after a short grace period instead of waiting for the grandchild."""
    code = (
        "import subprocess, sys; "
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
        "print(p.pid, flush=True)"
    )
    started = time.monotonic()
    result = await run([sys.executable, "-c", code], timeout=30)
    elapsed = time.monotonic() - started
    try:
        assert result.returncode == 0
        assert not result.timed_out
        assert elapsed < runner_mod.PIPE_DRAIN_GRACE + 5
    finally:
        for line in result.stdout_text.split():
            with contextlib.suppress(ValueError, psutil.Error):
                psutil.Process(int(line)).kill()


async def test_zero_output_limit_stores_nothing(fake_tools: ft.FakeTools) -> None:
    result = await run([str(fake_tools.ffmpeg), "-version"], timeout=30, max_output=0)
    assert result.ok
    assert result.stdout == b""
    assert result.truncated


# --------------------------------------------------------------------------- streaming


async def test_streaming_passes_lines_to_callbacks(fake_tools: ft.FakeTools) -> None:
    out: list[str] = []
    err: list[str] = []
    argv = [str(fake_tools.ffmpeg), "-i", "in.mkv", "-progress", "pipe:1", "-f", "null", "-"]
    result = await run_streaming(
        argv, on_stdout_line=out.append, on_stderr_line=err.append, cancel=None, timeout=60
    )
    assert result.ok
    assert out.count("progress=continue") == 4
    assert out[-1] == "progress=end"
    assert all("\n" not in line and "\r" not in line for line in out + err)
    assert err[0].startswith("ffmpeg version")  # the banner
    # The result keeps the tail of each stream.
    assert result.stdout.endswith(b"progress=end\n")


async def test_streaming_with_async_callbacks(fake_tools: ft.FakeTools) -> None:
    seen: list[str] = []

    async def on_line(line: str) -> None:
        await asyncio.sleep(0)
        seen.append(line)

    _scenario(fake_tools, ft.Rule(argv_has=["-l"], actions=[ft.stdout("a\r\nb\rc\n\nd")]))
    result = await run_streaming(
        [str(fake_tools.ffmpeg), "-l"], on_stdout_line=on_line, on_stderr_line=None, cancel=None
    )
    assert result.ok
    assert seen == ["a", "b", "c", "", "d"]


async def test_streaming_cancel_from_a_callback(fake_tools: ft.FakeTools) -> None:
    _scenario(
        fake_tools,
        ft.Rule(
            argv_has=["-tree"], actions=[ft.spawn_grandchild(), ft.stdout("ready\n"), ft.hang()]
        ),
    )
    token = CancelToken()

    def on_line(line: str) -> None:
        if line == "ready":
            token.cancel()

    result = await run_streaming(
        [str(fake_tools.ffmpeg), "-tree"], on_stdout_line=on_line, on_stderr_line=None, cancel=token
    )
    assert result.cancelled
    assert len(fake_tools.pids()) == 2
    for pid in fake_tools.pids():
        assert not _alive(pid)


async def test_streaming_timeout(fake_tools: ft.FakeTools) -> None:
    _scenario(fake_tools, ft.Rule(argv_has=["-hang"], actions=[ft.hang()]))
    result = await run_streaming(
        [str(fake_tools.ffmpeg), "-hang"],
        on_stdout_line=None,
        on_stderr_line=None,
        cancel=None,
        timeout=1,
    )
    assert result.timed_out


async def test_streaming_callback_error_kills_and_propagates(fake_tools: ft.FakeTools) -> None:
    _scenario(fake_tools, ft.Rule(argv_has=["-hang"], actions=[ft.stdout("boom\n"), ft.hang()]))

    def on_line(line: str) -> None:
        raise RuntimeError(f"callback failed on {line!r}")

    with pytest.raises(RuntimeError, match="callback failed on 'boom'"):
        await run_streaming(
            [str(fake_tools.ffmpeg), "-hang"],
            on_stdout_line=on_line,
            on_stderr_line=None,
            cancel=None,
            timeout=60,
        )
    await _wait_for(lambda: not any(_alive(pid) for pid in fake_tools.pids()))


async def test_streaming_keeps_the_tail(fake_tools: ft.FakeTools) -> None:
    _scenario(
        fake_tools,
        ft.Rule(argv_has=["-f"], actions=[ft.flood(3 * 2**20, "stderr"), ft.stderr("LAST\n")]),
    )
    lines: list[str] = []
    result = await run_streaming(
        [str(fake_tools.ffmpeg), "-f"],
        on_stdout_line=None,
        on_stderr_line=lines.append,
        cancel=None,
        max_output=1000,
    )
    assert result.truncated
    assert len(result.stderr) == 1000
    assert result.stderr.endswith(b"LAST\n")
    assert lines[-1] == "LAST"
    assert len(lines) == 3 * 2**20 // 64 + 1


async def test_streaming_splits_very_long_lines(fake_tools: ft.FakeTools) -> None:
    _scenario(
        fake_tools, ft.Rule(argv_has=["-l"], actions=[ft.stdout("y" * (2 * 2**20 + 5) + "\n")])
    )
    lines: list[str] = []
    await run_streaming(
        [str(fake_tools.ffmpeg), "-l"],
        on_stdout_line=lines.append,
        on_stderr_line=None,
        cancel=None,
    )
    assert [len(line) for line in lines] == [2**20, 2**20, 5]


def _reference_lines(data: bytes) -> list[str]:
    parts = re.split(rb"\r\n|\r|\n", data)
    if parts and parts[-1] == b"":
        parts.pop()
    return [p.decode("utf-8", errors="replace") for p in parts]


@settings(max_examples=200, deadline=None)
@given(
    data=st.lists(
        st.sampled_from([b"a", b"bc", b"\n", b"\r", b"\r\n", b"\xc3\xa9", b" "]), max_size=40
    ).map(b"".join),
    cuts=st.lists(st.integers(min_value=0, max_value=200), max_size=8),
)
def test_line_splitting_does_not_depend_on_chunk_boundaries(data: bytes, cuts: list[int]) -> None:
    lines: list[str] = []
    sink = runner_mod._LineSink(lines.append, tail=10)

    async def feed() -> None:
        points = sorted({c for c in cuts if 0 < c < len(data)})
        start = 0
        for point in [*points, len(data)]:
            await sink.feed(data[start:point])
            start = point
        await sink.close()

    asyncio.run(feed())
    # A trailing lone \r cannot be told apart from \r\n until EOF; at EOF it ends the line.
    assert lines == _reference_lines(data)
    assert sink.value() == data[-10:]


# --------------------------------------------------------------------------- tree kill helper


def test_kill_process_tree_on_a_dead_pid_is_harmless() -> None:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    assert kill_process_tree(proc.pid) == []


def test_kill_process_tree_kills_children_first(tmp_path: Path) -> None:
    tools = ft.make_fake_tools(
        tmp_path / "fake", ft.Scenario([ft.Rule(actions=[ft.spawn_grandchild(), ft.hang()])])
    )
    proc = subprocess.Popen([str(tools.ffmpeg), "-x"], env=tools.env())
    try:
        deadline = time.monotonic() + 10
        while len(tools.pids()) < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
        killed = kill_process_tree(proc.pid)
        proc.wait(timeout=10)
        assert {p.pid for p in killed} >= {
            inv.pid for inv in tools.invocations() if inv.role == "grandchild"
        }
        psutil.wait_procs(killed, timeout=5)
        assert not any(_alive(pid) for pid in tools.pids())
    finally:
        tools.kill_leftovers()
        if proc.poll() is None:
            proc.kill()


@pytest.mark.skipif(not POSIX, reason="on Windows the root is cmd.exe, which exits with its child")
def test_kill_process_tree_can_keep_the_root(tmp_path: Path) -> None:
    tools = ft.make_fake_tools(
        tmp_path / "fake", ft.Scenario([ft.Rule(actions=[ft.spawn_grandchild(), ft.hang()])])
    )
    proc = subprocess.Popen([str(tools.ffmpeg), "-x"], env=tools.env())
    try:
        deadline = time.monotonic() + 10
        while len(tools.pids()) < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
        grandchildren = [inv.pid for inv in tools.invocations() if inv.role == "grandchild"]
        killed = kill_process_tree(proc.pid, kill_root=False)
        psutil.wait_procs(killed, timeout=5)
        assert not any(_alive(pid) for pid in grandchildren)
        root = psutil.Process(proc.pid)
        assert root.status() != psutil.STATUS_STOPPED  # resumed after the kill
        assert proc.poll() is None
    finally:
        tools.kill_leftovers()
        if proc.poll() is None:
            proc.kill()
            proc.wait()


# --------------------------------------------------------------------------- child safety


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="PR_SET_PDEATHSIG is Linux only")
def test_children_die_when_reframe_is_killed(fake_tools: ft.FakeTools) -> None:
    """SIGKILL the process that called run(): the kernel kills its FFmpeg (PDEATHSIG)."""
    fake_tools.set_scenario(ft.Scenario([ft.Rule(argv_has=["-hang"], actions=[ft.hang()])]))
    helper = textwrap.dedent(
        """
        import asyncio, sys
        from reframe.tools import run
        asyncio.run(run([sys.argv[1], "-hang"], timeout=60))
        """
    )
    parent = subprocess.Popen([sys.executable, "-c", helper, str(fake_tools.ffmpeg)])
    try:
        deadline = time.monotonic() + 20
        while not fake_tools.pids() and time.monotonic() < deadline:
            time.sleep(0.02)
        (child_pid,) = fake_tools.pids()
        child = psutil.Process(child_pid)
        assert child.ppid() == parent.pid
        if sys.platform != "win32":
            assert os.getpgid(child_pid) == child_pid  # its own session and process group
        parent.kill()
        parent.wait(timeout=10)
        _, alive = psutil.wait_procs([child], timeout=10)
        assert not alive, "FFmpeg survived the death of its parent"
    finally:
        if parent.poll() is None:
            parent.kill()


def test_run_result_defaults() -> None:
    result = RunResult(0, b"", b"", 0.1)
    assert result.ok
    assert result.started
    assert result.argv == ()
