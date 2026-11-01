"""Run a real ``reframe-server`` in web mode in private folders, for browser checks and the
end-to-end tests.

Every folder the server uses (config, data, cache, a media root, an output root) is below one
new temporary home, so nothing reads or writes the owner's own queue, settings or cache. The
server gets ``REFRAME_POWER_DRY_RUN=1`` (a when-done power action never runs) and serves
``frontend/dist`` as its static folder unless ``--no-static`` is given.

Once ``GET /api/health`` answers, one JSON line goes to stdout: ``url``, ``token``, ``open``
(the address with ``#token=`` for a browser), ``home``, ``media``, ``output``, ``pid``. Ctrl+C,
SIGTERM or SIGHUP stop the server (SIGINT, then SIGKILL after 10 s) and remove the home unless
``--keep`` is given.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import FrameType

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "testing"))

from reframe_testing import fake_tools as ft  # noqa: E402
from reframe_testing.folders_guard import real_folders  # noqa: E402

MEDIA = ROOT / "testdata" / "media"
DIST = ROOT / "frontend" / "dist"
HEALTH_TIMEOUT = 30.0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, required=True, help="loopback port of the server")
    parser.add_argument(
        "--fixtures",
        default="multitrack",
        help="comma-separated names in testdata/media (files with or without extension, or "
        "folders) copied into the media root; empty for none",
    )
    parser.add_argument(
        "--output-fixtures",
        default="",
        help="the same, copied into the output root, which is then a media root too: an "
        "in-place metadata edit in web mode needs a source the server may read and write",
    )
    parser.add_argument("--auth", choices=["token", "password", "none"], default="token")
    parser.add_argument("--token", help="the run's token (default: random)")
    parser.add_argument(
        "--password",
        help="set this login password in the private config before the start (for --auth "
        "password; the run's token is accepted too)",
    )
    parser.add_argument(
        "--tools-dir",
        type=Path,
        help="a folder with ffmpeg and ffprobe (default: the server's own discovery)",
    )
    parser.add_argument(
        "--fake-ffmpeg",
        type=Path,
        metavar="SCENARIO_JSON",
        help="use the fake ffmpeg / ffprobe of reframe_testing with this scenario",
    )
    parser.add_argument(
        "--settings",
        type=Path,
        help="a JSON object merged over the default settings.json before the start",
    )
    parser.add_argument("--no-static", action="store_true", help="API only (no frontend/dist)")
    parser.add_argument(
        "--cors-origin",
        action="append",
        default=[],
        help="another origin allowed to call the API and open the event WebSocket (the Vite dev "
        "server's, for example http://127.0.0.1:5173); repeatable",
    )
    parser.add_argument("--home", type=Path, help="use this empty folder instead of a new one")
    parser.add_argument("--keep", action="store_true", help="keep the home after the stop")
    return parser


def _merge(base: dict[str, object], extra: dict[str, object]) -> dict[str, object]:
    merged = dict(base)
    for key, value in extra.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _merge(current, value)
        else:
            merged[key] = value
    return merged


def _fixture(name: str) -> Path:
    for candidate in (MEDIA / name, MEDIA / f"{name}.mkv"):
        if candidate.exists():
            return candidate
    raise SystemExit(
        f"dev-server: no fixture {name!r} in {MEDIA} (run scripts/make-testdata.py, or copy "
        "testdata/media from the main checkout)"
    )


def _check_home(home: Path) -> None:
    resolved = home.resolve()
    for folder in real_folders():
        if resolved == folder or resolved.is_relative_to(folder) or folder.is_relative_to(resolved):
            raise SystemExit(f"dev-server: {home} overlaps the owner's Reframe folder {folder}")


def _wait_healthy(url: str, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + HEALTH_TIMEOUT
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SystemExit(f"dev-server: the server exited with {process.returncode}")
        try:
            with urllib.request.urlopen(f"{url}/api/health", timeout=1) as answer:
                if answer.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.1)
    raise SystemExit(f"dev-server: no answer from {url}/api/health within {HEALTH_TIMEOUT} s")


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGINT)
    try:
        process.wait(10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    stopping = False

    def on_signal(signum: int, frame: FrameType | None) -> None:
        # Only the first signal stops the run: a second one during the clean-up would cut it
        # short and leave the server and the home behind.
        nonlocal stopping
        if stopping:
            return
        stopping = True
        raise KeyboardInterrupt

    # SIGINT too: a background job of a non-interactive shell starts with SIGINT ignored.
    handled = [signal.SIGINT, signal.SIGTERM]
    if sys.platform != "win32":
        handled.append(signal.SIGHUP)
    for signum in handled:
        signal.signal(signum, on_signal)

    # Checked before anything is made, so that a home given by mistake is never deleted.
    if args.home is not None:
        home = args.home.resolve()
        _check_home(home)
        home.mkdir(parents=True, exist_ok=True)
        if any(home.iterdir()):
            raise SystemExit(f"dev-server: {home} is not empty")
    else:
        home = Path(tempfile.mkdtemp(prefix="reframe-dev-"))
        _check_home(home)

    process: subprocess.Popen[bytes] | None = None
    try:
        command, env, folders, token = _prepare(args, home)
        process = subprocess.Popen(command, env=env)
        url = f"http://127.0.0.1:{args.port}"
        _wait_healthy(url, process)
        print(
            json.dumps(
                {
                    "event": "ready",
                    "url": url,
                    "token": token,
                    "open": f"{url}/#token={token}",
                    "home": str(home),
                    "media": str(folders["media"]),
                    "output": str(folders["output"]),
                    "pid": process.pid,
                }
            ),
            flush=True,
        )
        process.wait()
        return process.returncode or 0
    except KeyboardInterrupt:
        return 130
    finally:
        # Also after a failure before the server started (a missing fixture, a bad settings
        # file): the home is ours either way.
        if process is not None:
            _stop(process)
        if not args.keep:
            shutil.rmtree(home, ignore_errors=True)


def _prepare(
    args: argparse.Namespace, home: Path
) -> tuple[list[str], dict[str, str], dict[str, Path], str]:
    """The home's folders, fixtures and settings, and the server's command and environment."""
    folders = {name: home / name for name in ("config", "data", "cache", "media", "output")}
    for folder in folders.values():
        folder.mkdir(exist_ok=True)

    for root, names in (("media", args.fixtures), ("output", args.output_fixtures)):
        for name in filter(None, (part.strip() for part in names.split(","))):
            source = _fixture(name)
            target = folders[root] / source.name
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copyfile(source, target)

    settings: dict[str, object] = {
        "encoders": {"hardware_tests": False},
        "queue": {"sleep_inhibit": False, "when_done": "nothing"},
        "output": {
            "naming": {"output_folder_mode": "fixed", "output_folder": str(folders["output"])}
        },
    }
    if args.settings is not None:
        settings = _merge(settings, json.loads(args.settings.read_text(encoding="utf-8")))
    (folders["config"] / "settings.json").write_text(json.dumps(settings), encoding="utf-8")

    env = {key: value for key, value in os.environ.items() if not key.startswith("REFRAME_")}
    token: str = args.token or secrets.token_urlsafe(24)
    env.update(
        REFRAME_CONFIG_DIR=str(folders["config"]),
        REFRAME_DATA_DIR=str(folders["data"]),
        REFRAME_CACHE_DIR=str(folders["cache"]),
        REFRAME_POWER_DRY_RUN="1",
        REFRAME_TOKEN=token,
    )
    if args.cors_origin:
        env["REFRAME_CORS_ORIGINS"] = json.dumps(args.cors_origin)
    if args.tools_dir is not None:
        env["REFRAME_FFMPEG"] = str(args.tools_dir / "ffmpeg")
        env["REFRAME_FFPROBE"] = str(args.tools_dir / "ffprobe")
    if args.fake_ffmpeg is not None:
        scenario = json.loads(args.fake_ffmpeg.read_text(encoding="utf-8"))
        fake = ft.make_fake_tools(home / "fake-tools", scenario)
        env = fake.env(env)
        env["REFRAME_FFMPEG"] = str(fake.ffmpeg)
        env["REFRAME_FFPROBE"] = str(fake.ffprobe)
    if not args.no_static:
        if not (DIST / "index.html").is_file():
            raise SystemExit("dev-server: no frontend/dist/index.html (run npm run build:web)")
        env["REFRAME_STATIC_DIR"] = str(DIST)

    if args.password is not None:
        # From a pipe, --set-password reads the first line as the password.
        subprocess.run(
            [sys.executable, "-m", "reframe_server", "--set-password"],
            env=env,
            input=f"{args.password}\n".encode(),
            check=True,
            capture_output=True,
        )
    command = [
        sys.executable,
        "-m",
        "reframe_server",
        "--mode",
        "web",
        "--auth",
        args.auth,
        "--host",
        "127.0.0.1",
        "--port",
        str(args.port),
        "--media-root",
        str(folders["media"]),
        "--output-root",
        str(folders["output"]),
    ]
    if args.output_fixtures.strip():
        command += ["--media-root", str(folders["output"])]
    return command, env, folders, token


if __name__ == "__main__":
    raise SystemExit(main())
