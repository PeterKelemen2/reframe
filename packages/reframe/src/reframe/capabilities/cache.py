"""The capability cache (05 §C-4, 02 §State model): one JSON file per key in the cache dir.

**Key** (:class:`CacheKey`): the ffmpeg binary (absolute path, size, mtime) and its version
and extra environment (``LIBVA_DRIVERS_PATH``), the GPU fingerprint
(:mod:`reframe.capabilities.fingerprint`), the detection options (hardware tests on/off, the
VAAPI device forced in the settings, the render nodes, the filter tests, the OS), a hash of
the definition fields that detection uses (ids, platforms, pixel formats, hardware setup)
and a hash of the detection code. Any change is a miss.

**Entry**: ``<cache dir>/<digest>.json`` = ``{"format": 1, "key": {…}, "snapshot": {…}}``.
Writes are atomic (a temporary file, then ``os.replace``). An entry that cannot be read, has
another format or key, or does not validate (for example one written by a newer Reframe) is a
miss and is overwritten by the next detection. Only the newest :data:`MAX_ENTRIES` entries are
kept (switching between a few ffmpeg builds keeps their results). Cache errors never fail a
detection.

This is a cache, not a document: a newer Reframe's entry that this version cannot validate
is simply detected again, so it needs no schema version or migration.
"""

from __future__ import annotations

import contextlib
import functools
import hashlib
import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from reframe.capabilities.detect import DetectionOptions, current_os
from reframe.definitions import Definitions
from reframe.models.capabilities import CapabilitySnapshot
from reframe.models.tools import ToolInfo

__all__ = [
    "CACHE_FORMAT",
    "MAX_ENTRIES",
    "CacheKey",
    "CapabilityCache",
    "cache_key",
    "definitions_fingerprint",
    "detector_fingerprint",
]

log = logging.getLogger(__name__)

CACHE_FORMAT = 1
MAX_ENTRIES = 8
#: The modules whose source decides what a detection produces.
_DETECTOR_MODULES = ("parse.py", "reasons.py", "hwtest.py", "detect.py", "devices.py")


@functools.cache
def detector_fingerprint() -> str:
    """A hash of the detection modules' source; the Reframe version without the sources."""
    digest = hashlib.sha256()
    here = Path(__file__).resolve().parent
    try:
        for name in _DETECTOR_MODULES:
            digest.update(name.encode())
            digest.update((here / name).read_bytes())
    except OSError:
        from reframe import __version__

        return f"reframe-{__version__}"
    return digest.hexdigest()[:16]


def definitions_fingerprint(definitions: Definitions) -> str:
    """A hash of what detection reads from the definitions."""
    data = {
        "video": [
            enc.model_dump(
                mode="json", include={"id", "hardware", "platforms", "pix_fmts", "hardware_setup"}
            )
            for enc in definitions.video_encoders.values()
        ],
        "audio": sorted(definitions.audio_encoders),
    }
    text = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class CacheKey:
    ffmpeg: str
    """Absolute path of the binary."""
    size: int
    mtime_ns: int
    version: str | None
    env: tuple[tuple[str, str], ...]
    """``ToolInfo.env`` (``LIBVA_DRIVERS_PATH``), sorted."""
    gpu: str
    options: str
    definitions: str
    detector: str

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["env"] = [list(pair) for pair in self.env]
        return data

    def digest(self) -> str:
        text = json.dumps(self.to_json(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode("utf-8", errors="surrogatepass")).hexdigest()


def cache_key(
    ffmpeg: ToolInfo, *, gpu: str, options: DetectionOptions, definitions: Definitions
) -> CacheKey | None:
    """The key for a detection with ``ffmpeg`` (stats the binary: blocking); ``None`` when
    the binary cannot be stat'ed."""
    if ffmpeg.path is None:
        return None
    try:
        path = Path(os.path.abspath(ffmpeg.path))
        stat = path.stat()
    except OSError:
        return None
    detection = {
        "hardware_tests": options.hardware_tests,
        "os": options.os or current_os(),
        "vaapi_device": options.vaapi_device,
        "render_nodes": list(options.render_nodes) if options.render_nodes is not None else None,
        "filter_tests": list(options.filter_tests),
    }
    return CacheKey(
        ffmpeg=str(path),
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        version=ffmpeg.version,
        env=tuple(sorted(ffmpeg.env.items())),
        gpu=gpu,
        options=json.dumps(detection, sort_keys=True),
        definitions=definitions_fingerprint(definitions),
        detector=detector_fingerprint(),
    )


class CapabilityCache:
    """Detection results by :class:`CacheKey`, as JSON files in one folder. Blocking file I/O:
    the capability service calls it in a worker thread."""

    def __init__(self, folder: Path, *, max_entries: int = MAX_ENTRIES) -> None:
        self.folder = Path(folder)
        self.max_entries = max_entries

    def _path(self, key: CacheKey) -> Path:
        return self.folder / f"{key.digest()[:32]}.json"

    def get(self, key: CacheKey) -> CapabilitySnapshot | None:
        path = self._path(key)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(raw, dict) or raw.get("format") != CACHE_FORMAT:
            return None
        if raw.get("key") != key.to_json():
            return None
        try:
            return CapabilitySnapshot.model_validate(raw.get("snapshot"))
        except ValidationError as exc:
            log.info("capability cache entry %s does not validate: %s", path.name, exc)
            return None

    def put(self, key: CacheKey, snapshot: CapabilitySnapshot) -> None:
        """Store ``snapshot`` (``from_cache`` and ``detecting`` are stored as ``False``)."""
        stored = snapshot.model_copy(update={"from_cache": False, "detecting": False})
        entry = {
            "format": CACHE_FORMAT,
            "key": key.to_json(),
            "snapshot": stored.model_dump(mode="json"),
        }
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.folder, prefix=".tmp-", suffix=".json")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(entry, f, indent=1)
                os.replace(tmp, self._path(key))
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
                raise
        except OSError as exc:
            log.warning("capability cache: cannot write to %s: %s", self.folder, exc)
            return
        self.prune()

    def prune(self) -> None:
        """Keep the newest :attr:`max_entries` entries; remove temporary files."""
        try:
            entries = [p for p in self.folder.iterdir() if p.suffix == ".json"]
        except OSError:
            return

        def mtime(path: Path) -> float:
            try:
                return path.stat().st_mtime
            except OSError:
                return 0.0

        entries.sort(key=mtime, reverse=True)
        stale = [p for p in entries if p.name.startswith(".tmp-")]
        kept = [p for p in entries if not p.name.startswith(".tmp-")]
        for path in [*stale, *kept[self.max_entries :]]:
            with contextlib.suppress(OSError):
                path.unlink()
