"""Small helpers shared by the rules: issues, fixes, JSON patch operations, labels."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import JsonValue

from reframe.capabilities import field_pointer
from reframe.definitions import CodecSupport, ContainerDef, Definitions
from reframe.models.capabilities import CapabilitySnapshot, EncoderState
from reframe.models.issues import (
    AddOp,
    Fix,
    FixTarget,
    JsonPatchOp,
    RemoveOp,
    ReplaceOp,
    Severity,
    ValidationIssue,
)
from reframe.models.job import Container

__all__ = [
    "DEFAULT_AUDIO_ENCODER",
    "TrackKind",
    "add",
    "containers_for",
    "error",
    "fix",
    "info",
    "remove",
    "replace",
    "support",
    "switch_container_fixes",
    "usable_encoder",
    "warning",
]

#: The audio encoder used when a job track names none (``AudioOutputTrack.encoder`` ``None``
#: means "the preset's fallback encoder", whose default is ``aac``: ``PassthruPolicy``).
DEFAULT_AUDIO_ENCODER = "aac"


def _issue(
    severity: Severity, code: str, path: str, message: str, fixes: Sequence[Fix]
) -> ValidationIssue:
    return ValidationIssue(
        severity=severity, code=code, path=path, message=message, fixes=list(fixes)
    )


def error(code: str, path: str, message: str, *fixes: Fix) -> ValidationIssue:
    return _issue(Severity.ERROR, code, path, message, fixes)


def warning(code: str, path: str, message: str, *fixes: Fix) -> ValidationIssue:
    return _issue(Severity.WARNING, code, path, message, fixes)


def info(code: str, path: str, message: str, *fixes: Fix) -> ValidationIssue:
    return _issue(Severity.INFO, code, path, message, fixes)


def fix(label: str, *ops: JsonPatchOp, target: FixTarget = "job") -> Fix:
    return Fix(label=label, patch=list(ops), target=target)


def replace(path: str, value: JsonValue) -> ReplaceOp:
    """``replace`` at the dotted field ``path`` (``audio[2].encoder``)."""
    return ReplaceOp(path=field_pointer(path), value=value)


def add(path: str, value: JsonValue) -> AddOp:
    return AddOp(path=field_pointer(path), value=value)


def remove(path: str) -> RemoveOp:
    return RemoveOp(path=field_pointer(path))


def switch_container_fixes(
    allowed: Sequence[Container],
    current: Container,
    definitions: Definitions,
    *,
    target: FixTarget = "job",
) -> list[Fix]:
    """ "Switch to MKV" fixes for the containers in ``allowed`` (other than ``current``)."""
    fixes: list[Fix] = []
    for container_id, container in definitions.containers.items():
        if container_id != current and container_id in allowed:
            fixes.append(
                fix(
                    f"Switch to {container.label}",
                    replace("output.container", container_id),
                    target=target,
                )
            )
    return fixes


def usable_encoder(encoder_id: str, caps: CapabilitySnapshot) -> bool:
    """An encoder a fix may switch to: available, or (while detection has not finished) not
    known to be unavailable."""
    state = caps.status(encoder_id).state
    return state not in (EncoderState.UNAVAILABLE, EncoderState.ERROR)


TrackKind = Literal["video", "audio", "subtitles"]


def support(container: ContainerDef, kind: TrackKind) -> CodecSupport:
    if kind == "video":
        return container.video
    if kind == "audio":
        return container.audio
    return container.subtitles


def containers_for(
    definitions: Definitions, kind: TrackKind, codec: str, *, copy: bool = False
) -> list[Container]:
    """The containers that can encode (or, with ``copy``, stream-copy) ``codec`` for a track
    ``kind``."""
    found: list[Container] = []
    for container_id, container in definitions.containers.items():
        codecs = support(container, kind)
        if codecs.can_copy(codec) if copy else codec in codecs.encode:
            found.append(container_id)
    return found
