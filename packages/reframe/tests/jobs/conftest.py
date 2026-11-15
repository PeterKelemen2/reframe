"""Shared helpers of the jobs service and CLI tests."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from reframe import cli
from reframe.cli import build_app
from reframe.definitions import load_definitions
from reframe.models import (
    AppSettings,
    CapabilitySnapshot,
    EncoderState,
    EncoderStatus,
    JobSettings,
    MediaSource,
    Preset,
    QueueJob,
    SourceFingerprint,
    ToolInfo,
    ToolName,
    ToolSet,
    ToolStatus,
    ValidationIssue,
)
from reframe.presets import builtin_presets
from reframe.probe import ProbeError, ProbeErrorKind, parse_ffprobe
from reframe.service import Reframe
from reframe.tools import ENV_VARS
from reframe_testing import fake_tools as ft

from .fake_queue import Behaviour, FakeQueue

ROOT = Path(__file__).resolve().parents[4]
PROBES = ROOT / "testdata" / "probes"
WIDTH = "200"


def probe_json(name: str) -> Path:
    """Path of the probe ``name``: a generated fixture, or a recorded file."""
    for path in (PROBES / "fixtures" / f"{name}.mkv.json", PROBES / f"{name}.json"):
        if path.exists():
            return path
    raise FileNotFoundError(f"no recorded probe {name!r}")


def recorded(name: str, path: Path) -> MediaSource:
    """The recorded probe ``name`` parsed as the file ``path``."""
    probe = probe_json(name)
    frames = probe.with_name(probe.name.removesuffix(".json") + ".frames.json")
    return parse_ffprobe(
        json.loads(probe.read_text(encoding="utf-8")),
        path,
        frames=json.loads(frames.read_text(encoding="utf-8")) if frames.exists() else None,
        fingerprint=SourceFingerprint(size=0, mtime=0.0),
    )


def caps(
    *, unavailable: Mapping[str, str] | None = None, detecting: bool = False
) -> CapabilitySnapshot:
    """Every encoder of the definitions available, except ``unavailable`` (id → reason)."""
    defs = load_definitions()
    down = dict(unavailable or {})
    encoders = {}
    for enc_id in [*defs.video_encoders, *defs.audio_encoders]:
        encoders[enc_id] = EncoderStatus(
            id=enc_id,
            state=EncoderState.UNAVAILABLE if enc_id in down else EncoderState.AVAILABLE,
            reason=down.get(enc_id),
            device="/dev/dri/renderD128" if enc_id.endswith("_vaapi") else None,
            in_build=True,
            hardware=defs.video_encoders[enc_id].hardware
            if enc_id in defs.video_encoders
            else False,
        )
    names = sorted({n for f in defs.filters.values() for i in f.implementations for n in i.filters})
    return CapabilitySnapshot(
        encoders=encoders,
        filters=names,
        detecting=detecting,
        checked_at=None if detecting else datetime(2026, 10, 14, tzinfo=UTC),
    )


def checking() -> CapabilitySnapshot:
    """Detection running: every encoder ``checking``."""
    snap = caps(detecting=True)
    encoders = {
        k: v.model_copy(update={"state": EncoderState.CHECKING}) for k, v in snap.encoders.items()
    }
    return snap.model_copy(update={"encoders": encoders})


def toolset() -> ToolSet:
    def info(name: ToolName) -> ToolInfo:
        return ToolInfo(name=name, status=ToolStatus.FOUND)

    return ToolSet(
        ffmpeg=info("ffmpeg"),
        ffprobe=info("ffprobe"),
    )


def preset(name_or_id: str) -> Preset:
    for p in builtin_presets():
        if p.id == name_or_id or p.name == name_or_id:
            return p
    raise KeyError(name_or_id)


class Stubs:
    """The services of ``JobService`` without processes."""

    def __init__(self, sources: Mapping[Path, MediaSource] | None = None) -> None:
        self.sources: dict[Path, MediaSource] = dict(sources or {})
        self.presets = {p.id: p for p in builtin_presets()}
        self.default_id = "h265-mkv-1080p"
        self.tools = toolset()
        self.snapshot = caps()
        self.final: CapabilitySnapshot | None = None
        """What ``wait()`` returns (it also becomes the snapshot); ``None`` = the snapshot."""
        self.gate: asyncio.Event | None = None
        """When set, ``wait()`` waits for it (a detection that does not end)."""
        self.waits = 0
        self.probes = 0
        self.settings = AppSettings()

    async def probe(self, path: Any) -> MediaSource | ProbeError:
        self.probes += 1
        found = self.sources.get(Path(path))
        if found is None:
            return ProbeError(Path(path), ProbeErrorKind.NOT_FOUND, "The file does not exist.")
        return found

    def get(self, preset_id: str) -> Preset | None:
        return self.presets.get(preset_id)

    def find(self, name_or_id: str) -> Preset | None:
        for p in self.presets.values():
            if p.id == name_or_id or p.name.casefold() == name_or_id.casefold():
                return p
        return None

    def default(self) -> Preset:
        return self.presets[self.default_id]

    async def status(self) -> ToolSet:
        return self.tools

    async def wait(self) -> CapabilitySnapshot:
        self.waits += 1
        if self.gate is not None:
            await self.gate.wait()
        if self.final is not None:
            self.snapshot = self.final
        return self.snapshot


@pytest.fixture
def cli_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fake_tools: ft.FakeTools
) -> ft.FakeTools:
    """Fake ffmpeg and ffprobe, and private config, data and cache folders (never the user's).
    ``encode`` and ``batch`` run their jobs in-process (``tests/remote`` covers the server)."""
    monkeypatch.setenv(cli.IN_PROCESS_ENV, "1")
    for var in ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    for name in ("config", "data", "cache"):
        monkeypatch.setenv(f"REFRAME_{name.upper()}_DIR", str(tmp_path / name))
    monkeypatch.setenv("REFRAME_FFMPEG", str(fake_tools.ffmpeg))
    monkeypatch.setenv("REFRAME_FFPROBE", str(fake_tools.ffprobe))
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    return fake_tools


def probe_rule(probe: Path, file: Path | None = None) -> ft.Rule:
    """The fake ffprobe prints ``probe`` (for ``file`` only, or for every file)."""
    return ft.Rule(
        tool="ffprobe",
        argv_has=["-show_streams", *([str(file)] if file is not None else [])],
        actions=[{"stdout_file": str(probe)}],
    )


def replay(
    fake: ft.FakeTools,
    probe: str,
    *,
    per_file: Mapping[Path, str] | None = None,
    extra: tuple[ft.Rule, ...] = (),
) -> None:
    """Every file probes as the recorded ``probe``, except ``per_file`` (file → probe name);
    ``extra`` rules come first (ffmpeg rules for encoder detection)."""
    rules = [*extra]
    for file, name in (per_file or {}).items():
        rules.append(probe_rule(probe_json(name), file))
    rules.append(probe_rule(probe_json(probe)))
    fake.set_scenario(ft.Scenario(rules))


def media_file(folder: Path, name: str) -> Path:
    """A placeholder file (the fake ffprobe replays a recording for it)."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(b"placeholder")
    return path


def draft_path(source: Path, name: str) -> Path:
    """The output a draft names ``name`` next to ``source``. Where the file system ignores case
    (Windows), ``Movie.mkv`` is the source ``movie.mkv`` itself, so the draft takes the next
    free name."""
    path = source.with_name(name)
    if path.exists() and path.samefile(source):
        return path.with_name(f"{path.stem} (1){path.suffix}")
    return path


def invoke(*args: str, env: dict[str, str] | None = None) -> Result:
    return CliRunner().invoke(build_app(), list(args), env={"COLUMNS": WIDTH, **(env or {})})


class Queues:
    """Installs the fake queue as ``cli.get_queue`` and keeps the ones made."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, log_dir: Path) -> None:
        self.made: list[FakeQueue] = []
        self.log_dir = log_dir
        self.behaviour: Callable[[JobSettings], Behaviour] = lambda _job: "done"
        self.on_running: Callable[[QueueJob], None] | None = None
        self.validator: Callable[[JobSettings], Awaitable[list[ValidationIssue]]] | None = None
        """Replaces ``Reframe.jobs.validate`` as the queue's validation on ``add``."""
        monkeypatch.setattr(cli, "get_queue", self.make)

    def make(self, app: Reframe) -> FakeQueue:
        queue = FakeQueue(
            app.events,
            log_dir=self.log_dir,
            validate=self.validator or app.jobs.validate,
            behaviour=self.behaviour,
            on_running=self.on_running,
        )
        self.made.append(queue)
        return queue

    @property
    def queue(self) -> FakeQueue:
        assert len(self.made) == 1
        return self.made[0]


@pytest.fixture
def queues(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Queues:
    return Queues(monkeypatch, tmp_path / "logs")
