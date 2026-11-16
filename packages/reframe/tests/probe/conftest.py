from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from reframe.models import MediaSource, SourceFingerprint
from reframe.probe import Prober, ProbeTool, parse_ffprobe
from reframe.probe.matroska import MatroskaFile, read_matroska
from reframe_testing import fake_tools as ft

REPO = Path(__file__).resolve().parents[4]
PROBES = REPO / "testdata" / "probes"


def streams_rule(*actions: ft.Action, exit_code: int = 0) -> ft.Rule:
    """The rule for the main ffprobe call (the one with ``-show_streams``)."""
    return ft.Rule(tool="ffprobe", argv_has=["-show_streams"], actions=actions, exit_code=exit_code)


def stdout_file(path: Path) -> ft.Action:
    return {"stdout_file": str(path)}


def make_prober(fake: ft.FakeTools, **kw: object) -> Prober:
    return Prober(ProbeTool(str(fake.ffprobe), version="n-fake"), **kw)  # type: ignore[arg-type]


def load_probe(name: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """``(ffprobe JSON, frames JSON or None)`` of ``testdata/probes/<name>.json``."""
    path = PROBES / f"{name}.json"
    frames_path = PROBES / f"{name}.frames.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    frames = json.loads(frames_path.read_text(encoding="utf-8")) if frames_path.exists() else None
    return data, frames


def recorded_tracks(path: Path) -> MatroskaFile | None:
    """The track headers recorded next to ``<name>.json`` as ``<name>.tracks.mkv``, if any."""
    tracks = path.with_name(path.name.removesuffix(".json") + ".tracks.mkv")
    return read_matroska(tracks) if tracks.exists() else None


def parse_probe(name: str) -> MediaSource:
    data, frames = load_probe(name)
    return parse_ffprobe(
        data,
        Path("/media") / str(data["format"]["filename"]),
        frames=frames,
        fingerprint=SourceFingerprint(size=0, mtime=0.0),
        matroska=recorded_tracks(PROBES / f"{name}.json"),
    )


@pytest.fixture
def probe_source() -> Callable[[str], MediaSource]:
    """``probe_source("pgs")`` → the parsed ``MediaSource`` of a recorded probe."""
    return parse_probe


@pytest.fixture
def probes_dir() -> Path:
    return PROBES
