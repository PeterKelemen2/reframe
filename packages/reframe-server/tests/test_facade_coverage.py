"""Every public member of the facade is reached by a route or listed as not exposed in the plan,
and every route of the OpenAPI document is called by a route test.

Both are read from the source: which facade members a route reaches comes from its handler and
the server code the handler calls; which routes the tests call comes from their client calls.
"""

from __future__ import annotations

import ast
import functools
import importlib
import inspect
import itertools
import pkgutil
import re
import textwrap
import types
import typing
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import APIRoute, APIWebSocketRoute

import reframe_server.routers
from reframe.service import Reframe
from reframe_server.api import operation_id
from reframe_testing.server import ROOT, Api

pytestmark = pytest.mark.anyio

SERVICES = (
    "tools",
    "capabilities",
    "sources",
    "settings",
    "presets",
    "jobs",
    "queue",
    "power",
    "batch",
    "tasks",
    "events",
)
TESTS = Path(__file__).parent
PLAN = ROOT / "docs" / "plan" / "06-web-app.md"
SWEEPS = {"test_facade_coverage.py", "test_jail_sweep.py", "test_openapi.py"}
"""Files that call routes to check them all, not to test each one."""


def public_members(reframe: Reframe) -> set[str]:
    """``Reframe.<name>`` for the facade's own members, ``<service>.<name>`` for the rest."""
    found = {f"Reframe.{name}" for name in dir(reframe) if name[0] != "_" and name not in SERVICES}
    for service in SERVICES:
        found |= {f"{service}.{name}" for name in dir(getattr(reframe, service)) if name[0] != "_"}
    return found


def not_exposed() -> dict[str, str]:
    """The plan's "Not exposed" table: member → reason."""
    text = PLAN.read_text(encoding="utf-8")
    section = text.split("## S-2 REST API", 1)[1].split("\n## ", 1)[0]
    table = section.split("### Not exposed", 1)[1]
    listed: dict[str, str] = {}
    for line in table.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 2 and cells[1] and not set(cells[1]) <= {"-"}:
            for name in re.findall(r"`([A-Za-z]+\.[a-z_]+)`", cells[0]):
                listed[name] = cells[1]
    return listed


def _ours(obj: object) -> bool:
    return getattr(obj, "__module__", "").startswith("reframe_server")


def _class_of(annotation: Any) -> type | None:
    """The class of an annotation: ``Annotated`` and ``X | None`` unwrapped."""
    origin = typing.get_origin(annotation)
    if origin is typing.Annotated:
        return _class_of(typing.get_args(annotation)[0])
    if origin in (typing.Union, types.UnionType):
        args = [arg for arg in typing.get_args(annotation) if arg is not types.NoneType]
        return _class_of(args[0]) if len(args) == 1 else None
    return annotation if isinstance(annotation, type) else None


def _hints(obj: Callable[..., Any] | type) -> dict[str, type]:
    hints = typing.get_type_hints(obj, include_extras=True)
    return {name: cls for name, hint in hints.items() if (cls := _class_of(hint)) is not None}


@functools.cache
def _tree(fn: Callable[..., Any]) -> ast.AST:
    try:
        source = inspect.getsource(fn)
    except OSError:  # generated, such as a dataclass's __init__
        return ast.Module(body=[], type_ignores=[])
    return ast.parse(textwrap.dedent(source))


@functools.cache
def _attribute_classes(cls: type) -> dict[str, type]:
    """The classes of ``cls``'s attributes: its annotations, and ``self.x = param`` in
    ``__init__``."""
    found = _hints(cls)
    init = cls.__dict__.get("__init__")
    if inspect.isfunction(init):
        params = _hints(init)
        for node in ast.walk(_tree(init)):
            if (
                isinstance(node, ast.Assign)
                and isinstance(target := node.targets[0], ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
                and isinstance(node.value, ast.Name)
                and node.value.id in params
            ):
                found[target.attr] = params[node.value.id]
    return found


class Reach:
    """The facade members one function reaches, directly or through the server code it
    calls. A variable's class comes from its annotation (or the variable it was assigned)."""

    def __init__(self, reframe: Reframe) -> None:
        self.services: dict[type, str] = {type(getattr(reframe, s)): s for s in SERVICES}
        self.found: set[str] = set()
        self._seen: set[object] = set()

    def function(self, fn: Callable[..., Any], owner: type | None = None) -> None:
        fn = inspect.unwrap(fn)
        if fn in self._seen or not _ours(fn):
            return
        self._seen.add(fn)
        env: dict[str, type] = _hints(fn)
        if owner is not None:
            env["self"] = owner
        tree = _tree(fn)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.targets[0], ast.Name)
                and (cls := self._resolve(node.value, env, fn)) is not None
            ):
                env[node.targets[0].id] = cls
        for node in ast.walk(tree):
            if isinstance(node, (ast.Attribute, ast.Call)):
                self._resolve(node, env, fn)

    def _class(self, cls: type) -> None:
        for member in list(vars(cls).values()):
            if inspect.isfunction(member):
                self.function(member, cls)

    def _resolve(self, node: ast.AST, env: dict[str, type], fn: Any) -> type | None:
        """The class of the value of ``node``, if known; records the members it reaches."""
        if isinstance(node, ast.Name):
            return env.get(node.id)
        if isinstance(node, ast.Attribute):
            base = self._resolve(node.value, env, fn)
            return None if base is None else self._step(base, node.attr)
        if isinstance(node, ast.Call):
            called = node.func
            if isinstance(called, ast.Name):
                target = inspect.getclosurevars(fn).nonlocals.get(called.id)
                target = target or fn.__globals__.get(called.id)
                if inspect.isfunction(target):
                    self.function(target)
                elif inspect.isclass(target) and _ours(target):
                    self._class(target)
                    return target
            else:
                self._resolve(called, env, fn)
        return None

    def _step(self, base: type, name: str) -> type | None:
        if base is Reframe:
            if name in SERVICES:
                return self._service_class(name)
            self.found.add(f"Reframe.{name}")
            return None
        if base in self.services:
            self.found.add(f"{self.services[base]}.{name}")
            return None
        if not _ours(base):
            return None
        member = inspect.getattr_static(base, name, None)
        if isinstance(member, property) and member.fget is not None:
            self.function(member.fget, base)
        elif inspect.isfunction(member):
            self.function(member, base)
        else:
            return _attribute_classes(base).get(name)
        return None

    def _service_class(self, name: str) -> type:
        return next(cls for cls, service in self.services.items() if service == name)


def routes() -> Iterator[tuple[str, Callable[..., Any]]]:
    """``(operationId, handler)`` of every route of the routers; the WebSocket route by the
    same rule."""
    for info in pkgutil.iter_modules(reframe_server.routers.__path__):
        module = importlib.import_module(f"reframe_server.routers.{info.name}")
        for route in module.router.routes:
            if isinstance(route, APIRoute):
                yield operation_id(route), route.endpoint
            elif isinstance(route, APIWebSocketRoute):
                yield f"{module.router.tags[0]}_{route.name}", route.endpoint


def reached_by_routes(reframe: Reframe, served: set[str]) -> dict[str, set[str]]:
    """Facade member → the operationIds of the served routes that reach it."""
    by_member: dict[str, set[str]] = {}
    for op, handler in routes():
        if op not in served:
            continue
        reach = Reach(reframe)
        reach.function(handler)
        for member in reach.found:
            by_member.setdefault(member, set()).add(op)
    return by_member


def served_operations(document: dict[str, Any]) -> set[str]:
    ops = {op["operationId"] for item in document["paths"].values() for op in item.values()}
    return ops | {"events_stream"}


async def test_every_public_facade_member_is_reached_by_a_route_or_listed_as_not_exposed(
    api: Api,
) -> None:
    document = api.app.openapi()
    reached = reached_by_routes(api.reframe, served_operations(document))
    missing = public_members(api.reframe) - reached.keys() - not_exposed().keys()
    assert sorted(missing) == [], "no route reaches these, and the Not exposed table lacks them"


async def test_the_not_exposed_list_names_public_members_that_no_route_reaches(api: Api) -> None:
    listed = not_exposed()
    assert listed, "the plan has no Not exposed table"
    reached = reached_by_routes(api.reframe, served_operations(api.app.openapi()))
    assert {name: sorted(reached[name]) for name in listed if name in reached} == {}
    assert sorted(listed.keys() - public_members(api.reframe)) == []


HTTP_METHODS = {"get", "post", "put", "delete", "patch"}


def _assignments(nodes: list[ast.stmt] | ast.AST) -> dict[str, ast.expr]:
    found: dict[str, ast.expr] = {}
    for node in nodes if isinstance(nodes, list) else ast.walk(nodes):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found[target.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value:
            found[node.target.id] = node.value
    return found


def _rows(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, module: dict[str, ast.expr]
) -> list[dict[str, ast.expr]]:
    """One binding of argument name → value node per case of the test's ``parametrize``."""
    tables: list[list[dict[str, ast.expr]]] = []
    for decorator in fn.decorator_list:
        if not (
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr == "parametrize"
            and len(decorator.args) >= 2
        ):
            continue
        names_node, values = decorator.args[:2]
        if isinstance(names_node, ast.Constant):
            names = [name.strip() for name in str(names_node.value).split(",")]
        else:
            elts = getattr(names_node, "elts", [])
            names = [str(elt.value) for elt in elts if isinstance(elt, ast.Constant)]
        if isinstance(values, ast.Name):
            values = module.get(values.id, values)
        table = []
        for row in getattr(values, "elts", []):
            if isinstance(row, ast.Call) and getattr(row.func, "attr", "") == "param":
                row = row.args[0] if len(names) == 1 else ast.Tuple(elts=row.args)
            items = [row] if len(names) == 1 else getattr(row, "elts", [])
            table.append(dict(zip(names, items, strict=False)))
        tables.append(table)
    return [
        {name: value for row in rows for name, value in row.items()}
        for rows in itertools.product(*tables)
    ]


def _text(node: ast.AST | None, names: dict[str, ast.expr], depth: int = 0) -> str | None:
    """A sample of the string ``node`` makes: an unknown part of an f-string is ``X``."""
    if node is None or depth > 8:
        return None
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.Name):
        return _text(names.get(node.id), names, depth + 1)
    if isinstance(node, ast.JoinedStr):
        parts = [
            str(value.value)
            if isinstance(value, ast.Constant)
            else _text(getattr(value, "value", None), names, depth + 1) or "X"
            for value in node.values
        ]
        return "".join(parts)
    if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "format":
        base = _text(node.func.value, names, depth + 1)  # type: ignore[attr-defined]
        return None if base is None else re.sub(r"\{[^}]*\}", "X", base)
    return None


def called_routes(file: Path) -> set[tuple[str, str]]:
    """``(method, url)`` of each client call in a test file, with sample values for the parts
    the source does not show."""
    tree = ast.parse(file.read_text(encoding="utf-8"))
    module = _assignments(tree.body)
    calls: set[tuple[str, str]] = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        local = module | _assignments(fn)
        for row in _rows(fn, module) or [{}]:
            names = local | row
            for node in ast.walk(fn):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                    continue
                if node.func.attr in HTTP_METHODS and node.args:
                    method, url = node.func.attr, _text(node.args[0], names)
                elif node.func.attr == "request" and len(node.args) >= 2:
                    method = (_text(node.args[0], names) or "").lower()
                    url = _text(node.args[1], names)
                else:
                    continue
                if url is not None and url.startswith("/api/"):
                    calls.add((method, url.partition("?")[0]))
    return calls


def _template(path: str) -> re.Pattern[str]:
    parts = re.split(r"(\{[^}]+\})", path)
    return re.compile("".join("[^/]+" if p.startswith("{") else re.escape(p) for p in parts))


async def test_every_route_is_called_by_a_route_test(api: Api) -> None:
    calls = {
        call
        for file in sorted(TESTS.glob("test_*.py"))
        if file.name not in SWEEPS
        for call in called_routes(file)
    }
    document = api.app.openapi()
    uncalled = [
        operation["operationId"]
        for path, item in document["paths"].items()
        for method, operation in item.items()
        if not any(verb == method and _template(path).fullmatch(url) for verb, url in calls)
    ]
    assert uncalled == []
