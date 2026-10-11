"""Pydantic models: the only schema of Reframe (02 §One contract)."""

from reframe.models.base import DocumentModel, LanguageTag, Rational, ReframeModel
from reframe.models.issues import (
    AddOp,
    CopyOp,
    Fix,
    FixTarget,
    JsonPatch,
    JsonPatchOp,
    MoveOp,
    RemoveOp,
    ReplaceOp,
    Severity,
    TestOp,
    ValidationIssue,
)
from reframe.models.tools import ToolInfo, ToolName, ToolOrigin, ToolSet, ToolStatus

__all__ = [
    "AddOp",
    "CopyOp",
    "DocumentModel",
    "Fix",
    "FixTarget",
    "JsonPatch",
    "JsonPatchOp",
    "LanguageTag",
    "MoveOp",
    "Rational",
    "ReframeModel",
    "RemoveOp",
    "ReplaceOp",
    "Severity",
    "TestOp",
    "ToolInfo",
    "ToolName",
    "ToolOrigin",
    "ToolSet",
    "ToolStatus",
    "ValidationIssue",
]
