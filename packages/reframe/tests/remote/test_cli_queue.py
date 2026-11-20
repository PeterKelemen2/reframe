"""``reframe queue``: list and log through the owner, or from the saved queue without the lock;
pause, resume, cancel, retry and remove through the owner, by id or the start of one."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from reframe import cli
from reframe.models import Fix, JobState, QueueJob, ReplaceOp, Severity, ValidationIssue
from reframe.queue import lock as lock_module
from reframe.queue.logs import log_file
from reframe.queue.store import STORE_FILE
from reframe_testing.server import ApiFactory
from reframe_testing.waiting import wait_until

from .conftest import HANG, Server

pytestmark = pytest.mark.anyio


async def add(server: Server, name: str = "Show.mkv", *, start: bool = False) -> QueueJob:
    job = await server.api.reframe.queue.add(await server.job(name))
    if start:
        server.api.reframe.queue.start(job_ids=[job.id])
    return job


def state(server: Server, job_id: str) -> JobState | None:
    job = server.api.reframe.queue.get(job_id)
    return None if job is None else job.state


async def running(server: Server, job_id: str) -> None:
    await wait_until(lambda: state(server, job_id) is JobState.RUNNING)


async def test_list_through_the_owner(server: Server, capsys: pytest.CaptureFixture[str]) -> None:
    first = await add(server, "First.mkv")
    second = await add(server, "Second.mkv")
    await server.api.reframe.queue.cancel(second.id)
    server.publish()
    assert await cli.run_queue_list(as_json=False) == cli.EXIT_OK
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split() == ["#", "Id", "State", "Done", "Source", "→", "Output"]
    assert lines[1].split()[:3] == ["1", first.id[:8], "waiting"]
    assert lines[2].split()[:3] == ["2", second.id[:8], "cancelled"]
    assert lines[-1] == "2 jobs: 1 waiting, 1 cancelled."
    assert await cli.run_queue_list(as_json=True) == cli.EXIT_OK
    listed = json.loads(capsys.readouterr().out)
    assert [job["id"] for job in listed] == [first.id, second.id]
    assert listed[0]["log_path"] == str(server.data_dir / "logs" / f"{first.id}.log")


async def test_list_without_an_owner_reads_the_saved_queue_as_it_is(
    make_api: ApiFactory, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A job that was running when its owner stopped still says so: nothing is restored, and
    no lock is taken."""
    async with make_api(mode="desktop") as api:
        job = await api.reframe.queue.add(await Server(api, None).job())  # type: ignore[arg-type]
        data_dir = api.reframe.data_dir
    with sqlite3.connect(data_dir / STORE_FILE) as db:
        db.execute("UPDATE jobs SET state = 'running' WHERE id = ?", (job.id,))
    db.close()

    def no_lock(_self: object) -> None:
        raise AssertionError("reframe queue list took the queue's lock")

    monkeypatch.setattr(lock_module.StoreLock, "acquire", no_lock)
    assert await cli.run_queue_list(as_json=False) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "No Reframe server runs for this data folder: the saved queue."
    assert f"{job.id[:8]}  running" in out
    with sqlite3.connect(data_dir / STORE_FILE) as db:
        assert db.execute("SELECT state FROM jobs").fetchall() == [("running",)]
    db.close()


async def test_list_and_log_say_why_a_running_server_is_not_used(
    server: Server, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from reframe_server.routers import health

    job = await add(server)
    monkeypatch.setattr(health, "API_VERSION", 2)
    server.publish()
    assert await cli.run_queue_list(as_json=False) == cli.EXIT_OK
    first = capsys.readouterr().out.splitlines()[0]
    assert first.startswith("The Reframe server of this data folder cannot be used (Reframe ")
    assert first.endswith("it speaks API version 2, not 1 as this reframe does): the saved queue.")
    assert await cli.run_queue_log(job.id, follow=False) == cli.EXIT_OK
    err = capsys.readouterr().err
    assert err.startswith("warning: the Reframe server of this data folder cannot be used (")


async def test_an_empty_queue(make_api: ApiFactory, capsys: pytest.CaptureFixture[str]) -> None:
    async with make_api(mode="desktop"):
        pass  # the folders and the environment of a server, and no store file
    assert await cli.run_queue_list(as_json=False) == cli.EXIT_OK
    assert "The queue is empty." in capsys.readouterr().out


async def test_log_of_a_job_by_the_start_of_its_id(
    server: Server, capsys: pytest.CaptureFixture[str]
) -> None:
    job = await add(server, start=True)
    await asyncio.wait_for(server.api.reframe.queue.wait([job.id]), 30)
    server.publish()
    assert await cli.run_queue_log(job.id[:6], follow=False) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert out.startswith(f"=== Reframe job {job.id}: run started")
    assert "Job done" in out


async def test_log_follows_a_running_job_until_it_ends(
    server: Server, capsys: pytest.CaptureFixture[str]
) -> None:
    server.api.fake.set_scenario(HANG)
    job = await add(server, start=True)
    await running(server, job.id)
    server.publish()
    follow = asyncio.create_task(cli.run_queue_log(job.id, follow=True))
    await asyncio.sleep(1.0)
    assert not follow.done()
    await server.api.reframe.queue.cancel(job.id)
    assert await asyncio.wait_for(follow, 10) == cli.EXIT_OK
    assert "Job cancelled" in capsys.readouterr().out  # written after the follow began


async def test_following_a_log_ends_with_an_error_when_the_owner_stops_first(
    make_api: ApiFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    async with make_api(mode="desktop") as api:
        api.fake.set_scenario(HANG)
        async with api.live() as live:
            server = Server(api, live)
            job = await add(server, start=True)
            await running(server, job.id)
            server.publish()
            follow = asyncio.create_task(cli.run_queue_log(job.id, follow=True))
            await asyncio.sleep(1.0)
            assert not follow.done()
        assert await asyncio.wait_for(follow, 10) == cli.EXIT_FAILED
        await api.reframe.queue.cancel(job.id)
    err = capsys.readouterr().err
    assert err == f"error: the Reframe server stopped before job {job.id[:8]} ended.\n"


async def test_a_job_that_is_not_in_the_queue(
    server: Server, capsys: pytest.CaptureFixture[str]
) -> None:
    await add(server, "A.mkv")
    server.publish()
    assert await cli.run_queue_log("no-such-job", follow=False) == cli.EXIT_FAILED
    assert capsys.readouterr().err == "error: there is no job no-such-job in the queue.\n"
    assert await cli.run_queue_log("", follow=False) == cli.EXIT_FAILED
    assert capsys.readouterr().err == "error: name a job by its id or the start of it.\n"


@pytest.mark.parametrize(
    ("name", "shown"),
    [
        pytest.param(
            "Evil\x1b]0;title\x07.mkv",
            "Evil�]0;title�.mkv",
            id="C0",
            marks=pytest.mark.skipif(
                sys.platform == "win32", reason="Windows file names cannot hold C0 controls"
            ),
        ),
        pytest.param("Evil\x9b2J.mkv", "Evil�2J.mkv", id="C1"),
    ],
)
async def test_queue_output_shows_no_control_characters(
    server: Server, capsys: pytest.CaptureFixture[str], name: str, shown: str
) -> None:
    """A source named with an escape sequence, and a log line with one, reach the terminal as
    U+FFFD: they cannot change the terminal."""
    job = await add(server, name)
    log = log_file(server.data_dir, job.id)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_bytes(b"frame=1 \x1b[2J\x1b[31mred\n")
    server.publish()
    assert await cli.run_queue_list(as_json=False) == cli.EXIT_OK
    listed = capsys.readouterr().out
    assert shown in listed
    assert await cli.run_queue_log(job.id, follow=False) == cli.EXIT_OK
    assert capsys.readouterr().out == "frame=1 �[2J�[31mred\n"


def test_a_job_is_named_by_its_id_or_a_start_that_names_one_job() -> None:
    def job(job_id: str) -> QueueJob:
        return QueueJob.model_validate(
            {
                "id": job_id,
                "position": 0,
                "settings": {"source": {"path": "/a.mkv"}},
                "created_at": "2026-10-28T00:00:00Z",
            }
        )

    jobs = [job("abc"), job("abcd"), job("b123")]
    assert cli.find_job(jobs, "abc") is jobs[0]  # the whole id, though it starts another
    assert cli.find_job(jobs, "b1") is jobs[2]
    assert cli.find_job(jobs, "ab") == "ab is the start of 2 job ids: give more of it."


async def test_pause_resume_and_cancel_by_id(
    server: Server, capsys: pytest.CaptureFixture[str]
) -> None:
    server.api.fake.set_scenario(HANG)
    job = await add(server, start=True)
    await running(server, job.id)
    server.publish()
    for action, after in (("pause", "paused"), ("resume", "running"), ("cancel", "cancelled")):
        assert await cli.run_queue_action(action, [job.id[:8]], every=False) == cli.EXIT_OK
        assert capsys.readouterr().out.strip() == f"{job.id[:8]} Show.mkv: {after}"
        assert state(server, job.id) == after


@pytest.mark.parametrize(
    ("action", "start", "said"),
    [("cancel", True, "it has ended (done)"), ("pause", False, "it is waiting, not running")],
)
async def test_an_action_that_the_jobs_state_does_not_allow(
    server: Server, capsys: pytest.CaptureFixture[str], action: str, start: bool, said: str
) -> None:
    job = await add(server, start=start)
    if start:
        await asyncio.wait_for(server.api.reframe.queue.wait([job.id]), 30)
    before = state(server, job.id)
    server.publish()
    assert await cli.run_queue_action(action, [job.id], every=False) == cli.EXIT_FAILED
    captured = capsys.readouterr()
    assert captured.err == f"error: {job.id[:8]} Show.mkv: {said}.\n"
    assert captured.out == ""
    assert state(server, job.id) is before


async def test_all(server: Server, capsys: pytest.CaptureFixture[str]) -> None:
    waiting = await add(server, "Waiting.mkv")
    server.publish()
    assert await cli.run_queue_action("cancel", [], every=True) == cli.EXIT_OK
    assert capsys.readouterr().out.strip() == "Cancelled every job that had not ended."
    assert state(server, waiting.id) is JobState.CANCELLED


@pytest.mark.parametrize(("refs", "every"), [([], False), (["abc"], True)])
async def test_jobs_or_all_but_not_both(
    capsys: pytest.CaptureFixture[str], refs: list[str], every: bool
) -> None:
    assert await cli.run_queue_action("pause", refs, every=every) == cli.EXIT_USAGE
    assert "give --all" in capsys.readouterr().err


async def test_an_action_on_an_unknown_job_and_a_known_one(
    server: Server, capsys: pytest.CaptureFixture[str]
) -> None:
    job = await add(server)
    server.publish()
    code = await cli.run_queue_action("cancel", ["no-such-job", job.id], every=False)
    captured = capsys.readouterr()
    assert code == cli.EXIT_FAILED
    assert "there is no job no-such-job" in captured.err
    assert state(server, job.id) is JobState.CANCELLED  # the other one is still done


async def test_an_action_needs_an_owner(
    server: Server, short_waits: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """The test's server holds the queue but publishes no endpoint."""
    job = await add(server)
    assert await cli.run_queue_action("cancel", [job.id], every=False) == cli.EXIT_FAILED
    err = capsys.readouterr().err
    assert "reframe queue cancel needs the Reframe server that owns the queue" in err
    assert state(server, job.id) is JobState.WAITING


async def test_retry_waits_again_and_starts(
    server: Server, capsys: pytest.CaptureFixture[str]
) -> None:
    job = await add(server)
    await server.api.reframe.queue.cancel(job.id)
    server.publish()
    assert await cli.run_queue_retry(job.id) == cli.EXIT_OK
    assert "waiting; it starts when a slot is free" in capsys.readouterr().out
    [ended] = await asyncio.wait_for(server.api.reframe.queue.wait([job.id]), 30)
    assert ended.state is JobState.DONE


async def test_a_retry_that_the_queue_refuses(
    server: Server, capsys: pytest.CaptureFixture[str]
) -> None:
    claimed = await add(server, "Same.mkv")
    await server.api.reframe.queue.cancel(claimed.id)
    await add(server, "Same.mkv")  # another job now writes that output
    done = await add(server, "Done.mkv", start=True)
    await asyncio.wait_for(server.api.reframe.queue.wait([done.id]), 30)
    server.publish()
    assert await cli.run_queue_retry(claimed.id) == cli.EXIT_FAILED
    assert "is also the output of a job that is waiting" in capsys.readouterr().out
    assert await cli.run_queue_retry(done.id) == cli.EXIT_FAILED
    assert "it cannot be retried" in capsys.readouterr().err


async def test_remove(server: Server, capsys: pytest.CaptureFixture[str]) -> None:
    server.api.fake.set_scenario(HANG)
    job = await add(server, "Running.mkv", start=True)
    waiting = await add(server, "Waiting.mkv")
    await running(server, job.id)
    server.publish()
    assert await cli.run_queue_remove(waiting.id) == cli.EXIT_OK
    assert capsys.readouterr().out.strip() == f"Removed {waiting.id[:8]} Waiting.mkv."
    assert state(server, waiting.id) is None
    assert await cli.run_queue_remove(job.id) == cli.EXIT_FAILED
    assert "cancel it first" in capsys.readouterr().err
    await server.api.reframe.queue.cancel(job.id)


async def test_the_list_says_why_a_job_failed(
    server: Server, capsys: pytest.CaptureFixture[str]
) -> None:
    job = await server.job("Gone.mkv")
    (server.api.media / "Gone.mkv").unlink()
    failed = await server.api.reframe.queue.add(job)
    server.publish()
    assert await cli.run_queue_list(as_json=False) == cli.EXIT_OK
    lines = capsys.readouterr().out.splitlines()
    assert lines[1].split()[:3] == ["1", failed.id[:8], "failed"]
    assert lines[2].strip().startswith("failed: The job has errors: ")


async def test_the_list_marks_a_job_whose_encoder_is_unavailable_and_gives_its_fixes(
    server: Server,
) -> None:
    settings = await server.job("Gpu.mkv")
    issue = ValidationIssue(
        severity=Severity.ERROR,
        code="encoder.unavailable",
        path="video.encoder",
        message="hevc_nvenc is not available: NVIDIA driver not found.",
        fixes=[
            Fix(
                label="Use libx265 (closest match)",
                patch=[ReplaceOp(path="/video/encoder", value="libx265")],
            ),
            Fix(label="Save in the preset", patch=[], target="template"),
        ],
    )
    job = QueueJob(
        id="0123456789abcdef",
        position=0,
        state=JobState.FAILED,
        settings=settings,
        issues=[issue],
        created_at=datetime.now(UTC),
        error=f"The job has errors: {issue.message}",
    )
    lines = [line.strip() for line in cli.queue_rows([job])]
    assert lines[1].split()[:3] == ["1", "01234567", "failed"]
    assert lines[2:5] == [
        "failed — encoder unavailable: hevc_nvenc is not available: NVIDIA driver not found.",
        "fix: Use libx265 (closest match)",
        "or choose another encoder (edit the job in the app), or check again: reframe "
        "encoders, then reframe queue retry 01234567",
    ]


def saved_queue(api_data: Path, sql: str, *params: object) -> None:
    with sqlite3.connect(api_data / STORE_FILE) as db:
        db.execute(sql, params)
    db.close()


async def test_a_saved_queue_of_a_newer_reframe_is_not_listed_and_says_why(
    make_api: ApiFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    async with make_api(mode="desktop") as api:
        await api.reframe.queue.add(await Server(api, None).job())  # type: ignore[arg-type]
        data_dir = api.reframe.data_dir
    saved_queue(data_dir, "PRAGMA user_version = 99")
    assert await cli.run_queue_list(as_json=False) == cli.EXIT_FAILED
    captured = capsys.readouterr()
    assert "warning: the saved queue: " in captured.err
    assert "saved by a newer Reframe (schema 99)" in captured.err
    assert "The queue is empty." not in captured.out


async def test_a_damaged_job_is_left_out_of_the_list_and_counted(
    make_api: ApiFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    async with make_api(mode="desktop") as api:
        kept = await api.reframe.queue.add(await Server(api, None).job("Kept.mkv"))  # type: ignore[arg-type]
        damaged = await api.reframe.queue.add(await Server(api, None).job("Damaged.mkv"))  # type: ignore[arg-type]
        data_dir = api.reframe.data_dir
    saved_queue(data_dir, "UPDATE jobs SET settings_json = 'not json' WHERE id = ?", damaged.id)
    assert await cli.run_queue_list(as_json=True) == cli.EXIT_OK
    captured = capsys.readouterr()
    assert [job["id"] for job in json.loads(captured.out)] == [kept.id]
    assert "1 saved job(s) could not be read" in captured.err


@pytest.mark.skipif(
    sys.platform == "win32" or os.geteuid() == 0, reason="POSIX folder modes, not as root"
)
async def test_the_saved_queue_of_a_folder_the_user_cannot_write(
    make_api: ApiFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    async with make_api(mode="desktop") as api:
        job = await api.reframe.queue.add(await Server(api, None).job())  # type: ignore[arg-type]
        data_dir = api.reframe.data_dir
    for side in ("-wal", "-shm"):
        (data_dir / f"{STORE_FILE}{side}").unlink(missing_ok=True)
    data_dir.chmod(0o555)
    try:
        assert await cli.run_queue_list(as_json=True) == cli.EXIT_OK
    finally:
        data_dir.chmod(0o755)
    assert [j["id"] for j in json.loads(capsys.readouterr().out)] == [job.id]


async def test_the_log_of_a_job_that_never_ran_is_empty(
    server: Server, capsys: pytest.CaptureFixture[str]
) -> None:
    job = await add(server)
    server.publish()
    assert await cli.run_queue_log(job.id, follow=False) == cli.EXIT_OK
    assert capsys.readouterr().out == ""


async def test_following_the_log_of_a_job_that_an_in_process_command_runs(
    make_api: ApiFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    """No server, but the process that holds the saved queue (an ``--in-process`` command)
    runs: the log is followed until the saved queue says the job ended."""
    async with make_api(mode="desktop") as api:
        job = await api.reframe.queue.add(await Server(api, None).job())  # type: ignore[arg-type]
        data_dir = api.reframe.data_dir
    saved_queue(data_dir, "UPDATE jobs SET state = 'running' WHERE id = ?", job.id)
    (data_dir / "queue.lock").write_text(f"{os.getpid()}\n", encoding="ascii")
    follow = asyncio.create_task(cli.run_queue_log(job.id, follow=True))
    await asyncio.sleep(1.0)
    assert not follow.done()
    log = log_file(data_dir, job.id)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("the last line\n", encoding="utf-8")
    saved_queue(data_dir, "UPDATE jobs SET state = 'done' WHERE id = ?", job.id)
    assert await asyncio.wait_for(follow, 10) == cli.EXIT_OK
    assert capsys.readouterr().out == "the last line\n"


async def test_following_a_log_without_a_live_owner_ends_with_an_error(
    make_api: ApiFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    """The saved queue says "running", but the process that owned it is gone: the job will not
    end."""
    async with make_api(mode="desktop") as api:
        job = await api.reframe.queue.add(await Server(api, None).job())  # type: ignore[arg-type]
        data_dir = api.reframe.data_dir
    saved_queue(data_dir, "UPDATE jobs SET state = 'running' WHERE id = ?", job.id)
    gone = await asyncio.create_subprocess_exec(sys.executable, "-c", "pass")
    await gone.wait()
    (data_dir / "queue.lock").write_text(f"{gone.pid}\n", encoding="ascii")
    follow = cli.run_queue_log(job.id, follow=True)
    assert await asyncio.wait_for(follow, 10) == cli.EXIT_FAILED
    err = capsys.readouterr().err
    assert err == f"error: the Reframe server stopped before job {job.id[:8]} ended.\n"


@pytest.mark.parametrize("command", ["retry", "remove"])
async def test_retry_and_remove_of_a_job_that_is_not_there(
    server: Server, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    server.publish()
    run = cli.run_queue_retry if command == "retry" else cli.run_queue_remove
    assert await run("no-such-job") == cli.EXIT_FAILED
    assert "there is no job no-such-job" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["retry", "remove"])
async def test_retry_and_remove_need_an_owner(
    server: Server, short_waits: None, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    job = await add(server)
    run = cli.run_queue_retry if command == "retry" else cli.run_queue_remove
    assert await run(job.id) == cli.EXIT_FAILED
    assert f"reframe queue {command} needs the Reframe server" in capsys.readouterr().err
    assert state(server, job.id) is JobState.WAITING


def test_the_queue_commands_through_the_command_line(
    make_api_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The typer wiring: arguments and options reach the commands (no owner runs)."""
    from typer.testing import CliRunner

    app = cli.build_app()
    runner = CliRunner()
    listed = runner.invoke(app, ["queue", "list"])
    assert (listed.exit_code, listed.stdout.splitlines()[-1]) == (0, "The queue is empty.")
    assert runner.invoke(app, ["queue", "log", "-f", "abc"]).exit_code == cli.EXIT_FAILED
    for command in ("pause", "resume", "cancel"):
        both = runner.invoke(app, ["queue", command, "abc", "--all"])
        assert both.exit_code == cli.EXIT_USAGE, both.output
    detach = runner.invoke(app, ["encode", "--detach", "--in-process", "x.mkv"])
    assert detach.exit_code == cli.EXIT_USAGE
    monkeypatch.setenv(cli.IN_PROCESS_ENV, "1")
    detach = runner.invoke(app, ["batch", "--detach", "x"])
    assert "cannot be used with --in-process" in detach.stderr


@pytest.fixture
def make_api_env(make_api: ApiFactory, tmp_path: Path) -> Path:
    """The private folders and environment of the server harness, with no server."""
    return tmp_path
