"""reframe.jsonpatch against the examples of RFC 6902 (Appendix A) and RFC 6901 (§5)."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from reframe.jsonpatch import (
    JsonPatchConflict,
    JsonPatchError,
    JsonPatchTestFailed,
    JsonPointerError,
    apply_patch,
    escape_token,
    format_pointer,
    json_equal,
    parse_pointer,
    resolve_pointer,
)
from reframe.models import AddOp, CopyOp, MoveOp, RemoveOp, ReplaceOp, TestOp

# --------------------------------------------------------------------------- RFC 6902 Appendix A

RFC6902_OK: list[tuple[str, Any, list[dict[str, Any]], Any]] = [
    (
        "A.1 adding an object member",
        {"foo": "bar"},
        [{"op": "add", "path": "/baz", "value": "qux"}],
        {"baz": "qux", "foo": "bar"},
    ),
    (
        "A.2 adding an array element",
        {"foo": ["bar", "baz"]},
        [{"op": "add", "path": "/foo/1", "value": "qux"}],
        {"foo": ["bar", "qux", "baz"]},
    ),
    (
        "A.3 removing an object member",
        {"baz": "qux", "foo": "bar"},
        [{"op": "remove", "path": "/baz"}],
        {"foo": "bar"},
    ),
    (
        "A.4 removing an array element",
        {"foo": ["bar", "qux", "baz"]},
        [{"op": "remove", "path": "/foo/1"}],
        {"foo": ["bar", "baz"]},
    ),
    (
        "A.5 replacing a value",
        {"baz": "qux", "foo": "bar"},
        [{"op": "replace", "path": "/baz", "value": "boo"}],
        {"baz": "boo", "foo": "bar"},
    ),
    (
        "A.6 moving a value",
        {"foo": {"bar": "baz", "waldo": "fred"}, "qux": {"corge": "grault"}},
        [{"op": "move", "from": "/foo/waldo", "path": "/qux/thud"}],
        {"foo": {"bar": "baz"}, "qux": {"corge": "grault", "thud": "fred"}},
    ),
    (
        "A.7 moving an array element",
        {"foo": ["all", "grass", "cows", "eat"]},
        [{"op": "move", "from": "/foo/1", "path": "/foo/3"}],
        {"foo": ["all", "cows", "eat", "grass"]},
    ),
    (
        "A.8 testing a value: success",
        {"baz": "qux", "foo": ["a", 2, "c"]},
        [
            {"op": "test", "path": "/baz", "value": "qux"},
            {"op": "test", "path": "/foo/1", "value": 2},
        ],
        {"baz": "qux", "foo": ["a", 2, "c"]},
    ),
    (
        "A.10 adding a nested member object",
        {"foo": "bar"},
        [{"op": "add", "path": "/child", "value": {"grandchild": {}}}],
        {"foo": "bar", "child": {"grandchild": {}}},
    ),
    (
        "A.11 ignoring unrecognized elements",
        {"foo": "bar"},
        [{"op": "add", "path": "/baz", "value": "qux", "xyz": 123}],
        {"foo": "bar", "baz": "qux"},
    ),
    (
        "A.14 ~ escape ordering",
        {"/": 9, "~1": 10},
        [{"op": "test", "path": "/~01", "value": 10}],
        {"/": 9, "~1": 10},
    ),
    (
        "A.16 adding an array value",
        {"foo": ["bar"]},
        [{"op": "add", "path": "/foo/-", "value": ["abc", "def"]}],
        {"foo": ["bar", ["abc", "def"]]},
    ),
]

RFC6902_ERRORS: list[tuple[str, Any, list[dict[str, Any]], type[Exception]]] = [
    (
        "A.9 testing a value: error",
        {"baz": "qux"},
        [{"op": "test", "path": "/baz", "value": "bar"}],
        JsonPatchTestFailed,
    ),
    (
        "A.12 adding to a nonexistent target",
        {"foo": "bar"},
        [{"op": "add", "path": "/baz/bat", "value": "qux"}],
        JsonPatchConflict,
    ),
    (
        "A.15 comparing strings and numbers",
        {"/": 9, "~1": 10},
        [{"op": "test", "path": "/~01", "value": "10"}],
        JsonPatchTestFailed,
    ),
]


@pytest.mark.parametrize(
    ("name", "doc", "patch", "expected"), RFC6902_OK, ids=[c[0] for c in RFC6902_OK]
)
def test_rfc6902_examples(name: str, doc: Any, patch: list[dict[str, Any]], expected: Any) -> None:
    original = copy.deepcopy(doc)
    assert apply_patch(doc, patch) == expected
    assert doc == original  # the input is never changed


@pytest.mark.parametrize(
    ("name", "doc", "patch", "error"), RFC6902_ERRORS, ids=[c[0] for c in RFC6902_ERRORS]
)
def test_rfc6902_error_examples(
    name: str, doc: Any, patch: list[dict[str, Any]], error: type[Exception]
) -> None:
    with pytest.raises(error):
        apply_patch(doc, patch)


def test_a13_duplicate_members_parse_to_the_last_value() -> None:
    """A.13 (an invalid patch document with two "op" members) is a JSON parsing matter. Python's
    json keeps the last member, so it becomes "remove /baz", which fails on this document."""
    patch = json.loads('[{"op": "add", "path": "/baz", "value": "qux", "op": "remove"}]')
    with pytest.raises(JsonPatchConflict):
        apply_patch({"foo": "bar"}, patch)


# --------------------------------------------------------------------------- RFC 6901 §5

POINTER_DOC: dict[str, Any] = {
    "foo": ["bar", "baz"],
    "": 0,
    "a/b": 1,
    "c%d": 2,
    "e^f": 3,
    "g|h": 4,
    "i\\j": 5,
    'k"l': 6,
    " ": 7,
    "m~n": 8,
}


@pytest.mark.parametrize(
    ("pointer", "expected"),
    [
        ("", POINTER_DOC),
        ("/foo", ["bar", "baz"]),
        ("/foo/0", "bar"),
        ("/", 0),
        ("/a~1b", 1),
        ("/c%d", 2),
        ("/e^f", 3),
        ("/g|h", 4),
        ("/i\\j", 5),
        ('/k"l', 6),
        ("/ ", 7),
        ("/m~0n", 8),
    ],
)
def test_rfc6901_examples(pointer: str, expected: Any) -> None:
    assert resolve_pointer(POINTER_DOC, pointer) == expected


@pytest.mark.parametrize("pointer", ["foo", "/~2", "/a~", "/~a"])
def test_invalid_pointers(pointer: str) -> None:
    with pytest.raises(JsonPointerError):
        parse_pointer(pointer)


def test_pointer_helpers() -> None:
    assert parse_pointer("/a~1b/~0c/0") == ["a/b", "~c", "0"]
    assert escape_token("a/b~c") == "a~1b~0c"
    assert format_pointer(["audio", 2, "metadata", "a/b"]) == "/audio/2/metadata/a~1b"
    assert parse_pointer(format_pointer(["~1", "/"])) == ["~1", "/"]
    with pytest.raises(JsonPointerError):
        parse_pointer(5)  # type: ignore[arg-type]


@settings(max_examples=200)
@given(st.lists(st.text(max_size=6), max_size=5))
def test_format_and_parse_are_inverse(tokens: list[str]) -> None:
    assert parse_pointer(format_pointer(tokens)) == tokens


# --------------------------------------------------------------------------- more cases


@pytest.mark.parametrize(
    ("doc", "patch", "expected"),
    [
        ({"a": 1}, [{"op": "add", "path": "", "value": [1]}], [1]),
        ({"a": 1}, [{"op": "replace", "path": "", "value": {"b": 2}}], {"b": 2}),
        ({"a": [1, 2]}, [{"op": "add", "path": "/a/2", "value": 3}], {"a": [1, 2, 3]}),
        ({"a": [1, 2]}, [{"op": "add", "path": "/a/0", "value": 0}], {"a": [0, 1, 2]}),
        ({"a": {"b": 1}}, [{"op": "add", "path": "/a/b", "value": 2}], {"a": {"b": 2}}),
        ({"a": [1, 2]}, [{"op": "replace", "path": "/a/1", "value": 9}], {"a": [1, 9]}),
        ({"a": 1}, [{"op": "copy", "from": "/a", "path": "/b"}], {"a": 1, "b": 1}),
        ({"a": [1]}, [{"op": "copy", "from": "/a", "path": "/a/-"}], {"a": [1, [1]]}),
        ({"a": 1}, [{"op": "copy", "from": "", "path": "/b"}], {"a": 1, "b": {"a": 1}}),
        ({"a": 1}, [{"op": "move", "from": "/a", "path": "/a"}], {"a": 1}),
        ({"a": {"b": 1}}, [{"op": "move", "from": "/a/b", "path": ""}], 1),
        ({"a": [1, 2, 3]}, [{"op": "move", "from": "/a/0", "path": "/a/-"}], {"a": [2, 3, 1]}),
        ({"a": None}, [{"op": "test", "path": "/a", "value": None}], {"a": None}),
        ({"a": 1}, [{"op": "test", "path": "/a", "value": 1.0}], {"a": 1}),
        (
            {"a": {"x": [1, {"y": True}]}},
            [{"op": "test", "path": "/a", "value": {"x": [1, {"y": True}]}}],
            {"a": {"x": [1, {"y": True}]}},
        ),
        ({"a": 1}, [], {"a": 1}),
    ],
)
def test_more_operations(doc: Any, patch: list[dict[str, Any]], expected: Any) -> None:
    assert apply_patch(doc, patch) == expected


@pytest.mark.parametrize(
    ("doc", "patch", "error"),
    [
        ({"a": [1]}, [{"op": "add", "path": "/a/2", "value": 1}], JsonPatchConflict),
        ({"a": [1]}, [{"op": "add", "path": "/a/01", "value": 1}], JsonPatchConflict),
        ({"a": [1]}, [{"op": "add", "path": "/a/x", "value": 1}], JsonPatchConflict),
        ({"a": [1]}, [{"op": "remove", "path": "/a/-"}], JsonPatchConflict),
        ({"a": [1]}, [{"op": "remove", "path": "/a/1"}], JsonPatchConflict),
        ({"a": [1]}, [{"op": "replace", "path": "/a/5", "value": 1}], JsonPatchConflict),
        ({"a": 1}, [{"op": "remove", "path": "/b"}], JsonPatchConflict),
        ({"a": 1}, [{"op": "remove", "path": ""}], JsonPatchConflict),
        ({"a": 1}, [{"op": "replace", "path": "/b", "value": 1}], JsonPatchConflict),
        ({"a": 1}, [{"op": "add", "path": "/a/b", "value": 1}], JsonPatchConflict),
        ({"a": 1}, [{"op": "replace", "path": "/a/b", "value": 1}], JsonPatchConflict),
        ({"a": 1}, [{"op": "remove", "path": "/a/b"}], JsonPatchConflict),
        ({"a": "s"}, [{"op": "test", "path": "/a/0", "value": "s"}], JsonPatchConflict),
        ({"a": {"b": 1}}, [{"op": "move", "from": "/a", "path": "/a/b"}], JsonPatchConflict),
        ({"a": {"b": 1}}, [{"op": "move", "from": "", "path": "/c"}], JsonPatchConflict),
        ({"a": 1}, [{"op": "move", "from": "/x", "path": "/a"}], JsonPatchConflict),
        ({"a": 1}, [{"op": "move", "from": "/x", "path": "/x"}], JsonPatchConflict),
        ({"a": 1}, [{"op": "copy", "from": "/x", "path": "/b"}], JsonPatchConflict),
        ({"a": True}, [{"op": "test", "path": "/a", "value": 1}], JsonPatchTestFailed),
        ({"a": 1}, [{"op": "test", "path": "/a", "value": True}], JsonPatchTestFailed),
        ({"a": [1, 2]}, [{"op": "test", "path": "/a", "value": [2, 1]}], JsonPatchTestFailed),
        ({"a": {}}, [{"op": "test", "path": "/a", "value": {"b": None}}], JsonPatchTestFailed),
        ({"a": 1}, [{"op": "jump", "path": "/a"}], JsonPatchError),
        ({"a": 1}, [{"path": "/a"}], JsonPatchError),
        ({"a": 1}, [{"op": "add", "path": "/b"}], JsonPatchError),
        ({"a": 1}, [{"op": "move", "path": "/b"}], JsonPatchError),
        ({"a": 1}, [{"op": "add", "path": "b", "value": 1}], JsonPointerError),
        ({"a": 1}, [{"op": "add", "path": 3, "value": 1}], JsonPointerError),
        ({"a": 1}, ["not an op"], JsonPatchError),
    ],
)
def test_errors(doc: Any, patch: list[Any], error: type[Exception]) -> None:
    with pytest.raises(error):
        apply_patch(doc, patch)


def test_patch_must_be_a_list() -> None:
    not_a_list: Any = {"op": "remove", "path": "/a"}
    with pytest.raises(JsonPatchError):
        apply_patch({}, not_a_list)


def test_a_failing_patch_changes_nothing() -> None:
    doc = {"a": [1, 2], "b": {"c": 1}}
    original = copy.deepcopy(doc)
    with pytest.raises(JsonPatchTestFailed):
        apply_patch(
            doc,
            [
                {"op": "remove", "path": "/a/0"},
                {"op": "add", "path": "/b/d", "value": 2},
                {"op": "test", "path": "/b/c", "value": 99},
            ],
        )
    assert doc == original


def test_added_values_are_copies() -> None:
    value = {"x": [1]}
    result = apply_patch({}, [{"op": "add", "path": "/v", "value": value}])
    result["v"]["x"].append(2)
    assert value == {"x": [1]}


def test_model_operations() -> None:
    doc = {"tools": {"ffmpeg": "/x/ffmpeg", "ffprobe": None}, "list": [1]}
    patch = [
        TestOp(path="/tools/ffmpeg", value="/x/ffmpeg"),
        RemoveOp(path="/tools/ffmpeg"),
        AddOp(path="/list/-", value=2),
        ReplaceOp(path="/list/0", value=0),
        CopyOp(from_="/list", path="/copy"),
        MoveOp.model_validate({"op": "move", "from": "/copy", "path": "/moved"}),
    ]
    assert apply_patch(doc, patch) == {"tools": {"ffprobe": None}, "list": [0, 2], "moved": [0, 2]}


def test_json_equal() -> None:
    assert json_equal(1, 1.0)
    assert not json_equal(True, 1)
    assert not json_equal(0, False)
    assert json_equal(None, None)
    assert not json_equal(None, 0)
    assert not json_equal("1", 1)
    assert json_equal({"a": [1, {"b": None}]}, {"a": [1.0, {"b": None}]})
    assert not json_equal({"a": 1}, {"a": 1, "b": 2})
    assert not json_equal([1], (1,))
