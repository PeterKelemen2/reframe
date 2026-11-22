"""Resolving a template for one file and for a group of files."""

from __future__ import annotations

from pydantic import TypeAdapter

from reframe.batch import build_job, group_sources, matrix_columns, resolve
from reframe.batch.report import matrix_lines
from reframe.batch.resolve import row_status
from reframe.models import (
    BatchResolution,
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

from . import anime as A

OPS = TypeAdapter(list[JsonPatchOp])


def test_the_job_of_a_preset_and_of_a_template() -> None:
    e01 = A.recorded(1, 1)
    preset = A.builtin("h265-mkv-1080p")
    job, notes = build_job(preset, e01, TrackDraft())
    assert (job.preset_id, job.preset_name) == ("h265-mkv-1080p", "H.265 MKV 1080p")
    assert job.source == e01.ref
    assert job.video.metadata.default  # The drafted video track gets the default flag.
    assert job.range.kind == "full"  # The range is the whole file.
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
    # A failed detection belongs to the file it failed in.
    failed = JobTemplate.model_validate(
        {"dimensions": {"crop": {"mode": "auto", "detection_error": "Crop detection failed."}}}
    )
    assert build_job(failed, e01, TrackDraft())[0].dimensions.crop == CropSettings(mode="auto")


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


def test_an_override_that_changes_the_rule_lists_is_invalid() -> None:
    """A change to the rule list would put this file's cells under other rules' columns."""
    template = A.example_template()
    sources = A.season(1)[:3]
    (group,) = group_sources(sources, "standard")
    e02 = str(A.path(1, 2))
    plain = resolve(template, sources[1])
    signs = template.subtitle_rules[0].model_dump(mode="json")
    for ops in (
        [{"op": "remove", "path": "/audio_rules/0"}],
        [{"op": "add", "path": "/subtitle_rules/-", "value": signs}],
        [{"op": "move", "from": "/audio_rules/1", "path": "/audio_rules/0"}],
        [{"op": "replace", "path": "/audio_rules", "value": []}],
        [
            {"op": "replace", "path": "/video/preset", "value": "slow"},
            {"op": "copy", "from": "/audio_rules/0", "path": "/audio_rules/1"},
        ],
    ):
        patch = OPS.validate_python(ops)
        rows = [resolve(template, s, patch if str(s.ref.path) == e02 else None) for s in sources]
        row = rows[1]
        assert "batch.override_invalid" in [i.code for i in row.issues], ops
        assert row.job is not None
        assert plain.job is not None
        assert row.job.audio == plain.job.audio, ops
        assert row.job.video.preset == plain.job.video.preset  # the whole template part
        assert row.matches == plain.matches
        resolution = BatchResolution(group=group, columns=matrix_columns(template), rows=rows)
        lines = matrix_lines(resolution)
        a1 = lines[0].index("A1")
        assert lines[3][a1:].startswith("✓ #1"), lines[3]
    # A change inside a rule is fine: it keeps its column.
    bitrate = OPS.validate_python(
        [{"op": "replace", "path": "/audio_rules/1/settings/bitrate", "value": 448}]
    )
    row = resolve(template, sources[1], bitrate)
    assert row.job is not None
    assert [a.bitrate for a in row.job.audio] == [448, 448]
    assert all(i.severity.value != "error" for i in row.issues)


def _codes(issues: list[ValidationIssue]) -> list[str]:
    return [issue.code for issue in issues]


def _replace(path: str, value: object) -> list[JsonPatchOp]:
    return OPS.validate_python([{"op": "replace", "path": path, "value": value}])


def test_an_override_that_changes_the_compiled_rules_is_invalid() -> None:
    """The override changes what the compiled audio columns mean, so it is invalid: the English
    dub would land under "A1 jpn"."""
    template = A.japanese_template()
    sources = A.season(1)[:2]
    (group,) = group_sources(sources, "standard")
    columns = matrix_columns(template)
    assert [c.label for c in columns if c.kind == "audio"] == [
        "A1 jpn (defaults)",
        "A2 no listed language (defaults)",
        "A3 other languages (defaults)",
    ]
    override = _replace("/audio_defaults/selection/languages", ["eng", "jpn"])
    rows = [resolve(template, sources[0]), resolve(template, sources[1], override)]
    e01, e02 = rows
    (invalid,) = [i for i in e02.issues if i.code == "batch.override_invalid"]
    assert invalid.path == "audio_defaults.selection"
    assert "A1 jpn, A2 no listed language, A3 other languages → A1 eng, A2 jpn, A3 no" in (
        invalid.message
    )
    assert e02.status == "error"
    audio = [(m.rule, m.status, m.streams) for m in e02.matches if m.kind == "audio"]
    assert audio == [(m.rule, m.status, m.streams) for m in e01.matches if m.kind == "audio"]
    assert audio[0] == (0, "exact", [1])  # A1 jpn: the Japanese track, not the dub
    assert e02.job is not None
    assert e01.job is not None
    assert [a.source_stream for a in e02.job.audio] == [a.source_stream for a in e01.job.audio]
    lines = matrix_lines(BatchResolution(group=group, columns=columns, rows=rows))
    a1 = lines[0].index("A1")
    assert lines[2][a1:].startswith("✓ #1")
    assert lines[3][a1:].startswith("✓ #1")


def test_an_override_inside_the_compiled_rules_is_applied() -> None:
    """A language override that keeps the structure is applied: here the A1 rule takes the dub."""
    template = A.japanese_template()
    e02 = A.recorded(1, 2)
    swapped = resolve(template, e02, _replace("/audio_defaults/selection/languages", ["eng"]))
    assert "batch.override_invalid" not in _codes(swapped.issues)
    assert next((m.rule, m.streams) for m in swapped.matches if m.kind == "audio") == (0, [2])
    codec = resolve(
        template,
        e02,
        OPS.validate_python(
            [
                {
                    "op": "add",
                    "path": "/audio_defaults/codec_rules/0",
                    "value": {"codec": "libopus", "max_bitrate": 96},
                }
            ]
        ),
    )
    assert "batch.override_invalid" not in _codes(codec.issues)
    assert codec.job is not None
    assert {(a.encoder, a.bitrate) for a in codec.job.audio} == {("libopus", 96)}
    explicit = A.example_template()
    row = resolve(
        explicit, e02, _replace("/audio_defaults/selection/languages", ["eng", "jpn", "fre"])
    )
    assert "batch.override_invalid" not in _codes(row.issues)


def test_another_number_of_preferred_languages_is_an_invalid_override() -> None:
    """An empty language list compiles to the preferred languages: another number of them is
    invalid."""
    base = A.builtin("h265-mkv-1080p")
    e02 = A.recorded(1, 2)
    languages = LanguageSettings(preferred_audio=["jpn"])
    same = resolve(
        base, e02, _replace("/audio_defaults/selection/languages", ["jpn"]), languages=languages
    )
    assert "batch.override_invalid" not in _codes(same.issues)
    more = resolve(
        base,
        e02,
        _replace("/audio_defaults/selection/languages", ["jpn", "eng"]),
        languages=languages,
    )
    assert "batch.override_invalid" in _codes(more.issues)
