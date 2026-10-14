"""Decision 0024 items 3 and 4: the crop note and the audio values the encoder cannot do are
**info** issues that say what will change, with the values the command builder writes (C-6's
snap helpers, shared by C-7, C-8 and C-12).

- The texts name the written value (``AC-3 cannot make 7.1: … is written as 5.1``).
- The values are the helpers' answers (``AudioEncoderDef.snap_mixdown`` /
  ``snap_samplerate``, ``AudioBitrateDef.snap``, ``channels_mixdown``), for every audio
  encoder, every requested layout and typical source layouts.
- A mixdown fix is never Dolby Pro Logic II and never an upmix (decision 0019 item 3).
"""

from __future__ import annotations

import importlib.util
import itertools
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, get_args

import pytest

from reframe.definitions import channels_mixdown
from reframe.models import AudioOutputTrack, CropSettings, Mixdown, ReplaceOp, Severity


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"_reframe_validation_{name}", Path(__file__).with_name(f"{name}.py")
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sc = _load("scenario")
DEFS = sc.DEFS
AUDIO_CODES = (
    "audio.mixdown_unsupported",
    "audio.mixdown_upmix",
    "audio.bitrate_out_of_range",
    "audio.quality_unsupported",
    "audio.samplerate_unsupported",
)
LAYOUTS = {1: "mono", 2: "stereo", 3: "2.1", 6: "5.1(side)", 8: "7.1"}


def one_track(track: AudioOutputTrack, *, channels: int = 6, rate: int = 48000) -> Any:
    """The clean scenario with one audio track, reading the AC-3 source stream changed to
    ``channels`` channels and ``rate`` Hz."""
    s = sc.base()
    stream = s.source.audio[0]
    stream.channels = channels
    stream.channel_layout = LAYOUTS.get(channels)
    stream.sample_rate = rate
    s.job.audio = [track.model_copy(update={"source_stream": stream.index})]
    return s


def messages(s: Any, code: str) -> list[str]:
    return [i.message for i in s.validate() if i.code == code]


# --------------------------------------------------------------------------- the texts


def test_crop_note_says_what_happens() -> None:
    s = sc.base()
    s.job.dimensions.crop = CropSettings(mode="auto")
    [issue] = [i for i in s.validate() if i.code == "dimensions.crop_not_detected"]
    assert issue.severity is Severity.INFO
    assert issue.message == (
        "Crop detection is not available yet: automatic crop leaves the picture uncropped."
    )


@pytest.mark.parametrize(
    ("track", "channels", "code", "message", "fix"),
    [
        (
            AudioOutputTrack(encoder="ac3", mixdown="7.1", bitrate=640), 8,
            "audio.mixdown_unsupported",
            "AC-3 cannot make 7.1: audio track 1 is written as 5.1.", "Mix down to 5.1",
        ),
        (
            AudioOutputTrack(encoder="ac3"), 8, "audio.mixdown_unsupported",
            "AC-3 cannot make 7.1: audio track 1 is written as 5.1.", "Mix down to 5.1",
        ),
        (
            AudioOutputTrack(encoder="libmp3lame"), 6, "audio.mixdown_unsupported",
            "MP3 cannot make 5.1(side): audio track 1 is written as Stereo.",
            "Mix down to Stereo",
        ),
        (
            AudioOutputTrack(encoder="aac", mixdown="5.1"), 2, "audio.mixdown_upmix",
            "No upmix: the source of audio track 1 has 2 channels (stereo), so the track "
            "keeps the source layout (stereo) instead of 5.1.",
            "Keep the source layout",
        ),
        (
            AudioOutputTrack(encoder="libmp3lame", mixdown="5.1"), 3, "audio.mixdown_upmix",
            "No upmix: the source of audio track 1 has 3 channels (2.1), so the track is "
            "written as Stereo instead of 5.1.",
            "Mix down to Stereo",
        ),
        (
            AudioOutputTrack(encoder="aac", mixdown="dpl2"), 2, "audio.mixdown_upmix",
            "Dolby Pro Logic II needs a surround source: the source of audio track 1 is "
            "stereo, so the track keeps the source layout (stereo).",
            "Keep the source layout",
        ),
        (
            AudioOutputTrack(encoder="ac3", mixdown="5.1", bitrate=700), 6,
            "audio.bitrate_out_of_range",
            "AC-3 has no 700 kb/s for 5.1 (224 to 640 kb/s, fixed steps): audio track 1 is "
            "written at 640 kb/s.",
            "Use 640 kb/s",
        ),
        (
            AudioOutputTrack(encoder="ac3", bitrate=250), 2, "audio.bitrate_out_of_range",
            "AC-3 has no 250 kb/s for Stereo (96 to 640 kb/s, fixed steps): audio track 1 is "
            "written at 224 kb/s.",
            "Use 224 kb/s",
        ),
        (
            AudioOutputTrack(encoder="aac", bitrate=96), 6, "audio.bitrate_out_of_range",
            "AAC has no 96 kb/s for 5.1 (192 to 1536 kb/s): audio track 1 is written at "
            "192 kb/s.",
            "Use 192 kb/s",
        ),
        (
            AudioOutputTrack(encoder="aac", quality=4), 2, "audio.quality_unsupported",
            "AAC has no VBR quality: audio track 1 is written at 160 kb/s, the default for "
            "Stereo.",
            "Use 160 kb/s",
        ),
        (
            AudioOutputTrack(encoder="flac", bitrate=640), 2, "audio.bitrate_out_of_range",
            "FLAC is lossless and has no bitrate: audio track 1 is written without one "
            "(640 kb/s is not used).",
            "Remove the bitrate",
        ),
        (
            AudioOutputTrack(encoder="flac", quality=4), 2, "audio.quality_unsupported",
            "FLAC is lossless and has no VBR quality: audio track 1 is written without one.",
            "Remove the VBR quality",
        ),
        (
            AudioOutputTrack(encoder="ac3", bitrate=224, samplerate=96000), 2,
            "audio.samplerate_unsupported",
            "AC-3 has no 96000 Hz: audio track 1 is written at 48000 Hz.", "Use 48000 Hz",
        ),
    ],
)  # fmt: skip
def test_texts_say_what_is_written(
    track: AudioOutputTrack, channels: int, code: str, message: str, fix: str
) -> None:
    s = one_track(track, channels=channels)
    found = [i for i in sc.check(s) if i.code == code]
    assert [i.message for i in found] == [message]
    assert [f.label for f in found[0].fixes] == [fix]
    assert found[0].severity is Severity.INFO


@pytest.mark.parametrize(
    ("mixdown", "channels", "kbps", "written"),
    [("stereo", 6, 150, 128), ("5.1", 6, 700, 640), ("5.1", 6, 100, 224), (None, 2, 150, 128)],
)
def test_bitrates_snap_down_as_handbrake(
    mixdown: Mixdown | None, channels: int, kbps: int, written: int
) -> None:
    """Decision 0025 (HandBrake 1.11.2, libhb/common.c): clamp to the range of the layout,
    then the largest allowed step at or below. The fix sets that value."""
    track = AudioOutputTrack(encoder="ac3", mixdown=mixdown, bitrate=kbps)
    [issue] = [
        i
        for i in sc.check(one_track(track, channels=channels))
        if i.code == "audio.bitrate_out_of_range"
    ]
    assert issue.message.endswith(f"is written at {written} kb/s.")
    [op] = issue.fixes[0].patch
    assert isinstance(op, ReplaceOp)
    assert op.value == written


def test_a_passthru_copy_is_never_snapped() -> None:
    track = AudioOutputTrack(action="passthru", encoder="ac3", bitrate=700, samplerate=96000)
    issues = one_track(track, channels=8).validate()
    assert not [i for i in issues if i.code in AUDIO_CODES], issues


def test_a_layout_without_a_name_is_shown_as_channels() -> None:
    s = one_track(AudioOutputTrack(encoder="libmp3lame"), channels=6)
    s.source.audio[0].channel_layout = None
    assert messages(s, "audio.mixdown_unsupported") == [
        "MP3 cannot make 6 channels: audio track 1 is written as Stereo."
    ]


def test_a_passthru_track_without_a_source_is_only_source_missing() -> None:
    s = one_track(AudioOutputTrack(action="passthru"))
    s.job.output.container = "webm"
    s.job.audio[0].source_stream = 9
    codes = {i.code for i in s.validate() if i.code.startswith("audio.")}
    assert codes == {"audio.source_missing"}


def test_a_source_rate_the_encoder_lacks_is_resampled_without_a_note() -> None:
    """HandBrake resamples "same as source" silently (Opus has no 44.1 kHz)."""
    s = one_track(AudioOutputTrack(encoder="libopus"), channels=2, rate=44100)
    assert not sc.found(s.validate(), "audio.samplerate_unsupported")


def test_audio_values_never_block_the_queue() -> None:
    track = AudioOutputTrack(encoder="ac3", mixdown="7.1", bitrate=700, samplerate=96000)
    issues = one_track(track, channels=8).validate()
    assert {i.code for i in issues} >= {
        "audio.mixdown_unsupported",
        "audio.bitrate_out_of_range",
        "audio.samplerate_unsupported",
    }
    assert all(i.severity is not Severity.ERROR for i in issues), issues


# --------------------------------------------------------------------------- the helpers


REQUESTS: list[Mixdown | None] = [None, *get_args(Mixdown)]


@pytest.mark.parametrize(
    ("encoder_id", "requested", "channels"),
    list(itertools.product(sorted(DEFS.audio_encoders), REQUESTS, [0, 1, 2, 3, 6, 8])),
)
def test_mixdown_issues_follow_the_helper(
    encoder_id: str, requested: Mixdown | None, channels: int
) -> None:
    """For every encoder, layout and source: an issue exactly when the helper changes the
    track's layout; its fix sets the helper's layout, which is never Dolby Pro Logic II
    (unless asked for and kept) and never has more channels than the source."""
    encoder = DEFS.audio_encoders[encoder_id]
    written = encoder.snap_mixdown(requested, channels, DEFS.mixdowns)
    track = AudioOutputTrack(encoder=encoder_id, mixdown=requested)
    s = one_track(track, channels=channels)
    issues = [
        i for i in s.validate() if i.code in ("audio.mixdown_unsupported", "audio.mixdown_upmix")
    ]
    if written == requested:
        assert issues == []
        return
    [issue] = issues
    assert issue.severity is Severity.INFO
    [fix] = issue.fixes
    [op] = fix.patch
    assert isinstance(op, ReplaceOp)
    assert op.value == written
    assert op.value != "dpl2"
    if op.value is not None and channels > 0:
        assert DEFS.mixdowns[op.value].channels <= max(channels, 2)
    shown = "the source layout" if written is None else DEFS.mixdowns[written].label
    assert shown in issue.message


@pytest.mark.parametrize("encoder_id", sorted(DEFS.audio_encoders))
@pytest.mark.parametrize("kbps", [8, 100, 250, 700, 5000])
@pytest.mark.parametrize("channels", [1, 2, 6, 8])
def test_bitrate_issues_follow_the_helper(encoder_id: str, kbps: int, channels: int) -> None:
    """The written bitrate is ``AudioBitrateDef.snap`` (down) for the written layout, or for
    ``channels_mixdown`` of the kept source layout. A lossless encoder writes none."""
    encoder = DEFS.audio_encoders[encoder_id]
    s = one_track(AudioOutputTrack(encoder=encoder_id, bitrate=kbps), channels=channels)
    found = [i for i in s.validate() if i.code == "audio.bitrate_out_of_range"]
    if encoder.bitrate is None:
        [issue] = found
        assert issue.message.endswith(f"is written without one ({kbps} kb/s is not used).")
        return
    layout = encoder.snap_mixdown(None, channels, DEFS.mixdowns) or channels_mixdown(channels)
    snapped = encoder.bitrate.snap(kbps, layout, "down")
    if snapped == kbps:
        assert found == []
        return
    [issue] = found
    assert issue.message.endswith(f"is written at {snapped} kb/s.")


@pytest.mark.parametrize("encoder_id", sorted(DEFS.audio_encoders))
@pytest.mark.parametrize("rate", [8000, 22050, 44100, 48000, 96000, 192000])
def test_samplerate_issues_follow_the_helper(encoder_id: str, rate: int) -> None:
    encoder = DEFS.audio_encoders[encoder_id]
    s = one_track(AudioOutputTrack(encoder=encoder_id, samplerate=rate), channels=2)
    found = [i for i in s.validate() if i.code == "audio.samplerate_unsupported"]
    written = encoder.snap_samplerate(rate, 48000)
    if written == rate:
        assert found == []
    else:
        [issue] = found
        assert issue.message.endswith(f"is written at {written} Hz.")


def test_audio_codes_are_info() -> None:
    """Decision 0024 item 4, for every code of the audio value rules."""
    tracks = [
        (AudioOutputTrack(encoder="ac3", mixdown="7.1"), 8),
        (AudioOutputTrack(encoder="aac", mixdown="5.1"), 2),
        (AudioOutputTrack(encoder="ac3", bitrate=700), 6),
        (AudioOutputTrack(encoder="aac", quality=3), 2),
        (AudioOutputTrack(encoder="ac3", samplerate=96000), 2),
    ]
    seen: set[str] = set()
    for track, channels in tracks:
        for issue in one_track(track, channels=channels).validate():
            if issue.code in AUDIO_CODES:
                assert issue.severity is Severity.INFO
                seen.add(issue.code)
    assert seen == set(AUDIO_CODES)
