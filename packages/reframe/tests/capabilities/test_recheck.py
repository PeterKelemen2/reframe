"""A cached status can be stale: the GPU fingerprint does not change with a user-space driver
(AMF runtime, Mesa / libva, oneVPL), so a cached ``unavailable`` is checked again.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from reframe.cli import EXIT_FAILED, EXIT_OK, build_app
from reframe.probe import mediainfo
from reframe.tools import ENV_VARS
from reframe_testing import fake_tools as ft
from reframe_testing.capabilities import c4_rule

ROOT = Path(__file__).resolve().parents[4]
PROBE = ROOT / "testdata" / "probes" / "truehd-atmos.json"
PRESET = "H.265 VCN 1080p"  # hevc_amf
NO_RUNTIME = "AMD AMF runtime not found (libamfrt64.so.1)"


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fake_tools: ft.FakeTools) -> Path:
    """The fake ffmpeg / ffprobe and private config, data and cache folders; returns the
    capability cache folder."""
    for var in ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    for name in ("config", "data", "cache"):
        monkeypatch.setenv(f"REFRAME_{name.upper()}_DIR", str(tmp_path / name))
    monkeypatch.setenv("REFRAME_FFMPEG", str(fake_tools.ffmpeg))
    monkeypatch.setenv("REFRAME_FFPROBE", str(fake_tools.ffprobe))
    monkeypatch.setenv("REFRAME_MKVPROPEDIT", str(tmp_path / "no-mkvpropedit"))
    monkeypatch.setattr(mediainfo, "mediainfo_available", lambda: False)
    return tmp_path / "cache" / "capabilities"


def scenario(fake: ft.FakeTools, *rules: ft.Rule, probe_delay: float = 0.0) -> None:
    """``rules`` for ffmpeg, and every file probes as the recorded TrueHD Atmos movie (after
    ``probe_delay`` seconds)."""
    actions: list[ft.Action] = [ft.sleep(probe_delay)] if probe_delay else []
    probe = ft.Rule(
        tool="ffprobe",
        argv_has=["-show_streams"],
        actions=[*actions, {"stdout_file": str(PROBE)}],
    )
    fake.set_scenario(ft.Scenario([*rules, probe]))


def plan(movie: Path) -> Result:
    return CliRunner().invoke(
        build_app(), ["plan", str(movie), "--preset", PRESET], env={"COLUMNS": "200"}
    )


def cached(folder: Path) -> dict[str, Any]:
    """The cached ``hevc_amf`` status (one cache entry)."""
    (entry,) = folder.glob("*.json")
    status: dict[str, Any] = json.loads(entry.read_text(encoding="utf-8"))["snapshot"]
    return status["encoders"]["hevc_amf"]  # type: ignore[no-any-return]


def test_a_stale_cached_unavailable_is_checked_again(
    cli_env: Path, fake_tools: ft.FakeTools, tmp_path: Path
) -> None:
    movie = tmp_path / "media" / "Movie.2016.1080p.BluRay.x264-GRP" / "movie.mkv"
    movie.parent.mkdir(parents=True)
    movie.write_bytes(b"placeholder")

    scenario(fake_tools, c4_rule("c4_hevc_amf_no_runtime"))
    first = plan(movie)
    assert first.exit_code == EXIT_FAILED, first.output
    assert NO_RUNTIME in first.stdout
    assert cached(cli_env)["state"] == "unavailable"

    # The runtime is installed (the GPU fingerprint is the same). The file changed, so it is
    # probed again; the probe ends after the cached result is shown and before the re-check
    # ends, so the plan sees the cached status: it waits for the re-check instead of failing.
    movie.write_bytes(b"placeholder, changed")
    slow_listing = ft.Rule(
        argv_has=["-encoders"], actions=[ft.sleep(1.5), ft.stdout_data("encoders.stdout.txt")]
    )
    scenario(fake_tools, slow_listing, probe_delay=0.5)
    second = plan(movie)
    assert second.exit_code == EXIT_OK, second.output
    assert NO_RUNTIME not in second.stdout
    assert "-c:v:0 hevc_amf" in second.stdout
    assert cached(cli_env)["state"] == "available"  # the re-check was written to the cache

    scenario(fake_tools)
    third = plan(movie)
    assert third.exit_code == EXIT_OK, third.output
    assert "-c:v:0 hevc_amf" in third.stdout
