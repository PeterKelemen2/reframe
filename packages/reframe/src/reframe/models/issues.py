"""Validation issues and their fixes.

A fix is an RFC 6902 JSON patch. The client applies it to the document named by
:attr:`Fix.target` (usually the ``JobSettings`` being edited) and validates again.
:func:`reframe.jsonpatch.apply_patch` applies the same patches in Python.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, JsonValue

from reframe.models.base import ReframeModel

__all__ = [
    "AddOp",
    "CopyOp",
    "Fix",
    "FixTarget",
    "JsonPatch",
    "JsonPatchOp",
    "MoveOp",
    "RemoveOp",
    "ReplaceOp",
    "Severity",
    "TestOp",
    "ValidationIssue",
]

#: A JSON Pointer (RFC 6901): ``""`` (the whole document) or ``/a/b/0``. A reference token
#: may hold any character, a newline too (``[\s\S]``, not ``.``).
JsonPointer = Annotated[str, Field(pattern=r"^(/[\s\S]*)?$")]


class AddOp(ReframeModel):
    """RFC 6902 ``add``."""

    op: Literal["add"] = "add"
    path: JsonPointer
    value: JsonValue


class RemoveOp(ReframeModel):
    """RFC 6902 ``remove``."""

    op: Literal["remove"] = "remove"
    path: JsonPointer


class ReplaceOp(ReframeModel):
    """RFC 6902 ``replace``."""

    op: Literal["replace"] = "replace"
    path: JsonPointer
    value: JsonValue


class MoveOp(ReframeModel):
    """RFC 6902 ``move``. ``from_`` is ``"from"`` in JSON."""

    op: Literal["move"] = "move"
    from_: JsonPointer = Field(alias="from")
    path: JsonPointer


class CopyOp(ReframeModel):
    """RFC 6902 ``copy``. ``from_`` is ``"from"`` in JSON."""

    op: Literal["copy"] = "copy"
    from_: JsonPointer = Field(alias="from")
    path: JsonPointer


class TestOp(ReframeModel):
    """RFC 6902 ``test``."""

    __test__ = False  # not a pytest test class

    op: Literal["test"] = "test"
    path: JsonPointer
    value: JsonValue


#: One RFC 6902 operation, discriminated by ``op``.
JsonPatchOp = Annotated[
    AddOp | RemoveOp | ReplaceOp | MoveOp | CopyOp | TestOp, Field(discriminator="op")
]
#: An RFC 6902 JSON patch: operations applied in order, all or nothing.
JsonPatch = list[JsonPatchOp]


class Severity(StrEnum):
    """``error`` blocks *Add to queue*; ``warning`` and ``info`` do not."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


#: The document a fix patches. ``job``: the ``JobSettings`` being edited (the default).
#: ``template``: a ``JobTemplate`` / preset. ``settings``: ``AppSettings`` (for example the
#: "Use bundled FFmpeg" fix of a broken tool path).
FixTarget = Literal["job", "template", "settings"]


class Fix(ReframeModel):
    """A fix action: a button label and the JSON patch that the button applies."""

    label: str
    patch: JsonPatch
    target: FixTarget = "job"


class ValidationIssue(ReframeModel):
    """One problem found by validation (or by tool discovery and probing).

    ``code`` is a stable dotted identifier (``encoder.unavailable``,
    ``container.codec_unsupported``, ``tool.missing``). ``path`` is the dotted field path in the
    target document (``video.encoder``, ``audio[2].encoder``); empty when the issue is not about
    one field.
    """

    severity: Severity
    code: Annotated[str, Field(min_length=1)]
    path: str = ""
    message: str
    fixes: list[Fix] = Field(default_factory=list)
