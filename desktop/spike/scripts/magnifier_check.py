"""Frame times of the canvas crop magnifier (the ``magnifier`` page: a real 4K frame of
``hdr10-4k.mkv`` from the sidecar's preview API, four edge strips at 4x and a cursor loupe) in
WebKitGTK (the app), Chromium and Firefox (Playwright's own), under pointer movement.

Each case writes ``results/magnifier-<case>.json``: the page's runs (every animation frame's
interval and every redraw's time), their statistics, the refresh rate of the outputs and the
load of the machine before and after, the windows (read back on ``HDMI-A-1``) and the pointer's
moves. Windows and the real pointer stay on ``HDMI-A-1``; no key is sent.

    uv run python -m desktop.spike.scripts.magnifier_check frame-route
    uv run python -m desktop.spike.scripts.magnifier_check app [--no-dmabuf]
    uv run python -m desktop.spike.scripts.magnifier_check browsers --headless
    uv run python -m desktop.spike.scripts.magnifier_check browsers --headed
    uv run python -m desktop.spike.scripts.magnifier_check summary
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from types import FrameType
from typing import Any

import httpx
from desktop.spike.scripts import app as spike_app
from desktop.spike.scripts import browser, drop_check, kwin, pointer, prime_check, sidecar, windows
from desktop.spike.scripts.magnifier_stats import pooled, summarise
from desktop.spike.scripts.spike_paths import APP, SPIKE

RESULTS = SPIKE / "results"
SOURCE = sidecar.MEDIA / "hdr10-4k.mkv"
SPOT: windows.Spot = (40, 40, None, None)
WINDOW = "1280x800"
PARK = (960, 1040)
"""Where the pointer waits on ``HDMI-A-1``: below every window of the check."""
HEADLESS_HZ = 60.0
"""Headless Chromium and Firefox draw at 60 frames per second without an output."""
REAL_RUNS = 3


def run_text(argv: list[str]) -> str:
    return subprocess.run(argv, capture_output=True, text=True, timeout=20, check=True).stdout


def refresh_rates(text: str) -> dict[str, float]:
    """The current mode's refresh rate of each output in ``kscreen-doctor -o`` (``*``)."""
    rates: dict[str, float] = {}
    clean = re.sub(r"\x1b\[[0-9;]*m", "", text)
    for block in re.split(r"(?m)^Output: ", clean)[1:]:
        name = block.split()[1]
        current = re.search(r"\d+:\d+x\d+@([\d.]+)\*", block)
        if current:
            rates[name] = float(current.group(1))
    return rates


def load_now() -> dict[str, Any]:
    """The machine's load, read only: ``/proc/loadavg``, the top CPU users since they started
    (``ps``) and over the last half second (``top``), and the outputs' refresh rates."""
    top = run_text(["top", "-b", "-n", "2", "-d", "0.5", "-o", "%CPU", "-w", "120"])
    last = top.split("\ntop - ")[-1].splitlines()
    header = next(i for i, line in enumerate(last) if line.strip().startswith("PID"))
    return {
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "loadavg": Path("/proc/loadavg").read_text().strip(),
        "ps": run_text(["ps", "-eo", "pid,comm,%cpu", "--sort=-%cpu"]).splitlines()[:8],
        "top": [line.rstrip() for line in last[header : header + 8]],
        "refresh_hz": refresh_rates(run_text(["kscreen-doctor", "-o"])),
    }


def check_record(record: dict[str, Any]) -> dict[str, Any]:
    if record.get("type") == "failed":
        raise RuntimeError(f"the page failed: {record.get('error')}")
    return record


def is_type(kind: str, **fields: Any) -> Callable[[dict[str, Any]], bool]:
    return lambda r: (
        r.get("check", "magnifier") == "magnifier"
        and r.get("type") in (kind, "failed")
        and all(r.get(key) == value for key, value in fields.items())
    )


def frame_route() -> dict[str, Any]:
    """The preview API's answer for one frame of the 4K source, and ffprobe of the PNG."""
    with tempfile.TemporaryDirectory(prefix="reframe-spike-magnifier-") as tmp:
        home = Path(tmp)
        car = sidecar.start(
            sidecar.frozen_command(), home, extra_env={"XDG_CACHE_HOME": str(home / "xdg")}
        )
        try:
            source_id = car.probe(SOURCE)
            started = time.monotonic()
            answer = car.post("/api/preview/frames", {"source_id": source_id, "timestamps": [2.5]})
            first = time.monotonic() - started
            started = time.monotonic()
            again = car.post("/api/preview/frames", {"source_id": source_id, "timestamps": [2.5]})
            second = time.monotonic() - started
            link = answer["frames"][0]
            unsigned = httpx.get(f"http://127.0.0.1:{car.port}{link['url'].split('?')[0]}")
            png = httpx.get(f"http://127.0.0.1:{car.port}{link['url']}")
            png.raise_for_status()
            path = home / "frame.png"
            path.write_bytes(png.content)
            probe = json.loads(
                run_text(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-show_entries",
                        "stream=codec_name,width,height,pix_fmt",
                        "-of",
                        "json",
                        str(path),
                    ]
                )
            )
        finally:
            with contextlib.suppress(Exception):
                car.client.post("/api/system/shutdown")
                car.process.wait(15)
            if car.process.poll() is None:
                car.process.kill()
                car.process.wait()
            car.close()
    signed = link["url"].split("?", 1)
    return {
        "request": {"source_id": "<from POST /api/sources>", "timestamps": [2.5]},
        "answer": answer | {"frames": [link | {"url": signed[0] + "?…"}]},
        "url_query_keys": [part.split("=")[0] for part in signed[1].split("&")]
        if len(signed) > 1
        else [],
        "seconds": {"first": round(first, 3), "cached": round(second, 3)},
        "cached_again": again["frames"][0]["cached"],
        "png": {
            "status": png.status_code,
            "content_type": png.headers.get("content-type"),
            "bytes": len(png.content),
            "etag": png.headers.get("etag"),
            "ffprobe": probe["streams"],
        },
        "without_signature": {"status": unsigned.status_code, "body": unsigned.text[:300]},
    }


def finish(
    name: str, record: dict[str, Any], refresh_hz: float, runs: list[dict[str, Any]]
) -> dict[str, Any]:
    """Adds the statistics per drive and mode and writes ``results/magnifier-<name>.json``."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        groups.setdefault(f"{run['label']}/{run['mode']}", []).append(run)
    record["refresh_hz_used"] = refresh_hz
    record["cases"] = {key: pooled(group, refresh_hz) for key, group in groups.items()}
    record["runs"] = [
        summarise(run, refresh_hz)
        | {"intervals": [round(v, 2) for v in run["intervals"]]}
        | {"draws": [round(v, 2) for v in run["draws"]]}
        for run in runs
    ]
    path = RESULTS / f"magnifier-{name}.json"
    path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"written": str(path), "cases": record["cases"]}, indent=1))
    return record


def pointer_summary(log: list[dict[str, Any]]) -> dict[str, Any]:
    moves = [entry for entry in log if "to" in entry]
    times = sorted(entry["ms"] for entry in moves)
    return {
        "moves": len(moves),
        "all_read_back_at_target": all(
            entry["read_back"] is not None
            and [round(entry["read_back"][0]), round(entry["read_back"][1])] == entry["to"]
            for entry in moves
        ),
        "read_back_ms": {
            "median": times[len(times) // 2] if times else None,
            "worst": times[-1] if times else None,
        },
        "presses": sum("press" in entry for entry in log),
    }


CALIBRATE = (1150, 700)
"""A point of the window's frame that lands below the edge strips, on the page's empty
background, whatever the height of the title bar or the browser's toolbar (28 to 130 px)."""


def calibrate(
    device: pointer.Pointer, lines: drop_check.Lines, frame: kwin.Rect
) -> tuple[int, int]:
    """The offset from the page's client coordinates to the desktop's, from a move onto the
    page's empty background (the page logs the first move after a quiet moment)."""
    # Firefox fires no pointermove for the move that enters its window, only for the next one;
    # WebKitGTK once saw none for the second move either, so a few points are tried.
    device.move(frame.x + CALIBRATE[0] + 20, frame.y + CALIBRATE[1])
    seen = None
    for attempt in range(4):
        time.sleep(0.4)
        target = (frame.x + CALIBRATE[0] - 10 * attempt, frame.y + CALIBRATE[1])
        since = lines.mark()
        device.move(*target)
        seen = lines.wait(is_type("pointer"), 2, since)
        if seen is not None:
            break
    if seen is None:
        raise RuntimeError(f"the page saw no pointer move near {target} (window {frame})")
    offset = (round(target[0] - seen["x"]), round(target[1] - seen["y"]))
    # A second point checks the offset before the pointer goes over the frame.
    time.sleep(0.4)
    check = (target[0] - 80, target[1] - 40)
    since = lines.mark()
    device.move(*check)
    seen = lines.wait(is_type("pointer"), 5, since)
    if seen is None or (round(seen["x"]) + offset[0], round(seen["y"]) + offset[1]) != check:
        raise RuntimeError(f"the offset {offset} does not hold at {check}: {seen}")
    return offset


def real_runs(
    device: pointer.Pointer,
    lines: drop_check.Lines,
    session: windows.Session,
    ready: dict[str, Any],
    offset: tuple[int, int],
    first: int,
    count: int,
    seconds: float,
) -> list[dict[str, Any]]:
    """``count`` runs with the real pointer along the page's path, each until the page has
    logged it; between runs the pointer rests in the page's bottom bar."""
    x, y, width, height = ready["layout"]["main"]
    path = ready["path"]
    bar = ready["layout"]["bar"]
    rest = (round(bar[0] + bar[2] / 2 + offset[0]), round(bar[1] + bar[3] / 2 + offset[1]))
    moves: list[dict[str, Any]] = []
    for index in range(first, first + count):
        if lines.wait(is_type("armed", next=index), 30) is None:
            raise RuntimeError(f"the page is not armed for run {index}")
        since = lines.mark()
        started = time.monotonic()
        sent = 0
        while lines.wait(is_type("run", index=index, label="real"), 0, since) is None:
            if session.failure is not None:
                raise windows.WrongOutput(session.failure)
            if time.monotonic() - started > seconds + 5:
                raise TimeoutError(f"run {index} did not end")
            elapsed = (time.monotonic() - started) * 1000
            angle = 2 * math.pi * elapsed / path["turn"]
            px = x + width / 2 + path["radius"] * width * math.cos(angle)
            py = y + height / 2 + path["radius"] * height * math.sin(angle)
            device.move(round(px + offset[0]), round(py + offset[1]))
            sent += 1
            pause = started + sent * path["eventEvery"] / 1000 - time.monotonic()
            if pause > 0:
                time.sleep(pause)
        moves.append(
            {
                "index": index,
                "sent": sent,
                "seconds": round(time.monotonic() - started, 3),
                "ended": time.strftime("%H:%M:%S"),
            }
        )
        device.move(*rest)
    return moves


def _interrupt(number: int, frame: FrameType | None) -> None:
    raise KeyboardInterrupt(f"signal {number}")


def leftovers(pids: list[int]) -> list[str]:
    alive = []
    for pid in pids:
        with contextlib.suppress(FileNotFoundError, ProcessLookupError):
            state = Path(f"/proc/{pid}/stat").read_text().split(") ")[1].split()[0]
            if state != "Z":
                alive.append(f"{pid} {state}")
    return alive


@contextlib.contextmanager
def real_pointer(session: windows.Session) -> Iterator[pointer.Pointer]:
    device = pointer.for_session(session.journal, session.screen)
    with device:
        assert device.device is not None
        pointer.check_device(device.device)
        # KWin opens a window on the output under the cursor.
        device.move(session.screen.x + PARK[0], session.screen.y + PARK[1])
        yield device


def app_case(no_dmabuf: bool, tag: str = "") -> dict[str, Any]:
    name = ("webkitgtk-no-dmabuf" if no_dmabuf else "webkitgtk") + tag
    signal.signal(signal.SIGTERM, _interrupt)
    record: dict[str, Any] = {"case": name, "load_before": load_now()}
    with tempfile.TemporaryDirectory(prefix="reframe-spike-magnifier-") as tmp:
        home = Path(tmp)
        extra = {
            "REFRAME_SPIKE_PAGE": "magnifier",
            "REFRAME_SPIKE_WINDOW_SIZE": WINDOW,
            "REFRAME_SPIKE_REPORT_TOKEN": "1",
            "REFRAME_SPIKE_SNAPSHOT_DIR": str(home / "shots"),
            "XDG_CACHE_HOME": str(home / "xdg-cache"),
        }
        if no_dmabuf:
            extra["WEBKIT_DISABLE_DMABUF_RENDERER"] = "1"
        (home / "shots").mkdir()
        (home / "app").mkdir()
        env = spike_app.environment(home / "app", unfrozen=False, extra=extra)
        record["env"] = {key: value for key, value in extra.items() if "DIR" not in key}
        with windows.Session(cursor=True) as session, real_pointer(session) as device:
            process = session.spawn(
                [str(APP)],
                SPOT,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            lines = drop_check.Lines(process)
            try:
                placed = session.window(process.pid)
                record["window"] = placed.summary()
                ready_line = lines.wait(lambda r: r.get("event") == "sidecar_ready", 30)
                if ready_line is None:
                    raise RuntimeError("the sidecar was not ready")
                with httpx.Client(
                    base_url=f"http://127.0.0.1:{ready_line['port']}",
                    headers={"Authorization": f"Bearer {ready_line['token']}"},
                    timeout=60,
                ) as client:
                    client.post("/api/sources", json={"paths": [str(SOURCE)]}).raise_for_status()
                frame = check_record(lines.wait(is_type("frame"), 120) or {"type": "failed"})
                ready = check_record(lines.wait(is_type("ready"), 60) or {"type": "failed"})
                record["frame"], record["ready"] = frame, ready
                record["bench"] = lines.wait(is_type("bench"), 60)
                if lines.wait(is_type("armed", next=1), 120) is None:
                    raise RuntimeError("the page-driven runs did not end")
                record["load_between"] = load_now()
                offset = calibrate(device, lines, placed.rect)
                record["offset"] = offset
                record["real_moves"] = real_runs(
                    device, lines, session, ready, offset, 1, REAL_RUNS, 4
                )
                device.move(session.screen.x + PARK[0], session.screen.y + PARK[1])
            finally:
                assert process.stdin is not None
                with contextlib.suppress(BrokenPipeError):
                    process.stdin.write(b"quit\n")
                    process.stdin.flush()
                try:
                    record["exit"] = process.wait(15)
                except subprocess.TimeoutExpired:
                    record["exit"] = windows.terminate(process)
            record["pointer"] = pointer_summary(device.log)
            shot = home / "shots" / "magnifier-webkitgtk.png"
            if shot.exists() and not no_dmabuf and not tag:
                target = RESULTS / "magnifier-webkitgtk.png"
                shutil.copyfile(shot, target)
                prime_check.shrink(target)
        record["scripts_loaded_after"] = session.unloaded()
    record["device_left"] = pointer.NAME in Path("/proc/bus/input/devices").read_text()
    spawned = next((r for r in lines.seen if r.get("event") == "sidecar_spawned"), {})
    record["leftovers"] = leftovers([process.pid, *([spawned["pid"]] if spawned else [])])
    record["load_after"] = load_now()
    record["window_failure"] = session.failure
    runs = [r for r in lines.seen if r.get("type") == "run"]
    record["sidecar_stopped"] = next(
        (r for r in lines.seen if r.get("event") == "sidecar_stopped"), None
    )
    hz = record["load_before"]["refresh_hz"].get(kwin.SECONDARY, HEADLESS_HZ)
    return finish(name, record, hz, runs)


def browsers_case(
    engine: str, headed: bool, playwright_runs: int = 3, tag: str = ""
) -> dict[str, Any]:
    name = f"{engine}-{'headed' if headed else 'headless'}{tag}"
    signal.signal(signal.SIGTERM, _interrupt)
    record: dict[str, Any] = {"case": name, "load_before": load_now()}
    shot = RESULTS / f"magnifier-{engine}{tag}.png"
    with (
        tempfile.TemporaryDirectory(prefix="reframe-spike-magnifier-") as tmp,
        browser.serve_ui() as origin,
        browser.backend(origin) as car,
    ):
        url = browser.page_url(origin, "magnifier", car, source=str(SOURCE))
        script = SPIKE / "scripts" / "magnifier_browsers.mjs"
        argv = [
            "node",
            str(script),
            url,
            engine,
            str(shot if headed else Path(tmp) / "shot.png"),
            f"--playwright-runs={playwright_runs}",
        ]
        env = browser.browser_env()
        # Playwright looks for its browsers below XDG_CACHE_HOME unless told where they are.
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(
            Path(env.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "ms-playwright"
        )
        env["XDG_CACHE_HOME"] = str(Path(tmp) / "xdg-cache")
        if not headed:
            process = subprocess.Popen(argv, cwd=SPIKE, stdout=subprocess.PIPE, env=env)
            lines = drop_check.Lines(process)
            code = process.wait(300)
        else:
            with windows.Session(cursor=True) as session, real_pointer(session) as device:
                exe = session.wrapper(browser.executables()[engine], SPOT)
                argv += ["--headed", f"--exe={exe}", f"--real-runs={REAL_RUNS}"]
                process = subprocess.Popen(argv, cwd=SPIKE, stdout=subprocess.PIPE, env=env)
                lines = drop_check.Lines(process)
                try:
                    waiting = lines.wait(is_type("await_real"), 240)
                    if waiting is None:
                        raise RuntimeError("the browser did not get to the real-pointer runs")
                    placed = next(p for p in session.placed if p.added["normal"])
                    placed = session.window(placed.pid)
                    record["window"] = placed.summary()
                    ready = check_record(lines.wait(is_type("ready"), 0) or {"type": "failed"})
                    record["load_between"] = load_now()
                    offset = calibrate(device, lines, placed.rect)
                    record["offset"] = offset
                    record["real_moves"] = real_runs(
                        device, lines, session, ready, offset, waiting["next"], REAL_RUNS, 4
                    )
                    device.move(session.screen.x + PARK[0], session.screen.y + PARK[1])
                    code = process.wait(60)
                finally:
                    if process.poll() is None:
                        windows.terminate(process)
                        seen = [
                            {k: r.get(k) for k in ("type", "label", "index", "next") if k in r}
                            for r in lines.seen
                        ]
                        print(json.dumps({"stopped_after": seen}), file=sys.stderr)
                record["pointer"] = pointer_summary(device.log)
                record["windows"] = [p.summary() for p in session.placed]
            record["scripts_loaded_after"] = session.unloaded()
            record["device_left"] = pointer.NAME in Path("/proc/bus/input/devices").read_text()
            record["window_failure"] = session.failure
    if headed and shot.exists():
        prime_check.shrink(shot)
    record["exit"] = code
    if code != 0:
        raise RuntimeError(f"magnifier_browsers.mjs ended with {code}")
    record["leftovers"] = leftovers([process.pid])
    record["load_after"] = load_now()
    record["frame"] = next((r for r in lines.seen if r.get("type") == "frame"), None)
    record["ready"] = next((r for r in lines.seen if r.get("type") == "ready"), None)
    record["bench"] = next((r for r in lines.seen if r.get("type") == "bench"), None)
    record["version"] = lines.seen[0]["version"] if lines.seen else None
    record["playwright_moves"] = [r for r in lines.seen if r.get("type") == "playwright_moves"]
    record["page_errors"] = [r for r in lines.seen if r.get("type") == "page_error"]
    runs = [r for r in lines.seen if r.get("type") == "run"]
    hz = record["load_before"]["refresh_hz"].get(kwin.SECONDARY, HEADLESS_HZ)
    return finish(name, record, hz if headed else HEADLESS_HZ, runs)


def summary() -> dict[str, Any]:
    rows = []
    for path in sorted(RESULTS.glob("magnifier-*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if "cases" not in data:
            continue
        load = [data.get(key, {}).get("loadavg", "") for key in ("load_before", "load_after")]
        for key, case in data["cases"].items():
            rows.append(
                {
                    "file": path.name,
                    "case": data["case"],
                    "drive": key,
                    "refresh_hz": data["refresh_hz_used"],
                    "load_1min": [float(text.split()[0]) for text in load if text],
                    **case,
                }
            )
    for row in rows:
        interval, redraw, drop = row["interval"], row["redraw"], row["dropped"]
        events = row["events_per_second"]
        print(
            f"| {row['case']} | {row['drive']} | {interval['median']} / {interval['p95']} / "
            f"{interval['worst']} | {row['rate_fps']} | {redraw['median']} / {redraw['p95']} / "
            f"{redraw['worst']} | {drop['late']} ({drop['missed']}) of {row['frames']} | "
            f"{row['runs']} | {min(events):.0f}-{max(events):.0f} | {row['refresh_hz']:g} | "
            f"{' -> '.join(str(v) for v in row['load_1min'])} |"
        )
    return {"rows": rows}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("frame-route", help="the preview API's answer and the PNG (headless)")
    app_parser = commands.add_parser("app", help="WebKitGTK: the app on HDMI-A-1")
    app_parser.add_argument("--no-dmabuf", action="store_true")
    app_parser.add_argument("--tag", default="", help="a suffix of the result's name (a repeat)")
    browsers_parser = commands.add_parser("browsers", help="Playwright's Chromium and Firefox")
    browsers_parser.add_argument("--headed", action="store_true")
    browsers_parser.add_argument("--headless", action="store_true")
    browsers_parser.add_argument("--engines", default="chromium,firefox")
    browsers_parser.add_argument("--playwright-runs", type=int, default=3)
    browsers_parser.add_argument("--tag", default="", help="a suffix of the result's name")
    commands.add_parser("summary", help="the table of every results/magnifier-*.json")
    args = parser.parse_args(argv)
    RESULTS.mkdir(exist_ok=True)
    if args.command == "frame-route":
        answer = frame_route()
        path = RESULTS / "magnifier-frame-route.json"
        path.write_text(json.dumps(answer, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps(answer, indent=1, ensure_ascii=False))
    elif args.command == "app":
        app_case(args.no_dmabuf, args.tag)
    elif args.command == "browsers":
        for engine in args.engines.split(","):
            if args.headless or not args.headed:
                browsers_case(engine, False, args.playwright_runs, args.tag)
            if args.headed:
                browsers_case(engine, True, args.playwright_runs, args.tag)
    else:
        summary()
    return 0


if __name__ == "__main__":
    sys.exit(main())
