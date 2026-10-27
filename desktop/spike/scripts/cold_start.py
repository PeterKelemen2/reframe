"""Cold start to "ready": (a) the sidecar alone, spawn to the ready line; (b) the app, process
start to its page showing ``GET /api/health``. Each run gets new temporary folders; the app runs
of a case share their XDG folders (WebKitGTK's caches). ``warm`` runs one start first that is not
counted, and so does every app case, to fill its XDG caches; ``evicted`` drops the page cache of
the measured files before each run and checks with ``fincore`` that it is gone."""

from __future__ import annotations

import argparse
import contextlib
import json
import shutil
import statistics
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from desktop.spike.scripts import app, page_cache, sidecar, windows
from desktop.spike.scripts.spike_paths import APP, REPO, SIDECAR_ONEDIR


def unfrozen_files() -> list[Path]:
    """What ``uv run reframe-server`` reads and this user owns: uv, the venv and the workspace
    sources. A system interpreter and its standard library stay cached: fincore cannot count
    files the user cannot write (cachestat: "Operation not permitted")."""
    uv = shutil.which("uv")
    return [
        REPO / ".venv",
        REPO / "packages" / "reframe" / "src",
        REPO / "packages" / "reframe-server" / "src",
        *([Path(uv).resolve()] if uv else []),
    ]


def measured_files(target: str, unfrozen: bool) -> list[Path]:
    files = unfrozen_files() if unfrozen else [SIDECAR_ONEDIR]
    return [APP, *files] if target == "app" else files


@dataclass(frozen=True)
class Case:
    target: str
    unfrozen: bool = False
    cache: str = "warm"
    in_setup: bool = False
    """The app starts its sidecar in Tauri's setup hook, not before the window."""

    @property
    def label(self) -> str:
        sidecar = "uv run reframe-server" if self.unfrozen else "frozen onedir"
        where = ", spawned in setup" if self.in_setup else ""
        return f"{self.target} ({sidecar}{where})"


STOP_LIMIT = 15.0
"""Seconds a sidecar gets to stop after the shutdown request before it is killed."""


def run_sidecar(case: Case, xdg: Path) -> dict[str, Any]:
    command = sidecar.unfrozen_command() if case.unfrozen else sidecar.frozen_command()
    with tempfile.TemporaryDirectory(prefix="reframe-spike-") as tmp:
        car = sidecar.start(command, Path(tmp))
        try:
            with contextlib.suppress(httpx.HTTPError):
                car.client.post("/api/system/shutdown")
            windows.reap(car.process, STOP_LIMIT)
        finally:
            car.close()
            if car.process.poll() is None:
                car.process.kill()
                car.process.wait()
            if car.process.stdout is not None:
                car.process.stdout.close()
    return {"total": car.ready_after}


def run_app(case: Case, xdg: Path) -> dict[str, Any]:
    """One start of the app; ``xdg`` is shared by the runs of a case, so its caches (the
    shader cache) are warm after the first run as the owner's would be."""
    env = {"REFRAME_SPIKE_EXIT_AFTER_HEALTH": "1"}
    if case.in_setup:
        env["REFRAME_SPIKE_SPAWN_IN_SETUP"] = "1"
    with tempfile.TemporaryDirectory(prefix="reframe-spike-") as tmp:
        started = app.start(Path(tmp), unfrozen=case.unfrozen, extra_env=env, xdg=xdg)
        try:
            page = started.wait_event("page_health")
            started.process.wait(15)
        finally:
            if started.process.poll() is None:
                started.process.kill()
                started.process.wait()
    events = started.events
    return {
        "total": page["seen"],
        "spawn (in app)": events["sidecar_spawned"]["ms"] / 1000,
        "sidecar ready (in app)": events["sidecar_ready"]["ms"] / 1000,
        "page health (in app)": page["ms"] / 1000,
        "page mounted (page)": page["page"]["mounted"] / 1000,
    }


def measure(case: Case, runs: int) -> dict[str, Any]:
    run = run_app if case.target == "app" else run_sidecar
    files = measured_files(case.target, case.unfrozen)
    samples: list[dict[str, Any]] = []
    eviction: list[dict[str, int]] = []
    with tempfile.TemporaryDirectory(prefix="reframe-spike-xdg-") as xdg:
        if case.cache == "warm" or case.target == "app":
            run(case, Path(xdg))
        for _ in range(runs):
            if case.cache == "evicted":
                before = page_cache.resident(files)
                page_cache.evict(files)
                after = page_cache.resident(files)
                eviction.append(
                    {"before": before.cached, "after": after.cached, "size": after.size}
                )
            time.sleep(0.5)
            samples.append(run(case, Path(xdg)))
    totals = [sample["total"] for sample in samples]
    result: dict[str, Any] = {
        "case": case.label,
        "cache": case.cache,
        "runs": runs,
        "median": statistics.median(totals),
        "worst": max(totals),
        "best": min(totals),
        "samples": samples,
    }
    for key in samples[0]:
        if key != "total":
            result[f"median {key}"] = statistics.median(sample[key] for sample in samples)
    if eviction:
        result["page cache (bytes)"] = eviction
    return result


CASES = [
    Case("sidecar"),
    Case("sidecar", cache="evicted"),
    Case("sidecar", unfrozen=True),
    Case("sidecar", unfrozen=True, cache="evicted"),
    Case("app"),
    Case("app", cache="evicted"),
    Case("app", in_setup=True),
    Case("app", cache="evicted", in_setup=True),
    Case("app", unfrozen=True),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=["sidecar", "app"])
    parser.add_argument("--unfrozen", action="store_true")
    parser.add_argument("--cache", choices=["warm", "evicted"], default="warm")
    parser.add_argument("--in-setup", action="store_true", help="app: spawn in the setup hook")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--all", action="store_true", help="every case of the table")
    parser.add_argument("--json", type=Path, help="also write the results here")
    args = parser.parse_args(argv)
    if args.all:
        cases = CASES
    elif args.target:
        cases = [Case(args.target, args.unfrozen, args.cache, args.in_setup)]
    else:
        parser.error("give --target or --all")
    results = []
    for case in cases:
        result = measure(case, args.runs)
        results.append(result)
        print(
            f"{case.label:55} {case.cache:8} n={args.runs:<3} "
            f"median {result['median']:.3f} s  worst {result['worst']:.3f} s",
            flush=True,
        )
    if args.json:
        args.json.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    else:
        json.dump(results, sys.stdout, indent=2)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
