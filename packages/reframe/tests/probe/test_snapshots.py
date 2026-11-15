"""Snapshots of the parsed ``MediaSource`` for every recorded ffprobe JSON.

The fixtures under ``testdata/probes/fixtures/`` were probed with the pinned build, so the
snapshots do not depend on the FFmpeg that runs the tests. A probe recorded with its track
headers (``<name>.tracks.mkv``) is parsed with them, as the prober does.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from syrupy.assertion import SnapshotAssertion

from reframe.models import MediaSource, SourceFingerprint
from reframe.probe import parse_ffprobe

from .conftest import recorded_tracks

PROBES = Path(__file__).resolve().parents[4] / "testdata" / "probes"
NOT_PROBES = {"index.json", "confirmed_strings.json"}

#: Each of these must have a recorded probe.
REQUIRED_PROBES = {
    "truehd-atmos",
    "dts-hd-ma",
    "dts-x",
    "pgs",
    "ass-fonts",
    "vfr",
    "dvd-interlaced",
    "hdr10",
    "dv-p8",
}


def _probe_files() -> list[str]:
    files = [
        p.relative_to(PROBES).as_posix()
        for p in PROBES.rglob("*.json")
        if p.name not in NOT_PROBES and not p.name.endswith(".frames.json")
    ]
    return sorted(files)


PROBE_FILES = _probe_files()


def _parse(rel: str) -> MediaSource:
    path = PROBES / rel
    frames_path = path.with_name(path.name.removesuffix(".json") + ".frames.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    frames = json.loads(frames_path.read_text(encoding="utf-8")) if frames_path.exists() else None
    return parse_ffprobe(
        data,
        Path("/media", *_media_name(rel, data).split("/")),
        frames=frames,
        fingerprint=SourceFingerprint(size=0, mtime=0.0),
        matroska=recorded_tracks(path),
    )


def _media_name(rel: str, data: dict[str, Any]) -> str:
    if rel.startswith("fixtures/"):
        return rel.removeprefix("fixtures/").removesuffix(".json")
    return str(data["format"]["filename"])


def _normalised(source: MediaSource) -> dict[str, Any]:
    dumped = source.model_dump(mode="json")
    dumped["ref"]["path"] = Path(dumped["ref"]["path"]).relative_to(Path("/media")).as_posix()
    return dumped


@pytest.mark.parametrize("rel", PROBE_FILES)
def test_media_source_snapshot(rel: str, snapshot: SnapshotAssertion) -> None:
    source = _parse(rel)
    assert _normalised(source) == snapshot
    # The parsed source survives a JSON round trip (it is what the probe cache stores).
    assert MediaSource.model_validate_json(source.model_dump_json()) == source


def test_every_required_probe_is_recorded() -> None:
    recorded = {Path(rel).stem for rel in PROBE_FILES if "/" not in rel}
    assert recorded >= REQUIRED_PROBES


def test_every_fixture_file_is_recorded() -> None:
    from reframe_testing import media

    outputs = {out for recipe in media.build_recipes().values() for out in recipe.outputs}
    recorded = {rel.removeprefix("fixtures/").removesuffix(".json") for rel in PROBE_FILES}
    assert outputs <= recorded


def test_index_documents_every_recorded_probe() -> None:
    index = json.loads((PROBES / "index.json").read_text(encoding="utf-8"))
    recorded = {Path(rel).stem for rel in PROBE_FILES if "/" not in rel}
    assert set(index["probes"]) == recorded
    for name, entry in index["probes"].items():
        assert entry["synthesised"] == bool(entry["edits"]), name
        for edit in entry["edits"]:
            assert edit["why"], (name, edit)
        data = json.loads((PROBES / f"{name}.json").read_text(encoding="utf-8"))
        assert data["format"]["filename"] == entry["file"], "file names are anonymised"
