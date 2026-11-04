"""A byte of a file name that is not UTF-8 (Python's lone surrogate, PEP 383): data keeps it
and :func:`json_text` writes it as an escape; display text shows U+FFFD instead."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel

from reframe.models import (
    AppWarningEvent,
    AudioStream,
    BatchGroup,
    EncodePlan,
    EncoderStatus,
    Fingerprint,
    Fix,
    GroupMember,
    JobLogEvent,
    JobSettings,
    JobState,
    JobStateEvent,
    MediaSource,
    NameResult,
    NotificationEvent,
    PlanStep,
    QueueJob,
    ReplaceOp,
    RoleEvidence,
    Severity,
    SourceRef,
    TaskDoneEvent,
    TaskInfo,
    ToolInfo,
    ToolStatus,
    TrackDecision,
    TrackMatch,
    TrackRole,
    TrackRoleInfo,
    ValidationIssue,
    json_text,
)

#: ``os.fsdecode(b"bad\xffname.mkv")`` on POSIX.
BAD = "bad\udcffname.mkv"
SHOWN = "bad\ufffdname.mkv"
SOURCE = Path("/media") / BAD
OUTPUT = Path("/out") / BAD
OK = Path("/media/ok.mkv")


def settings() -> JobSettings:
    job = JobSettings(source=SourceRef(path=SOURCE))
    job.output.path = OUTPUT
    return job


def issue_with_a_fix() -> ValidationIssue:
    return ValidationIssue(
        severity=Severity.WARNING,
        code="output.name_not_portable",
        path="output.path",
        message=f"{BAD} cannot be written on Windows.",
        fixes=[
            Fix(label=f"Rename {BAD}", patch=[ReplaceOp(path="/output/path", value=str(OUTPUT))])
        ],
    )


DATA: list[BaseModel] = [
    settings(),
    QueueJob(
        id="j1",
        position=0,
        settings=settings(),
        issues=[issue_with_a_fix()],
        created_at=datetime(2026, 10, 19, tzinfo=UTC),
        output_path=OUTPUT,
        log_path=Path("/logs") / BAD,
        error=f"{BAD} failed",
    ),
    MediaSource(ref=SourceRef(path=SOURCE), warnings=[f"{BAD}: no duration"]),
    issue_with_a_fix(),
]


@pytest.mark.parametrize("model", DATA, ids=lambda model: type(model).__name__)
def test_json_text_round_trips_a_path_that_is_not_utf8(model: BaseModel) -> None:
    text = json_text(model)
    assert text.isascii()
    assert "\\udcff" in text
    assert type(model).model_validate(json.loads(text)) == model


def test_json_text_keeps_other_characters_when_not_ascii() -> None:
    job = JobSettings(source=SourceRef(path=Path("/media/コ") / BAD))
    text = json_text(job, ensure_ascii=False, indent=2)
    text.encode("utf-8")
    assert "コ" in text
    assert "bad\\udcffname.mkv" in text
    assert JobSettings.model_validate(json.loads(text)) == job


def test_json_text_of_json_data() -> None:
    data = {"path": f"/media/{BAD}", "n": [1, 2.5, None]}
    assert json_text(data, separators=(",", ":")) == (
        '{"path":"/media/bad\\udcffname.mkv","n":[1,2.5,null]}'
    )
    assert json.loads(json_text(data, ensure_ascii=False)) == data


def test_data_keeps_the_byte_and_display_text_shows_the_replacement() -> None:
    issue = issue_with_a_fix()
    assert issue.message == f"{SHOWN} cannot be written on Windows."
    assert issue.fixes[0].label == f"Rename {SHOWN}"
    patch = issue.fixes[0].patch[0]
    assert isinstance(patch, ReplaceOp)
    assert patch.value == str(OUTPUT)


def test_an_issue_that_quotes_such_a_path_dumps_as_json() -> None:
    issue = ValidationIssue(
        severity=Severity.ERROR, code="source.unreadable", message=f"{SOURCE} cannot be read."
    )
    dumped = json.loads(issue.model_dump_json())
    assert dumped["message"] == f"{SOURCE.parent / SHOWN} cannot be read."


def test_display_text_set_after_validation_is_dumped_with_the_replacement() -> None:
    task = TaskInfo(id="t1", kind="probe_folder")
    task.error = f"cannot read {SOURCE}"
    source = MediaSource(ref=SourceRef(path=OK))
    source.warnings.append(f"MediaInfo could not read {SOURCE}")
    shown = SOURCE.parent / SHOWN
    assert json.loads(task.model_dump_json())["error"] == f"cannot read {shown}"
    assert json.loads(source.model_dump_json())["warnings"] == [f"MediaInfo could not read {shown}"]


DISPLAY: list[BaseModel] = [
    AppWarningEvent(code="queue.unreadable", message=f"m {BAD}", detail=f"d {BAD}"),
    NotificationEvent(title=f"t {BAD}", message=f"m {BAD}"),
    JobStateEvent(job_id="j1", state=JobState.FAILED, error=f"e {BAD}"),
    JobLogEvent(job_id="j1", lines=[f"l {BAD}"]),
    TaskDoneEvent(task=TaskInfo(id="t1", kind="probe_folder", message=f"m {BAD}")),
    ToolInfo(name="ffmpeg", status=ToolStatus.MISSING, reason=f"r {BAD}"),
    EncoderStatus(id="h264_vaapi", reason=f"r {BAD}", detail=f"d {BAD}", reason_10bit=f"t {BAD}"),
    AudioStream(
        index=1,
        roles=[TrackRoleInfo(role=TrackRole.COMMENTARY, evidence=RoleEvidence.TITLE, detail=BAD)],
    ),
    NameResult(
        source="file",
        reason=f"r {BAD}",
        template="{main_title}",
        template_kind="movie",
        relative_path="Movie.mkv",
        extension="mkv",
        notes=[f"n {BAD}"],
    ),
    TrackDecision(source_stream=1, selection=f"s {BAD}", reason=f"r {BAD}", notes=[f"n {BAD}"]),
    BatchGroup(
        id="g1",
        name=f"n {BAD}",
        level="strict",
        representative=OK,
        fingerprint=Fingerprint(level="strict", digest="0"),
        members=[GroupMember(path=OK, match="near", differences=[f"d {BAD}"])],
    ),
    TrackMatch(kind="audio", rule=0, status="relaxed", message=f"m {BAD}"),
    EncodePlan(
        job_type="encode",
        steps=[PlanStep(kind="finalize", tool=None, description=f"Rename {BAD}")],
        output_tmp=OK,
        output_final=OK,
        expected_duration=1.0,
        display=f"ffmpeg -i {BAD}",
    ),
]


@pytest.mark.parametrize("model", DISPLAY, ids=lambda model: type(model).__name__)
def test_display_text_never_holds_a_lone_surrogate(model: BaseModel) -> None:
    assert SHOWN in model.model_dump_json()
