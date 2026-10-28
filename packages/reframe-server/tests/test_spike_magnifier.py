"""The statistics behind the magnifier's frame-time table (``desktop/spike/MAGNIFIER.md``): the
dropped frames, the 95th percentile and the refresh rate the threshold comes from."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from desktop.spike.scripts import magnifier_check, magnifier_stats  # noqa: E402

# `kscreen-doctor -o` of KDE Plasma 6.8 (trimmed): DP-1's preferred mode (`!`) is not its
# current one (`*`).
KSCREEN = (
    "\x1b[01;32mOutput: \x1b[0;0m1 HDMI-A-1 b07d9527\n\t\x1b[01;32menabled\x1b[0;0m\n"
    "\x1b[01;33m\tModes: \x1b[0;0m 1:\x1b[01;32m1920x1080@60.00*!\x1b[0;0m  2:1920x1080@59.94 \n"
    "\x1b[01;32mOutput: \x1b[0;0m2 DP-1 6f5109af\n\t\x1b[01;32menabled\x1b[0;0m\n"
    "\x1b[01;33m\tModes: \x1b[0;0m 28:1920x1080@60.00!  29:\x1b[01;32m1920x1080@165.00*\x1b[0;0m"
    "  30:1920x1080@144.00 \n"
)


def test_the_refresh_rate_is_the_current_mode_not_the_preferred_one() -> None:
    assert magnifier_check.refresh_rates(KSCREEN) == {"HDMI-A-1": 60.0, "DP-1": 165.0}


def test_a_frame_is_dropped_past_one_and_a_half_periods_and_counts_the_periods_it_skipped() -> None:
    # At 60 Hz: on time, just under the threshold (25 ms), one skipped period, two skipped.
    intervals = [16.7, 24.9, 26.0, 50.0]
    assert magnifier_stats.dropped(intervals, 60.0) == {"late": 2, "missed": 3}


def test_the_95th_percentile_shows_spikes_only_when_more_than_5_percent_are_slow() -> None:
    five = [16.7] * 95 + [33.4] * 5
    six = [16.7] * 94 + [33.4] * 6
    assert magnifier_stats.spread(five)["p95"] == 16.7
    assert magnifier_stats.spread(six)["p95"] == 33.4
    assert magnifier_stats.spread(five)["worst"] == 33.4


def test_the_95th_percentile_rounds_its_rank_up() -> None:
    # 2 slow frames of 21 are 9.5 %: the 95th percentile is the 20th value (19.95 rounded up).
    assert magnifier_stats.spread([16.7] * 19 + [33.4] * 2)["p95"] == 33.4


def test_the_median_interval_is_not_pulled_up_by_one_long_frame() -> None:
    assert magnifier_stats.spread([16.0, 16.0, 17.0, 50.0])["median"] == 16.5


def test_the_frame_rate_counts_frames_over_the_summed_intervals() -> None:
    # WebKitGTK's 1 ms steps: three frames in 49 ms are 61.22 fps, not the 62.5 of the median.
    assert magnifier_stats.rate([16.0, 16.0, 17.0]) == 61.22


def test_a_runs_first_interval_does_not_count() -> None:
    # Firefox and WebKitGTK without DMA-BUF start some runs with an interval of about 0 ms.
    run = {"intervals": [0.1, 20.0, 20.0, 20.0], "draws": [1.0] * 5, "events_per_second": 60.0}
    summary = magnifier_stats.summarise(run, 60.0)
    assert summary["rate_fps"] == 50.0
    assert summary["interval"]["count"] == 3


def test_redraws_per_second_count_only_the_frames_that_redrew() -> None:
    # 50 frames per second, and a redraw on 5 of the 10 frame callbacks.
    first = {"intervals": [20.0] * 4, "draws": [0.5] * 4, "events_per_second": 50.0}
    second = {"intervals": [20.0] * 4, "draws": [0.5], "events_per_second": 10.0}
    pooled = magnifier_stats.pooled([first, second], 60.0)
    assert pooled["rate_fps"] == 50.0
    assert pooled["redraws_per_second"] == 25.0


def test_several_runs_pool_their_frames_and_add_up_each_runs_drops() -> None:
    first = {"intervals": [16.7, 16.7, 40.0], "draws": [1.0], "events_per_second": 54.0}
    second = {
        "intervals": [16.7, 16.7, 50.0, 16.7],
        "draws": [2.0, 3.0],
        "events_per_second": 60.0,
    }
    pooled = magnifier_stats.pooled([first, second], 60.0)
    assert pooled["runs"] == 2
    assert pooled["frames"] == 5
    assert pooled["redraws"] == 3
    assert pooled["interval"]["worst"] == 50.0
    assert pooled["redraw"]["worst"] == 3.0
    # 40 ms skipped one period, 50 ms two.
    assert pooled["dropped"] == {"late": 2, "missed": 3, "per_run_late": [1, 1]}
    assert pooled["rate_fps"] == 35.69
    assert pooled["events_per_second"] == [54.0, 60.0]
