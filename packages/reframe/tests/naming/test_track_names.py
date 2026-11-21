"""Track name templates of a job, expanded for each track."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reframe.models.job import (
    AudioOutputTrack,
    ExternalSubtitle,
    JobSettings,
    OutputSettings,
    SubtitleOutputTrack,
    TrackMetadata,
)
from reframe.models.media import MediaSource, SourceFingerprint, SourceRef
from reframe.naming.track_names import expand_track_name, expand_track_names, track_names
from reframe.probe.parse import parse_ffprobe

PROBE = Path(__file__).resolve().parents[4] / "testdata" / "probes" / "fixtures"


@pytest.fixture(scope="module")
def source() -> MediaSource:
    data = json.loads((PROBE / "multitrack.mkv.json").read_text(encoding="utf-8"))
    path = Path("/media/multitrack.mkv")
    return parse_ffprobe(data, path, fingerprint=SourceFingerprint(size=0, mtime=0.0))


def job(
    *,
    audio: list[AudioOutputTrack] | None = None,
    subtitles: list[SubtitleOutputTrack] | None = None,
) -> JobSettings:
    settings = JobSettings(
        source=SourceRef(path=Path("/media/multitrack.mkv")),
        output=OutputSettings(container="mkv", path=Path("/out/multitrack.mkv")),
        audio=audio or [],
        subtitles=subtitles or [],
    )
    settings.video.encoder = "libx265"
    return settings


def named(name: str | None, **fields: object) -> TrackMetadata:
    return TrackMetadata(name=name, **fields)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("{lang_name} {channels} {codec}", "Japanese 5.1 Opus"),
        ("{lang_native} {channels}", "日本語 5.1"),
        ("{lang} · {bitrate} kb/s", "ja · 256 kb/s"),
        ("{title} ({source_codec})", "Japanese 5.1 (AC-3)"),
        ("{codec:upper}", "OPUS"),
        ("<{title} / >{codec}", "Japanese 5.1 / Opus"),
        ("{{lang_name}} {lang_name}", "{lang_name} Japanese"),
        # Written as typed: no brace, a syntax error, or a variable a track name does not have.
        ("Commentary <Director>", "Commentary <Director>"),
        ("Signs {Karaoke}", "Signs {Karaoke}"),
        ("{lang_name", "{lang_name"),
        ("{lang_nmae} 5.1", "{lang_nmae} 5.1"),
        ("", ""),
        (None, None),
    ],
)
def test_an_audio_track_name(source: MediaSource, name: str | None, expected: str | None) -> None:
    track = AudioOutputTrack(
        source_stream=1, encoder="libopus", mixdown="5.1", bitrate=256, metadata=named(name)
    )
    assert track_names(job(audio=[track]), source).audio == [expected]


def test_a_passthru_track_has_the_source_codec_and_layout(source: MediaSource) -> None:
    copied = AudioOutputTrack(
        source_stream=1, action="passthru", encoder="aac", metadata=named("{codec} {channels}")
    )
    stereo = AudioOutputTrack(
        source_stream=2, encoder="aac", mixdown="stereo", metadata=named("{channels} {codec}")
    )
    assert track_names(job(audio=[copied, stereo]), source).audio == ["AC-3 5.1", "2.0 AAC"]


def test_a_passthru_the_container_cannot_hold_names_its_fallback_encoder(
    source: MediaSource,
) -> None:
    settings = job(
        audio=[
            AudioOutputTrack(
                source_stream=1, action="passthru", encoder="aac", metadata=named("{codec}")
            )
        ]
    )
    settings.output.container = "webm"
    assert track_names(settings, source).audio == ["AAC"]


def test_the_track_language_wins_over_the_source_language(source: MediaSource) -> None:
    track = AudioOutputTrack(
        source_stream=2, encoder="aac", metadata=named("{lang_name}", language="hu")
    )
    assert track_names(job(audio=[track]), source).audio == ["Hungarian"]


def test_subtitle_and_video_names(source: MediaSource) -> None:
    subtitles = [
        SubtitleOutputTrack(source=5, metadata=named("{lang_name} {codec} ({title})")),
        SubtitleOutputTrack(
            source=4, action="convert", convert_to="ass", metadata=named("{codec}")
        ),
        SubtitleOutputTrack(
            source=ExternalSubtitle(path=Path("/media/extra.de.srt"), language="de", name="Full"),
            metadata=named("{lang_native} {source_codec} {title}"),
        ),
    ]
    settings = job(subtitles=subtitles)
    settings.video.metadata = named("{codec} from {source_codec}")
    names = track_names(settings, source)
    assert names.subtitles == ["English SRT (English SDH)", "ASS", "Deutsch SRT Full"]
    assert names.video == "HEVC from H.264 Constrained Baseline"
    settings.video.passthrough = True
    assert (
        track_names(settings, source).video
        == "H.264 Constrained Baseline from H.264 Constrained Baseline"
    )


def test_a_job_without_templates_is_returned_as_it_is(source: MediaSource) -> None:
    settings = job(audio=[AudioOutputTrack(source_stream=1, metadata=named("Japanese"))])
    assert expand_track_names(settings, source) is settings


def test_a_job_with_templates_is_expanded_in_a_copy(source: MediaSource) -> None:
    settings = job(
        audio=[
            AudioOutputTrack(source_stream=1, encoder="ac3", metadata=named("{lang_name} {codec}")),
            AudioOutputTrack(source_stream=2, metadata=named(None)),
        ]
    )
    expanded = expand_track_names(settings, source)
    assert [track.metadata.name for track in expanded.audio] == ["Japanese AC-3", None]
    assert settings.audio[0].metadata.name == "{lang_name} {codec}"


def test_an_empty_value_drops_its_optional_group() -> None:
    assert expand_track_name("{lang_name}< - {title}>", {"lang_name": "English"}) == "English"
    assert expand_track_name("{title}", {}) == ""


@pytest.mark.parametrize(
    ("track", "expected"),
    [
        # A stereo source is not upmixed.
        (AudioOutputTrack(source_stream=2, encoder="aac", mixdown="5.1"), "2.0 AAC 160"),
        # AC-3 takes at most 640 kb/s.
        (AudioOutputTrack(source_stream=1, encoder="ac3", bitrate=700), "5.1 AC-3 640"),
        # No bit rate: the encoder's default for the layout written.
        (AudioOutputTrack(source_stream=2, encoder="aac"), "2.0 AAC 160"),
        # MP3 has no 5.1.
        (AudioOutputTrack(source_stream=1, encoder="libmp3lame", mixdown="5.1"), "2.0 MP3 160"),
        # A copy has no bit rate of its own.
        (AudioOutputTrack(source_stream=1, action="passthru"), "5.1 AC-3"),
    ],
)
def test_an_audio_name_has_the_values_that_are_written(
    source: MediaSource, track: AudioOutputTrack, expected: str
) -> None:
    track.metadata = named("{channels} {codec} {bitrate}")
    assert track_names(job(audio=[track]), source).audio == [expected]


def test_a_passthru_without_a_fallback_encoder_names_the_default_one(source: MediaSource) -> None:
    vorbis = source.audio[0].model_copy(update={"codec": "vorbis", "display_codec": "Vorbis"})
    changed = source.model_copy(update={"audio": [vorbis, *source.audio[1:]]})
    template = named("{codec} {channels} {bitrate}")
    copied = AudioOutputTrack(source_stream=1, action="passthru", encoder=None, metadata=template)
    settings = job(audio=[copied])
    settings.output.container = "mp4"
    assert track_names(settings, changed).audio == ["AAC 5.1 384"]


def test_a_subtitle_name_has_the_codec_that_is_written(source: MediaSource) -> None:
    template = named("{codec} from {source_codec}")
    settings = job(subtitles=[SubtitleOutputTrack(source=4, metadata=template)])
    assert track_names(settings, source).subtitles == ["SRT from SRT"]
    settings.output.container = "mp4"
    assert track_names(settings, source).subtitles == ["mov_text from SRT"]
