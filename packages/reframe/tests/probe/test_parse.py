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

    def broken(stream: Any, common: Any, ctx: Any) -> Any:
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
    source = parse_ffprobe(doc(video(color_transfer="smpte2084"), second), FILE, frames=frames)
    hdr0, hdr1 = source.video[0].hdr, source.video[1].hdr
    assert hdr0 is not None
    assert hdr0.content_light is not None
    assert hdr1 is not None
    assert hdr1.content_light is None
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


# --------------------------------------------------------------------------- delay


def test_delay_is_relative_to_the_main_video_stream() -> None:
    """An M2TS clip: everything starts near 1.4 s; the audio starts 5 ms before the video."""
    v = video(start_time="1.405000")
    a = {"index": 1, "codec_type": "audio", "start_time": "1.400000"}
    s = {"index": 2, "codec_type": "subtitle", "start_time": "2.405"}
    source = parse_ffprobe(doc(v, a, s, fmt={"format_name": "mpegts", "start_time": "1.4"}), FILE)
    assert source.video[0].start_time == pytest.approx(1.405)
    assert source.video[0].delay == 0.0
    assert source.audio[0].delay == pytest.approx(-0.005)
    assert source.subtitles[0].delay == pytest.approx(1.0)


def test_delay_without_video_uses_the_container_start() -> None:
    a = {"index": 0, "codec_type": "audio", "start_time": "0.75"}
    source = parse_ffprobe(doc(a, fmt={"start_time": "0.5"}), FILE)
    assert source.audio[0].delay == pytest.approx(0.25)
    unknown = parse_ffprobe(doc({"index": 0, "codec_type": "audio"}), FILE)
    assert unknown.audio[0].delay is None
    cover = video(disposition={"attached_pic": 1}, start_time="9")
    a1 = {**a, "index": 1}
    with_cover = parse_ffprobe(doc(cover, a1, fmt={"start_time": "0.5"}), FILE)
    assert with_cover.audio[0].delay == pytest.approx(0.25)  # cover art is not the reference


# --------------------------------------------------------------------------- VFR in Matroska

MKV = {"format_name": "matroska,webm", "duration": "3.1", "size": "10000000", "bit_rate": "9000000"}


def mkv_video(
    frames: str | None, duration: str, rate: str = "29999/500", **extra: Any
) -> dict[str, Any]:
    tags = {"DURATION": duration, "_STATISTICS_TAGS": "BPS DURATION NUMBER_OF_FRAMES"}
    if frames is not None:
        tags["NUMBER_OF_FRAMES"] = frames
    return video(r_frame_rate=rate, avg_frame_rate=rate, tags=tags, **extra)


@pytest.mark.parametrize(
    ("stream", "vfr", "undecided"),
    [
        (mkv_video("114", "00:00:03.009"), True, False),  # mkvmerge-remuxed VFR: 37.9 vs 60
        (mkv_video("180", "00:00:03.000"), False, False),  # 60 fps CFR
        (mkv_video("60", "00:00:02.002", "30000/1001"), False, False),
        # Interlaced with a field-rate DefaultDuration: half the frames, not VFR.
        (mkv_video("60", "00:00:02.002", "60000/1001", field_order="tt"), False, False),
        (mkv_video(None, "00:00:03.000"), False, True),  # no NUMBER_OF_FRAMES
        (video(r_frame_rate="25/1", avg_frame_rate="25/1"), False, True),  # no tags at all
    ],
)
def test_matroska_vfr_from_statistics(stream: dict[str, Any], vfr: bool, undecided: bool) -> None:
    data = doc(stream, fmt=MKV)
    assert parse_ffprobe(data, FILE).video[0].vfr is vfr
    assert parse.vfr_undecided(data) == ([0] if undecided else [])


def test_stale_statistics_make_vfr_undecided() -> None:
    data = doc(mkv_video("114", "00:00:03.009"), fmt={**MKV, "size": "100"})
    data["streams"][0]["tags"]["NUMBER_OF_BYTES"] = "5000"
    source = parse_ffprobe(data, FILE)
    assert not source.video[0].vfr
    assert parse.vfr_undecided(data) == [0]
    assert source.warnings[0].startswith("Stream 0: the statistics tags look stale")


def test_vfr_undecided_ignores_other_streams() -> None:
    cover = video(index=1, disposition={"attached_pic": 1})
    audio = {"index": 2, "codec_type": "audio"}
    assert parse.vfr_undecided(doc(cover, audio, fmt=MKV)) == []
    assert parse.vfr_undecided(doc(video(r_frame_rate="25/1", avg_frame_rate="25/1"))) == [0]
    mp4 = doc(video(r_frame_rate="25/1", avg_frame_rate="25/1"), fmt={"format_name": "mov,mp4"})
    assert parse.vfr_undecided(mp4) == []


def _pts(*steps_ms: float, start: float = 0.0) -> list[float]:
    out, t = [start], start
    for step in steps_ms:
        t += step / 1000
        out.append(t)
    return out


@pytest.mark.parametrize(
    ("pts", "vfr"),
    [
        (_pts(*[41, 42] * 30), False),  # 23.976 fps with millisecond timestamps
        (_pts(*[40] * 59, 80), False),  # one dropped frame
        (_pts(*[41.7] * 24, *[33.3] * 30, *[16.7] * 60), True),  # 24 / 30 / 60 fps
        (_pts(*[33.3] * 10, *[16.7] * 10), True),
        (_pts(40, 40, 40), None),  # too few
        ([], None),
    ],
)
def test_vfr_from_timestamps(pts: list[float], vfr: bool | None) -> None:
    assert parse.vfr_from_timestamps(pts) is vfr
    assert parse.vfr_from_timestamps(list(reversed(pts))) is vfr  # order does not matter


# --------------------------------------------------------------------------- stale counts


def test_stale_stats_drop_frame_and_event_counts() -> None:
    tags = {"NUMBER_OF_FRAMES": "500", "NUMBER_OF_BYTES": "99999", "BPS": "1"}
    sub = {"index": 1, "codec_type": "subtitle", "codec_name": "subrip", "tags": dict(tags)}
    source = parse_ffprobe(doc(video(tags=dict(tags)), sub, fmt={"size": "1000"}), FILE)
    assert source.video[0].frame_count is None
    assert source.subtitles[0].event_count is None
    assert source.subtitles[0].event_count_source is None
    trusted = parse_ffprobe(doc(video(tags=dict(tags)), sub, fmt={"size": "10000000"}), FILE)
    assert trusted.video[0].frame_count == 500
    assert trusted.subtitles[0].event_count == 500


def test_hdr_uses_the_first_frame_with_side_data() -> None:
    cll = {"side_data_type": "Content light level metadata", "max_content": 7, "max_average": 3}
    frames = {"frames": [{"pict_type": "I"}, {"side_data_list": [cll]}]}
    source = parse_ffprobe(doc(video(color_transfer="smpte2084")), FILE, frames=frames)
    hdr_info = source.video[0].hdr
    assert hdr_info is not None
    assert hdr_info.content_light is not None
    assert hdr_info.content_light.max_cll == 7
