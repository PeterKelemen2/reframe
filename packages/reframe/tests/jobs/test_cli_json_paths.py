"""``--json`` of a file whose name is not UTF-8 (byte 0xFF; Python's lone surrogate): the JSON
holds the path as an escape that gives the exact name back."""

from __future__ import annotations

import json
import os
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from reframe.cli import EXIT_OK
from reframe.models import EncodePlan, JobDraft, MediaSource, NameResult
from reframe_testing import fake_tools as ft

from .conftest import invoke, media_file, replay

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="a file name that is not UTF-8")

NAME = b"bad\xffname.mkv"
FOLDER = "Amélie.2001.1080p-GRP"
#: The path in the JSON text: only the byte that is not UTF-8 is an escape.
IN_JSON = f"/{FOLDER}/bad\\udcffname.mkv"


@pytest.fixture
def bad(cli_env: ft.FakeTools, tmp_path: Path) -> Path:
    replay(cli_env, "truehd-atmos")
    path = media_file(tmp_path / "media" / FOLDER, os.fsdecode(NAME))
    assert os.fsencode(path).endswith(NAME)
    return path


def test_probe_json(bad: Path) -> None:
    result = invoke("probe", "--json", str(bad))
    assert result.exit_code == EXIT_OK, (result.output, result.exception)
    assert IN_JSON in result.stdout
    assert MediaSource.model_validate(json.loads(result.stdout)).ref.path == bad


def test_plan_json(bad: Path) -> None:
    result = invoke("plan", "--json", str(bad))
    assert result.exit_code == EXIT_OK, (result.output, result.exception)
    data = json.loads(result.stdout)
    assert JobDraft.model_validate(data["draft"]).job.source.path == bad
    plan = EncodePlan.model_validate(data["plan"])
    assert any(str(bad) in step.argv for step in plan.steps)  # the command keeps the byte
    assert "bad\ufffdname.mkv" in plan.display


def test_name_json(bad: Path) -> None:
    result = invoke("name", "--json", str(bad))
    assert result.exit_code == EXIT_OK, (result.output, result.exception)
    assert IN_JSON in result.stdout
    [named] = json.loads(result.stdout)
    assert NameResult.model_validate(named).candidates[0].path == bad


@pytest.mark.needs_ffmpeg
def test_probe_json_with_the_real_ffprobe(
    fixture_media: Callable[[str], Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("config", "data", "cache"):
        monkeypatch.setenv(f"REFRAME_{name.upper()}_DIR", str(tmp_path / name))
    copy = tmp_path / "media" / os.fsdecode(NAME)
    copy.parent.mkdir()
    shutil.copy2(fixture_media("multitrack"), copy)
    for _ in ("probed", "from the probe cache"):
        result = invoke("probe", "--json", str(copy))
        assert result.exit_code == EXIT_OK, (result.output, result.exception)
        source = MediaSource.model_validate(json.loads(result.stdout))
        assert source.ref.path == copy
        assert len(source.audio) > 1
