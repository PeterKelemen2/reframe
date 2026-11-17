"""The Matroska reader's limits and SeekHead checks, and the probe's ``language_ietf`` rules."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from reframe.metadata import remux_job
from reframe.models import JobSettings, MediaSource, SourceRef
from reframe.probe import matroska
from reframe.probe.matroska import MatroskaError, read_matroska
from reframe.probe.prober import Prober, apply_matroska
from reframe_testing.ebml import (
    cluster,
    element,
    header,
    info,
    track,
    tracks,
    with_bogus_seek_entry,
)
from reframe_testing.mkvtoolnix import with_bad_tag

from .conftest import parse_probe
from .test_matroska import _tool, mkvmerge_tracks, propedit, write

_SEGMENT = 0x18538067
_SEEK_HEAD = 0x114D9B74
_TRACKS = 0x1654AE6B


def seek(target: int, position: int, *, width: int = 8) -> bytes:
    return element(
        0x4DBB,
        element(0x53AB, target.to_bytes(4, "big"))
        + element(0x53AC, position.to_bytes(width, "big")),
    )


def seek_head(*entries: bytes) -> bytes:
    return element(_SEEK_HEAD, b"".join(entries))


def segment(payload: bytes) -> bytes:
    return header() + element(_SEGMENT, payload, unknown=True)


class Counter:
    """Counts the element headers that the reader parses and the bytes it reads."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.headers = 0
        self.bytes = 0
        parse = matroska._header
        read = matroska._Reader.read

        def counting_header(data: bytes, pos: int) -> tuple[int, int | None, int]:
            self.headers += 1
            return parse(data, pos)

        def counting_read(reader: matroska._Reader, pos: int, count: int) -> bytes:
            data = read(reader, pos, count)
            self.bytes += len(data)
            return data

        monkeypatch.setattr(matroska, "_header", counting_header)
        monkeypatch.setattr(matroska._Reader, "read", counting_read)


def test_a_seek_position_past_2_63_is_skipped_and_the_next_entry_used(tmp_path: Path) -> None:
    track_data = tracks(track(1, 2, language="por", ietf="pt-BR"))
    head = seek_head(seek(_TRACKS, 2**64 - 1), seek(_TRACKS, 0))
    real = len(head) + len(cluster())  # positions are fixed-width: the length stays
    head = seek_head(seek(_TRACKS, 2**64 - 1), seek(_TRACKS, real))
    found = read_matroska(write(tmp_path, segment(head + cluster() + track_data)))
    assert [t.language_ietf for t in found.tracks] == ["pt-BR"]


@pytest.mark.parametrize("position", [2**63, 2**64 - 1, 10_000])
def test_a_seek_head_with_only_unusable_positions_is_a_matroska_error(
    tmp_path: Path, position: int
) -> None:
    """The prober and the runner catch only ``MatroskaError`` and ``OSError``. 10 000 is past
    the end of this small file."""
    data = segment(seek_head(seek(_TRACKS, position)) + cluster())
    with pytest.raises(MatroskaError, match="no Tracks"):
        read_matroska(write(tmp_path, data))


def test_a_seek_position_must_name_its_element(tmp_path: Path) -> None:
    """The entry says Tracks, but the element there is an Info: no tracks are made up."""
    head = seek_head(seek(_TRACKS, 0))
    data = segment(seek_head(seek(_TRACKS, len(head) + len(cluster()))) + cluster() + info("x"))
    with pytest.raises(MatroskaError, match="no Tracks"):
        read_matroska(write(tmp_path, data))


@pytest.mark.parametrize("error", [ValueError("bad"), OverflowError("too big")])
def test_value_and_overflow_errors_of_the_reader_are_matroska_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    def broken(*args: object) -> str | None:
        raise error

    monkeypatch.setattr(matroska, "_title", broken)
    data = segment(info("T") + tracks(track(1, 1)))
    with pytest.raises(MatroskaError, match="damaged header"):
        read_matroska(write(tmp_path, data))


def filler(count: int, first_id: int) -> bytes:
    """``count`` Seek entries of other elements (distinct IDs)."""
    return b"".join(seek(first_id + i, 1, width=1) for i in range(count))


def test_many_seek_heads_full_of_entries_are_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Four SeekHeads of 20 000 entries each, then Tracks: only the first SeekHead is read,
    and only its first MAX_CHILDREN entries are looked at."""
    heads = [seek_head(filler(20_000, 0x10000000 + n * 20_000)) for n in range(4)]
    data = segment(b"".join(heads) + tracks(track(1, 2, ietf="de")))
    path = write(tmp_path, data)
    count = Counter(monkeypatch)
    found = read_matroska(path)
    assert [t.language_ietf for t in found.tracks] == ["de"]
    assert count.headers < 13_000  # 4096 entries x 3 headers, the top level and the track
    assert count.bytes < len(heads[0]) + 1024


def test_one_linked_seek_head_is_followed_and_no_more(tmp_path: Path) -> None:
    """The first SeekHead links to a second one after the clusters, which has the Tracks
    entry: it is read. A third SeekHead behind the second is not."""
    track_data = tracks(track(1, 2, ietf="hu"))
    probe = seek_head(seek(_SEEK_HEAD, 0))  # every entry is fixed-width: lengths are known
    second_at = len(probe) + len(cluster())
    second = seek_head(seek(_TRACKS, second_at + len(probe)))
    data = segment(seek_head(seek(_SEEK_HEAD, second_at)) + cluster() + second + track_data)
    assert [t.language_ietf for t in read_matroska(write(tmp_path, data)).tracks] == ["hu"]

    third_at = second_at + len(probe)
    second = seek_head(seek(_SEEK_HEAD, third_at))
    third = seek_head(seek(_TRACKS, third_at + len(probe)))
    data = segment(seek_head(seek(_SEEK_HEAD, second_at)) + cluster() + second + third + track_data)
    with pytest.raises(MatroskaError, match="no Tracks"):
        read_matroska(write(tmp_path, data, "chain.mkv"))


def test_linked_seek_heads_full_of_entries_are_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A chain of big SeekHeads after the first Cluster: two are read, then the reader stops."""
    big = [filler(20_000, 0x10000000 + n * 20_000) for n in range(4)]
    size = len(seek_head(seek(_SEEK_HEAD, 0) + big[0]))  # each links to the next one first
    first = seek_head(seek(_SEEK_HEAD, size + len(cluster())) + big[0])
    chain = [
        seek_head(seek(_SEEK_HEAD, size + len(cluster()) + n * size) + big[n]) for n in (1, 2, 3)
    ]
    path = write(tmp_path, segment(first + cluster() + b"".join(chain)))
    count = Counter(monkeypatch)
    with pytest.raises(MatroskaError, match="no Tracks"):
        read_matroska(path)
    assert count.headers < 26_000
    assert count.bytes < 2 * size + 1024


def test_a_tracks_element_with_too_many_children_is_a_matroska_error(tmp_path: Path) -> None:
    data = segment(element(_TRACKS, b"\xae\x80" * 70_000))
    with pytest.raises(MatroskaError, match="Tracks has more than 4096 elements"):
        read_matroska(write(tmp_path, data))


def test_all_element_headers_are_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Many small children in many entries: the total is bounded, not only each element."""
    entry = element(0xAE, b"\xec\x80" * 100)
    data = segment(element(_TRACKS, entry * 50))
    path = write(tmp_path, data)
    assert len(read_matroska(path).tracks) == 50
    monkeypatch.setattr(matroska, "MAX_ELEMENTS", 1000)
    with pytest.raises(MatroskaError, match="more than 1000 elements"):
        read_matroska(path)


def test_all_bytes_read_are_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = segment(info("T" * 3000) + tracks(track(1, 1)))
    path = write(tmp_path, data)
    assert read_matroska(path).title == "T" * 3000
    monkeypatch.setattr(matroska, "MAX_READ", 2000)
    with pytest.raises(MatroskaError, match="more than 2000 bytes"):
        read_matroska(path)


def test_a_seek_head_over_its_limit_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = segment(seek_head(filler(50, 0x10000000)) + tracks(track(1, 1)))
    path = write(tmp_path, data)
    monkeypatch.setattr(matroska, "MAX_SEEK_HEAD", 64)
    count = Counter(monkeypatch)
    assert len(read_matroska(path).tracks) == 1
    assert count.headers < 20  # its entries were not parsed


def _all_ietf(source: MediaSource) -> list[str | None]:
    return [s.language_ietf for s in [*source.video, *source.audio, *source.subtitles]]


def _file(*ietf: str | None) -> matroska.MatroskaFile:
    kinds = ["video", "audio", "audio", "audio", "subtitle", "subtitle", "subtitle"]
    return matroska.MatroskaFile(
        doc_type="matroska",
        tracks=[
            matroska.MatroskaTrack(kind=kind, language_ietf=value)  # type: ignore[arg-type]
            for kind, value in zip(kinds, ietf, strict=True)
        ],
    )


def test_matched_tracks_get_the_files_value_or_none() -> None:
    """Tags derived from ``jpn`` / ``eng`` are not the file's; the file has only a2 = pt-BR:
    the other streams have no BCP 47 tag."""
    source = parse_probe("fixtures/multitrack.mkv")
    for stream, value in zip(
        [*source.video, *source.audio, *source.subtitles],
        [None, "ja", "en", "en", "en", "en", "en"],
        strict=True,
    ):
        stream.language_ietf = value
    assert apply_matroska(source, _file(None, None, "pt-BR", None, None, None, None))
    assert _all_ietf(source) == [None, None, "pt-BR", None, None, None, None]
    assert source.warnings == []


def test_tracks_that_do_not_match_change_nothing() -> None:
    source = parse_probe("fixtures/multitrack.mkv")
    source.audio[0].language_ietf = "ja"
    data = _file(None, None, None, None, None, None, None)
    data.tracks.pop()  # 2 subtitle tracks, ffprobe shows 3
    assert not apply_matroska(source, data)
    assert source.audio[0].language_ietf == "ja"


def test_a_value_that_is_not_a_language_tag_is_not_used() -> None:
    source = parse_probe("fixtures/multitrack.mkv")
    long = "abcdefgh" + "-abcdefgh" * 7  # the shape of a tag, but 71 characters
    assert apply_matroska(source, _file("", "j\na;x", "en_US", long, "de", None, "pt-BR"))
    assert _all_ietf(source) == [None, None, None, None, "de", None, "pt-BR"]
    assert source.warnings == [
        "Stream 1: the BCP 47 language (LanguageIETF) 'j\\na;x' is not a language tag; not used.",
        "Stream 2: the BCP 47 language (LanguageIETF) 'en_US' is not a language tag; not used.",
        "Stream 3: the BCP 47 language (LanguageIETF) "
        "'abcdefgh-abcdefgh-abcdefgh-abcdefgh-abcd…' is not a language tag; not used.",
    ]
    MediaSource.model_validate(source.model_dump(mode="json"))  # the cache round trip
    job = remux_job(JobSettings(source=SourceRef(path=source.ref.path)), source)
    JobSettings.model_validate(job.model_dump(mode="json"))


def test_the_cache_options_name_the_new_reader() -> None:
    """Entries made with MediaInfo's rates and tags, before the sampled rates, or with the
    attachments in the video's estimate are misses."""
    assert Prober("ffprobe").cache_options()["matroska"] == 4


def _copy(fixture_media: Callable[[str], Path], tmp_path: Path, name: str) -> Path:
    copy = tmp_path / name
    shutil.copyfile(fixture_media("multitrack"), copy)
    return copy


@pytest.mark.needs_ffmpeg
@pytest.mark.anyio
async def test_probe_of_a_file_with_a_seek_position_past_2_63(
    fixture_media: Callable[[str], Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The file has ``Tracks`` after the clusters (long names make mkvpropedit move it), then
    a bogus Seek entry in front. ffprobe lists all seven streams; the probe returns them with
    the BCP 47 tag that the reader found through the real entry."""
    mkvpropedit, ffprobe = _tool("mkvpropedit"), _tool("ffprobe")
    copy = _copy(fixture_media, tmp_path, "hostile.mkv")
    long = "N" * 6000
    names = [arg for n in (1, 2, 3) for arg in ("--edit", f"track:a{n}", "--set", f"name={long}")]
    propedit(mkvpropedit, copy, *names, "--edit", "track:a2", "--set", "language-ietf=pt-BR")
    with_bogus_seek_entry(copy)
    assert _ffprobe_streams(ffprobe, copy) == 7  # FFmpeg skips the entry
    source = await Prober(ffprobe).probe(copy, use_cache=False)
    assert isinstance(source, MediaSource), source
    assert [a.language_ietf for a in source.audio] == [None, "pt-BR", None]
    assert read_matroska(copy).tracks[2].name == long


def _ffprobe_streams(ffprobe: str, path: Path) -> int:
    out = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return len(json.loads(out.stdout)["streams"])


def _with_mp4_language(source: Path, out: Path, language: str) -> Path:
    from reframe_testing import media

    ffmpeg = media.find_ffmpeg()
    assert ffmpeg is not None
    subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(source), "-c", "copy",
         "-metadata:s:v:0", f"language={language}", str(out)],
        check=True,
    )  # fmt: skip
    return out


@pytest.mark.needs_ffmpeg
@pytest.mark.anyio
async def test_bcp47_comes_from_the_track_in_matroska_and_from_the_iso_code_elsewhere(
    fixture_media: Callable[[str], Path], tmp_path: Path
) -> None:
    """A Matroska track without ``LanguageIETF`` gets no tag derived from its legacy language;
    an MP4 stream's ISO 639-2 code becomes its BCP 47 tag."""
    mkvpropedit, ffprobe = _tool("mkvpropedit"), _tool("ffprobe")
    copy = _copy(fixture_media, tmp_path, "m.mkv")
    propedit(mkvpropedit, copy, "--edit", "track:a2", "--set", "language=por",
             "--set", "language-ietf=pt-BR")  # fmt: skip
    source = await Prober(ffprobe).probe(copy, use_cache=False)
    assert isinstance(source, MediaSource), source
    assert _all_ietf(source) == [None, None, "pt-BR", None, None, None, None]
    assert [s.language for s in source.audio] == ["jpn", "por", "eng"]
    mp4 = _with_mp4_language(fixture_media("vfr"), tmp_path / "hun.mp4", "hun")
    other = await Prober(ffprobe).probe(mp4, use_cache=False)
    assert isinstance(other, MediaSource), other
    assert (other.video[0].language, other.video[0].language_ietf) == ("hun", "hu")
    undetermined = await Prober(ffprobe).probe(fixture_media("vfr"), use_cache=False)
    assert isinstance(undetermined, MediaSource), undetermined
    assert (undetermined.video[0].language, undetermined.video[0].language_ietf) == ("und", None)


@pytest.mark.needs_ffmpeg
@pytest.mark.anyio
@pytest.mark.parametrize("bad", [b"en_US", b"j\na;x"])
async def test_probe_of_an_invalid_language_ietf(
    fixture_media: Callable[[str], Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bad: bytes,
) -> None:
    """ffprobe reads the file (legacy ``jpn``); ``mkvmerge -J`` shows no ``language_ietf``
    for that track. The probe drops the value with a warning, and a remux job of the file
    is a valid ``JobSettings``."""
    mkvpropedit, ffprobe = _tool("mkvpropedit"), _tool("ffprobe")
    copy = _copy(fixture_media, tmp_path, "badtag.mkv")
    with_bad_tag(copy, mkvpropedit, bad)
    assert read_matroska(copy).tracks[1].language_ietf == bad.decode()
    if shutil.which("mkvmerge"):
        first_audio = mkvmerge_tracks(copy)[1]
        assert (first_audio.get("language"), first_audio.get("language_ietf")) == ("jpn", None)
    source = await Prober(ffprobe).probe(copy, use_cache=False)
    assert isinstance(source, MediaSource), source
    assert [(a.language, a.language_ietf) for a in source.audio] == [
        ("jpn", None), ("eng", None), ("eng", None),
    ]  # fmt: skip
    warning = (
        f"Stream 1: the BCP 47 language (LanguageIETF) {bad.decode()!r} is not a language tag; "
        "not used."
    )
    assert warning in source.warnings
    job = remux_job(JobSettings(source=SourceRef(path=copy)), source)
    assert job.audio[0].metadata.language == "ja"  # the legacy jpn, as a BCP 47 tag
    JobSettings.model_validate(job.model_dump(mode="json"))
