"""C-12 M7: resolving a template in one file (the job, its per-file policies) and in a group
(04 §Concepts "Resolution", §Per-file overrides)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from pydantic import TypeAdapter

from reframe.batch import build_job, group_sources, matrix_columns, resolve, resolve_group
from reframe.batch.resolve import row_status
from reframe.models import (
    ChapterOptions,
    CropRect,
    CropSettings,
    JobTemplate,
    JsonPatchOp,
    LanguageSettings,
    Severity,
    TrackDraft,
    TrackMatch,
    ValidationIssue,
)


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"_reframe_batch_{name}", Path(__file__).with_name(f"{name}.py")
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


A = _load("anime")
OPS = TypeAdapter(list[JsonPatchOp])


def test_the_job_of_a_preset_and_of_a_template() -> None:
    e01 = A.recorded(1, 1)
    preset = A.builtin("h265-mkv-1080p")
    job, notes = build_job(preset, e01, TrackDraft())
    assert (job.preset_id, job.preset_name) == ("h265-mkv-1080p", "H.265 MKV 1080p")
    assert job.source == e01.ref
    assert job.video.metadata.default  # decision 0024 item 5
    assert job.range.kind == "full"  # 04: the range is the whole file
    assert notes == []
    job, _ = build_job(JobTemplate(), e01, TrackDraft())
    assert (job.preset_id, job.preset_name) == (None, None)


def test_the_crop_policy() -> None:
    e01 = A.recorded(1, 1)
    rect = CropRect(top=20, bottom=20)
    detected = JobTemplate.model_validate(
        {"dimensions": {"crop": {"mode": "auto", "rect": rect.model_dump()}}}
    )
    job, notes = build_job(detected, e01, TrackDraft())
    assert job.dimensions.crop == CropSettings(mode="auto")
    assert notes == [
        "Crop: detected for each file (the template's crop policy); the template's crop "
        "rectangle is not used."
    ]
    fixed = detected.model_copy(update={"crop_policy": "fixed"})
    job, notes = build_job(fixed, e01, TrackDraft())
    assert job.dimensions.crop == CropSettings(mode="manual", rect=rect)
    assert notes == []
    manual = JobTemplate.model_validate(
        {"dimensions": {"crop": {"mode": "manual", "rect": rect.model_dump()}}}
    )
    assert build_job(manual, e01, TrackDraft())[0].dimensions.crop.rect == rect
    none = JobTemplate.model_validate({"dimensions": {"crop": {"mode": "none"}}})
    assert build_job(none, e01, TrackDraft())[0].dimensions.crop == CropSettings(mode="none")


def test_chapter_names() -> None:
    chaptered = A.recorded(1, 1).model_copy(
        update={
            "chapters": [
                {"index": 0, "start": 0.0, "end": 1.0},
                {"index": 1, "start": 1.0, "end": 2.0},
            ]
        }
    )
    generated = JobTemplate(
        chapter_name_policy="generated", chapters=ChapterOptions(generate_every=3.0)
    )
    job, notes = build_job(generated, chaptered, TrackDraft())
    assert job.chapters.names == ["Chapter 1", "Chapter 2"]
    assert job.chapters.generate_every == 3.0
    assert notes == ["Chapter names: generated (Chapter 1, Chapter 2, …), as the preset says."]
    assert build_job(JobTemplate(), chaptered, TrackDraft())[0].chapters.names is None


def test_row_status() -> None:
    def match(severity: Severity | None) -> TrackMatch:
        return TrackMatch(kind="audio", rule=0, status="exact", severity=severity)

    def issue(severity: Severity) -> ValidationIssue:
        return ValidationIssue(severity=severity, code="x", message="x")

    assert row_status([match(None), match(Severity.INFO)], [issue(Severity.INFO)]) == "ok"
    assert row_status([match(Severity.WARNING)], []) == "warning"
    assert row_status([], [issue(Severity.WARNING)]) == "warning"
    assert row_status([match(Severity.WARNING)], [issue(Severity.ERROR)]) == "error"


def test_resolve_one_file() -> None:
    e11 = A.recorded(1, 11)
    stale = OPS.validate_python(
        [{"op": "replace", "path": "/audio_rules/9/required", "value": False}]
    )
    resolution = resolve(A.example_template(), e11, stale)
    assert resolution.path == e11.ref.path
    assert resolution.status == "error"
    assert resolution.override == stale
    assert [i.code for i in resolution.issues] == [
        "batch.track_missing",
        "batch.track_relaxed",
        "batch.override_stale",
    ]
    assert len(resolution.decisions) == len(e11.audio)
    assert len(resolution.subtitle_decisions) == len(e11.subtitles)
    assert resolution.naming is None  # naming is the service's (it reads the file system)
    assert resolution.job is not None
    assert resolution.job.output.path is None


def test_resolve_a_group() -> None:
    sources = A.season(1)
    (group,) = group_sources(sources, "standard")
    e02 = str(A.path(1, 2))
    override = {
        e02: OPS.validate_python([{"op": "replace", "path": "/video/preset", "value": "veryslow"}])
    }
    rows = resolve_group(group, A.example_template(), sources[1:], override)
    assert [r.path for r in rows] == [m.path for m in group.members]
    missing = rows[0]
    assert (missing.status, missing.job) == ("error", None)
    assert [i.code for i in missing.issues] == ["source.probe_failed"]
    assert rows[1].job is not None
    assert rows[1].job.video.preset == "veryslow"
    assert rows[2].job is not None
    assert rows[2].job.video.preset != "veryslow"
    by_path = {s.ref.path: s for s in sources}
    again = resolve_group(group, A.example_template(), by_path)
    assert [r.status for r in again] == ["ok"] * 10 + ["error", "ok"]


def test_the_columns() -> None:
    assert [c.label for c in matrix_columns(JobTemplate())] == [
        "V",
        "A1 every track (defaults)",
        "S1 every track (defaults)",
        "Output name",
    ]
    preferred = LanguageSettings(preferred_audio=["ja", "en"], preferred_subtitle=["en"])
    labels = [c.label for c in matrix_columns(JobTemplate(), languages=preferred)]
    assert labels == [
        "V",
        "A1 jpn (defaults)",
        "A2 eng (defaults)",
        "A3 no listed language (defaults)",
        "S1 eng (defaults)",
        "Output name",
    ]
    explicit = matrix_columns(A.example_template())
    assert [c.kind for c in explicit] == ["video", "audio", "audio", "subtitle", "subtitle", "name"]
    assert [c.rule for c in explicit] == [None, 0, 1, 0, 1, None]
    assert not any(c.defaults for c in explicit)
