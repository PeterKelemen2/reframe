"""Per-file overrides as JSON patches, split and applied to a template or a job."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from reframe.batch import apply_job_override, apply_template_override, split_override
from reframe.models import (
    JobSettings,
    JobTemplate,
    JsonPatchOp,
    OutputTrackRule,
    Severity,
    SourceRef,
    SubtitleOutputSettings,
    TrackSelector,
)

OPS = TypeAdapter(list[JsonPatchOp])


def ops(*items: dict[str, Any]) -> list[JsonPatchOp]:
    return OPS.validate_python(list(items))


def template() -> JobTemplate:
    rule = OutputTrackRule(
        selector=TrackSelector(kind="subtitle", languages=["en"]), settings=SubtitleOutputSettings()
    )
    return JobTemplate(subtitle_rules=[rule])


def job() -> JobSettings:
    return JobSettings(source=SourceRef(path=Path("/m/a.mkv")))


def test_split() -> None:
    patch = ops(
        {"op": "replace", "path": "/video/encoder", "value": "libx264"},
        {"op": "add", "path": "/job/output/naming/field_overrides/episode", "value": "3"},
        {"op": "copy", "from": "/job/output/path", "path": "/job/tags/comment"},
        {"op": "move", "from": "/video/preset", "path": "/job/video/preset"},
        {"op": "replace", "path": "/job", "value": {}},
    )
    template_ops, job_ops, issues = split_override(patch)
    assert [op.path for op in template_ops] == ["/video/encoder"]
    assert [(op.op, op.path) for op in job_ops] == [
        ("add", "/output/naming/field_overrides/episode"),
        ("copy", "/tags/comment"),
        ("replace", ""),
    ]
    assert job_ops[1].from_ == "/output/path"  # type: ignore[union-attr]
    (issue,) = issues
    assert (issue.code, issue.severity, issue.path) == (
        "batch.override_invalid",
        Severity.ERROR,
        "job.video.preset",
    )
    assert split_override(None) == ([], [], [])


def test_a_template_override() -> None:
    patched, issues = apply_template_override(
        template(),
        ops(
            {"op": "replace", "path": "/video/encoder", "value": "libx264"},
            {"op": "add", "path": "/subtitle_rules/0/selector/stream", "value": 4},
        ),
    )
    assert issues == []
    assert patched.video.encoder == "libx264"
    assert patched.subtitle_rules[0].selector.stream == 4
    assert template().video.encoder == "libx265"


def test_an_operation_whose_path_vanished_is_skipped() -> None:
    patched, issues = apply_template_override(
        template(),
        ops(
            {"op": "replace", "path": "/audio_rules/0/settings/bitrate", "value": 384},
            {"op": "replace", "path": "/video/encoder", "value": "libx264"},
        ),
    )
    assert patched.video.encoder == "libx264"
    (issue,) = issues
    assert (issue.code, issue.severity, issue.path) == (
        "batch.override_stale",
        Severity.WARNING,
        "audio_rules[0].settings.bitrate",
    )
    assert "no longer applies" in issue.message


def test_a_failed_test_skips_the_rest() -> None:
    patched, issues = apply_template_override(
        template(),
        ops(
            {"op": "replace", "path": "/video/preset", "value": "slow"},
            {"op": "test", "path": "/subtitle_rules/0/selector/languages", "value": ["ja"]},
            {"op": "replace", "path": "/video/encoder", "value": "libx264"},
            {"op": "replace", "path": "/video/tune", "value": "film"},
        ),
    )
    assert (patched.video.preset, patched.video.encoder) == ("slow", "libx265")
    (issue,) = issues
    assert issue.code == "batch.override_stale"
    assert "last 3 operations are not applied" in issue.message
    only_test = ops({"op": "test", "path": "/video/encoder", "value": "x"})
    patched, issues = apply_template_override(template(), only_test)
    assert patched == template()
    assert "last 1 operation are" not in issues[0].message


def test_an_invalid_result_is_not_applied() -> None:
    patched, issues = apply_template_override(
        template(), ops({"op": "replace", "path": "/crop_policy", "value": "sometimes"})
    )
    assert patched == template()
    (issue,) = issues
    assert (issue.code, issue.severity, issue.path) == (
        "batch.override_invalid",
        Severity.ERROR,
        "crop_policy",
    )


def test_a_job_override() -> None:
    patched, issues = apply_job_override(
        job(),
        ops(
            {"op": "add", "path": "/output/naming/field_overrides/sub_title", "value": "Pilot"},
            {"op": "replace", "path": "/range", "value": {"kind": "time", "start": 0, "end": 60}},
        ),
    )
    assert issues == []
    assert patched.output.naming.field_overrides == {"sub_title": "Pilot"}
    assert patched.range.kind == "time"
    stale, issues = apply_job_override(job(), ops({"op": "remove", "path": "/audio/0"}))
    assert stale == job()
    assert [(i.code, i.path) for i in issues] == [("batch.override_stale", "job.audio[0]")]
    bad, issues = apply_job_override(job(), ops({"op": "replace", "path": "/range", "value": 5}))
    assert bad == job()
    assert [i.code for i in issues] == ["batch.override_invalid"]
    assert apply_job_override(job(), []) == (job(), [])
