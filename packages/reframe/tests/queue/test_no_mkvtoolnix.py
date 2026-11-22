"""No product code starts an MKVToolNix program: the Matroska header writer is Reframe's own.

Two guards: a scan of the product source for the program names in string constants (outside
docstrings), and runs of an in-place edit and of an encode with the ``LanguageIETF`` fix-up
that record every process the queue starts.
"""

from __future__ import annotations

import ast
import asyncio
import itertools
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from reframe.metadata import remux_job
from reframe.models import JobSettings, JobState, SourceRef
from reframe.queue import runner

from .conftest import Harness

ROOT = Path(__file__).resolve().parents[4]
SOURCES = (ROOT / "packages" / "reframe" / "src", ROOT / "packages" / "reframe-server" / "src")
PROGRAMS = frozenset({"mkvpropedit", "mkvmerge", "mkvinfo", "mkvextract"})
_WORD = re.compile(r"[A-Za-z0-9_.-]+")

#: Constants that name a program and start nothing.
ALLOWED = {
    # The settings migration removes the old ``tools.mkvpropedit`` path.
    ("reframe/models/migrations.py", "mkvpropedit"),
}


def _docstrings(tree: ast.AST) -> set[int]:
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                found.add(id(body[0].value))
    for node in ast.walk(tree):  # attribute docstrings: a string statement after an assignment
        for field in ("body", "orelse", "finalbody"):
            statements = getattr(node, field, None)
            if not isinstance(statements, list):
                continue
            for before, statement in itertools.pairwise(statements):
                if (
                    isinstance(before, ast.Assign | ast.AnnAssign)
                    and isinstance(statement, ast.Expr)
                    and isinstance(statement.value, ast.Constant)
                    and isinstance(statement.value.value, str)
                ):
                    found.add(id(statement.value))
    return found


def program_names(source: str) -> Iterator[tuple[int, str]]:
    """``(line, constant)`` of each string constant outside docstrings that names an MKVToolNix
    program as a word (``mkvpropedit``, ``/usr/bin/mkvmerge``, ``mkvinfo.exe``)."""
    tree = ast.parse(source)
    docstrings = _docstrings(tree)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            for word in _WORD.findall(node.value.replace("\\", "/")):
                name = word.lower().rsplit("/", 1)[-1].removesuffix(".exe")
                if name in PROGRAMS:
                    yield node.lineno, node.value
                    break


def product_modules() -> Iterator[tuple[str, Path]]:
    for src in SOURCES:
        for path in sorted(src.rglob("*.py")):
            yield path.relative_to(src).as_posix(), path


def test_no_product_module_names_an_mkvtoolnix_program() -> None:
    found = [
        f"{name}:{line}: {text!r}"
        for name, path in product_modules()
        for line, text in program_names(path.read_text(encoding="utf-8"))
        if (name, text) not in ALLOWED
    ]
    assert found == []


def test_the_scan_finds_a_program_in_code_but_not_in_a_docstring() -> None:
    code = '''
"""Runs mkvpropedit."""
X = 1
"""mkvmerge is described here."""
def f():
    """mkvinfo in a docstring."""
    run(["mkvpropedit", path])
    tools.get("mkvmerge")
    run([r"C:\\Program Files\\MKVToolNix\\mkvinfo.exe"])
    text = f"{tool} or mkvextract"
    ok = "mkvpropeditor mkvmerged"
'''
    assert sorted(line for line, _ in program_names(code)) == [7, 8, 9, 10]


def test_the_scan_sees_every_product_package() -> None:
    names = [name for name, _ in product_modules()]
    assert "reframe/queue/runner.py" in names
    assert "reframe_server/app.py" in names


class Spawned:
    """Every process the queue starts, by program name; the real start still happens."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.programs: list[str] = []
        real = asyncio.create_subprocess_exec

        async def spawn(program: str, *args: Any, **kwargs: Any) -> Any:
            self.programs.append(Path(program).name)
            return await real(program, *args, **kwargs)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)


@pytest.mark.anyio
async def test_an_in_place_edit_starts_no_process(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness
    spawned = Spawned(monkeypatch)
    monkeypatch.setattr(runner, "_in_place_refusal", lambda plan, source, probed: None)
    job = remux_job(JobSettings(source=SourceRef(path=h.source_path)), h.sources.source)
    job.audio[0].metadata.language = "pt-BR"
    job.output.edit_in_place = True
    ended = await h.run_one(job)
    assert [edit.path for edit in h.writer.edits] == [h.source_path]
    assert ended.state is not JobState.WAITING
    assert spawned.programs == []


@pytest.mark.anyio
async def test_an_encode_with_the_fixup_starts_only_ffmpeg(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness
    spawned = Spawned(monkeypatch)
    job = h.job()
    job.audio[1].metadata.language = "pt-BR"
    await h.run_one(job)
    assert [edit.path for edit in h.writer.edits] == [h.plan(job).output_tmp]
    assert spawned.programs == [h.fake.ffmpeg.name]  # the encode
