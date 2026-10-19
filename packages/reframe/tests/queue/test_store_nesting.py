"""The queue store with JSON nested deeper than ``MAX_DEPTH``: a deep row is skipped and kept
untouched, and a deep document is not written and never raises ``RecursionError``."""

from __future__ import annotations

import copy
import json
import sqlite3
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from reframe.models import (
    AppWarningEvent,
    JobSettings,
    JobState,
    QueueJob,
    Severity,
    SourceRef,
    ValidationIssue,
)
from reframe.queue import QueueService
from reframe.queue.store import QueueStore, row_of
from reframe.settings import MAX_DEPTH, TOO_DEEP, too_deep

from .conftest import Harness

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)

#: Deep enough for ``json.loads`` to raise ``RecursionError`` on any thread.
PARSER_DEPTH = 200_000


def nested(levels: int) -> list[Any]:
    """A list nested ``levels`` deep (``[]`` is one level)."""
    value: list[Any] = []
    for _ in range(levels - 1):
        value = [value]
    return value


def deep_text(levels: int) -> str:
    return "[" * levels + "]" * levels


def depth(value: object) -> int:
    """The nesting of ``value`` exactly, as ``too_deep`` counts it."""
    assert not too_deep(value, 100_000)
    low = 0
    while too_deep(value, low):
        low += 1
    return low


def store_at(path: Path) -> QueueStore:
    return QueueStore(path, now=lambda: NOW)


def run[T](store: QueueStore, call: Callable[[], T]) -> T:
    return store.submit(call).result()


def job(job_id: str, position: int = 0, *, extra: object = None, **fields: object) -> QueueJob:
    data = JobSettings(source=SourceRef(path=Path("/media/a.mkv"))).model_dump(mode="json")
    if extra is not None:
        data["from_the_future"] = extra
    settings = JobSettings.model_validate(data)
    return QueueJob(id=job_id, position=position, settings=settings, created_at=NOW, **fields)  # type: ignore[arg-type]


def settings_of(levels: int) -> dict[str, Any]:
    """A ``settings_json`` document nested exactly ``levels`` deep (an unknown field)."""
    data = job("x").settings.model_dump(mode="json")
    data["from_the_future"] = nested(levels - 1)
    assert depth(data) == levels
    return data


def issues_of(levels: int) -> list[dict[str, Any]]:
    """An ``issues_json`` document nested exactly ``levels`` deep (a fix's patch value)."""
    issue = ValidationIssue(severity=Severity.ERROR, code="x.y", message="bad")
    data = [issue.model_dump(mode="json")]
    op = {"op": "add", "path": "/x", "value": nested(levels - 6)}
    data[0]["fixes"] = [{"label": "Fix", "patch": [op], "target": "job"}]
    assert depth(data) == levels
    return data


def put_rows(path: Path, *rows: tuple[str, str, str | None, str]) -> None:
    """Insert ``(id, settings_json, plan_json, issues_json)`` rows as another program would."""
    db = sqlite3.connect(path)
    for position, (job_id, settings, plan, issues) in enumerate(rows, start=10):
        db.execute(
            "INSERT INTO jobs VALUES (?, ?, 'waiting', ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL)",
            (job_id, position, settings, plan, issues, NOW.isoformat()),
        )
    db.commit()
    db.close()


def stored(path: Path) -> dict[str, tuple[Any, ...]]:
    db = sqlite3.connect(path)
    rows = {row[0]: row for row in db.execute("SELECT * FROM jobs")}
    db.close()
    return rows


def new_store(tmp_path: Path) -> Path:
    path = tmp_path / "queue.sqlite3"
    store = store_at(path)
    run(store, lambda: store.upsert([row_of(job("ok"))]))
    store.close()
    return path


def test_python_facts_behind_the_rule() -> None:
    assert issubclass(RecursionError, RuntimeError)
    assert not issubclass(RecursionError, ValueError)
    assert json.loads(deep_text(1000)) == nested(1000)  # no recursion limit of 1000 here
    with pytest.raises(RecursionError):
        json.loads(deep_text(PARSER_DEPTH))
    caught: list[BaseException] = []

    def on_a_thread() -> None:  # the store parses on its own thread
        try:
            json.loads(deep_text(PARSER_DEPTH))
        except BaseException as exc:
            caught.append(exc)

    thread = threading.Thread(target=on_a_thread)
    thread.start()
    thread.join()
    assert [type(exc) for exc in caught] == [RecursionError]
    with pytest.raises(RecursionError):
        copy.deepcopy({"x": nested(1000)})
    settings = JobSettings.model_validate(settings_of(300))  # validation: any depth
    with pytest.raises(ValueError, match="depth exceeded"):
        settings.model_dump(mode="json")
    assert JobSettings.model_validate(settings_of(255)).model_dump(mode="json")


@pytest.mark.parametrize("levels", [MAX_DEPTH + 1, 300, 1000, PARSER_DEPTH])
def test_a_row_nested_too_deeply_is_skipped_and_kept_untouched(tmp_path: Path, levels: int) -> None:
    """The depths that break a reader (Pydantic's dump, the migrations' ``deepcopy``,
    ``json.loads``), in each of the three JSON columns."""
    path = new_store(tmp_path)
    plain = row_of(job("x"))
    good_settings, good_issues = plain[3], plain[5]
    deep = deep_text(levels - 1)
    deep_settings = good_settings[:-1] + f',"from_the_future":{deep}}}'
    put_rows(
        path,
        ("deep-settings", deep_settings, None, good_issues),
        ("deep-plan", good_settings, f'{{"x":{deep}}}', good_issues),
        ("deep-issues", good_settings, None, f"[{deep}]"),
    )
    before = stored(path)
    store = store_at(path)
    loaded = run(store, store.load)
    assert [j.id for j in loaded.jobs] == ["ok"]
    [warning] = loaded.warnings
    assert warning.code == "queue.rows_skipped"
    assert "3 saved queue job(s)" in warning.message
    assert warning.detail is not None
    for column, job_id in [
        ("settings_json", "deep-settings"),
        ("plan_json", "deep-plan"),
        ("issues_json", "deep-issues"),
    ]:
        assert f"{job_id}: {column}: {TOO_DEEP}" in warning.detail
    run(store, lambda: store.upsert([row_of(loaded.jobs[0])]))  # a later write
    store.close()
    after = stored(path)
    for job_id in ("deep-settings", "deep-plan", "deep-issues"):
        assert after[job_id] == before[job_id]  # untouched


def test_documents_of_64_levels_load(tmp_path: Path) -> None:
    """The limit itself: every column nested exactly 64 levels loads and saves again."""
    path = tmp_path / "queue.sqlite3"
    store = store_at(path)
    first = job(
        "edge",
        extra=nested(MAX_DEPTH - 1),
        issues=[ValidationIssue.model_validate(issue) for issue in issues_of(MAX_DEPTH)],
        state=JobState.FAILED,
    )
    row = row_of(first)
    assert depth(json.loads(row[3])) == MAX_DEPTH
    assert depth(json.loads(row[5])) == MAX_DEPTH
    run(store, lambda: store.upsert([row]))
    store.close()
    again = store_at(path)
    loaded = run(again, again.load)
    assert loaded.warnings == []
    [restored] = loaded.jobs
    assert restored.model_dump() == first.model_dump()
    again.close()


def test_a_plan_of_64_levels_is_derived_data(tmp_path: Path) -> None:
    """A ``plan_json`` of this depth is not too deep: an unknown plan is dropped (it is planned
    again before a run), and the row loads."""
    path = new_store(tmp_path)
    plain = row_of(job("x"))
    put_rows(path, ("plan64", plain[3], json.dumps({"x": nested(MAX_DEPTH - 1)}), plain[5]))
    store = store_at(path)
    loaded = run(store, store.load)
    assert [j.id for j in loaded.jobs] == ["ok", "plan64"]
    assert loaded.jobs[1].plan is None
    assert loaded.warnings == []
    store.close()


def test_settings_that_are_not_an_object_are_a_damaged_row(tmp_path: Path) -> None:
    """A ``settings_json`` that is JSON but not an object is a damaged row, not a crash in the
    migrations."""
    path = new_store(tmp_path)
    plain = row_of(job("x"))
    put_rows(path, ("list", "[1]", None, plain[5]), ("text", '"x"', None, plain[5]))
    store = store_at(path)
    loaded = run(store, store.load)
    assert [j.id for j in loaded.jobs] == ["ok"]
    [warning] = loaded.warnings
    assert warning.code == "queue.rows_skipped"
    assert warning.detail is not None
    assert "list: settings_json: not a JSON object" in warning.detail
    store.close()


@pytest.mark.parametrize(
    ("levels", "detail"),
    [(MAX_DEPTH + 1, TOO_DEEP), (300, "depth exceeded")],
)
def test_a_job_nested_too_deeply_is_never_written(tmp_path: Path, levels: int, detail: str) -> None:
    """``row_of`` never raises, and ``upsert`` leaves the deep row out: the file keeps the job's
    earlier row."""
    path = tmp_path / "queue.sqlite3"
    store = store_at(path)
    early = job("deep")
    run(store, lambda: store.upsert([row_of(early)]))
    before = stored(path)["deep"]
    deep = job("deep", extra=nested(levels - 1), state=JobState.FAILED)
    rows = [row_of(deep), row_of(job("other", 1))]
    assert isinstance(rows[0][3], str)  # still a Row
    run(store, lambda: store.upsert(rows))
    run(store, lambda: store.upsert([row_of(deep)]))  # again: no second warning
    [warning] = store.warnings
    assert warning.code == "queue.job_not_saved"
    assert "deep" in warning.message
    assert warning.detail is not None
    assert warning.detail.startswith("settings_json: ")
    assert detail in warning.detail
    store.close()
    after = stored(path)
    assert after["deep"] == before  # the earlier row, untouched
    assert "other" in after
    again = store_at(path)
    loaded = run(again, again.load)
    assert loaded.warnings == []  # a file this store wrote always loads
    assert [j.id for j in loaded.jobs] == ["deep", "other"]
    assert loaded.jobs[0].state is JobState.WAITING
    again.close()


def test_deep_issues_are_never_written(tmp_path: Path) -> None:
    path = tmp_path / "queue.sqlite3"
    store = store_at(path)
    issues = [ValidationIssue.model_validate(issue) for issue in issues_of(MAX_DEPTH + 1)]
    run(store, lambda: store.upsert([row_of(job("deep", issues=issues))]))
    [warning] = store.warnings
    assert warning.code == "queue.job_not_saved"
    assert warning.detail == f"issues_json: {TOO_DEEP}"
    store.close()
    assert not path.exists()  # nothing was written: the file is made at the first write


def test_a_store_that_saves_nothing_gives_no_warning(tmp_path: Path) -> None:
    """A private store in memory (another process owns the file) never says "not saved" for
    one job: nothing of it is saved anyway."""
    store = store_at(tmp_path / "queue.sqlite3")
    store.use_memory()
    run(store, lambda: store.upsert([row_of(job("deep", extra=nested(MAX_DEPTH)))]))
    assert store.warnings == []
    store.close()


def queue_at(h: Harness) -> QueueService:
    """A second queue on the same data folder (a restarted Reframe)."""
    from reframe.platform.sleep import SleepInhibitor

    return QueueService(
        h.events,
        lambda: h.settings.model_copy(deep=True),
        data_dir=h.tmp / "data",
        tools=h.tools,
        capabilities=h.caps,
        sources=h.sources,
        inhibitor=SleepInhibitor([], h.events),
    )


def codes(h: Harness) -> list[str]:
    return [e.code for e in h.events.published if isinstance(e, AppWarningEvent)]


@pytest.mark.anyio
async def test_the_queue_starts_with_a_deep_row_and_keeps_a_deep_job(harness: Harness) -> None:
    h = harness
    data = h.job().model_dump(mode="json")
    data["from_the_future"] = nested(MAX_DEPTH)
    deep = await h.queue.add(JobSettings.model_validate(data))
    assert h.queue.get(deep.id) is not None
    assert "queue.job_not_saved" in codes(h)
    kept = await h.queue.add(h.job("Kept"))
    await h.queue.close()
    path = h.tmp / "data" / "queue.sqlite3"
    assert deep.id not in stored(path)
    db = sqlite3.connect(path)
    db.execute("UPDATE jobs SET state = 'running' WHERE id = ?", (kept.id,))
    good = db.execute("SELECT settings_json FROM jobs WHERE id = ?", (kept.id,)).fetchone()[0]
    deep_settings = good[:-1] + f',"from_the_future":{deep_text(PARSER_DEPTH)}}}'
    db.execute(
        "INSERT INTO jobs SELECT 'deep-row', 9, 'running', ?, plan_json, issues_json, "
        "created_at, NULL, NULL, NULL, NULL, NULL FROM jobs WHERE id = ?",
        (deep_settings, kept.id),
    )
    db.commit()
    db.close()
    before = stored(path)["deep-row"]
    again = queue_at(h)
    again.list()  # the first use opens the store
    try:
        assert [(j.id, j.state) for j in again.list()] == [(kept.id, JobState.INTERRUPTED)]
        assert "queue.rows_skipped" in codes(h)
    finally:
        await again.close()
    after = stored(path)
    assert after["deep-row"] == before
    assert after[kept.id][2] == "interrupted"
