"""Check that only comments and docstrings changed in the Python files that git reports.

Each changed file is compared with its version at ``--base`` (default ``HEAD``: uncommitted
work; ``--base main`` checks a branch). The check fails when the syntax tree differs once
docstrings and other no-op statements (bare strings, ``...``, ``pass``) are removed, or when a
pragma (``noqa``, ``type: ignore``, ``pragma: no cover``, ``fmt: skip``) moved to another line.
It lists the changed docstrings that the program can read at run time: class and field
docstrings (Pydantic schema descriptions), docstrings of decorated functions (typer and FastAPI
help), and the module docstring of a file that uses ``__doc__``.

Exit status: 0 when only comments and docstrings changed, 1 when more changed, 2 on a git error.
"""

from __future__ import annotations

import argparse
import ast
import io
import re
import subprocess
import sys
import tokenize
from pathlib import Path

PRAGMA = re.compile(
    r"\b(?:noqa(?::\s*[A-Z]+[0-9]+(?:\s*,\s*[A-Z]+[0-9]+)*)?"
    r"|type:\s*ignore(?:\[[^\]]*\])?"
    r"|pragma:\s*no\s+(?:cover|branch)"
    r"|fmt:\s*(?:off|on|skip)"
    r"|(?:pyright|mypy|isort|ruff):\s*[\w\-=,\[\]]+)"
)

type Scope = ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, encoding="utf-8", check=True).stdout


def is_noop(node: ast.AST) -> bool:
    if isinstance(node, ast.Pass):
        return True
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and (isinstance(node.value.value, str) or node.value.value is Ellipsis)
    )


def strip(tree: ast.Module) -> ast.Module:
    """``tree`` without no-op statements (changes ``tree``)."""
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if isinstance(block, list):
                setattr(node, field, [stmt for stmt in block if not is_noop(stmt)])
    return tree


def shape(node: ast.AST) -> list[object]:
    """The node's own fields, with child nodes reduced to their type and lists to their length."""
    result: list[object] = [type(node).__name__]
    for _, value in ast.iter_fields(node):
        if isinstance(value, ast.AST):
            result.append(type(value).__name__)
        elif isinstance(value, list):
            result.append(len(value))
        else:
            result.append(value)
    return result


def first_difference(old: ast.Module, new: ast.Module) -> int | None:
    """The line in ``new`` of the first node that differs from ``old``, if it has a line."""
    for old_node, new_node in zip(ast.walk(old), ast.walk(new), strict=False):
        if shape(old_node) != shape(new_node):
            return getattr(new_node, "lineno", None)
    return None


def docstrings(tree: ast.Module, uses_doc: bool) -> dict[str, tuple[str, bool]]:
    """Each docstring by its qualified name → (text, whether the program can read it)."""
    found: dict[str, tuple[str, bool]] = {}

    def add(name: str, text: str, runtime: bool) -> None:
        key, count = name, 1
        while key in found:
            count += 1
            key = f"{name}#{count}"
        found[key] = (text, runtime)

    def record(scope: Scope, name: str) -> None:
        if isinstance(scope, ast.Module):
            runtime = uses_doc
        elif isinstance(scope, ast.ClassDef):
            runtime = True
        else:
            runtime = bool(scope.decorator_list)
        text = ast.get_docstring(scope, clean=False)
        if text is not None:
            add(name, text, runtime)
        if isinstance(scope, ast.ClassDef):
            for previous, stmt in zip(scope.body, scope.body[1:], strict=False):
                if (
                    isinstance(previous, ast.AnnAssign | ast.Assign)
                    and isinstance(stmt, ast.Expr)
                    and isinstance(stmt.value, ast.Constant)
                    and isinstance(stmt.value.value, str)
                ):
                    target = (
                        previous.target
                        if isinstance(previous, ast.AnnAssign)
                        else previous.targets[0]
                    )
                    add(f"{name}.{ast.unparse(target)}", stmt.value.value, True)

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                name = f"{prefix}.{child.name}" if prefix else child.name
                record(child, name)
                visit(child, name)
            else:
                visit(child, prefix)

    record(tree, "<module>")
    visit(tree, "")
    return found


def pragmas(source: str) -> list[tuple[str, list[str]]]:
    """(the code on the line, its pragmas) for each comment that holds a pragma, in order."""
    lines = source.splitlines()
    result: list[tuple[str, list[str]]] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT and (found := PRAGMA.findall(token.string)):
            row, column = token.start
            result.append((lines[row - 1][:column].strip(), found))
    return result


def compare(path: str, old: str, new: str) -> tuple[list[str], list[str], int]:
    """(problems, changed runtime docstrings, number of changed docstrings) for one file."""
    try:
        old_tree, new_tree = ast.parse(old, path), ast.parse(new, path)
    except SyntaxError as error:
        return [f"{path}: {error.msg} (line {error.lineno})"], [], 0
    uses_doc = "__doc__" in old or "__doc__" in new
    old_docs, new_docs = docstrings(old_tree, uses_doc), docstrings(new_tree, uses_doc)
    changed = sorted(
        name
        for name in old_docs.keys() | new_docs.keys()
        if old_docs.get(name, (None,))[0] != new_docs.get(name, (None,))[0]
    )
    runtime = [
        name
        for name in changed
        if old_docs.get(name, ("", False))[1] or new_docs.get(name, ("", False))[1]
    ]
    problems: list[str] = []
    old_tree, new_tree = strip(old_tree), strip(new_tree)
    if ast.dump(old_tree) != ast.dump(new_tree):
        line = first_difference(old_tree, new_tree)
        problems.append(f"{path}: code changed" + (f" near line {line}" if line else ""))
    if pragmas(old) != pragmas(new):
        problems.append(f"{path}: a pragma comment changed or moved to another line")
    return problems, runtime, len(changed)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check that only comments and docstrings changed.")
    parser.add_argument("--base", default="HEAD", help="git revision to compare with (HEAD)")
    parser.add_argument("paths", nargs="*", help="check only these paths")
    args = parser.parse_args()
    try:
        root = Path(git("rev-parse", "--show-toplevel").strip())
        status = git("diff", "--name-status", "--no-renames", args.base, "--", *args.paths)
        problems: list[str] = []
        runtime: list[str] = []
        not_python: list[str] = []
        files = docs = 0
        for line in status.splitlines():
            kind, path = line.split("\t", 1)
            if not path.endswith(".py"):
                not_python.append(path)
            elif kind != "M":
                problems.append(f"{path}: git status {kind}, not a modified file")
            else:
                old = git("show", f"{args.base}:{path}")
                new = (root / path).read_text(encoding="utf-8")
                found, names, changed = compare(path, old, new)
                problems += found
                runtime += [f"{path}: {', '.join(names)}"] if names else []
                files, docs = files + 1, docs + changed
    except subprocess.CalledProcessError as error:
        print(error.stderr.strip(), file=sys.stderr)
        return 2
    print(f"{files} Python file(s) compared with {args.base}, {docs} docstring(s) changed.")
    for title, items in (
        ("More than comments and docstrings changed:", problems),
        ("Docstrings that the program reads changed (run their tests):", runtime),
        ("Not checked (not Python):", not_python),
    ):
        if items:
            print(title, *(f"  {item}" for item in items), sep="\n")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
