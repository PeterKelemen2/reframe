"""The Docker image's settings against the code that reads them: the server ignores an
unknown ``REFRAME_*`` variable, so a renamed setting would leave the image without it."""

from __future__ import annotations

import os
import shlex
from pathlib import Path

import pytest

from reframe import paths
from reframe_server.config import ServerConfig, is_loopback

DOCKERFILE = Path(__file__).resolve().parents[3] / "docker" / "Dockerfile"


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
    env = image_env()
    read = {f"REFRAME_{name.upper()}" for name in ServerConfig.model_fields}
    read |= {paths.CONFIG_DIR_ENV, paths.DATA_DIR_ENV, paths.CACHE_DIR_ENV}
    assert {name for name in env if name.startswith("REFRAME_")} <= read
    # The server refuses a static_dir without index.html, and the image's build is not here.
    assert Path(env["REFRAME_STATIC_DIR"]) == copied_from("frontend")
    build = tmp_path / "frontend"
    build.mkdir()
    (build / "index.html").touch()
    env["REFRAME_STATIC_DIR"] = str(build)
    for name in os.environ:
        if name.startswith("REFRAME_"):
            monkeypatch.delenv(name)
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    config = ServerConfig()

    assert (config.mode, config.auth_mode) == ("web", "password")
    assert not is_loopback(config.host)
    assert config.media_roots == [Path("/media")]
    assert config.output_roots == [Path("/output")]
    assert config.static_dir == build


def test_the_image_puts_ffmpeg_where_discovery_finds_the_bundled_build() -> None:
    ffmpeg = copied_from("tools")
    environ = {paths.DATA_DIR_ENV: "/data"}
    roots = paths.bundled_tool_roots(environ=environ, frozen=False, platform="linux")

    assert ffmpeg.name == paths.BUNDLED_SUBDIRS["ffmpeg"]
    assert ffmpeg.parent in roots
    assert roots.index(ffmpeg.parent) < roots.index(paths.data_dir(environ) / "tools")
