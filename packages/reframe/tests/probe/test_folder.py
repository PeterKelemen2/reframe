"""Listing a folder: media files only, in natural order."""

from __future__ import annotations

from pathlib import Path

from reframe.probe import list_media_files, natural_key


def touch(folder: Path, *names: str) -> None:
    for name in names:
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")


def test_natural_key() -> None:
    names = ["Show.S01E10.mkv", "show.s01e2.mkv", "Show.S01E1.mkv", "Show.S01E02b.mkv", "a"]
    assert sorted(names, key=natural_key) == [
        "a",
        "Show.S01E1.mkv",
        "show.s01e2.mkv",
        "Show.S01E02b.mkv",
        "Show.S01E10.mkv",
    ]


def test_list_media_files(tmp_path: Path) -> None:
    touch(
        tmp_path,
        "E10.mkv",
        "E2.mkv",
        "e1.MP4",
        "E3.m2ts",
        ".hidden.mkv",
        "notes.txt",
        "E2.srt",
        "cover.jpg",
        "sub/E4.mkv",
    )
    (tmp_path / "folder.mkv").mkdir()
    assert [p.name for p in list_media_files(tmp_path)] == [
        "e1.MP4",
        "E2.mkv",
        "E3.m2ts",
        "E10.mkv",
    ]
    deep = list_media_files(tmp_path, recursive=True)
    assert [p.relative_to(tmp_path).as_posix() for p in deep] == [
        "e1.MP4",
        "E2.mkv",
        "E3.m2ts",
        "E10.mkv",
        "sub/E4.mkv",
    ]


def test_recursive_skips_hidden_folders(tmp_path: Path) -> None:
    touch(tmp_path, ".trash/E1.mkv", "Season 10/E1.mkv", "Season 2/E1.mkv")
    found = list_media_files(tmp_path, recursive=True)
    assert [p.parent.name for p in found] == ["Season 2", "Season 10"]
