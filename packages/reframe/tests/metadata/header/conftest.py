from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from reframe.metadata.header import apply_header_edit

from . import corpus


@pytest.fixture(scope="session")
def header_corpus(
    fixture_media: Callable[[str], Path], tmp_path_factory: pytest.TempPathFactory
) -> dict[str, Path]:
    """The fixture corpus (read only: copy a file before editing it)."""
    folder = tmp_path_factory.mktemp("header-corpus")
    multitrack = fixture_media("multitrack")
    moved = corpus.copy(multitrack, folder, "mkvpropedit-moved.mkv")
    result = corpus.mkvpropedit(corpus.multitrack_edit(moved, long=True, title=None), moved)
    assert result.returncode == 0, result.stdout
    linked = corpus.copy(multitrack, folder, "mkvpropedit-linked.mkv")
    result = corpus.mkvpropedit(corpus.multitrack_edit(linked, long=True), linked)
    assert result.returncode == 0, result.stdout
    # mkvpropedit moved the SeekHead's entries to a second SeekHead behind the clusters.
    assert [t.id for t in corpus.segment(linked.read_bytes()).top].count(corpus.SEEK_HEAD) == 2
    ours = corpus.copy(multitrack, folder, "reframe-moved.mkv")
    assert apply_header_edit(corpus.generic_edit(ours, long=True)).ok
    with_crc = corpus.mkvmerge_crc(multitrack, folder)
    data = with_crc.read_bytes()
    top = corpus.segment(data).top
    assert all(data[t.data] == corpus.CRC for t in top[:4] if t.id != corpus.VOID)
    assert corpus.crc_problems(with_crc) == []
    return {
        "ffmpeg-multitrack": multitrack,
        "ffmpeg-text-subs": fixture_media("text-subs"),
        "ffmpeg-chapters": fixture_media("chapters"),
        "mkvmerge-reordered": corpus.mkvmerge_reordered(multitrack, folder),
        "mkvmerge-crc": with_crc,
        "mkvpropedit-moved": moved,
        "mkvpropedit-linked": linked,
        "reframe-moved": ours,
    }
