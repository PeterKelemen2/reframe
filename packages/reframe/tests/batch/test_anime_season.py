"""The example anime season through the batch engine: grouping, resolution, overrides and naming.

The source files are the recorded probes that ``anime.py`` loads. Naming reads a stand-in file
system that lists the season folder.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

from pydantic import TypeAdapter
from syrupy.assertion import SnapshotAssertion

from reframe.batch import group_sources, matrix_columns, output_size, resolve_group
from reframe.batch.report import matrix_lines
from reframe.models import (
    AudioOutputSettings,
    BatchResolution,
    ConstantQuality,
    JobTemplate,
    JsonPatchOp,
    MediaSource,
    Preset,
    PresetFile,
)
from reframe.naming import FileTimes, resolve_output_name


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
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


class SeasonFs:
    """The season folder as naming sees it: its files, no file times."""

    def __init__(self, sources: Sequence[MediaSource]) -> None:
        self.names = sorted(s.ref.path.name for s in sources)

    def list_files(self, folder: Path) -> list[str] | None:
        return self.names

    def file_times(self, file: Path) -> FileTimes | None:
        return None


def matrix(
    template: JobTemplate,
    sources: Sequence[MediaSource],
    overrides: Mapping[str, Sequence[JsonPatchOp]] | None = None,
) -> BatchResolution:
    """Group at the standard level, resolve every file and name its output."""
    (group,) = group_sources(sources, "standard")
    by_path = {s.ref.path: s for s in sources}
    fs = SeasonFs(sources)
    rows = []
    for row in resolve_group(group, template, sources, overrides):
        assert row.job is not None
        source = by_path[row.path]
        assert template.naming is not None
        name = resolve_output_name(
            row.path,
            template.naming,
            job=row.job,
            source=source,
            output_size=output_size(row.job, source),
            now=NOW,
            fs=fs,
        )
        job = row.job.model_copy(deep=True)
        job.output.path = name.path
        rows.append(row.model_copy(update={"job": job, "naming": name}))
    return BatchResolution(group=group, columns=matrix_columns(template), rows=rows)


def cells(resolution: BatchResolution) -> dict[str, list[tuple[str, list[int]]]]:
    return {
        f"E{n:02d}": [(m.status, m.streams) for m in row.matches]
        for n, row in enumerate(resolution.rows, start=1)
    }


def test_the_season_groups_and_resolves_as_the_matrix_of_04(snapshot: SnapshotAssertion) -> None:
    resolution = matrix(A.example_template(), A.season(1))
    labels = [c.label for c in resolution.columns]
    assert labels == [
        "V",
        "A1 jpn TrueHD→Opus 5.1",
        "A2 eng DTS-HD MA→AC-3 5.1",
        "S1 eng Signs & Songs",
        "S2 eng Full",
        "Output name",
    ]
    found = cells(resolution)
    exact = [("exact", [1]), ("exact", [2]), ("exact", [3]), ("exact", [4])]
    for episode, row in found.items():
        if episode == "E05":  # the commentary is #3: the subtitles are #4 and #5
            assert row == [("exact", [1]), ("exact", [2]), ("exact", [4]), ("exact", [5])]
        elif episode == "E11":  # no dub: A2 is missing; S1 matches without its title.
            assert row == [("exact", [1]), ("missing", []), ("relaxed", [2]), ("exact", [3])]
        else:
            assert row == exact, episode
    e11 = resolution.rows[10]
    assert e11.matches[2].relaxed == ["title_pattern"]
    assert e11.matches[2].message == "matched without title"
    assert [r.status for r in resolution.rows] == ["ok"] * 10 + ["error", "ok"]
    names = [r.job.output.path.name for r in resolution.rows if r.job and r.job.output.path]
    assert names[0] == "Anime Show - S01E01 - Pilot.mkv"
    assert names[10] == "Anime Show - S01E11 - Static.mkv"
    group = resolution.group
    assert group is not None
    members = [
        f"E{m.episode:02d} {m.match} {'; '.join(m.differences)}".rstrip() for m in group.members
    ]
    head = f"{group.name} · {len(group.members)} files · {group.level} match"
    text = "\n".join([head, *members, "", *matrix_lines(resolution)])
    assert text == snapshot


def test_the_example_steps() -> None:
    """E05's commentary track is not selected, because no rule asks for the ``commentary`` role."""
    resolution = matrix(A.example_template(), A.season(1))
    e05 = resolution.rows[4]
    assert [(d.source_stream, d.selected) for d in e05.decisions] == [
        (1, True),
        (2, True),
        (3, False),
    ]
    assert e05.decisions[2].selection == "No track rule takes this track"
    assert e05.job is not None
    assert [t.source_stream for t in e05.job.audio] == [1, 2]


def test_e01s_audio_setup_gives_identical_audio_settings() -> None:
    e01 = A.recorded(1, 1)
    wanted = [t.model_dump(exclude={"source_stream"}) for t in A.example_job(e01).audio]
    resolution = matrix(A.example_template(e01), A.season(1))
    for n, row in enumerate(resolution.rows, start=1):
        assert row.job is not None
        got = [t.model_dump(exclude={"source_stream"}) for t in row.job.audio]
        if n == 11:  # no dub: A1 only
            assert got == wanted[:1]
        else:
            assert got == wanted, n
    for row in resolution.rows:
        assert row.job is not None
        flags = [(t.metadata.forced, t.metadata.default) for t in row.job.subtitles]
        assert flags == [(True, False), (False, True)]


def test_an_override_survives_a_change_of_the_template() -> None:
    template = A.example_template()
    e03 = str(A.path(1, 3))
    override = {
        e03: OPS.validate_python(
            [
                {"op": "replace", "path": "/audio_rules/0/settings/bitrate", "value": 384},
                {
                    "op": "add",
                    "path": "/job/output/naming/field_overrides/sub_title",
                    "value": "Storm (Extended)",
                },
            ]
        )
    }
    before = matrix(template, A.season(1), override)
    row = before.rows[2]
    assert row.job is not None
    assert [t.bitrate for t in row.job.audio] == [384, 640]
    assert row.job.output.path is not None
    assert row.job.output.path.name == "Anime Show - S01E03 - Storm (Extended).mkv"
    assert row.override == override[e03]

    changed = template.model_copy(deep=True)
    for rule, bitrate in zip(changed.audio_rules, (512, 448), strict=True):
        assert isinstance(rule.settings, AudioOutputSettings)
        rule.settings.bitrate = bitrate
    changed.audio_rules[1].metadata.name_template = "English AC-3"
    assert isinstance(changed.video.rate_control, ConstantQuality)
    changed.video.rate_control.value = 20.0
    after = matrix(changed, A.season(1), override)
    row = after.rows[2]
    assert row.job is not None
    assert [t.bitrate for t in row.job.audio] == [384, 448]  # A1 kept, A2 follows
    assert row.job.audio[1].metadata.name == "English AC-3"
    assert row.job.video.rate_control.value == 20.0  # type: ignore[union-attr]
    assert row.job.output.path is not None
    assert row.job.output.path.name == "Anime Show - S01E03 - Storm (Extended).mkv"
    other = after.rows[3]
    assert other.job is not None
    assert [t.bitrate for t in other.job.audio] == [512, 448]


def test_e11_overrides_skip_the_dub_and_pick_the_signs_by_hand() -> None:
    e11 = str(A.path(1, 11))
    override = {
        e11: OPS.validate_python(
            [
                {"op": "replace", "path": "/audio_rules/1/required", "value": False},
                {"op": "add", "path": "/subtitle_rules/0/selector/stream", "value": 2},
            ]
        )
    }
    row = matrix(A.example_template(), A.season(1), override).rows[10]
    assert [(m.status, m.streams) for m in row.matches] == [
        ("exact", [1]),
        ("skipped", []),
        ("exact", [2]),
        ("exact", [3]),
    ]
    assert row.matches[2].message == "#2 picked by hand"
    assert row.status == "ok"
    assert [i.code for i in row.issues] == ["batch.track_skipped"]


def test_the_saved_template_resolves_season_2_exactly() -> None:
    resolution = matrix(A.example_template(), A.season(2))
    assert all(m.status == "exact" for row in resolution.rows for m in row.matches)
    assert [r.status for r in resolution.rows] == ["ok"] * 3
    names = [r.job.output.path.name for r in resolution.rows if r.job and r.job.output.path]
    assert names == [
        "Anime Show - S02E01 - Return.mkv",
        "Anime Show - S02E02 - Ashes.mkv",
        "Anime Show - S02E03 - Northbound.mkv",
    ]


def test_the_demo_preset_file_is_the_derived_template() -> None:
    saved = json.loads(A.PRESET_FILE.read_text(encoding="utf-8"))
    assert saved == A.preset_document()
    (preset,) = PresetFile.model_validate(saved).presets
    assert isinstance(preset, Preset)
    assert preset.name == A.PRESET_NAME
    assert [rule.required for rule in preset.audio_rules] == [True, False]
    derived = A.example_template()
    assert preset.subtitle_rules == derived.subtitle_rules
    assert preset.audio_rules[0] == derived.audio_rules[0]
    # With the dub optional, E11 resolves without an error: every episode can be queued.
    rows = matrix(preset, A.season(1)).rows
    assert [r.status for r in rows] == ["ok"] * 10 + ["warning", "ok"]
    assert [(m.status, m.streams) for m in rows[10].matches][1] == ("skipped", [])
