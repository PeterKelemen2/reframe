"""The ffprobe JSON parser (C-3) on hand-made edge cases."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from reframe.models import FieldOrder, Rational, SourceFingerprint
from reframe.probe import parse
from reframe.probe.parse import parse_ffprobe, parse_rational

FILE = Path("/media/x.mkv")


def video(**extra: Any) -> dict[str, Any]:
    return {
        "index": 0,
        "codec_type": "video",
        "codec_name": "h264",
        "width": 1920,
        "height": 1080,
        **extra,
    }


def doc(
    *streams: dict[str, Any], fmt: dict[str, Any] | None = None, **extra: Any
) -> dict[str, Any]:
    return {
        "streams": list(streams),
        "format": {"format_name": "matroska,webm", "duration": "10.0", **(fmt or {})},
        **extra,
    }


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("24000/1001", Rational(num=24000, den=1001)),
        ("32:27", Rational(num=32, den=27)),
        ("50/2", Rational(num=25)),
        ("0/0", None),
        ("0:1", None),
        ("1/0", None),
        ("-1/2", None),
        ("abc", None),
        ("1/2/3", None),
        ("a/b", None),
        (None, None),
        ("N/A", None),
    ],
)
def test_parse_rational(text: str | None, expected: Rational | None) -> None:
    assert parse_rational(text) == expected


@pytest.mark.parametrize(
    ("r_rate", "avg", "field_order", "fmt", "vfr"),
    [
        ("24000/1001", "24000/1001", "progressive", "matroska,webm", False),
        ("24000/1001", "8150000/339959", "progressive", "mov,mp4", False),  # rounding only
        ("120/1", "38/1", "progressive", "mov,mp4", True),
        ("120/1", "0/0", "progressive", "matroska,webm", True),
        ("25/1", "0/0", "progressive", "mpegts", False),
        ("60000/1001", "30000/1001", "tt", "mpegts", False),  # field rate, interlaced
        ("60000/1001", "30000/1001", "progressive", "mpegts", True),
        ("0/0", "0/0", "progressive", "matroska,webm", False),
    ],
)
def test_vfr(r_rate: str, avg: str, field_order: str, fmt: str, vfr: bool) -> None:
    stream = video(r_frame_rate=r_rate, avg_frame_rate=avg, field_order=field_order)
    source = parse_ffprobe(doc(stream, fmt={"format_name": fmt}), FILE)
    assert source.video[0].vfr is vfr


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("progressive", FieldOrder.PROGRESSIVE),
        ("tt", FieldOrder.TOP_FIRST),
        ("tb", FieldOrder.TOP_FIRST),
        ("bb", FieldOrder.BOTTOM_FIRST),
        ("bt", FieldOrder.BOTTOM_FIRST),
        ("unknown", FieldOrder.UNKNOWN),
        (None, FieldOrder.UNKNOWN),
    ],
)
def test_field_order(value: str | None, expected: FieldOrder) -> None:
    stream = video() if value is None else video(field_order=value)
    assert parse_ffprobe(doc(stream), FILE).video[0].field_order is expected


@pytest.mark.parametrize(
    ("side", "tags", "rotation"),
    [
        ([{"side_data_type": "Display Matrix", "rotation": -90}], {}, 90),
        ([{"side_data_type": "Display Matrix", "rotation": 90}], {}, 270),
        ([{"side_data_type": "Display Matrix", "rotation": 180}], {}, 180),
        ([{"side_data_type": "Display Matrix", "rotation": -89.9}], {}, 90),
        ([], {"rotate": "90"}, 90),
        ([{"side_data_type": "Display Matrix"}], {"rotate": "270"}, 270),
        ([], {}, 0),
    ],
)
def test_rotation(side: list[dict[str, Any]], tags: dict[str, str], rotation: int) -> None:
    stream = video(side_data_list=side, tags=tags)
    assert parse_ffprobe(doc(stream), FILE).video[0].rotation == rotation


def test_missing_values_are_none() -> None:
    stream = video(
        profile="unknown",
        level=-99,
        sample_aspect_ratio="0:1",
        color_space="unknown",
        color_range="unknown",
        color_primaries="reserved",
        pix_fmt="weird_fmt",
        nb_frames="N/A",
    )
    source = parse_ffprobe({"streams": [stream], "format": {}}, FILE)
    v = source.video[0]
    assert (v.profile, v.level, v.sar, v.bit_depth, v.frame_count) == (None, None, None, None, None)
    assert v.color.matrix is None
    assert v.color.range is None
    assert v.color.primaries is None
    assert v.display_codec == "H.264"
    assert source.container.duration is None
    assert "The container reports no duration." in source.warnings


@pytest.mark.parametrize(
    ("stream_extra", "depth"),
    [
        ({"bits_per_raw_sample": "10"}, 10),
        ({"pix_fmt": "yuv420p10le"}, 10),
        ({"pix_fmt": "p010le"}, 10),
        ({"pix_fmt": "yuv444p12be"}, 12),
        ({"pix_fmt": "yuv420p"}, 8),
        ({"pix_fmt": "nv12"}, 8),
        ({"pix_fmt": "gbrpf32le"}, 32),
    ],
)
def test_bit_depth(stream_extra: dict[str, Any], depth: int) -> None:
    assert parse.video_bit_depth(video(**stream_extra)) == depth


def test_stream_duration_falls_back_to_the_matroska_tag() -> None:
    audio = {
        "index": 1,
        "codec_type": "audio",
        "codec_name": "aac",
        "channels": 2,
        "tags": {"DURATION-eng": "01:02:03.500000000"},
    }
    source = parse_ffprobe(doc(video(), audio), FILE)
    assert source.audio[0].duration == pytest.approx(3723.5)


def test_bad_language_is_a_warning() -> None:
    audio = {"index": 1, "codec_type": "audio", "tags": {"language": "English (US)"}}
    source = parse_ffprobe(doc(audio), FILE)
    assert source.audio[0].language is None
    assert any("language tag 'English (US)'" in w for w in source.warnings)


def test_video_without_size_becomes_a_data_stream() -> None:
    source = parse_ffprobe(doc(video(width=0), video(index=1)), FILE)
    assert [d.index for d in source.data] == [0]
    assert [v.index for v in source.video] == [1]
    assert source.video[0].type_index == 1  # counts like FFmpeg's 0:v:N
    assert "Video stream 0 has no frame size." in source.warnings


def test_type_index_counts_cover_art_like_ffmpeg() -> None:
    cover = video(
        index=2, codec_name="mjpeg", disposition={"attached_pic": 1}, tags={"filename": "cover.jpg"}
    )
    source = parse_ffprobe(doc(cover, video(index=3)), FILE)
    assert [c.filename for c in source.cover_art] == ["cover.jpg"]
    assert source.video[0].type_index == 1
    assert parse.main_video_index(doc(cover, video(index=3))) == 3


def test_unknown_types_are_data_streams() -> None:
    weird = {"index": 0, "codec_type": "attachmentx", "codec_tag_string": "[0][0][0][0]"}
    source = parse_ffprobe(doc(weird), FILE)
    assert source.data[0].codec_tag is None


def test_no_streams_is_a_warning() -> None:
    assert "ffprobe found no streams." in parse_ffprobe({"format": {}}, FILE).warnings
    junk = parse_ffprobe({"streams": "junk", "format": "junk", "chapters": "junk"}, FILE)
    assert junk.container.format_name is None
    assert junk.chapters == []


def test_invalid_stream_is_a_warning_not_an_error() -> None:
    # A negative channel count cannot be stored: clamp it. A nonsense sample rate is dropped.
    audio = {"index": 1, "codec_type": "audio", "channels": -2, "sample_rate": "x"}
    source = parse_ffprobe(doc(audio), FILE)
    assert source.audio[0].channels == 0
    assert source.audio[0].sample_rate is None


def test_validation_error_in_a_stream_becomes_a_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    source = parse_ffprobe(doc({"index": 1, "codec_type": "audio", "disposition": "junk"}), FILE)
    assert source.audio[0].disposition.default is False

    def broken(stream: Any, common: Any) -> Any:
        from reframe.models import AudioStream

        return AudioStream.model_validate({"index": -1})

    monkeypatch.setattr(parse, "_audio", broken)
    source = parse_ffprobe(doc({"index": 1, "codec_type": "audio"}), FILE)
    assert source.audio == []
    assert any(w.startswith("Stream 1 (audio) could not be read") for w in source.warnings)


def test_chapters() -> None:
    chapters = [
        {"id": 1, "start_time": "-0.5", "end_time": "1.0", "tags": {"title": "A"}},
        {"id": 2, "start_time": "1.0", "end_time": "0.5"},
        "junk",
    ]
    source = parse_ffprobe(doc(video(), chapters=chapters), FILE)
    assert [(c.index, c.start, c.end, c.title) for c in source.chapters] == [
        (0, 0.0, 1.0, "A"),
        (1, 1.0, 1.0, None),
    ]


def test_creation_time() -> None:
    fmt = {"tags": {"creation_time": "2024-01-02T03:04:05.000000Z"}}
    assert parse_ffprobe(doc(fmt=fmt), FILE).container.creation_time is not None
    for bad in ("yesterday", "2024-01-02T03:04:05"):  # junk, no time zone
        fmt = {"tags": {"creation_time": bad}}
        assert parse_ffprobe(doc(fmt=fmt), FILE).container.creation_time is None


def test_frames_only_for_the_main_video_stream() -> None:
    frames = {
        "frames": [
            {
                "side_data_list": [
                    {
                        "side_data_type": "Content light level metadata",
                        "max_content": 1,
                        "max_average": 1,
                    }
                ]
            }
        ]
    }
    second = video(index=1, color_transfer="smpte2084")
    source = parse_ffprobe(doc(video(color_transfer="bt709"), second), FILE, frames=frames)
    assert source.video[0].hdr is not None  # the frame's CLL belongs to stream 0
    assert source.video[1].hdr is not None
    assert source.video[1].hdr.content_light is None
    empty = parse_ffprobe(doc(video()), FILE, frames={"frames": ["junk"]})
    assert empty.video[0].hdr is None


def test_fingerprint_gets_the_layout_hash() -> None:
    data = doc(video(), {"index": 1, "codec_type": "audio", "channels": 2})
    first = parse_ffprobe(data, FILE, fingerprint=SourceFingerprint(size=1, mtime=2.0))
    again = parse_ffprobe(data, FILE, fingerprint=SourceFingerprint(size=1, mtime=2.0))
    assert first.ref.fingerprint is not None
    assert first.ref.fingerprint.probe_hash
    assert again.ref.fingerprint == first.ref.fingerprint
    data["streams"][1]["channels"] = 6
    changed = parse_ffprobe(data, FILE, fingerprint=SourceFingerprint(size=1, mtime=2.0))
    assert changed.ref.fingerprint is not None
    assert changed.ref.fingerprint.probe_hash != first.ref.fingerprint.probe_hash
    assert parse_ffprobe(data, FILE).ref.fingerprint is None
