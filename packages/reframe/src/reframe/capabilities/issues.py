"""The closest available encoder and the encoder issues of a job or preset (C-4). Pure.

C-8 (validation) registers :func:`encoder_issues` as its encoder rule and adds the quality
conversion of the fix (C-6 ``convert_quality``) and the 10-bit and option checks.

Issue codes (03 §Missing encoder behaviour):

========================  ========  ==========================================================
code                      severity  when
========================  ========  ==========================================================
``encoder.unknown``       error     the id is not in the definitions
``encoder.checking``      info      detection still runs (or has not run) for this encoder
``encoder.untested``      warning   a hardware encoder in the build that was not tested,
                                    because hardware test encodes are off
``encoder.unavailable``   error     ``unavailable`` or ``error``: the reason is in the message;
                                    the fix switches to :func:`closest_available` (video and
                                    audio chains; no fix when nothing is available)
========================  ========  ==========================================================

``encoder.checking`` is ``info``, not an error: 03 says "a preset or job can be edited.
Queueing waits until the encoder's status is known", and an error would block *Add to
queue* (03 §Validation). It is not a warning either, because nothing is wrong yet. The queue
(C-11) waits for ``CapabilityService.wait()`` before it starts a job whose encoder is still
being checked.
"""

from __future__ import annotations

import re

from reframe.definitions import Definitions
from reframe.models.capabilities import CapabilitySnapshot, EncoderState, EncoderStatus
from reframe.models.issues import Fix, FixTarget, ReplaceOp, Severity, ValidationIssue

__all__ = ["closest_available", "encoder_issues", "field_pointer"]

_INDEX = re.compile(r"\[(\d+)\]")


def closest_available(
    encoder_id: str, caps: CapabilitySnapshot, definitions: Definitions
) -> str | None:
    """``encoder_id`` itself when it is available, else the first available encoder of its
    fallback chain in the definitions: video (``hevc_nvenc → hevc_qsv → hevc_amf →
    hevc_vaapi → libx265``) or audio (``libfdk_aac → aac``, decision 0020). ``None`` when
    none is available or the encoder is not in the definitions."""
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
    """``Preset "X" uses hevc_nvenc, which`` or ``hevc_nvenc (NVIDIA NVENC H.265)``."""
    if subject:
        return f"{subject} uses {encoder_id}, which"
    return _label(encoder_id, definitions)


def _unavailable_text(status: EncoderStatus) -> str:
    reason = status.reason or "no reason given"
    if status.state is EncoderState.ERROR:
        return f"could not be checked: {reason}"
    return f"is not available: {reason}"


def encoder_issues(
    encoder_id: str,
    caps: CapabilitySnapshot,
    definitions: Definitions,
    *,
    path: str = "video.encoder",
    target: FixTarget = "job",
    subject: str | None = None,
) -> list[ValidationIssue]:
    """The issues of using ``encoder_id`` now (see the module doc for the codes).

    :param path: the dotted field path of the encoder in the target document; the fix patch
        replaces the same field (``video.encoder`` → ``/video/encoder``).
    :param target: the document the fix patches (``job``; ``template`` for a preset).
    :param subject: names the document in the message, for example ``Preset "H.265 NVENC
        1080p"`` → "Preset "H.265 NVENC 1080p" uses hevc_nvenc, which is not available: …".
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
        fixes.append(
            Fix(
                label=f"Use {closest} (closest match)",
                patch=[ReplaceOp(path=field_pointer(path), value=closest)],
                target=target,
            )
        )
    return [
        ValidationIssue(
            severity=Severity.ERROR,
            code="encoder.unavailable",
            path=path,
            message=f"{who} {_unavailable_text(status)}.",
            fixes=fixes,
        )
    ]
