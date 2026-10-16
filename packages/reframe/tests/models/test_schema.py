"""C-2 "Done when": a JSON Schema snapshot test exists for all public models.

The snapshots (``__snapshots__/test_schema.ambr``) are the contract with the frontend
(02 §One contract): a change to a model shows up here and must be reviewed. Update them with
``uv run pytest packages/reframe/tests/models/test_schema.py --snapshot-update``.

Each snapshot holds a model's own schema with only the **names** of its ``$defs``: every
definition is a public model or enum with its own snapshot, and
:func:`test_definitions_match_their_own_schema` checks that the inlined definition is the
same. This keeps the snapshot file small without losing anything.
"""

from __future__ import annotations

import enum
import json
import types
import typing
from typing import Any

import pytest
from pydantic import BaseModel, TypeAdapter
from syrupy.assertion import SnapshotAssertion

import reframe.models as models


def _schema_targets() -> list[tuple[str, Any]]:
    targets = []
    for name in models.__all__:
        obj = getattr(models, name)
        is_model = isinstance(obj, type) and issubclass(obj, BaseModel)
        is_enum = isinstance(obj, type) and issubclass(obj, enum.Enum)
        is_alias = typing.get_origin(obj) is not None or isinstance(obj, types.UnionType)
        if is_model or is_enum or is_alias:
            targets.append((name, obj))
    return targets


TARGETS = _schema_targets()


def _schema(obj: Any) -> dict[str, Any]:
    if isinstance(obj, type) and issubclass(obj, BaseModel):
        return obj.model_json_schema()
    schema: dict[str, Any] = TypeAdapter(obj).json_schema()
    return schema


#: ``$defs`` entries that are not public names of ``reframe.models``.
_NON_PUBLIC_DEFS = {"JsonValue"}


@pytest.mark.parametrize(("name", "obj"), TARGETS, ids=[name for name, _ in TARGETS])
def test_json_schema_snapshot(name: str, obj: Any, snapshot: SnapshotAssertion) -> None:
    schema = _schema(obj)
    json.dumps(schema)  # serialisable
    defs = schema.pop("$defs", {})
    assert {**schema, "$defs": sorted(defs)} == snapshot


#: Targets whose schema has ``$defs`` (for the others there is nothing to compare).
WITH_DEFS = [(name, obj) for name, obj in TARGETS if _schema(obj).get("$defs")]


@pytest.mark.parametrize(("name", "obj"), WITH_DEFS, ids=[name for name, _ in WITH_DEFS])
def test_definitions_match_their_own_schema(name: str, obj: Any) -> None:
    public = dict(TARGETS)
    for def_name, definition in _schema(obj)["$defs"].items():
        if def_name in _NON_PUBLIC_DEFS:
            continue
        assert def_name in public, f"{name}: $defs has the non-public {def_name!r}"
        own = _schema(public[def_name])
        own.pop("$defs", None)
        assert definition == own, def_name


def test_document_models_keep_strict_typescript_types() -> None:
    """Document models keep unknown fields, but their schema does not say
    ``additionalProperties: true`` (openapi-typescript would add an index signature)."""
    schema = json.dumps(models.AppSettings.model_json_schema())
    assert "additionalProperties" not in schema
    # Runtime models forbid unknown fields, and say so.
    assert models.ValidationIssue.model_json_schema()["additionalProperties"] is False
