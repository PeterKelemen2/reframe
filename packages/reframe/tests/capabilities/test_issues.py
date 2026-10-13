"""``closest_available`` and ``encoder_issues`` (pure), and the third "Done when" of 05 §C-4:
a preset that references a removed encoder gives ``encoder.unavailable`` with a fix to the
closest available encoder."""

from __future__ import annotations

import pytest

from reframe.capabilities import closest_available, encoder_issues, field_pointer
from reframe.definitions import load_definitions
from reframe.jsonpatch import apply_patch
from reframe.models import (
    CapabilitySnapshot,
    EncoderState,
    EncoderStatus,
    JobSettings,
    Preset,
    ReplaceOp,
    Severity,
)

DEFS = load_definitions()
AVAILABLE = EncoderState.AVAILABLE
UNAVAILABLE = EncoderState.UNAVAILABLE


def caps(**states: EncoderState | tuple[EncoderState, str]) -> CapabilitySnapshot:
    """Every encoder of the definitions available, except the given ones."""
    encoders = {}
    for encoder_id in [*DEFS.video_encoders, *DEFS.audio_encoders]:
        value = states.get(encoder_id, AVAILABLE)
        state, reason = value if isinstance(value, tuple) else (value, None)
        encoders[encoder_id] = EncoderStatus(
            id=encoder_id, state=state, reason=reason, in_build=state is not EncoderState.UNKNOWN
        )
    return CapabilitySnapshot(encoders=encoders)


NO_HEVC_HARDWARE = {
    "hevc_nvenc": (UNAVAILABLE, "NVIDIA driver not found"),
    "hevc_qsv": (UNAVAILABLE, "No Intel QSV device"),
    "hevc_amf": (UNAVAILABLE, "AMD AMF runtime not found (libamfrt64.so.1)"),
    "hevc_vaapi": (EncoderState.ERROR, "The test encode did not finish within 10 s"),
}


def test_closest_available_walks_the_fallback_chain() -> None:
    assert closest_available("hevc_nvenc", caps(), DEFS) == "hevc_nvenc"  # itself
    assert closest_available("hevc_nvenc", caps(hevc_nvenc=UNAVAILABLE), DEFS) == "hevc_qsv"
    two = caps(hevc_nvenc=UNAVAILABLE, hevc_qsv=UNAVAILABLE)
    assert closest_available("hevc_nvenc", two, DEFS) == "hevc_amf"
    assert closest_available("hevc_nvenc", caps(**NO_HEVC_HARDWARE), DEFS) == "libx265"
    checking = caps(hevc_nvenc=UNAVAILABLE, hevc_qsv=EncoderState.CHECKING)
    assert closest_available("hevc_nvenc", checking, DEFS) == "hevc_amf"  # only "available"
    assert closest_available("av1_qsv", caps(av1_qsv=UNAVAILABLE), DEFS) == "av1_nvenc"


def test_closest_available_none() -> None:
    nothing = caps(**NO_HEVC_HARDWARE, libx265=UNAVAILABLE)
    assert closest_available("hevc_nvenc", nothing, DEFS) is None
    assert closest_available("libx265", caps(libx265=UNAVAILABLE), DEFS) is None  # no chain
    assert closest_available("reframe_nonexistent", caps(), DEFS) is None
    no_aac = caps(libfdk_aac=UNAVAILABLE, aac=UNAVAILABLE)
    assert closest_available("libfdk_aac", no_aac, DEFS) is None
    assert closest_available("aac", caps(aac=UNAVAILABLE), DEFS) is None  # no chain


def test_closest_available_audio() -> None:
    """Decision 0020: audio encoders have a fallback chain too (``libfdk_aac → aac``)."""
    assert DEFS.audio_encoders["libfdk_aac"].fallback == ["aac"]
    assert closest_available("libfdk_aac", caps(libfdk_aac=UNAVAILABLE), DEFS) == "aac"
    assert closest_available("libfdk_aac", caps(), DEFS) == "libfdk_aac"


def test_every_chain_ends_in_software() -> None:
    for encoder in DEFS.video_encoders.values():
        if encoder.hardware:
            hardware = {e.id: UNAVAILABLE for e in DEFS.video_encoders.values() if e.hardware}
            closest = closest_available(encoder.id, caps(**hardware), DEFS)
            assert closest is not None
            assert not DEFS.video_encoders[closest].hardware
            assert DEFS.video_encoders[closest].codec == encoder.codec


def test_every_audio_chain_ends_in_a_gpl_encoder() -> None:
    for encoder in DEFS.audio_encoders.values():
        if not encoder.fallback:
            continue
        gone = {e.id: UNAVAILABLE for e in DEFS.audio_encoders.values() if not e.in_gpl_builds}
        closest = closest_available(encoder.id, caps(**gone), DEFS)
        assert closest is not None, encoder.id
        assert DEFS.audio_encoders[closest].in_gpl_builds
        assert DEFS.audio_encoders[closest].codec == encoder.codec


def test_field_pointer() -> None:
    assert field_pointer("video.encoder") == "/video/encoder"
    assert field_pointer("audio[2].encoder") == "/audio/2/encoder"
    assert field_pointer("audio.tracks[2].encoder") == "/audio/tracks/2/encoder"
    assert field_pointer("a/b.c~d") == "/a~1b/c~0d"


def test_available_has_no_issue() -> None:
    assert encoder_issues("libx265", caps(), DEFS) == []


def test_unknown_encoder() -> None:
    (issue,) = encoder_issues("reframe_nonexistent", caps(), DEFS)
    assert (issue.code, issue.severity, issue.path) == (
        "encoder.unknown",
        Severity.ERROR,
        "video.encoder",
    )
    assert (
        issue.message == "Unknown encoder 'reframe_nonexistent': Reframe has no definition for it."
    )
    assert issue.fixes == []
    (named,) = encoder_issues("x", caps(), DEFS, subject='Preset "Old"')
    assert named.message == "Preset \"Old\" uses the unknown encoder 'x'."


def test_checking_is_info() -> None:
    """03: "A preset or job can be edited. Queueing waits until the encoder's status is
    known": an error would block Add to queue, so ``info``."""
    for snapshot in (caps(hevc_amf=EncoderState.CHECKING), CapabilitySnapshot(detecting=True)):
        (issue,) = encoder_issues("hevc_amf", snapshot, DEFS)
        assert (issue.code, issue.severity) == ("encoder.checking", Severity.INFO)
        assert issue.message == (
            "hevc_amf (AMD AMF H.265) is still being checked. The job waits for the result "
            "before it starts."
        )
        assert issue.fixes == []


def test_untested_is_a_warning() -> None:
    snapshot = caps(hevc_amf=(EncoderState.UNKNOWN, "Not tested: hardware test encodes are off"))
    snapshot.encoders["hevc_amf"].in_build = True
    (issue,) = encoder_issues("hevc_amf", snapshot, DEFS)
    assert (issue.code, issue.severity) == ("encoder.untested", Severity.WARNING)
    assert "hardware test encodes are off" in issue.message


def test_unavailable_with_a_fix() -> None:
    (issue,) = encoder_issues("hevc_nvenc", caps(**NO_HEVC_HARDWARE), DEFS)
    assert (issue.code, issue.severity, issue.path) == (
        "encoder.unavailable",
        Severity.ERROR,
        "video.encoder",
    )
    assert (
        issue.message
        == "hevc_nvenc (NVIDIA NVENC H.265) is not available: NVIDIA driver not found."
    )
    (fix,) = issue.fixes
    assert fix.label == "Use libx265 (closest match)"
    assert fix.patch == [ReplaceOp(path="/video/encoder", value="libx265")]
    assert fix.target == "job"


def test_error_state_is_unavailable_too() -> None:
    (issue,) = encoder_issues("hevc_vaapi", caps(**NO_HEVC_HARDWARE), DEFS)
    assert issue.code == "encoder.unavailable"
    assert issue.message == (
        "hevc_vaapi (VAAPI H.265) could not be checked: The test encode did not finish within 10 s."
    )
    assert issue.fixes[0].label == "Use libx265 (closest match)"


def test_unavailable_without_anything_available() -> None:
    (issue,) = encoder_issues("hevc_nvenc", caps(**NO_HEVC_HARDWARE, libx265=UNAVAILABLE), DEFS)
    assert issue.code == "encoder.unavailable"
    assert issue.fixes == []


def test_audio_encoder_unavailable_with_a_fix() -> None:
    snapshot = caps(libfdk_aac=(UNAVAILABLE, "Not in this FFmpeg build"))
    (issue,) = encoder_issues("libfdk_aac", snapshot, DEFS, path="audio[1].encoder")
    assert (issue.code, issue.severity, issue.path) == (
        "encoder.unavailable",
        Severity.ERROR,
        "audio[1].encoder",
    )
    assert issue.message == "libfdk_aac (AAC (FDK)) is not available: Not in this FFmpeg build."
    (fix,) = issue.fixes
    assert fix.label == "Use aac (closest match)"
    assert fix.patch == [ReplaceOp(path="/audio/1/encoder", value="aac")]
    assert fix.target == "job"


def test_audio_encoder_without_anything_available() -> None:
    snapshot = caps(libfdk_aac=UNAVAILABLE, aac=UNAVAILABLE)
    (issue,) = encoder_issues("libfdk_aac", snapshot, DEFS, path="audio[0].encoder")
    assert issue.code == "encoder.unavailable"
    assert issue.fixes == []


def test_job_with_a_libfdk_aac_track() -> None:
    """Decision 0020: a job whose second audio track uses libfdk_aac (not in GPL builds)."""
    job = JobSettings.model_validate(
        {
            "source": {"path": "/media/a.mkv"},
            "audio": [
                {"source_stream": 1, "encoder": "ac3", "bitrate": 448},
                {"source_stream": 2, "encoder": "libfdk_aac", "bitrate": 160},
            ],
        }
    )
    snapshot = caps(libfdk_aac=(UNAVAILABLE, "Not in this FFmpeg build"))
    issues = [
        issue
        for index, track in enumerate(job.audio)
        if track.encoder is not None
        for issue in encoder_issues(track.encoder, snapshot, DEFS, path=f"audio[{index}].encoder")
    ]
    (issue,) = issues
    assert issue.path == "audio[1].encoder"
    (fix,) = issue.fixes
    assert fix.label == "Use aac (closest match)"
    fixed = JobSettings.model_validate(apply_patch(job.model_dump(mode="json"), fix.patch))
    assert [track.encoder for track in fixed.audio] == ["ac3", "aac"]
    assert fixed.audio[1].bitrate == 160  # only the encoder changes
    assert fixed.audio[1].source_stream == 2
    assert all(
        encoder_issues(track.encoder, snapshot, DEFS) == []
        for track in fixed.audio
        if track.encoder is not None
    )


def test_job_fix_applies() -> None:
    job = JobSettings.model_validate(
        {"source": {"path": "/media/a.mkv"}, "video": {"encoder": "hevc_nvenc"}}
    )
    snapshot = caps(**NO_HEVC_HARDWARE)
    (issue,) = encoder_issues(job.video.encoder, snapshot, DEFS)
    fixed = JobSettings.model_validate(
        apply_patch(job.model_dump(mode="json"), issue.fixes[0].patch)
    )
    assert fixed.video.encoder == "libx265"
    assert encoder_issues(fixed.video.encoder, snapshot, DEFS) == []


@pytest.mark.parametrize(
    ("removed", "expected"),
    [
        ("hevc_nvenc", "hevc_amf"),  # an AMD machine: AMF works, NVENC and QSV do not
        ("h264_qsv", "h264_amf"),
        ("av1_nvenc", "av1_amf"),
    ],
)
def test_preset_with_a_removed_encoder(removed: str, expected: str) -> None:
    """05 §C-4 "Done when", third sentence."""
    preset = Preset.model_validate(
        {"id": "h265-nvenc-1080p", "name": "H.265 NVENC 1080p", "video": {"encoder": removed}}
    )
    snapshot = caps(
        **{
            e.id: (UNAVAILABLE, "NVIDIA driver not found")
            for e in DEFS.video_encoders.values()
            if e.family in ("nvenc", "qsv")
        }
    )
    issues = encoder_issues(
        preset.video.encoder, snapshot, DEFS, target="template", subject=f'Preset "{preset.name}"'
    )
    (issue,) = issues
    assert issue.code == "encoder.unavailable"
    assert issue.severity is Severity.ERROR
    assert issue.message.startswith(
        f'Preset "H.265 NVENC 1080p" uses {removed}, which is not available'
    )
    (fix,) = issue.fixes
    assert fix.label == f"Use {expected} (closest match)"
    assert fix.target == "template"
    patched = Preset.model_validate(apply_patch(preset.model_dump(mode="json"), fix.patch))
    assert patched.video.encoder == expected
    assert snapshot.status(patched.video.encoder).state is AVAILABLE
    assert encoder_issues(patched.video.encoder, snapshot, DEFS, target="template") == []
    assert patched.model_dump(exclude={"video"}) == preset.model_dump(exclude={"video"})
