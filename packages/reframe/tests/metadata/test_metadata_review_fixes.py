"""Metadata edits of unusual files through the facade, the real queue and the real tools:
MediaInfo's BCP 47 tags, an invalid ``LanguageIETF``, and a SeekHead position past 2^63."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from reframe.models import JobDraft, JobState
from reframe.probe import mediainfo

from .test_metadata_edit_real import Env, draft_remux, env, mkvmerge, reprobe, run

pytestmark = [pytest.mark.needs_ffmpeg, pytest.mark.anyio]
__all__ = ["env"]


def _element(element_id: int, payload: bytes) -> bytes:
    raw_id = element_id.to_bytes((element_id.bit_length() + 7) // 8, "big")
    return raw_id + bytes([0x01]) + len(payload).to_bytes(7, "big") + payload


def _header(data: bytes, pos: int) -> tuple[int, int, int]:
    """``(id, size, header length)`` of the element at ``pos`` (known sizes only)."""
    first = data[pos]
    id_len = 8 - first.bit_length() + 1
    element_id = int.from_bytes(data[pos : pos + id_len], "big")
    size_first = data[pos + id_len]
    size_len = 8 - size_first.bit_length() + 1
    raw = int.from_bytes(data[pos + id_len : pos + id_len + size_len], "big")
    size = raw & ((1 << (7 * size_len)) - 1)
    return element_id, size, id_len + size_len


def with_bogus_seek_entry(path: Path) -> None:
    """A Seek entry ``Tracks → 2^64 - 1`` in front of the SeekHead's entries, in the Void
    after it."""
    data = bytearray(path.read_bytes())
    _, ebml_size, ebml_header = _header(bytes(data), 0)
    seg = ebml_header + ebml_size
    seg_id, _, seg_header = _header(bytes(data), seg)
    assert seg_id == 0x18538067
    start = seg + seg_header
    head_id, head_size, head_header = _header(bytes(data), start)
    assert head_id == 0x114D9B74
    payload = bytes(data[start + head_header : start + head_header + head_size])
    void_id, void_size, void_header = _header(bytes(data), start + head_header + head_size)
    assert void_id == 0xEC
    room = head_header + head_size + void_header + void_size
    bogus = _element(
        0x4DBB, _element(0x53AB, bytes.fromhex("1654AE6B")) + _element(0x53AC, b"\xff" * 8)
    )
    new_head = _element(0x114D9B74, bogus + payload)
    new_void = _element(0xEC, b"\0" * (room - len(new_head) - 9))
    assert len(new_head) + len(new_void) == room
    data[start : start + room] = new_head + new_void
    path.write_bytes(bytes(data))


def with_bad_tag(path: Path, bad: bytes) -> None:
    """``LanguageIETF`` of a1 = ``bad`` (5 bytes): mkvpropedit writes ``en-US``, then the bytes
    are replaced (mkvpropedit does not write an invalid tag)."""
    tool = shutil.which("mkvpropedit")
    assert tool is not None
    subprocess.run(
        [tool, str(path), "--edit", "track:a1", "--set", "language-ietf=en-US"],
        check=True, capture_output=True,
    )  # fmt: skip
    data = bytearray(path.read_bytes())
    needle = bytes.fromhex("22B59D85") + b"en-US"
    assert data.count(needle) == 1
    at = data.index(needle) + 4
    data[at : at + 5] = bad
    path.write_bytes(bytes(data))


async def test_demo_3_with_mediainfo_on_shows_only_the_files_bcp47_tags(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Untouched tracks have no ``LanguageIETF``: MediaInfo would derive ``en`` from ``eng``."""
    if mediainfo._library() is None:
        pytest.skip("MediaInfo (pymediainfo) is not available")
    monkeypatch.setattr(mediainfo, "mediainfo_available", lambda: True)  # env switched it off
    app = await env.app()
    try:
        job = await draft_remux(app, env.source)
        hungarian, brazilian, commentary = job.audio
        hungarian.metadata.language = "hu"
        brazilian.metadata.language = "pt-BR"
        commentary.metadata.commentary = True
        job.subtitles[0].metadata.language = "hu"
        ended = await run(app, job)
        assert ended.state is JobState.DONE, ended.error
        out = await reprobe(app, env.source)
        assert [(s.language, s.language_ietf) for s in [*out.audio, *out.subtitles]] == [
            ("hun", "hu"), ("por", "pt-BR"), ("eng", None),
            ("hun", "hu"), ("eng", None), ("eng", None),
        ]  # fmt: skip
        tracks = mkvmerge(env.source)
        if tracks:  # MKVToolNix agrees
            assert [t.get("language_ietf") for t in tracks[1:]] == [
                "hu", "pt-BR", None, "hu", None, None,
            ]  # fmt: skip
    finally:
        await app.close()


@pytest.mark.parametrize("bad", [b"en_US", b"j\na;x"])
async def test_a_file_with_an_invalid_language_ietf_can_be_drafted_and_planned(
    env: Env, bad: bytes
) -> None:
    with_bad_tag(env.source, bad)
    app = await env.app()
    try:
        draft = await app.jobs.draft(env.source)
        assert isinstance(draft, JobDraft), draft
        assert draft.job.audio[0].metadata.language in (None, "ja")
        job = await draft_remux(app, env.source)
        assert job.audio[0].metadata.language == "ja"  # the legacy jpn
        plan = await app.jobs.plan(job)
        assert not isinstance(plan, list), plan
        source = await reprobe(app, env.source)
        assert any("is not a language tag" in w for w in source.warnings)
    finally:
        await app.close()


def with_long_names(path: Path, name: str) -> None:
    tool = shutil.which("mkvpropedit")
    assert tool is not None
    names = [arg for n in (1, 2, 3) for arg in ("--edit", f"track:a{n}", "--set", f"name={name}")]
    subprocess.run([tool, str(path), *names], check=True, capture_output=True)


async def test_an_in_place_edit_of_a_file_with_a_seek_position_past_2_63_ends_as_data(
    env: Env,
) -> None:
    long = "N" * 6000
    with_long_names(env.source, long)
    with_bogus_seek_entry(env.source)
    before = env.source.read_bytes()
    app = await env.app()
    try:
        source = await reprobe(app, env.source)
        assert [a.title for a in source.audio] == [long, long, long]
        job = await draft_remux(app, env.source)
        job.audio[0].metadata.name = "Short"
        ended = await run(app, job)
        assert ended.state is JobState.FAILED
        assert ended.error is not None
        assert ended.error.startswith("mkvpropedit failed (exit code 2)"), ended.error
        assert env.source.read_bytes() == before
    finally:
        await app.close()
