"""Count the lines of Python in packages/, per package, source and tests apart, as a table.

A line is blank, a comment (a ``#`` line or a line inside a string statement, which covers
docstrings and attribute docstrings) or code. A file counts as a test when a ``tests``
directory is on its path inside the package. ``__pycache__`` and hidden directories are skipped.
"""

from __future__ import annotations

import ast
import os
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = ROOT / "packages"

HEADERS = ("Package", "Kind", "Files", "Code", "Comments", "Blank", "Total", "% group", "% all")
LEFT_ALIGNED = 2


@dataclass
class Counts:
    files: int = 0
    code: int = 0
    comments: int = 0
    blank: int = 0

    @property
    def total(self) -> int:
        return self.code + self.comments + self.blank

    def add(self, other: Counts) -> None:
        self.files += other.files
        self.code += other.code
        self.comments += other.comments
        self.blank += other.blank


def python_files(root: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__" and not d.startswith("."))
        for name in sorted(filenames):
            if name.endswith(".py"):
                yield Path(dirpath, name)


def string_statement_lines(source: str) -> set[int]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    lines: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            lines.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    return lines


def count_file(path: Path) -> Counts:
    source = path.read_text(encoding="utf-8", errors="replace")
    # Not splitlines(): ast numbers lines by \n only, and the two must agree.
    lines = source.split("\n")
    if lines[-1] == "":
        lines.pop()
    in_string = string_statement_lines(source)
    counts = Counts(files=1)
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            counts.blank += 1
        elif number in in_string or stripped.startswith("#"):
            counts.comments += 1
        else:
            counts.code += 1
    return counts


def count_package(package: Path) -> tuple[Counts, Counts]:
    source, tests = Counts(), Counts()
    for path in python_files(package):
        is_test = "tests" in path.relative_to(package).parts[:-1]
        (tests if is_test else source).add(count_file(path))
    return source, tests


def percent(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f}%" if whole else "0.0%"


def group_rows(label: str, source: Counts, tests: Counts, grand_code: int) -> list[tuple[str, ...]]:
    subtotal = Counts()
    subtotal.add(source)
    subtotal.add(tests)
    rows: list[tuple[str, ...]] = []
    for kind, counts in (("source", source), ("tests", tests), ("total", subtotal)):
        rows.append(
            (
                label if not rows else "",
                kind,
                str(counts.files),
                str(counts.code),
                str(counts.comments),
                str(counts.blank),
                str(counts.total),
                percent(counts.code, subtotal.code),
                percent(counts.code, grand_code),
            )
        )
    return rows


def render(groups: list[list[tuple[str, ...]]]) -> str:
    widths = [
        max(len(row[i]) for row in [HEADERS, *(r for g in groups for r in g)])
        for i in range(len(HEADERS))
    ]
    border = "+" + "+".join("-" * (w + 2) for w in widths) + "+"

    def line(row: tuple[str, ...]) -> str:
        cells = [
            cell.ljust(w) if i < LEFT_ALIGNED else cell.rjust(w)
            for i, (cell, w) in enumerate(zip(row, widths, strict=True))
        ]
        return "| " + " | ".join(cells) + " |"

    out = [border, line(HEADERS), border]
    for group in groups:
        out.extend(line(row) for row in group)
        out.append(border)
    return "\n".join(out)


def main() -> int:
    if not PACKAGES.is_dir():
        sys.stderr.write(f"no such directory: {PACKAGES}\n")
        return 1

    per_package = {
        package.name: count_package(package)
        for package in sorted(PACKAGES.iterdir())
        if package.is_dir() and not package.name.startswith(".")
    }
    all_source, all_tests = Counts(), Counts()
    for source, tests in per_package.values():
        all_source.add(source)
        all_tests.add(tests)
    grand_code = all_source.code + all_tests.code

    groups = [group_rows(name, s, t, grand_code) for name, (s, t) in per_package.items()]
    groups.append(group_rows("all packages", all_source, all_tests, grand_code))

    sys.stdout.write(render(groups) + "\n")
    sys.stdout.write(
        "Comments include docstrings. Percentages are shares of code lines: '% group' of the\n"
        "package (or of all packages), '% all' of all packages.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
