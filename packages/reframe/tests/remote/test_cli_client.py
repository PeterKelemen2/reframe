"""``reframe encode`` and ``reframe batch`` as clients of the queue's owner: the owner validates
and runs the jobs (no encoder detection here), ``--detach``, Ctrl+C and Ctrl+Z, jobs that another
front end removes or retries, a Stop by another front end, a server that stops or a connection
that is lost, the owner's when-done countdown, and the fallback to the in-process queue with the
reason. The owner is the test's server in this event loop; the CLI runs in the same loop, on the
same folders."""

from __future__ import annotations

import asyncio
import gc
import json
import os
import signal
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from websockets.asyncio.client import ClientConnection

from reframe import cli
from reframe.capabilities.service import CapabilityService
from reframe.events import EventBus
from reframe.models import (
    JobDraft,
    JobState,
    NamingOptions,
    OutputTrackRule,
    PowerCountdownEvent,
    Severity,
    TrackSelector,
    ValidationIssue,
)
from reframe.models.template import AudioOutputSettings
from reframe.platform.power import OsAction, PowerService
from reframe.queue.client import read_saved_queue
from reframe.remote import RemoteError, RemoteQueue
from reframe_testing import fake_tools as ft
from reframe_testing.server import PROBE_RULE, Api, ApiFactory
from reframe_testing.waiting import wait_until

from .conftest import HANG, Server, Wire, serving

pytestmark = pytest.mark.anyio

WAIT = 30.0
"""Seconds a command of these tests may take."""
STOP = int(getattr(signal, "SIGTSTP", 20))
"""The terminal's Ctrl+Z (POSIX only)."""


@pytest.fixture
def detections(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every encoder detection that starts from now on, through ``start`` or ``wait``."""
    started: list[str] = []
    start = CapabilityService._start

    def record(self: CapabilityService, **kwargs: Any) -> Any:
        started.append("detection")
        return start(self, **kwargs)

    monkeypatch.setattr(CapabilityService, "_start", record)
    return started


def ends(name: str, *, seconds: float = 0.0, code: int = 0) -> ft.Rule:
    """The encode of the source ``name`` writes its ``.part`` file, prints progress, runs for
    ``seconds`` and exits with ``code``."""
    actions = [ft.write_output(), ft.progress(blocks=1, end=False), ft.sleep(seconds)]
    return ft.Rule(
        tool="ffmpeg", argv_contains=[f"{os.sep}{name}"], actions=actions, exit_code=code
    )


def scenario(*rules: ft.Rule) -> ft.Scenario:
    """``rules`` first; every other encode hangs as in :data:`HANG`."""
    return ft.Scenario([PROBE_RULE, *rules, *HANG.rules[1:]])


async def job_of(server: Server, name: str, state: JobState | None = None) -> str:
    """The id of the job of the source ``name`` (once it is in ``state``)."""

    def found() -> str | None:
        for job in server.api.reframe.queue.list():
            if Path(job.settings.source.path).name == name and state in (None, job.state):
                return job.id
        return None

    await wait_until(lambda: found() is not None)
    job_id = found()
    assert job_id is not None
    return job_id


def states(server: Server) -> dict[str, JobState]:
    return {job.id: job.state for job in server.api.reframe.queue.list()}


async def test_encode_hands_its_jobs_to_the_owner_at_the_end_of_the_queue(
    server: Server, detections: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    foreign = await server.api.reframe.queue.add(await server.job("Foreign.mkv"))
    server.publish()
    source = server.api.media_file("Ours.mkv")
    code = await cli.run_encode([source], preset=None, output=server.api.output / "Ours.mkv")
    out = capsys.readouterr().out
    assert code == cli.EXIT_OK, out
    assert "Queue: Reframe " in out
    assert "[1/1] done" in out
    jobs = server.api.reframe.queue.list()
    assert (jobs[0].id, jobs[0].state) == (foreign.id, JobState.WAITING)
    assert jobs[1].state is JobState.DONE
    assert detections == []  # the owner's statuses decide: no test encodes here


async def test_the_owners_validation_decides_what_is_queued(
    server: Server, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    refused = ValidationIssue(
        severity=Severity.ERROR, code="owner.refuses", message="The owner refuses this job."
    )
    validate = server.api.reframe.jobs.validate

    async def owners_validation(*args: object, **kwargs: object) -> list[ValidationIssue]:
        return [*await validate(*args, **kwargs), refused]  # type: ignore[arg-type]

    monkeypatch.setattr(server.api.reframe.jobs, "validate", owners_validation)
    server.publish()
    code = await cli.run_encode([server.api.media_file("A.mkv")], preset=None, output=None)
    out = capsys.readouterr().out
    assert code == cli.EXIT_FAILED
    assert "The owner refuses this job." in out
    assert server.api.reframe.queue.list() == []


@pytest.mark.parametrize("preset_kind", ["default", "own rules and naming"])
async def test_a_client_drafts_as_the_in_process_draft(server: Server, preset_kind: str) -> None:
    """The second preset has a required track rule that no track matches (an error of the
    track stage) and its own naming template."""
    app = server.api.reframe
    source = server.api.media_file("Show.S01E02.1080p.BluRay.x264-GRP.mkv")
    preset = app.presets.default()
    if preset_kind != "default":
        missing = OutputTrackRule(
            selector=TrackSelector(kind="audio", languages=["fin"]),
            settings=AudioOutputSettings(encoder="aac"),
        )
        preset = preset.model_copy(
            update={
                "audio_rules": [missing],
                "naming": NamingOptions(episode_template="{name} custom"),
            }
        )
    local = await app.jobs.draft(source, preset)
    client = await cli.OwnerJobs(app, app.jobs.validate).draft(source, preset)
    assert isinstance(local, JobDraft)
    assert client == local
    if preset_kind != "default":
        assert "batch.track_missing" in [issue.code for issue in local.issues]
        assert local.naming.template == "{name} custom"


async def test_detach_queues_and_starts_the_jobs_and_ends(
    server: Server, capsys: pytest.CaptureFixture[str]
) -> None:
    server.publish()
    code = await cli.run_encode(
        [server.api.media_file("A.mkv")], preset=None, output=None, detach=True
    )
    out = capsys.readouterr().out
    assert code == cli.EXIT_OK, out
    [job] = server.api.reframe.queue.list()
    assert f"[1/1] job {job.id}" in out
    assert "Detached" in out
    [ended] = await asyncio.wait_for(server.api.reframe.queue.wait([job.id]), 30)
    assert ended.state is JobState.DONE  # neither cancelled with the connection nor left waiting


async def test_detach_ends_with_1_when_a_file_is_not_queued(
    server: Server, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    refused = ValidationIssue(severity=Severity.ERROR, code="owner.refuses", message="No.")
    validate = server.api.reframe.jobs.validate

    async def owners_validation(job: Any, *args: Any, **kwargs: Any) -> list[ValidationIssue]:
        issues = await validate(job, *args, **kwargs)
        return [*issues, refused] if "Bad" in str(job.source.path) else issues

    monkeypatch.setattr(server.api.reframe.jobs, "validate", owners_validation)
    server.publish()
    files = [server.api.media_file(name) for name in ("Good.mkv", "Bad.mkv")]
    code = await cli.run_encode(files, preset=None, output=None, detach=True)
    out = capsys.readouterr().out
    assert code == cli.EXIT_FAILED, out
    assert "Detached" in out
    [job] = server.api.reframe.queue.list()
    assert f"[1/2] job {job.id}" in out
    await asyncio.wait_for(server.api.reframe.queue.wait([job.id]), 30)


async def test_detach_needs_an_owner(
    server: Server, short_waits: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """The test's server holds the queue but publishes no endpoint."""
    code = await cli.run_encode(
        [server.api.media_file("A.mkv")], preset=None, output=None, detach=True
    )
    assert code == cli.EXIT_FAILED
    assert "--detach needs the Reframe server that owns the queue" in capsys.readouterr().err
    assert server.api.reframe.queue.list() == []


@pytest.mark.parametrize(
    ("command", "options", "named"),
    [
        ("encode", {"in_process": True}, "--in-process"),
        ("batch", {"in_process": True}, "--in-process"),
        ("batch", {"dry_run": True}, "--dry-run"),
    ],
)
async def test_detach_needs_the_server(
    capsys: pytest.CaptureFixture[str], command: str, options: dict[str, bool], named: str
) -> None:
    if command == "encode":
        code = await cli.run_encode(
            [Path("x.mkv")], preset=None, output=None, detach=True, **options
        )
    else:
        code = await cli.run_batch(
            [Path("x")],
            preset=None,
            detach=True,
            in_process=bool(options.get("in_process")),
            dry_run=options.get("dry_run", False),
        )
    assert code == cli.EXIT_USAGE
    assert f"cannot be used with {named}" in capsys.readouterr().err


async def test_an_owner_that_was_stopping_when_it_connected_is_looked_for_again(
    server: Server, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The owner of the first look was in its exit window; the next look finds one."""
    from reframe.remote import OwnerStopping, RemoteQueue

    connect = RemoteQueue.connect
    tries: list[int] = []

    async def stopping_once(*args: object, **kwargs: object) -> RemoteQueue:
        tries.append(1)
        if len(tries) == 1:
            raise OwnerStopping("the Reframe server is stopping", code="server.stopping")
        return await connect(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(RemoteQueue, "connect", stopping_once)
    server.publish()
    code = await cli.run_encode([server.api.media_file("A.mkv")], preset=None, output=None)
    assert code == cli.EXIT_OK, capsys.readouterr().out
    assert len(tries) == 2
    assert [job.state for job in server.api.reframe.queue.list()] == [JobState.DONE]


async def test_an_owner_that_keeps_stopping_is_left_with_the_reason(
    server: Server, capsys: pytest.CaptureFixture[str]
) -> None:
    server.publish()
    await server.api.app.state.hub.close()
    code = await cli.run_encode([server.api.media_file("A.mkv")], preset=None, output=None)
    captured = capsys.readouterr()
    assert code == cli.EXIT_OK, captured.out
    assert "no Reframe server can take the jobs (the Reframe server is stopping)" in captured.err
    assert server.api.reframe.queue.list() == []


async def test_a_job_the_owner_refuses_to_add(
    server: Server, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from reframe.service import ReframeClosedError

    async def closing(*_args: object, **_kwargs: object) -> None:
        raise ReframeClosedError

    monkeypatch.setattr(server.api.reframe.queue, "add", closing)
    server.publish()
    code = await cli.run_encode([server.api.media_file("A.mkv")], preset=None, output=None)
    captured = capsys.readouterr()
    assert code == cli.EXIT_FAILED
    assert "error: the jobs cannot be queued: The server is shutting down" in captured.err
    assert "unexpected error" not in captured.err


async def test_without_a_usable_owner_the_jobs_run_here_and_the_reason_is_shown(
    server: Server, short_waits: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """The lock is held by a process that serves no endpoint (here: this one)."""
    code = await cli.run_encode([server.api.media_file("A.mkv")], preset=None, output=None)
    captured = capsys.readouterr()
    assert code == cli.EXIT_OK, captured.out
    assert "warning: no Reframe server can take the jobs (another Reframe process" in captured.err
    assert "is using the saved queue" in captured.err  # queue.store_busy of the private queue
    assert "[1/1] done" in captured.out
    assert server.api.reframe.queue.list() == []


async def test_a_server_of_another_api_version_is_not_used(
    server: Server, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from reframe_server.routers import health

    monkeypatch.setattr(health, "API_VERSION", 2)
    server.publish()
    code = await cli.run_encode([server.api.media_file("A.mkv")], preset=None, output=None)
    captured = capsys.readouterr()
    assert code == cli.EXIT_OK, captured.out
    assert "owns the queue, and it speaks API version 2, not 1" in captured.err
    assert server.api.reframe.queue.list() == []


async def test_ctrl_c_cancels_only_the_commands_jobs(server: Server) -> None:
    """Two slots: another front end's job runs next to the command's, and a third front end's
    job waits. Ctrl+C cancels the command's running and waiting jobs only."""
    await server.api.reframe.settings.update(
        [{"op": "replace", "path": "/queue/parallel_jobs", "value": 2}]
    )
    server.api.fake.set_scenario(scenario(ends("Running.mkv", seconds=4)))
    queue = server.api.reframe.queue
    running = await queue.add(await server.job("Running.mkv"))
    queue.start(job_ids=[running.id])
    waiting = await queue.add(await server.job("Waiting.mkv"))
    server.publish()
    files = [server.api.media_file(f"{name}.mkv") for name in ("A", "B")]
    task = asyncio.create_task(cli.run_encode(files, preset=None, output=None))
    await wait_until(lambda: list(states(server).values()).count(JobState.RUNNING) == 2)
    assert queue.get(running.id).state is JobState.RUNNING  # type: ignore[union-attr]
    task.cancel()
    assert await asyncio.wait_for(task, WAIT) == cli.EXIT_INTERRUPTED
    found = states(server)
    assert found.pop(waiting.id) is JobState.WAITING
    assert found.pop(running.id) in (JobState.RUNNING, JobState.DONE)
    assert sorted(found.values()) == [JobState.CANCELLED, JobState.CANCELLED]
    assert not list(server.api.media.glob("*.part.*"))  # the command's outputs are there
    [other] = await asyncio.wait_for(queue.wait([running.id]), WAIT)
    assert other.state is JobState.DONE


async def test_a_server_that_stops_while_the_command_follows_its_jobs(
    make_api: ApiFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    async with make_api(mode="desktop") as api:
        api.fake.set_scenario(HANG)
        files = [api.media_file(f"{name}.mkv") for name in ("A", "B")]
        async with api.live() as live:
            Server(api, live).publish()
            task = asyncio.create_task(cli.run_encode(files, preset=None, output=None))
            await wait_until(
                lambda: any(j.state is JobState.RUNNING for j in api.reframe.queue.list())
            )
        code = await asyncio.wait_for(task, 30)
        jobs = api.reframe.queue.list()
        await api.reframe.queue.cancel()
    captured = capsys.readouterr()
    assert code == cli.EXIT_FAILED
    assert "[1/2] interrupted" in captured.out.splitlines()
    assert "1 interrupted, 1 not finished" in captured.out
    [waiting] = [j.id for j in jobs if j.state is JobState.WAITING]
    assert captured.err == (
        "error: the Reframe server stopped. The waiting jobs stay in the queue, not started: "
        f"reframe queue retry ID starts one, reframe queue cancel ID cancels it ({waiting[:8]}).\n"
    )


async def test_batch_hands_its_jobs_to_the_owner(
    server: Server, detections: list[str], fixture_season: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    server.publish()
    code = await asyncio.wait_for(cli.run_batch([fixture_season], preset=None), WAIT)
    out = capsys.readouterr().out
    assert code == cli.EXIT_OK, out
    assert "Queue: Reframe " in out
    assert [job.state for job in server.api.reframe.queue.list()] == [JobState.DONE] * 2
    assert detections == []


@pytest.fixture
def fixture_season(server: Server) -> Path:
    folder = server.api.media / "Show.S01.1080p.BluRay.x264-GRP"
    for number in (1, 2):
        server.api.media_file(f"{folder.name}/Show.S01E{number:02d}.1080p.BluRay.x264-GRP.mkv")
    return folder


async def test_a_job_another_front_end_removes_is_reported_and_the_command_ends(
    server: Server, capsys: pytest.CaptureFixture[str]
) -> None:
    """``reframe queue remove`` (or the UI) takes the command's waiting job; the command ends
    when its other job has ended."""
    server.api.fake.set_scenario(HANG)
    server.publish()
    files = [server.api.media_file(f"{name}.mkv") for name in ("A", "B")]
    task = asyncio.create_task(cli.run_encode(files, preset=None, output=None))
    a = await job_of(server, "A.mkv", JobState.RUNNING)
    b = await job_of(server, "B.mkv", JobState.WAITING)
    await server.api.reframe.queue.remove(b)
    await server.api.reframe.queue.cancel(a)
    code = await asyncio.wait_for(task, WAIT)
    lines = capsys.readouterr().out.splitlines()
    assert code == cli.EXIT_FAILED
    assert "[2/2] removed" in lines
    assert lines[-1] == "Summary: 0 done, 0 failed, 1 cancelled, 1 removed, 0 not queued."


async def test_ctrl_c_after_another_front_end_removed_a_job(
    server: Server, capsys: pytest.CaptureFixture[str]
) -> None:
    server.api.fake.set_scenario(HANG)
    server.publish()
    files = [server.api.media_file(f"{name}.mkv") for name in ("A", "B")]
    task = asyncio.create_task(cli.run_encode(files, preset=None, output=None))
    a = await job_of(server, "A.mkv", JobState.RUNNING)
    b = await job_of(server, "B.mkv", JobState.WAITING)
    await server.api.reframe.queue.remove(b)
    await asyncio.sleep(0.2)  # the command hears of it
    task.cancel()
    code = await asyncio.wait_for(task, WAIT)
    captured = capsys.readouterr()
    assert code == cli.EXIT_INTERRUPTED
    assert "cannot be cancelled" not in captured.err
    last = captured.out.splitlines()[-1]
    assert last == "Summary: 0 done, 0 failed, 1 cancelled, 1 removed, 0 not queued."
    assert states(server) == {a: JobState.CANCELLED}


async def test_a_stop_by_another_front_end_is_reported_and_a_later_start_runs_the_job(
    server: Server, capsys: pytest.CaptureFixture[str]
) -> None:
    """The UI's Stop while B waits behind A: the command says so once and goes on waiting, also
    when A's slot is free; the UI's Start then runs B."""
    server.api.fake.set_scenario(scenario(ends("B.mkv")))
    server.publish()
    files = [server.api.media_file(f"{name}.mkv") for name in ("A", "B")]
    task = asyncio.create_task(cli.run_encode(files, preset=None, output=None))
    queue = server.api.reframe.queue
    a = await job_of(server, "A.mkv", JobState.RUNNING)
    b = await job_of(server, "B.mkv", JobState.WAITING)
    await wait_until(lambda: queue.only == [a, b])  # the command's start
    await queue.stop()
    out: list[str] = []

    def stop_shown() -> bool:
        out.append(capsys.readouterr().out)
        return cli.STOPPED_BY_OTHERS in "".join(out)

    await wait_until(stop_shown)
    await queue.cancel(a)
    await asyncio.sleep(0.3)  # a job that the runner took would be running by now
    assert states(server)[b] is JobState.WAITING
    assert not task.done()
    queue.start()
    code = await asyncio.wait_for(task, WAIT)
    lines = "".join([*out, capsys.readouterr().out]).splitlines()
    assert code == cli.EXIT_FAILED, lines  # A was cancelled
    assert lines.count(cli.STOPPED_BY_OTHERS) == 1
    assert "[2/2] done" in [line.split(" in ")[0] for line in lines]
    assert states(server)[b] is JobState.DONE


async def test_the_idle_end_of_another_commands_start_is_not_reported_as_a_stop(
    server: Server, capsys: pytest.CaptureFixture[str]
) -> None:
    """After the UI's Stop, another CLI starts only its own job Y; Y's end makes the queue idle
    while B still waits: that is no second stop. C's cancel comes after the idle event, so once
    the command shows it, it has handled the idle event with B waiting."""
    server.api.fake.set_scenario(scenario(ends("Y.mkv")))
    server.publish()
    files = [server.api.media_file(f"{name}.mkv") for name in ("A", "B", "C")]
    task = asyncio.create_task(cli.run_encode(files, preset=None, output=None))
    queue = server.api.reframe.queue
    a = await job_of(server, "A.mkv", JobState.RUNNING)
    b = await job_of(server, "B.mkv", JobState.WAITING)
    c = await job_of(server, "C.mkv", JobState.WAITING)
    await wait_until(lambda: queue.only == [a, b, c])  # the command's start
    await queue.stop()
    await queue.cancel(a)
    other = await queue.add(await server.job("Y.mkv"))
    queue.start(job_ids=[other.id])
    [ended] = await asyncio.wait_for(queue.wait([other.id]), WAIT)
    assert ended.state is JobState.DONE
    assert not queue.processing  # idle, with B and C still waiting
    await queue.cancel(c)
    out: list[str] = []

    def c_shown() -> bool:
        out.append(capsys.readouterr().out)
        return "[3/3] cancelled" in "".join(out).splitlines()

    await wait_until(c_shown)
    await queue.cancel(b)
    code = await asyncio.wait_for(task, WAIT)
    lines = "".join([*out, capsys.readouterr().out]).splitlines()
    assert code == cli.EXIT_FAILED, lines
    assert lines.count(cli.STOPPED_BY_OTHERS) == 1


async def test_a_stop_while_none_of_its_jobs_waits_is_not_reported(
    server: Server, capsys: pytest.CaptureFixture[str]
) -> None:
    server.api.fake.set_scenario(HANG)
    server.publish()
    task = asyncio.create_task(
        cli.run_encode([server.api.media_file("A.mkv")], preset=None, output=None)
    )
    queue = server.api.reframe.queue
    a = await job_of(server, "A.mkv", JobState.RUNNING)
    await queue.stop()
    await queue.cancel(a)  # its events come after the stop's
    assert await asyncio.wait_for(task, WAIT) == cli.EXIT_FAILED
    assert cli.STOPPED_BY_OTHERS not in capsys.readouterr().out


async def test_a_stop_just_before_the_commands_own_start_is_not_reported(
    server: Server, wire: Wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Another front end's Stop reaches the owner between the command's add and its start, so
    the start runs the command's jobs; its event reaches the command after the stop's."""
    server.api.fake.set_scenario(HANG)
    queue = server.api.reframe.queue
    queue.start()
    server.publish()
    wire.lag = 0.05
    send = RemoteQueue._send_start

    async def stopped_first(self: RemoteQueue, ids: list[str] | None) -> None:
        await queue.stop()
        await send(self, ids)

    monkeypatch.setattr(RemoteQueue, "_send_start", stopped_first)
    files = [server.api.media_file(f"{name}.mkv") for name in ("A", "B")]
    task = asyncio.create_task(cli.run_encode(files, preset=None, output=None))
    a = await job_of(server, "A.mkv", JobState.RUNNING)
    b = await job_of(server, "B.mkv", JobState.WAITING)
    await wait_until(lambda: queue.only == [a, b])
    await queue.cancel()  # its events come after the stop's and the start's
    assert await asyncio.wait_for(task, WAIT) == cli.EXIT_FAILED
    assert cli.STOPPED_BY_OTHERS not in capsys.readouterr().out


async def test_a_stop_that_cannot_be_checked_with_the_owner_ends_nothing(
    server: Server, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    checks: list[RemoteQueue] = []

    async def unreadable(self: RemoteQueue) -> None:
        checks.append(self)
        raise RemoteError("the queue cannot be read", code="test")

    monkeypatch.setattr(RemoteQueue, "refresh", unreadable)
    server.api.fake.set_scenario(scenario(ends("B.mkv")))
    server.publish()
    files = [server.api.media_file(f"{name}.mkv") for name in ("A", "B")]
    task = asyncio.create_task(cli.run_encode(files, preset=None, output=None))
    queue = server.api.reframe.queue
    a = await job_of(server, "A.mkv", JobState.RUNNING)
    await job_of(server, "B.mkv", JobState.WAITING)
    await queue.stop()
    await wait_until(lambda: bool(checks))
    await queue.cancel(a)
    queue.start()
    code = await asyncio.wait_for(task, WAIT)
    captured = capsys.readouterr()
    assert code == cli.EXIT_FAILED, captured
    assert captured.out.splitlines()[-1] == (
        "Summary: 1 done, 0 failed, 1 cancelled, 0 not queued."
    )
    assert "error" not in captured.err


async def connections_closed(server: Server) -> None:
    """Until no event connection is open, and the owner has acted on their ends."""
    await wait_until(lambda: server.api.app.state.hub.connections == 0)
    await asyncio.sleep(0.5)


async def test_a_job_another_front_end_retries_is_left_to_it(
    server: Server, capsys: pytest.CaptureFixture[str]
) -> None:
    """The command's job A fails, and ``reframe queue retry`` in another terminal runs it again
    in the second slot while the command still follows B: the command neither shows nor waits
    for A's new run, and its end does not cancel A."""
    await server.api.reframe.settings.update(
        [{"op": "replace", "path": "/queue/parallel_jobs", "value": 2}]
    )
    server.api.fake.set_scenario(scenario(ends("A.mkv", code=1), ends("B.mkv", seconds=4)))
    server.publish()
    files = [server.api.media_file(f"{name}.mkv") for name in ("A", "B")]
    task = asyncio.create_task(cli.run_encode(files, preset=None, output=None))
    a = await job_of(server, "A.mkv", JobState.FAILED)
    await job_of(server, "B.mkv", JobState.RUNNING)
    server.api.fake.set_scenario(scenario(ends("B.mkv", seconds=4)))  # A's next run hangs
    assert await cli.run_queue_retry(a) == cli.EXIT_OK
    await wait_until(lambda: states(server)[a] is JobState.RUNNING)
    assert not task.done()
    code = await asyncio.wait_for(task, WAIT)
    lines = capsys.readouterr().out.splitlines()
    assert code == cli.EXIT_FAILED
    assert lines[-1] == "Summary: 1 done, 1 failed, 0 cancelled, 0 not queued."
    assert lines.count("[1/2] running") == 1  # A's new run is not shown
    await connections_closed(server)
    await wait_until(lambda: states(server)[a] is JobState.RUNNING)
    await server.api.reframe.queue.cancel(a)


async def test_ctrl_c_leaves_a_job_another_front_end_retried(
    server: Server, capsys: pytest.CaptureFixture[str]
) -> None:
    server.api.fake.set_scenario(scenario(ends("A.mkv", code=1)))
    server.publish()
    files = [server.api.media_file(f"{name}.mkv") for name in ("A", "B")]
    task = asyncio.create_task(cli.run_encode(files, preset=None, output=None))
    a = await job_of(server, "A.mkv", JobState.FAILED)
    await job_of(server, "B.mkv", JobState.RUNNING)
    server.api.fake.set_scenario(HANG)
    assert await cli.run_queue_retry(a) == cli.EXIT_OK  # it waits for B's slot
    task.cancel()
    code = await asyncio.wait_for(task, WAIT)
    lines = capsys.readouterr().out.splitlines()
    assert code == cli.EXIT_INTERRUPTED
    assert lines[-1] == "Summary: 0 done, 1 failed, 1 cancelled, 0 not queued."
    await connections_closed(server)
    await wait_until(
        lambda: states(server)[a] is JobState.RUNNING
    )  # in the slot of the cancelled B
    await server.api.reframe.queue.cancel(a)


def _open_connections(server: Server) -> list[ClientConnection]:
    """The open event connections of this process's clients to the test's server."""
    from websockets.protocol import State

    return [
        found
        for found in gc.get_objects()
        if type(found) is ClientConnection  # not a weak proxy of it
        and found.state is State.OPEN
        and found.remote_address[1] == server.live.port
    ]


def _sigtstp_handled() -> bool:
    return signal.getsignal(STOP) not in (signal.SIG_DFL, signal.SIG_IGN, None)


@pytest.mark.skipif(sys.platform == "win32", reason="no job control on Windows")
async def test_ctrl_z_pauses_the_commands_jobs_and_fg_resumes_them(
    server: Server, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """While the command is stopped, its running job is paused in the owner, and no connection
    is left whose end would cancel it (a stopped process cannot answer the server's
    keepalive). When the command is continued it resumes the job and follows it to its end."""
    await _stop_and_continue(server, monkeypatch, capsys)


@pytest.mark.skipif(sys.platform == "win32", reason="no job control on Windows")
async def test_ctrl_z_pauses_a_job_whose_start_the_command_has_not_seen(
    server: Server, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The command's copy of the queue can be behind the owner: a job that has just started
    still shows as waiting. It is paused all the same."""
    real = RemoteQueue._apply_state
    missed: list[object] = []

    async def behind(self: RemoteQueue, event: Any) -> None:
        if event.state is JobState.RUNNING and not missed:
            missed.append(event)
        else:
            await real(self, event)

    monkeypatch.setattr(RemoteQueue, "_apply_state", behind)
    await _stop_and_continue(server, monkeypatch, capsys)
    assert missed


async def _stop_and_continue(
    server: Server, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    server.api.fake.set_scenario(scenario(ends("A.mkv", seconds=2)))
    server.publish()
    seen: list[tuple[JobState | None, int]] = []
    job_id = ""

    def stopped() -> None:
        job = server.api.reframe.queue.get(job_id)
        seen.append((job.state if job is not None else None, len(_open_connections(server))))

    monkeypatch.setattr(cli, "_stop_process", stopped, raising=False)
    task = asyncio.create_task(
        cli.run_encode([server.api.media_file("A.mkv")], preset=None, output=None)
    )
    job_id = await job_of(server, "A.mkv", JobState.RUNNING)
    await wait_until(_sigtstp_handled, 10)  # never raised without a handler: it would stop pytest
    signal.raise_signal(STOP)
    code = await asyncio.wait_for(task, WAIT)
    captured = capsys.readouterr()
    assert seen == [(JobState.PAUSED, 0)]
    assert code == cli.EXIT_OK, captured
    assert "Stopped" in captured.err
    assert "[1/1] resumed" in captured.out.splitlines()
    assert states(server) == {job_id: JobState.DONE}
    assert not _sigtstp_handled()


@pytest.mark.skipif(sys.platform == "win32", reason="no job control on Windows")
async def test_a_command_that_was_stopped_cancels_its_jobs_on_sigterm(
    server: Server, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``kill %1`` of a stopped command (SIGTERM, then SIGCONT): its jobs are not attached any
    more, so the command cancels them itself, as on Ctrl+C."""
    server.api.fake.set_scenario(HANG)
    server.publish()
    monkeypatch.setattr(cli, "_stop_process", lambda: signal.raise_signal(signal.SIGTERM))
    # A SIGTERM that the command does not take must not end pytest (uvicorn's own handler of
    # the test's server would raise it again when the server stops).
    previous = signal.signal(signal.SIGTERM, lambda *_args: None)
    try:
        task = asyncio.create_task(
            cli.run_encode([server.api.media_file("A.mkv")], preset=None, output=None)
        )
        job_id = await job_of(server, "A.mkv", JobState.RUNNING)
        await wait_until(_sigtstp_handled, 10)
        signal.raise_signal(STOP)
        code = await asyncio.wait_for(task, WAIT)
        assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL  # the command's handler is gone
    finally:
        signal.signal(signal.SIGTERM, previous)
    captured = capsys.readouterr()
    assert code == cli.EXIT_INTERRUPTED, captured
    assert captured.out.splitlines()[-1] == "Summary: 0 done, 0 failed, 1 cancelled, 0 not queued."
    assert states(server) == {job_id: JobState.CANCELLED}


@pytest.mark.parametrize(
    ("attached", "answers"),
    [(True, True), (False, True), (True, False)],
    ids=["attached", "not attached", "the saved queue"],
)
async def test_after_a_lost_connection_the_owners_states_are_reported(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    attached: bool,
    answers: bool,
) -> None:
    """The connection ends while the owner runs on (as when the owner's keepalive gives up on
    a stopped client). The owner cancels an attached job; one that is not attached any more
    (as after a Ctrl+Z) runs on. The command reports what the owner says, or else what the
    saved queue says, not a guess."""
    server.api.fake.set_scenario(HANG)
    server.publish()
    task = asyncio.create_task(
        cli.run_encode([server.api.media_file("A.mkv")], preset=None, output=None)
    )
    job_id = await job_of(server, "A.mkv", JobState.RUNNING)
    if not attached:
        server.api.app.state.hub.release(job_id)
    connect = cli.connect_owner
    after = JobState.CANCELLED if attached else JobState.RUNNING

    def saved() -> JobState | None:
        return {job.id: job.state for job in read_saved_queue(server.data_dir).jobs}.get(job_id)

    async def after_the_owner_acted(*args: Any, **kwargs: Any) -> Any:
        await wait_until(lambda: states(server)[job_id] is after)
        if answers:
            return await connect(*args, **kwargs)
        # The owner changes a job's state before it saves it.
        await wait_until(lambda: saved() is after)
        return "no Reframe server answers"

    monkeypatch.setattr(cli, "connect_owner", after_the_owner_acted)
    [connection] = _open_connections(server)
    connection.transport.abort()
    code = await asyncio.wait_for(task, WAIT)
    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert code == cli.EXIT_FAILED
    assert "error: the connection to the Reframe server was lost." in captured.err
    if attached:
        assert "[1/1] cancelled" in lines
        assert lines[-1] == "Summary: 0 done, 0 failed, 1 cancelled, 0 not queued."
    else:
        assert "[1/1] interrupted" not in lines
        assert lines[-1] == "Summary: 0 done, 0 failed, 0 cancelled, 1 not finished, 0 not queued."
        await server.api.reframe.queue.cancel(job_id)


@pytest.mark.skipif(sys.platform == "win32", reason="no job control on Windows")
async def test_a_command_that_cannot_reach_the_owner_after_a_stop(
    server: Server, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    server.api.fake.set_scenario(HANG)
    server.publish()

    async def no_owner(*_args: object, **_kwargs: object) -> str:
        return "no Reframe server answers for this data folder"

    def stopped() -> None:
        monkeypatch.setattr(cli, "connect_owner", no_owner)

    monkeypatch.setattr(cli, "_stop_process", stopped)
    task = asyncio.create_task(
        cli.run_encode([server.api.media_file("A.mkv")], preset=None, output=None)
    )
    job_id = await job_of(server, "A.mkv", JobState.RUNNING)
    await wait_until(_sigtstp_handled, 10)
    signal.raise_signal(STOP)
    code = await asyncio.wait_for(task, WAIT)
    captured = capsys.readouterr()
    assert code == cli.EXIT_FAILED
    assert captured.err.endswith(
        "error: the Reframe server cannot be reached after the stop (no Reframe server answers "
        "for this data folder).\n"
    )
    assert states(server) == {job_id: JobState.PAUSED}  # detached: it waits for a resume
    await server.api.reframe.queue.cancel(job_id)


async def test_detach_reports_a_job_that_another_front_end_removed_before_it_started(
    server: Server, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    queue = server.api.reframe.queue
    add = queue.add
    added: list[str] = []

    async def add_then_remove_the_first(*args: Any, **kwargs: Any) -> Any:
        job = await add(*args, **kwargs)
        added.append(job.id)
        if len(added) == 2:
            await queue.remove(added[0])
        return job

    monkeypatch.setattr(queue, "add", add_then_remove_the_first)
    server.publish()
    files = [server.api.media_file(f"{name}.mkv") for name in ("A", "B")]
    code = await cli.run_encode(files, preset=None, output=None, detach=True)
    lines = capsys.readouterr().out.splitlines()
    assert code == cli.EXIT_FAILED
    assert "[1/2] removed" in lines
    assert f"[2/2] job {added[1]}" in lines
    [ended] = await asyncio.wait_for(queue.wait([added[1]]), WAIT)
    assert ended.state is JobState.DONE


async def test_ctrl_c_while_an_add_fails(
    server: Server, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The owner refuses the add that is under way at Ctrl+C (it is shutting down)."""
    from reframe.service import ReframeClosedError

    queue = server.api.reframe.queue
    add = queue.add
    entered = asyncio.Event()

    async def refuse_the_second(*args: Any, **kwargs: Any) -> Any:
        if entered.is_set():
            raise AssertionError("a third add")
        if queue.list():
            entered.set()
            await asyncio.sleep(0.5)
            raise ReframeClosedError
        return await add(*args, **kwargs)

    monkeypatch.setattr(queue, "add", refuse_the_second)
    server.publish()
    files = [server.api.media_file(f"{name}.mkv") for name in ("A", "B")]
    task = asyncio.create_task(cli.run_encode(files, preset=None, output=None))
    await asyncio.wait_for(entered.wait(), WAIT)
    task.cancel()
    code = await asyncio.wait_for(task, WAIT)
    lines = capsys.readouterr().out.splitlines()
    assert code == cli.EXIT_INTERRUPTED
    assert lines[-1] == "Summary: 0 done, 0 failed, 1 cancelled, 1 not queued."


def _slow_second_add(
    server: Server, monkeypatch: pytest.MonkeyPatch, seconds: float
) -> asyncio.Event:
    """The owner's second add answers ``seconds`` after the job is in the queue (attached); the
    event is set when that job is in."""
    queue = server.api.reframe.queue
    add = queue.add
    added: list[str] = []
    entered = asyncio.Event()

    async def slow_add(*args: Any, **kwargs: Any) -> Any:
        job = await add(*args, **kwargs)
        added.append(job.id)
        if len(added) == 2:
            entered.set()
            await asyncio.sleep(seconds)
        return job

    monkeypatch.setattr(queue, "add", slow_add)
    return entered


async def test_ctrl_c_while_detach_adds_a_job_leaves_no_job_behind(
    server: Server, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The job whose ``POST /api/queue`` is under way at Ctrl+C is in the queue already: the
    command learns of it and cancels it with the other one."""
    server.publish()
    entered = _slow_second_add(server, monkeypatch, 0.5)
    files = [server.api.media_file(f"{name}.mkv") for name in ("A", "B")]
    task = asyncio.create_task(cli.run_encode(files, preset=None, output=None, detach=True))
    await asyncio.wait_for(entered.wait(), WAIT)
    task.cancel()
    code = await asyncio.wait_for(task, WAIT)
    lines = capsys.readouterr().out.splitlines()
    assert code == cli.EXIT_INTERRUPTED
    assert lines[-1] == "Summary: 0 done, 0 failed, 2 cancelled, 0 not queued."
    assert sorted(states(server).values()) == [JobState.CANCELLED] * 2


async def test_a_detach_that_was_interrupted_leaves_its_jobs_to_the_owners_cancel(
    server: Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The add under way at Ctrl+C does not answer in time: the command ends without the
    ``detach`` message, so the owner cancels that job when the connection ends."""
    monkeypatch.setattr(cli, "ADD_WAIT", 0.2, raising=False)
    server.publish()
    entered = _slow_second_add(server, monkeypatch, 2.0)
    files = [server.api.media_file(f"{name}.mkv") for name in ("A", "B")]
    task = asyncio.create_task(cli.run_encode(files, preset=None, output=None, detach=True))
    await asyncio.wait_for(entered.wait(), WAIT)
    task.cancel()
    assert await asyncio.wait_for(task, WAIT) == cli.EXIT_INTERRUPTED
    await wait_until(lambda: sorted(states(server).values()) == [JobState.CANCELLED] * 2)


@asynccontextmanager
async def stoppable(api: Api) -> AsyncIterator[uvicorn.Server]:
    """``api`` served over TCP as ``Api.live`` does, with the uvicorn server at hand to stop."""
    served = uvicorn.Server(
        uvicorn.Config(api.app, host="127.0.0.1", port=0, lifespan="off", log_level="warning")
    )
    running = asyncio.create_task(served.serve())
    try:
        await wait_until(lambda: served.started or running.done())
        yield served
    finally:
        served.should_exit = True
        await running


async def test_an_owner_that_stops_while_the_jobs_are_added(
    make_api: ApiFactory, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The owner stops (as on SIGTERM) after the command's second add: the jobs that were added
    stay waiting in the saved queue, and the error names them."""
    from reframe_testing.server import LiveServer

    async with make_api(mode="desktop") as api, stoppable(api) as served:
        port = served.servers[0].sockets[0].getsockname()[1]
        Server(api, LiveServer(port)).publish()
        queue = api.reframe.queue
        add = queue.add
        added: list[str] = []

        async def add_then_stop(*args: Any, **kwargs: Any) -> Any:
            job = await add(*args, **kwargs)
            added.append(job.id)
            if len(added) == 2:
                served.should_exit = True
                await wait_until(lambda: not served.servers[0].is_serving())
            return job

        monkeypatch.setattr(queue, "add", add_then_stop)
        files = [api.media_file(f"{name}.mkv") for name in ("A", "B", "C")]
        code = await asyncio.wait_for(cli.run_encode(files, preset=None, output=None), WAIT)
        jobs = api.reframe.queue.list()
        await api.reframe.queue.cancel()
    captured = capsys.readouterr()
    assert code == cli.EXIT_FAILED
    assert [job.state for job in jobs] == [JobState.WAITING] * 2
    named = ", ".join(job.id[:8] for job in jobs)
    assert (
        "The waiting jobs stay in the queue, not started: reframe queue retry ID starts one, "
        f"reframe queue cancel ID cancels it ({named})."
    ) in captured.err
    last = captured.out.splitlines()[-1]
    assert last == "Summary: 0 done, 0 failed, 0 cancelled, 2 not finished, 1 not queued."


async def test_a_command_that_ends_by_an_unexpected_error_leaves_no_job_behind(
    server: Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only ``--detach`` keeps the jobs when the command ends: a bug in the command (here: in
    its progress view) ends its connection without the ``detach`` message."""
    server.api.fake.set_scenario(HANG)
    server.publish()

    def broken(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("a bug")

    monkeypatch.setattr(cli, "EncodeView", broken)
    with pytest.raises(RuntimeError, match="a bug"):
        await asyncio.wait_for(
            cli.run_encode([server.api.media_file("A.mkv")], preset=None, output=None), WAIT
        )
    [job] = server.api.reframe.queue.list()
    [ended] = await asyncio.wait_for(server.api.reframe.queue.wait([job.id]), WAIT)
    assert ended.state is JobState.CANCELLED


class _RecordingExecutor:
    """A power executor that only records: the operating system is never asked."""

    def __init__(self) -> None:
        self.actions: list[OsAction] = []

    async def execute(self, action: OsAction) -> str | None:
        self.actions.append(action)
        return None


@pytest.fixture
async def owner_with_power(
    make_api: ApiFactory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> AsyncIterator[tuple[Server, _RecordingExecutor]]:
    """An owner whose power service only records and whose when-done setting is shutdown. The
    command's own settings (another config folder) say "nothing"."""
    import reframe.service as service_module

    executor = _RecordingExecutor()

    def recording(events: EventBus, **_options: object) -> PowerService:
        return PowerService(events, executor=executor)

    monkeypatch.setattr(service_module, "create_power_service", recording)
    async with serving(make_api) as server:
        update = [{"op": "replace", "path": "/queue/when_done", "value": "shutdown"}]
        await server.api.reframe.settings.update(update)
        own = tmp_path / "client-config"
        own.mkdir()
        settings = {"encoders": {"hardware_tests": False}, "queue": {"sleep_inhibit": False}}
        (own / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
        monkeypatch.setenv("REFRAME_CONFIG_DIR", str(own))
        yield server, executor


async def test_the_owners_countdown_is_shown_and_ctrl_c_cancels_it(
    owner_with_power: tuple[Server, _RecordingExecutor],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    server, executor = owner_with_power
    shown = asyncio.Event()
    show = cli.CountdownView.show

    def showing(self: cli.CountdownView, event: PowerCountdownEvent) -> None:
        show(self, event)
        shown.set()

    monkeypatch.setattr(cli.CountdownView, "show", showing)
    server.publish()
    task = asyncio.create_task(
        cli.run_encode([server.api.media_file("A.mkv")], preset=None, output=None)
    )
    await asyncio.wait_for(shown.wait(), WAIT)
    task.cancel()
    code = await asyncio.wait_for(task, WAIT)
    captured = capsys.readouterr()
    assert code == cli.EXIT_INTERRUPTED
    assert "Shutting down in 60 s — press Ctrl+C to cancel" in captured.out
    assert (
        "Interrupted: the countdown is cancelled, the computer will not shut down." in captured.err
    )
    assert server.api.reframe.power.pending is None
    assert executor.actions == []


def _claimed(server: Server) -> Path:
    """Another front end's waiting job writes ``Same.mkv``: a job of the command with that
    output is added ``failed``."""
    return server.api.output / "Same.mkv"


async def test_a_countdown_that_the_commands_jobs_did_not_start_is_not_followed(
    server: Server, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The command's only job fails when it is queued, so none of its jobs ran; a countdown
    that another front end's jobs start meanwhile is not the command's to show or cancel. The
    owner's power service is a stand-in that only reports that countdown."""
    foreign = PowerCountdownEvent(
        countdown_id="ui", action="shutdown", phase="tick", seconds_left=42
    )
    pending: list[PowerCountdownEvent] = []
    cancels: list[str | None] = []

    def cancel(_self: PowerService, countdown_id: str | None = None) -> bool:
        cancels.append(countdown_id)
        return True

    monkeypatch.setattr(PowerService, "pending", property(lambda _self: next(iter(pending), None)))
    monkeypatch.setattr(PowerService, "cancel", cancel)

    async def shutdown(_self: RemoteQueue) -> str:
        return "shutdown"

    monkeypatch.setattr(RemoteQueue, "when_done", shutdown)
    queue = server.api.reframe.queue
    await queue.add(await server.job("Other.mkv", output=_claimed(server).name))
    add = queue.add

    async def add_then_countdown(*args: Any, **kwargs: Any) -> Any:
        job = await add(*args, **kwargs)
        pending.append(foreign)
        server.api.reframe.events.publish(foreign)
        return job

    monkeypatch.setattr(queue, "add", add_then_countdown)
    server.publish()
    mine = server.api.media_file("Mine.mkv")
    code = await asyncio.wait_for(cli.run_encode([mine], preset=None, output=_claimed(server)), 10)
    out = capsys.readouterr().out
    assert code == cli.EXIT_FAILED
    assert "Shutting down" not in out
    assert "ui" not in cancels


async def test_a_job_that_the_owner_adds_failed_is_not_counted_as_queued(
    server: Server, capsys: pytest.CaptureFixture[str]
) -> None:
    await server.api.reframe.queue.add(await server.job("Other.mkv", output=_claimed(server).name))
    server.publish()
    mine = server.api.media_file("Mine.mkv")
    code = await cli.run_encode([mine], preset=None, output=_claimed(server))
    out = capsys.readouterr().out
    assert code == cli.EXIT_FAILED
    assert "[1/1] failed when it was queued:" in out
    assert "Queued" not in out
