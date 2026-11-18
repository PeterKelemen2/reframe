"""The Matroska track reader, and the prober's ``language_ietf``."""

from __future__ import annotations

import io
import json
import shutil
import struct
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from reframe.probe import matroska
from reframe.probe.matroska import MatroskaError, read_matroska, tracks_by_kind
from reframe_testing.ebml import cluster, element, header, info, track, tracks, uint


def write(tmp_path: Path, data: bytes, name: str = "t.mkv") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_reads_tracks_title_and_defaults(tmp_path: Path) -> None:
    segment = info("Film") + tracks(
        track(1, 1),
        track(2, 2, language="por", ietf="pt-BR", name="Dub", default=0, commentary=1),
        track(3, 0x11, language="hun"),
        track(4, 0x12),
    )
    data = header() + element(0x18538067, segment + cluster())
    found = read_matroska(write(tmp_path, data))
    assert found.doc_type == "matroska"
    assert found.title == "Film"
    video, audio, sub, other = found.tracks
    assert (video.kind, video.language, video.language_ietf, video.default) == (
        "video", "eng", None, True,
    )  # fmt: skip
    assert (audio.number, audio.language, audio.language_ietf, audio.name) == (
        2, "por", "pt-BR", "Dub",
    )  # fmt: skip
    assert (audio.default, audio.commentary, audio.forced) == (False, True, False)
    assert (sub.kind, other.kind) == ("subtitle", "other")
    kinds = tracks_by_kind(found)
    assert [len(kinds[k]) for k in ("video", "audio", "subtitle", "other")] == [1, 1, 1, 1]


def test_unknown_size_segment_and_tracks_after_a_seek_head(tmp_path: Path) -> None:
    track_data = tracks(track(1, 2, language="ger", ietf="de"))
    info_data = info("T")
    head_size = 200  # the seek head is padded to this length with a Void
    first = cluster()
    tracks_pos = head_size + len(first)
    info_pos = tracks_pos + len(track_data)

    def seek(target: int, position: int) -> bytes:
        return element(
            0x4DBB,
            element(0x53AB, target.to_bytes(4, "big"))
            + element(0x53AC, position.to_bytes(8, "big")),
        )

    seeks = seek(0x1654AE6B, tracks_pos) + seek(0x1549A966, info_pos)
    seek_head = element(0x114D9B74, seeks)
    assert len(seek_head) <= head_size
    seek_head = element(0x114D9B74, seeks + element(0xEC, b"\0" * (head_size - len(seek_head) - 9)))
    assert len(seek_head) == head_size
    segment = seek_head + first + track_data + info_data
    data = header() + element(0x18538067, segment, unknown=True)
    found = read_matroska(write(tmp_path, data))
    assert [t.language_ietf for t in found.tracks] == ["de"]
    assert found.title == "T"


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"", "truncated"),
        (b"\x00\x00", "invalid variable-size integer"),
        (element(0x1A45DFA2, b""), "not an EBML file"),
        (header("avi"), "not a Matroska file"),
        (header() + element(0x1F43B675, b""), "no Segment"),
        (header() + element(0x18538067, cluster()), "no Tracks element"),
        (header() + element(0x18538067, element(0x1654AE6B, b"", unknown=True)), "no Tracks"),
        (header() + bytes([0x1F, 0x43, 0xB6, 0x75, 0x7F]) , "truncated|no Segment"),
        (bytes([0x08, 0x00, 0x00, 0x00, 0x00, 0x81, 0x00]), "invalid element ID"),
    ],
)  # fmt: skip
def test_damaged_files_raise_matroska_error(tmp_path: Path, data: bytes, message: str) -> None:
    with pytest.raises(MatroskaError, match=message):
        read_matroska(write(tmp_path, data))


@pytest.mark.parametrize(
    "entry",
    [
        element(0x1549A966, element(0x2AD7B1, b"\x01" + b"\0" * 129)),  # TimestampScale
        element(0x1549A966, element(0x2AD7B1, b"\0" * 8 + b"\x01")),
        tracks(element(0xAE, element(0xD7, b"\0" * 8 + b"\x01") + uint(0x83, 1))),
    ],
    ids=["scale-of-130-bytes", "scale-of-9-bytes", "track-number-of-9-bytes"],
)
def test_an_unsigned_integer_over_eight_bytes_is_damaged(tmp_path: Path, entry: bytes) -> None:
    data = header() + element(0x18538067, entry + tracks(track(1, 1)))
    with pytest.raises(MatroskaError, match="over 8 bytes"):
        read_matroska(write(tmp_path, data))


def test_a_duration_too_large_for_a_float_is_none(tmp_path: Path) -> None:
    scale = element(0x2AD7B1, (1 << 63).to_bytes(8, "big"))
    duration = element(0x4489, struct.pack(">d", 1e300))
    data = header() + element(
        0x18538067, element(0x1549A966, scale + duration) + tracks(track(1, 1))
    )
    found = read_matroska(write(tmp_path, data))
    assert found.timestamp_scale == 1 << 63
    assert found.duration is None


def test_webm_doc_type_and_large_element_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = header("webm") + element(0x18538067, tracks(track(1, 1)))
    assert read_matroska(write(tmp_path, data)).doc_type == "webm"
    monkeypatch.setattr(matroska, "MAX_ELEMENT", 4)
    with pytest.raises(MatroskaError, match="too large"):
        read_matroska(write(tmp_path, data))


def test_scan_gives_up_after_max_top_level(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    voids = element(0xEC, b"") * 5
    data = header() + element(0x18538067, voids + tracks(track(1, 1)))
    monkeypatch.setattr(matroska, "MAX_TOP_LEVEL", 3)
    with pytest.raises(MatroskaError, match="no Tracks"):
        read_matroska(write(tmp_path, data))


def _tool(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        pytest.skip(f"{name} not found")
    return found


def propedit(mkvpropedit: str, path: Path, *args: str) -> None:
    subprocess.run([mkvpropedit, str(path), *args], check=True, capture_output=True)


def mkvmerge_tracks(path: Path) -> list[dict[str, object]]:
    out = subprocess.run(
        [_tool("mkvmerge"), "-J", str(path)], capture_output=True, text=True, check=True
    )
    return [t["properties"] for t in json.loads(out.stdout)["tracks"]]


def same_as_mkvmerge(path: Path) -> None:
    found = read_matroska(path)
    for ours, theirs in zip(found.tracks, mkvmerge_tracks(path), strict=True):
        assert ours.number == theirs["number"]
        assert ours.language == theirs.get("language", "eng")
        assert ours.language_ietf == theirs.get("language_ietf")
        assert ours.name == theirs.get("track_name")
        assert ours.default == theirs["default_track"]
        assert ours.forced == theirs["forced_track"]
        assert ours.commentary == theirs.get("flag_commentary", False)
        assert ours.hearing_impaired == theirs.get("flag_hearing_impaired", False)


@pytest.mark.needs_ffmpeg
def test_generated_fixture_and_mkvpropedit_edits(
    fixture_media: Callable[[str], Path], tmp_path: Path
) -> None:
    mkvpropedit = _tool("mkvpropedit")
    copy = tmp_path / "m.mkv"
    shutil.copyfile(fixture_media("multitrack"), copy)
    same_as_mkvmerge(copy)
    assert read_matroska(copy).title == "Reframe multi-track fixture"
    subprocess.run(
        [mkvpropedit, str(copy), "--edit", "track:a2", "--set", "language=por",
         "--set", "language-ietf=pt-BR", "--edit", "track:s1", "--set", "flag-commentary=1"],
        check=True, capture_output=True,
    )  # fmt: skip
    same_as_mkvmerge(copy)
    assert [t.language_ietf for t in read_matroska(copy).tracks][2] == "pt-BR"
    long = "N" * 6000
    args = [arg for n in (1, 2, 3) for arg in ("--edit", f"track:a{n}", "--set", f"name={long}")]
    subprocess.run([mkvpropedit, str(copy), *args], check=True, capture_output=True)
    same_as_mkvmerge(copy)
    assert read_matroska(copy).tracks[1].name == long


class _ShortReads(io.BytesIO):
    def read(self, size: int | None = -1, /) -> bytes:
        return super().read(min(3, size if size is not None and size >= 0 else 3))


def test_read_exactly_joins_short_reads_and_stops_at_the_end() -> None:
    handle = _ShortReads(bytes(range(20)))
    assert matroska.read_exactly(handle, 2, 10) == bytes(range(2, 12))
    assert matroska.read_exactly(handle, 15, 10) == bytes(range(15, 20))
