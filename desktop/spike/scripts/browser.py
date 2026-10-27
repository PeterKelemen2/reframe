"""The spike pages in a browser: the built UI (``ui/dist``) on a loopback port with the app's
Content-Security-Policy, and a frozen sidecar of its own that allows that origin (CORS). A
page opens at :func:`page_url` (``?page=<name>&base=<url>&token=<token>``)."""

from __future__ import annotations

import contextlib
import functools
import json
import os
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from desktop.spike.scripts import sidecar
from desktop.spike.scripts.spike_paths import SPIKE, TAURI

UI_DIST = SPIKE / "ui" / "dist"


def app_csp() -> str:
    """The policy of ``tauri.conf.json``; Tauri adds hashes and nonces of its own on top."""
    config = json.loads((TAURI / "tauri.conf.json").read_text(encoding="utf-8"))
    policy: str = config["app"]["security"]["csp"]
    return policy


class _Handler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Content-Security-Policy", app_csp())
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        pass


@contextlib.contextmanager
def serve_ui() -> Iterator[str]:
    """Serves ``ui/dist`` on a free loopback port; yields its origin."""
    if not (UI_DIST / "index.html").exists():
        raise FileNotFoundError(f"{UI_DIST} is not built: npm --prefix desktop/spike run build:ui")
    handler = functools.partial(_Handler, directory=str(UI_DIST))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


@contextlib.contextmanager
def backend(origin: str) -> Iterator[sidecar.Sidecar]:
    """A frozen sidecar in temporary folders that answers pages from ``origin``."""
    with tempfile.TemporaryDirectory(prefix="reframe-spike-browser-") as tmp:
        extra = {"REFRAME_CORS_ORIGINS": json.dumps([origin])}
        car = sidecar.start(sidecar.frozen_command(), Path(tmp), extra_env=extra)
        try:
            yield car
        finally:
            with contextlib.suppress(Exception):
                car.client.post("/api/system/shutdown")
                car.process.wait(15)
            if car.process.poll() is None:
                car.process.kill()
                car.process.wait()
            car.close()


def page_url(origin: str, page: str, car: sidecar.Sidecar, **query: str) -> str:
    params = {"page": page, "base": f"http://127.0.0.1:{car.port}", "token": car.token, **query}
    return f"{origin}/index.html?{urlencode(params)}"


def node(
    script: Path,
    arguments: Sequence[str],
    timeout: float = 300,
    stop: Callable[[], str | None] = lambda: None,
) -> list[dict[str, Any]]:
    """Runs a Node script of the spike (Playwright) and returns the JSON lines it prints.
    ``stop`` is asked every 0.1 s; a reason from it ends the script (its browsers close with
    it: Playwright drives them through a pipe)."""
    with tempfile.TemporaryFile("w+") as out, tempfile.TemporaryFile("w+") as err:
        process = subprocess.Popen(
            ["node", str(script), *arguments],
            cwd=SPIKE,
            stdout=out,
            stderr=err,
            text=True,
            env=browser_env(),
        )
        deadline = time.monotonic() + timeout
        reason = None
        while process.poll() is None:
            reason = stop() or ("timeout" if time.monotonic() > deadline else None)
            if reason:
                process.terminate()
                process.wait(15)
                break
            time.sleep(0.1)
        out.seek(0)
        err.seek(0)
        stdout, stderr = out.read(), err.read()
    if reason or process.returncode != 0:
        raise RuntimeError(
            f"{script.name} stopped ({reason or process.returncode}): {stderr[-3000:]}"
        )
    return [json.loads(line) for line in stdout.splitlines() if line.startswith("{")]


def browser_env() -> dict[str, str]:
    """Our environment without what an Electron host (VS Code) leaves in it: Chromium takes its
    Wayland app id from ``CHROME_DESKTOP``."""
    return {
        name: value
        for name, value in os.environ.items()
        if name != "CHROME_DESKTOP" and not name.startswith("ELECTRON_")
    }


def executables() -> dict[str, str]:
    """Playwright's own Chromium and Firefox binaries."""
    code = (
        'import("playwright").then((p) => console.log(JSON.stringify('
        "{chromium: p.chromium.executablePath(), firefox: p.firefox.executablePath()})))"
    )
    answer = subprocess.run(
        ["node", "-e", code], cwd=SPIKE, capture_output=True, text=True, timeout=60, check=True
    )
    paths: dict[str, str] = json.loads(answer.stdout)
    return paths
