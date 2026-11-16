"""The desktop sidecar of ``desktop/sidecar/build.py``: the frozen server starts, answers from the
data files it must bundle, and ends with its encode when the process that started it ends; the
frozen CLI next to it uses it as its owner. CI does not build the sidecar, so those tests are
skipped without it. The package scripts that link the CLI as ``/usr/bin/reframe`` run on any
Linux."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx
import psutil
import pytest

import reframe
from reframe_server import parent
from reframe_testing import fake_tools as ft
from reframe_testing import media
from reframe_testing.processes import ready_port
from reframe_testing.server import PROBE_RULE

REPO = Path(__file__).resolve().parents[3]
SIDECAR = REPO / "desktop" / "src-tauri" / "resources" / "sidecar"
FROZEN = SIDECAR / "reframe-server"
FROZEN_CLI = SIDECAR / "reframe"
PACKAGE_SCRIPTS = REPO / "desktop" / "src-tauri" / "linux"
TOKEN = "frozen-test-" + "x" * 32
RELEASE_NAME = "Show.Name.S01E02.1080p.BluRay.x264-GRP.mkv"

needs_sidecar = pytest.mark.skipif(
    not (FROZEN.is_file() and FROZEN_CLI.is_file()),
    reason=f"no sidecar build in {SIDECAR} (CI does not build it; "
    "`uv run python desktop/sidecar/build.py` does)",
)


@dataclass
class Frozen:
    process: subprocess.Popen[bytes]
    client: httpx.Client
    env: dict[str, str]


class StartFrozen(Protocol):
    def __call__(self, parent_pid: int | None = None, *, real_tools: bool = False) -> Frozen: ...


@pytest.fixture
def frozen_env(tmp_path: Path, fake_tools: ft.FakeTools) -> dict[str, str]:
    """The environment of a frozen program: its own folders, the power dry run, and the fake
    tools (every probe answers with the ``multitrack`` fixture)."""
    fake_tools.set_scenario(ft.Scenario([PROBE_RULE]))
    env = {k: v for k, v in os.environ.items() if not k.startswith("REFRAME_")}
    for name in ("config", "data", "cache"):
        env[f"REFRAME_{name.upper()}_DIR"] = str(tmp_path / name)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "settings.json").write_text(
        json.dumps({"encoders": {"hardware_tests": False}, "queue": {"sleep_inhibit": False}}),
        encoding="utf-8",
    )
    env |= {
        "REFRAME_FFMPEG": str(fake_tools.ffmpeg),
        "REFRAME_FFPROBE": str(fake_tools.ffprobe),
        "REFRAME_POWER_DRY_RUN": "1",
    }
    return env


@pytest.fixture
def start_frozen(frozen_env: dict[str, str]) -> Iterator[StartFrozen]:
    """``start(parent_pid=None, real_tools=False)``: the frozen server in desktop mode, with the
    fake tools or the real FFmpeg."""
    started: list[Frozen] = []

    def start(parent_pid: int | None = None, *, real_tools: bool = False) -> Frozen:
        env = frozen_env | {"REFRAME_TOKEN": TOKEN}
        if real_tools:
            env["REFRAME_FFMPEG"] = media.find_ffmpeg() or env["REFRAME_FFMPEG"]
            env["REFRAME_FFPROBE"] = media.find_ffprobe() or env["REFRAME_FFPROBE"]
        argv = [str(FROZEN), "--mode", "desktop", "--port", "0"]
        if parent_pid is not None:
            argv += ["--parent-pid", str(parent_pid)]
        process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
        client = httpx.Client(
            base_url=f"http://127.0.0.1:{ready_port(process)}",
            headers={"Authorization": f"Bearer {TOKEN}"},
            timeout=30,
        )
        frozen = Frozen(process, client, env)
        started.append(frozen)
        return frozen

    yield start
    for frozen in started:
        frozen.client.close()
        if frozen.process.poll() is None:
            frozen.process.kill()
            frozen.process.wait()
        assert frozen.process.stdout is not None
        frozen.process.stdout.close()


@pytest.mark.slow
@needs_sidecar
def test_the_frozen_server_answers_from_its_bundled_data(
    start_frozen: StartFrozen, tmp_path: Path
) -> None:
    """A build without a data file starts and answers health, and only fails later."""
    client = start_frozen().client
    assert client.get("/api/health").json()["version"] == reframe.__version__
    definitions = client.get("/api/definitions").json()["definitions"]
    assert "libx265" in definitions["video_encoders"]
    assert client.get("/api/presets").json()["presets"]
    assert client.get("/api/languages").json()["languages"]
    fetch = client.post("/api/system/tools/fetch", json={"build": "no-such-build"}).json()

    def fetched() -> Any:
        task = client.get(f"/api/tasks/{fetch['task_id']}").json()
        return task if task["state"] not in ("queued", "running") else None

    assert "has no build 'no-such-build'" in wait_for(fetched)["error"]
    source = tmp_path / "media" / RELEASE_NAME
    source.parent.mkdir()
    source.write_bytes(b"not really matroska")
    source_id = probe(client, source)["id"]
    [name] = client.post("/api/naming/preview", json={"source_ids": [source_id]}).json()
    fields = name["candidates"][0]["fields"]
    assert (fields["season"], fields["episode"], fields["release_group"]) == (1, 2, "GRP")


def wait_for(check: Callable[[], Any], limit: float = 30.0) -> Any:
    deadline = time.monotonic() + limit
    while (result := check()) is None:
        assert time.monotonic() < deadline, "not in time"
        time.sleep(0.05)
    return result


def probe(client: httpx.Client, path: Path) -> dict[str, Any]:
    accepted = client.post("/api/sources", json={"paths": [str(path)]}).json()

    def probed() -> Any:
        task = client.get(f"/api/tasks/{accepted['task_id']}").json()
        return task["result"] if task["state"] == "done" else None

    source: dict[str, Any] = wait_for(probed)["sources"][0]
    return source


@pytest.mark.needs_ffmpeg
@pytest.mark.slow
@needs_sidecar
def test_the_frozen_server_estimates_the_bit_rates_that_ffprobe_does_not_give(
    start_frozen: StartFrozen, fixture_media: Callable[[str], Path], tmp_path: Path
) -> None:
    """A stream without a bit rate keeps an unknown one, and every rule that reads bit rates
    treats it as too high."""
    source = tmp_path / "media" / "vfr.mkv"
    source.parent.mkdir()
    source.write_bytes(fixture_media("vfr-mkv").read_bytes())
    client = start_frozen(real_tools=True).client
    source_id = probe(client, source)["id"]
    [video] = client.get(f"/api/sources/{source_id}").json()["video"]
    assert video["bitrate"]["source"] == "estimated"
    assert video["bitrate"]["value"] > 0
    assert video["bitrate"]["samples"] > 0


@pytest.mark.needs_ffmpeg
@pytest.mark.slow
@needs_sidecar
def test_the_frozen_cli_names_languages_from_its_bundled_tables(
    frozen_env: dict[str, str], fixture_media: Callable[[str], Path], tmp_path: Path
) -> None:
    """The language libraries are not in the build: without the tables every language is an
    unknown code and every track rule that matches a language fails."""
    tables = SIDECAR / "_internal" / "reframe" / "definitions" / "data"
    assert sorted(p.name for p in tables.glob("language-*.json.gz")) == [
        "language-core.json.gz",
        "language-locale-names.json.gz",
        "language-search.json.gz",
    ]
    env = frozen_env | {"REFRAME_FFMPEG": str(media.find_ffmpeg())}
    env["REFRAME_FFPROBE"] = str(media.find_ffprobe())
    result = run_cli(FROZEN_CLI, "probe", str(fixture_media("multitrack")), env=env, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "jpn Japanese" in result.stdout
    assert "eng English" in result.stdout
    assert "unknown code" not in result.stdout


def older_stand_in() -> subprocess.Popen[bytes]:
    """The shell of the test. It is not the server's ancestor, so it must have started a clock
    tick (10 ms) before the server."""
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    time.sleep(0.03)
    return process


def ffmpeg_processes(pid: int) -> list[psutil.Process]:
    return [p for p in psutil.Process(pid).children(recursive=True) if "ffmpeg" in p.name()]


@pytest.mark.needs_ffmpeg
@pytest.mark.slow
@needs_sidecar
def test_the_frozen_server_and_its_encode_end_with_the_process_that_started_it(
    start_frozen: StartFrozen, fixture_media: Callable[[str], Path], tmp_path: Path
) -> None:
    source = tmp_path / "media" / "hdr10-4k.mkv"
    source.parent.mkdir()
    source.write_bytes(fixture_media("hdr10-4k").read_bytes())
    shell = older_stand_in()
    try:
        frozen = start_frozen(shell.pid, real_tools=True)
        client = frozen.client
        source_id = probe(client, source)["id"]
        job = client.post("/api/jobs/draft", json={"source_id": source_id}).json()["job"]
        job["output"]["path"] = str(tmp_path / "out" / "encoded.mkv")
        job["video"] |= {"encoder": "libx265", "preset": "slow"}
        [added] = client.post("/api/queue", json={"jobs": [job]}).json()
        assert client.post("/api/queue/start").status_code == 204

        def writing() -> Any:
            [queued] = client.get("/api/queue").json()["jobs"]
            assert queued["id"] == added["id"]
            assert queued["state"] in ("waiting", "running"), queued
            return queued if (queued.get("progress") or {}).get("output_size") else None

        part = Path(wait_for(writing, 60)["plan"]["output_tmp"])
        encoders = ffmpeg_processes(frozen.process.pid)
        assert encoders
        assert part.exists()
        shell.kill()
        killed = time.monotonic()
        code = frozen.process.wait(timeout=parent.STOP_LIMIT + 10)
        took = time.monotonic() - killed
    finally:
        shell.kill()
        shell.wait()
    assert code == 0
    assert took < parent.STOP_LIMIT
    _, alive = psutil.wait_procs(encoders, timeout=5)
    assert alive == []
    assert not part.exists()


def run_cli(
    cli: Path, *args: str, env: dict[str, str], cwd: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(cli), *args], env=env, cwd=cwd, capture_output=True, text=True, timeout=60, check=False
    )


@pytest.mark.slow
@needs_sidecar
def test_the_frozen_cli_reports_the_version_of_the_core(
    frozen_env: dict[str, str], tmp_path: Path
) -> None:
    result = run_cli(FROZEN_CLI, "version", env=frozen_env, cwd=tmp_path)
    assert (result.returncode, result.stdout.strip()) == (0, reframe.__version__)


@pytest.mark.slow
@needs_sidecar
def test_the_frozen_cli_hands_its_encode_to_the_running_frozen_server(
    start_frozen: StartFrozen, tmp_path: Path
) -> None:
    frozen = start_frozen()
    source = tmp_path / "media" / "episode.mkv"
    source.parent.mkdir()
    source.write_bytes(b"not really matroska")
    env = {k: v for k, v in frozen.env.items() if k != "REFRAME_TOKEN"}
    out = tmp_path / "out" / "episode.mkv"
    encoded = run_cli(
        FROZEN_CLI, "encode", str(source), "-o", str(out), "--detach", env=env, cwd=tmp_path
    )
    assert encoded.returncode == 0, encoded.stderr
    jobs = frozen.client.get("/api/queue").json()["jobs"]
    assert [job["settings"]["output"]["path"] for job in jobs] == [str(out)]
    assert jobs[0]["id"] in encoded.stdout
    listed = run_cli(FROZEN_CLI, "queue", "list", "--json", env=env, cwd=tmp_path)
    assert listed.returncode == 0, listed.stderr
    assert jobs[0]["id"] in listed.stdout
    assert frozen.process.poll() is None


@pytest.mark.slow
@needs_sidecar
def test_the_frozen_cli_run_through_a_link_starts_the_frozen_server_next_to_its_file(
    frozen_env: dict[str, str], tmp_path: Path
) -> None:
    """``/usr/bin/reframe`` of the packages is a link to the CLI in the sidecar folder."""
    link = tmp_path / "bin" / "reframe"
    link.parent.mkdir()
    link.symlink_to(FROZEN_CLI)
    result = run_cli(link, "queue", "pause", "--all", env=frozen_env, cwd=tmp_path)
    endpoint = Path(frozen_env["REFRAME_DATA_DIR"]) / "server.json"
    owner = psutil.Process(json.loads(endpoint.read_text(encoding="utf-8"))["pid"])
    try:
        assert result.returncode == 0, result.stderr
        assert Path(owner.exe()) == FROZEN
    finally:
        owner.kill()
        owner.wait(10)


def package_script(name: str, root: Path) -> list[str]:
    """``linux/<name>`` with its two absolute paths moved below ``root``."""
    text = (PACKAGE_SCRIPTS / name).read_text(encoding="utf-8")
    for line in ("cli=/usr/lib/Reframe/sidecar/reframe", "link=/usr/bin/reframe"):
        assert line in text
        key, value = line.split("=")
        text = text.replace(line, f"{key}={root}{value}")
    return ["sh", "-c", text, name]


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "usr" / "bin").mkdir(parents=True)
    (tmp_path / "usr" / "lib" / "Reframe" / "sidecar").mkdir(parents=True)
    (tmp_path / "usr" / "lib" / "Reframe" / "sidecar" / "reframe").write_text("cli")
    return tmp_path


def installed(root: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*package_script("link-cli.sh", root), *argv], capture_output=True, text=True, check=True
    )


def removed(root: Path, argument: str) -> None:
    subprocess.run([*package_script("unlink-cli.sh", root), argument], check=True)


skip_windows = pytest.mark.skipif(sys.platform == "win32", reason="Linux package scripts")


@skip_windows
@pytest.mark.parametrize("argv", [["configure"], ["1"]], ids=["deb", "rpm"])
def test_installing_links_the_cli_as_usr_bin_reframe(root: Path, argv: list[str]) -> None:
    installed(root, *argv)
    link = root / "usr" / "bin" / "reframe"
    assert link.readlink() == root / "usr" / "lib" / "Reframe" / "sidecar" / "reframe"
    installed(root, *argv)
    assert link.read_text() == "cli"


@skip_windows
def test_installing_leaves_a_reframe_that_another_package_put_there(root: Path) -> None:
    other = root / "usr" / "bin" / "reframe"
    other.write_text("pip's reframe")
    result = installed(root, "configure")
    assert other.read_text() == "pip's reframe"
    assert not other.is_symlink()
    assert "stays at" in result.stderr


@skip_windows
@pytest.mark.parametrize(
    ("argument", "kept"), [("remove", False), ("0", False), ("upgrade", True), ("1", True)]
)
def test_removing_the_package_removes_the_link_but_an_upgrade_keeps_it(
    root: Path, argument: str, kept: bool
) -> None:
    installed(root, "configure")
    removed(root, argument)
    assert (root / "usr" / "bin" / "reframe").is_symlink() == kept


@skip_windows
def test_removing_the_package_leaves_a_reframe_that_is_not_its_link(root: Path) -> None:
    other = root / "usr" / "bin" / "reframe"
    other.symlink_to(root / "elsewhere")
    removed(root, "remove")
    assert other.is_symlink()
