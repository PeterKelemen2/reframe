"""Start a sidecar (the frozen onedir, or ``uv run reframe-server``) in its own temporary
folders, and drive it through its HTTP API: health, the routes that read bundled data, and an
encode (probe, draft, queue, start)."""

from __future__ import annotations

import json
import os
import secrets
import selectors
import shutil
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from desktop.spike.scripts.spike_paths import FROZEN_SERVER, REPO
from websockets.exceptions import WebSocketException
from websockets.sync.client import connect
from websockets.typing import Origin

READY_TIMEOUT = 20.0
RELEASE_NAME = "Show.Name.S01E02.1080p.BluRay.x264-GRP.mkv"
"""The smoke's source: a copy of ``multitrack.mkv`` with a name that guessit must parse."""
NAMING_FIELDS = ("main_title", "season", "episode", "resolution", "source_type", "release_group")
MEDIA = REPO / "testdata" / "media"
"""The generated fixtures (``scripts/make-testdata.py``)."""


def frozen_command() -> list[str]:
    return [str(FROZEN_SERVER)]


def unfrozen_command() -> list[str]:
    return ["uv", "run", "--project", str(REPO), "reframe-server"]


SETTINGS = {"encoders": {"hardware_tests": False}}
"""Every spike sidecar's settings: no VAAPI test encode and no libplacebo (Vulkan) run test on
the GPU that the owner's movie shares; no check of the spike needs them."""


def write_settings(config: Path) -> None:
    """Writes :data:`SETTINGS` to a new config folder (an existing ``settings.json`` stays)."""
    config.mkdir(parents=True, exist_ok=True)
    settings = config / "settings.json"
    if not settings.exists():
        settings.write_text(json.dumps(SETTINGS), encoding="utf-8")


def isolated_env(home: Path, token: str, extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment of a sidecar whose settings, queue and cache are in ``home``."""
    env = {name: value for name, value in os.environ.items() if not name.startswith("REFRAME_")}
    for name in ("config", "data", "cache"):
        folder = home / name
        folder.mkdir(parents=True, exist_ok=True)
        env[f"REFRAME_{name.upper()}_DIR"] = str(folder)
    write_settings(home / "config")
    env["REFRAME_TOKEN"] = token
    return env | dict(extra or {})


@dataclass
class Api:
    """The API of a running server, with its token."""

    port: int
    token: str
    home: Path
    client: httpx.Client = field(init=False)

    def __post_init__(self) -> None:
        self.client = httpx.Client(
            base_url=f"http://127.0.0.1:{self.port}",
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=60,
        )

    def get(self, path: str) -> Any:
        response = self.client.get(path)
        response.raise_for_status()
        return response.json()

    def post(self, path: str, body: Any = None) -> Any:
        response = self.client.post(path, json=body)
        response.raise_for_status()
        return response.json() if response.content else None

    def task_result(self, accepted: Any, limit: float = 120.0) -> Any:
        deadline = time.monotonic() + limit
        while True:
            info = self.get(f"/api/tasks/{accepted['task_id']}")
            if info["state"] not in ("queued", "running"):
                if info["state"] != "done":
                    raise RuntimeError(f"task {info['kind']} ended {info['state']}: {info}")
                return info["result"]
            if time.monotonic() > deadline:
                raise TimeoutError(f"task {info['kind']} still {info['state']}")
            time.sleep(0.05)

    def probe(self, path: Path) -> str:
        summary = self.task_result(self.post("/api/sources", {"paths": [str(path)]}))
        if summary["errors"]:
            raise RuntimeError(f"probe failed: {summary['errors']}")
        source_id: str = summary["sources"][0]["id"]
        return source_id

    def encode(self, source: Path, output: Path, *, preset: str = "slow") -> str:
        """Queue and start an x265 encode of ``source``; returns the job id."""
        draft = self.post("/api/jobs/draft", {"source_id": self.probe(source)})
        job = draft["job"]
        job["output"]["path"] = str(output)
        job["video"]["encoder"] = "libx265"
        job["video"]["preset"] = preset
        [added] = self.post("/api/queue", {"jobs": [job]})
        self.post("/api/queue/start")
        job_id: str = added["id"]
        return job_id

    def job(self, job_id: str) -> Any:
        return next(job for job in self.get("/api/queue")["jobs"] if job["id"] == job_id)

    def wait_encoding(self, job_id: str, limit: float = 60.0) -> Any:
        """Until the job runs and its encode has written output."""
        deadline = time.monotonic() + limit
        while True:
            job = self.job(job_id)
            progress = job.get("progress") or {}
            if job["state"] == "running" and progress.get("output_size"):
                return job
            if job["state"] not in ("waiting", "running") or time.monotonic() > deadline:
                raise RuntimeError(f"the job does not encode: {job['state']} {job.get('error')}")
            time.sleep(0.1)

    def hello(self) -> Any:
        """The event WebSocket's first message after the token."""
        origin = f"http://127.0.0.1:{self.port}"
        with connect(f"ws://127.0.0.1:{self.port}/api/events", origin=Origin(origin)) as ws:
            ws.send(json.dumps({"type": "auth", "token": self.token}))
            return json.loads(ws.recv(timeout=10))

    def close(self) -> None:
        self.client.close()


@dataclass
class Sidecar(Api):
    process: subprocess.Popen[bytes] = field(kw_only=True)
    ready_after: float = field(kw_only=True)
    """Seconds from the spawn to the ready line."""

    @property
    def log(self) -> Path:
        return self.home / "sidecar.log"


def read_ready_line(process: subprocess.Popen[bytes], limit: float = READY_TIMEOUT) -> int:
    """The port of the ready line; raises when the process ends or ``limit`` passes first."""
    assert process.stdout is not None
    deadline = time.monotonic() + limit
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError(f"no ready line within {limit} s")
            if selector.select(left):
                line = process.stdout.readline()
                if not line:
                    raise RuntimeError(f"the sidecar ended first (exit {process.wait()})")
                ready = json.loads(line)
                if ready.get("event") == "ready":
                    port: int = ready["port"]
                    return port


def start(
    command: Sequence[str],
    home: Path,
    *,
    parent_pid: int | None = None,
    extra_env: Mapping[str, str] | None = None,
) -> Sidecar:
    """Spawn a desktop-mode sidecar and wait for its ready line; stderr goes to its log."""
    token = secrets.token_urlsafe(32)
    argv = [*command, "--mode", "desktop", "--port", "0", "--auth", "token"]
    if parent_pid is not None:
        argv += ["--parent-pid", str(parent_pid)]
    home.mkdir(parents=True, exist_ok=True)
    with (home / "sidecar.log").open("ab") as log:
        started = time.monotonic()
        process = subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=log, env=isolated_env(home, token, extra_env)
        )
    try:
        port = read_ready_line(process)
    except BaseException:
        process.kill()
        process.wait()
        raise
    return Sidecar(port, token, home, process=process, ready_after=time.monotonic() - started)


def smoke(sidecar: Sidecar) -> dict[str, Any]:
    """Call the routes that read bundled data or start a tool. Each check gives a short answer,
    or its error, so one run shows every failure."""
    media = sidecar.home / "media"
    media.mkdir(exist_ok=True)
    source = media / RELEASE_NAME
    shutil.copyfile(MEDIA / "multitrack.mkv", source)
    state: dict[str, Any] = {}

    def manifest() -> Any:
        # An unknown build fails after the manifest is read, before any download.
        accepted = sidecar.post("/api/system/tools/fetch", {"build": "no-such-build"})
        try:
            return sidecar.task_result(accepted)
        except RuntimeError:
            return sidecar.get(f"/api/tasks/{accepted['task_id']}")["error"]

    def naming() -> Any:
        [name] = sidecar.post("/api/naming/preview", {"source_ids": [state["source_id"]]})
        fields = name["candidates"][0]["fields"]
        return {key: fields[key] for key in NAMING_FIELDS}

    def draft() -> Any:
        state["source_id"] = sidecar.probe(source)
        state["draft"] = sidecar.post("/api/jobs/draft", {"source_id": state["source_id"]})
        return [issue["code"] for issue in state["draft"]["issues"]]

    checks: dict[str, Any] = {
        "health": lambda: sidecar.get("/api/health"),
        "tools": lambda: {
            name: {key: tool[key] for key in ("status", "path", "origin", "version")}
            for name, tool in sidecar.get("/api/system")["tools"].items()
        },
        "video encoders": lambda: len(
            sidecar.get("/api/definitions")["definitions"]["video_encoders"]
        ),
        "x265 options for 'psy'": lambda: len(
            sidecar.get("/api/definitions/encoders/libx265/options?q=psy")
        ),
        "languages": lambda: len(sidecar.get("/api/languages")["languages"]),
        "presets": lambda: len(sidecar.get("/api/presets")["presets"]),
        "probe and draft (issues)": draft,
        "plan steps": lambda: len(
            sidecar.post("/api/jobs/plan", {"job": state["draft"]["job"]})["steps"]
        ),
        "naming": naming,
        "event socket": sidecar.hello,
        "tools manifest": manifest,
    }
    answers: dict[str, Any] = {}
    for name, check in checks.items():
        try:
            answers[name] = check()
        except (httpx.HTTPError, RuntimeError, KeyError, OSError, WebSocketException) as exc:
            detail = exc.response.text if isinstance(exc, httpx.HTTPStatusError) else ""
            answers[name] = f"ERROR {exc!r} {detail}".strip()
    return answers
