"""The ``-progress`` parser, the weighted percent and the ETA (C-11), with clocks that jump."""

from __future__ import annotations

import pytest

from reframe.models import PlanStep, StepKind
from reframe.queue.progress import (
    MAX_INTERVAL,
    ProgressBlock,
    ProgressParser,
    ProgressTracker,
)
from reframe_testing import fake_tools as ft
from reframe_testing.fake_ffmpeg import progress_block

# --------------------------------------------------------------------------- parser


def blocks_of(text: str) -> list[ProgressBlock]:
    parser = ProgressParser()
    return [b for line in text.splitlines() if (b := parser.feed(line)) is not None]


def test_parser_reads_the_real_long_captures() -> None:
    """The real n9.0.2 runs (``fake_data``): N/A start-up blocks, padded values, one end."""
    for name in ("progress_null_long.stdout.txt", "progress_mkv_long.stdout.txt"):
        text = (ft.DATA_DIR / name).read_text(encoding="utf-8")
        blocks = blocks_of(text)
        assert len(blocks) == text.count("progress=")
        assert [b.end for b in blocks].count(True) == 1
        assert blocks[-1].end
        times = [b.out_time for b in blocks if b.out_time is not None]
        assert times == sorted(times)
        assert times[-1] > 1.0
        assert all(b.speed is None or b.speed > 0 for b in blocks)


def test_parser_na_and_padded_values() -> None:
    text = progress_block({"na_blocks": 1, "blocks": 1, "na_fields": ["total_size"]}, 0, 0.5)
    [startup] = blocks_of(text)
    assert startup == ProgressBlock(out_time=None, frame=0, fps=0.0, speed=None, end=False)
    padded = "frame=12\nfps=24.0\nout_time_us=500000\ntotal_size=N/A\nspeed= 4.3x\nprogress=end\n"
    [block] = blocks_of(padded)
    assert block == ProgressBlock(out_time=0.5, frame=12, fps=24.0, speed=4.3, end=True)


def test_parser_ignores_other_lines_and_odd_values() -> None:
    parser = ProgressParser()
    assert parser.feed("Exiting with exit code 0") is None
    assert not parser.is_progress_line("Exiting with exit code 0")
    assert parser.is_progress_line("stream_0_0_q=28.0")
    for line in ("out_time_us=-23220", "fps=nan", "speed=fast", "frame=", "progress=continue"):
        result = parser.feed(line)
    assert result == ProgressBlock(out_time=0.0, frame=None, fps=None, speed=None)


# --------------------------------------------------------------------------- tracker


def step(kind: StepKind, weight: float) -> PlanStep:
    return PlanStep(
        kind=kind, tool=None if kind == "finalize" else "ffmpeg", progress_weight=weight
    )


ENCODE = [step("encode", 1.0), step("finalize", 0.0)]


def feed(
    tracker: ProgressTracker,
    *,
    start: float,
    stop: float,
    speed: float,
    media0: float = 0.0,
    every: float = 0.5,
    wall_offset: float = 0.0,
) -> float:
    """Blocks every ``every`` s of monotonic time from ``start`` to ``stop``; returns the media
    time reached."""
    t = start
    media = media0
    while t <= stop + 1e-9:
        tracker.update(
            ProgressBlock(out_time=media, frame=int(media * 25)), mono=t, wall=t + wall_offset
        )
        t += every
        media += every * speed
    return media - every * speed


def test_weighted_percent_across_steps() -> None:
    steps = [step("analyse", 0.05), step("pass1", 0.4), step("pass2", 0.6), step("finalize", 0)]
    tracker = ProgressTracker(steps, expected_duration=100.0)
    tracker.start_step(0)
    assert tracker.update(ProgressBlock(out_time=50.0), mono=0, wall=0).percent == pytest.approx(
        100 * 0.025 / 1.05, abs=1e-3
    )
    tracker.step_done()
    assert tracker.percent == pytest.approx(100 * 0.05 / 1.05, abs=1e-3)
    tracker.start_step(1)
    tracker.update(ProgressBlock(out_time=100.0, end=True), mono=1, wall=1)
    assert tracker.percent == pytest.approx(100 * 0.45 / 1.05, abs=1e-3)
    tracker.start_step(2)
    progress = tracker.update(ProgressBlock(out_time=25.0), mono=2, wall=2)
    assert progress.percent == pytest.approx(100 * (0.45 + 0.15) / 1.05, abs=1e-3)
    assert (progress.step, progress.step_count, progress.step_kind) == (2, 4, "pass2")
    assert tracker.finish().percent == 100.0


def test_percent_never_goes_back() -> None:
    tracker = ProgressTracker(ENCODE, expected_duration=10.0)
    tracker.start_step(0)
    tracker.update(ProgressBlock(out_time=5.0), mono=0, wall=0)
    assert tracker.update(ProgressBlock(out_time=1.0), mono=0.5, wall=0.5).percent == 50.0


def test_unknown_duration_counts_only_step_boundaries() -> None:
    tracker = ProgressTracker(ENCODE, expected_duration=0.0)
    tracker.start_step(0)
    assert tracker.update(ProgressBlock(out_time=5.0), mono=0, wall=0).percent == 0.0
    assert tracker.step_done().percent == 100.0


def test_speed_fps_and_eta_from_the_blocks() -> None:
    tracker = ProgressTracker(ENCODE, expected_duration=100.0)
    tracker.start_step(0)
    first = tracker.update(
        ProgressBlock(out_time=0.0, frame=0, speed=9.0, fps=99.0), mono=0, wall=0
    )
    assert (first.speed, first.fps, first.eta) == (9.0, 99.0, None)  # FFmpeg's, until we know
    feed(tracker, start=0.5, stop=10.0, speed=2.0, media0=1.0)
    progress = tracker.snapshot()
    assert progress.speed == pytest.approx(2.0, rel=1e-3)
    assert progress.fps == pytest.approx(50.0, rel=1e-3)
    assert progress.percent == pytest.approx(20.0, abs=0.01)
    assert progress.eta == pytest.approx(40.0, abs=0.2)  # 80 s of media at 2x


def eta_around_a_gap(*, mono_gap: float, wall_gap: float) -> tuple[float, float, float, float]:
    tracker = ProgressTracker(ENCODE, expected_duration=1000.0)
    tracker.start_step(0)
    media = feed(tracker, start=0.0, stop=60.0, speed=2.0)
    before = tracker.snapshot()
    assert before.eta is not None
    assert before.speed is not None
    # The system sleeps after the last block; the next blocks come after the gap.
    t = 60.0 + mono_gap
    feed(
        tracker,
        start=t,
        stop=t + 2.0,
        speed=2.0,
        media0=media + 1.0,
        wall_offset=wall_gap - mono_gap,
    )
    after = tracker.snapshot()
    assert after.eta is not None
    assert after.speed is not None
    return before.eta, after.eta, before.speed, after.speed


def test_eta_survives_a_linux_suspend() -> None:
    """Linux: the monotonic clock stops during a suspend, the wall clock does not."""
    eta_before, eta_after, speed_before, speed_after = eta_around_a_gap(
        mono_gap=0.5, wall_gap=3600.0
    )
    assert speed_after == pytest.approx(speed_before, rel=0.01)
    assert eta_after == pytest.approx(eta_before - 3.0 / 1.0, abs=2.0)  # 3 s more of 2x media


def test_eta_survives_a_suspend_that_both_clocks_count() -> None:
    """An OS whose monotonic clock counts the suspend (an interval > MAX_INTERVAL)."""
    eta_before, eta_after, speed_before, speed_after = eta_around_a_gap(
        mono_gap=3600.0, wall_gap=3600.0
    )
    assert speed_after == pytest.approx(speed_before, rel=0.01)
    assert eta_after == pytest.approx(eta_before - 3.0, abs=2.0)
    assert MAX_INTERVAL < 3600.0


def test_a_short_stall_is_counted_but_a_wall_clock_change_is_not() -> None:
    _, _eta_after, _, speed_after = eta_around_a_gap(mono_gap=0.5, wall_gap=-7200.0)
    assert speed_after == pytest.approx(2.0, rel=0.01)
    _, _, _, slow = eta_around_a_gap(mono_gap=20.0, wall_gap=20.0)
    assert slow < 2.0  # 20 s for one block of progress is real (slow) progress


def test_paused_time_is_not_counted() -> None:
    tracker = ProgressTracker(ENCODE, expected_duration=1000.0)
    tracker.start_step(0)
    media = feed(tracker, start=0.0, stop=60.0, speed=2.0)
    before = tracker.snapshot()
    tracker.pause()
    tracker.resume()
    # Ten minutes later on both clocks: the paused time must not count.
    feed(tracker, start=660.0, stop=662.0, speed=2.0, media0=media + 1.0)
    after = tracker.snapshot()
    assert after.speed == pytest.approx(2.0, rel=0.01)
    assert before.eta is not None
    assert after.eta == pytest.approx(before.eta - 3.0, abs=2.0)
    assert tracker.active_time == pytest.approx(62.0, abs=0.6)


def test_ffmpeg_averages_are_not_used_after_a_pause() -> None:
    tracker = ProgressTracker(ENCODE, expected_duration=100.0)
    tracker.start_step(0)
    tracker.update(ProgressBlock(out_time=0.0, speed=5.0), mono=0, wall=0)
    tracker.pause()
    tracker.resume()
    progress = tracker.update(ProgressBlock(out_time=1.0, speed=0.1), mono=100, wall=100)
    assert progress.speed is None  # FFmpeg's 0.1x includes the pause; ours is not known yet


def test_analyse_steps_have_no_frame_rate() -> None:
    steps = [step("analyse", 0.05), step("encode", 1.0), step("finalize", 0.0)]
    tracker = ProgressTracker(steps, expected_duration=10.0)
    tracker.start_step(0)
    tracker.update(ProgressBlock(out_time=0.0, frame=0, fps=0.0), mono=0, wall=0)
    progress = tracker.update(ProgressBlock(out_time=5.0, frame=0, fps=0.0), mono=1, wall=1)
    assert progress.fps is None
    assert progress.speed == pytest.approx(5.0)
    assert progress.eta is not None


def test_output_size_keeps_the_last_known_value() -> None:
    tracker = ProgressTracker(ENCODE, expected_duration=10.0)
    tracker.start_step(0)
    tracker.update(ProgressBlock(out_time=1.0, total_size=1000), mono=0, wall=0)
    assert tracker.update(ProgressBlock(out_time=2.0), mono=1, wall=1).output_size == 1000


def test_no_weights_and_no_steps() -> None:
    tracker = ProgressTracker([step("finalize", 0.0), step("finalize", 0.0)], 10.0)
    tracker.start_step(1)
    assert tracker.percent == 50.0
    empty = ProgressTracker([], 10.0)
    assert empty.start_step(0).step_kind is None
    assert empty.update(ProgressBlock(out_time=1.0), mono=0, wall=0).percent == 0.0
