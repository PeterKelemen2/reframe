from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from reframe.models import MediaSource, SourceFingerprint
from reframe.probe import parse_ffprobe

REPO = Path(__file__).resolve().parents[4]
PROBES = REPO / "testdata" / "probes"


def load_probe(name: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """``(ffprobe JSON, frames JSON or None)`` of ``testdata/probes/<name>.json``."""
    path = PROBES / f"{name}.json"
    frames_path = PROBES / f"{name}.frames.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    frames = json.loads(frames_path.read_text(encoding="utf-8")) if frames_path.exists() else None
    return data, frames


def parse_probe(name: str) -> MediaSource:
    data, frames = load_probe(name)
    return parse_ffprobe(
        data,
        Path("/media") / str(data["format"]["filename"]),
        frames=frames,
        fingerprint=SourceFingerprint(size=0, mtime=0.0),
    )


@pytest.fixture
def probe_source() -> Callable[[str], MediaSource]:
    """``probe_source("pgs")`` → the parsed ``MediaSource`` of a recorded probe."""
    return parse_probe


@pytest.fixture
def probes_dir() -> Path:
    return PROBES
