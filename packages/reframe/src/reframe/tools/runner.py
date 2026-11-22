"""The one way Reframe runs a subprocess.

- :func:`run` collects the output; :func:`run_streaming` passes each line to callbacks.
- Both take a :class:`CancelToken`; ``run`` also has a timeout. On timeout, cancel, or
  when the calling task is cancelled, the **whole process tree** is killed (children first,
  then the process itself) and the pipes are drained, so nothing is left behind and nothing
  deadlocks.
- A non-zero exit code is a normal result. A program that cannot be started (missing file,
  not executable, wrong format) is also a normal result: :attr:`RunResult.error` is set and
  :attr:`RunResult.returncode` is ``None``. Only programming errors raise (an empty ``argv``,
  a negative timeout, an exception in a line callback).
- Child safety (the child dies with Reframe) is in :mod:`reframe.platform.childproc`.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import os
import signal
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import psutil

from reframe.platform import childproc

__all__ = [
    "DEFAULT_MAX_OUTPUT",
    "CancelToken",
    "LineCallback",
    "RunResult",
    "kill_leftovers",
    "kill_process_tree",
    "run",
    "run_streaming",
]

DEFAULT_MAX_OUTPUT = 16 * 2**20
#: ``run_streaming`` keeps the last this many bytes of each stream in the result.
DEFAULT_STREAMING_TAIL = 2**20
#: A line longer than this is passed to the callback in pieces of this size.
MAX_LINE = 2**20
#: After the process exited (or was killed), wait this long for the pipes to close. A
#: process that escaped the tree kill and still holds a pipe cannot block ``run`` forever.
PIPE_DRAIN_GRACE = 2.0
_READ_SIZE = 64 * 1024

#: Called with each line (decoded as UTF-8, invalid bytes replaced, line end removed).
#: It may return an awaitable, which is awaited before the next line is read.
LineCallback = Callable[[str], object]


class CancelToken:
    """A cancel flag that any coroutine or thread can set; :func:`run` reacts at once.

    One token can cancel several runs.
    """

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._waiters: list[tuple[asyncio.AbstractEventLoop, asyncio.Future[None]]] = []

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        """Set the flag (idempotent). Thread-safe."""
        with self._lock:
            if self._event.is_set():
                return
            self._event.set()
            waiters, self._waiters = self._waiters, []
        for loop, future in waiters:
            with contextlib.suppress(RuntimeError):  # the loop is closed: nobody waits
                loop.call_soon_threadsafe(_resolve, future)

    async def wait(self) -> None:
        """Return when the token is cancelled."""
        loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = loop.create_future()
        with self._lock:
            if self._event.is_set():
                return
            entry = (loop, future)
            self._waiters.append(entry)
        try:
            await future
        finally:
            with self._lock, contextlib.suppress(ValueError):
                self._waiters.remove(entry)


def _resolve(future: asyncio.Future[None]) -> None:
    if not future.done():
        future.set_result(None)


@dataclass(frozen=True, slots=True)
class RunResult:
    """What happened to one process.

    ``stdout`` / ``stderr`` are bytes: ``run`` keeps the first ``max_output`` bytes of each
    stream, ``run_streaming`` the last ``DEFAULT_STREAMING_TAIL`` bytes (the end of an FFmpeg log is
    where the error is). ``truncated`` is true if anything was not stored.
    """

    returncode: int | None
    """The exit code (on POSIX ``-N`` for "killed by signal N"); ``None`` if it never ran."""
    stdout: bytes
    stderr: bytes
    duration: float
    """Wall-clock seconds from start to the end of the process (and its pipes)."""
    timed_out: bool = False
    cancelled: bool = False
    truncated: bool = False
    error: str | None = None
    """Why the process could not be started (for example ``FileNotFoundError: …``)."""
    argv: tuple[str, ...] = field(default=())

    @property
    def started(self) -> bool:
        return self.error is None

    @property
    def ok(self) -> bool:
        """Exit code 0, not timed out, not cancelled."""
        return self.returncode == 0 and not self.timed_out and not self.cancelled

    @property
    def stdout_text(self) -> str:
        return self.stdout.decode("utf-8", errors="replace")

    @property
    def stderr_text(self) -> str:
        return self.stderr.decode("utf-8", errors="replace")


class _Sink(Protocol):
    truncated: bool

    async def feed(self, data: bytes) -> None: ...
    async def close(self) -> None: ...
    def value(self) -> bytes: ...


class _HeadBuffer:
    """Keep the first ``limit`` bytes; count the rest as truncated."""

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._chunks: list[bytes] = []
        self._size = 0
        self.truncated = False

    async def feed(self, data: bytes) -> None:
        room = self._limit - self._size
        if room <= 0:
            self.truncated = True
            return
        if len(data) > room:
            data = data[:room]
            self.truncated = True
        self._chunks.append(data)
        self._size += len(data)

    async def close(self) -> None:
        return None

    def value(self) -> bytes:
        return b"".join(self._chunks)


class _LineSink:
    """Split a byte stream into lines for a callback, and keep the last ``tail`` bytes.

    ``\\n``, ``\\r\\n`` and a lone ``\\r`` all end a line (FFmpeg's status line on stderr is
    rewritten with ``\\r``). A ``\\r`` at the end of a chunk waits for the next chunk, so a
    ``\\r\\n`` split across two reads is still one line end.
    """

    def __init__(self, callback: LineCallback | None, tail: int) -> None:
        self._callback = callback
        self._tail_limit = tail
        self._tail = bytearray()
        self._pending = bytearray()
        self.truncated = False

    async def feed(self, data: bytes) -> None:
        self._keep_tail(data)
        if self._callback is None:
            return
        self._pending += data
        buf = self._pending
        start = 0
        i = 0
        n = len(buf)
        while i < n:
            byte = buf[i]
            if byte == 0x0A:  # \n
                await self._emit(bytes(buf[start:i]))
                start = i = i + 1
            elif byte == 0x0D:  # \r
                if i + 1 == n:
                    break  # wait: the next chunk may start with \n
                await self._emit(bytes(buf[start:i]))
                i += 2 if buf[i + 1] == 0x0A else 1
                start = i
            else:
                i += 1
        del buf[:start]
        while len(buf) >= MAX_LINE:
            await self._emit(bytes(buf[:MAX_LINE]))
            del buf[:MAX_LINE]

    async def close(self) -> None:
        if self._callback is None or not self._pending:
            return
        rest = bytes(self._pending)
        self._pending.clear()
        if rest.endswith(b"\r"):  # a \r at the very end still ends the last line
            rest = rest[:-1]
        await self._emit(rest)

    async def _emit(self, line: bytes) -> None:
        assert self._callback is not None
        result = self._callback(line.decode("utf-8", errors="replace"))
        if inspect.isawaitable(result):
            await result

    def _keep_tail(self, data: bytes) -> None:
        if self._tail_limit <= 0:
            if data:
                self.truncated = True
            return
        self._tail += data
        excess = len(self._tail) - self._tail_limit
        if excess > 0:
            del self._tail[:excess]
            self.truncated = True

    def value(self) -> bytes:
        return bytes(self._tail)


async def _pump(stream: asyncio.StreamReader | None, sink: _Sink) -> None:
    if stream is None:
        return
    while True:
        data = await stream.read(_READ_SIZE)
        if not data:
            break
        await sink.feed(data)
    await sink.close()


def _collect_tree(proc: psutil.Process) -> list[psutil.Process]:
    try:
        return proc.children(recursive=True)
    except psutil.Error:
        return []


def kill_process_tree(pid: int, *, kill_root: bool = True) -> list[psutil.Process]:
    """Kill the descendants of ``pid`` (children first), then ``pid`` itself (unless
    ``kill_root`` is false: then the root keeps running).

    The root is suspended first, so it cannot start new children while they are killed; the
    tree is listed again until no new process shows up. On POSIX the root's process group is
    killed as well: a descendant whose parent already exited cannot be found through the parent.

    Returns the descendants that were signalled (not the root: the caller reaps it, so that
    asyncio gets its exit code). Errors for processes that are already gone are ignored.
    """
    try:
        root = psutil.Process(pid)
    except psutil.Error:
        return []
    with contextlib.suppress(psutil.Error):
        root.suspend()
    killed: dict[int, psutil.Process] = {}
    for _ in range(10):
        new = [p for p in _collect_tree(root) if p.pid not in killed]
        if not new:
            break
        for child in reversed(new):  # deepest first (psutil lists parents before children)
            with contextlib.suppress(psutil.Error):
                child.kill()
            killed[child.pid] = child
    if kill_root:
        group_leader = False
        if sys.platform != "win32":
            with contextlib.suppress(OSError):
                group_leader = os.getpgid(pid) == pid
        with contextlib.suppress(psutil.Error):
            root.kill()
        if sys.platform != "win32" and group_leader:
            with contextlib.suppress(OSError):
                os.killpg(pid, signal.SIGKILL)  # Reframe's children lead their own group
    else:
        with contextlib.suppress(psutil.Error):
            root.resume()
    return list(killed.values())


def _create_time(pid: int) -> float | None:
    try:
        return psutil.Process(pid).create_time()
    except psutil.Error:
        return None


def kill_leftovers(
    pid: int, *, created_after: float | None = None, platform: str | None = None
) -> list[psutil.Process]:
    """Kill what is left of the tree of ``pid`` after ``pid`` itself exited.

    POSIX: Reframe's children lead their own process group (``start_new_session``), so every
    remaining member of the group ``pid`` is killed. The kernel does not reuse a pid while it
    is still a process group id, so this cannot hit an unrelated group.

    Windows: orphans keep their parent's pid as ``ppid``, so the processes whose ``ppid`` is
    ``pid`` and that started after ``created_after`` (the dead child's start time; this rules
    out a reused pid) are killed with their trees.

    Returns the processes that were signalled (wait for them with psutil).
    """
    platform = sys.platform if platform is None else platform
    killed: list[psutil.Process] = []
    if platform != "win32":
        # Looked up when called: Windows has neither, so a test there stands them in.
        getpgid: Callable[[int], int] = getattr(os, "getpgid")  # noqa: B009
        killpg: Callable[[int, int], None] = getattr(os, "killpg")  # noqa: B009
        for candidate in psutil.process_iter():
            with contextlib.suppress(psutil.Error, OSError):
                if getpgid(candidate.pid) == pid:
                    killed.append(candidate)
        with contextlib.suppress(OSError):
            killpg(pid, int(getattr(signal, "SIGKILL", 9)))
        return killed
    for candidate in psutil.process_iter(["ppid", "create_time"]):
        info = candidate.info
        if info.get("ppid") != pid:
            continue
        started = info.get("create_time")
        if created_after is not None and (started is None or started < created_after - 1.0):
            continue
        killed.extend(kill_process_tree(candidate.pid))
        killed.append(candidate)
    return killed


async def _wait_gone(procs: Sequence[psutil.Process], limit: float) -> None:
    """Wait (without blocking the loop) until ``procs`` are gone or zombies."""
    deadline = time.monotonic() + limit
    pending = list(procs)
    while pending and time.monotonic() < deadline:
        still = []
        for p in pending:
            try:
                if p.status() != psutil.STATUS_ZOMBIE:
                    still.append(p)
            except psutil.Error:
                pass
        pending = still
        if pending:
            await asyncio.sleep(0.02)


def _check_args(argv: Sequence[str], timeout: float | None, max_output: int) -> list[str]:
    if isinstance(argv, (str, bytes)):
        raise TypeError("argv must be a sequence of arguments, not a single string")
    args = [os.fspath(a) for a in argv]
    if not args:
        raise ValueError("argv is empty")
    if timeout is not None and not timeout > 0:
        raise ValueError(f"timeout must be > 0 seconds, got {timeout!r}")
    if max_output < 0:
        raise ValueError(f"max_output must be >= 0, got {max_output!r}")
    return args


def _child_env(extra_env: Mapping[str, str] | None) -> dict[str, str]:
    env = childproc.user_environ()
    env.update(extra_env or {})
    return env


async def _execute(
    args: list[str],
    *,
    timeout: float | None,  # noqa: ASYNC109 - a deadline for the child, not for this coroutine
    cancel: CancelToken | None,
    cwd: Path | None,
    extra_env: Mapping[str, str] | None,
    out_sink: _Sink,
    err_sink: _Sink,
    on_start: Callable[[int], None] | None = None,
) -> RunResult:
    started = time.monotonic()
    if cancel is not None and cancel.cancelled:
        return RunResult(None, b"", b"", 0.0, cancelled=True, argv=tuple(args))
    try:
        proc = await _spawn(
            args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=_child_env(extra_env),
            **childproc.spawn_options(),
        )
    except OSError as exc:
        return RunResult(
            None,
            b"",
            b"",
            time.monotonic() - started,
            error=f"{type(exc).__name__}: {exc}",
            argv=tuple(args),
        )
    childproc.after_spawn(proc.pid)
    created = _create_time(proc.pid)

    readers = [
        asyncio.ensure_future(_pump(proc.stdout, out_sink)),
        asyncio.ensure_future(_pump(proc.stderr, err_sink)),
    ]
    waiter = asyncio.ensure_future(proc.wait())
    cancel_waiter = asyncio.ensure_future(cancel.wait()) if cancel is not None else None

    timed_out = cancelled = False
    deadline = None if timeout is None else started + timeout
    try:
        if on_start is not None:
            on_start(proc.pid)  # inside the try: if it raises, the finally kills the tree
        watch: set[asyncio.Future[Any]] = {waiter, *readers}
        if cancel_waiter is not None:
            watch.add(cancel_waiter)
        while not waiter.done():
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                timed_out = True
                break
            done, _ = await asyncio.wait(
                watch, timeout=remaining, return_when=asyncio.FIRST_COMPLETED
            )
            if waiter in done:
                break  # it exited: an exit at the same moment as a cancel is a normal exit
            if cancel_waiter is not None and cancel_waiter in done:
                cancelled = True
                break
            for task in done:
                if task in readers:
                    task.result()  # a callback raised: re-raise (the finally kills the tree)
                    watch.discard(task)
        if (timed_out or cancelled) and proc.returncode is None:
            await _kill_and_reap(proc)
        # The process has exited: give the pipes a short time to reach EOF.
        _, still_open = await asyncio.wait(readers, timeout=PIPE_DRAIN_GRACE)
        if still_open:
            # A descendant that outlived the process still holds a pipe: kill what is left.
            leftovers = kill_leftovers(proc.pid, created_after=created)
            _, still_open = await asyncio.wait(still_open, timeout=PIPE_DRAIN_GRACE)
            await _wait_gone(leftovers, limit=5.0)
        for task in still_open:
            task.cancel()
        for task in readers:
            if task.done() and not task.cancelled():
                task.result()
    finally:
        if proc.returncode is None:  # an exception or a cancelled caller: never leak
            await asyncio.shield(_kill_and_reap(proc))
        for task in (*readers, *(t for t in (cancel_waiter,) if t is not None)):
            if not task.done():
                task.cancel()
        await asyncio.gather(*readers, *(t for t in (cancel_waiter,) if t), return_exceptions=True)
        if not waiter.done():
            waiter.cancel()
        _close_transport(proc)

    return RunResult(
        proc.returncode,
        out_sink.value(),
        err_sink.value(),
        time.monotonic() - started,
        timed_out=timed_out,
        cancelled=cancelled,
        truncated=out_sink.truncated or err_sink.truncated,
        argv=tuple(args),
    )


async def _spawn(args: list[str], **options: Any) -> asyncio.subprocess.Process:
    # A cancel inside create_subprocess_exec closes the transport while its pipes are still
    # being connected: a pipe connected later is never closed, and only the child is killed.
    spawn = asyncio.ensure_future(asyncio.create_subprocess_exec(*args, **options))
    try:
        return await asyncio.shield(spawn)
    except asyncio.CancelledError:
        await asyncio.shield(_end_cancelled_spawn(spawn))
        raise


async def _end_cancelled_spawn(spawn: asyncio.Future[asyncio.subprocess.Process]) -> None:
    await asyncio.wait({spawn})
    if spawn.cancelled() or spawn.exception() is not None:
        return
    proc = spawn.result()
    try:
        await _kill_and_reap(proc)
    finally:
        _close_transport(proc)


async def _kill_and_reap(proc: asyncio.subprocess.Process) -> None:
    # Not proc.kill(): on POSIX, Popen.send_signal() first polls with waitpid(), which can
    # reap the child before asyncio's child watcher sees it (exit code 255 and a warning).
    descendants = kill_process_tree(proc.pid)
    try:
        await asyncio.wait_for(proc.wait(), timeout=10.0)
    except TimeoutError:  # pragma: no cover - psutil could not kill it
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        await proc.wait()
    await _wait_gone(descendants, limit=5.0)


def _close_transport(proc: asyncio.subprocess.Process) -> None:
    transport = getattr(proc, "_transport", None)
    if transport is not None:
        with contextlib.suppress(Exception):
            transport.close()


async def run(
    argv: Sequence[str],
    *,
    timeout: float,  # noqa: ASYNC109 - a deadline for the child, not for this coroutine
    cancel: CancelToken | None = None,
    max_output: int = DEFAULT_MAX_OUTPUT,
    cwd: Path | None = None,
    extra_env: Mapping[str, str] | None = None,
) -> RunResult:
    """Run ``argv`` and collect its output.

    :param timeout: seconds of wall-clock time; then the process tree is killed and
        ``timed_out`` is set.
    :param cancel: cancelling the token kills the process tree and sets ``cancelled``.
    :param max_output: bytes kept **per stream** (the rest is read and dropped, and
        ``truncated`` is set).
    :param cwd: working directory of the process.
    :param extra_env: variables added to (or replacing ones in) the current environment.
    The process's stdin is the null device.
    """
    args = _check_args(argv, timeout, max_output)
    return await _execute(
        args,
        timeout=timeout,
        cancel=cancel,
        cwd=cwd,
        extra_env=extra_env,
        out_sink=_HeadBuffer(max_output),
        err_sink=_HeadBuffer(max_output),
    )


async def run_streaming(
    argv: Sequence[str],
    *,
    on_stdout_line: LineCallback | None,
    on_stderr_line: LineCallback | None,
    cancel: CancelToken | None,
    extra_env: Mapping[str, str] | None = None,
    on_start: Callable[[int], None] | None = None,
) -> RunResult:
    """Run ``argv`` and pass each output line to a callback as it arrives.

    Lines end at ``\\n``, ``\\r\\n`` or ``\\r``; the callback gets the text without the line
    end. A callback may be a coroutine function; it is awaited before the next line of that
    stream is read. If a callback raises, the process tree is killed and the exception
    propagates. There is no time limit: use ``cancel`` to stop it.

    :param on_start: called once with the pid of the started process, before any output is
        read. If it raises, the process tree is killed and the exception propagates.
    """
    args = _check_args(argv, None, DEFAULT_STREAMING_TAIL)
    return await _execute(
        args,
        timeout=None,
        cancel=cancel,
        cwd=None,
        extra_env=extra_env,
        out_sink=_LineSink(on_stdout_line, DEFAULT_STREAMING_TAIL),
        err_sink=_LineSink(on_stderr_line, DEFAULT_STREAMING_TAIL),
        on_start=on_start,
    )
