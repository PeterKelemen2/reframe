"""The frozen sidecar of the desktop spike (``desktop/spike/scripts/build_sidecar.py``): it
starts, answers from the data files it must bundle, and ends with the process that started it.
CI does not build it, so the tests are skipped without it."""

from __future__ import annotations

import json
import os
import queue
import runpy
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx
import psutil
import pytest

import reframe_server
from reframe_server import parent
from reframe_testing import fake_tools as ft
from reframe_testing.server import PROBE_RULE

REPO = Path(__file__).resolve().parents[3]
FROZEN = Path(
    os.environ.get("REFRAME_FROZEN_SERVER")
    or runpy.run_path(str(REPO / "desktop" / "spike" / "scripts" / "spike_paths.py"))[
        "FROZEN_SERVER"
    ]
)
TOKEN = "frozen-test-" + "x" * 32
RELEASE_NAME = "Show.Name.S01E02.1080p.BluRay.x264-GRP.mkv"

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not FROZEN.is_file(),
        reason=f"no frozen sidecar at {FROZEN} (CI does not build it; "
        "`uv run python -m desktop.spike.scripts.build_sidecar` does)",
    ),
]


@dataclass
class Frozen:
    process: subprocess.Popen[bytes]
    client: httpx.Client


class StartFrozen(Protocol):
    def __call__(self, parent_pid: int | None = None) -> Frozen: ...


def ready_port(process: subprocess.Popen[bytes], limit: float = 30.0) -> int:
    lines: queue.Queue[bytes] = queue.Queue()
    stdout = process.stdout
    assert stdout is not None
    threading.Thread(target=lambda: lines.put(stdout.readline()), daemon=True).start()
    ready = json.loads(lines.get(timeout=limit))
    assert ready["event"] == "ready"
    port: int = ready["port"]
    return port


@pytest.fixture
def start_frozen(tmp_path: Path, fake_tools: ft.FakeTools) -> Iterator[StartFrozen]:
    """``start(parent_pid=None)``: the frozen server in desktop mode, in its own folders, with
    the fake tools (every probe answers with the ``multitrack`` fixture)."""
    fake_tools.set_scenario(ft.Scenario([PROBE_RULE]))
    started: list[Frozen] = []

    def start(parent_pid: int | None = None) -> Frozen:
        env = {k: v for k, v in os.environ.items() if not k.startswith("REFRAME_")}
        for name in ("config", "data", "cache"):
            env[f"REFRAME_{name.upper()}_DIR"] = str(tmp_path / name)
        env |= {
            "REFRAME_FFMPEG": str(fake_tools.ffmpeg),
            "REFRAME_FFPROBE": str(fake_tools.ffprobe),
            "REFRAME_TOKEN": TOKEN,
        }
        argv = [str(FROZEN), "--mode", "desktop", "--port", "0"]
        if parent_pid is not None:
            argv += ["--parent-pid", str(parent_pid)]
        process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
        client = httpx.Client(
            base_url=f"http://127.0.0.1:{ready_port(process)}",
            headers={"Authorization": f"Bearer {TOKEN}"},
            timeout=30,
        )
        frozen = Frozen(process, client)
        started.append(frozen)
        return frozen

    yield start
    for frozen in started:
        frozen.client.close()
        if frozen.process.poll() is None:
            frozen.process.kill()
            frozen.process.wait()
        assert frozen.process.stdout is not None
        frozen.process.stdout.close()


def test_the_frozen_server_answers_from_its_bundled_data(
    start_frozen: StartFrozen, tmp_path: Path
) -> None:
    """A build without a data file starts and answers health, and only fails later."""
    client = start_frozen().client
    assert client.get("/api/health").json()["version"] == reframe_server.__version__
    definitions = client.get("/api/definitions").json()["definitions"]
    assert "libx265" in definitions["video_encoders"]
    assert client.get("/api/presets").json()["presets"]
    assert client.get("/api/languages").json()["languages"]
    fetch = client.post("/api/system/tools/fetch", json={"build": "no-such-build"}).json()

    def fetched() -> Any:
        task = client.get(f"/api/tasks/{fetch['task_id']}").json()
        return task if task["state"] not in ("queued", "running") else None

    assert "has no build 'no-such-build'" in wait_for(fetched)["error"]
    source = tmp_path / "media" / RELEASE_NAME
    source.parent.mkdir()
    source.write_bytes(b"not really matroska")
    probe = client.post("/api/sources", json={"paths": [str(source)]}).json()

    def probed() -> Any:
        task = client.get(f"/api/tasks/{probe['task_id']}").json()
        return task if task["state"] == "done" else None

    source_id = wait_for(probed)["result"]["sources"][0]["id"]
    [name] = client.post("/api/naming/preview", json={"source_ids": [source_id]}).json()
    fields = name["candidates"][0]["fields"]
    assert (fields["season"], fields["episode"], fields["release_group"]) == (1, 2, "GRP")


def wait_for(check: Callable[[], Any], limit: float = 30.0) -> Any:
    deadline = time.monotonic() + limit
    while (result := check()) is None:
        assert time.monotonic() < deadline, "not in time"
        time.sleep(0.05)
    return result


def test_the_frozen_server_ends_with_the_process_that_started_it(
    start_frozen: StartFrozen,
) -> None:
    shell = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    try:
        frozen = start_frozen(shell.pid)
        tree = [psutil.Process(frozen.process.pid)]
        tree += tree[0].children(recursive=True)
        shell.kill()
        killed = time.monotonic()
        code = frozen.process.wait(timeout=parent.STOP_LIMIT + 10)
        took = time.monotonic() - killed
    finally:
        shell.kill()
        shell.wait()
    assert code == 0
    assert took < parent.STOP_LIMIT
    _, alive = psutil.wait_procs(tree, timeout=5)
    assert alive == []
