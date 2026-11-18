"""``reframe encoders`` on the fake ffmpeg: the cached result, then the changes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reframe.cli import EXIT_NO_TOOL, EXIT_OK, encoder_text
from reframe.models import CapabilitySnapshot, EncoderState, EncoderStatus
from reframe_testing import fake_tools as ft
from reframe_testing.capabilities import detect_rule
from reframe_testing.cli import invoke, run_cli

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


def test_the_cache_is_printed_then_the_changes(cli_env: ft.FakeTools) -> None:
    assert invoke("encoders").exit_code == EXIT_OK  # every test encode works: cached
    unchanged = invoke("encoders")
    assert unchanged.exit_code == EXIT_OK, unchanged.output
    out = lines(unchanged.stdout)
    assert "(cached result of " in out[0]
    assert "Checking again…" in out
    cached = out[1 : out.index("Checking again…")]
    assert "libx265 — available" in cached
    assert out[-1].endswith("(no changes).")

    cli_env.set_scenario(ft.Scenario([detect_rule("detect_hevc_nvenc_no_driver")]))
    changed = invoke("encoders")
    assert changed.exit_code == EXIT_OK, changed.output
    out = lines(changed.stdout)
    checking_again = out.index("Checking again…")
    assert "hevc_nvenc — available" in out[:checking_again]
    assert NVENC_LINE in out[checking_again:]
    assert out[-1].endswith("(1 changed since the cached result).")


def nvenc_driver_too_old(encoder: str) -> ft.Rule:
    """The test encode of ``encoder`` fails as with an NVIDIA driver older than the build needs
    (the real lines of the pinned build with driver 582.78)."""
    text = (
        f"[{encoder} @ 0x55] Driver does not support the required nvenc API version. Required: "
        f"13.1 Found: 13.0\n[{encoder} @ 0x55] The minimum required Nvidia driver for nvenc is "
        "610.00 or newer\nConversion failed!\n"
    )
    return ft.Rule(actions=[ft.stderr(text)], exit_code=1, argv_has=["-c:v", encoder])


HINT = (
    "hint: {} newer system software than this FFmpeg build expects: update the driver, or use "
    "another build (reframe tools fetch --build compat, or REFRAME_FFMPEG / tools.ffmpeg)."
)


def test_a_build_mismatch_ends_with_a_hint(cli_env: ft.FakeTools) -> None:
    cli_env.set_scenario(
        ft.Scenario(
            [
                nvenc_driver_too_old("h264_nvenc"),
                nvenc_driver_too_old("hevc_nvenc"),
                detect_rule("detect_hevc_nvenc_no_driver", encoder="av1_nvenc"),
            ]
        )
    )
    result = invoke("encoders")
    assert result.exit_code == EXIT_OK, result.output
    out = lines(result.stdout)
    too_old = "unavailable: NVIDIA driver too old: NVENC needs driver 610.00 or newer"
    assert f"hevc_nvenc — {too_old}" in out
    assert "av1_nvenc — unavailable: NVIDIA driver not found" in out
    assert out[-2].startswith("Done in ")
    assert out[-1] == HINT.format("h264_nvenc, hevc_nvenc need")

    # tools status shows the hint of the cached result
    status = invoke("tools", "status")
    assert status.exit_code == EXIT_OK, status.output
    assert lines(status.stdout)[-1] == HINT.format("h264_nvenc, hevc_nvenc need")

    # without a build mismatch there is no hint
    cli_env.set_scenario(ft.Scenario([nvenc_driver_too_old("hevc_nvenc")]))
    out = lines(invoke("encoders").stdout)
    assert out[-1] == HINT.format("hevc_nvenc needs")
    cli_env.set_scenario(ft.Scenario([]))
    assert not any(line.startswith("hint:") for line in lines(invoke("encoders").stdout))
    assert not any(line.startswith("hint:") for line in lines(invoke("tools", "status").stdout))


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
    for args in (["encoders"], ["name", str(tmp_path / "Movie.2016.1080p" / "m→v.mkv")]):
        result = run_cli(cli_env, tmp_path, *args, encoding="cp1252")
        assert result.returncode == 0, result.stderr.decode("cp1252", "replace")
        out = result.stdout.decode("cp1252")
        assert "Traceback" not in result.stderr.decode("cp1252", "replace")
        if args[0] == "encoders":
            assert "libx264 — available" in out
        else:
            assert "m?v.mkv" in out
