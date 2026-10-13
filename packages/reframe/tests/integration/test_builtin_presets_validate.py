"""M2 cross-step check (lead): every built-in preset (C-9) passes C-8's template validation
on a machine where every encoder of the definitions (C-6) is available (C-4)."""

from __future__ import annotations

import pytest

from reframe.definitions import load_definitions
from reframe.models import CapabilitySnapshot, EncoderState, EncoderStatus, Preset, Severity
from reframe.presets import builtin_presets
from reframe.validation import validate_template


def _everything_available() -> CapabilitySnapshot:
    defs = load_definitions()
    ids = [*defs.video_encoders, *defs.audio_encoders]
    return CapabilitySnapshot(
        encoders={
            encoder_id: EncoderStatus(
                id=encoder_id, state=EncoderState.AVAILABLE, in_build=True, supports_10bit=True
            )
            for encoder_id in ids
        },
        filters=None,
    )


@pytest.mark.parametrize("preset", builtin_presets(), ids=lambda p: p.id)
def test_builtin_preset_has_no_validation_errors(preset: Preset) -> None:
    issues = validate_template(preset, _everything_available(), subject=preset.name)
    errors = [issue for issue in issues if issue.severity is Severity.ERROR]
    assert errors == []
