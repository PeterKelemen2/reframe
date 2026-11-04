"""The app skeleton: health, the entry point, the token, problem answers and JSON paths that
are not UTF-8."""

from __future__ import annotations

import asyncio
import json
import os
import selectors
import signal
import socket
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel, SecretStr, ValidationError

import reframe_server
from reframe.models import Severity, ValidationIssue
from reframe.probe import ProbeError, ProbeErrorKind
from reframe.queue.errors import JobStateError, UnknownJobError
from reframe.service import ReframeClosedError
from reframe.tasks import TaskContext
from reframe_server import idle
from reframe_server.__main__ import serve
from reframe_server.api import JsonTextResponse, accepted, api_router
from reframe_server.app import create_app
from reframe_server.config import ServerConfig
from reframe_server.deps import ReframeDep
from reframe_server.errors import ProblemError, issue_problem, probe_problem
from reframe_testing.server import BASE_URL, Api, ApiFactory, receive_json

pytestmark = pytest.mark.anyio

BAD = "/media/bad\udcffname.mkv"


async def test_health_answers_without_credentials(api: Api) -> None:
    response = await api.anonymous.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == reframe_server.__version__
    assert body["api_version"] == 1
    assert body["instance"] == api.app.state.instance
    assert body["uptime"] >= 0


def test_each_app_is_a_new_instance() -> None:
    """The CLI tells a restarted server from the one in ``server.json`` by ``instance``."""
    config = ServerConfig()
    assert create_app(config).state.instance != create_app(config).state.instance


async def test_lifespan_closes_the_facade(make_api: ApiFactory) -> None:
    async with make_api() as api:
        reframe = api.reframe
    assert reframe.closed
    assert api.app.state.reframe is None


def test_reframe_token_is_the_runs_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFRAME_TOKEN", "from-the-desktop-shell")
    assert ServerConfig().secret_token == "from-the-desktop-shell"


def test_without_reframe_token_each_run_gets_a_random_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REFRAME_TOKEN", raising=False)
    first, second = ServerConfig().secret_token, ServerConfig().secret_token
    assert first != second
    assert len(first) >= 32


@pytest.mark.parametrize(
    ("host", "allowed"),
    [("localhost", True), ("[::1]", True), ("0.0.0.0", False), ("nas.example", False)],
)
def test_auth_none_only_on_loopback(host: str, allowed: bool) -> None:
    if allowed:
        assert ServerConfig(host=host, auth="none").auth_mode == "none"
    else:
        with pytest.raises(ValidationError, match="loopback"):
            ServerConfig(host=host, auth="none")


def test_unset_auth_off_loopback_is_refused() -> None:
    with pytest.raises(ValidationError, match="auth must be set"):
        ServerConfig(host="0.0.0.0")
    assert ServerConfig(host="127.0.0.1").auth_mode == "none"


def test_desktop_mode_uses_token_auth() -> None:
    assert ServerConfig(mode="desktop").auth_mode == "token"
    with pytest.raises(ValidationError, match="desktop mode always uses token auth"):
        ServerConfig(mode="desktop", auth="password")


def test_bad_options_exit_2(capsys: pytest.CaptureFixture[str]) -> None:
    from reframe_server.__main__ import main

    assert main(["--mode", "desktop", "--auth", "none"]) == 2
    assert "desktop mode always uses token auth" in capsys.readouterr().err


def test_the_token_is_read_once_and_kept_from_the_servers_children(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from reframe_server import __main__ as entry

    seen: dict[str, object] = {}

    async def fake_serve(config: ServerConfig) -> int:
        seen["token"] = config.secret_token
        seen["environment"] = os.environ.get("REFRAME_TOKEN")
        return 0

    monkeypatch.setenv("REFRAME_TOKEN", "the-desktop-token")
    monkeypatch.setattr(entry, "serve", fake_serve)
    assert entry.main(["--mode", "desktop", "--port", "0"]) == 0
    assert seen == {"token": "the-desktop-token", "environment": None}


@pytest.mark.slow
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Popen.send_signal cannot send SIGINT on Windows, and select() takes only sockets",
)
def test_desktop_server_prints_the_ready_line_and_answers_health(
    tmp_path: Path, fake_tools: object
) -> None:
    """``reframe-server`` starts, the shell reads the port from the first stdout line, and
    ``GET /api/health`` answers on it. The run's token never shows in its output."""
    token = "hunter2-" + "x" * 32
    env = {key: value for key, value in os.environ.items() if not key.startswith("REFRAME_")} | {
        "REFRAME_CONFIG_DIR": str(tmp_path / "config"),
        "REFRAME_DATA_DIR": str(tmp_path / "data"),
        "REFRAME_CACHE_DIR": str(tmp_path / "cache"),
        "REFRAME_FFMPEG": str(fake_tools.ffmpeg),  # type: ignore[attr-defined]
        "REFRAME_FFPROBE": str(fake_tools.ffprobe),  # type: ignore[attr-defined]
        "REFRAME_TOKEN": token,
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "reframe_server", "--mode", "desktop", "--port", "0"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
    )
    try:
        assert process.stdout is not None
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            assert selector.select(timeout=60), "no ready line on stdout within 60 s"
        ready = json.loads(process.stdout.readline())
        assert ready == {"event": "ready", "port": ready["port"]}
        assert ready["port"] > 0
        health = httpx.get(
            f"http://127.0.0.1:{ready['port']}/api/health",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        assert health.status_code == 200
        assert health.json()["version"] == reframe_server.__version__
    finally:
        process.send_signal(signal.SIGINT)
        _out, err = process.communicate(timeout=30)
    assert process.returncode == 130, err
    assert "Application shutdown complete" in err
    assert _out == "", "only the ready line may go to stdout"
    assert token not in err


@pytest.mark.skipif(sys.platform == "win32", reason="checked on Linux only (decision 0053)")
def test_a_server_whose_port_is_taken_exits_1(tmp_path: Path, fake_tools: object) -> None:
    """A shell or a CLI that starts the server reads a failed start from the exit code. uvicorn
    ends a failed bind with ``sys.exit(3)`` inside the server's task."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("REFRAME_")} | {
        "REFRAME_CONFIG_DIR": str(tmp_path / "config"),
        "REFRAME_DATA_DIR": str(tmp_path / "data"),
        "REFRAME_CACHE_DIR": str(tmp_path / "cache"),
        "REFRAME_FFMPEG": str(fake_tools.ffmpeg),  # type: ignore[attr-defined]
        "REFRAME_FFPROBE": str(fake_tools.ffprobe),  # type: ignore[attr-defined]
    }
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]
        result = subprocess.run(
            [sys.executable, "-m", "reframe_server", "--mode", "desktop", "--port", str(port)],
            capture_output=True,
            env=env,
            text=True,
            timeout=60,
        )
    assert result.returncode == 1, result.stderr
    assert "Task exception was never retrieved" not in result.stderr
    assert result.stdout == ""


@pytest.mark.usefixtures("make_api")  # the test's own folders, tools and settings
async def test_a_cancel_of_serve_while_its_idle_watch_ends_is_not_lost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``serve()`` waits for its cancelled idle watch at the end; a cancel of ``serve()``
    itself in that time (the event loop's runner on a signal) must still end it cancelled."""
    ending, release = asyncio.Event(), asyncio.Event()

    async def watch(*_args: object) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            ending.set()
            await release.wait()  # a clean-up that takes a moment
            raise

    monkeypatch.setattr(idle, "watch", watch)
    token = "cancel-test-" + "x" * 32
    config = ServerConfig(
        mode="desktop",
        idle_exit=3600,
        token=SecretStr(token),
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
    )
    serving = asyncio.create_task(serve(config))
    printed = ""
    while not printed:
        assert not serving.done()
        await asyncio.sleep(0.02)
        printed = capsys.readouterr().out
    port = json.loads(printed)["port"]
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", headers=headers) as client:
        assert (await client.post("/api/system/shutdown")).status_code == 204
    await asyncio.wait_for(ending.wait(), 30)
    serving.cancel()
    release.set()
    await asyncio.wait((serving,), timeout=10)
    assert serving.cancelled()


class _PathBody(BaseModel):
    path: str


def _probe_routes(app: FastAPI) -> None:
    """Routes that raise each expected failure, mounted the way the real routers are."""
    router = api_router("test")

    @router.post("/echo")
    async def echo(body: _PathBody) -> _PathBody:
        return body

    @router.get("/problem")
    async def problem() -> None:
        raise ProblemError(403, "path.outside_roots", "Outside", "The path is not below a root.")

    @router.get("/issue")
    async def issue() -> None:
        raise issue_problem(
            ValidationIssue(severity=Severity.ERROR, code="preset.builtin", message="Built in")
        )

    @router.get("/probe/{kind}")
    async def probe(kind: ProbeErrorKind) -> None:
        raise probe_problem(ProbeError(Path(BAD), kind, f"Cannot read {BAD}"))

    @router.get("/unknown-job")
    async def unknown_job() -> None:
        raise UnknownJobError("j-1")

    @router.get("/job-state")
    async def job_state() -> None:
        raise JobStateError("job j-1 is running: cancel it first")

    @router.get("/closed")
    async def closed() -> None:
        raise ReframeClosedError

    @router.get("/crash")
    async def crash() -> None:
        raise RuntimeError("secret-internal-detail")

    @router.post("/secret")
    async def secret(body: dict[str, int]) -> None:
        del body

    @router.post("/task")
    async def task(reframe: ReframeDep) -> JsonTextResponse:
        async def work(_ctx: TaskContext) -> None:
            return None

        return accepted(reframe.tasks.start("test", work))

    app.include_router(router, prefix="/t")


@pytest.fixture
async def probe_api(make_api: ApiFactory) -> AsyncIterator[Api]:
    async with make_api() as harness:
        _probe_routes(harness.app)
        yield harness


async def test_a_path_that_is_not_utf8_goes_in_and_out(probe_api: Api) -> None:
    body = json.dumps({"path": BAD})  # ASCII text with a \udcff escape
    response = await probe_api.client.post(
        "/t/echo", content=body, headers={"content-type": "application/json"}
    )
    assert response.status_code == 200
    assert response.content.isascii()
    assert json.loads(response.text) == {"path": BAD}


@pytest.mark.parametrize(
    ("path", "status", "code", "issues"),
    [
        ("/t/problem", 403, "path.outside_roots", []),
        ("/t/issue", 422, "preset.builtin", ["preset.builtin"]),
        ("/t/probe/not_found", 404, "probe.not_found", []),
        ("/t/unknown-job", 404, "queue.unknown_job", []),
        ("/t/job-state", 409, "queue.job_state", []),
        ("/t/closed", 503, "server.closing", []),
        ("/api/no-such-route", 404, "http.404", []),
    ],
)
async def test_expected_failures_are_problems(
    probe_api: Api, path: str, status: int, code: str, issues: list[str]
) -> None:
    response = await probe_api.client.get(path)
    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json"
    problem = response.json()
    assert (problem["status"], problem["code"]) == (status, code)
    assert problem["title"]
    assert [issue["code"] for issue in problem.get("issues", [])] == issues


async def test_a_probe_problem_with_a_path_that_is_not_utf8(probe_api: Api) -> None:
    response = await probe_api.client.get("/t/probe/not_found")
    assert BAD in json.loads(response.text)["title"]


async def test_an_invalid_body_is_not_echoed(probe_api: Api) -> None:
    """The validation error names the field, never the value (it may be a password)."""
    response = await probe_api.client.post("/t/secret", json={"password": "hunter2-secret"})
    assert response.status_code == 422
    assert response.json()["code"] == "request.invalid"
    assert response.json()["errors"][0]["loc"] == ["body", "password"]
    assert "hunter2-secret" not in response.text


async def test_an_unexpected_error_is_a_500_without_its_detail(probe_api: Api) -> None:
    transport = httpx.ASGITransport(app=probe_api.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
        response = await client.get("/t/crash")
    assert response.status_code == 500
    assert response.json()["code"] == "server.unexpected"
    assert "secret-internal-detail" not in response.text


async def test_a_request_after_close_is_503(probe_api: Api) -> None:
    await probe_api.reframe.close()
    response = await probe_api.client.post("/t/task")
    assert (response.status_code, response.json()["code"]) == (503, "server.closing")


async def test_task_events_name_no_server_folder(api: Api) -> None:
    """The event stream shows a task's result as ``GET /api/tasks/{id}`` does: the server's
    cache folder as ``<cache>``."""
    frame = f"{api.reframe.cache_dir}/frames/f.png"

    async def work(_ctx: TaskContext) -> dict[str, str]:
        return {"path": frame}

    async with api.live() as server, server.connect() as connection:
        await connection.send(json.dumps({"type": "auth", "token": api.token}))
        assert (await receive_json(connection))["type"] == "hello"
        task = api.reframe.tasks.start("test", work)
        while True:
            message = await receive_json(connection)
            event = message.get("event", {})
            if event.get("type") == "task.done" and event["task"]["id"] == task.id:
                break
    assert event["task"]["result"] == {"path": "<cache>/frames/f.png"}
