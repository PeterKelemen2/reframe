"""``reframe plan`` (C-15; M2 demo items 2 and 4): the issues, then the FFmpeg command.

Most tests replay recorded probes through the fake ffprobe and detect encoders on the fake
ffmpeg; one runs the real tools on a generated fixture.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest

from reframe import jobs as jobs_module
from reframe.cli import EXIT_FAILED, EXIT_NO_FFPROBE, EXIT_NOT_FOUND, EXIT_OK, EXIT_USAGE
from reframe.models import EncodePlan, JobDraft
from reframe_testing import fake_tools as ft
from reframe_testing.capabilities import c4_rule

from .conftest import invoke, media_file, replay

Media = "Movie.2016.1080p.BluRay.x264-GRP"


@pytest.fixture
def movie(cli_env: ft.FakeTools, tmp_path: Path) -> Path:
    replay(cli_env, "truehd-atmos")
    return media_file(tmp_path / "media" / Media, "movie.mkv")


def section(output: str, title: str) -> list[str]:
    """The lines of a section (``Issues (…)``, ``Command (…)``) up to the next blank line."""
    lines = output.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(title))
    end = next((i for i in range(start + 1, len(lines)) if not lines[i].strip()), len(lines))
    return lines[start + 1 : end]


def test_default_preset_prints_issues_then_the_command(movie: Path, cli_env: ft.FakeTools) -> None:
    result = invoke("plan", str(movie))
    assert result.exit_code == EXIT_OK, result.output
    out = result.stdout
    assert out.startswith("movie.mkv\n")
    assert "  Preset   H.265 MKV 1080p" in out
    assert f"  Output   {movie.parent / 'Movie.mkv'}" in out
    assert "template {main_title} on the folder name" in out
    assert "  Audio    #1  " in out
    assert out.index("Issues (") < out.index("Command (")
    issues = section(out, "Issues (0 errors, 0 warnings, 1 info)")
    assert issues[0].startswith("  info     Crop detection did not run for this job")
    assert "[dimensions.crop_not_detected · dimensions.crop]" in issues[1]
    assert "fix: Do not crop" in issues[2]
    command = section(out, "Command (encode, 2 steps)")
    assert len(command) == 1  # one line, to copy into a terminal
    assert command[0].startswith(f"{cli_env.ffmpeg} -hide_banner")
    assert "-c:v:0 libx265" in command[0]
    assert str(movie.parent / "Movie.part.mkv") in command[0]


def test_preset_by_name_and_output(movie: Path, tmp_path: Path) -> None:
    out = tmp_path / "out" / "My movie"
    out.parent.mkdir()
    result = invoke("plan", str(movie), "--preset", "fast 1080p30", "-o", str(out))
    assert result.exit_code == EXIT_OK, result.output
    assert "  Preset   Fast 1080p30" in result.stdout
    assert f"  Output   {out.parent / 'My movie.mp4'}" in result.stdout
    assert "the manual name My movie" in result.stdout
    assert "-c:v:0 libx264" in result.stdout


def test_unavailable_encoder_fails_and_names_the_closest(
    cli_env: ft.FakeTools, tmp_path: Path
) -> None:
    """Demo item 4 on the real FFmpeg text of a machine without the NVIDIA driver."""
    replay(cli_env, "truehd-atmos", extra=(c4_rule("c4_hevc_nvenc_no_driver"),))
    movie = media_file(tmp_path / "media" / Media, "movie.mkv")
    started = time.monotonic()
    result = invoke("plan", str(movie), "--preset", "H.265 NVENC 1080p")
    assert time.monotonic() - started < 30
    assert result.exit_code == EXIT_FAILED, result.output
    out = result.stdout
    issues = section(out, "Issues (1 error")
    assert issues[0] == (
        "  error    hevc_nvenc (NVIDIA NVENC H.265) is not available: NVIDIA driver not found."
    )
    assert issues[1].strip() == "[encoder.unavailable · video.encoder]"
    assert issues[2].strip().startswith("fix: Use hevc_qsv (closest match")
    assert "No command: the job has errors." in out
    assert "Command (" not in out


def test_detection_that_does_not_end_does_not_hang(
    cli_env: ft.FakeTools, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every hardware test encode hangs: validation waits a bounded time, then plans with the
    statuses it has (``encoder.checking`` is info), and closing kills the test encodes."""
    monkeypatch.setattr(jobs_module, "DETECTION_WAIT", 0.5)
    replay(cli_env, "truehd-atmos", extra=(ft.Rule(argv_has=["-f", "null"], actions=[ft.hang()]),))
    movie = media_file(tmp_path / "media" / Media, "movie.mkv")
    started = time.monotonic()
    result = invoke("plan", str(movie), "--preset", "H.265 NVENC 1080p")
    assert time.monotonic() - started < 20
    assert result.exit_code == EXIT_OK, result.output
    assert "is still being checked" in result.stdout
    assert "Encoder detection did not finish within 0.5 s" in result.stdout
    assert "-c:v:0 hevc_nvenc" in result.stdout


def test_job_errors_exit_1(cli_env: ft.FakeTools, tmp_path: Path) -> None:
    replay(cli_env, "cover-art")  # audio only
    song = media_file(tmp_path / "media", "song.mka")
    result = invoke("plan", str(song))
    assert result.exit_code == EXIT_FAILED
    assert "error    song.mka has no video track" in result.stdout
    assert "[source.no_video · source]" in result.stdout


def test_unknown_preset(movie: Path) -> None:
    result = invoke("plan", str(movie), "--preset", "H.265 MKV 1088p")
    assert result.exit_code == EXIT_USAGE
    assert result.stdout == ""
    assert result.stderr.startswith('error: there is no preset named "H.265 MKV 1088p". Did you')
    assert '"H.265 MKV 1080p"' in result.stderr
    nothing = invoke("plan", str(movie), "--preset", "zzzz")
    assert nothing.exit_code == EXIT_USAGE
    assert "Presets: " in nothing.stderr


def test_missing_file(cli_env: ft.FakeTools, tmp_path: Path) -> None:
    result = invoke("plan", str(tmp_path / "missing.mkv"))
    assert result.exit_code == EXIT_NOT_FOUND
    assert result.stderr.startswith("error: ")
    assert "does not exist" in result.stderr


def test_no_ffprobe(movie: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("REFRAME_FFPROBE", str(tmp_path / "no-ffprobe"))
    result = invoke("plan", str(movie))
    assert result.exit_code == EXIT_NO_FFPROBE
    assert result.stderr.startswith("error: ffprobe is not usable")


def test_json(movie: Path) -> None:
    result = invoke("plan", str(movie), "--json")
    assert result.exit_code == EXIT_OK, result.output
    data = json.loads(result.stdout)
    draft = JobDraft.model_validate(data["draft"])
    plan = EncodePlan.model_validate(data["plan"])
    assert draft.job.output.path == plan.output_final
    assert draft.job.video.metadata.default is True


def test_json_with_errors_has_no_plan(cli_env: ft.FakeTools, tmp_path: Path) -> None:
    replay(cli_env, "cover-art")
    song = media_file(tmp_path / "media", "song.mka")
    result = invoke("plan", str(song), "--json")
    assert result.exit_code == EXIT_FAILED
    assert json.loads(result.stdout)["plan"] is None


@pytest.mark.needs_ffmpeg
def test_real_ffmpeg_plan_of_a_fixture(
    fixture_media: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M2 demo item 2 with the real tools: ``reframe plan multitrack.mkv --preset "H.265 MKV
    1080p"`` prints the command, and the command's input and output are the right files."""
    assert callable(fixture_media)
    source: Path = fixture_media("multitrack")
    for name in ("config", "data", "cache"):
        monkeypatch.setenv(f"REFRAME_{name.upper()}_DIR", str(tmp_path / name))
    copy = tmp_path / "media" / "multitrack.mkv"
    copy.parent.mkdir()
    shutil.copy2(source, copy)
    result = invoke("plan", str(copy), "--preset", "H.265 MKV 1080p")
    assert result.exit_code == EXIT_OK, result.output
    command = section(result.stdout, "Command (encode")
    assert len(command) == 1
    assert f"-i {copy}" in command[0]
    assert "-c:v:0 libx265" in command[0]
    # The template name is the source itself, so the output is the next free name.
    assert "multitrack (1).part.mkv" in command[0]
    assert "The name multitrack.mkv is the source file itself" in result.stdout
