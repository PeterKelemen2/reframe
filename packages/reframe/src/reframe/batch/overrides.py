"""Per-file overrides as JSON patches (04 §Per-file overrides; 05 §C-12, M7).

An override is one RFC 6902 JSON patch per file, against the **per-file document**: the group
template, with one extra member ``job`` that holds the job resolved for that file
(decision 0040):

- ``/audio_rules/1/settings/bitrate``, ``/video/rate_control/value``, … patch the template
  **before** the file is resolved. A later change of the template still reaches every field
  the patch does not touch, and the track rules are resolved again with the patched rules:
  a candidate picked by hand in a matrix cell is ``add /audio_rules/1/selector/stream 5``
  (:attr:`~reframe.models.TrackSelector.stream`), and its codec rules are evaluated for the
  track that was picked.
- ``/job/...`` patches the resolved job **after** the resolution: the fields that are per file
  by nature (04: range, chapter names, a crop of this file) and the parsed-name corrections of
  C-16, ``add /job/output/naming/field_overrides/episode "5"`` (03 §Naming editor).

The template part is applied first, then the job part, each in the patch's order. An
override that no longer applies is an issue, never an exception: an operation whose path
vanished (``batch.override_stale``, a warning) is skipped and the rest is applied; a failed
``test`` operation skips the rest of the override (the override was made for another
template); a ``move`` or ``copy`` between the template and the job, or a result that is not a
valid template or job (``batch.override_invalid``, an error), leaves that part unapplied.

Pure: no I/O.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError

from reframe.jsonpatch import (
    JsonPatchError,
    JsonPatchTestFailed,
    apply_patch,
    parse_pointer,
)
from reframe.models.issues import JsonPatchOp, Severity, ValidationIssue
from reframe.models.job import JobSettings
from reframe.models.template import JobTemplate

__all__ = [
    "JOB_MEMBER",
    "apply_job_override",
    "apply_template_override",
    "split_override",
]

#: The member of the per-file document that holds the resolved job.
JOB_MEMBER = "job"


def _in_job(pointer: str) -> bool:
    try:
        tokens = parse_pointer(pointer)
    except JsonPatchError:
        return False
    return bool(tokens) and tokens[0] == JOB_MEMBER


def _strip(pointer: str) -> str:
    return pointer[len(JOB_MEMBER) + 1 :]


def _dotted(pointer: str) -> str:
    """``/audio_rules/1/settings/bitrate`` → ``audio_rules[1].settings.bitrate``."""
    try:
        tokens = parse_pointer(pointer)
    except JsonPatchError:
        return pointer
    text = ""
    for token in tokens:
        text += f"[{token}]" if token.isdecimal() and token.isascii() else f".{token}"
    return text.lstrip(".")


def _issue(severity: Severity, code: str, pointer: str, message: str) -> ValidationIssue:
    return ValidationIssue(severity=severity, code=code, path=_dotted(pointer), message=message)


def split_override(
    override: Sequence[JsonPatchOp] | None,
) -> tuple[list[JsonPatchOp], list[JsonPatchOp], list[ValidationIssue]]:
    """The template part and the job part (paths without ``/job``) of an override, and an
    issue for every ``move`` / ``copy`` between the two (left out)."""
    template_ops: list[JsonPatchOp] = []
    job_ops: list[JsonPatchOp] = []
    issues: list[ValidationIssue] = []
    for op in override or ():
        target = _in_job(op.path)
        source = getattr(op, "from_", None)
        if source is not None and _in_job(source) != target:
            issues.append(
                _issue(
                    Severity.ERROR,
                    "batch.override_invalid",
                    op.path,
                    f"The override's {op.op} from {source} to {op.path} goes between the "
                    "template and the job: it is not applied.",
                )
            )
            continue
        if not target:
            template_ops.append(op)
            continue
        update: dict[str, Any] = {"path": _strip(op.path)}
        if source is not None:
            update["from_"] = _strip(source)
        job_ops.append(op.model_copy(update=update))
    return template_ops, job_ops, issues


def _apply(
    document: Any, ops: Sequence[JsonPatchOp], *, prefix: str
) -> tuple[Any, list[ValidationIssue], int]:
    """Apply ``ops`` one by one; return the document, the issues and how many applied."""
    issues: list[ValidationIssue] = []
    applied = 0
    for number, op in enumerate(ops):
        shown = prefix + op.path
        try:
            document = apply_patch(document, [op])
        except JsonPatchTestFailed:
            rest = len(ops) - number
            issues.append(
                _issue(
                    Severity.WARNING,
                    "batch.override_stale",
                    shown,
                    f"The override's test at {shown} failed: it was made for another template, "
                    f"so its last {rest} "
                    f"{'operation is' if rest == 1 else 'operations are'} not applied.",
                )
            )
            break
        except JsonPatchError as exc:
            issues.append(
                _issue(
                    Severity.WARNING,
                    "batch.override_stale",
                    shown,
                    f"The override's {op.op} at {shown} no longer applies ({exc}): it is skipped.",
                )
            )
            continue
        applied += 1
    return document, issues, applied


def apply_template_override[T: JobTemplate](
    template: T, ops: Sequence[JsonPatchOp]
) -> tuple[T, list[ValidationIssue]]:
    """``template`` with the template part of an override (see the module doc)."""
    if not ops:
        return template, []
    document, issues, applied = _apply(template.model_dump(mode="json"), ops, prefix="")
    if not applied:
        return template, issues
    try:
        return type(template).model_validate(document), issues
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        return template, [
            *issues,
            _issue(
                Severity.ERROR,
                "batch.override_invalid",
                "/" + where.replace(".", "/"),
                f"The override makes the template invalid ({where}: {first['msg']}): it is not "
                "applied.",
            ),
        ]


def apply_job_override(
    job: JobSettings, ops: Sequence[JsonPatchOp]
) -> tuple[JobSettings, list[ValidationIssue]]:
    """``job`` with the job part of an override (paths without ``/job``; see the module
    doc)."""
    if not ops:
        return job, []
    document, issues, applied = _apply(job.model_dump(mode="json"), ops, prefix="/job")
    if not applied:
        return job, issues
    try:
        return JobSettings.model_validate(document), issues
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        return job, [
            *issues,
            _issue(
                Severity.ERROR,
                "batch.override_invalid",
                "/job/" + where.replace(".", "/"),
                f"The override makes the job invalid ({where}: {first['msg']}): its job part "
                "is not applied.",
            ),
        ]
