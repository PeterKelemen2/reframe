from __future__ import annotations

import os
import sys
import threading
from collections.abc import Callable
from pathlib import Path

import pytest

from reframe import cli
from reframe.tools import ENV_VARS
from reframe_testing import fake_tools as ft

MULTITRACK = (
    Path(__file__).resolve().parents[3] / "testdata" / "probes" / "fixtures" / "multitrack.mkv.json"
)

type FifoRead = Callable[[str, Callable[[Path], object]], object]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def fifo_read(tmp_path: Path) -> FifoRead:
    """``fifo_read(name, reader)``: ``reader`` of a new FIFO with no writer, in a thread; the
    test fails when ``reader`` waits for a writer."""
    if sys.platform == "win32":
        pytest.skip("needs FIFOs")
    else:

        def read(name: str, reader: Callable[[Path], object]) -> object:
            fifo = tmp_path / name
            os.mkfifo(fifo)
            results: list[object] = []
            thread = threading.Thread(target=lambda: results.append(reader(fifo)), daemon=True)
            thread.start()
            thread.join(5)
            if thread.is_alive():
                os.close(os.open(fifo, os.O_WRONLY | os.O_NONBLOCK))  # free the reader
                thread.join(5)
                pytest.fail(f"reading the FIFO {name} waited for a writer")
            return results[0]

        return read


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """No tool overrides, user folders in ``tmp_path``."""
    for var in ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    for name in ("config", "data", "cache"):
        monkeypatch.setenv(f"REFRAME_{name.upper()}_DIR", str(tmp_path / name))
    return tmp_path


@pytest.fixture
def fake(env: Path, fake_tools: ft.FakeTools, monkeypatch: pytest.MonkeyPatch) -> ft.FakeTools:
    """``REFRAME_FFMPEG`` / ``REFRAME_FFPROBE`` point at the fake tools (multitrack probe)."""
    monkeypatch.setenv("REFRAME_FFMPEG", str(fake_tools.ffmpeg))
    monkeypatch.setenv("REFRAME_FFPROBE", str(fake_tools.ffprobe))
    rule = ft.Rule(
        tool="ffprobe", argv_has=["-show_streams"], actions=[{"stdout_file": str(MULTITRACK)}]
    )
    fake_tools.set_scenario(ft.Scenario([rule]))
    return fake_tools


@pytest.fixture
def cli_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fake_tools: ft.FakeTools
) -> ft.FakeTools:
    """Fake ffmpeg and ffprobe, and private config, data and cache folders (never the user's).
    ``encode`` and ``batch`` run their jobs in-process (``tests/remote`` covers the server)."""
    monkeypatch.setenv(cli.IN_PROCESS_ENV, "1")
    for var in ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    for name in ("config", "data", "cache"):
        monkeypatch.setenv(f"REFRAME_{name.upper()}_DIR", str(tmp_path / name))
    monkeypatch.setenv("REFRAME_FFMPEG", str(fake_tools.ffmpeg))
    monkeypatch.setenv("REFRAME_FFPROBE", str(fake_tools.ffprobe))
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    return fake_tools
