"""``reframe_testing.capabilities`` and the capture helpers in ``capture_fake_data.py``."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from reframe.models import ToolStatus
from reframe_testing import capture_fake_data
from reframe_testing import fake_tools as ft
from reframe_testing.capabilities import PINNED_VERSION, StubTools, c4_rule, ffmpeg_info, tool_set


def test_tool_set() -> None:
    tools = tool_set(ffmpeg_info(Path("/x/ffmpeg")))
    assert tools.ffmpeg.status is ToolStatus.FOUND
    assert tools.ffmpeg.version == PINNED_VERSION
    assert tools.ffprobe.status is ToolStatus.MISSING


def test_stub_tools_gate() -> None:
    async def scenario() -> None:
        stub = StubTools(tool_set(ffmpeg_info(None)))
        stub.gate = asyncio.Event()
        waiting = asyncio.create_task(stub.status())
        await asyncio.sleep(0.05)
        assert not waiting.done()
        stub.gate.set()
        assert (await waiting).ffmpeg.path is None
        assert stub.calls == 1
        assert stub.current is stub.tools

    asyncio.run(scenario())


def run(fake: ft.FakeTools, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run([str(fake.ffmpeg), *args], capture_output=True, timeout=60, check=False)


def test_c4_rule_replays_the_capture(fake_tools: ft.FakeTools) -> None:
    fake_tools.set_scenario(
        ft.Scenario(
            [
                c4_rule("c4_hevc_amf_no_runtime"),
                c4_rule("c4_h264_amf_10bit", encoder="av1_amf", ten_bit=True),
            ]
        )
    )
    amf = run(fake_tools, "-pix_fmt", "nv12", "-c:v", "hevc_amf", "-f", "null", "-")
    assert amf.returncode == 171
    assert b"DLL libamfrt64.so.1 failed to open" in amf.stderr
    eight = run(fake_tools, "-pix_fmt", "nv12", "-c:v", "av1_amf", "-f", "null", "-")
    ten = run(fake_tools, "-pix_fmt", "p010le", "-c:v", "av1_amf", "-f", "null", "-")
    assert eight.returncode == 0
    assert ten.returncode == 183


def test_c4_captures_are_listed_with_their_files() -> None:
    captures = ft.captures()
    names = set(capture_fake_data.c4_captures())
    assert names <= set(captures)
    for name in names:
        capture = captures[name]
        assert capture.machine is not None
        assert capture.stderr is not None
        assert (ft.DATA_DIR / capture.stderr).is_file()
    assert captures["c4_hevc_amf_no_runtime"].env == {
        "LD_LIBRARY_PATH": capture_fake_data.EMPTY_AMF_RUNTIME
    }


def test_only_captures_merge_into_the_index(
    fake_tools: ft.FakeTools, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "fake_data"
    shutil.copytree(ft.DATA_DIR, data)
    monkeypatch.setattr(capture_fake_data, "DATA_DIR", data)
    fake_tools.set_scenario(ft.Scenario([c4_rule("c4_hevc_nvenc_no_driver")]))
    before = json.loads((data / "captures.json").read_text(encoding="utf-8"))
    (data / "c4_hevc_nvenc_no_driver.stderr.txt").unlink()
    code = capture_fake_data.main(
        [
            "--ffmpeg",
            str(fake_tools.ffmpeg),
            "--ffprobe",
            str(fake_tools.ffprobe),
            "--only",
            "c4_hevc_nvenc_no_driver",
        ]
    )
    assert code == 0
    after = json.loads((data / "captures.json").read_text(encoding="utf-8"))
    assert set(after) == set(before)
    assert after["encoders"] == before["encoders"]
    assert after["c4_hevc_nvenc_no_driver"]["exit_code"] == 255
    assert b"Cannot load libcuda.so.1" in (data / "c4_hevc_nvenc_no_driver.stderr.txt").read_bytes()
    assert (data / "encoders.stdout.txt").is_file()
    calls = fake_tools.calls()
    assert [c for c in calls if "-c:v" in c] == [
        tuple(capture_fake_data.c4_captures()["c4_hevc_nvenc_no_driver"][0])
    ]
