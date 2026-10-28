"""``reframe encode`` and ``reframe batch`` as clients of the queue's owner: the owner validates
and runs the jobs (no encoder detection here), ``--detach``, Ctrl+C, a server that stops, and the
fallback to the in-process queue with the reason. The owner is the test's server in this event
loop; the CLI runs in the same loop, on the same folders."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from reframe import cli
from reframe.capabilities.service import CapabilityService
from reframe.models import JobDraft, JobState, Severity, ValidationIssue
from reframe.remote import owner as owner_module
from reframe_testing.server import ApiFactory

from .conftest import HANG, Server, poll

pytestmark = pytest.mark.anyio


@pytest.fixture
def detections(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every encoder detection that starts from now on."""
    started: list[str] = []
    start = CapabilityService.start

    def record(self: CapabilityService) -> None:
        started.append("start")
        start(self)

    monkeypatch.setattr(CapabilityService, "start", record)
    return started


@pytest.fixture
def short_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(owner_module, "HELD_WAIT", 0.3)
    monkeypatch.setattr(owner_module, "START_WAIT", 0.3)


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


async def test_a_client_drafts_as_the_in_process_draft(server: Server) -> None:
    app = server.api.reframe
    source = server.api.media_file("Show.S01E02.1080p.BluRay.x264-GRP.mkv")
    preset = app.presets.default()
    local = await app.jobs.draft(source, preset)
    client = await cli.OwnerJobs(app, app.jobs.validate).draft(source, preset)
    assert isinstance(local, JobDraft)
    assert client == local


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
            in_process=options.get("in_process"),
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
    server.api.fake.set_scenario(HANG)
    foreign = await server.api.reframe.queue.add(await server.job("Foreign.mkv"))
    server.publish()
    files = [server.api.media_file(f"{name}.mkv") for name in ("A", "B")]
    task = asyncio.create_task(cli.run_encode(files, preset=None, output=None))
    await poll(lambda: JobState.RUNNING in states(server).values())
    task.cancel()
    assert await asyncio.wait_for(task, 30) == cli.EXIT_INTERRUPTED
    found = states(server)
    assert found.pop(foreign.id) is JobState.WAITING
    assert sorted(found.values()) == [JobState.CANCELLED, JobState.CANCELLED]
    assert not list(server.api.output.glob("*.part.*"))


async def test_a_server_that_stops_while_the_command_follows_its_jobs(
    make_api: ApiFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    async with make_api(mode="desktop") as api:
        api.fake.set_scenario(HANG)
        files = [api.media_file(f"{name}.mkv") for name in ("A", "B")]
        async with api.live() as live:
            Server(api, live).publish()
            task = asyncio.create_task(cli.run_encode(files, preset=None, output=None))
            await poll(lambda: any(j.state is JobState.RUNNING for j in api.reframe.queue.list()))
        code = await asyncio.wait_for(task, 30)
        jobs = api.reframe.queue.list()
        await api.reframe.queue.cancel()
    captured = capsys.readouterr()
    assert code == cli.EXIT_FAILED
    assert "1 interrupted, 1 not finished" in captured.out
    [waiting] = [j.id for j in jobs if j.state is JobState.WAITING]
    assert (
        "error: the Reframe server stopped: its running jobs were interrupted. The waiting jobs "
        "stay in the queue, not started: reframe queue retry ID starts one, reframe queue "
        f"cancel ID cancels it ({waiting[:8]})."
    ) in captured.err


async def test_batch_hands_its_jobs_to_the_owner(
    server: Server, detections: list[str], fixture_season: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    server.publish()
    code = await cli.run_batch([fixture_season], preset=None)
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
