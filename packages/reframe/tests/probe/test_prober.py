"""Probing one file through a fake ffprobe (C-3): success, cache, HDR frame fallback, and
fault injection (hang → timeout, crash, garbage JSON, missing tool, cancel)."""

from __future__ import annotations

import asyncio
import json
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
from reframe.probe.prober import MATROSKA_READER
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


def probe_calls(fake: ft.FakeTools) -> list[tuple[str, ...]]:
    """ffprobe calls without the packet-timestamp samples (the VFR check of Matroska files
    without statistics tags when MediaInfo is off)."""
    return [c for c in fake.calls("ffprobe") if "packet=pts_time" not in c]


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
    assert probe_calls(fake_tools) == [
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
    assert len(probe_calls(fake_tools)) == 1
    # Another process (new cache object, same folder) also hits.
    again = await make_prober(fake_tools, cache=ProbeCache(tmp_path / "cache")).probe(media_file)
    assert again == first
    assert len(probe_calls(fake_tools)) == 1
    # use_cache=False probes again; a touched file is a miss.
    await prober.probe(media_file, use_cache=False)
    assert len(probe_calls(fake_tools)) == 2
    _append(media_file, b"more")
    await prober.probe(media_file)
    assert len(probe_calls(fake_tools)) == 3


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
    frame_call = probe_calls(fake_tools)[1]
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
        "The HDR side data of the first frames could not be read: ffprobe could not read the "
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
    await until(lambda: len(probe_calls(fake_tools)) >= 2)
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
    assert probe_calls(fake_tools) == []


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
    monkeypatch.setattr(mediainfo, "mediainfo_version", lambda: "pymediainfo 1, libmediainfo 2")
    reader = {"matroska": MATROSKA_READER}
    assert Prober("ffprobe").cache_options() == {
        "mediainfo": "pymediainfo 1, libmediainfo 2",
        **reader,
    }
    assert Prober("ffprobe", use_mediainfo=False).cache_options() == {"mediainfo": False, **reader}
    monkeypatch.setattr(mediainfo, "mediainfo_available", lambda: False)
    assert Prober("ffprobe").cache_options() == {"mediainfo": False, **reader}


# --------------------------------------------------------------------------- review fixes (M1)


def _packets_json(tmp_path: Path, steps_ms: list[float]) -> Path:
    t, packets = 0.0, []
    for step in [0.0, *steps_ms]:
        t += step / 1000
        packets.append({"pts_time": f"{t:.6f}"})
    path = tmp_path / "packets.json"
    path.write_text(json.dumps({"packets": [*packets, {"pts_time": "N/A"}, {}]}), "utf-8")
    return path


@pytest.mark.parametrize(
    ("steps", "vfr"),
    [([41.7] * 24 + [33.3] * 30 + [16.7] * 60, True), ([40.0] * 100, False), ([], False)],
)
async def test_undecided_matroska_vfr_samples_packets(
    fake_tools: ft.FakeTools, media_file: Path, tmp_path: Path, steps: list[float], vfr: bool
) -> None:
    """A Matroska stream with r = avg and no statistics tags (MediaInfo off): packet sample."""
    fake_tools.set_scenario(
        ft.Scenario(
            [
                ft.Rule(
                    tool="ffprobe",
                    argv_has=["packet=pts_time"],
                    actions=[stdout_file(_packets_json(tmp_path, steps))],
                ),
                streams_rule(stdout_file(MULTITRACK)),
            ]
        )
    )
    source = await make_prober(fake_tools).probe(media_file)
    assert isinstance(source, MediaSource)
    assert source.video[0].vfr is vfr
    [call] = [c for c in fake_tools.calls("ffprobe") if "packet=pts_time" in c]
    assert call[call.index("-read_intervals") + 1] == "%+#120"


async def test_packet_sample_failure_is_a_warning(
    fake_tools: ft.FakeTools, media_file: Path
) -> None:
    fake_tools.set_scenario(
        ft.Scenario(
            [
                ft.Rule(tool="ffprobe", argv_has=["packet=pts_time"], exit_code=1),
                streams_rule(stdout_file(MULTITRACK)),
            ]
        )
    )
    source = await make_prober(fake_tools).probe(media_file)
    assert isinstance(source, MediaSource)
    assert not source.video[0].vfr
    assert source.warnings[-1].startswith("Video stream 0: the packet timestamps could not be read")


async def test_no_decoded_frame_is_a_warning(fake_tools: ft.FakeTools, media_file: Path) -> None:
    fake_tools.set_scenario(
        ft.Scenario(
            [
                ft.Rule(tool="ffprobe", argv_has=["-show_frames"], actions=[ft.stdout("{}")]),
                streams_rule(stdout_file(PROBES / "hdr10-sei-only.json")),
            ]
        )
    )
    source = await make_prober(fake_tools).probe(media_file)
    assert isinstance(source, MediaSource)
    assert source.warnings == [
        "No frame of video stream 0 could be decoded from its first 5 packets: HDR metadata "
        "that is only in the frames (SEI, HDR10+) was not checked."
    ]
    frame_call = next(c for c in fake_tools.calls("ffprobe") if "-show_frames" in c)
    assert frame_call[frame_call.index("-read_intervals") + 1] == "%+#5"


async def test_mediainfo_gives_language_ietf_and_frame_rate_mode(
    fake_tools: ft.FakeTools, media_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    info = mediainfo.MediaInfoData(
        languages={("audio", 1): "ja-JP", ("subtitle", 4): "en-US"},
        frame_rate_modes={("video", 0): "VFR"},
    )
    monkeypatch.setattr(mediainfo, "mediainfo_available", lambda: True)
    monkeypatch.setattr(mediainfo, "mediainfo_version", lambda: "fake 1")
    monkeypatch.setattr(mediainfo, "read_mediainfo", lambda path: info)
    fake_tools.set_scenario(ft.Scenario([streams_rule(stdout_file(MULTITRACK))]))
    prober = Prober(ProbeTool(str(fake_tools.ffprobe)), use_mediainfo=True)
    source = await prober.probe(media_file)
    assert isinstance(source, MediaSource)
    assert (source.audio[0].language, source.audio[0].language_ietf) == ("jpn", "ja-JP")
    assert source.subtitles[0].language_ietf == "en-US"
    assert source.audio[1].language_ietf is None
    assert source.video[0].vfr  # MediaInfo decided: no packet sample
    assert [c for c in fake_tools.calls("ffprobe") if "packet=pts_time" in c] == []


async def test_concurrent_probes_of_one_file_share_one_ffprobe(
    fake_tools: ft.FakeTools, media_file: Path
) -> None:
    fake_tools.set_scenario(ft.Scenario([streams_rule(ft.sleep(0.3), stdout_file(MULTITRACK))]))
    prober = make_prober(fake_tools)
    results = await asyncio.gather(*(prober.probe(media_file) for _ in range(5)))
    assert all(isinstance(r, MediaSource) for r in results)
    assert len([c for c in fake_tools.calls("ffprobe") if "-show_streams" in c]) == 1
    first, second = results[0], results[1]
    assert first == second
    assert first is not second
    # After the flight landed, a new probe runs ffprobe again.
    await prober.probe(media_file)
    assert len([c for c in fake_tools.calls("ffprobe") if "-show_streams" in c]) == 2


async def test_one_cancelled_caller_does_not_cancel_the_others(
    fake_tools: ft.FakeTools, media_file: Path
) -> None:
    fake_tools.set_scenario(ft.Scenario([streams_rule(ft.sleep(0.5), stdout_file(MULTITRACK))]))
    prober = make_prober(fake_tools)
    token = CancelToken()
    quitter = asyncio.create_task(prober.probe(media_file, cancel=token))
    stayer = asyncio.create_task(prober.probe(media_file))
    await until(lambda: bool(fake_tools.pids()))
    token.cancel()
    left = await quitter
    assert isinstance(left, ProbeError)
    assert left.kind is ProbeErrorKind.CANCELLED
    assert isinstance(await stayer, MediaSource)


async def test_last_caller_gone_kills_the_shared_ffprobe(
    fake_tools: ft.FakeTools, media_file: Path
) -> None:
    fake_tools.set_scenario(ft.Scenario([streams_rule(ft.hang())]))
    prober = make_prober(fake_tools)
    task = asyncio.create_task(prober.probe(media_file))
    await until(lambda: bool(fake_tools.pids()))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert ffprobe_procs_alive(fake_tools) == []  # gone before probe() returned
    assert prober._flights == {}


async def test_cancel_during_a_slow_stat(
    tmp_path: Path, fake_tools: ft.FakeTools, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    release = threading.Event()
    real_prepare = Prober._prepare

    def slow_prepare(self: Prober, *args: object) -> object:
        release.wait(5)  # a network share that does not answer
        return real_prepare(self, *args)  # type: ignore[arg-type]

    monkeypatch.setattr(Prober, "_prepare", slow_prepare)
    token = CancelToken()
    task = asyncio.create_task(make_prober(fake_tools).probe(tmp_path / "a.mkv", cancel=token))
    await asyncio.sleep(0.05)
    started = time.monotonic()
    token.cancel()
    try:
        result = await asyncio.wait_for(task, 1.0)
    finally:
        release.set()
    assert time.monotonic() - started < 1.0
    assert isinstance(result, ProbeError)
    assert result.kind is ProbeErrorKind.CANCELLED


async def test_already_cancelled_token(fake_tools: ft.FakeTools, media_file: Path) -> None:
    token = CancelToken()
    token.cancel()
    result = await make_prober(fake_tools).probe(media_file, cancel=token)
    assert isinstance(result, ProbeError)
    assert result.kind is ProbeErrorKind.CANCELLED
    assert fake_tools.calls("ffprobe") == []
