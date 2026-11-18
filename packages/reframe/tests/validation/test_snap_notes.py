"""The info notes on crop and audio values the encoder cannot do, with what is written instead."""

from __future__ import annotations

from typing import Any

import pytest

from reframe.models import AudioOutputTrack, CropSettings, Mixdown, ReplaceOp, Severity

from . import scenario as sc

DEFS = sc.DEFS
AUDIO_CODES = (
    "audio.mixdown_unsupported",
    "audio.mixdown_upmix",
    "audio.bitrate_out_of_range",
    "audio.quality_unsupported",
    "audio.samplerate_unsupported",
)
LAYOUTS = {1: "mono", 2: "stereo", 3: "3.0", 6: "5.1(side)", 8: "7.1"}
#: One encoder of each mixdown kind.
MIXDOWN_ENCODERS = ("aac", "ac3", "libmp3lame", "libopus")
#: For sample rates also a lossless encoder (FLAC).
VALUE_ENCODERS = (*MIXDOWN_ENCODERS, "flac")


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


def test_crop_note_says_what_happens() -> None:
    s = sc.base()
    s.job.dimensions.crop = CropSettings(mode="auto")
    [issue] = [i for i in s.validate() if i.code == "dimensions.crop_not_detected"]
    assert issue.severity is Severity.INFO
    assert issue.message == (
        "Crop detection did not run for this job, so automatic crop has no values: "
        "the picture is not cropped."
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
            "AC-3 cannot keep 7.1: audio track 1 is written as 5.1.", "Mix down to 5.1",
        ),
        (
            AudioOutputTrack(encoder="libmp3lame"), 6, "audio.mixdown_unsupported",
            "MP3 cannot keep 5.1(side): audio track 1 is written as Stereo.",
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
            "No upmix: the source of audio track 1 has 3 channels (3.0), so the track is "
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
    [("stereo", 6, 150, 128), ("5.1", 6, 100, 224), (None, 2, 150, 128)],
)
def test_bitrates_snap_down_as_handbrake(
    mixdown: Mixdown | None, channels: int, kbps: int, written: int
) -> None:
    """Clamp to the layout's range, then take the largest allowed step at or below."""
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


@pytest.mark.parametrize(
    ("layout", "channels", "message", "fixes"),
    [
        ("2.1", 3, "Opus cannot keep 2.1: audio track 1 is written as stereo.",
         ["Mix down to Stereo"]),
        ("3.0(back)", 3, "Opus cannot keep 3.0(back): audio track 1 is written as stereo.",
         ["Mix down to Stereo"]),
        ("4.0", 4, "Opus cannot keep 4.0: audio track 1 is written as 3.0.", []),
        ("6.0", 6, "Opus cannot keep 6.0: audio track 1 is written as 5.0.", []),
        ("7.1(wide)", 8, "Opus cannot keep 7.1(wide): audio track 1 is written as 5.1.",
         ["Mix down to 5.1"]),
    ],
)  # fmt: skip
def test_opus_layout_downmix_is_a_note(
    layout: str, channels: int, message: str, fixes: list[str]
) -> None:
    """The note names the layout that libopus writes instead."""
    s = one_track(AudioOutputTrack(encoder="libopus"), channels=channels)
    s.source.audio[0].channel_layout = layout
    [issue] = [i for i in sc.check(s) if i.code == "audio.mixdown_unsupported"]
    assert (issue.message, issue.severity) == (message, Severity.INFO)
    assert [f.label for f in issue.fixes] == fixes


def test_opus_side_to_back_relabel_is_no_note() -> None:
    """``5.1(side)`` → ``5.1`` is lossless (the same PCM): no note."""
    s = one_track(AudioOutputTrack(encoder="libopus"), channels=6)
    assert not sc.found(s.validate(), "audio.mixdown_unsupported")


def test_a_layout_without_a_name_is_shown_as_channels() -> None:
    s = one_track(AudioOutputTrack(encoder="libmp3lame"), channels=6)
    s.source.audio[0].channel_layout = None
    assert messages(s, "audio.mixdown_unsupported") == [
        "MP3 cannot keep 6 channels: audio track 1 is written as Stereo."
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


@pytest.mark.parametrize("encoder_id", VALUE_ENCODERS)
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
