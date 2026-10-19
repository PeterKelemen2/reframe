"""RFC 6902 JSON Patch and RFC 6901 JSON Pointer, in plain Python (no dependency).

Errors raise :class:`JsonPatchError` (or a subclass): a patch that does not apply is a
programming error in the caller or a conflict that the caller reports.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import BaseModel

__all__ = [
    "JsonPatchConflict",
    "JsonPatchError",
    "JsonPatchTestFailed",
    "JsonPointerError",
    "apply_patch",
    "escape_token",
    "format_pointer",
    "json_equal",
    "parse_pointer",
    "resolve_pointer",
]

_INDEX_RE = re.compile(r"^(0|[1-9][0-9]*)$")
_BAD_ESCAPE_RE = re.compile(r"~(?![01])")


class JsonPatchError(ValueError):
    """A patch is malformed or cannot be applied."""


class JsonPointerError(JsonPatchError):
    """A JSON Pointer is malformed (RFC 6901)."""


class JsonPatchConflict(JsonPatchError):
    """The target location does not exist, or an index is out of range."""


class JsonPatchTestFailed(JsonPatchError):
    """A ``test`` operation found a different value."""


def escape_token(token: str) -> str:
    """Escape one reference token: ``~`` → ``~0``, ``/`` → ``~1``."""
    return token.replace("~", "~0").replace("/", "~1")


def format_pointer(tokens: Iterable[str | int]) -> str:
    """Build a pointer from tokens, escaping each one."""
    return "".join("/" + escape_token(str(t)) for t in tokens)


def parse_pointer(pointer: str) -> list[str]:
    """Split a pointer into unescaped tokens."""
    if not isinstance(pointer, str):
        raise JsonPointerError(f"a JSON Pointer must be a string, got {pointer!r}")
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise JsonPointerError(f"a JSON Pointer must be empty or start with '/': {pointer!r}")
    tokens = pointer[1:].split("/")
    for token in tokens:
        if _BAD_ESCAPE_RE.search(token):
            raise JsonPointerError(f"invalid escape in JSON Pointer {pointer!r}")
    # ~1 first, then ~0: "~01" is "~1" (RFC 6901 §4).
    return [t.replace("~1", "/").replace("~0", "~") for t in tokens]


def _index(token: str, size: int, *, allow_end: bool, pointer: str) -> int:
    if token == "-":
        if allow_end:
            return size
        raise JsonPatchConflict(f"'-' (the end of the array) cannot be used here: {pointer!r}")
    if not _INDEX_RE.match(token):
        raise JsonPatchConflict(f"{token!r} is not an array index in {pointer!r}")
    index = int(token)
    limit = size if allow_end else size - 1
    if index > limit:
        raise JsonPatchConflict(f"index {index} is out of range in {pointer!r}")
    return index


def _child(container: Any, token: str, pointer: str) -> Any:
    if isinstance(container, dict):
        if token not in container:
            raise JsonPatchConflict(f"no member {token!r} at {pointer!r}")
        return container[token]
    if isinstance(container, list):
        return container[_index(token, len(container), allow_end=False, pointer=pointer)]
    raise JsonPatchConflict(f"{pointer!r} goes through a value that is not an object or array")


def resolve_pointer(document: Any, pointer: str) -> Any:
    """The value at ``pointer`` (raises :class:`JsonPatchConflict` if it does not exist)."""
    value = document
    for token in parse_pointer(pointer):
        value = _child(value, token, pointer)
    return value


def _parent(document: Any, pointer: str) -> tuple[Any, str]:
    tokens = parse_pointer(pointer)
    parent = document
    for token in tokens[:-1]:
        parent = _child(parent, token, pointer)
    return parent, tokens[-1]


def json_equal(a: Any, b: Any) -> bool:
    """Equality with JSON semantics (RFC 6902 §4.6).

    ``1`` equals ``1.0``, but ``true`` does not equal ``1``.
    """
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(json_equal(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(json_equal(a[k], b[k]) for k in a)
    return False


def _add(document: Any, pointer: str, value: Any) -> Any:
    if pointer == "":
        return value
    parent, token = _parent(document, pointer)
    if isinstance(parent, dict):
        parent[token] = value
    elif isinstance(parent, list):
        parent.insert(_index(token, len(parent), allow_end=True, pointer=pointer), value)
    else:
        raise JsonPatchConflict(f"the parent of {pointer!r} is not an object or array")
    return document


def _remove(document: Any, pointer: str) -> tuple[Any, Any]:
    """Remove the value at ``pointer``; return ``(document, removed value)``."""
    if pointer == "":
        raise JsonPatchConflict("the whole document cannot be removed")
    parent, token = _parent(document, pointer)
    if isinstance(parent, dict):
        if token not in parent:
            raise JsonPatchConflict(f"no member {token!r} at {pointer!r}")
        return document, parent.pop(token)
    if isinstance(parent, list):
        return document, parent.pop(_index(token, len(parent), allow_end=False, pointer=pointer))
    raise JsonPatchConflict(f"the parent of {pointer!r} is not an object or array")


def _replace(document: Any, pointer: str, value: Any) -> Any:
    if pointer == "":
        return value
    parent, token = _parent(document, pointer)
    if isinstance(parent, dict):
        if token not in parent:
            raise JsonPatchConflict(f"no member {token!r} at {pointer!r}")
        parent[token] = value
    elif isinstance(parent, list):
        parent[_index(token, len(parent), allow_end=False, pointer=pointer)] = value
    else:
        raise JsonPatchConflict(f"the parent of {pointer!r} is not an object or array")
    return document


def _member(op: Mapping[str, Any], name: str, number: int) -> Any:
    if name not in op:
        raise JsonPatchError(f"operation {number} ({op.get('op')!r}) has no {name!r} member")
    return op[name]


def _pointer_member(op: Mapping[str, Any], name: str, number: int) -> str:
    value = _member(op, name, number)
    if not isinstance(value, str):
        raise JsonPointerError(f"operation {number}: {name!r} must be a string")
    parse_pointer(value)
    return value


def _apply_one(document: Any, op: Mapping[str, Any], number: int) -> Any:
    kind = _member(op, "op", number)
    path = _pointer_member(op, "path", number)
    if kind == "add":
        return _add(document, path, copy.deepcopy(_member(op, "value", number)))
    if kind == "remove":
        return _remove(document, path)[0]
    if kind == "replace":
        return _replace(document, path, copy.deepcopy(_member(op, "value", number)))
    if kind == "move":
        source = _pointer_member(op, "from", number)
        if source == path:
            resolve_pointer(document, source)  # it must exist
            return document
        if path.startswith(source + "/") or source == "":
            raise JsonPatchConflict(f"cannot move {source!r} into its own child {path!r}")
        document, value = _remove(document, source)
        return _add(document, path, value)
    if kind == "copy":
        source = _pointer_member(op, "from", number)
        value = copy.deepcopy(resolve_pointer(document, source))
        return _add(document, path, value)
    if kind == "test":
        expected = _member(op, "value", number)
        actual = resolve_pointer(document, path)
        if not json_equal(actual, expected):
            raise JsonPatchTestFailed(f"test failed at {path!r}: {actual!r} != {expected!r}")
        return document
    raise JsonPatchError(f"operation {number}: unknown op {kind!r}")


def _as_mapping(op: Any, number: int) -> Mapping[str, Any]:
    if isinstance(op, BaseModel):
        dumped: dict[str, Any] = op.model_dump(mode="json", by_alias=True)
        return dumped
    if isinstance(op, Mapping):
        return op
    raise JsonPatchError(f"operation {number} is not an object: {op!r}")


def apply_patch(document: Any, patch: Iterable[Mapping[str, Any] | BaseModel]) -> Any:
    """Apply an RFC 6902 patch to a JSON-like value; return the patched **copy**.

    The input is never changed, also when an operation fails. Unknown members of an operation
    are ignored (RFC 6902 §4). ``patch`` items may be dicts or
    :class:`reframe.models.JsonPatchOp` models. The document
    must be made of ``dict``, ``list``, ``str``, ``int``, ``float``, ``bool`` and ``None``
    (``model.model_dump(mode="json")`` gives that).
    """
    if isinstance(patch, (str, bytes, Mapping)):
        raise JsonPatchError("a JSON patch is a list of operations")
    result = copy.deepcopy(document)
    for number, op in enumerate(patch):
        result = _apply_one(result, _as_mapping(op, number), number)
    return result
