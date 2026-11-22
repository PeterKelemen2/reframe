"""The character encoding of an external subtitle file (the real ffprobe runs in
``reframe-server/tests/test_subtitles.py``)."""

from __future__ import annotations

import pytest

from reframe.textfile import charset_of

TEXT = "Őszi szél"


@pytest.mark.parametrize(
    ("data", "charset"),
    [
        (TEXT.encode(), "UTF-8"),
        (b"plain ASCII", "UTF-8"),
        (b"\xef\xbb\xbf" + TEXT.encode(), "UTF-8"),
        (b"\xff\xfe" + TEXT.encode("utf-16-le"), "UTF-16LE"),
        (b"\xfe\xff" + TEXT.encode("utf-16-be"), "UTF-16BE"),
        (b"\xff\xfe\x00\x00" + TEXT.encode("utf-32-le"), "UTF-32LE"),
        (b"\x00\x00\xfe\xff" + TEXT.encode("utf-32-be"), "UTF-32BE"),
        (TEXT.encode("cp1250"), None),
    ],
)
def test_the_encoding_comes_from_a_byte_order_mark_or_valid_utf8(
    data: bytes, charset: str | None
) -> None:
    assert charset_of(data).name == charset


def test_a_character_cut_at_the_end_of_a_sample_is_still_utf8() -> None:
    cut = TEXT.encode()[:1]  # the first byte of "Ő"
    assert charset_of(cut, complete=False).name == "UTF-8"
    assert charset_of(cut, complete=True).name is None


@pytest.mark.parametrize(
    ("data", "ascii"),
    [
        (b"plain", True),
        (b"\xef\xbb\xbfplain", True),
        (TEXT.encode(), False),
        (b"\xff\xfeplain", False),
    ],
)
def test_ascii_text_is_marked_as_read_alike_by_every_ascii_encoding(
    data: bytes, ascii: bool
) -> None:
    assert charset_of(data).ascii is ascii
