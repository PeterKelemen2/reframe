"""The frozen sidecar of the desktop spike (``desktop/spike/scripts/build_sidecar.py``): it
starts, answers from the data files and the MediaInfo library it must bundle, and ends with its
encode when the process that started it ends. CI does not build it, so the tests are skipped
without it."""

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
from reframe_testing import media
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
    def __call__(self, parent_pid: int | None = None, *, real_tools: bool = False) -> Frozen: ...


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
    """``start(parent_pid=None, real_tools=False)``: the frozen server in desktop mode, in its
    own folders, with the fake tools (every probe answers with the ``multitrack`` fixture) or
    the real FFmpeg."""
    fake_tools.set_scenario(ft.Scenario([PROBE_RULE]))
    started: list[Frozen] = []

    def start(parent_pid: int | None = None, *, real_tools: bool = False) -> Frozen:
        env = {k: v for k, v in os.environ.items() if not k.startswith("REFRAME_")}
        for name in ("config", "data", "cache"):
            env[f"REFRAME_{name.upper()}_DIR"] = str(tmp_path / name)
        (tmp_path / "config").mkdir(exist_ok=True)
        (tmp_path / "config" / "settings.json").write_text(
            json.dumps({"encoders": {"hardware_tests": False}, "queue": {"sleep_inhibit": False}}),
            encoding="utf-8",
        )
        tools = (media.find_ffmpeg(), media.find_ffprobe()) if real_tools else (None, None)
        env |= {
            "REFRAME_FFMPEG": tools[0] or str(fake_tools.ffmpeg),
            "REFRAME_FFPROBE": tools[1] or str(fake_tools.ffprobe),
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


def probe(client: httpx.Client, path: Path) -> dict[str, Any]:
    accepted = client.post("/api/sources", json={"paths": [str(path)]}).json()

    def probed() -> Any:
        task = client.get(f"/api/tasks/{accepted['task_id']}").json()
        return task["result"] if task["state"] == "done" else None

    source: dict[str, Any] = wait_for(probed)["sources"][0]
    return source


@pytest.mark.needs_ffmpeg
def test_the_frozen_server_reads_bit_rates_with_its_bundled_mediainfo(
    start_frozen: StartFrozen, fixture_media: Callable[[str], Path], tmp_path: Path
) -> None:
    """Without MediaInfo in the build the probe still works, but a stream that ffprobe gives no
    bit rate for keeps an unknown one, and every rule that reads bit rates treats it as too high."""
    source = tmp_path / "media" / "vfr.mkv"
    source.parent.mkdir()
    source.write_bytes(fixture_media("vfr-mkv").read_bytes())
    client = start_frozen(real_tools=True).client
    source_id = probe(client, source)["id"]
    [video] = client.get(f"/api/sources/{source_id}").json()["video"]
    assert video["bitrate"]["source"] == "mediainfo"
    assert video["bitrate"]["value"] > 0


def older_stand_in() -> subprocess.Popen[bytes]:
    """The shell of the test. It is not the server's ancestor, so it must have started a clock
    tick (10 ms) before the server."""
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    time.sleep(0.03)
    return process


def ffmpeg_processes(pid: int) -> list[psutil.Process]:
    return [p for p in psutil.Process(pid).children(recursive=True) if "ffmpeg" in p.name()]


@pytest.mark.needs_ffmpeg
def test_the_frozen_server_and_its_encode_end_with_the_process_that_started_it(
    start_frozen: StartFrozen, fixture_media: Callable[[str], Path], tmp_path: Path
) -> None:
    source = tmp_path / "media" / "hdr10-4k.mkv"
    source.parent.mkdir()
    source.write_bytes(fixture_media("hdr10-4k").read_bytes())
    shell = older_stand_in()
    try:
        frozen = start_frozen(shell.pid, real_tools=True)
        client = frozen.client
        source_id = probe(client, source)["id"]
        job = client.post("/api/jobs/draft", json={"source_id": source_id}).json()["job"]
        job["output"]["path"] = str(tmp_path / "out" / "encoded.mkv")
        job["video"] |= {"encoder": "libx265", "preset": "slow"}
        [added] = client.post("/api/queue", json={"jobs": [job]}).json()
        assert client.post("/api/queue/start").status_code == 204

        def writing() -> Any:
            [queued] = client.get("/api/queue").json()["jobs"]
            assert queued["id"] == added["id"]
            assert queued["state"] in ("waiting", "running"), queued
            return queued if (queued.get("progress") or {}).get("output_size") else None

        part = Path(wait_for(writing, 60)["plan"]["output_tmp"])
        encoders = ffmpeg_processes(frozen.process.pid)
        assert encoders
        assert part.exists()
        shell.kill()
        killed = time.monotonic()
        code = frozen.process.wait(timeout=parent.STOP_LIMIT + 10)
        took = time.monotonic() - killed
    finally:
        shell.kill()
        shell.wait()
    assert code == 0
    assert took < parent.STOP_LIMIT
    _, alive = psutil.wait_procs(encoders, timeout=5)
    assert alive == []
    assert not part.exists()
