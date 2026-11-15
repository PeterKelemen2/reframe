"""Fault injection for every failure path of the job runner, with the fake ffmpeg."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from reframe.metadata.header import HeaderEditResult
from reframe.models import (
    AverageBitrate,
    HeaderEdit,
    JobSettings,
    JobState,
    QueueJob,
    Severity,
    ToolStatus,
    TrackHeaderEdit,
)
from reframe.probe import ProbeError, ProbeErrorKind
from reframe_testing import fake_tools as ft

from .conftest import Harness, encode_rule, tool_set

pytestmark = pytest.mark.anyio

POSIX = os.name != "nt"
DISK_FULL = (
    "[out#0/matroska @ 0x55d0] Error writing trailer: No space left on device\n"
    "[out#0/matroska @ 0x55d0] Error closing file: No space left on device\n"
    "Conversion failed!\n"
)
SILENT_BLOCK = (
    "[Parsed_loudnorm_0 @ 0x7f56]\n{\n"
    '\t"input_i" : "-inf",\n\t"input_tp" : "-inf",\n\t"input_lra" : "0.00",\n'
    '\t"input_thresh" : "-70.00",\n\t"output_i" : "-inf",\n\t"output_tp" : "-inf",\n'
    '\t"output_lra" : "0.00",\n\t"output_thresh" : "-70.00",\n'
    '\t"normalization_type" : "linear",\n\t"target_offset" : "inf"\n}\n'
)


def chapters_and_two_pass(h: Harness, name: str = "Movie") -> tuple[JobSettings, Path, list[Path]]:
    """A job with generated chapters and 2-pass x264. The fake does not write the statistics
    files, so they are made here."""
    job = h.job(name, rate_control=AverageBitrate(kbps=500, two_pass=True))
    job.chapters.generate_every = 0.02
    plan = h.plan(job)
    assert len(plan.files) == 1
    assert plan.temp_files
    for path in plan.temp_files:
        path.write_text("stats")
    return job, plan.output_tmp, [plan.files[0].path, *plan.temp_files]


def assert_failed_run(h: Harness, job_id: str, *, error_part: str) -> None:
    states = h.states(job_id)
    assert states == [(None, "waiting"), ("waiting", "running"), ("running", "failed")]
    [end] = [e for e in h.events_of(job_id) if e.type == "job.state" and e.state.value == "failed"]
    assert error_part in (end.error or "")
    kinds = h.kinds(job_id)
    assert kinds[:3] == ["job.state", "job.state", "job.progress"]
    assert kinds[-1] == "job.state"
    assert "job.log" in kinds
    assert h.leftovers() == []


@pytest.mark.parametrize("policy", ["delete", "keep"])
async def test_crash_mid_encode(harness: Harness, policy: str) -> None:
    h = harness
    h.settings.output.partial_file = policy  # type: ignore[assignment]
    job, part, others = chapters_and_two_pass(h)
    chapters = others[0]
    h.scenario(
        ft.Rule(tool="ffmpeg", argv_has=["-pass", "1"], actions=[ft.progress(blocks=2)]),
        encode_rule(
            {"stderr_file": str(chapters)},  # the plan file exists while the steps run
            ft.progress(blocks=3, end=False),
            ft.write_output(4096),
            ft.crash(signal="SIGSEGV"),
        ),
    )
    ended = await h.run_one(job)
    assert ended.state is JobState.FAILED
    if POSIX:
        assert ended.error == "ffmpeg crashed during pass 2 (signal 11 (SIGSEGV))."
    else:
        assert ended.error == "ffmpeg crashed during pass 2 (exit code 0xC0000005)."
    assert_failed_run(h, ended.id, error_part="pass 2")
    assert part.exists() is (policy == "keep")
    assert not any(p.exists() for p in others)  # files and temp_files: always removed
    log = h.log_text(ended.id)
    assert ";FFMETADATA1" in log
    assert "$ " + str(h.fake.ffmpeg) in log
    assert "Step 2/3 (pass2)" in log
    assert "Job failed after" in log
    if policy == "keep":
        assert f"The partial output is kept: {part}" in log
    progress = [e for e in h.events_of(ended.id) if e.type == "job.progress"]
    assert max(e.progress.percent for e in progress) >= 40.0


async def test_non_zero_exit_names_the_error(harness: Harness) -> None:
    h = harness
    h.scenario(
        encode_rule(
            ft.stderr(
                "[vost#0:0/libx264 @ 0x55d0] Error while opening encoder - maybe incorrect "
                "parameters such as bit_rate, rate, width or height\nConversion failed!\n"
            ),
            exit_code=1,
        )
    )
    ended = await h.run_one(h.job())
    assert ended.error == (
        "The encode failed (exit code 1): Error while opening encoder - maybe incorrect "
        "parameters such as bit_rate, rate, width or height"
    )
    assert_failed_run(h, ended.id, error_part="Error while opening encoder")
    assert "Conversion failed!" in h.log_text(ended.id)
    assert "Step 1/2 ended: exit code 1" in h.log_text(ended.id)


async def test_disk_full(harness: Harness) -> None:
    h = harness
    job = h.job()
    part = h.plan(job).output_tmp
    h.scenario(
        encode_rule(
            ft.progress(blocks=2), ft.write_output(1000), ft.stderr(DISK_FULL), exit_code=228
        )
    )
    ended = await h.run_one(job)
    assert (
        ended.error
        == "The encode failed (exit code 228): No space left on device: the disk is full."
    )
    assert_failed_run(h, ended.id, error_part="No space left on device")
    assert not part.exists()


async def test_missing_output(harness: Harness) -> None:
    h = harness
    h.scenario(encode_rule(ft.progress(blocks=2)))
    ended = await h.run_one(h.job())
    assert ended.error == (
        "The encode ended without an error but wrote no output (Movie.part.mkv is missing)."
    )
    assert_failed_run(h, ended.id, error_part="no output")
    assert not (h.tmp / "out" / "Movie.mkv").exists()


async def test_tool_that_cannot_start(harness: Harness) -> None:
    h = harness
    h.tools.tools = tool_set(h.tmp / "no-such-ffmpeg")
    ended = await h.run_one(h.job())
    assert ended.state is JobState.FAILED
    assert ended.error is not None
    assert ended.error.startswith("The encode could not start ffmpeg:")


async def test_hang_is_stopped_by_the_stall_watchdog(harness: Harness) -> None:
    h = harness
    h.queue._runner._stall_after = 0.4
    job = h.job()
    part = h.plan(job).output_tmp
    h.scenario(encode_rule(ft.progress(blocks=2, end=False), ft.write_output(100), ft.hang()))
    ended = await h.run_one(job)
    assert ended.error == (
        "FFmpeg made no progress for 0.4 seconds (no output, no CPU use) and was stopped."
    )
    assert_failed_run(h, ended.id, error_part="no progress")
    assert not part.exists()
    assert "Step 1/2 ended: stopped" in h.log_text(ended.id)


async def test_a_slow_step_that_prints_is_not_stalled(harness: Harness) -> None:
    h = harness
    h.queue._runner._stall_after = 0.3
    # A block every 0.1 s for 1.2 s: four times the stall limit.
    h.scenario(encode_rule(ft.progress(blocks=12, interval=0.1), ft.write_output(100)))
    ended = await h.run_one(h.job())
    assert ended.state is JobState.DONE


async def test_failing_analyse_step(harness: Harness) -> None:
    h = harness
    job = h.job()
    job.audio[0].loudness = "ebu_r128"
    h.scenario(
        ft.Rule(
            tool="ffmpeg",
            argv_contains=["print_format=json"],
            actions=[ft.stderr("[in#0 @ 0x1] Error opening input: Invalid data found\n")],
            exit_code=1,
        )
    )
    ended = await h.run_one(job)
    assert ended.error == (
        "Measuring the loudness failed (exit code 1): Error opening input: Invalid data found"
    )
    assert_failed_run(h, ended.id, error_part="loudness")
    assert not any("matroska" in call for call in h.fake.calls("ffmpeg"))  # no encode ran


async def test_analyse_without_a_result(harness: Harness) -> None:
    h = harness
    job = h.job()
    job.audio[0].loudness = "streaming"
    h.scenario(ft.Rule(tool="ffmpeg", argv_contains=["print_format=json"], actions=[]))
    ended = await h.run_one(job)
    assert ended.error == "Measuring the loudness printed 0 loudnorm result(s), 1 expected"


async def test_silent_track_values_are_clamped_for_the_encode(harness: Harness) -> None:
    h = harness
    job = h.job()
    job.audio[2].loudness = "ebu_r128"
    h.scenario(
        ft.Rule(
            tool="ffmpeg",
            argv_contains=["print_format=json"],
            actions=[ft.progress(blocks=2), ft.stderr(SILENT_BLOCK)],
        )
    )
    ended = await h.run_one(job)
    assert ended.state is JobState.DONE, ended.error
    [encode] = [call for call in h.fake.calls("ffmpeg") if "matroska" in call]
    [chain] = [arg for arg in encode if "loudnorm=" in arg]
    assert "measured_I=-99.00:measured_TP=-99.00:measured_LRA=0.00" in chain
    assert "measured_thresh=-70.00:offset=0.00:linear=true" in chain
    assert "values clamped into loudnorm's ranges" in h.log_text(ended.id)


def ietf_job(h: Harness) -> JobSettings:
    job = h.job()
    job.audio[1].metadata.language = "pt-BR"  # needs Matroska LanguageIETF: a header edit
    return job


def written_as_portuguese(h: Harness) -> None:
    """The re-probed output has what the job wrote: the header edit's language, and only the
    flags that :func:`draft` keeps."""
    portuguese = h.sources.source.model_copy(deep=True)
    for stream in [*portuguese.video, *portuguese.audio, *portuguese.subtitles]:
        for flag in ("hearing_impaired", "visual_impaired", "original"):
            setattr(stream.disposition, flag, False)
    portuguese.audio[1].language = "por"
    portuguese.audio[1].language_ietf = "pt-BR"
    h.sources.output = lambda path: portuguese


async def test_the_fixup_writes_the_part_file_without_any_mkvtoolnix(harness: Harness) -> None:
    h = harness
    assert h.tools.tools.mkvpropedit.status is not ToolStatus.FOUND
    job = ietf_job(h)
    part = h.plan(job).output_tmp
    written_as_portuguese(h)
    ended = await h.run_one(job)
    assert (ended.state, ended.error) == (JobState.DONE, None)
    assert h.writer.edits == [
        HeaderEdit(
            path=part,
            tracks=[
                TrackHeaderEdit(track_type="audio", number=2, language="por", language_ietf="pt-BR")
            ],
        )
    ]
    [encode] = h.fake.calls("ffmpeg")  # the header edit started no program
    assert "matroska" in encode
    log = h.log_text(ended.id)
    assert f"header_edit {part} audio 2: language=por language_ietf=pt-BR" in log
    assert "Step 2/3 ended: written after" in log


async def test_a_failed_fixup_fails_the_job_and_removes_the_part(harness: Harness) -> None:
    h = harness
    job = ietf_job(h)
    part = h.plan(job).output_tmp
    h.writer.result = HeaderEditResult("failed", "header.write_error", "No space left on device")
    ended = await h.run_one(job)
    assert ended.error == (
        "Writing the Matroska header of Movie.part.mkv failed: No space left on device. The file "
        "holds either all its old values or all the new ones."
    )
    assert_failed_run(h, ended.id, error_part="Writing the Matroska header")
    assert "Step 2/3 ended: failed (header.write_error): No space left on device" in h.log_text(
        ended.id
    )
    assert not part.exists()


async def test_a_refused_fixup_fails_the_job(harness: Harness) -> None:
    h = harness
    job = ietf_job(h)
    part = h.plan(job).output_tmp
    h.writer.result = HeaderEditResult("refused", "header.no_room", "The SeekHead has no room.")
    ended = await h.run_one(job)
    assert ended.state is JobState.FAILED
    assert ended.error == (
        "Reframe cannot edit the Matroska header of Movie.part.mkv: The SeekHead has no room. "
        "Nothing was changed in the file."
    )
    assert not part.exists()


async def test_a_writer_that_raises_is_an_internal_error(harness: Harness) -> None:
    h = harness
    h.writer.raises = RuntimeError("a bug")
    ended = await h.run_one(ietf_job(h))
    assert ended.state is JobState.FAILED
    assert ended.error == "Internal error: RuntimeError: a bug"


async def test_a_cancel_during_the_fixup_waits_for_the_write(harness: Harness) -> None:
    """The worker thread cannot be stopped: the ``.part`` file is removed only after the write
    ended, never under it."""
    h = harness
    h.writer.hold = True
    job = ietf_job(h)
    part = h.plan(job).output_tmp
    added = await h.queue.add(job)
    h.queue.start()
    await h.wait_for(h.writer.started.is_set)
    cancel = asyncio.ensure_future(h.queue.cancel(added.id))
    await asyncio.sleep(0.2)
    assert not cancel.done()
    assert part.exists()
    h.writer.release()
    await cancel
    ended = h.queue.get(added.id)
    assert ended is not None
    assert (ended.state, ended.error) == (JobState.CANCELLED, None)
    assert h.writer.finished.is_set()
    assert not part.exists()
    note = "The job is cancelled while Reframe is writing the header of Movie.part.mkv"
    assert f"{note}: it is let finish" in h.log_text(added.id)


async def test_reprobe_mismatch(harness: Harness) -> None:
    h = harness
    job = h.job()
    part = h.plan(job).output_tmp
    short = h.sources.source.model_copy(deep=True)
    short.audio.pop()
    short.subtitles[1].language = "ger"
    h.sources.output = lambda path: short
    ended = await h.run_one(job)
    assert ended.error == (
        "The output does not match the plan: 3 audio tracks expected, 2 found; subtitle track "
        "2: language eng expected, ger found."
    )
    assert_failed_run(h, ended.id, error_part="does not match")
    assert not part.exists()
    assert not (h.tmp / "out" / "Movie.mkv").exists()  # a bad output never gets the name
    assert (part, False) in h.sources.calls  # probed again, not from the cache


async def test_reprobe_fails(harness: Harness) -> None:
    h = harness
    h.sources.output = lambda path: ProbeError(
        path, ProbeErrorKind.FAILED, "ffprobe cannot read it.", "Invalid data found"
    )
    ended = await h.run_one(h.job())
    assert ended.error == "The output cannot be read: ffprobe cannot read it. (Invalid data found)"


async def test_collision_auto_rename(harness: Harness) -> None:
    h = harness
    final = h.tmp / "out" / "Movie.mkv"
    final.write_text("the user's file")
    (h.tmp / "out" / "Movie (1).mkv").write_text("another")
    ended = await h.run_one(h.job())
    assert ended.state is JobState.DONE
    assert ended.output_path == h.tmp / "out" / "Movie (2).mkv"
    assert final.read_text() == "the user's file"
    assert [i.code for i in ended.issues if i.code.startswith("output.")] == ["output.renamed"]
    assert "Movie.mkv exists: saved as Movie (2).mkv" in h.log_text(ended.id)


async def test_collision_overwrite(harness: Harness) -> None:
    h = harness
    h.settings.output.collision = "overwrite"
    final = h.tmp / "out" / "Movie.mkv"
    final.write_text("old")
    ended = await h.run_one(h.job())
    assert ended.state is JobState.DONE
    assert ended.output_path == final
    assert final.read_bytes() == b"\0" * 1024  # the fake's output
    assert not (h.tmp / "out" / "Movie.part.mkv").exists()


async def test_collision_ask_at_add_time(harness: Harness) -> None:
    h = harness
    h.settings.output.collision = "ask"
    (h.tmp / "out" / "Movie.mkv").write_text("old")
    added = await h.queue.add(h.job())
    assert added.state is JobState.FAILED
    assert added.error == "The job has errors: Movie.mkv already exists."
    [issue] = [i for i in added.issues if i.severity is Severity.ERROR]
    assert issue.code == "output.exists"
    assert [f.label for f in issue.fixes] == [
        "Save as Movie (1).mkv",
        "Always overwrite (Settings → Output)",
    ]
    assert h.states(added.id) == [(None, "failed")]


async def test_collision_ask_when_the_name_is_taken_during_the_encode(harness: Harness) -> None:
    """The complete encode is kept as the ``.part`` file."""
    h = harness
    h.settings.output.collision = "ask"
    job = h.job()
    part = h.plan(job).output_tmp
    h.scenario(
        encode_rule(ft.progress(blocks=1, end=False), ft.progress(blocks=3), ft.write_output())
    )
    added = await h.queue.add(job)
    h.queue.start()
    await h.first_event(added.id, "job.progress")
    await h.queue.pause(added.id)
    (h.tmp / "out" / "Movie.mkv").write_text("appeared")
    await h.queue.resume(added.id)
    [ended] = await h.queue.wait([added.id])
    assert ended.state is JobState.FAILED
    assert ended.error == (
        "Movie.mkv already exists (Settings → Output asks what to do, and a queue cannot "
        "ask). The finished encode is kept as Movie.part.mkv."
    )
    assert "output.exists" in [i.code for i in ended.issues]
    assert part.stat().st_size == 1024
    assert (h.tmp / "out" / "Movie.mkv").read_text() == "appeared"


async def test_source_that_cannot_be_probed(harness: Harness) -> None:
    h = harness
    job = h.job()
    job.source.path = h.tmp / "media" / "missing.mkv"
    added = await h.queue.add(job)
    assert added.state is JobState.FAILED
    assert [i.code for i in added.issues] == ["queue.source_unreadable"]
    assert added.error == (
        "The job has errors: The source missing.mkv cannot be read: The file does not exist."
    )


async def test_source_gone_before_the_run(harness: Harness) -> None:
    h = harness
    added = await h.queue.add(h.job())
    h.source_path.unlink()
    good = h.sources.source
    h.sources.source = good.model_copy(
        update={"ref": good.ref.model_copy(update={"path": h.tmp / "elsewhere.mkv"})}
    )
    h.queue.start()
    [ended] = await h.queue.wait([added.id])
    assert ended.state is JobState.FAILED
    assert ended.error is not None
    assert "cannot be read" in ended.error
    assert h.states(ended.id)[-1] == ("running", "failed")


async def test_encoder_checking_waits_for_detection(harness: Harness) -> None:
    h = harness
    from reframe.models import EncoderState

    from .conftest import all_caps

    final = h.caps.snapshot
    h.caps.snapshot = all_caps(state=EncoderState.CHECKING)
    h.caps.final = final
    added = await h.queue.add(h.job())
    assert added.state is JobState.WAITING
    assert "encoder.checking" in [i.code for i in added.issues]
    h.queue.start()
    [ended] = await h.queue.wait([added.id])
    assert ended.state is JobState.DONE
    assert h.caps.waited == 1
    assert "encoder.checking" not in [i.code for i in ended.issues]
    assert "Waiting for the encoder detection" in h.log_text(ended.id)


async def test_encoder_unavailable_after_detection(harness: Harness) -> None:
    h = harness
    from reframe.models import EncoderState

    from .conftest import all_caps

    h.caps.snapshot = all_caps(state=EncoderState.CHECKING)
    gone = all_caps()
    gone.encoders["libx264"] = gone.encoders["libx264"].model_copy(
        update={"state": EncoderState.UNAVAILABLE, "reason": "not in this build"}
    )
    h.caps.final = gone
    ended = await h.run_one(h.job())
    assert ended.state is JobState.FAILED
    assert "encoder.unavailable" in [i.code for i in ended.issues]
    assert ended.error is not None
    assert "not in this build" in ended.error


async def test_plan_error_is_a_failure(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    from reframe.command import PlanError
    from reframe.queue import runner

    def refuse(*args: object, **kwargs: object) -> object:
        raise PlanError("a case validation does not know")

    monkeypatch.setattr(runner, "build_plan", refuse)
    ended = await harness.run_one(harness.job())
    assert ended.error == "The job cannot be planned: a case validation does not know"
    assert "queue.plan_failed" in [i.code for i in ended.issues]


async def test_internal_error_fails_only_the_job(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness

    async def broken(*args: object) -> object:
        raise RuntimeError("bug")

    monkeypatch.setattr(h.queue._runner, "run", broken)
    ended = await h.run_one(h.job())
    assert (ended.state, ended.error) == (JobState.FAILED, "Internal error: RuntimeError: bug")
    monkeypatch.undo()
    second = await h.run_one(h.job("Second"))
    assert second.state is JobState.DONE


async def test_unwritable_output_folder(harness: Harness) -> None:
    h = harness
    added = await h.queue.add(h.job())
    (h.tmp / "out").rmdir()
    (h.tmp / "out").write_text("now a file")  # the folder cannot be made
    h.queue.start()
    [ended] = await h.queue.wait([added.id])
    assert ended.state is JobState.FAILED
    assert ended.error is not None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
async def test_the_output_folder_is_created(harness: Harness) -> None:
    h = harness
    job = h.job()
    job.output.path = h.tmp / "out" / "Season 1" / "Movie.mkv"
    ended = await h.run_one(job)
    assert ended.state is JobState.DONE, ended.error
    assert ended.output_path == h.tmp / "out" / "Season 1" / "Movie.mkv"


@pytest.mark.parametrize(
    ("block", "error"),
    [
        (
            '{\n"input_i" : "-20.0"\n}\n',
            "The encode needs the measured value a0.input_tp, which is missing",
        ),
        (
            '{\n"input_i" : "loud"\n}\n',
            "Measuring the loudness failed: loudnorm printed input_i = 'loud', not a number",
        ),
    ],
)
async def test_unusable_loudnorm_results(harness: Harness, block: str, error: str) -> None:
    h = harness
    job = h.job()
    job.audio[0].loudness = "ebu_r128"
    h.scenario(
        ft.Rule(tool="ffmpeg", argv_contains=["print_format=json"], actions=[ft.stderr(block)])
    )
    ended = await h.run_one(job)
    assert (ended.state, ended.error) == (JobState.FAILED, error)


async def test_plan_files_that_cannot_be_written(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from reframe.queue import runner

    def refuse(plan: object) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(runner, "_write_files", refuse)
    ended = await harness.run_one(harness.job())
    assert ended.error == (
        "The output folder or the plan files cannot be written: [Errno 13] Permission denied"
    )


async def test_rename_that_fails(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    from reframe.queue import files

    h = harness
    h.settings.output.collision = "overwrite"

    def locked(source: Path, target: Path) -> None:
        raise PermissionError(13, "The process cannot access the file")

    monkeypatch.setattr(files, "replace_file", locked)
    ended = await h.run_one(h.job())
    assert ended.error == (
        "Movie.part.mkv could not be renamed to Movie.mkv: The process cannot access the file"
    )
    assert not (h.tmp / "out" / "Movie.part.mkv").exists()  # a failure: the policy deletes it


async def test_a_name_taken_during_the_rename_is_looked_up_again(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from reframe.queue import files

    h = harness
    real = files.rename_no_replace
    taken: list[Path] = []

    def race(source: Path, target: Path) -> None:
        if not taken:
            taken.append(target)
            target.write_text("someone was faster")
            raise FileExistsError(target)
        real(source, target)

    monkeypatch.setattr(files, "rename_no_replace", race)
    ended = await h.run_one(h.job())
    assert ended.output_path == h.tmp / "out" / "Movie (1).mkv"
    assert taken == [h.tmp / "out" / "Movie.mkv"]


async def test_cancel_while_preparing(harness: Harness) -> None:
    h = harness
    added = await h.queue.add(h.job())
    h.sources.delay = 5.0  # a probe that would take long: the cancel does not wait for it
    h.queue.start()
    await h.first_event(added.id, "job.state", state="running")
    await h.queue.cancel(added.id)
    assert h.queue.get(added.id).state is JobState.CANCELLED  # type: ignore[union-attr]
    assert h.fake.calls("ffmpeg") == []


async def test_close_before_a_scheduled_job_started(harness: Harness) -> None:
    h = harness
    added = await h.queue.add(h.job())
    h.queue.start()  # its task is created but has not run
    await h.queue.close()
    assert h.queue.get(added.id).state is JobState.WAITING  # type: ignore[union-attr]
    assert h.states(added.id) == [(None, "waiting")]


def test_durations_in_messages() -> None:
    from reframe.queue.runner import _duration

    assert _duration(600) == "10 minutes"
    assert _duration(60) == "1 minute"
    assert _duration(1) == "1 second"
    assert _duration(None) == "0 seconds"


def without_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    """The run-time guard is tested alone: validation reports the same case on its own."""
    from reframe.queue import runner

    monkeypatch.setattr(runner, "validate", lambda *args, **kwargs: [])


def assert_untouched(h: Harness, ended: QueueJob, source: Path, content: bytes) -> None:
    assert ended.state is JobState.FAILED
    assert "queue.writes_source" in [i.code for i in ended.issues]
    assert ended.error is not None
    assert "nothing was written or removed" in ended.error
    assert source.read_bytes() == content
    assert h.fake.calls("ffmpeg") == []


async def test_a_source_named_like_the_part_file(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The source is the job's ``.part`` file: the job must not write over or remove it."""
    from .conftest import draft, recorded

    h = harness
    without_validation(monkeypatch)
    source = h.tmp / "media" / "Foo.part.mkv"
    source.write_bytes(b"the only copy")
    h.sources.source = recorded("multitrack.mkv", source)
    ended = await h.run_one(draft(h.sources.source, h.tmp / "media" / "Foo.mkv"))
    assert_untouched(h, ended, source, b"the only copy")
    assert ended.error == (
        f"Foo.part.mkv is the source file itself ({source}): the job would write over or "
        "remove its source, so nothing was written or removed."
    )
    assert sorted(p.name for p in source.parent.iterdir()) == ["Foo.part.mkv", "Movie.Source.mkv"]


@pytest.mark.skipif(sys.platform == "win32", reason="symbolic links need privileges on Windows")
@pytest.mark.parametrize("which", ["final", "part"])
async def test_an_output_folder_that_links_to_the_source_folder(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, which: str
) -> None:
    """The output folder links to the source folder, so the output (or its ``.part`` file) is
    the source under another path."""
    from .conftest import draft, recorded

    h = harness
    without_validation(monkeypatch)
    h.settings.output.collision = "overwrite"
    link = h.tmp / "link"
    link.symlink_to(h.tmp / "media", target_is_directory=True)
    name = "Movie.Source.mkv" if which == "final" else "Clip.part.mkv"
    source = h.tmp / "media" / name
    source.write_bytes(b"the only copy")
    h.sources.source = recorded("multitrack.mkv", source)
    output = link / ("Movie.Source.mkv" if which == "final" else "Clip.mkv")
    ended = await h.run_one(draft(h.sources.source, output))
    assert_untouched(h, ended, source, b"the only copy")


def test_same_file_through_links_and_case(tmp_path: Path) -> None:
    from reframe.queue.files import remove_files, same_file

    real = tmp_path / "Real.mkv"
    real.write_text("x")
    assert same_file(real, tmp_path / "real.MKV")  # another spelling (case)
    assert same_file(real, tmp_path / "sub" / ".." / "Real.mkv")
    if sys.platform != "win32":
        (tmp_path / "link").symlink_to(tmp_path, target_is_directory=True)
        assert same_file(real, tmp_path / "link" / "Real.mkv")
        os.link(real, tmp_path / "hard.mkv")
        assert same_file(real, tmp_path / "hard.mkv")  # a hard link: the same file
    assert not same_file(real, tmp_path / "Other.mkv")
    assert remove_files([tmp_path / "REAL.mkv"], keep=real) == [
        f"{tmp_path / 'REAL.mkv'} is the source file, not removed"
    ]
    assert real.exists()
