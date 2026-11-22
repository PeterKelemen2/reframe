"""The Docker image's files against the code that reads them: the server ignores an unknown
``REFRAME_*`` variable, so a renamed setting would leave the image without it."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from reframe import paths
from reframe_server.config import ServerConfig, is_loopback
from reframe_testing.server import ApiFactory

DOCKER = Path(__file__).resolve().parents[3] / "docker"
DOCKERFILE = DOCKER / "Dockerfile"
ENTRYPOINT = DOCKER / "entrypoint.sh"
COMPOSE = DOCKER / "compose.example.yml"

linux_only = pytest.mark.skipif(sys.platform == "win32", reason="the image is Linux")


def instructions() -> list[tuple[str, str]]:
    """``(INSTRUCTION, arguments)`` of the final stage, continuation lines joined."""
    text = DOCKERFILE.read_text(encoding="utf-8").replace("\\\n", " ")
    found = [
        (keyword.upper(), rest.strip())
        for keyword, _, rest in (
            line.strip().partition(" ") for line in text.splitlines() if line.strip()
        )
        if not keyword.startswith("#")
    ]
    last_from = max(i for i, (keyword, _) in enumerate(found) if keyword == "FROM")
    return found[last_from:]


def image_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for keyword, rest in instructions():
        if keyword == "ENV":
            env |= dict(token.split("=", 1) for token in shlex.split(rest))
    return env


def use_image_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    env = image_env()
    for name in os.environ:
        if name.startswith("REFRAME_"):
            monkeypatch.delenv(name)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return env


def copied_from(stage: str) -> Path:
    [target] = [
        rest.split()[-1]
        for keyword, rest in instructions()
        if keyword == "COPY" and rest.startswith(f"--from={stage} ")
    ]
    return Path(target)


def test_the_image_starts_a_web_server_with_its_roots_and_the_frontend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env = use_image_env(monkeypatch)
    read = {f"REFRAME_{name.upper()}" for name in ServerConfig.model_fields}
    read |= {paths.CONFIG_DIR_ENV, paths.DATA_DIR_ENV, paths.CACHE_DIR_ENV}
    assert {name for name in env if name.startswith("REFRAME_")} <= read
    # The server refuses a static_dir without index.html, and the image's build is not here.
    assert Path(env["REFRAME_STATIC_DIR"]) == copied_from("frontend")
    build = tmp_path / "frontend"
    build.mkdir()
    (build / "index.html").touch()
    monkeypatch.setenv("REFRAME_STATIC_DIR", str(build))

    config = ServerConfig()

    assert (config.mode, config.auth_mode) == ("web", "password")
    assert not is_loopback(config.host)
    assert config.media_roots == [Path("/media")]
    assert config.output_roots == [Path("/output")]
    assert config.static_dir == build


@linux_only
def test_the_server_keeps_its_files_in_the_mounts_that_the_entrypoint_hands_to_puid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_image_env(monkeypatch)
    # Under `docker run --user` the home is /, so a folder the image does not name is no mount.
    monkeypatch.setenv("HOME", "/")
    for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        monkeypatch.delenv(name, raising=False)
    [handed_over] = re.findall(r"^for dir in (.+); do$", ENTRYPOINT.read_text("utf-8"), re.M)
    owned = [Path(folder) for folder in handed_over.split()]
    mounted = re.findall(r"^ +- [^\s:#]+:(/[^\s:]+)", COMPOSE.read_text("utf-8"), re.M)

    assert {str(folder) for folder in owned} <= set(mounted)
    for folder in (paths.config_dir(), paths.data_dir(), paths.cache_dir()):
        assert any(folder.is_relative_to(base) for base in owned), folder


@pytest.mark.anyio
async def test_the_health_check_asks_a_route_that_answers_without_a_login(
    make_api: ApiFactory,
) -> None:
    [check] = [rest for keyword, rest in instructions() if keyword == "HEALTHCHECK"]
    [path] = re.findall(r"http://127\.0\.0\.1:%s(/[^'\"]*)", check)

    async with make_api(auth="password") as api:
        response = await api.anonymous.get(path)

    assert response.status_code == 200


def test_the_image_has_no_ffmpeg_and_a_download_lands_in_the_data_mount() -> None:
    """A build downloaded in the container must survive a new container: in the bind mount."""
    code = [line for line in DOCKERFILE.read_text("utf-8").splitlines() if not line.startswith("#")]
    assert not re.search(r"ffmpeg|ffprobe|fetch-tools", "\n".join(code), re.IGNORECASE)
    assert not any(rest.startswith("--from=tools ") for keyword, rest in instructions())
    # Without the CA certificates the download's TLS check fails.
    assert any(
        keyword == "RUN" and re.search(r"\bca-certificates=", rest)
        for keyword, rest in instructions()
    )

    environ = {paths.DATA_DIR_ENV: image_env()["REFRAME_DATA_DIR"]}
    download = paths.data_dir(environ) / "tools" / paths.BUNDLED_SUBDIRS["ffmpeg"]
    mounted = re.findall(r"^ +- [^\s:#]+:(/[^\s:]+)", COMPOSE.read_text("utf-8"), re.M)

    assert download.parent in paths.bundled_tool_roots(
        environ=environ, frozen=False, platform="linux"
    )
    assert any(download.is_relative_to(folder) for folder in mounted)


def test_the_amd64_image_has_a_qsv_runtime_for_old_and_new_intel_gpus() -> None:
    """libmfx-gen does not take Intel GPUs before Tiger Lake; they need the Media SDK runtime,
    which Debian 13 does not have. The older suite's source must not stay in the image."""
    [run] = [rest for keyword, rest in instructions() if keyword == "RUN" and "gpu=" in rest]
    amd64 = re.search(r'amd64\) gpu="([^"]*)"', run)
    assert amd64 is not None
    packages = {item.split("=", 1)[0] for item in amd64[1].split()}
    assert {"libmfx-gen1.2", "libmfx1", "intel-media-va-driver-non-free"} <= packages
    sources = re.findall(r">\s*(/etc/apt/\S+)", run)
    assert sources, "libmfx1 comes from Debian 12, so the RUN adds its source"
    removed = re.findall(r"\brm -rf ([^&]*)", run)
    assert all(any(path in cleanup.split() for cleanup in removed) for path in sources)


FAKE_TOOLS = {
    "id": "echo 0",
    "mkdir": ":",
    "stat": 'case "$2" in %g) echo 0 ;; *) echo "$FAKE_OWNER" ;; esac',
    "chown": 'echo "chown $*"',
    "setpriv": 'echo "setpriv $*"',
    "serve": 'echo "as is"',
}
"""Stand-ins that make the entrypoint believe it runs as root, and print what it would do."""


def run_entrypoint(tmp_path: Path, *prefix: str, **env: str) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in FAKE_TOOLS.items():
        tool = bin_dir / name
        tool.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        tool.chmod(0o755)
    environ = {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "FAKE_OWNER": "0:0"}
    return subprocess.run(
        [*prefix, "sh", str(ENTRYPOINT), "serve"],
        env=environ | env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


@linux_only
def test_puid_zero_written_with_leading_zeros_runs_as_root_and_warns_on_a_rootful_host(
    tmp_path: Path,
) -> None:
    if Path("/proc/self/uid_map").read_text("utf-8").split() != ["0", "0", "4294967295"]:
        pytest.skip("the tests run in a user namespace")

    result = run_entrypoint(tmp_path, PUID="00")

    assert result.stdout == "as is\n"
    assert "root on the host" in result.stderr


@linux_only
def test_puid_zero_does_not_warn_where_the_containers_root_is_a_host_user(
    tmp_path: Path,
) -> None:
    unshare = ["unshare", "--user", "--map-root-user"]
    if not shutil.which("unshare") or subprocess.run([*unshare, "true"], check=False).returncode:
        pytest.skip("no unprivileged user namespaces here")

    result = run_entrypoint(tmp_path, *unshare, PUID="0")

    assert (result.stdout, result.stderr) == ("as is\n", "")


@linux_only
def test_a_puid_with_leading_zeros_does_not_walk_the_folders_at_every_start(
    tmp_path: Path,
) -> None:
    result = run_entrypoint(tmp_path, PUID="01000", PGID="1000", FAKE_OWNER="1000:1000")

    assert "chown" not in result.stdout
    assert result.stdout.startswith("setpriv --reuid=1000 --regid=1000 ")
    # Without it a setuid program in the container could take the privileges back.
    assert result.stdout.endswith(" --no-new-privs -- serve\n")


@linux_only
def test_a_puid_that_is_not_a_number_stops_the_container(tmp_path: Path) -> None:
    result = run_entrypoint(tmp_path, PUID="1000x")

    assert (result.returncode, result.stdout) == (2, "")
