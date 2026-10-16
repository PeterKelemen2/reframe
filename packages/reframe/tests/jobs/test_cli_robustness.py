"""M2 review findings on the CLI: warnings of the core are shown, and nothing ends in a
traceback (not even a file name that is not valid UTF-8)."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from reframe import cli
from reframe.cli import EXIT_FAILED, EXIT_OK
from reframe.jobs import JobService
from reframe.models import AppWarningEvent
from reframe.service import Reframe
from reframe_testing import fake_tools as ft

from .conftest import invoke, media_file, replay
from .fake_queue import FakeQueue


def warning_event(code: str) -> AppWarningEvent:
    return AppWarningEvent(code=code, message=f"Something about {code}.", detail="the detail")


def publish_on_find_preset(monkeypatch: pytest.MonkeyPatch, code: str) -> None:
    """``plan``, ``encode`` and ``name`` look up the preset after the facade is made: the
    warning is published there, on the real bus."""
    original = cli.find_preset

    def find(app: Reframe, name: str | None) -> Any:
        app.events.publish(warning_event(code))
        return original(app, name)

    monkeypatch.setattr(cli, "find_preset", find)


@pytest.mark.parametrize("code", ["queue.store_busy"])
def test_app_warnings_are_printed(
    cli_env: ft.FakeTools, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, code: str
) -> None:
    publish_on_find_preset(monkeypatch, code)
    result = invoke("name", str(tmp_path / "Movie.2016.mkv"))
    assert result.exit_code == EXIT_OK, result.output
    assert result.stderr.splitlines() == [f"warning: Something about {code}. (the detail)"]
    assert "warning:" not in result.stdout


@pytest.mark.parametrize("command", ["plan", "encode"])
def test_plan_and_encode_print_warnings(
    cli_env: ft.FakeTools, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, command: str
) -> None:
    replay(cli_env, "truehd-atmos")
    movie = media_file(tmp_path / "media" / "Movie.2016.1080p-GRP", "movie.mkv")
    publish_on_find_preset(monkeypatch, "queue.store_busy")
    monkeypatch.setattr(cli, "get_queue", lambda app: FakeQueue(app.events, log_dir=tmp_path))
    result = invoke(command, str(movie))
    assert result.exit_code == EXIT_OK, result.output
    assert "warning: Something about queue.store_busy. (the detail)" in result.stderr.splitlines()


def test_warnings_while_closing_are_printed(
    cli_env: ft.FakeTools, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``reframe encoders`` (no preset lookup): a warning published while Reframe closes
    (when-done, a failed queue write) is still printed."""
    original = Reframe.close

    async def close(self: Reframe) -> None:
        if not self.closed:
            self.events.publish(warning_event("queue.when_done_unavailable"))
        await original(self)

    monkeypatch.setattr(Reframe, "close", close)
    result = invoke("encoders")
    assert result.exit_code == EXIT_OK, result.output
    assert result.stderr.splitlines() == [
        "warning: Something about queue.when_done_unavailable. (the detail)"
    ]


def test_start_up_problems_of_settings_and_presets(cli_env: ft.FakeTools, tmp_path: Path) -> None:
    """The settings are read in ``Reframe.create()``, before anything can subscribe: their
    problems are kept in ``settings.problems`` and printed from there, once."""
    config = tmp_path / "config"
    config.mkdir()
    (config / "settings.json").write_text("{not json", encoding="utf-8")
    (config / "presets.json").write_text("[1, 2", encoding="utf-8")
    result = invoke("name", str(tmp_path / "Movie.2016.mkv"))
    assert result.exit_code == EXIT_OK, result.output
    lines = result.stderr.splitlines()
    assert len(lines) == 2, lines
    assert lines[0].startswith("warning: ")
    assert "settings" in lines[0].lower()
    assert lines[1].startswith("warning: ")
    assert "preset" in lines[1].lower()


# --------------------------------------------------------------------------- never a traceback


def test_an_unexpected_error_is_one_line(
    cli_env: ft.FakeTools, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def broken(*_args: object, **_kw: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(JobService, "name", broken)
    result = invoke("name", str(tmp_path / "a.mkv"))
    assert result.exit_code == EXIT_FAILED
    assert result.stdout == ""
    assert result.stderr.splitlines() == [
        "error: unexpected error (RuntimeError: boom). Please report this; "
        "REFRAME_TRACEBACK=1 shows the traceback."
    ]


def test_traceback_on_request(
    cli_env: ft.FakeTools, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def broken(*_args: object, **_kw: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(JobService, "name", broken)
    result = invoke("name", str(tmp_path / "a.mkv"), env={"REFRAME_TRACEBACK": "1"})
    assert result.exit_code == 1
    assert isinstance(result.exception, RuntimeError)


def test_display_path_replaces_undecodable_bytes() -> None:
    name = os.fsdecode(b"bad\xffname.mkv") if sys.platform != "win32" else "bad\udcffname.mkv"
    assert cli.display_path(Path("/m") / name).endswith("bad�name.mkv")
    assert cli.display_path(Path("/m/ok.mkv")) == str(Path("/m/ok.mkv"))


BAD = b"bad\xffname.mkv"
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="Windows names are UTF-16")


def bad_file(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / os.fsdecode(BAD)
    path.write_bytes(b"placeholder")
    return path


@posix_only
def test_name_of_an_undecodable_file_name(cli_env: ft.FakeTools, tmp_path: Path) -> None:
    bad_file(tmp_path / "media")
    result = invoke("name", str(tmp_path / "media"))
    assert result.exit_code == EXIT_OK, (result.output, result.exception)
    assert "bad�name.mkv" in result.stdout


def _replay_bad(cli_env: ft.FakeTools, tmp_path: Path) -> Path:
    replay(cli_env, "truehd-atmos")
    return bad_file(tmp_path / "media" / "Movie.2016.1080p-GRP")


@posix_only
def test_plan_of_an_undecodable_file_name(cli_env: ft.FakeTools, tmp_path: Path) -> None:
    path = _replay_bad(cli_env, tmp_path)
    result = invoke("plan", str(path))
    assert result.exit_code == EXIT_OK, (result.output, result.exception)
    assert result.stdout.startswith("bad�name.mkv\n")


@posix_only
def test_encode_of_an_undecodable_file_name(
    cli_env: ft.FakeTools, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _replay_bad(cli_env, tmp_path)
    monkeypatch.setattr(cli, "get_queue", lambda app: FakeQueue(app.events, log_dir=tmp_path))
    result = invoke("encode", str(path.parent))
    assert result.exit_code == EXIT_OK, (result.output, result.exception)
    assert "[1/1] bad�name.mkv → " in result.stdout


Factory = Callable[[Reframe], FakeQueue]


def test_json_of_an_undecodable_name_is_escaped(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from reframe.models import SourceRef

    ref = SourceRef(path=Path("/m") / "bad\udcffname.mkv")
    cli._write_model_json(ref)
    out = capsys.readouterr().out
    assert "bad\\udcffname.mkv" in out
