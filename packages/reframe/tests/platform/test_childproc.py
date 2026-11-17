"""reframe.platform.childproc: PDEATHSIG (Linux) and the Windows Job Object (mocked kernel32)."""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
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
# GetCurrentProcess's (HANDLE)-1, which a HANDLE restype returns unsigned.
CURRENT_PROCESS = (1 << 8 * ctypes.sizeof(ctypes.c_void_p)) - 1
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
    # 64-bit layout of JOBOBJECT_EXTENDED_LIMIT_INFORMATION (winnt.h).
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

    preexec = childproc.linux_preexec(prctl=prctl)
    assert preexec is not None
    preexec()
    assert calls == [(childproc.PR_SET_PDEATHSIG, SIGKILL, 0, 0, 0)]


_LOCKED_TRACER = """
import os, subprocess, sys, threading
import reframe
from reframe.platform import childproc

measured = os.path.dirname(reframe.__file__)
parent = os.getpid()
held = threading.Lock()
tool = next(i for i in range(6) if sys.monitoring.get_tool(i) is None)
sys.monitoring.use_tool_id(tool, "test")

def py_start(code, offset):
    if os.getpid() != parent and code.co_filename.startswith(measured):
        held.acquire()
    return sys.monitoring.DISABLE

sys.monitoring.register_callback(tool, sys.monitoring.events.PY_START, py_start)
sys.monitoring.set_events(tool, sys.monitoring.events.PY_START)
options = childproc.spawn_options()
held.acquire()
print(subprocess.run(["true"], **options).returncode)
"""


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="PR_SET_PDEATHSIG is Linux-only")
def test_a_tracer_lock_held_at_the_fork_does_not_block_a_spawn() -> None:
    """A tracer that takes a lock on the first call of measured code (as coverage does) blocks a
    forked child forever when another thread held that lock at the fork, if the ``preexec_fn`` is
    Reframe's Python code. The stdlib's at-fork hooks still run there; they are not measured."""
    result = subprocess.run(
        [sys.executable, "-c", _LOCKED_TRACER], capture_output=True, text=True, timeout=60
    )
    assert (result.returncode, result.stdout.strip()) == (0, "0"), result.stderr


class _FakePopen:
    """Records the arguments; ``wait`` returns at once (the reaper thread calls it)."""

    calls: list[tuple[list[str], dict[str, Any]]]

    def __init__(self, fail_first: BaseException | None = None) -> None:
        self.calls = []
        self.fail_first = fail_first

    def __call__(self, argv: list[str], **kwargs: Any) -> Any:
        self.calls.append((argv, kwargs))
        if self.fail_first is not None:
            error, self.fail_first = self.fail_first, None
            raise error
        return mock.Mock(pid=4321, wait=mock.Mock(return_value=0))


def _no_job(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail() -> None:
        raise AssertionError("a user-facing launch must not need the job")

    monkeypatch.setattr(childproc, "windows_job", fail)


def test_user_facing_spawn_options(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_job(monkeypatch)
    win = childproc.spawn_options("win32", user_facing=True)
    assert win == {
        "creationflags": childproc.CREATE_BREAKAWAY_FROM_JOB | childproc.CREATE_NEW_PROCESS_GROUP
    }
    assert not win["creationflags"] & CREATE_NO_WINDOW
    assert childproc.CREATE_BREAKAWAY_FROM_JOB == 0x01000000
    linux = childproc.spawn_options("linux", user_facing=True)
    assert linux == {"start_new_session": True}  # no PDEATHSIG: it outlives Reframe


def test_launch_detached_on_windows_breaks_away_from_the_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_job(monkeypatch)
    popen = _FakePopen()
    pid = childproc.launch_detached(
        ["explorer.exe", "C:\\Videos\\out.mkv"], platform="win32", popen=popen
    )
    assert pid == 4321
    ((argv, kwargs),) = popen.calls
    assert argv == ["explorer.exe", "C:\\Videos\\out.mkv"]
    assert kwargs["creationflags"] & childproc.CREATE_BREAKAWAY_FROM_JOB
    assert not kwargs["creationflags"] & CREATE_NO_WINDOW
    assert kwargs["stdin"] == kwargs["stdout"] == kwargs["stderr"] == subprocess.DEVNULL
    assert kwargs["close_fds"] is True


def test_launch_detached_retries_inside_a_job_that_forbids_breakaway() -> None:
    popen = _FakePopen(fail_first=PermissionError(13, "Access is denied"))
    assert childproc.launch_detached(["player.exe", "a.mkv"], platform="win32", popen=popen) == 4321
    first, second = (kwargs["creationflags"] for _, kwargs in popen.calls)
    assert first & childproc.CREATE_BREAKAWAY_FROM_JOB
    assert second == childproc.CREATE_NEW_PROCESS_GROUP


def test_launch_detached_on_posix() -> None:
    popen = _FakePopen()
    childproc.launch_detached(
        ["xdg-open", "/media/out.mkv"], cwd="/media", platform="linux", popen=popen
    )
    ((_, kwargs),) = popen.calls
    assert kwargs["start_new_session"] is True
    assert "preexec_fn" not in kwargs
    assert kwargs["cwd"] == "/media"


def test_launch_detached_posix_errors_are_raised() -> None:
    popen = _FakePopen(fail_first=PermissionError(13, "denied"))
    with pytest.raises(PermissionError):
        childproc.launch_detached(["x"], platform="linux", popen=popen)
    assert len(popen.calls) == 1


def test_launch_detached_real_process() -> None:
    import psutil

    code = "import time; time.sleep(30)"
    pid = childproc.launch_detached([sys.executable, "-c", code])
    try:
        assert psutil.Process(pid).is_running()
        if sys.platform != "win32":  # its own session
            assert os.getsid(pid) == pid != os.getsid(0)
    finally:
        psutil.Process(pid).kill()


# What PyInstaller's bootloader and an AppImage's AppRun (AppImageKit's, with linuxdeploy's GTK
# hook) leave in the frozen sidecar's environment; the values follow their format strings.
APPDIR = "/tmp/.mount_ReframXYZ"
SIDECAR = f"{APPDIR}/usr/lib/Reframe/sidecar/reframe-server"
APPIMAGE_ENV = {
    "APPDIR": APPDIR,
    "APPIMAGE": "/home/u/Reframe_0.1.0_amd64.AppImage",
    "LD_LIBRARY_PATH": f"{APPDIR}/usr/lib/Reframe/sidecar/_internal:{APPDIR}/usr/lib/:"
    f"{APPDIR}/usr/lib/x86_64-linux-gnu/:{APPDIR}/lib/:/opt/mine/lib",
    "LD_LIBRARY_PATH_ORIG": f"{APPDIR}/usr/lib/:{APPDIR}/usr/lib/x86_64-linux-gnu/:"
    f"{APPDIR}/lib/:/opt/mine/lib",
    "PATH": f"{APPDIR}/usr/bin/:{APPDIR}/usr/sbin/:/usr/local/bin:/usr/bin",
    "PYTHONHOME": f"{APPDIR}/usr/",
    "XDG_DATA_DIRS": f"{APPDIR}/usr/share:/usr/share:{APPDIR}/usr/share/:",
    "GTK_PATH": f"{APPDIR}//usr/lib/gtk-3.0",
    "GTK_THEME": "Adwaita:light",
    "HOME": "/home/u",
}


def test_a_frozen_app_gives_tools_the_library_path_it_was_started_with() -> None:
    """Without this, a system tool loads PyInstaller's libstdc++ (CXXABI errors)."""
    env = {
        "LD_LIBRARY_PATH": "/app/_internal:/opt/mine/lib",
        "LD_LIBRARY_PATH_ORIG": "/opt/mine/lib",
    }
    out = childproc.user_environ(env, frozen=True, executable="/app/reframe", platform="linux")
    assert out == {"LD_LIBRARY_PATH": "/opt/mine/lib"}
    unset = childproc.user_environ(
        {"LD_LIBRARY_PATH": "/app/_internal", "HOME": "/h"},
        frozen=True,
        executable="/app/reframe",
        platform="linux",
    )
    assert unset == {"HOME": "/h"}


def test_inside_an_appimage_the_image_is_dropped_from_every_search_path() -> None:
    out = childproc.user_environ(APPIMAGE_ENV, frozen=True, executable=SIDECAR, platform="linux")
    assert out == {
        "APPIMAGE": "/home/u/Reframe_0.1.0_amd64.AppImage",
        "LD_LIBRARY_PATH": "/opt/mine/lib",
        "PATH": "/usr/local/bin:/usr/bin",
        "XDG_DATA_DIRS": "/usr/share",
        "GTK_THEME": "Adwaita:light",
        "HOME": "/home/u",
    }


@pytest.mark.parametrize(
    ("frozen", "platform"),
    [
        (False, "linux"),  # from source: the user's own LD_LIBRARY_PATH stays
        (True, "win32"),
    ],
)
def test_the_environment_stays_when_not_a_frozen_linux_app(frozen: bool, platform: str) -> None:
    out = childproc.user_environ(APPIMAGE_ENV, frozen=frozen, executable=SIDECAR, platform=platform)
    assert out == APPIMAGE_ENV


def test_an_appdir_that_is_not_the_apps_own_is_kept() -> None:
    out = childproc.user_environ(
        APPIMAGE_ENV, frozen=True, executable="/opt/reframe/sidecar/reframe", platform="linux"
    )
    assert out["PATH"] == APPIMAGE_ENV["PATH"]
    assert out["LD_LIBRARY_PATH"] == APPIMAGE_ENV["LD_LIBRARY_PATH_ORIG"]


def test_launch_detached_gives_the_program_the_users_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/app/_internal")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
    popen = _FakePopen()
    childproc.launch_detached(["xdg-open", "/media/out.mkv"], platform="linux", popen=popen)
    ((_, kwargs),) = popen.calls
    assert "LD_LIBRARY_PATH" not in kwargs["env"]
    assert kwargs["env"]["PATH"] == os.environ["PATH"]
