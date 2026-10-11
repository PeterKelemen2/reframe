"""Probing one file through a fake ffprobe (C-3): success, cache, HDR frame fallback, and
fault injection (hang → timeout, crash, garbage JSON, missing tool, cancel)."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

import psutil
import pytest

from reframe.models import MediaSource, ToolInfo, ToolOrigin, ToolStatus
from reframe.probe import (
    ProbeCache,
    ProbeError,
    ProbeErrorKind,
    Prober,
    ProbeTool,
    mediainfo,
    probe_argv,
    probe_file,
)
from reframe.probe import prober as prober_mod
from reframe.tools import CancelToken
from reframe_testing import fake_tools as ft

pytestmark = pytest.mark.anyio


async def until(condition: Callable[[], bool], limit: float = 30.0) -> None:
    """Wait (polling) until ``condition()`` is true."""
    deadline = time.monotonic() + limit
    while not condition():
        if time.monotonic() > deadline:
            raise TimeoutError("condition not met in time")
        await asyncio.sleep(0.02)


PROBES = Path(__file__).resolve().parents[4] / "testdata" / "probes"
MULTITRACK = PROBES / "fixtures" / "multitrack.mkv.json"


def _append(path: Path, data: bytes) -> None:
    with path.open("ab") as f:
        f.write(data)


def streams_rule(*actions: ft.Action, exit_code: int = 0) -> ft.Rule:
    return ft.Rule(tool="ffprobe", argv_has=["-show_streams"], actions=actions, exit_code=exit_code)


def stdout_file(path: Path) -> ft.Action:
    return {"stdout_file": str(path)}


@pytest.fixture
def media_file(tmp_path: Path) -> Path:
    path = tmp_path / "Show.S01E01.mkv"
    path.write_bytes(b"\x1a\x45\xdf\xa3 not really matroska")
    return path


def make_prober(fake: ft.FakeTools, **kw: object) -> Prober:
    return Prober(ProbeTool(str(fake.ffprobe), version="n-fake"), use_mediainfo=False, **kw)  # type: ignore[arg-type]


def ffprobe_procs_alive(fake: ft.FakeTools) -> list[int]:
    alive = []
    for pid in fake.pids():
        try:
            if psutil.Process(pid).status() != psutil.STATUS_ZOMBIE:
                alive.append(pid)
        except psutil.Error:
            pass
    return alive


async def test_probe_parses_the_output(fake_tools: ft.FakeTools, media_file: Path) -> None:
    fake_tools.set_scenario(ft.Scenario([streams_rule(stdout_file(MULTITRACK))]))
    source = await make_prober(fake_tools).probe(media_file)
    assert isinstance(source, MediaSource)
    assert len(source.audio) == 3
    assert len(source.subtitles) == 3
    assert source.ref.path == media_file
    assert source.ref.fingerprint is not None
    assert source.ref.fingerprint.size == os.stat(media_file).st_size
    assert source.ref.fingerprint.probe_hash
    assert source.probe_tool == "n-fake"
    assert source.probed_at is not None
    assert fake_tools.calls("ffprobe") == [
        tuple(probe_argv(str(fake_tools.ffprobe), str(media_file))[1:])
    ]


async def test_cache_hit_runs_no_ffprobe(
    fake_tools: ft.FakeTools, media_file: Path, tmp_path: Path
) -> None:
    fake_tools.set_scenario(ft.Scenario([streams_rule(stdout_file(MULTITRACK))]))
    cache = ProbeCache(tmp_path / "cache")
    prober = make_prober(fake_tools, cache=cache)
    first = await prober.probe(media_file)
    second = await prober.probe(media_file)
    assert isinstance(first, MediaSource)
    assert second == first
    assert len(fake_tools.calls("ffprobe")) == 1
    # Another process (new cache object, same folder) also hits.
    again = await make_prober(fake_tools, cache=ProbeCache(tmp_path / "cache")).probe(media_file)
    assert again == first
    assert len(fake_tools.calls("ffprobe")) == 1
    # use_cache=False probes again; a touched file is a miss.
    await prober.probe(media_file, use_cache=False)
    assert len(fake_tools.calls("ffprobe")) == 2
    _append(media_file, b"more")
    await prober.probe(media_file)
    assert len(fake_tools.calls("ffprobe")) == 3


async def test_hdr_reads_the_first_frame(fake_tools: ft.FakeTools, media_file: Path) -> None:
    fake_tools.set_scenario(
        ft.Scenario(
            [
                ft.Rule(
                    tool="ffprobe",
                    argv_has=["-show_frames"],
                    actions=[stdout_file(PROBES / "hdr10-sei-only.frames.json")],
                ),
                streams_rule(stdout_file(PROBES / "hdr10-sei-only.json")),
            ]
        )
    )
    source = await make_prober(fake_tools).probe(media_file)
    assert isinstance(source, MediaSource)
    hdr = source.video[0].hdr
    assert hdr is not None
    assert hdr.source == "frame"
    assert hdr.mastering_display is not None
    frame_call = fake_tools.calls("ffprobe")[1]
    assert frame_call[frame_call.index("-select_streams") + 1] == "0"


async def test_frame_read_failure_is_a_warning(fake_tools: ft.FakeTools, media_file: Path) -> None:
    fake_tools.set_scenario(
        ft.Scenario(
            [
                ft.Rule(
                    tool="ffprobe",
                    argv_has=["-show_frames"],
                    actions=[ft.stderr("Error while decoding stream #0:0\n")],
                    exit_code=1,
                ),
                streams_rule(stdout_file(PROBES / "hdr10-sei-only.json")),
            ]
        )
    )
    source = await make_prober(fake_tools).probe(media_file)
    assert isinstance(source, MediaSource)
    assert source.warnings == [
        "The HDR side data of the first frame could not be read: ffprobe could not read the "
        "file (exit code 1). (Error while decoding stream #0:0)"
    ]
    assert source.video[0].hdr is not None  # PQ alone still says HDR10


async def test_hang_is_a_timeout(fake_tools: ft.FakeTools, media_file: Path) -> None:
    fake_tools.set_scenario(ft.Scenario([streams_rule(ft.hang())]))
    started = time.monotonic()
    result = await make_prober(fake_tools, timeout=0.5).probe(media_file)
    assert isinstance(result, ProbeError)
    assert result.kind is ProbeErrorKind.TIMEOUT
    assert result.message == "ffprobe did not finish reading the file within 0.5 s and was stopped."
    assert time.monotonic() - started < 5
    assert ffprobe_procs_alive(fake_tools) == []


async def test_cancel_kills_ffprobe(fake_tools: ft.FakeTools, media_file: Path) -> None:
    fake_tools.set_scenario(ft.Scenario([streams_rule(ft.hang())]))
    token = CancelToken()
    task = asyncio.create_task(make_prober(fake_tools).probe(media_file, cancel=token))
    await until(lambda: bool(fake_tools.pids()))
    started = time.monotonic()
    token.cancel()
    result = await task
    assert time.monotonic() - started < 1.0
    assert isinstance(result, ProbeError)
    assert result.kind is ProbeErrorKind.CANCELLED
    assert ffprobe_procs_alive(fake_tools) == []


async def test_cancel_during_frame_read(fake_tools: ft.FakeTools, media_file: Path) -> None:
    fake_tools.set_scenario(
        ft.Scenario(
            [
                ft.Rule(tool="ffprobe", argv_has=["-show_frames"], actions=[ft.hang()]),
                streams_rule(stdout_file(PROBES / "hdr10.json")),
            ]
        )
    )
    token = CancelToken()
    task = asyncio.create_task(make_prober(fake_tools).probe(media_file, cancel=token))
    await until(lambda: len(fake_tools.calls("ffprobe")) >= 2)
    token.cancel()
    result = await task
    assert isinstance(result, ProbeError)
    assert result.kind is ProbeErrorKind.CANCELLED


async def test_crash(fake_tools: ft.FakeTools, media_file: Path) -> None:
    fake_tools.set_scenario(ft.Scenario([streams_rule(ft.crash())]))
    result = await make_prober(fake_tools).probe(media_file)
    assert isinstance(result, ProbeError)
    assert result.kind is ProbeErrorKind.FAILED


async def test_unreadable_file(fake_tools: ft.FakeTools, media_file: Path) -> None:
    err = f"{media_file}: Invalid data found when processing input\n"
    fake_tools.set_scenario(ft.Scenario([streams_rule(ft.stderr(err), exit_code=1)]))
    result = await make_prober(fake_tools).probe(media_file)
    assert isinstance(result, ProbeError)
    assert result.kind is ProbeErrorKind.FAILED
    assert result.message == "ffprobe could not read the file (exit code 1)."
    assert result.detail == err.strip()
    assert result.to_json()["kind"] == "failed"


@pytest.mark.parametrize(
    ("stdout", "message"),
    [
        ("this is not json", "ffprobe printed something that is not JSON."),
        ('{"streams": [', "ffprobe printed something that is not JSON."),
        ("[1, 2]", "ffprobe printed JSON that is not an object."),
    ],
)
async def test_garbage_output(
    fake_tools: ft.FakeTools, media_file: Path, stdout: str, message: str
) -> None:
    fake_tools.set_scenario(ft.Scenario([streams_rule(ft.stdout(stdout))]))
    result = await make_prober(fake_tools).probe(media_file)
    assert isinstance(result, ProbeError)
    assert (result.kind, result.message) == (ProbeErrorKind.INVALID_OUTPUT, message)


async def test_truncated_output(
    fake_tools: ft.FakeTools, media_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from reframe.probe import ffprobe as ffprobe_mod

    monkeypatch.setattr(ffprobe_mod, "MAX_OUTPUT", 1000)
    fake_tools.set_scenario(ft.Scenario([streams_rule(ft.flood(5000))]))
    result = await make_prober(fake_tools).probe(media_file)
    assert isinstance(result, ProbeError)
    assert result.kind is ProbeErrorKind.INVALID_OUTPUT


async def test_parser_failure_is_an_error_value(
    fake_tools: ft.FakeTools, media_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: object, **kw: object) -> MediaSource:
        raise ValueError("boom")

    monkeypatch.setattr(prober_mod, "parse_ffprobe", broken)
    fake_tools.set_scenario(ft.Scenario([streams_rule(stdout_file(MULTITRACK))]))
    result = await make_prober(fake_tools).probe(media_file)
    assert isinstance(result, ProbeError)
    assert (result.kind, result.detail) == (ProbeErrorKind.INVALID_OUTPUT, "boom")


async def test_missing_tool(tmp_path: Path, media_file: Path) -> None:
    result = await probe_file(media_file, tmp_path / "no-ffprobe", use_mediainfo=False)
    assert isinstance(result, ProbeError)
    assert result.kind is ProbeErrorKind.TOOL_FAILED
    assert result.detail is not None


async def test_missing_file_and_folder(tmp_path: Path, fake_tools: ft.FakeTools) -> None:
    missing = await make_prober(fake_tools).probe(tmp_path / "nope.mkv")
    assert isinstance(missing, ProbeError)
    assert missing.kind is ProbeErrorKind.NOT_FOUND
    folder = await make_prober(fake_tools).probe(tmp_path)
    assert isinstance(folder, ProbeError)
    assert folder.kind is ProbeErrorKind.NOT_A_FILE
    assert fake_tools.calls("ffprobe") == []


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
async def test_stat_error_is_unreadable(tmp_path: Path, fake_tools: ft.FakeTools) -> None:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root can read anything")
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0)
    try:
        result = await make_prober(fake_tools).probe(locked / "a.mkv")
    finally:
        locked.chmod(0o700)
    assert isinstance(result, ProbeError)
    assert result.kind is ProbeErrorKind.UNREADABLE


async def test_relative_path_is_made_absolute(
    fake_tools: ft.FakeTools, media_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_tools.set_scenario(ft.Scenario([streams_rule(stdout_file(MULTITRACK))]))
    monkeypatch.chdir(media_file.parent)
    source = await make_prober(fake_tools).probe(media_file.name)
    assert isinstance(source, MediaSource)
    assert source.ref.path == media_file


def test_probe_tool_from_tool_info_and_identity(tmp_path: Path) -> None:
    binary = tmp_path / "ffprobe"
    binary.write_bytes(b"x")
    info = ToolInfo(
        name="ffprobe",
        status=ToolStatus.FOUND,
        path=binary,
        origin=ToolOrigin.PATH,
        version="n9.0.2",
        env={"LIBVA_DRIVERS_PATH": "/usr/lib/dri"},
    )
    tool = ProbeTool.of(info)
    assert (tool.path, tool.version, dict(tool.env)) == (str(binary), "n9.0.2", info.env)
    assert tool.identity() == "ffprobe n9.0.2"
    assert ProbeTool.of(tool) is tool
    unknown = ProbeTool.of(binary)
    assert unknown.identity().startswith(f"ffprobe at {binary} (1 bytes")
    assert ProbeTool.of(tmp_path / "gone").identity() == f"ffprobe at {tmp_path / 'gone'}"
    with pytest.raises(ValueError, match="no path"):
        ProbeTool.of(info.model_copy(update={"path": None}))


def test_cache_options_follow_mediainfo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mediainfo, "mediainfo_available", lambda: True)
    assert Prober("ffprobe").cache_options() == {"mediainfo": True}
    assert Prober("ffprobe", use_mediainfo=False).cache_options() == {"mediainfo": False}
    monkeypatch.setattr(mediainfo, "mediainfo_available", lambda: False)
    assert Prober("ffprobe").cache_options() == {"mediainfo": False}
