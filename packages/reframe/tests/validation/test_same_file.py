"""Validation, the queue and ``reframe.jobs`` agree on when two paths are the same file."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from reframe.jobs import file_key
from reframe.queue import files
from reframe.validation import LocalFileSystem

_real_stat = os.stat


def _no_file_index(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
    found = _real_stat(path, *args, **kwargs)
    return os.stat_result((found.st_mode, 0, 0, *tuple(found)[3:]))


@pytest.fixture
def tree(tmp_path: Path) -> dict[str, Path]:
    real = tmp_path / "real"
    real.mkdir()
    movie = real / "Movie.mkv"
    movie.write_bytes(b"movie")
    other = real / "Other.mkv"
    other.write_bytes(b"other")
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    hard = tmp_path / "hard.mkv"
    os.link(movie, hard)
    return {
        "movie": movie,
        "other": other,
        "through_link": linked / "Movie.mkv",
        "hard_link": hard,
        "dotdot": real / ".." / "real" / "Movie.mkv",
        "new_output": linked / "New.mkv",
        "new_output_real": real / "New.mkv",
    }


def test_local_same_file(tree: dict[str, Path]) -> None:
    fs = LocalFileSystem()
    movie = tree["movie"]
    assert fs.same_file(movie, tree["through_link"])
    assert fs.same_file(movie, tree["hard_link"])
    assert fs.same_file(movie, tree["dotdot"])
    assert not fs.same_file(movie, tree["other"])
    assert not fs.same_file(tree["new_output"], tree["new_output_real"])  # neither exists


def test_without_file_indexes_two_files_are_not_the_same(
    tree: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "stat", _no_file_index)
    fs = LocalFileSystem()
    assert not fs.same_file(tree["movie"], tree["other"])
    assert fs.same_file(tree["movie"], tree["through_link"])  # the resolved paths are equal
    assert not files.same_file(tree["movie"], tree["other"])


@pytest.mark.parametrize(
    ("a", "b", "same"),
    [
        ("movie", "through_link", True),
        ("movie", "hard_link", True),
        ("movie", "dotdot", True),
        ("movie", "other", False),
        ("new_output", "new_output_real", True),
        ("new_output", "movie", False),
    ],
)
def test_jobs_file_key_agrees_with_the_queue(
    tree: dict[str, Path], a: str, b: str, same: bool
) -> None:
    first, second = tree[a], tree[b]
    assert (file_key(first) == file_key(second)) is same
    assert files.same_key(files.file_key(first), files.file_key(second)) is same
