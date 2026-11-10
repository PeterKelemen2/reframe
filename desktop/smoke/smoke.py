"""Smoke test of a built desktop app through tauri-driver (WebDriver).

The app starts with a fixture in its arguments, in a new temporary home. The test waits for the
backend (``server.json`` and ``GET /api/health``), adds the opened file to the queue with the
default preset, starts the queue, waits for the job to finish, closes the window, and checks
that no process of the app is left. Standard library only::

    python desktop/smoke/smoke.py --app /usr/bin/reframe-desktop \
        --fixture testdata/media/chapters.mkv

``tauri-driver`` must be on ``PATH`` (or ``--driver``), with WebKitWebDriver (Linux) or
msedgedriver (Windows) next to it as tauri-driver expects. Exit code 0 when every step passed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

#: The WebDriver element key (W3C).
ELEMENT = "element-6066-11e4-a52f-4a5c6eb5e5c4"
#: The driver programs; they are not the app's processes.
DRIVERS = frozenset({"tauri-driver", "WebKitWebDriver"})


class SmokeError(Exception):
    """A step failed; the message says which and why."""


def _log(message: str) -> None:
    print(f"smoke: {message}", file=sys.stderr, flush=True)


def _http(
    method: str, url: str, body: object = None, headers: Mapping[str, str] | None = None
) -> Any:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, method=method, headers=dict(headers or {}))
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            text = response.read().decode() or "null"
    except urllib.error.HTTPError as e:
        raise SmokeError(f"{method} {url}: HTTP {e.code}: {e.read().decode()[:500]}") from e
    return json.loads(text)


def wait_for[T](what: str, check: Callable[[], T | None], timeout: float) -> T:
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except (OSError, SmokeError, ValueError) as e:
            last = e
        time.sleep(0.5)
    raise SmokeError(
        f"timed out after {timeout:.0f} s waiting for {what}" + (f" ({last})" if last else "")
    )


class Session:
    """A WebDriver session with the app."""

    def __init__(self, driver_url: str, app: Path, args: list[str]) -> None:
        self.base = driver_url
        capabilities = {
            "capabilities": {
                "alwaysMatch": {
                    "browserName": "wry",
                    "tauri:options": {"application": str(app), "args": args},
                }
            }
        }
        self.id = _http("POST", f"{self.base}/session", capabilities)["value"]["sessionId"]

    def call(self, method: str, path: str, body: object = None) -> Any:
        return _http(method, f"{self.base}/session/{self.id}{path}", body)["value"]

    def script(self, source: str) -> Any:
        return self.call("POST", "/execute/sync", {"script": source, "args": []})

    def element(self, css: str) -> str | None:
        found = self.call("POST", "/elements", {"using": "css selector", "value": css})
        if not found:
            return None
        # WebKitWebDriver may answer with the legacy key ("ELEMENT").
        reference = found[0]
        return str(reference.get(ELEMENT) or next(iter(reference.values())))

    def enabled(self, css: str) -> str | None:
        element = self.element(css)
        if element is not None and self.call("GET", f"/element/{element}/enabled"):
            return element
        return None

    def click(self, css: str, timeout: float) -> None:
        element = wait_for(f"{css} to be enabled", lambda: self.enabled(css), timeout)
        self.call("POST", f"/element/{element}/click", {})

    def close(self) -> None:
        try:
            self.call("DELETE", "/window")
        finally:
            _http("DELETE", f"{self.base}/session/{self.id}")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


if sys.platform == "win32":

    def _app_processes(home: Path, app_dir: Path) -> list[str]:
        """The processes of this run: their program file is in the app's folder."""
        command = (
            "Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -like "
            f"'{app_dir}\\*' }} | ForEach-Object {{ \"$($_.ProcessId) $($_.ExecutablePath)\" }}"
        )
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True, text=True, timeout=60, check=False,
        ).stdout  # fmt: skip
        return [line for line in out.splitlines() if line.strip()]

else:

    def _app_processes(home: Path, app_dir: Path) -> list[str]:
        """The processes of this run: the data folder is in their environment. The drivers have
        it too (they start the app), but they are not the app's."""
        marker = f"REFRAME_DATA_DIR={home / 'data'}".encode()
        found = []
        for proc in Path("/proc").iterdir():
            if not proc.name.isdigit():
                continue
            try:
                exe = os.readlink(proc / "exe")
                if Path(exe).name in DRIVERS:
                    continue
                if marker in (proc / "environ").read_bytes().split(b"\0"):
                    found.append(f"{proc.name} {exe}")
            except OSError:
                continue
        return found


def run(app: Path, fixture: Path, driver: list[str], timeout: float) -> None:
    home = Path(tempfile.mkdtemp(prefix="reframe-smoke-"))
    source = home / "media" / fixture.name
    source.parent.mkdir()
    shutil.copyfile(fixture, source)
    env = {
        **os.environ,
        "REFRAME_CONFIG_DIR": str(home / "config"),
        "REFRAME_DATA_DIR": str(home / "data"),
        "REFRAME_CACHE_DIR": str(home / "cache"),
        "REFRAME_NO_UPDATE_CHECK": "1",
    }
    port = _free_port()
    driver_process = subprocess.Popen([*driver, "--port", str(port)], env=env)
    session: Session | None = None
    try:
        driver_url = f"http://127.0.0.1:{port}"
        wait_for("tauri-driver", lambda: _http("GET", f"{driver_url}/status"), 30)
        # msedgedriver passes the arguments as browser switches ("--c:\…", lowercased), so on
        # Windows a second launch hands the file to the running app (single instance).
        second_launch = sys.platform == "win32"
        session = started = Session(driver_url, app, [] if second_launch else [str(source)])
        _log("the app started")

        endpoint_file = home / "data" / "server.json"
        endpoint = wait_for(
            "the backend's server.json",
            lambda: json.loads(endpoint_file.read_text(encoding="utf-8")),
            timeout,
        )
        api = f"http://127.0.0.1:{endpoint['port']}/api"
        auth = {"Authorization": f"Bearer {endpoint['token']}"}
        wait_for("GET /api/health", lambda: _http("GET", f"{api}/health", headers=auth), timeout)
        _log("the backend is ready")

        def opened() -> bool:
            return fixture.name in str(started.script("return document.body.innerText"))

        how = "a second launch" if second_launch else "the arguments"
        if second_launch:
            subprocess.run([str(app), str(source)], env=env, timeout=60, check=False)
        wait_for(f"{fixture.name} to open from {how}", opened, timeout)
        _log(f"{fixture.name} opened from {how}")
        started.click(".status-bar__add", timeout)
        jobs = wait_for(
            "the job in the queue", lambda: _http("GET", f"{api}/queue", headers=auth)["jobs"], 30
        )
        started.click(".status-bar__start", 30)
        _log(f"job {jobs[0]['id']} queued and started")

        def finished() -> str | None:
            state = _http("GET", f"{api}/queue", headers=auth)["jobs"][0]["state"]
            if state in ("failed", "cancelled", "interrupted"):
                raise SmokeError(f"the job ended as {state}")
            return state if state == "done" else None

        wait_for("the job to finish", finished, timeout)
        outputs = [p for p in source.parent.iterdir() if p != source]
        if not outputs:
            raise SmokeError("the job is done but wrote no file next to the source")
        _log(f"the job is done: {outputs[0].name}")

        session = None
        started.close()
        try:
            wait_for("the app's processes to end", lambda: not _app_processes(home, app.parent), 30)
        except SmokeError as e:
            raise SmokeError(f"{e}; left: {'; '.join(_app_processes(home, app.parent))}") from e
        _log("the app quit and left no process")
    finally:
        if session is not None:
            try:
                session.close()
            except (OSError, SmokeError) as e:
                _log(f"closing the session failed: {e}")
        driver_process.terminate()
        try:
            driver_process.wait(10)
        except subprocess.TimeoutExpired:
            driver_process.kill()
        shutil.rmtree(home, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--app", type=Path, required=True, help="the app's main program")
    parser.add_argument("--fixture", type=Path, required=True, help="a media file to encode")
    parser.add_argument("--driver", default="tauri-driver")
    parser.add_argument("--native-driver", help="msedgedriver or WebKitWebDriver, if not on PATH")
    parser.add_argument("--timeout", type=float, default=180.0, help="seconds for each step")
    args = parser.parse_args(argv)
    try:
        driver = [args.driver]
        if args.native_driver:
            driver += ["--native-driver", args.native_driver]
        run(args.app.resolve(), args.fixture.resolve(), driver, args.timeout)
    except SmokeError as e:
        _log(f"FAILED: {e}")
        return 1
    _log("passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
