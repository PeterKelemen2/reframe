"""The encoding of an external subtitle file as validation reads it from the real file system."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from reframe.textfile import TextCharset, read_charset
from reframe.validation import LocalFileSystem
from reframe.validation import fs as validation_fs

TEXT = "1\n00:00:00,500 --> 00:00:01,500\nŐszi szél\n"


def test_the_encoding_of_a_file_follows_its_changes(tmp_path: Path) -> None:
    file = tmp_path / "Film.hu.srt"
    file.write_bytes(TEXT.encode())
    local = LocalFileSystem()
    assert local.text_charset(file) == TextCharset("UTF-8", ascii=False)
    file.write_bytes(TEXT.encode("cp1250"))  # one byte shorter: a new size
    assert local.text_charset(file) == TextCharset(None, ascii=False)
    file.write_bytes(b"\xef\xbb\xbf" + TEXT.encode("ascii", "replace"))
    assert local.text_charset(file) == TextCharset("UTF-8", ascii=True)


def test_a_file_saved_again_with_the_same_size_and_time_is_read_again(tmp_path: Path) -> None:
    file = tmp_path / "Film.hu.srt"
    file.write_bytes("ő".encode())  # two bytes in UTF-8 and in UTF-16
    local = LocalFileSystem()
    assert local.text_charset(file) == TextCharset("UTF-8", ascii=False)
    times = os.stat(file).st_atime_ns, os.stat(file).st_mtime_ns
    # A later save: NTFS takes a file's times from the clock tick (up to 15.6 ms).
    time.sleep(0.05)
    file.write_bytes(b"\xff\xfe")
    os.utime(file, ns=times)
    assert local.text_charset(file) == TextCharset("UTF-16LE", ascii=False)


def test_an_unchanged_file_is_read_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Validation runs on every edit, and a subtitle file can be megabytes."""
    file = tmp_path / "Film.hu.srt"
    file.write_bytes(TEXT.encode())
    reads: list[object] = []

    def counted(path: Path) -> TextCharset:
        reads.append(path)
        return read_charset(path)

    monkeypatch.setattr(validation_fs, "read_charset", counted)
    local = LocalFileSystem()
    assert local.text_charset(file) == local.text_charset(file) == TextCharset("UTF-8", False)
    assert reads == [file]


def test_what_is_not_a_readable_file_has_no_encoding(tmp_path: Path) -> None:
    local = LocalFileSystem()
    assert local.text_charset(tmp_path / "missing.srt") is None
    assert local.text_charset(tmp_path) is None
    assert local.text_charset(tmp_path / "bad\0name.srt") is None


def test_a_fifo_named_like_a_subtitle_file_does_not_block_validation(
    fifo_read: Callable[..., object],
) -> None:
    assert fifo_read("Film.srt", LocalFileSystem().text_charset) is None
