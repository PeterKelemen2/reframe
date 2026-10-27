"""Frame-time statistics of the magnifier runs: the median, the 95th percentile (nearest rank)
and the worst of a list of milliseconds, the frames dropped at an output's refresh rate, and
how often the page redrew. The first interval of each run is left out: it starts at the frame
callback that the run asked for, whose timestamp in some engines is the time of the request
(intervals of 0 to 14 ms in Firefox and in WebKitGTK without the DMA-BUF renderer)."""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from typing import Any

LATE = 1.5
"""An interval longer than this many frame periods is a dropped frame."""


def spread(values: Sequence[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "median": None, "p95": None, "worst": None}
    ordered = sorted(values)
    rank = math.ceil(0.95 * len(ordered))
    return {
        "count": len(ordered),
        "median": round(statistics.median(ordered), 3),
        "p95": round(ordered[rank - 1], 3),
        "worst": round(ordered[-1], 3),
    }


def rate(intervals: Sequence[float]) -> float | None:
    """Frames per second over the intervals (their sum is exact to the clock's step even when
    each interval is rounded)."""
    return round(1000 * len(intervals) / sum(intervals), 2) if intervals else None


def dropped(intervals: Sequence[float], refresh_hz: float) -> dict[str, int]:
    """``late``: intervals longer than :data:`LATE` periods; ``missed``: the periods they
    skipped (an interval of about three periods missed two)."""
    period = 1000.0 / refresh_hz
    late = [value for value in intervals if value > LATE * period]
    return {
        "late": len(late),
        "missed": sum(max(round(value / period) - 1, 1) for value in late),
    }


def steady(run: dict[str, Any]) -> list[float]:
    """The run's frame intervals without its first one."""
    intervals: list[float] = run["intervals"][1:]
    return intervals


def redraw_rate(runs: Sequence[dict[str, Any]]) -> float | None:
    """Redraws per second: the frame rate times the share of frame callbacks that redrew
    (a callback redraws only when a pointer event came since the last one)."""
    fps = rate([value for run in runs for value in steady(run)])
    callbacks = sum(len(run["intervals"]) + 1 for run in runs)
    draws = sum(len(run["draws"]) for run in runs)
    return None if fps is None else round(fps * draws / callbacks, 2)


def summarise(run: dict[str, Any], refresh_hz: float) -> dict[str, Any]:
    """A run record of the page with its statistics, without the raw lists."""
    kept = {key: value for key, value in run.items() if key not in ("intervals", "draws")}
    return kept | {
        "interval": spread(steady(run)),
        "rate_fps": rate(steady(run)),
        "redraws_per_second": redraw_rate([run]),
        "redraw": spread(run["draws"]),
        "dropped": dropped(steady(run), refresh_hz),
        "redraws": len(run["draws"]),
    }


def pooled(runs: Sequence[dict[str, Any]], refresh_hz: float) -> dict[str, Any]:
    """The statistics of several runs of one case, their intervals and redraws taken together."""
    intervals = [value for run in runs for value in steady(run)]
    draws = [value for run in runs for value in run["draws"]]
    late = [dropped(steady(run), refresh_hz) for run in runs]
    return {
        "runs": len(runs),
        "frames": len(intervals),
        "redraws": len(draws),
        "interval": spread(intervals),
        "rate_fps": rate(intervals),
        "redraws_per_second": redraw_rate(runs),
        "redraw": spread(draws),
        "dropped": {
            "late": sum(entry["late"] for entry in late),
            "missed": sum(entry["missed"] for entry in late),
            "per_run_late": [entry["late"] for entry in late],
        },
        "events_per_second": [run["events_per_second"] for run in runs],
    }
