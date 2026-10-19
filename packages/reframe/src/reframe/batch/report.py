"""The match report as plain text: the matrix of ``reframe batch``, one row per file and one
column per track rule. Tracks are named by their absolute stream index, not by their position
among the tracks of one kind.

Pure: no I/O.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence

from reframe.batch.grouping import episode_labels
from reframe.batch.selectors import RELAX_WORDS
from reframe.models.batch import BatchResolution, Resolution, TrackMatch
from reframe.naming.sanitize import replace_undecodable

__all__ = [
    "CELL_ASCII",
    "CELL_MARKS",
    "ROW_ASCII",
    "ROW_MARKS",
    "match_cell",
    "matrix_lines",
    "name_cell",
    "video_cell",
]

#: A matrix cell's mark.
CELL_MARKS = {
    "exact": "✓",
    "relaxed": "≈",
    "ambiguous": "≈",
    "missing": "✗",
    "skipped": "\N{EN DASH}",
}
CELL_ASCII = {"exact": "ok", "relaxed": "~", "ambiguous": "~", "missing": "x", "skipped": "-"}
#: A row's mark (``Resolution.status``).
ROW_MARKS = {"ok": "✓", "warning": "⚠", "error": "✗"}
ROW_ASCII = {"ok": "ok", "warning": "!", "error": "x"}
_NONE = "—"


def match_cell(match: TrackMatch, *, unicode: bool = True) -> str:
    """One matrix cell: the mark, the streams, and the note for a relaxed or ambiguous match."""
    mark = (CELL_MARKS if unicode else CELL_ASCII)[match.status]
    streams = " ".join(f"#{index}" for index in match.streams)
    match match.status:
        case "exact":
            return f"{mark} {streams}"
        case "relaxed":
            return f"{mark} {streams} ({', '.join(RELAX_WORDS[f] for f in match.relaxed)})"
        case "ambiguous":
            return f"{mark} {streams} ({len(match.candidates)} candidates)"
        case "missing":
            return f"{mark} none"
        case _:
            return f"{mark} skipped"


def video_cell(row: Resolution, *, unicode: bool = True) -> str:
    """The output size as a cell, ``✓ 1080p``, from the ``resolution`` naming variable."""
    marks = CELL_MARKS if unicode else CELL_ASCII
    if row.job is None:
        return marks["missing"]
    size = row.naming.variables.get("resolution", "") if row.naming is not None else ""
    return f"{marks['exact']} {size}" if size else marks["skipped"]


def name_cell(row: Resolution) -> str:
    """The output name: the template's relative path (subfolders too), or only the file name
    when the output was renamed away from the template."""
    if row.job is None or row.job.output.path is None:
        return _NONE
    path = row.job.output.path
    if row.naming is not None and path.as_posix().endswith("/" + row.naming.relative_path):
        return replace_undecodable(row.naming.relative_path)
    return replace_undecodable(path.name)


def _width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in text)


def matrix_lines(resolution: BatchResolution, *, unicode: bool = True) -> list[str]:
    """The resolution matrix as text lines, one per file under a header and a rule. A cell is in
    the column of its rule, explicit or compiled from the defaults. ``unicode=False`` gives ASCII
    marks for a console that cannot print them."""
    rules = [c for c in resolution.columns if c.kind in ("audio", "subtitle")]
    header = ["File", "V", *(c.label.partition(" ")[0] for c in rules), "Output name"]
    marks = ROW_MARKS if unicode else ROW_ASCII
    table: list[Sequence[str]] = [header]
    labels = episode_labels([row.path for row in resolution.rows])
    for row, label in zip(resolution.rows, labels, strict=True):
        cells: dict[tuple[str, bool, int], str] = {
            (m.kind, m.defaults, m.rule): match_cell(m, unicode=unicode) for m in row.matches
        }
        table.append(
            [
                replace_undecodable(f"{label} {marks[row.status]}"),
                video_cell(row, unicode=unicode),
                *(
                    cells.get((c.kind, c.defaults, c.rule if c.rule is not None else -1), "")
                    for c in rules
                ),
                name_cell(row),
            ]
        )
    widths = [max(_width(line[i]) for line in table) for i in range(len(header))]

    def join(cells: Sequence[str]) -> str:
        padded = [cell + " " * (widths[i] - _width(cell)) for i, cell in enumerate(cells)]
        return "   ".join(padded).rstrip()

    rule = ("\N{BOX DRAWINGS LIGHT HORIZONTAL}" if unicode else "-") * _width(join(header))
    return [join(header), rule, *(join(line) for line in table[1:])]
