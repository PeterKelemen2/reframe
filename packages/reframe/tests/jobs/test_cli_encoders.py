"""``reframe encoders`` on the fake ffmpeg: the cached result, then the changes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reframe.cli import EXIT_NO_TOOL, EXIT_OK, encoder_text
from reframe.models import CapabilitySnapshot, EncoderState, EncoderStatus
from reframe_testing import fake_tools as ft
from reframe_testing.capabilities import detect_rule
from reframe_testing.cli import invoke

NVENC_LINE = "hevc_nvenc — unavailable: NVIDIA driver not found"


def lines(output: str) -> list[str]:
    return [line.rstrip() for line in output.splitlines()]


def test_first_run_checks_then_lists_every_encoder(cli_env: ft.FakeTools) -> None:
    result = invoke("encoders")
    assert result.exit_code == EXIT_OK, result.output
    out = lines(result.stdout)
    assert out[0].startswith("No cached result: checking the encoders of ffmpeg")
    assert str(cli_env.ffmpeg) in out[0]
    assert "libx264 — available" in out
    assert "aac — available" in out
    assert "libfdk_aac — unavailable: Not in this FFmpeg build" in out
    assert out[-1].startswith("Done in ")
    assert "(no changes)" not in out[-1]
    names = [line.split(" — ")[0] for line in out[1:-1]]
    assert len(names) == len(set(names))
    assert not any("checking…" in line for line in out)


def test_second_run_prints_the_cache_at_once(cli_env: ft.FakeTools) -> None:
    assert invoke("encoders").exit_code == EXIT_OK
    result = invoke("encoders")
    assert result.exit_code == EXIT_OK, result.output
    out = lines(result.stdout)
    assert "(cached result of " in out[0]
    assert "Checking again…" in out
    cached = out[1 : out.index("Checking again…")]
    assert "libx265 — available" in cached
    assert out[-1].endswith("(no changes).")


def test_a_status_that_changes_after_the_cache_is_printed_again(cli_env: ft.FakeTools) -> None:
    assert invoke("encoders").exit_code == EXIT_OK  # every test encode works: cached
    cli_env.set_scenario(ft.Scenario([detect_rule("detect_hevc_nvenc_no_driver")]))
    result = invoke("encoders")
    assert result.exit_code == EXIT_OK, result.output
    out = lines(result.stdout)
    checking_again = out.index("Checking again…")
    assert "hevc_nvenc — available" in out[:checking_again]
    assert NVENC_LINE in out[checking_again:]
    assert out[-1].endswith("(1 changed since the cached result).")


def test_json_waits_for_the_result(cli_env: ft.FakeTools) -> None:
    result = invoke("encoders", "--json")
    assert result.exit_code == EXIT_OK, result.output
    snapshot = CapabilitySnapshot.model_validate(json.loads(result.stdout))
    assert snapshot.detecting is False
    assert snapshot.status("libx264").state is EncoderState.AVAILABLE


def test_missing_ffmpeg(
    cli_env: ft.FakeTools, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("REFRAME_FFMPEG", str(tmp_path / "no-ffmpeg"))
    result = invoke("encoders")
    assert result.exit_code == EXIT_NO_TOOL
    assert "libx264 — unavailable: FFmpeg not found" in lines(result.stdout)
    assert result.stderr.startswith("error: ffmpeg is not usable (missing")
    assert "Traceback" not in result.output


@pytest.mark.parametrize(
    ("status", "text"),
    [
        (EncoderStatus(id="libx264", state=EncoderState.AVAILABLE), "libx264 — available"),
        (
            EncoderStatus(
                id="h264_vaapi",
                state=EncoderState.AVAILABLE,
                hardware=True,
                supports_10bit=False,
                device="/dev/dri/renderD128",
            ),
            "h264_vaapi — available (/dev/dri/renderD128, 8-bit only)",
        ),
        (EncoderStatus(id="hevc_qsv", state=EncoderState.CHECKING), "hevc_qsv — checking…"),
        (
            EncoderStatus(
                id="hevc_qsv", state=EncoderState.UNKNOWN, reason="Hardware tests are off"
            ),
            "hevc_qsv — not tested: Hardware tests are off",
        ),
        (EncoderStatus(id="hevc_qsv", state=EncoderState.UNKNOWN), "hevc_qsv — not tested"),
        (
            EncoderStatus(id="av1_amf", state=EncoderState.ERROR, reason="Timed out after 10 s"),
            "av1_amf — error: Timed out after 10 s",
        ),
        (
            EncoderStatus(id="av1_amf", state=EncoderState.UNAVAILABLE),
            "av1_amf — unavailable: no reason given",
        ),
    ],
)
def test_encoder_text(status: EncoderStatus, text: str) -> None:
    assert encoder_text(status) == text


def test_a_legacy_windows_console_encoding_does_not_crash(
    cli_env: ft.FakeTools, tmp_path: Path
) -> None:
    """cp1252 (a Windows console) has the dash but no arrow: what it cannot encode is
    replaced, never a ``UnicodeEncodeError``."""
    import subprocess
    import sys

    from reframe.tools import ENV_VARS

    env = cli_env.env()
    for var in ENV_VARS.values():
        env.pop(var, None)
    env.update(
        REFRAME_FFMPEG=str(cli_env.ffmpeg),
        REFRAME_FFPROBE=str(cli_env.ffprobe),
        REFRAME_CACHE_DIR=str(tmp_path / "cache-sub"),
        REFRAME_CONFIG_DIR=str(tmp_path / "config-sub"),
        REFRAME_DATA_DIR=str(tmp_path / "data-sub"),
        PYTHONIOENCODING="cp1252",
        COLUMNS="120",
    )
    env.pop("PYTHONUTF8", None)
    for args in (["encoders"], ["name", str(tmp_path / "Movie.2016.1080p" / "m→v.mkv")]):
        result = subprocess.run(
            [sys.executable, "-m", "reframe.cli", *args],
            capture_output=True,
            env=env,
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, result.stderr.decode("cp1252", "replace")
        out = result.stdout.decode("cp1252")
        assert "Traceback" not in result.stderr.decode("cp1252", "replace")
        if args[0] == "encoders":
            assert "libx264 — available" in out
        else:
            assert "m?v.mkv" in out
