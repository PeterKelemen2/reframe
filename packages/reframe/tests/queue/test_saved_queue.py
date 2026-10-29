"""The saved queue read without its owner: nothing is written to the store, any data folder
can be named in the SQLite URI, and a read that cannot see the newest changes says so."""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from reframe.queue import read_saved_queue
from reframe.queue.client import _store_uri
from reframe.queue.store import STORE_FILE

from .conftest import Harness

pytestmark = pytest.mark.anyio

posix_modes = pytest.mark.skipif(
    sys.platform == "win32" or os.geteuid() == 0, reason="POSIX folder modes, not as root"
)


def copy_store(data_dir: Path, folder: Path, *sides: str) -> None:
    folder.mkdir()
    for side in ("", *sides):
        shutil.copyfile(data_dir / f"{STORE_FILE}{side}", folder / f"{STORE_FILE}{side}")


def checkpoint(data_dir: Path) -> None:
    other = sqlite3.connect(data_dir / STORE_FILE)
    other.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    other.close()


def store_bytes(folder: Path) -> dict[str, bytes | None]:
    """The database file and its ``-wal`` file (``None``: gone)."""
    files = {side: folder / f"{STORE_FILE}{side}" for side in ("", "-wal")}
    return {side: path.read_bytes() if path.exists() else None for side, path in files.items()}


async def stopped_owner(h: Harness, folder: Path, *, checkpointed: int, newer: int) -> list[str]:
    """``folder`` holds the store of an owner that stopped without closing it: ``checkpointed``
    jobs are in the database file, ``newer`` ones only in its ``-wal`` file. The ids, in order."""
    ids = [(await h.queue.add(h.job(f"Saved {n}"))).id for n in range(checkpointed)]
    checkpoint(h.tmp / "data")
    ids += [(await h.queue.add(h.job(f"Newer {n}"))).id for n in range(newer)]
    copy_store(h.tmp / "data", folder, "-wal", "-shm")
    return ids


async def test_reading_the_saved_queue_writes_nothing_to_the_store(
    harness: Harness, tmp_path: Path
) -> None:
    """A read-write connection would put the stopped owner's ``-wal`` into the database file
    when it closes."""
    folder = tmp_path / "stopped"
    ids = await stopped_owner(harness, folder, checkpointed=1, newer=1)
    before = store_bytes(folder)
    saved = read_saved_queue(folder)
    assert [job.id for job in saved.jobs] == ids
    assert saved.problem is None
    assert store_bytes(folder) == before


@posix_modes
async def test_a_store_read_as_immutable_says_newer_changes_may_be_missing(
    harness: Harness, tmp_path: Path
) -> None:
    """Without a ``-shm`` file in a folder the user cannot write, only the immutable read works,
    and it does not see the commits in the ``-wal`` file."""
    folder = tmp_path / "stopped"
    first, _newer = await stopped_owner(harness, folder, checkpointed=1, newer=1)
    (folder / f"{STORE_FILE}-shm").unlink()
    folder.chmod(0o555)
    try:
        saved = read_saved_queue(folder)
    finally:
        folder.chmod(0o755)
    assert [job.id for job in saved.jobs] == [first]
    assert saved.problem is not None
    assert "newer changes in queue.sqlite3-wal may be missing" in saved.problem


@posix_modes
async def test_a_store_without_a_wal_read_as_immutable_has_no_problem(
    harness: Harness, tmp_path: Path
) -> None:
    h = harness
    job = await h.queue.add(h.job())
    await h.queue.close()  # the owner's close folds the -wal into the file and removes it
    folder = h.tmp / "data"
    assert not (folder / f"{STORE_FILE}-wal").exists()
    folder.chmod(0o555)
    try:
        saved = read_saved_queue(folder)
    finally:
        folder.chmod(0o755)
    assert [j.id for j in saved.jobs] == [job.id]
    assert saved.problem is None


@pytest.mark.skipif(sys.platform == "win32", reason="a file name that is not UTF-8")
async def test_a_data_folder_with_uri_characters_and_bytes_that_are_not_utf8(
    harness: Harness, tmp_path: Path
) -> None:
    h = harness
    job = await h.queue.add(h.job())
    await h.queue.close()
    folder = Path(os.fsdecode(bytes(tmp_path) + b"/a?b#c%41-\xff"))
    copy_store(h.tmp / "data", folder)
    saved = read_saved_queue(folder)
    assert [j.id for j in saved.jobs] == [job.id]
    assert saved.problem is None


def test_a_unc_data_folder_has_a_uri_that_sqlite_accepts(tmp_path: Path) -> None:
    """SQLite refuses ``file://nas/share/…`` ("invalid uri authority: nas"). With an empty
    authority it gives the VFS the URI's whole path, ``//nas/share/…``: the UNC path."""
    uri = _store_uri(PureWindowsPath(r"\\nas\share\data\queue.sqlite3"))
    assert uri == "file:////nas/share/data/queue.sqlite3"
    assert _store_uri(PureWindowsPath(r"C:\data\queue.sqlite3")) == "file:///C:/data/queue.sqlite3"
    if sys.platform != "win32":  # no network look-up of "nas"; here //tmp/x is /tmp/x
        with pytest.raises(sqlite3.OperationalError) as refused:
            sqlite3.connect(f"{uri}?mode=ro", uri=True)
        assert str(refused.value) == "unable to open database file"
        db = sqlite3.connect(tmp_path / "x.sqlite3")
        db.execute("CREATE TABLE t (x)")
        db.close()
        double = _store_uri(PurePosixPath("/" + (tmp_path / "x.sqlite3").as_posix()))
        assert double.startswith("file:////")
        db = sqlite3.connect(f"{double}?mode=ro", uri=True)
        assert db.execute("SELECT count(*) FROM t").fetchone() == (0,)
        db.close()
