"""The capability cache: key, round trip, misses, pruning."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from reframe.capabilities import CacheKey, CapabilityCache, DetectionOptions, cache_key
from reframe.capabilities.cache import (
    CACHE_FORMAT,
    definitions_fingerprint,
    detector_fingerprint,
)
from reframe.definitions import load_definitions
from reframe.models import CapabilitySnapshot, EncoderState, EncoderStatus, ToolStatus
from reframe_testing.capabilities import ffmpeg_info

DEFS = load_definitions()


@pytest.fixture
def binary(tmp_path: Path) -> Path:
    path = tmp_path / "bin" / "ffmpeg"
    path.parent.mkdir()
    path.write_bytes(b"not really ffmpeg")
    return path


def key_for(binary: Path, **kw: object) -> CacheKey:
    options = DetectionOptions(os="linux", **kw)  # type: ignore[arg-type]
    key = cache_key(
        ffmpeg_info(binary),
        gpu="linux; drm 0x1002:0x7480 amdgpu",
        options=options,
        definitions=DEFS,
    )
    assert key is not None
    return key


def snapshot(binary: Path) -> CapabilitySnapshot:
    return CapabilitySnapshot(
        encoders={"libx265": EncoderStatus(id="libx265", state=EncoderState.AVAILABLE)},
        filters=["zscale"],
        ffmpeg=binary,
        ffmpeg_version="n9.0.2",
        detecting=True,
        from_cache=True,
    )


def test_key_parts(binary: Path) -> None:
    key = key_for(binary)
    stat = binary.stat()
    assert (key.ffmpeg, key.size, key.mtime_ns) == (str(binary), stat.st_size, stat.st_mtime_ns)
    assert key.version == "n9.0.2-17-g2a571b6068-20260930"
    assert key.gpu == "linux; drm 0x1002:0x7480 amdgpu"
    assert json.loads(key.options) == {
        "hardware_tests": True,
        "os": "linux",
        "vaapi_device": None,
        "render_nodes": None,
        "filter_tests": ["libplacebo"],
    }
    assert key.definitions == definitions_fingerprint(DEFS)
    assert key.detector == detector_fingerprint()
    assert len(key.digest()) == 64


def test_key_changes(binary: Path) -> None:
    key = key_for(binary)
    assert key_for(binary) == key
    assert key_for(binary, hardware_tests=False) != key
    assert key_for(binary, vaapi_device="/dev/dri/renderD129") != key
    nodes = key_for(binary, render_nodes=("/dev/dri/renderD128",))
    assert nodes != key
    assert key_for(binary, render_nodes=("/dev/dri/renderD128", "/dev/dri/renderD129")) != nodes
    assert key_for(binary, filter_tests=()) != key
    env = cache_key(
        ffmpeg_info(binary, env={"LIBVA_DRIVERS_PATH": "/usr/lib/dri"}),
        gpu=key.gpu,
        options=DetectionOptions(os="linux"),
        definitions=DEFS,
    )
    assert env is not None
    assert env != key
    binary.write_bytes(b"another build, another size")
    assert key_for(binary) != key


def test_definition_changes_change_the_key() -> None:
    hevc = DEFS.video_encoders["hevc_vaapi"]
    changed = DEFS.model_copy(
        update={
            "video_encoders": {
                **DEFS.video_encoders,
                "hevc_vaapi": hevc.model_copy(update={"pix_fmts": {"8": "nv12"}}),
            }
        }
    )
    assert definitions_fingerprint(changed) != definitions_fingerprint(DEFS)
    relabelled = DEFS.model_copy(
        update={
            "video_encoders": {
                **DEFS.video_encoders,
                "hevc_vaapi": hevc.model_copy(update={"label": "Another label"}),
            }
        }
    )
    assert definitions_fingerprint(relabelled) == definitions_fingerprint(DEFS)


def test_no_key_without_a_binary(tmp_path: Path) -> None:
    options = DetectionOptions(os="linux")
    assert cache_key(ffmpeg_info(None), gpu="", options=options, definitions=DEFS) is None
    missing = ffmpeg_info(tmp_path / "gone", status=ToolStatus.MISSING)
    assert cache_key(missing, gpu="", options=options, definitions=DEFS) is None


def test_round_trip(tmp_path: Path, binary: Path) -> None:
    cache = CapabilityCache(tmp_path / "caps")
    key = key_for(binary)
    assert cache.get(key) is None
    cache.put(key, snapshot(binary))
    got = cache.get(key)
    assert got is not None
    assert got.status("libx265").state is EncoderState.AVAILABLE
    assert (got.detecting, got.from_cache) == (False, False)  # stored as a finished result
    assert got.filters == ["zscale"]
    files = list((tmp_path / "caps").iterdir())
    assert len(files) == 1
    entry = json.loads(files[0].read_text(encoding="utf-8"))
    assert entry["format"] == CACHE_FORMAT
    assert entry["key"] == key.to_json()


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        "[]",
        json.dumps({"format": 99}),
        "KEY_MISMATCH",
        "INVALID_SNAPSHOT",
    ],
)
def test_bad_entries_are_misses(tmp_path: Path, binary: Path, content: str) -> None:
    cache = CapabilityCache(tmp_path / "caps")
    key = key_for(binary)
    cache.put(key, snapshot(binary))
    (path,) = (tmp_path / "caps").iterdir()
    entry = json.loads(path.read_text(encoding="utf-8"))
    if content == "KEY_MISMATCH":
        entry["key"]["gpu"] = "another GPU"
        content = json.dumps(entry)
    elif content == "INVALID_SNAPSHOT":
        entry["snapshot"]["encoders"]["libx265"]["state"] = "a state from a newer Reframe"
        content = json.dumps(entry)
    path.write_text(content, encoding="utf-8")
    assert cache.get(key) is None
    cache.put(key, snapshot(binary))  # the next detection overwrites it
    assert cache.get(key) is not None


def test_prune_keeps_the_newest(tmp_path: Path, binary: Path) -> None:
    folder = tmp_path / "caps"
    cache = CapabilityCache(folder, max_entries=2)
    keys = [key_for(binary, vaapi_device=f"/dev/dri/renderD{n}") for n in range(128, 132)]
    for n, key in enumerate(keys):
        cache.put(key, snapshot(binary))
        path = folder / f"{key.digest()[:32]}.json"
        os.utime(path, (1_000_000 + n, 1_000_000 + n))
    left_behind = folder / ".tmp-left-behind.json"
    left_behind.write_text("x", encoding="utf-8")
    os.utime(left_behind, (1_000_000, 1_000_000))
    cache.prune()
    assert [cache.get(key) is not None for key in keys] == [False, False, True, True]
    assert not left_behind.exists()


def test_prune_keeps_the_temporary_file_of_a_running_write(tmp_path: Path, binary: Path) -> None:
    """Another process (the CLI next to the server) may be writing its entry right now."""
    folder = tmp_path / "caps"
    folder.mkdir()
    writing = folder / ".tmp-another-process.json"
    writing.write_text("{", encoding="utf-8")
    CapabilityCache(folder).put(key_for(binary), snapshot(binary))
    assert writing.exists()


def test_unwritable_cache_is_ignored(tmp_path: Path, binary: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("not a folder", encoding="utf-8")
    cache = CapabilityCache(blocker / "caps")
    cache.put(key_for(binary), snapshot(binary))  # logs, does not raise
    assert cache.get(key_for(binary)) is None
    cache.prune()
