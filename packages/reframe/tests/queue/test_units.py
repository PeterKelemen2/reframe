"""Small parts of the queue: the watchdog, loudnorm, failure texts, the job log, output checks,
files and process trees."""

from __future__ import annotations

import errno
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from unittest import mock

import psutil
import pytest

from reframe import fsretry
from reframe.definitions import load_definitions
from reframe.events import EventBus
from reframe.models import (
    ExternalSubtitle,
    JobLogEvent,
    PlanFile,
    PlanStep,
    SubtitleOutputTrack,
    TrackMetadata,
)
from reframe.queue import files, loudnorm, runner
from reframe.queue.errors import UnknownJobError, exit_text, stderr_reason
from reframe.queue.logs import JobLog
from reframe.queue.process import resume_tree, suspend_tree
from reframe.queue.verify import check_output, expected_streams
from reframe.queue.watchdog import StepWatch, tree_cpu_seconds
from reframe.tools import RunResult, crashed
from reframe_testing import fake_tools as ft

from .conftest import draft, recorded


def test_stall_needs_no_progress_no_output_and_no_cpu() -> None:
    watch = StepWatch(stall_after=10.0, time_limit=None, max_tick=2.0)
    assert watch.tick(0.0, 0.0, paused=False) is None
    for t in range(1, 10):
        assert watch.tick(float(t), 0.0, paused=False) is None
    assert watch.tick(10.0, 0.0, paused=False) == "stalled"
    busy = StepWatch(stall_after=3.0, time_limit=None, max_tick=2.0)
    busy.tick(0.0, 0.0, paused=False)
    for t in range(1, 20):  # one core busy: never stalled
        assert busy.tick(float(t), float(t), paused=False) is None
    quiet = StepWatch(stall_after=3.0, time_limit=None, max_tick=2.0)
    quiet.tick(0.0, None, paused=False)
    for t in range(1, 20):
        quiet.activity()  # progress or a stderr line each tick
        assert quiet.tick(float(t), None, paused=False) is None


def test_a_busy_step_that_does_not_exit_after_its_last_block_is_stopped() -> None:
    watch = StepWatch(stall_after=100.0, time_limit=None, max_tick=2.0, exit_grace=3.0)
    watch.tick(0.0, 0.0, paused=False)
    assert watch.tick(1.0, 1.0, paused=False) is None
    watch.ended()
    verdicts = []
    for t in range(2, 6):  # one core busy and a line each tick
        watch.activity()
        verdicts.append(watch.tick(float(t), float(t), paused=False))
    assert verdicts == [None, None, "no_exit", "no_exit"]


def test_watchdog_is_sleep_aware_and_ignores_pauses() -> None:
    watch = StepWatch(stall_after=10.0, time_limit=None, max_tick=2.0)
    watch.tick(0.0, 0.0, paused=False)
    assert watch.tick(3600.0, 0.0, paused=False) is None  # a system sleep: one short tick
    assert watch.idle == 2.0
    for t in range(3601, 3700):
        assert watch.tick(float(t), 0.0, paused=True) is None
    assert watch.idle == 0.0
    assert watch.active == 2.0


def test_short_step_time_limit() -> None:
    watch = StepWatch(stall_after=None, time_limit=5.0, max_tick=1.0)
    watch.tick(0.0, None, paused=False)
    verdicts = [watch.tick(float(t), float(t), paused=False) for t in range(1, 6)]
    assert verdicts == [None, None, None, None, "timeout"]


def test_tree_cpu_seconds() -> None:
    assert (tree_cpu_seconds(os.getpid()) or 0) > 0
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    assert tree_cpu_seconds(proc.pid) is None


SILENT = """[Parsed_loudnorm_0 @ 0x7f5668002bc0]
{
\t"input_i" : "-inf",
\t"input_tp" : "-inf",
\t"input_lra" : "0.00",
\t"input_thresh" : "-70.00",
\t"output_i" : "-inf",
\t"output_tp" : "-inf",
\t"output_lra" : "0.00",
\t"output_thresh" : "-70.00",
\t"normalization_type" : "linear",
\t"target_offset" : "inf"
}
[out#0/null @ 0x55ec00980640] video:0KiB audio:1504KiB
"""


def test_loudnorm_of_a_silent_track_is_clamped() -> None:
    """The real block of a silent track, as FFmpeg prints it."""
    [block] = loudnorm.parse_blocks(SILENT)
    clamped, notes = loudnorm.clamp(block)
    assert clamped["input_i"] == "-99.00"
    assert clamped["input_tp"] == "-99.00"
    assert clamped["target_offset"] == "0.00"  # not 99: that amplifies noise to full scale
    assert clamped["input_lra"] == "0.00"
    assert clamped["input_thresh"] == "-70.00"
    assert clamped["output_i"] == "-inf"  # not read by the second pass
    assert len(notes) == 3


def test_loudnorm_clamps_finite_values_and_reads_nan() -> None:
    block = {"input_i": "5.0", "input_tp": "-120", "input_lra": "nan", "target_offset": "-inf"}
    clamped, _ = loudnorm.clamp(block)
    assert clamped == {
        "input_i": "0.00",
        "input_tp": "-99.00",
        "input_lra": "0.00",
        "target_offset": "0.00",  # any infinite offset: no gain
    }
    assert loudnorm.clamp({"input_i": "-21.83"}) == ({"input_i": "-21.83"}, [])


def test_loudnorm_errors() -> None:
    assert loudnorm.parse_blocks("no json here") == []
    with pytest.raises(loudnorm.MeasureError):
        loudnorm.parse_blocks('{ "input_i" : "-1", }')
    with pytest.raises(loudnorm.MeasureError):
        loudnorm.clamp({"input_i": "loud"})


def test_stderr_reason_picks_the_cause() -> None:
    nan = [
        "Stream mapping:",
        "  Stream #0:1 -> #0:0 (aac (native) -> aac (native))",
        "[aac @ 0x55ae00dbb400] Input contains (near) NaN/+-Inf",
        "[aost#0:0/aac @ 0x55ae00e07f40] [enc:aac @ 0x55ae00d96340] Error submitting audio "
        "frame to the encoder",
        "[aost#0:0/aac @ 0x55ae00e07f40] Task finished with error code: -22 (Invalid argument)",
        "Conversion failed!",
    ]
    assert stderr_reason(nan) == (
        "Input contains (near) NaN/+-Inf; Error submitting audio frame to the encoder"
    )
    full = ["[out#0/matroska @ 0x1] Error writing trailer: No space left on device", "x"]
    assert stderr_reason(full) == "No space left on device: the disk is full."
    assert stderr_reason(["Some plain last line", "Conversion failed!"]) == "Some plain last line"
    assert stderr_reason(["", "Conversion failed!"]) is None
    assert stderr_reason([]) is None
    assert stderr_reason(["Error: " + "x" * 400])[-1:] == "…"  # type: ignore[index]


def test_stderr_reason_names_the_nvenc_session_limit() -> None:
    capture = ft.captures()["detect_hevc_nvenc_session_limit"]
    assert capture.stderr is not None
    lines = (ft.DATA_DIR / capture.stderr).read_text(encoding="utf-8").splitlines()
    assert stderr_reason(lines) == (
        "Every NVENC session of the GPU is in use by other programs (GeForce cards run only a "
        "few at once). Run the job again when they finish."
    )


def test_exit_text() -> None:
    assert exit_text(1) == "exit code 1"
    assert exit_text(-11) == "signal 11 (SIGSEGV)"
    assert exit_text(-99) == "signal 99"
    assert exit_text(None) == "no exit code"
    assert exit_text(0xC0000005) == "exit code 0xC0000005"
    assert str(UnknownJobError("x")) == "no job 'x' in the queue"


def test_a_signal_or_a_windows_exception_is_a_crash() -> None:
    assert [crashed(code) for code in (-11, 0xC0000005, 0xC00000FD, 0xC0000409)] == [True] * 4
    assert [crashed(code) for code in (None, 0, 1, 255, 0x8000_0003)] == [False] * 5


def test_ffmpegs_own_error_codes_on_windows_are_not_crashes() -> None:
    # FFmpeg exits with its AVERROR code; Windows reports it as an unsigned 32-bit number.
    codes = (-22 & 0xFFFFFFFF, 0xDFB9B0BB, 0xDEB8AABE, 0xCFCFCB08, 0xBEBBB1B7)
    assert [crashed(code) for code in codes] == [False] * len(codes)


@pytest.mark.parametrize("returncode", [-22 & 0xFFFFFFFF], ids=["windows-averror"])
def test_an_ffmpeg_error_exit_on_windows_is_a_failure_not_a_crash(returncode: int) -> None:
    step = PlanStep(kind="encode", tool="ffmpeg")
    result = RunResult(returncode=returncode, stdout=b"", stderr=b"", duration=1.0)
    assert runner._failure(step, result, ["title=Chapter 4"]) == (
        "The encode failed (exit code 0xFFFFFFEA): title=Chapter 4"
    )


@pytest.mark.parametrize(
    ("returncode", "error"),
    [
        (-11, "ffmpeg crashed during pass 2 (signal 11 (SIGSEGV))."),
        (0xC0000005, "ffmpeg crashed during pass 2 (exit code 0xC0000005)."),
        (1, "Pass 2 failed (exit code 1): title=Chapter 4"),
    ],
    ids=["signal", "windows-exception", "exit-code"],
)
def test_the_last_line_is_the_reason_of_a_failure_not_of_a_crash(
    returncode: int, error: str
) -> None:
    step = PlanStep(kind="pass2", tool="ffmpeg")
    result = RunResult(returncode=returncode, stdout=b"", stderr=b"", duration=1.0)
    assert runner._failure(step, result, ["title=Chapter 4"]) == error


@pytest.mark.anyio
async def test_job_log_rate_limit_and_file(tmp_path: Path) -> None:
    bus = EventBus()
    sub = bus.subscribe()
    joblog = JobLog(tmp_path / "logs" / "j.log", "j", bus, interval=60.0, max_lines=3)
    joblog.open("header")
    for n in range(10):
        joblog.write(f"line {n}")
    joblog.close()
    event = sub.get_nowait()
    assert isinstance(event, JobLogEvent)
    assert event.lines == ["line 7", "line 8", "line 9"]
    assert event.dropped == 8  # the header and lines 0-6
    text = (tmp_path / "logs" / "j.log").read_text(encoding="utf-8")
    assert text.splitlines() == ["header", *(f"line {n}" for n in range(10))]


@pytest.mark.anyio
async def test_job_log_timer_and_a_broken_file(tmp_path: Path) -> None:
    bus = EventBus()
    sub = bus.subscribe()
    folder = tmp_path / "file-not-folder"
    folder.write_text("x")
    joblog = JobLog(folder / "j.log", "j", bus, interval=0.01)
    joblog.open("header")  # the folder cannot be made: events only
    joblog.note("a note")
    async with sub:
        first = await anext(sub)
    assert isinstance(first, JobLogEvent)
    assert first.lines[0] == "header"
    assert first.lines[1].endswith("a note")
    joblog.flush_file()
    joblog.close()


def test_expected_streams_and_languages(tmp_path: Path) -> None:
    source = recorded("multitrack.mkv", tmp_path / "s.mkv")
    defs = load_definitions()
    job = draft(source, tmp_path / "o.mkv")
    job.audio[1].metadata.language = "hu"
    job.subtitles[2].action = "burn"
    job.subtitles.append(
        SubtitleOutputTrack(
            source=ExternalSubtitle(path=tmp_path / "x.srt", language="de"),
            metadata=TrackMetadata(),
        )
    )
    kinds = [(e.kind, e.language) for e in expected_streams(job, source, defs.containers["mkv"])]
    assert kinds == [
        ("video", "und"),
        ("audio", "jpn"),
        ("audio", "hun"),
        ("audio", "eng"),
        ("subtitle", "eng"),
        ("subtitle", "eng"),
        ("subtitle", "ger"),
    ]
    mp4 = expected_streams(job, source, defs.containers["mp4"])
    assert mp4[-1].language == "deu"


def test_check_output_names_each_difference(tmp_path: Path) -> None:
    source = recorded("multitrack.mkv", tmp_path / "s.mkv")
    defs = load_definitions()
    job = draft(source, tmp_path / "o.mkv")
    assert check_output(job, source, source, defs) == []
    output = source.model_copy(deep=True)
    output.audio.pop()
    output.subtitles[0].language = "fre"
    assert check_output(job, source, output, defs) == [
        "3 audio tracks expected, 2 found",
        "subtitle track 1: language eng expected, fre found",
    ]
    no_video = source.model_copy(update={"video": []}, deep=True)
    assert check_output(job, no_video, no_video, defs) == []
    job.audio[0].source_stream = 99  # a stream the source lacks: und
    assert "audio track 1: language und expected, jpn found" in check_output(
        job, source, source, defs
    )


def test_rename_no_replace_posix(tmp_path: Path) -> None:
    a, b = tmp_path / "a.part.mkv", tmp_path / "a.mkv"
    a.write_text("new")
    files.rename_no_replace(a, b)
    assert b.read_text() == "new"
    assert not a.exists()
    a.write_text("newer")
    with pytest.raises(FileExistsError):
        files.rename_no_replace(a, b)
    assert b.read_text() == "new"


def test_rename_without_hard_links(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """FAT, exFAT, some network shares: ``os.link`` fails, check-then-rename is used."""

    def no_link(src: Any, dst: Any) -> None:
        raise OSError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(files, "WINDOWS", False)
    monkeypatch.setattr(os, "link", no_link)
    a, b = tmp_path / "a.part.mkv", tmp_path / "a.mkv"
    a.write_text("new")
    files.rename_no_replace(a, b)
    assert b.read_text() == "new"
    a.write_text("again")
    with pytest.raises(FileExistsError):
        files.rename_no_replace(a, b)

    def broken_link(src: Any, dst: Any) -> None:
        raise OSError(errno.EIO, "I/O error")

    monkeypatch.setattr(os, "link", broken_link)
    with pytest.raises(OSError, match="I/O"):
        files.rename_no_replace(a, tmp_path / "c.mkv")


def test_windows_rename_retries_an_open_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows: ``os.rename`` refuses an existing target; an open target gives
    ``PermissionError`` (a sharing violation), which is tried again (mocked on Linux)."""
    monkeypatch.setattr(files, "WINDOWS", True)
    monkeypatch.setattr(fsretry, "WINDOWS", True)
    sleeps: list[float] = []
    monkeypatch.setattr(fsretry, "_sleep", sleeps.append)
    calls: list[str] = []
    failures = iter([True, True, False])

    def flaky(src: Any, dst: Any) -> None:
        calls.append(Path(dst).name)
        if next(failures):
            raise PermissionError(13, "The process cannot access the file")

    monkeypatch.setattr(os, "rename", flaky)
    files.rename_no_replace(tmp_path / "a", tmp_path / "b")
    assert calls == ["b"] * 3
    assert sleeps == [0.05, 0.1]


def test_remove_files_reports_problems(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    present = tmp_path / "x.txt"
    present.write_text("x")
    folder = tmp_path / "folder"
    folder.mkdir()
    problems = files.remove_files([present, tmp_path / "missing", folder])
    assert not present.exists()
    assert len(problems) == 1
    assert "folder" in problems[0]
    monkeypatch.setattr(fsretry, "WINDOWS", True)
    monkeypatch.setattr(fsretry, "_sleep", lambda s: None)
    locked = tmp_path / "locked.part.mkv"
    locked.write_text("x")
    original = Path.unlink
    attempts: list[Path] = []

    def unlink(self: Path, missing_ok: bool = False) -> None:
        attempts.append(self)
        if len(attempts) < 3:
            raise PermissionError(13, "The process cannot access the file")
        original(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink)
    assert files.remove_files([locked]) == []
    assert len(attempts) == 3
    assert not locked.exists()


def test_write_plan_files_uses_utf8_and_lf(tmp_path: Path) -> None:
    path = tmp_path / "m.part.chapters.txt"
    files.write_plan_files([PlanFile(path=path, content=";FFMETADATA1\ntitle=Ünnep\n")])
    assert path.read_bytes() == ";FFMETADATA1\ntitle=Ünnep\n".encode()


def test_suspend_and_resume_a_real_tree() -> None:
    code = (
        "import subprocess, sys, time; "
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); time.sleep(30)"
    )
    proc = subprocess.Popen([sys.executable, "-c", code])
    try:
        root = psutil.Process(proc.pid)
        deadline = time.monotonic() + 10
        while not root.children() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert suspend_tree(root) == 2
        if sys.platform != "win32":
            deadline = time.monotonic() + 10
            while root.status() != psutil.STATUS_STOPPED and time.monotonic() < deadline:
                time.sleep(0.02)
            assert root.status() == psutil.STATUS_STOPPED
            assert root.children()[0].status() == psutil.STATUS_STOPPED
        assert resume_tree(root) == 2
    finally:
        for p in [*psutil.Process(proc.pid).children(recursive=True)]:
            p.kill()
        proc.kill()
        proc.wait()
    assert suspend_tree(root) == 0
    assert resume_tree(root) == 0


def test_suspend_order_with_mocked_psutil() -> None:
    """The Windows path is the same psutil calls (``NtSuspendProcess``); the order matters:
    root first on suspend (no new children), root last on resume."""
    order: list[str] = []
    child = mock.Mock(spec=psutil.Process)
    child.suspend.side_effect = lambda: order.append("child.suspend")
    child.resume.side_effect = lambda: order.append("child.resume")
    gone = mock.Mock(spec=psutil.Process)
    gone.suspend.side_effect = psutil.NoSuchProcess(1)
    gone.resume.side_effect = psutil.NoSuchProcess(1)
    root = mock.Mock(spec=psutil.Process)
    root.suspend.side_effect = lambda: order.append("root.suspend")
    root.resume.side_effect = lambda: order.append("root.resume")
    root.children.return_value = [child, gone]
    assert suspend_tree(root) == 2
    assert resume_tree(root) == 2
    assert order == ["root.suspend", "child.suspend", "child.resume", "root.resume"]
    root.children.side_effect = psutil.AccessDenied(1)
    assert suspend_tree(root) == 1
