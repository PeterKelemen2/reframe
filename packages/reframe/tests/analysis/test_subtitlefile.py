"""The character encoding of an external subtitle file (the real ffprobe runs in
``reframe-server/tests/test_subtitles.py``)."""

from __future__ import annotations

import pytest

from reframe.analysis.subtitlefile import detect_charset

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
    assert detect_charset(data) == charset


def test_a_character_cut_at_the_end_of_a_sample_is_still_utf8() -> None:
    cut = TEXT.encode()[:1]  # the first byte of "Ő"
    assert detect_charset(cut, complete=False) == "UTF-8"
    assert detect_charset(cut, complete=True) is None
