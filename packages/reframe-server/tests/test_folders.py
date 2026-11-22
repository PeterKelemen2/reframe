"""The server folders in answers, as Windows and Linux spell them."""

from __future__ import annotations

import pytest

from reframe_server.folders import _mask

WINDOWS_DATA = r"C:\Users\Ann\AppData\Local\Reframe"
WINDOWS_CACHE = WINDOWS_DATA + r"\Cache"


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        (WINDOWS_CACHE + r"\frames\a.png", r"<cache>\frames\a.png"),
        (WINDOWS_DATA + r"\logs\job.log", r"<config>\logs\job.log"),
        ("C:/Users/Ann/AppData/Local/Reframe/Cache/frames/a.png", "<cache>/frames/a.png"),
        (r"c:\users\ann\appdata\local\reframe\cache\x.png", r"<cache>\x.png"),
        (
            r"subtitles='C\:/Users/Ann/AppData/Local/Reframe/Cache/s.ass'",
            "subtitles='<cache>/s.ass'",
        ),
        (WINDOWS_DATA + r"2\film.mkv", None),
        (r"D:\Archive" + WINDOWS_DATA[2:] + r"\film.mkv", None),
    ],
    ids=["cache", "data-is-config", "slashes", "case", "escaped-colon", "longer-name", "inside"],
)
def test_windows_folders_in_any_case_and_with_either_separator(
    text: str, shown: str | None
) -> None:
    """Config and data are one folder on Windows, and the cache is inside it."""
    mask = _mask(WINDOWS_DATA, WINDOWS_DATA, WINDOWS_CACHE, windows=True)
    assert mask.text(text) == (text if shown is None else shown)


def test_linux_folders_keep_their_case() -> None:
    mask = _mask(
        "/home/a/.config/reframe",
        "/home/a/.local/share/reframe",
        "/home/a/.cache/reframe",
        windows=False,
    )
    assert mask.text("/home/a/.cache/reframe/x.png") == "<cache>/x.png"
    assert mask.text("/home/a/.CACHE/reframe/x.png") == "/home/a/.CACHE/reframe/x.png"
