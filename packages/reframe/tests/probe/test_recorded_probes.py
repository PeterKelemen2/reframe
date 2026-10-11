"""What the parser makes of the recorded real-world probes (Q-2.2), beyond the snapshots.

How each file was made (and which fields were edited) is in ``testdata/probes/README.md`` and
``testdata/probes/index.json``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from reframe.models import (
    BitrateSource,
    FieldOrder,
    HdrFormat,
    MediaSource,
    Rational,
    RoleEvidence,
    TrackRole,
)

Load = Callable[[str], MediaSource]


def _roles(stream: object) -> list[tuple[TrackRole, RoleEvidence]]:
    return [(r.role, r.evidence) for r in getattr(stream, "roles", [])]


def test_truehd_atmos(probe_source: Load) -> None:
    source = probe_source("truehd-atmos")
    truehd, ac3, commentary = source.audio
    assert truehd.display_codec == "TrueHD Atmos"
    assert truehd.lossless
    assert truehd.bit_depth == 24
    # TrueHD has no stream bit rate: the mkvmerge statistics tag gives it.
    assert truehd.bitrate.source is BitrateSource.STATS_TAG
    assert truehd.bitrate.value == 385232
    assert ac3.bitrate.source is BitrateSource.STREAM
    assert _roles(commentary) == [(TrackRole.COMMENTARY, RoleEvidence.TITLE)]
    assert _roles(truehd) == [(TrackRole.MAIN, RoleEvidence.FLAG)]


@pytest.mark.parametrize(("name", "display"), [("dts-hd-ma", "DTS-HD MA"), ("dts-x", "DTS:X")])
def test_dts_lossless(probe_source: Load, name: str, display: str) -> None:
    dts = probe_source(name).audio[0]
    assert dts.display_codec == display
    assert dts.lossless
    assert dts.sample_fmt == "s32p"
    assert dts.bit_depth == 24
    assert dts.bitrate.source is BitrateSource.STATS_TAG  # no bit_rate for XLL


def test_dts_hd_ma_commentary_heuristic(probe_source: Load) -> None:
    stereo = probe_source("dts-hd-ma").audio[1]
    assert stereo.title is None
    assert _roles(stereo) == [(TrackRole.COMMENTARY, RoleEvidence.HEURISTIC)]
    assert "192 kb/s" in (stereo.roles[0].detail or "")


def test_eac3_atmos_and_title_roles(probe_source: Load) -> None:
    source = probe_source("eac3-atmos")
    assert source.audio[0].display_codec == "E-AC-3 Atmos"
    assert not source.audio[0].lossless
    assert [_roles(s) for s in source.subtitles] == [
        [(TrackRole.MAIN, RoleEvidence.HEURISTIC)],
        [(TrackRole.SDH, RoleEvidence.TITLE)],
        [(TrackRole.FORCED, RoleEvidence.TITLE)],
    ]
    assert [s.event_count for s in source.subtitles] == [8, 10, 1]


def test_pgs(probe_source: Load) -> None:
    subs = probe_source("pgs").subtitles
    assert {s.display_codec for s in subs} == {"PGS"}
    assert all(s.subtitle_kind == "bitmap" and (s.width, s.height) == (1920, 1080) for s in subs)
    assert [s.event_count for s in subs] == [8, 1, 9, 8]
    assert all(s.event_count_source == "stats_tag" for s in subs)
    assert _roles(subs[1]) == [(TrackRole.FORCED, RoleEvidence.HEURISTIC)]
    assert _roles(subs[2]) == [(TrackRole.SDH, RoleEvidence.FLAG)]
    assert subs[3].language == "hun"


def test_ass_with_fonts(probe_source: Load) -> None:
    source = probe_source("ass-fonts")
    signs, full = source.subtitles
    assert (signs.display_codec, full.display_codec) == ("ASS", "ASS")
    assert _roles(signs) == [(TrackRole.SIGNS, RoleEvidence.TITLE)]
    assert [(a.filename, a.mimetype, a.size) for a in source.attachments] == [
        ("ReframeBox.ttf", "application/x-truetype-font", 1672),
        ("ReframeBox-Alt.ttf", "font/ttf", 1672),
    ]
    assert source.attachments[0].codec == "ttf"
    assert source.attachments[1].codec is None  # this ffprobe does not map font/ttf
    assert source.audio[0].display_codec == "FLAC"
    assert source.audio[0].lossless
    assert [c.title for c in source.chapters] == ["Opening", "Part A"]


def test_vfr(probe_source: Load) -> None:
    video = probe_source("vfr").video[0]
    assert video.vfr
    assert video.frame_rate == Rational(num=120)
    assert video.avg_frame_rate is None  # 0/0 in Matroska
    assert video.bitrate.source is BitrateSource.STATS_TAG
    assert video.frame_count == 114  # NUMBER_OF_FRAMES


def test_interlaced_dvd(probe_source: Load) -> None:
    mkv = probe_source("dvd-interlaced")
    video = mkv.video[0]
    assert (video.display_codec, video.width, video.height) == ("MPEG-2 Main", 720, 480)
    assert video.sar == Rational(num=32, den=27)
    assert video.field_order is FieldOrder.TOP_FIRST  # "tb" in Matroska
    assert not video.vfr
    assert [s.display_codec for s in mkv.subtitles] == ["VobSub", "VobSub"]
    assert len(mkv.chapters) == 2

    vob = probe_source("dvd-interlaced-vob")
    assert vob.container.display_name == "VOB"
    assert vob.video[0].field_order is FieldOrder.TOP_FIRST  # "tt" in MPEG-PS
    # Raw start times, and the delay relative to the video (what the UI shows): the audio
    # starts 5 ms before the video, not 528 ms after the container start.
    assert vob.audio[0].start_time == pytest.approx(0.528033)
    assert vob.video[0].start_time == pytest.approx(0.533367)
    assert vob.audio[0].delay == pytest.approx(-0.005334)
    assert vob.video[0].delay == 0.0
    assert mkv.audio[0].delay == 0.0


def test_hdr10(probe_source: Load) -> None:
    video = probe_source("hdr10").video[0]
    assert video.hdr is not None
    assert video.hdr.formats == [HdrFormat.HDR10]
    assert video.hdr.source == "stream"
    md = video.hdr.mastering_display
    assert md is not None
    assert (md.red_x, md.green_y, md.white_x) == pytest.approx((0.68, 0.69, 0.3127))
    assert (md.min_luminance, md.max_luminance) == pytest.approx((0.0001, 1000.0))
    assert video.hdr.content_light is not None
    assert (video.hdr.content_light.max_cll, video.hdr.content_light.max_fall) == (1000, 400)
    assert video.bit_depth == 10
    assert video.color.transfer == "smpte2084"


def test_hdr10_from_the_first_frame(probe_source: Load) -> None:
    video = probe_source("hdr10-sei-only").video[0]
    assert video.hdr is not None
    assert video.hdr.formats == [HdrFormat.HDR10]
    assert video.hdr.source == "frame"
    assert video.hdr.mastering_display is not None


def test_dolby_vision_profile_8(probe_source: Load) -> None:
    hdr = probe_source("dv-p8").video[0].hdr
    assert hdr is not None
    assert hdr.formats == [HdrFormat.HDR10, HdrFormat.DOLBY_VISION]
    assert hdr.dolby_vision is not None
    assert (hdr.dolby_vision.profile, hdr.dolby_vision.bl_signal_compatibility_id) == (8, 1)
    assert hdr.dolby_vision.rpu_present
    assert not hdr.dolby_vision.el_present


def test_hlg(probe_source: Load) -> None:
    hdr = probe_source("hlg").video[0].hdr
    assert hdr is not None
    assert hdr.formats == [HdrFormat.HLG]
    assert hdr.mastering_display is None


def test_cover_art_is_not_a_video_track(probe_source: Load) -> None:
    source = probe_source("cover-art")
    assert source.video == []
    assert [(c.codec, c.width) for c in source.cover_art] == [("png", 300)]
    assert source.container.display_name == "M4A"
    assert source.container.title == "Test Song"
    assert source.audio[0].language == "und"


def test_phone_rotation_timecode_and_creation_time(probe_source: Load) -> None:
    source = probe_source("phone-rotated")
    assert source.container.display_name == "MOV"
    assert source.video[0].rotation == 90  # ffprobe "rotation": -90 (counter-clockwise)
    assert [(d.codec_tag, d.title) for d in source.data] == [("tmcd", "TimeCodeHandler")]
    assert source.container.creation_time == datetime(2026, 5, 1, 10, 20, 30, tzinfo=UTC)


def test_mkvmerge_vfr_is_detected_from_the_statistics_tags(probe_source: Load) -> None:
    """mkvmerge writes DefaultDuration, so r_frame_rate = avg_frame_rate = 29999/500; its
    statistics tags say 114 frames in 3.01 s (37.9 fps): VFR."""
    source = probe_source("mkvmerge-vfr")
    video = source.video[0]
    assert video.frame_rate == video.avg_frame_rate == Rational(num=29999, den=500)
    assert video.vfr
    assert video.frame_count == 114
    assert source.audio[0].delay == pytest.approx(-0.021)  # mkvmerge shifted the video
    assert source.warnings == []


def test_stale_statistics_tags_are_not_used(probe_source: Load) -> None:
    """A 200 kb/s FFmpeg re-encode of an mkvmerge file keeps the old tags (BPS 9.6 Mb/s,
    2.4 MB in an 85 kB file)."""
    source = probe_source("stale-stats")
    video = source.video[0]
    assert video.tags["BPS"] == "9582197"  # still visible in the tags
    assert video.bitrate.source is BitrateSource.UNKNOWN
    assert video.frame_count is None
    assert not video.vfr
    assert source.warnings == [
        "Stream 0: the statistics tags look stale (the tracks' NUMBER_OF_BYTES add up to "
        "2397945 bytes, more than the file's 85344 bytes); not used."
    ]
