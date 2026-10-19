"""Commercial codec names: the whole map, table-driven.

The profile strings are checked against ``testdata/probes/confirmed_strings.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reframe.probe import names

CONFIRMED = Path(__file__).resolve().parents[4] / "testdata" / "probes" / "confirmed_strings.json"

AUDIO = [
    # (codec_name, profile, display name, lossless)
    ("aac", "LC", "AAC-LC", False),
    ("aac", "HE-AAC", "HE-AAC", False),
    ("aac", "HE-AACv2", "HE-AACv2", False),
    ("aac", "LD", "AAC-LD", False),
    ("aac", "ELD", "AAC-ELD", False),
    ("aac", "Main", "AAC Main", False),
    ("aac", "SSR", "AAC SSR", False),
    ("aac", "LTP", "AAC LTP", False),
    ("aac", "xHE-AAC", "xHE-AAC", False),
    ("aac", None, "AAC", False),
    ("aac_latm", "HE-AAC", "HE-AAC", False),
    ("dts", "DTS", "DTS", False),
    ("dts", "DTS-ES", "DTS-ES", False),
    ("dts", "DTS 96/24", "DTS 96/24", False),
    ("dts", "DTS-HD HRA", "DTS-HD HRA", False),
    ("dts", "DTS-HD MA", "DTS-HD MA", True),
    ("dts", "DTS-HD MA + DTS:X", "DTS:X", True),
    ("dts", "DTS-HD MA + DTS:X IMAX", "DTS:X IMAX", True),
    ("dts", "DTS Express", "DTS Express", False),
    ("dts", None, "DTS", False),
    ("eac3", "Dolby Digital Plus + Dolby Atmos", "E-AC-3 Atmos", False),
    ("eac3", None, "E-AC-3", False),
    ("truehd", "Dolby TrueHD + Dolby Atmos", "TrueHD Atmos", True),
    ("truehd", None, "TrueHD", True),
    ("mlp", None, "MLP", True),
    ("ac3", None, "AC-3", False),
    ("ac3", "unknown", "AC-3", False),
    ("flac", None, "FLAC", True),
    ("alac", None, "ALAC", True),
    ("pcm_s16le", None, "PCM", True),
    ("pcm_bluray", None, "PCM", True),
    ("opus", None, "Opus", False),
    ("vorbis", None, "Vorbis", False),
    ("mp3", None, "MP3", False),
    ("mp2", None, "MP2", False),
    ("wavpack", None, "WavPack", True),
    ("speex", None, "speex", False),  # unknown codecs keep the ffprobe name
]

VIDEO = [
    ("h264", "High", "H.264 High"),
    ("h264", "Constrained Baseline", "H.264 Constrained Baseline"),
    ("h264", "High 10", "H.264 High 10"),
    ("h264", "High 4:4:4 Predictive", "H.264 High 4:4:4 Predictive"),
    ("hevc", "Main", "HEVC Main"),
    ("hevc", "Main 10", "HEVC Main 10"),
    ("hevc", "Rext", "HEVC Rext"),
    ("av1", "Main", "AV1"),
    ("av1", "High", "AV1 High"),
    ("av1", "Professional", "AV1 Professional"),
    ("vp9", "Profile 0", "VP9"),
    ("vp9", "Profile 2", "VP9 Profile 2"),
    ("mpeg2video", "Main", "MPEG-2 Main"),
    ("mpeg2video", "4:2:2", "MPEG-2 4:2:2"),
    ("mpeg4", "Simple", "MPEG-4 Visual Simple"),
    ("vc1", None, "VC-1"),
    ("vvc", "Main 10", "VVC Main 10"),
    ("prores", "HQ", "ProRes HQ"),
    ("hevc", None, "HEVC"),
    ("hevc", "unknown", "HEVC"),
    ("cinepak", None, "cinepak"),
]

SUBTITLES = [
    ("subrip", "SRT", "text"),
    ("srt", "SRT", "text"),
    ("ass", "ASS", "text"),
    ("ssa", "SSA", "text"),
    ("webvtt", "WebVTT", "text"),
    ("mov_text", "mov_text", "text"),
    ("hdmv_pgs_subtitle", "PGS", "bitmap"),
    ("dvd_subtitle", "VobSub", "bitmap"),
    ("dvb_subtitle", "DVB", "bitmap"),
    ("xsub", "XSUB", "bitmap"),
    ("dvb_teletext", "Teletext", "text"),
    ("eia_608", "CEA-608", "text"),
    ("hdmv_text_subtitle", "HDMV Text", "text"),
    ("text", "Text", "text"),
    ("unknown_sub", "unknown_sub", "text"),
]

CONTAINERS = [
    ("matroska,webm", "a.mkv", "MKV"),
    ("matroska,webm", "a.webm", "WebM"),
    ("matroska,webm", "a.MKA", "MKA"),
    ("mov,mp4,m4a,3gp,3g2,mj2", "a.mp4", "MP4"),
    ("mov,mp4,m4a,3gp,3g2,mj2", "a.mov", "MOV"),
    ("mov,mp4,m4a,3gp,3g2,mj2", "a.m4v", "M4V"),
    ("mov,mp4,m4a,3gp,3g2,mj2", "a.m4a", "M4A"),
    ("mov,mp4,m4a,3gp,3g2,mj2", None, "MP4"),
    ("mpegts", "a.ts", "TS"),
    ("mpegts", "a.m2ts", "M2TS"),
    ("mpegts", "a.MTS", "M2TS"),
    ("mpeg", "a.vob", "VOB"),
    ("mpeg", "a.mpg", "MPEG-PS"),
    ("avi", "a.avi", "AVI"),
    ("asf", "a.wmv", "WMV"),
    ("srt", "a.srt", "SRT"),
    ("ass", "a.ass", "ASS"),
    ("nut", "a.nut", "NUT"),
    ("wav,w64", "a.wav", "WAV"),
]


@pytest.mark.parametrize(("codec", "profile", "display", "lossless"), AUDIO)
def test_audio_names(codec: str, profile: str | None, display: str, lossless: bool) -> None:
    assert names.audio_display_name(codec, profile) == display
    assert names.is_lossless_audio(codec, profile) is lossless


@pytest.mark.parametrize(("codec", "profile", "display"), VIDEO)
def test_video_names(codec: str, profile: str | None, display: str) -> None:
    assert names.video_display_name(codec, profile) == display


@pytest.mark.parametrize(("codec", "display", "kind"), SUBTITLES)
def test_subtitle_names(codec: str, display: str, kind: str) -> None:
    assert names.subtitle_display_name(codec) == display
    assert (codec in names.BITMAP_SUBTITLE_CODECS) is (kind == "bitmap")


@pytest.mark.parametrize(("format_name", "filename", "display"), CONTAINERS)
def test_container_names(format_name: str, filename: str | None, display: str) -> None:
    assert names.container_display_name(format_name, filename) == display


def test_no_codec_no_name() -> None:
    assert names.audio_display_name(None, "LC") is None
    assert names.video_display_name(None, None) is None
    assert names.subtitle_display_name(None) is None
    assert names.container_display_name(None, "a.mkv") is None
    assert not names.is_lossless_audio(None, None)


def test_every_profile_in_the_map_is_confirmed() -> None:
    confirmed = json.loads(CONFIRMED.read_text(encoding="utf-8"))["strings"]
    found = {text: hits for group in confirmed.values() for text, hits in group.items()}
    used = {profile for table in names._AUDIO_PROFILES.values() for profile in table} | set(
        names._DEFAULT_VIDEO_PROFILE.values()
    )
    used |= {profile for _, profile, _, _ in AUDIO if profile and profile != "unknown"}
    used |= {profile for _, profile, _ in VIDEO if profile and profile != "unknown"}
    for profile in sorted(used):
        hits = found.get(profile)
        assert hits, f"{profile!r} was not searched for (add it to record_probes.STRINGS)"
        assert any(k.startswith("build: lib/libavcodec") for k in hits), (profile, hits)
        assert any(k.startswith("system: ") for k in hits), (profile, hits)


def test_codec_and_side_data_names_are_confirmed() -> None:
    confirmed = json.loads(CONFIRMED.read_text(encoding="utf-8"))["strings"]
    for group in ("codec names", "codec long names", "side data types", "ffprobe fields"):
        for text, hits in confirmed[group].items():
            assert any(k.startswith("build: ") for k in hits), (group, text)
            assert any(k.startswith("system: ") for k in hits), (group, text)
