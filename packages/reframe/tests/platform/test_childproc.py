"""reframe.platform.childproc: PDEATHSIG (Linux) and the Windows Job Object (mocked kernel32).

The Windows code cannot run on Linux, so these tests replace ``kernel32`` with a mock and
check the calls: which functions, in which order, with which flags.
"""

from __future__ import annotations

import ctypes
import os
import signal
from typing import Any
from unittest import mock

import pytest

from reframe.platform import childproc
from reframe.platform.childproc import (
    CREATE_NO_WINDOW,
    JOB_OBJECT_LIMIT_BREAKAWAY_OK,
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    KillOnCloseJob,
)

JOB = 0x1234
CURRENT_PROCESS = -1  # the pseudo handle that GetCurrentProcess() returns
CHILD_HANDLE = 0x5678
SIGKILL = int(getattr(signal, "SIGKILL", 9))


def _kernel32(*, create: int = JOB, set_info: int = 1, assign_self: int = 1) -> mock.Mock:
    k32 = mock.Mock(name="kernel32")
    k32.CreateJobObjectW.return_value = create
    k32.SetInformationJobObject.return_value = set_info
    k32.GetCurrentProcess.return_value = CURRENT_PROCESS
    k32.OpenProcess.return_value = CHILD_HANDLE

    def assign(job: int, process: int) -> int:
        return assign_self if process == CURRENT_PROCESS else 1

    k32.AssignProcessToJobObject.side_effect = assign
    k32.CloseHandle.return_value = 1
    return k32


def _names(k32: mock.Mock) -> list[str]:
    return [c[0] for c in k32.mock_calls]


def test_job_assigns_reframe_itself_with_kill_on_close() -> None:
    k32 = _kernel32()
    job = KillOnCloseJob(k32, last_error=lambda: 0)
    assert job.setup() == "process"
    assert _names(k32) == [
        "CreateJobObjectW",
        "SetInformationJobObject",
        "GetCurrentProcess",
        "AssignProcessToJobObject",
    ]
    k32.CreateJobObjectW.assert_called_once_with(None, None)
    handle, info_class, pointer, size = k32.SetInformationJobObject.call_args.args
    assert handle == JOB
    assert info_class == 9  # JobObjectExtendedLimitInformation
    info = pointer.contents
    assert isinstance(info, childproc.JobObjectExtendedLimitInformation)
    flags = info.BasicLimitInformation.LimitFlags
    assert flags == JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_BREAKAWAY_OK
    assert flags & 0x00002000  # KILL_ON_JOB_CLOSE
    assert not flags & 0x00001000  # never SILENT_BREAKAWAY_OK: children must stay in the job
    assert size == ctypes.sizeof(childproc.JobObjectExtendedLimitInformation)
    k32.AssignProcessToJobObject.assert_called_once_with(JOB, CURRENT_PROCESS)
    k32.CloseHandle.assert_not_called()  # the job handle stays open for the process lifetime
    assert job.handle == JOB


def test_extended_limit_information_has_the_windows_layout() -> None:
    # 64-bit layout of JOBOBJECT_EXTENDED_LIMIT_INFORMATION (winnt.h): 144 bytes.
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        assert ctypes.sizeof(childproc.JobObjectExtendedLimitInformation) == 144
        assert childproc._BasicLimitInformation.LimitFlags.offset == 16


def test_job_setup_runs_once() -> None:
    k32 = _kernel32()
    job = KillOnCloseJob(k32)
    job.setup()
    job.setup()
    assert k32.CreateJobObjectW.call_count == 1


def test_children_inherit_the_job_in_process_mode() -> None:
    k32 = _kernel32()
    job = KillOnCloseJob(k32)
    assert job.adopt(4242) is True
    k32.OpenProcess.assert_not_called()  # nothing to do: the child was born in the job


def test_fallback_assigns_each_child_when_reframe_cannot_join() -> None:
    k32 = _kernel32(assign_self=0)
    job = KillOnCloseJob(k32, last_error=lambda: 5)  # ERROR_ACCESS_DENIED
    assert job.setup() == "per_child"
    assert job.error is not None
    assert "error 5" in job.error
    k32.reset_mock()
    assert job.adopt(4242) is True
    assert _names(k32) == ["OpenProcess", "AssignProcessToJobObject", "CloseHandle"]
    access, inherit, pid = k32.OpenProcess.call_args.args
    assert access == childproc.PROCESS_SET_QUOTA | childproc.PROCESS_TERMINATE
    assert inherit is False
    assert pid == 4242
    k32.AssignProcessToJobObject.assert_called_once_with(JOB, CHILD_HANDLE)
    k32.CloseHandle.assert_called_once_with(CHILD_HANDLE)


def test_fallback_child_that_is_gone() -> None:
    k32 = _kernel32(assign_self=0)
    k32.OpenProcess.return_value = 0
    job = KillOnCloseJob(k32)
    assert job.adopt(4242) is False
    k32.CloseHandle.assert_not_called()


def test_job_unavailable_when_create_fails() -> None:
    k32 = _kernel32(create=0)
    job = KillOnCloseJob(k32, last_error=lambda: 8)
    assert job.setup() == "unavailable"
    assert job.error is not None
    assert "CreateJobObjectW" in job.error
    assert job.adopt(1) is False
    assert _names(k32) == ["CreateJobObjectW"]


def test_job_unavailable_when_limits_cannot_be_set() -> None:
    k32 = _kernel32(set_info=0)
    job = KillOnCloseJob(k32, last_error=lambda: 87)
    assert job.setup() == "unavailable"
    assert job.error is not None
    assert "SetInformationJobObject" in job.error
    k32.CloseHandle.assert_called_once_with(JOB)  # a job without the limit is useless
    k32.AssignProcessToJobObject.assert_not_called()


def test_windows_spawn_options(monkeypatch: pytest.MonkeyPatch) -> None:
    k32 = _kernel32()
    job = KillOnCloseJob(k32)
    monkeypatch.setattr(childproc, "_job", job)
    options = childproc.spawn_options("win32")
    assert options == {"creationflags": CREATE_NO_WINDOW}
    assert CREATE_NO_WINDOW == 0x08000000
    # Reframe joined the job before the first child starts.
    assert _names(k32)[-1] == "AssignProcessToJobObject"
    assert job.mode == "process"


def test_windows_after_spawn_adopts_in_fallback_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    k32 = _kernel32(assign_self=0)
    job = KillOnCloseJob(k32)
    monkeypatch.setattr(childproc, "_job", job)
    childproc.after_spawn(777, "win32")
    k32.OpenProcess.assert_called_once()
    assert k32.OpenProcess.call_args.args[2] == 777


def test_windows_job_is_created_lazily(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[KillOnCloseJob] = []

    class FakeJob(KillOnCloseJob):
        def __init__(self) -> None:
            super().__init__(_kernel32())
            created.append(self)

    monkeypatch.setattr(childproc, "_job", None)
    monkeypatch.setattr(childproc, "KillOnCloseJob", FakeJob)
    first = childproc.windows_job()
    second = childproc.windows_job()
    assert first is second
    assert created == [first]


def test_posix_after_spawn_is_a_no_op() -> None:
    childproc.after_spawn(1, "linux")


def test_linux_spawn_options() -> None:
    options = childproc.spawn_options("linux")
    assert options["start_new_session"] is True
    assert callable(options["preexec_fn"])


def test_other_posix_spawn_options() -> None:
    assert childproc.spawn_options("darwin") == {"start_new_session": True}


def test_preexec_sets_pdeathsig() -> None:
    calls: list[tuple[Any, ...]] = []

    def prctl(*args: Any) -> int:
        calls.append(args)
        return 0

    preexec = childproc.linux_preexec(os.getppid(), prctl=prctl)
    preexec()  # we are not in a forked child, so make the parent check pass with getppid()
    assert calls == [(childproc.PR_SET_PDEATHSIG, SIGKILL, 0, 0, 0)]


def test_preexec_kills_itself_when_the_parent_is_already_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: killed.append((pid, sig)))
    preexec = childproc.linux_preexec(parent_pid=-12345, prctl=lambda *a: 0)
    preexec()
    assert killed == [(os.getpid(), SIGKILL)]


@pytest.mark.skipif(os.name != "posix", reason="libc prctl")
def test_real_prctl_is_loaded() -> None:
    preexec = childproc.linux_preexec()
    assert callable(preexec)
