"""Plays clips in an AppImage's window through WebKitWebDriver: whether the shell says its webview
can play video (``webview_plays_video``), then for each clip whether a ``<video>`` plays it
(``currentTime`` advances, with a picture or without one: no decoder for its video), reports a
media error, or neither; and that the web process is still there after each one. Prints one JSON
line per clip, the VA-API libraries that the web processes loaded, and a summary.

A clip's codec is its file name up to the first ``-`` or ``.``. Exits 1 when the shell's answer
is not ``--expect-player``, a clip ends in neither state, the web process is gone, a clip of a
``--must-play`` codec does not play with a picture, or any other clip does not end where the
preview shows its frame compare (a media error, or its data loaded without a picture width).

    python3 appimage-video.py APPIMAGE CLIP_DIR [--expect-player yes|no] [--must-play vp9,av1]
        [--driver WebKitWebDriver]

The AppImage runs with ``TAURI_WEBVIEW_AUTOMATION=true`` (and the caller's environment); a
display must be set.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

PLAY = """
const [url, done] = [arguments[0], arguments[arguments.length - 1]];
const video = document.createElement('video');
video.muted = true;
video.src = url;
document.body.append(video);
const end = Date.now() + 8000;
let loadedWidth = null;
video.addEventListener('loadeddata', () => { loadedWidth = video.videoWidth; });
const report = (state) => {
  const error = video.error ? video.error.code : null;
  done({state, error, readyState: video.readyState, currentTime: video.currentTime,
        width: video.videoWidth, height: video.videoHeight, loadedWidth});
  video.removeAttribute('src');
  video.load();
  video.remove();
};
video.addEventListener('error', () => report('error'));
video.play().catch(() => {});
(function poll() {
  if (video.error) return;
  if (video.currentTime > 1.0) return report(video.videoWidth > 0 ? 'playing' : 'no-picture');
  if (Date.now() > end) return report('stuck');
  setTimeout(poll, 100);
})();
"""

PLAYS_VIDEO = """
const done = arguments[arguments.length - 1];
window.__TAURI_INTERNALS__.invoke('webview_plays_video').then(done, (e) => done('error: ' + e));
"""


class Driver:
    def __init__(self, url: str) -> None:
        self.url = url
        self.session = ""

    def call(self, method: str, path: str, body: Any = None, timeout: float = 60) -> Any:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(
            self.url + path, data=data, method=method, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read() or b"{}").get("value")
        except urllib.error.HTTPError as e:
            raise RuntimeError(
                f"{method} {path}: {e.code} {e.read().decode(errors='replace')}"
            ) from e

    def script(self, source: str, *args: Any, run: str = "async") -> Any:
        return self.call(
            "POST", f"/session/{self.session}/execute/{run}", {"script": source, "args": list(args)}
        )


def codec(clip: str) -> str:
    return re.split(r"[-.]", clip, maxsplit=1)[0]


def as_expected(result: dict[str, Any], must_play: bool) -> bool:
    """The preview plays a clip from its ``loadeddata``, and shows the frame compare instead on
    a media error or when that event finds no picture width."""
    loaded = result.get("loadedWidth")
    if must_play:
        return bool(result["state"] == "playing" and loaded)
    return bool(result["state"] == "error" or loaded == 0)


def web_process_va_libraries() -> list[str]:
    """The libva, VA-API driver and GStreamer VA files that WebKit's web processes have mapped."""
    found: set[str] = set()
    for proc in Path("/proc").iterdir():
        try:
            if not (proc / "comm").read_text().startswith("WebKitWebProces"):
                continue
            maps = (proc / "maps").read_text()
        except OSError:
            continue
        for line in maps.splitlines():
            fields = line.split(maxsplit=5)
            name = fields[-1].rsplit("/", 1)[-1] if len(fields) == 6 else ""
            if name.startswith(("libva.so", "libva-drm.so", "libgstva")) or name.endswith(
                "_drv_video.so"
            ):
                found.add(fields[-1])
    return sorted(found)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        pass


def serve(folder: Path) -> str:
    handler = functools.partial(QuietHandler, directory=str(folder))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("appimage", type=Path)
    parser.add_argument("clips", type=Path)
    parser.add_argument("--expect-player", choices=["yes", "no"], default="yes")
    parser.add_argument("--must-play", default="", help="comma-separated codecs")
    parser.add_argument("--driver", default="WebKitWebDriver")
    args = parser.parse_args()
    must_play = {name for name in args.must_play.split(",") if name}

    clips_url = serve(args.clips)
    port = free_port()
    env = dict(os.environ, TAURI_WEBVIEW_AUTOMATION="true")
    driver_process = subprocess.Popen([args.driver, f"--port={port}"], env=env)
    driver = Driver(f"http://127.0.0.1:{port}")
    failed = False
    try:
        for _ in range(100):
            try:
                driver.call("GET", "/status", timeout=2)
                break
            except (OSError, RuntimeError):
                time.sleep(0.1)
        options = {"binary": str(args.appimage.resolve()), "args": []}
        capabilities = {"alwaysMatch": {"webkitgtk:browserOptions": options}}
        created = driver.call("POST", "/session", {"capabilities": capabilities}, timeout=120)
        driver.session = created["sessionId"]
        driver.call("POST", f"/session/{driver.session}/timeouts", {"script": 30000})
        for _ in range(300):
            if driver.script("return !!window.__TAURI_INTERNALS__", run="sync"):
                break
            time.sleep(0.2)
        plays = driver.script(PLAYS_VIDEO)
        print(json.dumps({"webview_plays_video": plays}), flush=True)
        if plays is not (args.expect_player == "yes"):
            failed = True
        if plays is not True:
            return 1 if failed else 0
        summary: dict[str, list[str]] = {}
        for clip in sorted(args.clips.iterdir()):
            result = driver.script(PLAY, f"{clips_url}/{clip.name}")
            alive = driver.script("return 1", run="sync") == 1
            expected = as_expected(result, codec(clip.name) in must_play)
            line = {"clip": clip.name, **result, "web_process": alive, "as_expected": expected}
            print(json.dumps(line), flush=True)
            summary.setdefault(result["state"] if alive else "crashed", []).append(clip.name)
            if result["state"] == "stuck" or not alive or not expected:
                failed = True
        print(json.dumps({"web_process_va": web_process_va_libraries()}), flush=True)
        print(json.dumps({"summary": summary}), flush=True)
    finally:
        if driver.session:
            try:
                driver.call("DELETE", f"/session/{driver.session}", timeout=30)
            except (OSError, RuntimeError) as e:
                print(f"-- delete session: {e}", file=sys.stderr)
        driver_process.terminate()
        driver_process.wait(timeout=30)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
