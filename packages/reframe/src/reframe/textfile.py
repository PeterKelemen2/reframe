"""Small text files read by name: their character encoding, and an open that takes only a
regular file, so that a FIFO or a device named like a text file never blocks the reader."""

from __future__ import annotations

import codecs
import errno
import os
import stat
from dataclasses import dataclass
from typing import BinaryIO

__all__ = [
    "ENCODING_SAMPLE",
    "NotARegularFileError",
    "TextCharset",
    "charset_of",
    "detect_charset",
    "open_regular",
    "read_charset",
]

#: Bytes read to tell the character encoding; a subtitle file is rarely larger.
ENCODING_SAMPLE = 16 * 2**20
# UTF-32LE's mark starts with UTF-16LE's, so it is tested first.
_BOMS = (
    (codecs.BOM_UTF32_LE, "UTF-32LE"),
    (codecs.BOM_UTF32_BE, "UTF-32BE"),
    (codecs.BOM_UTF8, "UTF-8"),
    (codecs.BOM_UTF16_LE, "UTF-16LE"),
    (codecs.BOM_UTF16_BE, "UTF-16BE"),
)


@dataclass(frozen=True, slots=True)
class TextCharset:
    """The character encoding of a text file."""

    name: str | None
    """``UTF-8``, ``UTF-16LE`` / ``UTF-16BE`` or ``UTF-32LE`` / ``UTF-32BE`` from a byte order
    mark, else ``UTF-8`` when the text is valid UTF-8; ``None``: not detected."""
    ascii: bool
    """UTF-8 text with only ASCII characters, which every ASCII-based encoding reads the same."""


def charset_of(data: bytes, *, complete: bool = True) -> TextCharset:
    """The encoding of ``data``. ``complete`` ``False``: ``data`` is the start of a longer file,
    so a character cut at its end does not count."""
    for bom, name in _BOMS:
        if data.startswith(bom):
            return TextCharset(name, name == "UTF-8" and data[len(bom) :].isascii())
    if data.isascii():
        return TextCharset("UTF-8", True)
    try:
        codecs.getincrementaldecoder("utf-8")().decode(data, final=complete)
    except UnicodeDecodeError:
        return TextCharset(None, False)
    return TextCharset("UTF-8", False)


def detect_charset(data: bytes, *, complete: bool = True) -> str | None:
    """:attr:`TextCharset.name` of :func:`charset_of`."""
    return charset_of(data, complete=complete).name


class NotARegularFileError(OSError):
    """The path is a FIFO, a socket or a device: reading it could wait for ever."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        super().__init__(errno.EINVAL, "Not a regular file", os.fspath(path))


def _check_kind(mode: int, path: str | os.PathLike[str]) -> None:
    if stat.S_ISDIR(mode):
        raise IsADirectoryError(errno.EISDIR, "Is a directory", os.fspath(path))
    if not stat.S_ISREG(mode):
        raise NotARegularFileError(path)


def open_regular(path: str | os.PathLike[str]) -> BinaryIO:
    """``path`` opened for reading in binary mode when it is a regular file (links followed).
    Raises :class:`IsADirectoryError` for a folder, :class:`NotARegularFileError` for any other
    kind of file, at once, and :class:`OSError` as :func:`open` does."""
    _check_kind(os.stat(path).st_mode, path)
    # O_NONBLOCK: a file replaced by a FIFO after the stat must not wait for a writer.
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    try:
        _check_kind(os.fstat(fd).st_mode, path)
        return os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise


def read_charset(path: str | os.PathLike[str]) -> TextCharset:
    """:func:`charset_of` the first :data:`ENCODING_SAMPLE` bytes of ``path`` (through
    :func:`open_regular`, whose errors it raises). Blocks: call it in a worker thread."""
    with open_regular(path) as file:
        data = file.read(ENCODING_SAMPLE + 1)
    return charset_of(data[:ENCODING_SAMPLE], complete=len(data) <= ENCODING_SAMPLE)
