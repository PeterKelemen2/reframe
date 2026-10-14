"""C-7 "Done when", part 1: syrupy snapshots of ``EncodePlan`` for fixture jobs.

Every encoder family (all 16 video encoders), every container, burn-in (text and bitmap,
source and external), 2-pass, loudnorm, external subtitles, ranges (time, chapters, frames),
HDR → SDR (libplacebo and zscale), HDR passthrough, remux, filters, chapters, tags and
languages. The sources are the recorded probes of ``testdata/probes`` (the generated
fixtures and the real-world recordings), so the plans do not depend on the machine.

Update with ``uv run pytest packages/reframe/tests/command/test_snapshots.py
--snapshot-update`` and review the diff.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from syrupy.assertion import SnapshotAssertion

from reframe.command import build_plan
from reframe.models import (
    AudioOutputTrack,
    AverageBitrate,
    CapabilitySnapshot,
    ChapterRange,
    ChapterSettings,
    ConstantQuality,
    CropRect,
    CropSettings,
    DimensionSettings,
    EncodePlan,
    ExactWidth,
    ExternalSubtitle,
    FilterConfig,
    FilterSettings,
    FitWithin,
    FrameRange,
    JobSettings,
    MediaSource,
    NamingOptions,
    Rational,
    SameAsSource,
    SubtitleOutputTrack,
    TagSettings,
    TimeRange,
    ToolSet,
    TrackMetadata,
)

from .conftest import caps, draft, recorded, tools

Case = tuple[JobSettings, MediaSource, CapabilitySnapshot, ToolSet, dict[str, Any]]
CASES: dict[str, Callable[[], Case]] = {}


def case(fn: Callable[[], Case]) -> Callable[[], Case]:
    CASES[fn.__name__] = fn
    return fn


def plain(job: JobSettings, source: MediaSource, **kwargs: Any) -> Case:
    capabilities = kwargs.pop("caps", None) or caps()
    tool_set = kwargs.pop("tools", None) or tools()
    return job, source, capabilities, tool_set, kwargs


def encoder_case(
    encoder: str, name: str = "multitrack.mkv", *, bit_depth: int = 8, **video: Any
) -> Case:
    src = recorded(name)
    job = draft(src, video={"encoder": encoder, "bit_depth": bit_depth, **video})
    return plain(job, src)


# --------------------------------------------------------------------------- every encoder


@case
def x264_mkv_multitrack_crf() -> Case:
    return encoder_case("libx264", preset="slow", tune="film", profile="high", level="4.1")


@case
def x265_mkv_1080p_multitrack() -> Case:
    """The M2 demo: "H.265 MKV 1080p" on the multi-track fixture, all audio and subtitles."""
    return encoder_case("libx265", rate_control=ConstantQuality(value=22), preset="slow")


@case
def svtav1_mkv_10bit() -> Case:
    return encoder_case(
        "libsvtav1", bit_depth=10, preset="6", tune="0", level="4.1", fast_decode=True,
        advanced={"film-grain": 8, "film-grain-denoise": False, "enable-qm": True},
    )  # fmt: skip


@case
def vp9_webm_opus_webvtt() -> Case:
    src = recorded("multitrack.mkv")
    job = draft(src, container="webm", audio_encoder="libopus", video={"encoder": "libvpx-vp9"})
    job.video.preset = "fast"
    return plain(job, src)


@case
def h264_nvenc_mp4() -> Case:
    src = recorded("multitrack.mkv")
    job = draft(src, container="mp4", video={"encoder": "h264_nvenc", "preset": "p5", "tune": "hq"})
    job.video.advanced = {"bf": 3, "b_ref_mode": "middle", "spatial-aq": True}
    return plain(job, src)


@case
def hevc_nvenc_10bit_hdr10() -> Case:
    return encoder_case("hevc_nvenc", "hdr10", bit_depth=10, profile="main10")


@case
def av1_nvenc() -> Case:
    return encoder_case("av1_nvenc", rate_control=ConstantQuality(value=33))


@case
def h264_qsv() -> Case:
    return encoder_case("h264_qsv", preset="slow")


@case
def hevc_qsv_10bit() -> Case:
    return encoder_case("hevc_qsv", "hlg", bit_depth=10)


@case
def av1_qsv() -> Case:
    return encoder_case("av1_qsv", rate_control=AverageBitrate(kbps=4000))


@case
def h264_amf_quality() -> Case:
    return encoder_case("h264_amf", preset="quality", rate_control=ConstantQuality(value=6))


@case
def hevc_amf_10bit_hdr10() -> Case:
    return encoder_case("hevc_amf", "hdr10.mkv", bit_depth=10)


@case
def av1_amf_bitrate() -> Case:
    return encoder_case("av1_amf", rate_control=AverageBitrate(kbps=3000))


@case
def h264_vaapi() -> Case:
    return encoder_case("h264_vaapi", level="4.1", rate_control=ConstantQuality(value=22))


@case
def hevc_vaapi_10bit_second_render_node() -> Case:
    src = recorded("hdr10.mkv")
    job = draft(src, video={"encoder": "hevc_vaapi", "bit_depth": 10})
    return plain(job, src, caps=caps(devices={"hevc_vaapi": "/dev/dri/renderD129"}))


@case
def av1_vaapi() -> Case:
    return encoder_case("av1_vaapi", "anamorphic.mkv")


# --------------------------------------------------------------------------- containers


@case
def mp4_web_optimized_mov_text_ac3_passthru() -> Case:
    src = recorded("multitrack.mkv")
    job = draft(src, container="mp4", output_settings={"web_optimized": True},
                video={"encoder": "libx265"})  # fmt: skip
    job.audio[0].action = "passthru"
    job.audio[0].metadata = TrackMetadata(language="de", default=True)
    job.subtitles[0].metadata = TrackMetadata(language="hu", name="Magyar", original=True)
    return plain(job, src)


@case
def mp4_truehd_passthru_strict() -> Case:
    src = recorded("truehd-atmos")
    job = draft(src, container="mp4", audio="passthru", video={"encoder": "libx264"})
    return plain(job, src)


@case
def mp4_vobsub_copy() -> Case:
    src = recorded("vobsub.mkv")
    job = draft(src, container="mp4", video={"encoder": "libx264"})
    return plain(job, src)


@case
def webm_truehd_falls_back_to_opus() -> Case:
    src = recorded("truehd-atmos")
    job = draft(src, container="webm", audio="passthru", audio_encoder="libopus",
                video={"encoder": "libsvtav1"})  # fmt: skip
    job.audio[1].encoder = None  # no fallback named: AAC, which WebM cannot hold → see test
    job.audio[1].encoder = "libopus"
    return plain(job, src)


@case
def mkv_dts_hd_passthru_and_mixdowns() -> Case:
    src = recorded("dts-hd-ma")
    job = draft(src, audio="passthru", video={"encoder": "libx265"})
    job.audio.append(
        AudioOutputTrack(source_stream=1, encoder="ac3", mixdown="5.1", bitrate=640,
                         metadata=TrackMetadata(language="en", name="English AC-3"))
    )  # fmt: skip
    job.audio.append(
        AudioOutputTrack(source_stream=1, encoder="aac", mixdown="dpl2", samplerate=44100,
                         gain=-2.5, drc=2.0)
    )  # fmt: skip
    return plain(job, src)


@case
def audio_values_snapped_to_the_encoder() -> Case:
    """Decision 0024 item 4: what the encoder cannot do is snapped with C-6's helpers."""
    src = recorded("multitrack.mkv")  # AC-3 5.1(side), AAC stereo, AAC stereo commentary
    job = draft(src, video={"encoder": "libx264"}, subtitles=False)
    a0, a1, a2 = job.audio
    # 5.1 source: no upmix to 7.1 (relabel to 5.1), 700 → 640 kb/s, 96 → 48 kHz.
    a0.encoder, a0.mixdown, a0.bitrate, a0.samplerate = "ac3", "7.1", 700, 96000
    # Stereo source: no upmix to 5.1, so the stereo default (160 kb/s), not the 5.1 one.
    a1.encoder, a1.mixdown = "aac", "5.1"
    # Stereo source: nothing to matrix-encode; 600 → 512 kb/s; 44.1 → 48 kHz.
    a2.encoder, a2.mixdown, a2.bitrate, a2.samplerate = "libopus", "dpl2", 600, 44100
    job.audio += [
        # MP3 makes stereo of the 5.1 source; 330 → 320 kb/s.
        AudioOutputTrack(source_stream=1, encoder="libmp3lame", bitrate=330),
        # E-AC-3 has no 7.1 and the source is 5.1 anyway; 100 → the 5.1 minimum, 224 kb/s.
        AudioOutputTrack(source_stream=1, encoder="eac3", mixdown="7.1", bitrate=100),
    ]
    return plain(job, src)


@case
def audio_71_source_snapped() -> Case:
    """A 7.1 source (the TrueHD Atmos probe with eight channels): AC-3 and E-AC-3 make 5.1,
    MP3 stereo, Opus keeps 7.1; the passthru track is copied, never snapped."""
    src = recorded("truehd-atmos")
    seven = src.audio[0].model_copy(update={"channels": 8, "channel_layout": "7.1"})
    src = src.model_copy(update={"audio": [seven, *src.audio[1:]]})
    job = draft(src, video={"encoder": "libx265"}, subtitles=False)
    index = seven.index
    job.audio = [
        AudioOutputTrack(source_stream=index, encoder="ac3", mixdown="7.1"),
        AudioOutputTrack(source_stream=index, encoder="eac3", bitrate=700),
        AudioOutputTrack(source_stream=index, encoder="libmp3lame", mixdown="5.1",
                         samplerate=96000),
        AudioOutputTrack(source_stream=index, encoder="libopus", samplerate=44100),
        AudioOutputTrack(source_stream=index, action="passthru", encoder="ac3", mixdown="5.1",
                         bitrate=700),
    ]  # fmt: skip
    return plain(job, src)


@case
def audio_quality_flac_and_mp3() -> Case:
    src = recorded("ass-fonts")
    job = draft(src, video={"encoder": "libx264"})
    job.audio[0].encoder = "flac"
    job.audio[1].encoder = "libmp3lame"
    job.audio[1].quality = 2
    job.audio[1].samplerate = 96000
    return plain(job, src)


# --------------------------------------------------------------------------- burn-in


@case
def burn_text_subtitle_from_source() -> Case:
    src = recorded("multitrack.mkv")
    job = draft(src, video={"encoder": "libx264"})
    job.subtitles[2].action = "burn"
    return plain(job, src)


@case
def burn_ass_with_fonts_and_range() -> Case:
    src = recorded("ass-fonts")
    job = draft(src, video={"encoder": "libx265"})
    job.subtitles[0].action = "burn"
    job.range = TimeRange(start=1.5, end=3.0)
    return plain(job, src)


@case
def burn_pgs_forced_only_with_crop() -> Case:
    src = recorded("pgs")
    job = draft(src, video={"encoder": "libx265"})
    job.dimensions = DimensionSettings(
        crop=CropSettings(mode="manual", rect=CropRect(top=140, bottom=140, left=0, right=0))
    )
    job.subtitles[1].action = "burn"
    job.subtitles[1].forced_only = True
    return plain(job, src)


@case
def burn_vobsub_bitmap() -> Case:
    src = recorded("vobsub.mkv")
    job = draft(src, video={"encoder": "libx264"})
    job.subtitles[1].action = "burn"
    return plain(job, src)


@case
def burn_external_srt_special_characters_windows_display() -> Case:
    """Every character the filter graph parser treats specially, in the subtitle's path; the
    display quoted for Windows. (Windows paths themselves: ``test_filtergraph.py``.)"""
    src = recorded("multitrack.mkv")
    job = draft(src, video={"encoder": "libx264"}, subtitles=False)
    ext = ExternalSubtitle(
        path=Path("/media/Movies/It's: a [test], ok; 100% \\ \"quoted\".srt"),
        offset_ms=-250, charset="cp1250",
    )  # fmt: skip
    job.subtitles = [SubtitleOutputTrack(source=ext, action="burn")]
    job.range = TimeRange(start=1.0)
    return plain(job, src, shell="windows")


@case
def burn_external_sup_forced() -> Case:
    src = recorded("pgs")
    job = draft(src, video={"encoder": "libx264"}, subtitles=False)
    ext = ExternalSubtitle(path=Path("/media/forced.sup"), offset_ms=1000)
    job.subtitles = [SubtitleOutputTrack(source=ext, action="burn", forced_only=True)]
    return plain(job, src)


# --------------------------------------------------------------------------- 2-pass


@case
def x264_two_pass_turbo() -> Case:
    return encoder_case(
        "libx264", rate_control=AverageBitrate(kbps=2500, two_pass=True, turbo_first_pass=True)
    )


@case
def x265_two_pass_full() -> Case:
    return encoder_case("libx265", rate_control=AverageBitrate(kbps=2000, two_pass=True))


@case
def svtav1_two_pass() -> Case:
    return encoder_case("libsvtav1", rate_control=AverageBitrate(kbps=1500, two_pass=True))


@case
def nvenc_multipass_single_run() -> Case:
    return encoder_case(
        "hevc_nvenc", rate_control=AverageBitrate(kbps=5000, two_pass=True, turbo_first_pass=True)
    )


@case
def x265_two_pass_stats_path_with_colon_windows_display() -> Case:
    src = recorded("multitrack.mkv")
    job = draft(src, video={"encoder": "libx265",
                            "rate_control": AverageBitrate(kbps=2000, two_pass=True)})  # fmt: skip
    job.output.path = Path("/out/Show: S01E01 'Pilot'.mkv")
    return plain(job, src, shell="windows")


# --------------------------------------------------------------------------- loudness


@case
def loudnorm_ebu_dpl2_gain() -> Case:
    src = recorded("multitrack.mkv")
    job = draft(src, video={"encoder": "libx265"}, subtitles=False)
    job.audio[0].loudness = "ebu_r128"
    job.audio[0].mixdown = "dpl2"
    job.audio[0].gain = 1.5
    return plain(job, src)


@case
def loudnorm_two_tracks_with_two_pass() -> Case:
    """The 2-pass + loudnorm job of the report."""
    src = recorded("multitrack.mkv")
    job = draft(src, video={"encoder": "libx264",
                            "rate_control": AverageBitrate(kbps=1800, two_pass=True)})  # fmt: skip
    job.audio[0].loudness = "streaming"
    job.audio[1].loudness = "ebu_r128"
    job.range = TimeRange(start=0.5, end=3.5)
    return plain(job, src)


# --------------------------------------------------------------------------- external subtitles


@case
def external_subtitles_copy_mkv() -> Case:
    src = recorded("multitrack.mkv")
    job = draft(src, video={"encoder": "libx264"})
    job.subtitles += [
        SubtitleOutputTrack(
            source=ExternalSubtitle(path=Path("/media/ext/film.hu.srt"), language="hu",
                                    offset_ms=1500, charset="ISO-8859-2"),
            metadata=TrackMetadata(language="hu", default=True),
        ),
        SubtitleOutputTrack(
            source=ExternalSubtitle(path=Path("/media/ext/film.en.ass"), name="Fansub"),
            metadata=TrackMetadata(language="en"),
        ),
        SubtitleOutputTrack(source=ExternalSubtitle(path=Path("/media/ext/film.sup"))),
    ]  # fmt: skip
    return plain(job, src)


@case
def external_srt_into_mp4_with_range() -> Case:
    src = recorded("multitrack.mkv")
    job = draft(src, container="mp4", video={"encoder": "libx264"}, subtitles=False)
    job.subtitles = [
        SubtitleOutputTrack(source=ExternalSubtitle(path=Path("/media/film.srt"), offset_ms=200),
                            metadata=TrackMetadata(language="de"))
    ]  # fmt: skip
    job.range = TimeRange(start=2.0, end=3.0)
    return plain(job, src)


# --------------------------------------------------------------------------- ranges and chapters


@case
def time_range_copies_chapters() -> Case:
    src = recorded("chapters.mkv")
    job = draft(src, video={"encoder": "libx264"})
    job.range = TimeRange(start=1.2, end=3.2)
    return plain(job, src)


@case
def chapter_range_renamed() -> Case:
    src = recorded("chapters.mkv")
    job = draft(src, video={"encoder": "libx264"})
    job.range = ChapterRange(start=2, end=3)
    job.chapters = ChapterSettings(names=["Intro", "Erste; Teil = 1", "", "End"])
    return plain(job, src)


@case
def frame_range() -> Case:
    src = recorded("multitrack.mkv")
    job = draft(src, video={"encoder": "libx264"})
    job.range = FrameRange(start=10, end=60)
    return plain(job, src)


@case
def generated_chapters() -> Case:
    src = recorded("truehd-atmos")
    job = draft(src, video={"encoder": "libx264"})
    job.chapters = ChapterSettings(generate_every=0.5 / 60)
    return plain(job, src)


@case
def chapters_off() -> Case:
    src = recorded("chapters.mkv")
    job = draft(src, video={"encoder": "libx264"})
    job.chapters = ChapterSettings(enabled=False)
    return plain(job, src)


# --------------------------------------------------------------------------- HDR


@case
def hdr10_to_sdr_libplacebo() -> Case:
    src = recorded("hdr10")
    job = draft(src, video={"encoder": "libx264"})
    job.filters = FilterSettings({"tonemap": FilterConfig(tune="hable")})
    return plain(job, src)


@case
def hdr10_to_sdr_zscale_without_vulkan() -> Case:
    src = recorded("hdr10")
    job = draft(src, video={"encoder": "libx265"})
    job.filters = FilterSettings(
        {"tonemap": FilterConfig(), "sharpen": FilterConfig(preset="light")}
    )
    return plain(job, src, caps=caps(libplacebo=False))


@case
def hdr10_x265_passthrough() -> Case:
    return encoder_case("libx265", "hdr10", bit_depth=10, advanced={"hdr10-opt": True})


@case
def hdr10_svtav1_passthrough() -> Case:
    return encoder_case("libsvtav1", "hdr10", bit_depth=10)


@case
def hlg_x265_passthrough() -> Case:
    return encoder_case("libx265", "hlg", bit_depth=10)


@case
def dolby_vision_p8_to_x265() -> Case:
    return encoder_case("libx265", "dv-p8", bit_depth=10, advanced={"max-cll": "800,300"})


@case
def hdr10_sei_only_to_8bit_x264() -> Case:
    return encoder_case("libx264", "hdr10-sei-only")


# --------------------------------------------------------------------------- remux


@case
def remux_mkv_to_mp4() -> Case:
    src = recorded("multitrack.mkv")
    job = draft(src, container="mp4", audio="passthru")
    job.video.passthrough = True
    return plain(job, src)


@case
def remux_mkv_with_ass_fonts() -> Case:
    src = recorded("ass-fonts")
    job = draft(src, audio="passthru")
    job.video.passthrough = True
    return plain(job, src)


@case
def video_passthrough_hevc_into_mp4_with_encoded_audio() -> Case:
    src = recorded("hdr10")
    job = draft(src, container="mp4", audio="encode", audio_encoder="eac3")
    job.video.passthrough = True
    return plain(job, src)


# --------------------------------------------------------------------------- dimensions, filters


@case
def anamorphic_dvd_square_pixels() -> Case:
    src = recorded("anamorphic.mkv")
    job = draft(src, video={"encoder": "libx264"})
    job.dimensions = DimensionSettings(size=SameAsSource(), scaler="spline")
    return plain(job, src)


@case
def anamorphic_keep_par_exact_width() -> Case:
    src = recorded("anamorphic.mkv")
    job = draft(src, video={"encoder": "libx264"})
    job.dimensions = DimensionSettings(size=ExactWidth(width=640), pixel_aspect="keep", modulus=16)
    return plain(job, src)


@case
def interlaced_all_filters() -> Case:
    src = recorded("interlaced.mkv")
    job = draft(src, video={"encoder": "libx264"})
    job.filters = FilterSettings(
        {
            "grayscale": FilterConfig(),
            "detelecine": FilterConfig(),
            "interlace_detection": FilterConfig(preset="permissive"),
            "deinterlace": FilterConfig(implementation="yadif", preset="bob"),
            "denoise": FilterConfig(preset="medium", tune="animation"),
            "deblock": FilterConfig(preset="strong", tune="small"),
            "sharpen": FilterConfig(implementation="cas", preset="medium"),
            "chroma_smooth": FilterConfig(preset="light", tune="wide"),
            "custom": FilterConfig(preset="default", custom="eq=gamma=1.1"),
        }
    )
    return plain(job, src)


@case
def letterbox_crop_rotate_flip() -> Case:
    src = recorded("letterbox.mkv")
    job = draft(src, video={"encoder": "libx264"})
    job.dimensions = DimensionSettings(
        rotate=90, flip_horizontal=True, size=FitWithin(width=1280, height=720),
        crop=CropSettings(mode="manual", rect=CropRect(top=22, bottom=24, left=0, right=0)),
        pixel_aspect="custom", custom_par=Rational(num=1, den=1),
    )  # fmt: skip
    return plain(job, src)


@case
def phone_rotated_source() -> Case:
    return encoder_case("libx265", "phone-rotated")


@case
def dvd_interlaced_untagged_colorspace() -> Case:
    src = recorded("dvd-interlaced")
    job = draft(src, video={"encoder": "libx264"})
    job.filters = FilterSettings(
        {"deinterlace": FilterConfig(), "colorspace": FilterConfig(preset="bt709")}
    )
    return plain(job, src)


@case
def frame_rates_constant_and_peak() -> Case:
    src = recorded("vfr.mp4")
    job = draft(src, video={"encoder": "libx264", "framerate_mode": "constant"})
    return plain(job, src)


@case
def frame_rate_peak_30() -> Case:
    src = recorded("vfr")
    job = draft(src, video={"encoder": "libx264", "framerate_mode": "peak",
                            "framerate": Rational(num=30, den=1)})  # fmt: skip
    return plain(job, src)


# --------------------------------------------------------------------------- metadata


@case
def languages_flags_and_ietf() -> Case:
    src = recorded("multitrack.mkv")
    job = draft(src, video={"encoder": "libx264"})
    job.video.metadata = TrackMetadata(default=True, name="Main", language="ja")
    job.audio[0].metadata = TrackMetadata(language="pt-BR", default=True, original=True)
    job.audio[1].metadata = TrackMetadata(language="yue", visual_impaired=True)
    job.audio[2].metadata = TrackMetadata(language="zh-Hant", commentary=True, name="")
    job.subtitles[0].metadata = TrackMetadata(
        language="sr-Latn", default=True, forced=True, commentary=True,
        hearing_impaired=True, visual_impaired=True, original=True,
    )  # fmt: skip
    return plain(job, src)


@case
def languages_mp4_drops_original_flag() -> Case:
    src = recorded("multitrack.mkv")
    job = draft(src, container="mp4", video={"encoder": "libx264"})
    job.audio[0].metadata = TrackMetadata(language="de", default=True, original=True)
    job.subtitles[0].metadata = TrackMetadata(language="zh-Hant", original=True)
    return plain(job, src)


@case
def tags_with_naming_variables() -> Case:
    src = recorded("multitrack.mkv", path=Path("/media/Show.S01E02.Title.mkv"))
    job = draft(src, video={"encoder": "libx265"})
    job.output.passthru_metadata = False
    job.tags = TagSettings(
        title="{name}< \u2013 S{season:02}E{episode:02}>", actors="A, B", director="D",
        release_date="{date:%Y}", comment="{{literal}}", genre="Drama", description="",
        plot="Plot / more",
    )  # fmt: skip
    return plain(job, src, now=datetime(2026, 10, 13, 12, 0, tzinfo=UTC),
                 naming=NamingOptions(word_separator="space"))  # fmt: skip


@case
def stale_stats_source() -> Case:
    return encoder_case("libx264", "stale-stats")


@case
def eac3_atmos_without_mkvpropedit() -> Case:
    src = recorded("eac3-atmos")
    job = draft(src, audio="passthru", video={"encoder": "libx264"})
    job.subtitles[0].metadata = TrackMetadata(language="pt-BR")
    return plain(job, src, tools=tools(mkvpropedit=False))


@case
def x264_advanced_and_custom_params() -> Case:
    return encoder_case(
        "libx264", preset="veryslow", tune="animation", fast_decode=True,
        advanced={"psy-rd": 0.8, "deblock-alpha": -1, "deblock-beta": -1, "bframes": 8,
                  "aq-mode": "0", "aq-strength": 1.2, "unknown-option": 3},
        custom_params="no-dct-decimate=1:nr=100",
    )  # fmt: skip


@case
def x265_advanced_composite_defaults() -> Case:
    return encoder_case(
        "libx265", preset="slow", advanced={"deblock-tc": -2, "sao": False, "rd": 4},
        custom_params=":limit-tu=4:",
    )  # fmt: skip


@case
def posix_display_with_tool_paths() -> Case:
    src = recorded("multitrack.mkv", path=Path("/media/My Films/It's here (2024).mkv"))
    job = draft(src, video={"encoder": "libx264"}, output=Path("/out/It's here (2024).mkv"))
    tool_paths = {"ffmpeg": Path("/opt/reframe/tools/ffmpeg/bin/ffmpeg")}
    return plain(job, src, tools=tools(paths=tool_paths))  # type: ignore[arg-type]


# --------------------------------------------------------------------------- the snapshots


def test_there_are_at_least_40_fixture_jobs() -> None:
    assert len(CASES) >= 40


@pytest.mark.parametrize("name", sorted(CASES))
def test_plan_snapshot(name: str, snapshot: SnapshotAssertion) -> None:
    job, source, capabilities, tool_set, kwargs = CASES[name]()
    plan = build_plan(job, source, capabilities, tool_set, **kwargs)
    assert plan.model_dump(mode="json") == snapshot
    assert EncodePlan.model_validate_json(plan.model_dump_json()) == plan
