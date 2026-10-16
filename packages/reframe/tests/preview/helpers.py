"""Helpers of the C-10 picture tests: a :class:`MediaTaskContext` with the real FFmpeg and a
fixed capability snapshot, recorded probes, jobs, PNG pixels, and FFmpeg processes."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psutil

from reframe.definitions import load_definitions
from reframe.events import EventBus
from reframe.mediatask import MediaTaskContext
from reframe.models import (
    AppSettings,
    CapabilitySnapshot,
    EncoderState,
    EncoderStatus,
    JobSettings,
    MediaSource,
    OutputSettings,
    SourceFingerprint,
    SourceRef,
    TaskInfo,
    ToolInfo,
    ToolName,
    ToolSet,
    ToolStatus,
)
from reframe.probe import ProbeError, Prober, parse_ffprobe
from reframe.tasks import TaskManager
from reframe.tools import CancelToken
from reframe_testing import media

ROOT = Path(__file__).resolve().parents[4]
PROBES = ROOT / "testdata" / "probes"
DEFS = load_definitions()


def caps(*, libplacebo: bool | None = False) -> CapabilitySnapshot:
    """Every encoder available, every filter of the definitions in the build; libplacebo
    usable (``True``), failed (``False``, the default: deterministic CPU tone mapping) or not
    checked yet (``None``)."""
    encoders = {
        enc_id: EncoderStatus(id=enc_id, state=EncoderState.AVAILABLE)
        for enc_id in [*DEFS.video_encoders, *DEFS.audio_encoders]
    }
    names = sorted({n for f in DEFS.filters.values() for i in f.implementations for n in i.filters})
    return CapabilitySnapshot(
        encoders=encoders,
        filters=names,
        filter_failures={"libplacebo": "No working Vulkan driver"} if libplacebo is False else {},
        untested_filters=["libplacebo"] if libplacebo is None else [],
    )


def recorded(name: str) -> MediaSource:
    """A source from the recorded ffprobe JSON of a fixture, at ``/media/<name>``."""
    probe = PROBES / "fixtures" / f"{name}.json"
    frames = probe.with_name(probe.name.removesuffix(".json") + ".frames.json")
    return parse_ffprobe(
        json.loads(probe.read_text(encoding="utf-8")),
        Path("/media") / name,
        frames=json.loads(frames.read_text(encoding="utf-8")) if frames.exists() else None,
        fingerprint=SourceFingerprint(size=0, mtime=0.0),
    )


def tool(name: ToolName, path: str | None) -> ToolInfo:
    if path is None:
        return ToolInfo(name=name, status=ToolStatus.MISSING, reason=f"{name} was not found.")
    return ToolInfo(name=name, status=ToolStatus.FOUND, path=Path(path))


def real_tools(*, mkvpropedit: bool = True) -> ToolSet:
    return ToolSet(
        ffmpeg=tool("ffmpeg", media.find_ffmpeg()),
        ffprobe=tool("ffprobe", media.find_ffprobe()),
        mkvpropedit=tool("mkvpropedit", shutil.which("mkvpropedit") if mkvpropedit else None),
        mediainfo=tool("mediainfo", None),
    )


class Tools:
    def __init__(self, tools: ToolSet) -> None:
        self.tools = tools

    async def status(self) -> ToolSet:
        return self.tools


class Sources:
    """Probes with the real ffprobe (memoised, like the facade's probe cache)."""

    def __init__(self, ffprobe: str) -> None:
        self.prober = Prober(ffprobe, use_mediainfo=False)
        self.known: dict[str, MediaSource] = {}
        self.calls = 0

    async def probe(
        self,
        path: str | os.PathLike[str],
        *,
        use_cache: bool = True,
        cancel: CancelToken | None = None,
    ) -> MediaSource | ProbeError:
        self.calls += 1
        key = os.fspath(path)
        if use_cache and key in self.known:
            return self.known[key]
        outcome = await self.prober.probe(path, cancel=cancel)
        if isinstance(outcome, MediaSource):
            self.known[key] = outcome
        return outcome

    async def store(self, source: MediaSource) -> None:
        self.known[os.fspath(source.ref.path)] = source

    async def update(
        self, source: MediaSource, change: Callable[[MediaSource], MediaSource]
    ) -> None:
        key = os.fspath(source.ref.path)
        self.known[key] = change(self.known.get(key, source))


class Caps:
    """``Reframe.capabilities``: a fixed snapshot; ``detected`` (when set) is the result of a
    detection that :meth:`wait` waits for."""

    def __init__(self, snapshot: CapabilitySnapshot) -> None:
        self._snapshot = snapshot
        self.detected: CapabilitySnapshot | None = None
        self.waits = 0

    @property
    def snapshot(self) -> CapabilitySnapshot:
        return self._snapshot

    async def wait(self) -> CapabilitySnapshot:
        self.waits += 1
        if self.detected is not None:
            self._snapshot = self.detected
        return self._snapshot


@dataclass
class Env:
    """A context and its parts."""

    ctx: MediaTaskContext
    tasks: TaskManager
    caps: Caps
    sources: Sources
    settings: AppSettings = field(default_factory=AppSettings)

    async def finish(self, info: TaskInfo) -> tuple[TaskInfo, Any]:
        done = await self.tasks.wait(info.id)
        return done, self.tasks.value(info.id)


def make_env(
    cache_dir: Path,
    *,
    snapshot: CapabilitySnapshot | None = None,
    settings: AppSettings | None = None,
    tools: ToolSet | None = None,
) -> Env:
    """A context with the real FFmpeg (``media.find_ffmpeg``), call it inside a running
    event loop (the task manager needs one)."""
    events = EventBus()
    tasks = TaskManager(events)
    toolset = tools if tools is not None else real_tools()
    ffprobe = toolset.ffprobe.path
    assert ffprobe is not None
    sources = Sources(str(ffprobe))
    capabilities = Caps(snapshot if snapshot is not None else caps())
    current = settings if settings is not None else AppSettings()
    ctx = MediaTaskContext(
        tasks=tasks,
        tools=Tools(toolset),
        sources=sources,
        capabilities=capabilities,
        settings=lambda: current,
        events=events,
        cache_dir=cache_dir,
        definitions=load_definitions,
    )
    return Env(ctx=ctx, tasks=tasks, caps=capabilities, sources=sources, settings=current)


def job_for(path: Path, *, container: str = "mkv", **video: Any) -> JobSettings:
    """A job of ``path`` without audio and subtitles; ``video`` are VideoSettings fields
    (default: libx264 8-bit, ultrafast)."""
    settings: dict[str, Any] = {
        "encoder": "libx264",
        "bit_depth": 8,
        "preset": "ultrafast",
        **video,
    }
    job = JobSettings(
        source=SourceRef(path=path),
        output=OutputSettings.model_validate({"container": container}),
    )
    job.video = job.video.model_validate({**job.video.model_dump(), **settings})
    return job


def ffmpeg() -> str:
    path = media.find_ffmpeg()
    assert path is not None
    return path


def run_ffmpeg(*args: str) -> subprocess.CompletedProcess[str]:
    """A helper FFmpeg run (making test files, reading pixels): fails the test on an error."""
    proc = subprocess.run(
        [ffmpeg(), "-hide_banner", "-nostdin", "-y", "-loglevel", "error", *args],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return proc


def rgb_pixels(png: Path) -> bytes:
    """The RGB24 pixels of a PNG (decoded by FFmpeg)."""
    proc = subprocess.run(
        [ffmpeg(), "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(png),
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True,
        timeout=60,
        check=True,
    )  # fmt: skip
    return proc.stdout


def ffmpeg_children(predicate: Callable[[list[str]], bool] | None = None) -> list[psutil.Process]:
    """FFmpeg processes started by this test process (and match ``predicate`` on argv)."""
    found: list[psutil.Process] = []
    for child in psutil.Process().children(recursive=True):
        try:
            argv = child.cmdline()
        except psutil.Error:
            continue
        if (
            argv
            and Path(argv[0]).name.startswith("ffmpeg")
            and (predicate is None or predicate(argv))
        ):
            found.append(child)
    return found
