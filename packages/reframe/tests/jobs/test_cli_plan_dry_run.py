"""``reframe plan`` runs the one-frame dry run (C-6) when the job has custom encoder parameters
(C-15). The dry run itself is C-6's; here ``JobService.dry_run`` is replaced, so these tests
check only what the CLI asks for and how it prints the result."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from reframe.cli import DRY_RUN_NOTE, EXIT_FAILED, EXIT_OK, needs_dry_run
from reframe.jobs import JobService
from reframe.models import JobSettings, MediaSource, Severity, ValidationIssue
from reframe.presets import builtin_presets
from reframe_testing import fake_tools as ft

from .conftest import invoke, media_file, replay

CUSTOM = "Custom x265"


@pytest.fixture
def movie(cli_env: ft.FakeTools, tmp_path: Path) -> Path:
    replay(cli_env, "truehd-atmos")
    base = next(p for p in builtin_presets() if p.id == "h265-mkv-1080p")
    preset = base.model_copy(
        update={"id": "u-custom", "name": CUSTOM, "category": "Custom", "built_in": False},
        deep=True,
    )
    preset.video.custom_params = "aq-mode=3:psy-rd=2.0"
    folder = tmp_path / "config"
    folder.mkdir(parents=True)
    (folder / "presets.json").write_text(
        json.dumps({"schema_version": 1, "presets": [preset.model_dump(mode="json")]}),
        encoding="utf-8",
    )
    return media_file(tmp_path / "media" / "Movie.2016.1080p.BluRay-GRP", "movie.mkv")


class DryRun:
    """Replaces ``JobService.dry_run``: records the custom parameters, returns ``issues``."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[str] = []
        self.issues: list[ValidationIssue] = []
        recorder = self

        async def dry_run(
            self: JobService, job: JobSettings, source: MediaSource | None = None
        ) -> list[ValidationIssue]:
            recorder.calls.append(job.video.custom_params)
            return list(recorder.issues)

        monkeypatch.setattr(JobService, "dry_run", dry_run)


@pytest.fixture
def dry_run(monkeypatch: pytest.MonkeyPatch) -> DryRun:
    return DryRun(monkeypatch)


REFUSED = ValidationIssue(
    severity=Severity.ERROR,
    code="video.custom_params_rejected",
    path="video.custom_params",
    message="x265 refuses psy-rd=2.0: [error] invalid value",
)


def test_custom_parameters_are_dry_run_and_errors_printed(movie: Path, dry_run: DryRun) -> None:
    dry_run.issues = [REFUSED]
    result = invoke("plan", str(movie), "--preset", CUSTOM)
    assert result.exit_code == EXIT_FAILED, result.output
    assert dry_run.calls == ["aq-mode=3:psy-rd=2.0"]
    out = result.stdout
    assert "Issues (1 error, " in out
    assert "  error    x265 refuses psy-rd=2.0: [error] invalid value" in out
    assert "[video.custom_params_rejected · video.custom_params]" in out
    assert out.rstrip().endswith("No command: the job has errors.")
    assert DRY_RUN_NOTE not in out
    assert "Traceback" not in result.stderr


def test_dry_run_errors_in_json(movie: Path, dry_run: DryRun) -> None:
    dry_run.issues = [REFUSED]
    result = invoke("plan", str(movie), "--preset", CUSTOM, "--json")
    assert result.exit_code == EXIT_FAILED
    data: dict[str, Any] = json.loads(result.stdout)
    assert data["plan"] is None
    assert "video.custom_params_rejected" in [i["code"] for i in data["draft"]["issues"]]


def test_a_passing_dry_run_is_a_note_and_the_command_follows(movie: Path, dry_run: DryRun) -> None:
    result = invoke("plan", str(movie), "--preset", CUSTOM)
    assert result.exit_code == EXIT_OK, result.output
    assert dry_run.calls == ["aq-mode=3:psy-rd=2.0"]
    assert f"  Note     {DRY_RUN_NOTE}" in result.stdout
    assert "Command (encode, " in result.stdout
    assert "aq-mode=3:psy-rd=2.0" in result.stdout


@pytest.mark.parametrize("preset", ["Fast 1080p30", "H.265 MKV 1080p"])
def test_no_dry_run_without_custom_or_with_builtin_parameters(
    movie: Path, dry_run: DryRun, preset: str
) -> None:
    """*Fast 1080p30* has no custom parameters; the default *H.265 MKV 1080p* has its own,
    unchanged (decision 0038: those are not dry-run)."""
    result = invoke("plan", str(movie), "--preset", preset)
    assert result.exit_code == EXIT_OK, result.output
    assert dry_run.calls == []
    assert DRY_RUN_NOTE not in result.stdout


def test_needs_dry_run() -> None:
    job = JobSettings.model_validate({"source": {"path": "/a.mkv"}})
    assert not needs_dry_run(job)
    job.video.custom_params = "  "
    assert not needs_dry_run(job)
    job.video.custom_params = "aq-mode=3"
    assert needs_dry_run(job)
    job.video.passthrough = True
    assert not needs_dry_run(job)
    job.video.passthrough = False
    builtin = next(p for p in builtin_presets() if p.id == "h265-mkv-1080p")
    job.video.encoder = builtin.video.encoder
    job.video.custom_params = builtin.video.custom_params
    assert not needs_dry_run(job, builtin)
    job.video.custom_params += ":aq-strength=1.2"
    assert needs_dry_run(job, builtin)
    user = builtin.model_copy(update={"built_in": False, "id": "u"})
    job.video.custom_params = builtin.video.custom_params
    assert needs_dry_run(job, user)
