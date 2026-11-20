"""The closest available encoder and the encoder issues of a job or preset. Pure.

``encoder.checking`` is ``info``, not an error: an error would stop a job from being queued
while its encoder is still being checked, and nothing is wrong yet.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from reframe.definitions import Definitions
from reframe.models.capabilities import CapabilitySnapshot, EncoderState, EncoderStatus
from reframe.models.issues import (
    Fix,
    FixTarget,
    JsonPatchOp,
    ReplaceOp,
    Severity,
    ValidationIssue,
)

__all__ = ["closest_available", "encoder_issues", "field_pointer"]

_INDEX = re.compile(r"\[(\d+)\]")


def closest_available(
    encoder_id: str, caps: CapabilitySnapshot, definitions: Definitions
) -> str | None:
    """``encoder_id`` itself when it is available, else the first available encoder of its
    fallback chain in the definitions (video or audio). ``None`` when none is available or
    the encoder is not in the definitions."""
    if caps.status(encoder_id).state is EncoderState.AVAILABLE:
        return encoder_id
    video = definitions.video_encoders.get(encoder_id)
    audio = definitions.audio_encoders.get(encoder_id)
    chain = video.fallback if video is not None else audio.fallback if audio is not None else []
    for candidate in chain:
        if caps.status(candidate).state is EncoderState.AVAILABLE:
            return candidate
    return None


def field_pointer(path: str) -> str:
    """The JSON Pointer of a dotted field path: ``video.encoder`` → ``/video/encoder``,
    ``audio[2].encoder`` → ``/audio/2/encoder`` (the third audio track of a job)."""
    parts = _INDEX.sub(r".\1", path).split(".")
    escaped = (part.replace("~", "~0").replace("/", "~1") for part in parts if part)
    return "".join(f"/{part}" for part in escaped)


def _known(encoder_id: str, definitions: Definitions) -> bool:
    return encoder_id in definitions.video_encoders or encoder_id in definitions.audio_encoders


def _label(encoder_id: str, definitions: Definitions) -> str:
    video = definitions.video_encoders.get(encoder_id)
    if video is not None:
        return f"{encoder_id} ({video.label})"
    audio = definitions.audio_encoders.get(encoder_id)
    return f"{encoder_id} ({audio.label})" if audio is not None else encoder_id


def _uses(subject: str | None, encoder_id: str, definitions: Definitions) -> str:
    """``<subject> uses <id>, which``, or else ``<id> (<label>)``."""
    if subject:
        return f"{subject} uses {encoder_id}, which"
    return _label(encoder_id, definitions)


def _unavailable_text(status: EncoderStatus) -> str:
    reason = status.reason or "no reason given"
    if status.state is EncoderState.ERROR:
        return f"could not be checked: {reason}"
    if status.build_mismatch:
        return (
            f"is not available: {reason}. Another FFmpeg build may work with this computer "
            "(Settings → Tools, or reframe tools fetch --build)"
        )
    return f"is not available: {reason}"


def encoder_issues(
    encoder_id: str,
    caps: CapabilitySnapshot,
    definitions: Definitions,
    *,
    path: str = "video.encoder",
    target: FixTarget = "job",
    subject: str | None = None,
    fix_ops: Callable[[str], tuple[list[JsonPatchOp], str | None]] | None = None,
) -> list[ValidationIssue]:
    """The issues of using ``encoder_id`` now.

    :param path: the dotted field path of the encoder in the target document; the fix patch
        replaces the same field (``video.encoder`` → ``/video/encoder``).
    :param target: the document the fix patches (``job``; ``template`` for a preset).
    :param subject: the document that uses the encoder, named in the message
        (``Preset "X" uses …``).
    :param fix_ops: the patch and a note for switching to the closest encoder; ``None``
        replaces only the encoder field.
    """
    if not _known(encoder_id, definitions):
        message = f"Unknown encoder {encoder_id!r}: Reframe has no definition for it."
        if subject:
            message = f"{subject} uses the unknown encoder {encoder_id!r}."
        return [
            ValidationIssue(
                severity=Severity.ERROR, code="encoder.unknown", path=path, message=message
            )
        ]
    status = caps.status(encoder_id)
    state = status.state
    who = _uses(subject, encoder_id, definitions)
    if state is EncoderState.AVAILABLE:
        return []
    # A cached failure may be stale: the GPU fingerprint does not see user-space drivers
    # (AMF runtime, Mesa, oneVPL). While detection runs again, the job waits for the result.
    if caps.from_cache and caps.detecting and state is not EncoderState.CHECKING:
        last = f"{state.value}, {status.reason}" if status.reason else state.value
        message = (
            f"{who} is being checked again (last result: {last}). The job waits for the "
            "result before it starts."
        )
        return [
            ValidationIssue(
                severity=Severity.INFO, code="encoder.checking", path=path, message=message
            )
        ]
    if state is EncoderState.CHECKING or (state is EncoderState.UNKNOWN and not status.in_build):
        message = f"{who} is still being checked. The job waits for the result before it starts."
        return [
            ValidationIssue(
                severity=Severity.INFO, code="encoder.checking", path=path, message=message
            )
        ]
    if state is EncoderState.UNKNOWN:
        reason = status.reason or "it was not tested"
        message = (
            f"{who} was not tested ({reason}). The encode fails if this computer cannot use it."
        )
        return [
            ValidationIssue(
                severity=Severity.WARNING, code="encoder.untested", path=path, message=message
            )
        ]
    fixes: list[Fix] = []
    closest = closest_available(encoder_id, caps, definitions)
    if closest is not None and closest != encoder_id:
        if fix_ops is not None:
            ops, note = fix_ops(closest)
        else:
            ops, note = [ReplaceOp(path=field_pointer(path), value=closest)], None
        detail = "closest match" + (f"; {note}" if note else "")
        fixes.append(Fix(label=f"Use {closest} ({detail})", patch=ops, target=target))
    return [
        ValidationIssue(
            severity=Severity.ERROR,
            code="encoder.unavailable",
            path=path,
            message=f"{who} {_unavailable_text(status)}.",
            fixes=fixes,
        )
    ]
