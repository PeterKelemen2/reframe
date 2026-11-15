"""Record an anonymised probe of a real Matroska file: ffprobe's JSON and the track headers.

    uv run python testdata/probes/real/record_real.py --ffprobe "$BIN/ffprobe" NAME FILE

The file is only read. ``NAME.json`` is the output of Reframe's probe command
(:func:`reframe.probe.probe_argv`) and ``NAME.tracks.mkv`` a small Matroska file with the
EBML header, a Segment of unknown size, ``Info`` and ``Tracks`` (no clusters), so that
:func:`reframe.probe.matroska.read_matroska` gives what it gives for the real file.

Anonymised: the file name, every title and track name, the segment and track UIDs, the dates
and ``CodecPrivate`` are replaced or left out; the numbers that the probe uses are kept.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from reframe.probe import matroska
from reframe.probe.ffprobe import probe_argv

HERE = Path(__file__).resolve().parent
NEUTRAL_DATE = "2020-01-01 00:00:00"
NEUTRAL_TIME = "2020-01-01T00:00:00.000000Z"
#: Tags that can name the file or its release.
NAMING_TAGS = frozenset({"title", "comment", "description", "filename", "handler_name"})

_EBML, _SEGMENT, _INFO, _TRACKS, _TRACK_ENTRY = 0x1A45DFA3, 0x18538067, 0x1549A966, 0x1654AE6B, 0xAE
_TRACK_UID = 0x73C5
#: ``Info`` children kept: TimestampScale, Duration, MuxingApp, WritingApp.
_INFO_KEPT = frozenset({0x2AD7B1, 0x4489, 0x4D80, 0x5741})
#: ``TrackEntry`` children kept: number, type, the flags, lacing, codec ID, the languages,
#: default duration, the Video and Audio elements and ``ContentEncodings``.
_TRACK_KEPT = frozenset(
    {0xD7, 0x83, 0xB9, 0x88, 0x55AA, 0x55AB, 0x55AC, 0x55AD, 0x55AE, 0x55AF, 0x9C, 0x86}
    | {0x22B59C, 0x22B59D, 0x23E383, 0xE0, 0xE1, 0x6D80}
)


def _vint_size(size: int) -> bytes:
    return bytes([0x01]) + size.to_bytes(7, "big")


def _element(element_id: int, payload: bytes, *, unknown: bool = False) -> bytes:
    raw_id = element_id.to_bytes((element_id.bit_length() + 7) // 8, "big")
    size = bytes([0x01]) + b"\xff" * 7 if unknown else _vint_size(len(payload))
    return raw_id + size + payload


def _filtered(payload: bytes, kept: frozenset[int]) -> bytes:
    budget = matroska._Budget()
    return b"".join(
        _element(child_id, data)
        for child_id, data in matroska._children(payload, budget, "an element")
        if child_id in kept
    )


def header_extract(path: Path) -> bytes:
    """EBML header + Segment (unknown size) + Info + Tracks of ``path``, anonymised."""
    info = matroska.read_matroska(path)  # also checks that the file is one the reader reads
    data = path.read_bytes() if path.stat().st_size < 64 * 1024 else _head(path, info)
    _, size, header = matroska._header(data, 0)
    assert size is not None
    ebml = data[: header + size]
    pos = info.segment
    parts: list[bytes] = []
    budget = matroska._Budget()
    for element_id, payload in matroska._iter_children(data[pos:], budget):
        if element_id == _INFO:
            parts.append(_element(_INFO, _filtered(payload, _INFO_KEPT)))
        elif element_id == _TRACKS:
            entries = []
            for number, (child_id, entry) in enumerate(
                matroska._children(payload, budget, "Tracks"), start=1
            ):
                if child_id == _TRACK_ENTRY:
                    uid = _element(_TRACK_UID, number.to_bytes(1, "big"))
                    entries.append(_element(_TRACK_ENTRY, _filtered(entry, _TRACK_KEPT) + uid))
            parts.append(_element(_TRACKS, b"".join(entries)))
        if len(parts) == 2:
            break
    if len(parts) != 2:
        raise SystemExit(f"{path}: Info and Tracks are not both before the first cluster")
    return ebml + _element(_SEGMENT, b"".join(parts), unknown=True)


def _head(path: Path, info: matroska.MatroskaFile) -> bytes:
    """The file up to its first cluster (Info and Tracks are there in mkvmerge's files)."""
    with path.open("rb") as handle:
        data = handle.read(16 * 1024 * 1024)
    cluster = data.find(b"\x1f\x43\xb6\x75", info.segment)
    if cluster < 0:
        raise SystemExit(f"{path}: no cluster in the first 16 MB")
    return data[:cluster]


def anonymised(data: dict[str, Any], name: str) -> dict[str, Any]:
    """ffprobe's JSON without anything that names the file or its release."""
    out = json.loads(json.dumps(data))
    out["format"]["filename"] = f"{name}.mkv"
    for holder in [out["format"], *out.get("streams", []), *out.get("chapters", [])]:
        tags = holder.get("tags")
        if not isinstance(tags, dict):
            continue
        for key in list(tags):
            base = key.split("-")[0].lower()
            if base in NAMING_TAGS:
                del tags[key]
            elif base == "_statistics_writing_date_utc":
                tags[key] = NEUTRAL_DATE
            elif base == "creation_time":
                tags[key] = NEUTRAL_TIME
    for number, chapter in enumerate(out.get("chapters", []), start=1):
        chapter["id"] = number
        chapter["tags"] = {"title": f"Chapter {number:02d}"}
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--ffprobe", required=True)
    parser.add_argument("name")
    parser.add_argument("file", type=Path)
    args = parser.parse_args(argv)
    out = subprocess.run(
        probe_argv(args.ffprobe, str(args.file)), capture_output=True, text=True, check=True
    )
    probe = anonymised(json.loads(out.stdout), args.name)
    (HERE / f"{args.name}.json").write_text(json.dumps(probe, indent=4) + "\n", encoding="utf-8")
    (HERE / f"{args.name}.tracks.mkv").write_bytes(header_extract(args.file))
    return 0


if __name__ == "__main__":
    sys.exit(main())
