"""The power executors (05 §C-14): the Linux ``systemctl`` argv and the Windows calls, every
one with a fake command runner or mocked DLLs. Nothing here reaches the operating system."""

from __future__ import annotations

import ctypes
import threading
from collections.abc import Sequence
from typing import Any

import pytest

from reframe.platform import power
from reframe.platform.power import (
    COMMAND_TIMEOUT,
    ERROR_NOT_ALL_ASSIGNED,
    SE_PRIVILEGE_ENABLED,
    TOKEN_ADJUST_PRIVILEGES,
    TOKEN_QUERY,
    WINDOWS_SHUTDOWN_COMMENT,
    SystemctlExecutor,
    UnsupportedExecutor,
    Win32Libraries,
    WindowsExecutor,
    default_executor,
    systemctl_argv,
    windows_shutdown_argv,
)
from reframe.tools import RunResult

pytestmark = pytest.mark.anyio


def result(
    returncode: int | None = 0,
    *,
    stdout: bytes = b"",
    stderr: bytes = b"",
    error: str | None = None,
    timed_out: bool = False,
    cancelled: bool = False,
) -> RunResult:
    return RunResult(
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        duration=0.01,
        error=error,
        timed_out=timed_out,
        cancelled=cancelled,
    )


class FakeRunner:
    """A fake command runner: records the argv, returns ``answer``."""

    def __init__(self, answer: RunResult | None = None) -> None:
        self.calls: list[list[str]] = []
        self.answer = answer if answer is not None else result()

    async def __call__(self, argv: Sequence[str]) -> RunResult:
        self.calls.append(list(argv))
        return self.answer


# --------------------------------------------------------------------------- Linux


@pytest.mark.parametrize(("action", "verb"), [("shutdown", "poweroff"), ("sleep", "suspend")])
async def test_systemctl_argv_and_success(action: power.OsAction, verb: str) -> None:
    run = FakeRunner()
    assert await SystemctlExecutor(run=run).execute(action) is None
    assert run.calls == [["systemctl", "--no-ask-password", verb]]
    assert systemctl_argv(action, "/usr/bin/systemctl") == [
        "/usr/bin/systemctl",
        "--no-ask-password",
        verb,
    ]


async def test_systemctl_path_can_be_given() -> None:
    run = FakeRunner()
    await SystemctlExecutor(run=run, systemctl="/usr/bin/systemctl").execute("sleep")
    assert run.calls == [["/usr/bin/systemctl", "--no-ask-password", "suspend"]]


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (
            result(1, stderr=b"Call to PowerOff failed: Access denied\n"),
            "systemctl poweroff failed (exit code 1): Call to PowerOff failed: Access denied",
        ),
        (
            # polkit without --no-ask-password prompts; with it, systemctl says this
            result(1, stderr=b"\nCall to PowerOff failed: Interactive authentication required.\n"),
            "systemctl poweroff failed (exit code 1): "
            "Call to PowerOff failed: Interactive authentication required.",
        ),
        (
            result(1, stdout=b"System has not been booted with systemd as init system (PID 1).\n"),
            "systemctl poweroff failed (exit code 1): "
            "System has not been booted with systemd as init system (PID 1).",
        ),
        (result(3), "systemctl poweroff failed (exit code 3)"),
        (
            result(None, error="FileNotFoundError: [Errno 2] No such file or directory"),
            "systemctl poweroff could not be started: "
            "FileNotFoundError: [Errno 2] No such file or directory",
        ),
        (
            result(-9, timed_out=True),
            f"systemctl poweroff did not finish within {COMMAND_TIMEOUT:g} s",
        ),
        (result(-9, cancelled=True), "systemctl poweroff was cancelled"),
    ],
)
async def test_systemctl_failures_are_strings(answer: RunResult, expected: str) -> None:
    assert await SystemctlExecutor(run=FakeRunner(answer)).execute("shutdown") == expected


# --------------------------------------------------------------------------- Windows: shut down


async def test_windows_shutdown_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYSTEMROOT", "D:\\Win")
    run = FakeRunner()
    assert await WindowsExecutor(run=run).execute("shutdown") is None
    assert run.calls == [
        ["D:\\Win\\System32\\shutdown.exe", "/s", "/t", "60", "/c", WINDOWS_SHUTDOWN_COMMENT]
    ]
    assert len(WINDOWS_SHUTDOWN_COMMENT) <= 512  # shutdown /c takes at most 512 characters


def test_windows_shutdown_exe_without_system_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SYSTEMROOT", raising=False)
    assert windows_shutdown_argv()[0] == "C:\\Windows\\System32\\shutdown.exe"
    assert windows_shutdown_argv("x.exe")[:4] == ["x.exe", "/s", "/t", "60"]


async def test_windows_shutdown_failure() -> None:
    run = FakeRunner(
        result(1190, stderr=b"A system shutdown has already been scheduled.(1190)\r\n")
    )
    detail = await WindowsExecutor(run=run, shutdown_exe="shutdown.exe").execute("shutdown")
    assert detail == (
        "shutdown /s failed (exit code 1190): A system shutdown has already been scheduled.(1190)"
    )


async def test_windows_shutdown_never_loads_the_dlls() -> None:
    def no_dlls() -> Win32Libraries:
        raise AssertionError("shutdown must not load powrprof")

    run = FakeRunner()
    await WindowsExecutor(run=run, libraries=no_dlls, shutdown_exe="s.exe").execute("shutdown")
    assert len(run.calls) == 1


# --------------------------------------------------------------------------- Windows: sleep


class FakeWin32:
    """Mocked ``powrprof`` / ``advapi32`` / ``kernel32`` with the Win32 call semantics."""

    PROCESS = 0xFFFF  # GetCurrentProcess's pseudo handle
    TOKEN = 0x1234
    SHUTDOWN_LUID = 19

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.threads: list[str] = []
        self.open_ok = True
        self.lookup_ok = True
        self.adjust_ok = True
        self.adjust_error = 0
        self.suspend_result = 1
        self.suspend_raises: Exception | None = None
        self.error = 0

    # kernel32
    def GetCurrentProcess(self) -> int:
        self.calls.append(("GetCurrentProcess",))
        return self.PROCESS

    def CloseHandle(self, handle: Any) -> int:
        self.calls.append(("CloseHandle", handle.value))
        return 1

    # advapi32
    def OpenProcessToken(self, process: Any, access: int, token: Any) -> int:
        self.calls.append(("OpenProcessToken", process, access))
        if not self.open_ok:
            self.error = 5
            return 0
        token._obj.value = self.TOKEN
        return 1

    def LookupPrivilegeValueW(self, system: str | None, name: str, luid: Any) -> int:
        self.calls.append(("LookupPrivilegeValueW", system, name))
        if not self.lookup_ok:
            self.error = 1313
            return 0
        luid._obj.LowPart = self.SHUTDOWN_LUID
        return 1

    def AdjustTokenPrivileges(
        self,
        token: Any,
        disable_all: bool,
        new_state: Any,
        length: int,
        previous_state: Any,
        return_length: Any,
    ) -> int:
        state = new_state._obj
        privilege = state.Privileges[0]
        self.calls.append(
            (
                "AdjustTokenPrivileges",
                token.value,
                disable_all,
                state.PrivilegeCount,
                privilege.Luid.LowPart,
                privilege.Attributes,
                length,
                previous_state,
                return_length,
            )
        )
        if not self.adjust_ok:
            self.error = 6
            return 0
        self.error = self.adjust_error
        return 1

    # powrprof
    def SetSuspendState(self, hibernate: bool, force: bool, wakeup_events_disabled: bool) -> int:
        self.calls.append(("SetSuspendState", hibernate, force, wakeup_events_disabled))
        self.threads.append(threading.current_thread().name)
        if self.suspend_raises is not None:
            raise self.suspend_raises
        if not self.suspend_result:
            self.error = 50
        return self.suspend_result

    def libraries(self) -> Win32Libraries:
        return Win32Libraries(
            powrprof=self, advapi32=self, kernel32=self, last_error=lambda: self.error
        )


def names(calls: list[tuple[Any, ...]]) -> list[str]:
    return [str(call[0]) for call in calls]


async def test_windows_sleep_enables_the_privilege_then_suspends_on_a_worker_thread() -> None:
    win = FakeWin32()
    run = FakeRunner()
    assert await WindowsExecutor(run=run, libraries=win.libraries).execute("sleep") is None
    assert win.calls == [
        ("GetCurrentProcess",),
        ("OpenProcessToken", FakeWin32.PROCESS, TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY),
        ("LookupPrivilegeValueW", None, "SeShutdownPrivilege"),
        (
            "AdjustTokenPrivileges",
            FakeWin32.TOKEN,
            False,
            1,
            FakeWin32.SHUTDOWN_LUID,
            SE_PRIVILEGE_ENABLED,
            0,
            None,
            None,
        ),
        ("CloseHandle", FakeWin32.TOKEN),
        # sleep, not hibernate; bForce has no effect; wake events stay enabled
        ("SetSuspendState", False, False, False),
    ]
    assert win.threads != [threading.current_thread().name]  # never on the event loop
    assert run.calls == []  # no shutdown.exe for sleep


@pytest.mark.parametrize(
    ("setup", "expected", "called"),
    [
        (
            {"open_ok": False},
            "OpenProcessToken failed (error 5)",
            ["GetCurrentProcess", "OpenProcessToken"],
        ),
        (
            {"lookup_ok": False},
            "LookupPrivilegeValueW(SeShutdownPrivilege) failed (error 1313)",
            ["GetCurrentProcess", "OpenProcessToken", "LookupPrivilegeValueW", "CloseHandle"],
        ),
        (
            {"adjust_ok": False},
            "AdjustTokenPrivileges failed (error 6)",
            [
                "GetCurrentProcess",
                "OpenProcessToken",
                "LookupPrivilegeValueW",
                "AdjustTokenPrivileges",
                "CloseHandle",
            ],
        ),
        (
            {"adjust_error": ERROR_NOT_ALL_ASSIGNED},
            "this account does not hold SeShutdownPrivilege",
            [
                "GetCurrentProcess",
                "OpenProcessToken",
                "LookupPrivilegeValueW",
                "AdjustTokenPrivileges",
                "CloseHandle",
            ],
        ),
        (
            {"suspend_result": 0},
            "SetSuspendState failed (error 50)",
            [
                "GetCurrentProcess",
                "OpenProcessToken",
                "LookupPrivilegeValueW",
                "AdjustTokenPrivileges",
                "CloseHandle",
                "SetSuspendState",
            ],
        ),
        (
            {"suspend_raises": ctypes.ArgumentError("argument 1: wrong type")},
            "SetSuspendState failed: ArgumentError: argument 1: wrong type",
            [
                "GetCurrentProcess",
                "OpenProcessToken",
                "LookupPrivilegeValueW",
                "AdjustTokenPrivileges",
                "CloseHandle",
                "SetSuspendState",
            ],
        ),
    ],
)
async def test_windows_sleep_failures_are_strings(
    setup: dict[str, Any], expected: str, called: list[str]
) -> None:
    win = FakeWin32()
    for name, value in setup.items():
        setattr(win, name, value)
    assert await WindowsExecutor(libraries=win.libraries).execute("sleep") == expected
    assert names(win.calls) == called


async def test_windows_sleep_without_powrprof() -> None:
    def missing() -> Win32Libraries:
        raise OSError("[WinError 126] The specified module could not be found")

    detail = await WindowsExecutor(libraries=missing).execute("sleep")
    assert detail == (
        "powrprof not available: [WinError 126] The specified module could not be found"
    )


# --------------------------------------------------------------------------- per platform


def test_default_executor_per_platform() -> None:
    assert isinstance(default_executor("win32"), WindowsExecutor)
    assert isinstance(default_executor("linux"), SystemctlExecutor)
    other = default_executor("darwin")
    assert isinstance(other, UnsupportedExecutor)
    assert other.reason == "power actions are not supported on 'darwin'"


async def test_unsupported_executor_fails_every_action() -> None:
    executor = UnsupportedExecutor("no power actions here")
    assert await executor.execute("shutdown") == "no power actions here"
    assert await executor.execute("sleep") == "no power actions here"
