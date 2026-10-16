"""C-12 M7: the match report as text (04 §Resolving rules, §Resolution matrix)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from reframe.batch.report import match_cell, matrix_lines, name_cell, video_cell
from reframe.models import (
    BatchResolution,
    JobSettings,
    MatrixColumn,
    NameResult,
    Resolution,
    SourceRef,
    TrackMatch,
)


def cell(status: str, **kw: Any) -> TrackMatch:
    return TrackMatch.model_validate({"kind": "audio", "rule": 0, "status": status, **kw})


def test_cells() -> None:
    assert match_cell(cell("exact", streams=[1])) == "✓ #1"
    assert match_cell(cell("exact", streams=[1, 2])) == "✓ #1 #2"
    relaxed = cell("relaxed", streams=[2], relaxed=["title_pattern", "profiles"])
    assert match_cell(relaxed) == "≈ #2 (title, profile)"
    assert match_cell(cell("ambiguous", streams=[3], candidates=[3, 4])) == "≈ #3 (2 candidates)"
    assert match_cell(cell("missing")) == "✗ none"
    assert match_cell(cell("skipped")) == "\N{EN DASH} skipped"
    assert match_cell(cell("missing"), unicode=False) == "x none"
    assert match_cell(cell("exact", streams=[1, 2]), unicode=False) == "ok #1 #2"
    assert match_cell(relaxed, unicode=False) == "~ #2 (title, profile)"


def naming(relative: str) -> NameResult:
    return NameResult(
        source="file",
        reason="",
        template="{name}",
        template_kind="episode",
        relative_path=relative,
        extension="mkv",
        variables={"resolution": "1080p"},
    )


def row(name: str, output: str | None, status: str = "ok", **kw: Any) -> Resolution:
    job = JobSettings(source=SourceRef(path=Path("/tv") / name))
    if output is not None:
        job.output.path = Path("/tv") / output
    return Resolution.model_validate(
        {"path": Path("/tv") / name, "job": job, "status": status, **kw}
    )


def test_video_and_name_cells() -> None:
    plain = row("Show.S01E01.mkv", "Show/Season 01/Show - S01E01.mkv")
    assert video_cell(plain) == "\N{EN DASH}"  # not named yet: no size
    named = plain.model_copy(update={"naming": naming("Show/Season 01/Show - S01E01.mkv")})
    assert video_cell(named) == "✓ 1080p"
    assert video_cell(named, unicode=False) == "ok 1080p"
    assert name_cell(named) == "Show/Season 01/Show - S01E01.mkv"
    renamed = row("Show.S01E01.mkv", "Show (1).mkv").model_copy(
        update={"naming": naming("Show.mkv")}
    )
    assert name_cell(renamed) == "Show (1).mkv"
    undecodable = row("bad\udcffname.mkv", "bad\udcffname (1).mkv")
    assert name_cell(undecodable) == "bad\N{REPLACEMENT CHARACTER}name (1).mkv"
    assert name_cell(row("x.mkv", None)) == "—"
    missing = Resolution(path=Path("/tv/x.mkv"), status="error")
    assert (video_cell(missing), name_cell(missing)) == ("✗", "—")


def test_matrix_lines() -> None:
    columns = [
        MatrixColumn(kind="video", label="V"),
        MatrixColumn(kind="audio", rule=0, label="A1 jpn TrueHD→Opus 5.1"),
        MatrixColumn(kind="subtitle", rule=0, label="S1 eng Full"),
        MatrixColumn(kind="name", label="Output name"),
    ]
    subtitle = {"kind": "subtitle", "rule": 0, "status": "exact", "streams": [3]}
    rows = [
        row("Show.S01E01.mkv", "第一話.mkv", matches=[cell("exact", streams=[1])]),
        row(
            "Show.S01E02.mkv",
            "Show - S01E02.mkv",
            status="error",
            matches=[cell("missing"), subtitle],
        ),
    ]
    resolution = BatchResolution(columns=columns, rows=rows)
    lines = matrix_lines(resolution)
    dash = "\N{EN DASH}"
    assert lines == [
        "File    V   A1       S1     Output name",
        "\N{BOX DRAWINGS LIGHT HORIZONTAL}" * len("File    V   A1       S1     Output name"),
        f"E01 ✓   {dash}   ✓ #1            第一話.mkv",
        f"E02 ✗   {dash}   ✗ none   ✓ #3   Show - S01E02.mkv",
    ]
    ascii_lines = matrix_lines(resolution, unicode=False)
    assert ascii_lines[1] == "-" * len(ascii_lines[0])
    assert ascii_lines[3] == "E02 x    -   x none   ok #3   Show - S01E02.mkv"
