"""``reframe encode`` against the in-memory fake queue."""

from __future__ import annotations

import asyncio
import io
import signal
from collections.abc import Sequence
from pathlib import Path

import pytest
from rich.console import Console

from reframe import cli
from reframe.cli import (
    EXIT_FAILED,
    EXIT_INTERRUPTED,
    EXIT_NOT_FOUND,
    EXIT_OK,
    EXIT_USAGE,
    EncodeView,
    progress_text,
)
from reframe.models import (
    JobProgress,
    JobSettings,
    JobState,
    QueueChangedEvent,
    QueueJob,
    Severity,
)
from reframe.models import ValidationIssue as Issue
from reframe.queue import UnknownJobError
from reframe.service import Reframe
from reframe_testing import fake_tools as ft

from .conftest import Queues, invoke, media_file, replay
from .fake_queue import FakeQueue

SEASON = "Show.S01.1080p.BluRay.x264-GRP"
EPISODES = [f"Show.S01E{n:02d}.Title.{n}.1080p.BluRay.x264-GRP.mkv" for n in (1, 2, 10)]


@pytest.fixture
def season(cli_env: ft.FakeTools, tmp_path: Path) -> Path:
    replay(cli_env, "multitrack")
    folder = tmp_path / "media" / SEASON
    for name in EPISODES:
        media_file(folder, name)
    return folder


def partial_files(folder: Path) -> list[Path]:
    return list(folder.glob("*.part.*"))


def outputs(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir() if not p.name.endswith("BluRay.x264-GRP.mkv"))


def test_a_season_folder_and_a_file(season: Path, queues: Queues, tmp_path: Path) -> None:
    movie = media_file(tmp_path / "media" / "Movie.2016.1080p.BluRay-GRP", "movie.mkv")
    result = invoke("encode", str(season), str(movie))
    assert result.exit_code == EXIT_OK, result.output
    out = result.stdout.splitlines()
    assert out[0] == "Preset: H.265 MKV 1080p"
    # One job per media file, in natural order (E10 after E02), each named by the template.
    assert out[1] == f"[1/4] {EPISODES[0]} → {season / 'Show.S01E01.Title.1.mkv'}"
    assert out[2] == f"[2/4] {EPISODES[1]} → {season / 'Show.S01E02.Title.2.mkv'}"
    assert out[3] == f"[3/4] {EPISODES[2]} → {season / 'Show.S01E10.Title.10.mkv'}"
    assert out[4] == f"[4/4] movie.mkv → {movie.parent / 'Movie.mkv'}"
    assert "Queued 4 jobs." in out
    assert "[1/4] running" in out
    assert "[1/4] 25.0% · 48.0 fps · 2.00x · ETA 0:00:06 · 244.1 KiB" in out
    assert any(line.startswith("[4/4] done in 0:00:0") for line in out)
    assert out[-1] == "Summary: 4 done, 0 failed, 0 cancelled, 0 not queued."
    assert outputs(season) == [
        "Show.S01E01.Title.1.mkv",
        "Show.S01E02.Title.2.mkv",
        "Show.S01E10.Title.10.mkv",
    ]
    assert (movie.parent / "Movie.mkv").exists()
    # Our jobs go first in the queue, and the runner takes only them.
    calls = queues.queue.calls
    assert calls == ["add"] * 4 + ["start job-1 job-2 job-3 job-4"]
    assert [job.position for job in queues.queue.list()] == [0, 1, 2, 3]


def test_a_file_with_errors_is_not_queued(
    cli_env: ft.FakeTools, queues: Queues, tmp_path: Path
) -> None:
    folder = tmp_path / "media" / SEASON
    files = [media_file(folder, name) for name in EPISODES[:2]]
    song = media_file(folder, "song.mkv")
    replay(cli_env, "multitrack", per_file={song: "cover-art"})
    result = invoke("encode", str(folder))
    assert result.exit_code == EXIT_FAILED, result.output
    out = result.stdout
    assert "[3/3] song.mkv → " in out
    assert "      not queued: 1 error, 0 warnings, 0 info" in out
    assert "error    song.mkv has no video track" in out
    assert "Queued 2 jobs." in out
    assert out.splitlines()[-1] == "Summary: 2 done, 0 failed, 0 cancelled, 1 not queued."
    assert len(queues.queue.list()) == 2
    assert all((folder / f.name.replace(".1080p.BluRay.x264-GRP", "")).exists() for f in files)


def test_a_file_that_cannot_be_probed_is_not_queued(
    cli_env: ft.FakeTools, queues: Queues, tmp_path: Path
) -> None:
    folder = tmp_path / "media" / SEASON
    media_file(folder, EPISODES[0])
    broken = media_file(folder, "broken.mkv")
    garbage = ft.Rule(
        tool="ffprobe",
        argv_has=[str(broken)],
        exit_code=1,
        actions=[ft.stderr(f"{broken}: Invalid data found when processing input\n")],
    )
    replay(cli_env, "multitrack", extra=(garbage,))
    result = invoke("encode", str(folder))
    assert result.exit_code == EXIT_FAILED, result.output
    assert "broken.mkv: not queued" in result.stdout
    assert "Summary: 1 done, 0 failed, 0 cancelled, 1 not queued." in result.stdout


def test_output_with_several_files_is_refused(season: Path, queues: Queues, tmp_path: Path) -> None:
    result = invoke("encode", str(season), "-o", str(tmp_path / "out.mkv"))
    assert result.exit_code == EXIT_USAGE
    assert result.stderr.startswith("error: -o/--output needs a single file, but there are 3")
    assert queues.made == []


def test_output_with_one_file(season: Path, queues: Queues, tmp_path: Path) -> None:
    out = tmp_path / "out" / "Pilot.mkv"
    out.parent.mkdir()
    result = invoke("encode", str(season / EPISODES[0]), "-o", str(out))
    assert result.exit_code == EXIT_OK, result.output
    assert out.exists()
    assert not (out.parent / "Pilot.part.mkv").exists()


def test_failed_job(season: Path, queues: Queues) -> None:
    queues.behaviour = lambda job: "fail" if "E02" in job.source.path.name else "done"
    result = invoke("encode", str(season))
    assert result.exit_code == EXIT_FAILED
    out = result.stdout
    assert "[2/3] failed: ffmpeg exited with code 1: Conversion failed!" in out
    assert f"log: {queues.log_dir / 'job-2.log'}" in out
    assert out.splitlines()[-1] == "Summary: 2 done, 1 failed, 0 cancelled, 0 not queued."
    assert not list(season.glob("*.part.*"))


def test_job_that_fails_when_queued(season: Path, queues: Queues) -> None:
    async def refuse(_job: JobSettings) -> list[Issue]:
        return [
            Issue(
                severity=Severity.ERROR,
                code="output.exists",
                path="output.path",
                message="Show.S01E01.Title.1.mkv already exists.",
            )
        ]

    queues.validator = refuse
    result = invoke("encode", str(season / EPISODES[0]))
    assert result.exit_code == EXIT_FAILED
    assert "[1/1] failed when it was queued:" in result.stdout
    assert "error    Show.S01E01.Title.1.mkv already exists." in result.stdout
    assert "Nothing" not in result.stdout


def _interrupt(_job: QueueJob) -> None:
    signal.raise_signal(signal.SIGINT)


@pytest.mark.skipif(
    signal.getsignal(signal.SIGINT) is not signal.default_int_handler,
    reason="needs Python's own SIGINT handler (asyncio.run replaces it)",
)
def test_ctrl_c_cancels_the_jobs_and_removes_the_partial_file(season: Path, queues: Queues) -> None:
    """A real SIGINT while the first job runs: asyncio.run cancels the command, which cancels
    the waiting and running jobs through the queue."""
    queues.behaviour = lambda _job: "hang"
    queues.on_running = _interrupt
    result = invoke("encode", str(season))
    assert result.exit_code == EXIT_INTERRUPTED, result.output
    assert "Interrupted: cancelling the jobs" in result.stderr
    assert result.stdout.splitlines()[-1] == "Summary: 0 done, 0 failed, 3 cancelled, 0 not queued."
    calls = queues.queue.calls
    assert "stop" not in calls  # it would stop other front ends' jobs of a shared queue
    cancels = [call for call in calls if call.startswith("cancel")]
    assert cancels == ["cancel job-2", "cancel job-3", "cancel job-1"]
    assert [job.state for job in queues.queue.list()] == [JobState.CANCELLED] * 3
    assert not list(season.glob("*.part.*"))
    assert outputs(season) == []


@pytest.mark.anyio
async def test_cancelling_the_command_cancels_the_jobs(
    season: Path, queues: Queues, tmp_path: Path
) -> None:
    """The same through the task (how asyncio.run reacts to Ctrl+C on every OS, also to
    Windows' CTRL_C_EVENT)."""
    running = asyncio.Event()
    queues.behaviour = lambda _job: "hang"
    queues.on_running = lambda _job: running.set()
    task = asyncio.create_task(cli.run_encode([season], preset=None, output=None))
    await asyncio.wait_for(running.wait(), 30)
    await asyncio.sleep(0.05)  # the 10 % progress event
    assert partial_files(season)
    task.cancel()
    assert await task == EXIT_INTERRUPTED
    assert not partial_files(season)
    assert {job.state for job in queues.queue.list()} == {JobState.CANCELLED}


def test_missing_path(cli_env: ft.FakeTools, queues: Queues, tmp_path: Path) -> None:
    result = invoke("encode", str(tmp_path / "nope.mkv"))
    assert result.exit_code == EXIT_NOT_FOUND
    assert result.stderr.startswith("error: ")
    assert "does not exist" in result.stderr
    assert queues.made == []


def test_folder_without_media(cli_env: ft.FakeTools, queues: Queues, tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "notes.txt").write_text("x")
    result = invoke("encode", str(empty))
    assert result.exit_code == EXIT_NOT_FOUND
    assert "no media files in this folder" in result.stderr
    assert "error: no media files to encode." in result.stderr


def test_unknown_preset(season: Path, queues: Queues) -> None:
    result = invoke("encode", str(season), "--preset", "nope")
    assert result.exit_code == EXIT_USAGE
    assert 'no preset named "nope"' in result.stderr
    assert queues.made == []


def test_recursive(cli_env: ft.FakeTools, queues: Queues, tmp_path: Path) -> None:
    replay(cli_env, "multitrack")
    show = tmp_path / "media" / "Show"
    media_file(show / "Season 01", EPISODES[0])
    flat = invoke("encode", str(show))
    assert flat.exit_code == EXIT_NOT_FOUND
    deep = invoke("encode", "-r", str(show))
    assert deep.exit_code == EXIT_OK, deep.output


def test_progress_text() -> None:
    progress = JobProgress(
        percent=42.0,
        fps=87.3,
        speed=3.64,
        eta=83.4,
        output_size=12_900_000,
        step=1,
        step_count=2,
        step_kind="pass2",
    )
    assert progress_text(progress) == (
        "42.0% · 87.3 fps · 3.64x · ETA 0:01:23 · 12.3 MiB · step 2/2 pass2"
    )
    assert progress_text(JobProgress()) == "0.0% · ETA —"


def test_lines_mode_prints_every_ten_percent(monkeypatch: pytest.MonkeyPatch) -> None:
    buffer = io.StringIO()
    console = Console(file=buffer, width=120, force_terminal=False)
    view = EncodeView(console, {"a": "[1/1]"}, live=False)
    clock = [0.0]
    monkeypatch.setattr("reframe.cli.time.monotonic", lambda: clock[0])
    view.state("a", JobState.RUNNING)
    for percent in (1.0, 5.0, 10.5, 12.0, 25.0):
        view.progress("a", JobProgress(percent=percent))
    clock[0] = 31.0
    view.progress("a", JobProgress(percent=26.0))  # 30 s later: printed anyway
    view.state("a", JobState.PAUSED)
    view.state("a", JobState.RUNNING, previous=JobState.PAUSED)
    view.state("a", JobState.CANCELLED)
    view.state("other", JobState.DONE)  # not ours: ignored
    lines = buffer.getvalue().splitlines()
    assert lines == [
        "[1/1] running",
        "[1/1] 1.0% · ETA —",
        "[1/1] 10.5% · ETA —",
        "[1/1] 25.0% · ETA —",
        "[1/1] 26.0% · ETA —",
        "[1/1] paused",
        "[1/1] resumed",
        "[1/1] cancelled",
    ]


def test_live_mode_on_a_terminal() -> None:
    buffer = io.StringIO()
    console = Console(file=buffer, width=120, force_terminal=True)
    view = EncodeView(console, {"a": "[1/2]", "b": "[2/2]"})
    assert view.live
    view.state("a", JobState.RUNNING)
    view.progress("a", JobProgress(percent=50.0, fps=30.0, eta=10.0))
    view.progress("b", JobProgress(percent=5.0))  # a bar appears for it too
    view.state("a", JobState.DONE, output=Path("/out/a.mkv"))
    view.state("b", JobState.FAILED, error="boom", log=Path("/logs/b.log"))
    view.state("b", JobState.INTERRUPTED)
    view.close()
    text = buffer.getvalue()
    assert "[1/2] done in 0:00:00: /out/a.mkv" in text
    assert "[2/2] failed: boom" in text
    assert "log: /logs/b.log" in text
    assert "[2/2] interrupted" in text


def test_nothing_to_encode(cli_env: ft.FakeTools, queues: Queues, tmp_path: Path) -> None:
    replay(cli_env, "cover-art")
    media_file(tmp_path / "media", "song.mkv")
    result = invoke("encode", str(tmp_path / "media"))
    assert result.exit_code == EXIT_FAILED
    assert result.stdout.splitlines()[-1] == "Nothing to encode."
    assert queues.queue.calls == []


class _Events:
    """A subscription stand-in that yields the given events."""

    def __init__(self, events: list[object]) -> None:
        self.events = events

    def __aiter__(self) -> _Events:
        return self

    async def __anext__(self) -> object:
        if not self.events:
            raise StopAsyncIteration
        event = self.events.pop(0)
        return event() if callable(event) else event


@pytest.mark.anyio
async def test_follow_rereads_the_queue_after_a_resync(tmp_path: Path) -> None:
    """The end of a job was among the events that a slow subscriber lost: the resync marker
    makes the follow read the queue, show the end and stop."""
    from types import SimpleNamespace

    from reframe.events import EventBus
    from reframe.models import JobSettings, OutputSettings, ResyncEvent, SourceRef

    queue = FakeQueue(EventBus(), log_dir=tmp_path)
    job = await queue.add(
        JobSettings(
            source=SourceRef(path=tmp_path / "a.src.mkv"),
            output=OutputSettings(path=tmp_path / "a.mkv"),
        )
    )
    queue._jobs[job.id] = queue._jobs[job.id].model_copy(update={"state": JobState.RUNNING})

    def ended_unseen() -> ResyncEvent:
        queue._jobs[job.id] = queue._jobs[job.id].model_copy(update={"state": JobState.DONE})
        return ResyncEvent(dropped=3)

    buffer = io.StringIO()
    view = EncodeView(Console(file=buffer, width=200), {job.id: "[1/1]"}, live=False)
    jobs = cli.CommandJobs()
    jobs.add(job, "[1/1]")
    session = SimpleNamespace(queue=queue, lost=None)
    following = cli._Following(session, _Events([ended_unseen]), view)  # type: ignore[arg-type]
    await asyncio.wait_for(cli._follow_jobs(following, jobs), 10)
    assert buffer.getvalue().splitlines() == ["[1/1] done"]
    assert jobs.open() == []


@pytest.mark.anyio
async def test_cancel_wait_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Stuck(FakeQueue):
        async def wait(self, job_ids: Sequence[str] | None = None) -> list[QueueJob]:
            await asyncio.Event().wait()
            return []

    from reframe.events import EventBus

    monkeypatch.setattr(cli, "CANCEL_WAIT", 0.05)
    errors: list[str] = []
    monkeypatch.setattr(cli, "_error", errors.append)
    await cli._cancel_jobs(Stuck(EventBus(), log_dir=tmp_path), cli.CommandJobs())
    assert errors == ["the jobs did not end within 0.05 s after they were cancelled."]


def test_summary_counts_interrupted_jobs() -> None:
    buffer = io.StringIO()
    cli._summary(Console(file=buffer, width=200), [JobState.INTERRUPTED, JobState.RUNNING], 0)
    assert buffer.getvalue().strip() == (
        "Summary: 0 done, 0 failed, 0 cancelled, 1 interrupted, 1 not finished, 0 not queued."
    )


class _RefusedStart(FakeQueue):
    """The queue contract of a queue in a server: another front end removes ``job-1`` while
    the command's start is on its way, so the owner refuses that start (nothing starts) and
    the refusal is raised by the next awaited call."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.refusal: UnknownJobError | None = None

    def start(self, *, job_ids: Sequence[str] | None = None) -> None:
        if job_ids is None or "job-1" not in job_ids:
            super().start(job_ids=job_ids)
            return
        self.calls.append(f"refused start {' '.join(job_ids)}")
        self._order.remove("job-1")
        del self._jobs["job-1"]
        self.events.publish(QueueChangedEvent(job_ids=list(self._order)))
        self.refusal = UnknownJobError("job-1")

    async def wait(self, job_ids: Sequence[str] | None = None) -> list[QueueJob]:
        refusal, self.refusal = self.refusal, None
        if refusal is not None:
            raise refusal
        return await super().wait(job_ids)


@pytest.mark.anyio
async def test_a_start_that_the_owner_refuses_is_sent_again_for_the_jobs_still_there(
    season: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    made: list[_RefusedStart] = []

    def make(app: Reframe) -> _RefusedStart:
        made.append(_RefusedStart(app.events, log_dir=tmp_path / "logs"))
        return made[-1]

    monkeypatch.setattr(cli, "get_queue", make)
    files = [season / name for name in EPISODES[:2]]
    code = await asyncio.wait_for(cli.run_encode(files, preset=None, output=None), 30)
    lines = capsys.readouterr().out.splitlines()
    assert code == EXIT_FAILED
    assert [call for call in made[0].calls if "start" in call] == [
        "refused start job-1 job-2",
        "start job-2",
    ]
    assert "[1/2] removed" in lines
    assert lines[-1] == "Summary: 1 done, 0 failed, 0 cancelled, 1 removed, 0 not queued."


@pytest.mark.anyio
async def test_ctrl_c_leaves_foreign_jobs_alone(tmp_path: Path) -> None:
    """Only our ids are started and cancelled: a waiting job of another front end in the
    shared store stays waiting (never ``cancel()`` without an id)."""
    from reframe.events import EventBus
    from reframe.models import OutputSettings, SourceRef

    def settings(name: str) -> JobSettings:
        return JobSettings(
            source=SourceRef(path=tmp_path / f"{name}.src.mkv"),
            output=OutputSettings(path=tmp_path / f"{name}.mkv"),
        )

    queue = FakeQueue(EventBus(), log_dir=tmp_path, behaviour=lambda _job: "hang")
    foreign = await queue.add(settings("foreign"))
    ours = [(await queue.add(settings(n), position=i)).id for i, n in enumerate("ab")]
    jobs = cli.CommandJobs()
    for number, job_id in enumerate(ours, start=1):
        jobs.add(queue.get(job_id), f"[{number}/2]")  # type: ignore[arg-type]
    queue.start(job_ids=ours)
    await asyncio.sleep(0.05)
    await cli._cancel_jobs(queue, jobs)
    assert [c for c in queue.calls if c.startswith("cancel")] == [
        "cancel job-3",  # waiting first, then the running one
        "cancel job-2",
    ]
    assert queue.get(foreign.id).state is JobState.WAITING  # type: ignore[union-attr]
    assert {queue.get(j).state for j in ours} == {JobState.CANCELLED}  # type: ignore[union-attr]
    await queue.close()
