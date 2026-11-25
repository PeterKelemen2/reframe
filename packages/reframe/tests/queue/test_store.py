"""The SQLite queue store: its schema, round trips and damaged, newer or unwritable files."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from reframe.models import (
    EncodePlan,
    JobSettings,
    JobState,
    QueueJob,
    Severity,
    SourceRef,
    ValidationIssue,
)
from reframe.queue.store import SCHEMA_VERSION, QueueStore, row_of

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def store_at(path: Path) -> QueueStore:
    return QueueStore(path, now=lambda: NOW)


def job(job_id: str, position: int = 0, **fields: Any) -> QueueJob:
    settings = JobSettings(source=SourceRef(path=Path("/media/a.mkv")))
    return QueueJob(id=job_id, position=position, settings=settings, created_at=NOW, **fields)


def run[T](store: QueueStore, call: Callable[[], T]) -> T:
    return store.submit(call).result()


def test_columns_of_the_plan(tmp_path: Path) -> None:
    path = tmp_path / "queue.sqlite3"
    store = store_at(path)
    assert not path.exists()
    assert run(store, store.load).jobs == []
    assert not path.exists()  # nothing written yet
    run(store, lambda: store.upsert([row_of(job("a"))]))
    store.close()
    db = sqlite3.connect(path)
    columns = [row[1] for row in db.execute("PRAGMA table_info(jobs)")]
    assert columns == [
        "id", "position", "state", "settings_json", "plan_json", "issues_json", "created_at",
        "started_at", "finished_at", "output_path", "log_path", "error", "output_size",
    ]  # fmt: skip
    assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    db.close()


def test_round_trip_keeps_unknown_fields(tmp_path: Path) -> None:
    path = tmp_path / "queue.sqlite3"
    store = store_at(path)
    plan = EncodePlan(
        job_type="encode",
        steps=[],
        output_tmp=Path("/o/a.part.mkv"),
        output_final=Path("/o/a.mkv"),
        expected_duration=1.0,
        display="",
    )
    first = job(
        "a",
        state=JobState.FAILED,
        plan=plan,
        issues=[ValidationIssue(severity=Severity.ERROR, code="x.y", message="bad")],
        started_at=NOW,
        finished_at=NOW,
        output_path=Path("/out/a.mkv"),
        log_path=Path("/data/logs/a.log"),
        error="it broke",
    )
    data = first.settings.model_dump(mode="json")
    data["future_field"] = {"kept": True}
    data["video"]["future_option"] = 7
    first.settings = JobSettings.model_validate(data)
    run(store, lambda: store.upsert([row_of(first), row_of(job("b", 5))]))
    run(store, lambda: store.delete("missing"))
    store.close()
    again = store_at(path)
    loaded = run(again, again.load)
    assert [j.id for j in loaded.jobs] == ["a", "b"]
    restored = loaded.jobs[0]
    assert restored.model_dump() == first.model_dump()
    dumped = json.loads(restored.settings.model_dump_json())
    assert dumped["future_field"] == {"kept": True}
    assert dumped["video"]["future_option"] == 7
    assert loaded.jobs[1].position == 5
    again.close()


def test_rows_that_do_not_load_are_kept_untouched(tmp_path: Path) -> None:
    path = tmp_path / "queue.sqlite3"
    store = store_at(path)
    run(store, lambda: store.upsert([row_of(job("ok")), row_of(job("newer", 1))]))
    store.close()
    db = sqlite3.connect(path)
    newer = json.loads(db.execute("SELECT settings_json FROM jobs WHERE id='newer'").fetchone()[0])
    newer["schema_version"] = 99
    db.execute("UPDATE jobs SET settings_json=? WHERE id='newer'", (json.dumps(newer),))
    db.execute(
        "INSERT INTO jobs SELECT 'odd', 2, 'teleporting', settings_json, NULL, 'not json', "
        "created_at, NULL, NULL, NULL, NULL, NULL, NULL FROM jobs WHERE id='ok'"
    )
    db.execute("UPDATE jobs SET plan_json='{\"job_type\": \"x\"}', issues_json='[1]' WHERE id='ok'")
    db.commit()
    db.close()
    again = store_at(path)
    loaded = run(again, again.load)
    assert [j.id for j in loaded.jobs] == ["ok"]
    assert loaded.jobs[0].plan is None  # derived data of another version is dropped
    assert loaded.jobs[0].issues == []
    [warning] = loaded.warnings
    assert warning.code == "queue.rows_skipped"
    assert "2 saved queue job(s)" in warning.message
    run(again, lambda: again.upsert([row_of(loaded.jobs[0])]))
    again.close()
    db = sqlite3.connect(path)
    kept = json.loads(db.execute("SELECT settings_json FROM jobs WHERE id='newer'").fetchone()[0])
    assert kept["schema_version"] == 99
    db.close()


def test_a_corrupt_file_is_backed_up(tmp_path: Path) -> None:
    path = tmp_path / "queue.sqlite3"
    path.write_bytes(b"this is not a database" * 100)
    (tmp_path / "queue.sqlite3-wal").write_bytes(b"junk")
    store = store_at(path)
    loaded = run(store, store.load)
    [warning] = loaded.warnings
    assert warning.code == "queue.corrupt"
    backup = tmp_path / "queue.corrupt-20261014-120000.sqlite3"
    assert backup.read_bytes().startswith(b"this is not")
    run(store, lambda: store.upsert([row_of(job("a"))]))
    store.close()
    again = store_at(path)
    assert [j.id for j in run(again, again.load).jobs] == ["a"]
    again.close()


def test_a_newer_file_is_not_read_or_written(tmp_path: Path) -> None:
    path = tmp_path / "queue.sqlite3"
    db = sqlite3.connect(path)
    db.execute("PRAGMA user_version = 99")
    db.execute("CREATE TABLE jobs (id TEXT)")
    db.commit()
    db.close()
    before = path.read_bytes()
    store = store_at(path)
    loaded = run(store, store.load)
    assert loaded.jobs == []
    assert [w.code for w in loaded.warnings] == ["queue.newer_version"]
    assert store.read_only
    run(store, lambda: store.upsert([row_of(job("a"))]))
    store.close()
    assert path.read_bytes() == before


def test_unreadable_and_unwritable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "queue.sqlite3"
    path.write_bytes(b"")
    store = store_at(path)

    def refuse(*, configure: bool = True) -> sqlite3.Connection:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(store, "_connect", refuse)
    loaded = run(store, store.load)
    assert [w.code for w in loaded.warnings] == ["queue.unreadable"]
    assert store.read_only
    store.close()
    blocked = tmp_path / "file"
    blocked.write_text("x")
    writer = store_at(blocked / "queue.sqlite3")  # its folder cannot be made
    run(writer, lambda: writer.upsert([row_of(job("a"))]))
    run(writer, lambda: writer.upsert([row_of(job("b"))]))
    assert [w.code for w in writer.warnings] == ["queue.not_saved"]  # once
    writer.close()


def test_a_corrupt_file_that_cannot_be_moved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "queue.sqlite3"
    path.write_bytes(b"garbage" * 100)
    store = store_at(path)

    def refuse(src: object, dst: object) -> None:
        raise PermissionError(13, "in use")

    monkeypatch.setattr("reframe.queue.store.os.replace", refuse)
    loaded = run(store, store.load)
    assert [w.code for w in loaded.warnings] == ["queue.unreadable"]
    assert store.read_only
    store.close()
