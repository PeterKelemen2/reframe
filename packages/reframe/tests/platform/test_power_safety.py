"""No test can shut down or suspend the machine that runs it (C-14 safety).

Two layers, both proved here:

1. the shared pytest plugin replaces the two functions of ``reframe.platform.power`` that
   reach the operating system with ones that fail the test (``power_guard``);
2. those two functions refuse by themselves while ``PYTEST_CURRENT_TEST`` (or
   ``REFRAME_POWER_DRY_RUN``) is set. That layer is tested with ``reframe.tools.run``
   mocked and a harmless argv, so even a broken refusal cannot run a power command.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, cast

import pytest

from reframe import tools
from reframe.events import EventBus
from reframe.models.events import AppWarningEvent, PowerCountdownEvent
from reframe.platform import power
from reframe.platform.power import (
    COMMAND_TIMEOUT,
    DRY_RUN_ENV,
    PowerService,
    SystemctlExecutor,
    WindowsExecutor,
    create_power_service,
    refusal,
)
from reframe.tools import RunResult
from reframe_testing.pytest_plugin import PowerGuard

pytestmark = pytest.mark.anyio

FAILED = pytest.fail.Exception
HARMLESS = ["reframe-test-not-a-power-command", "--harmless"]


class NoRun:
    """Stands in for ``reframe.tools.run``: records, never starts a process."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    async def __call__(self, argv: Sequence[str], **kwargs: Any) -> RunResult:
        self.calls.append((list(argv), kwargs))
        return RunResult(returncode=0, stdout=b"", stderr=b"", duration=0.0, argv=tuple(argv))


@pytest.fixture
def no_run(monkeypatch: pytest.MonkeyPatch) -> NoRun:
    fake = NoRun()
    monkeypatch.setattr(tools, "run", fake)
    return fake


# --------------------------------------------------------------------------- layer 1: the plugin


def test_the_plugin_replaced_both_functions(power_guard: PowerGuard) -> None:
    assert power._run_command == power_guard.run_command
    assert power._load_win32 == power_guard.load_win32
    assert power_guard.originals["_run_command"] is not power._run_command


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the Linux executor")
async def test_linux_service_executor_fails_the_test_instead_of_running(
    power_guard: PowerGuard, no_run: NoRun
) -> None:
    service = create_power_service(EventBus())
    assert isinstance(service.executor, SystemctlExecutor)
    with pytest.raises(FAILED, match="reached a real power action"):
        await service.executor.execute("shutdown")
    with pytest.raises(FAILED, match="reached a real power action"):
        await service.executor.execute("sleep")
    assert power_guard.take_calls() == [
        "power command ['systemctl', '--no-ask-password', 'poweroff']",
        "power command ['systemctl', '--no-ask-password', 'suspend']",
    ]
    assert no_run.calls == []


async def test_the_default_executor_of_a_bare_service_is_guarded_too(
    power_guard: PowerGuard, no_run: NoRun
) -> None:
    """``PowerService(events)`` (no executor) uses this OS's executor: guarded as well."""
    service = PowerService(EventBus())
    with pytest.raises(FAILED):
        await service.executor.execute("shutdown")
    assert len(power_guard.take_calls()) == 1
    assert no_run.calls == []


async def test_windows_path_fails_the_test_instead_of_running(
    power_guard: PowerGuard, no_run: NoRun
) -> None:
    service = create_power_service(EventBus(), platform="win32")
    executor = service.executor
    assert isinstance(executor, WindowsExecutor)
    with pytest.raises(FAILED):
        await executor.execute("shutdown")
    with pytest.raises(FAILED):
        await executor.execute("sleep")
    calls = power_guard.take_calls()
    assert len(calls) == 2
    assert calls[0].startswith("power command [")
    assert "shutdown.exe', '/s'" in calls[0]
    assert calls[1] == "the Windows power DLLs (SetSuspendState)"
    assert no_run.calls == []


async def test_a_whole_countdown_into_the_real_executor_is_stopped(
    power_guard: PowerGuard, no_run: NoRun
) -> None:
    """The service path: the countdown ends, ``executing`` is published, and the guard
    stops the executor; no ``app.warning`` hides it."""
    events = EventBus()
    subscription = events.subscribe()
    release = asyncio.Event()

    async def sleep(_: float) -> None:
        await release.wait()

    service = create_power_service(events)
    service._sleep = sleep
    service._countdown = 1.0
    service.schedule("shutdown")
    release.set()
    executing = events.subscribe(types={"power.countdown"})
    async with asyncio.timeout(5):
        async for received in executing:
            if isinstance(received, PowerCountdownEvent) and received.phase == "executing":
                break
    (action,) = service._actions  # registered in the same step as `executing`
    with pytest.raises(FAILED):
        await action
    assert len(power_guard.take_calls()) == 1
    seen = []
    while (event := subscription.get_nowait()) is not None:
        seen.append(event)
    assert [e.phase for e in seen if isinstance(e, PowerCountdownEvent)] == [
        "started",
        "executing",
    ]
    assert not [e for e in seen if isinstance(e, AppWarningEvent)]
    assert no_run.calls == []
    await service.close()


# --------------------------------------------------------------------------- layer 2: refusal


def original_run_command(guard: PowerGuard) -> Callable[[Sequence[str]], Awaitable[RunResult]]:
    return cast("Callable[[Sequence[str]], Awaitable[RunResult]]", guard.originals["_run_command"])


def original_load_win32(guard: PowerGuard) -> Callable[[], power.Win32Libraries]:
    return cast("Callable[[], power.Win32Libraries]", guard.originals["_load_win32"])


def test_refusal_reasons(monkeypatch: pytest.MonkeyPatch) -> None:
    assert refusal() == "refused: a test is running (PYTEST_CURRENT_TEST is set)"
    monkeypatch.delenv("PYTEST_CURRENT_TEST")
    monkeypatch.delenv(DRY_RUN_ENV, raising=False)
    assert refusal() is None
    for off in ("", "0", "false", "No"):
        monkeypatch.setenv(DRY_RUN_ENV, off)
        assert refusal() is None
    monkeypatch.setenv(DRY_RUN_ENV, "1")
    assert refusal() == f"refused: {DRY_RUN_ENV} is set (dry run)"


async def test_real_run_command_refuses_under_pytest(
    power_guard: PowerGuard, no_run: NoRun
) -> None:
    run_command = original_run_command(power_guard)
    outcome = await run_command(HARMLESS)
    assert outcome.error == "refused: a test is running (PYTEST_CURRENT_TEST is set)"
    assert not outcome.started
    assert outcome.argv == tuple(HARMLESS)
    assert no_run.calls == []


async def test_real_run_command_refuses_a_dry_run(
    power_guard: PowerGuard, no_run: NoRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PYTEST_CURRENT_TEST")
    monkeypatch.setenv(DRY_RUN_ENV, "yes")
    run_command = original_run_command(power_guard)
    outcome = await run_command(HARMLESS)
    assert outcome.error == f"refused: {DRY_RUN_ENV} is set (dry run)"
    assert no_run.calls == []


async def test_real_run_command_goes_through_reframe_tools_run(
    power_guard: PowerGuard, no_run: NoRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a refusal it calls ``reframe.tools.run`` (mocked here; the argv is harmless
    anyway) with the command time-out."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST")
    monkeypatch.delenv(DRY_RUN_ENV, raising=False)
    run_command = original_run_command(power_guard)
    outcome = await run_command(HARMLESS)
    assert outcome.ok
    assert no_run.calls == [(HARMLESS, {"timeout": COMMAND_TIMEOUT})]


async def test_a_refused_command_is_a_failure_string_of_the_executor(
    power_guard: PowerGuard, no_run: NoRun
) -> None:
    executor = SystemctlExecutor(run=original_run_command(power_guard))
    detail = await executor.execute("shutdown")
    assert detail == (
        "systemctl poweroff could not be started: "
        "refused: a test is running (PYTEST_CURRENT_TEST is set)"
    )
    assert no_run.calls == []


async def test_real_load_win32_refuses_under_pytest(power_guard: PowerGuard) -> None:
    load = original_load_win32(power_guard)
    with pytest.raises(OSError, match="PYTEST_CURRENT_TEST"):
        load()
    detail = await WindowsExecutor(libraries=load).execute("sleep")
    assert detail == (
        "powrprof not available: refused: a test is running (PYTEST_CURRENT_TEST is set)"
    )


@pytest.mark.skipif(sys.platform == "win32", reason="loads the real DLLs on Windows")
def test_real_load_win32_without_windows(
    power_guard: PowerGuard, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PYTEST_CURRENT_TEST")
    monkeypatch.delenv(DRY_RUN_ENV, raising=False)
    with pytest.raises(OSError, match="only on Windows"):
        original_load_win32(power_guard)()
