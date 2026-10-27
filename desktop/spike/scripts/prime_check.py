"""PrimeVue 4 rendering: the ``prime`` page (DataTable of 200 rows, Dialog, Select, Slider, Tabs,
Toast; the frontend's preset, light and dark) in WebKitGTK (the app on the secondary output, its
own snapshots) and in Playwright's headless Chromium and Firefox at the same CSS viewport and a
device pixel ratio of 1. Writes ``results/prime/<engine>-<theme>-<state>.png`` and
``results/prime-metrics.json``: the page's measurements per engine, their differences, the
share of pixels that differ, and every CSP violation.

    uv run python -m desktop.spike.scripts.prime_check
"""

from __future__ import annotations

import argparse
import itertools
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from desktop.spike.scripts import app as spike_app
from desktop.spike.scripts import browser, drop_check, pointer, windows
from desktop.spike.scripts.spike_paths import APP, SPIKE

RESULTS = SPIKE / "results"
SHOTS = RESULTS / "prime"
WIDTH, HEIGHT = 1280, 800
APP_SPOT: windows.Spot = (40, 40, None, None)
ENGINES = ("webkitgtk", "chromium", "firefox")


def webkitgtk(out: Path) -> dict[str, Any]:
    """Runs the page in the app; it snapshots each state itself and logs its measurements."""
    with tempfile.TemporaryDirectory(prefix="reframe-spike-prime-") as tmp:
        extra = {
            "REFRAME_SPIKE_PAGE": "prime",
            "REFRAME_SPIKE_SNAPSHOT_DIR": str(out),
            "REFRAME_SPIKE_WINDOW_SIZE": f"{WIDTH}x{HEIGHT}",
        }
        env = spike_app.environment(Path(tmp), unfrozen=False, extra=extra)
        with windows.Session() as session:
            process = session.spawn(
                [str(APP)],
                APP_SPOT,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            lines = drop_check.Lines(process)
            try:
                window = session.window(process.pid)
                done = lines.wait(
                    lambda r: r.get("check") == "prime" and r.get("type") == "done", 90
                )
                if done is None:
                    raise RuntimeError("the prime page did not finish")
            finally:
                assert process.stdin is not None
                process.stdin.write(b"quit\n")
                process.stdin.flush()
                code = process.wait(15)
        states = [r for r in lines.seen if r.get("check") == "prime" and r.get("type") == "state"]
        return {
            "window": window.summary(),
            "focus": [
                {k: v for k, v in r.items() if k not in ("seen", "t")}
                for r in session.journal.seen
                if r["event"] in ("loaded", "kept_active", "active")
            ],
            "scripts_loaded_after": session.unloaded(),
            "exit": code,
            "states": [
                {key: r[key] for key in ("theme", "state", "metrics", "snapshot")} for r in states
            ],
            "csp": [r for r in lines.seen if r.get("check") == "csp"],
            "csp_probe": probe_of(lines.seen),
            "logs": [
                r for r in lines.seen if r.get("check") == "prime" and r.get("type") != "state"
            ],
        }


def browsers(out: Path) -> dict[str, Any]:
    with browser.serve_ui() as origin, browser.backend(origin) as car:
        url = browser.page_url(origin, "prime", car)
        lines = browser.node(
            SPIKE / "scripts" / "prime_browsers.mjs", [url, str(out), str(WIDTH), str(HEIGHT)]
        )
    return collect(lines)


def headed(out: Path) -> dict[str, Any]:
    """Headed Chromium and Firefox on the secondary output: headless Chromium hides its
    scrollbars, so only a window shows which kind it draws."""
    with windows.Session(cursor=True) as session:
        device = pointer.for_session(session.journal, session.screen)
        with device:
            assert device.device is not None
            pointer.check_device(device.device)
            # KWin opens a window on the output under the cursor, also one it does not match.
            device.move(session.screen.x + session.screen.width // 2, session.screen.y + 1040)
            paths = browser.executables()
            with browser.serve_ui() as origin, browser.backend(origin) as car:
                arguments = [
                    browser.page_url(origin, "prime", car),
                    str(out),
                    str(WIDTH),
                    str(HEIGHT),
                    "--headed",
                    "--suffix=-headed",
                    "--states=base",
                ]
                for engine, binary in paths.items():
                    arguments.append(f"--exe-{engine}={session.wrapper(binary, APP_SPOT)}")
                lines = browser.node(
                    SPIKE / "scripts" / "prime_browsers.mjs",
                    arguments,
                    stop=lambda: session.failure,
                )
    result = collect(lines)
    result["windows"] = [placed.summary() for placed in session.placed]
    result["other_windows"] = [r for r in session.journal.seen if r["event"] == "other"]
    result["scripts_loaded_after"] = session.unloaded()
    result["pointer_log"] = device.log
    return result


def probe_of(logs: list[dict[str, Any]]) -> str | None:
    return next((r["probe"] for r in logs if r.get("type") == "csp_probe"), None)


def collect(lines: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for line in lines:
        engine = result.setdefault(line["engine"], {"version": line["version"], "states": []})
        if "logs" in line:
            engine["csp"] = [r for r in line["logs"] if r.get("check") == "csp"]
            engine["csp_probe"] = probe_of(line["logs"])
            engine["logs"] = [r for r in line["logs"] if r.get("check") != "csp"]
        else:
            engine["states"].append({key: line[key] for key in ("theme", "state", "metrics")})
    return result


def shrink(path: Path) -> None:
    """Rewrites a screenshot with a palette of 256 colours (about a third of the size); the
    measurements and the pixel counts are taken before."""
    smaller = path.with_suffix(".small.png")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(path),
            "-vf",
            "split[a][b];[a]palettegen=max_colors=256[p];[b][p]paletteuse=dither=none",
            str(smaller),
        ],
        check=True,
        timeout=60,
    )
    smaller.replace(path)


def pixels(path: Path) -> bytes:
    """The image as rgb24 (ffmpeg decodes it)."""
    return subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True,
        check=True,
        timeout=60,
    ).stdout


def differing(first: Path, second: Path) -> float | None:
    """The share of pixels that differ; ``None`` when the sizes differ."""
    a, b = pixels(first), pixels(second)
    if len(a) != len(b):
        return None
    if a == b:
        return 0.0
    count = sum(a[i : i + 3] != b[i : i + 3] for i in range(0, len(a), 3))
    return round(count / (len(a) // 3), 4)


def box_differences(
    runs: dict[str, dict[str, Any]], tolerance: float = 1.0
) -> list[dict[str, Any]]:
    """Every measured box (x, y, width, height) or number that differs by more than
    ``tolerance`` px between two engines, per theme and state."""
    found = []
    by_state = {
        engine: {(s["theme"], s["state"]): s["metrics"] for s in run["states"]}
        for engine, run in runs.items()
    }
    for key in by_state["webkitgtk"]:
        for left, right in itertools.combinations(ENGINES, 2):
            a, b = by_state[left].get(key), by_state[right].get(key)
            if a is None or b is None:
                continue
            for name in a:
                if name in ("userAgent", "font"):
                    continue
                first, second = a[name], b.get(name)
                if (
                    isinstance(first, list)
                    and isinstance(second, list)
                    and len(first) == len(second)
                ):
                    delta = max(abs(x - y) for x, y in zip(first, second, strict=True))
                elif isinstance(first, int | float) and isinstance(second, int | float):
                    delta = abs(first - second)
                else:
                    delta = 0.0 if first == second else float("inf")
                if delta > tolerance:
                    found.append(
                        {
                            "theme": key[0],
                            "state": key[1],
                            "metric": name,
                            "engines": [left, right],
                            "values": [first, second],
                            "delta": delta,
                        }
                    )
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--skip-app", action="store_true", help="browsers only (no window)")
    parser.add_argument(
        "--headed", action="store_true", help="also headed Chromium and Firefox (windows)"
    )
    args = parser.parse_args(argv)
    windows.stop_on_signals()
    SHOTS.mkdir(parents=True, exist_ok=True)
    runs: dict[str, dict[str, Any]] = {}
    if not args.skip_app:
        runs["webkitgtk"] = webkitgtk(SHOTS)
    runs |= browsers(SHOTS)
    report: dict[str, Any] = {"viewport": [WIDTH, HEIGHT, 1], "runs": runs}
    if args.headed:
        report["headed"] = headed(SHOTS)
    if "webkitgtk" in runs:
        report["box_differences"] = box_differences(runs)
        report["pixel_differences"] = {
            f"{theme}-{state}": {
                f"{left}/{right}": differing(
                    SHOTS / f"{left}-{theme}-{state}.png", SHOTS / f"{right}-{theme}-{state}.png"
                )
                for left, right in itertools.combinations(ENGINES, 2)
            }
            for theme in ("light", "dark")
            for state in ("base", "select", "dialog")
        }
    for shot in SHOTS.glob("*.png"):
        shrink(shot)
    (RESULTS / "prime-metrics.json").write_text(
        json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    shown = {key: report[key] for key in report if key not in ("runs", "headed")}
    print(json.dumps(shown, indent=1)[:6000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
