"""Each rule has a positive and a negative case in :data:`CASES`; every fix removes its issue.

A positive case is a change of the clean scenario that must produce a code at a path; its
negative case is a close change that must not. ``scenario.check`` applies every fix of every
issue and validates again: the issue (same code and path) must be gone.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from reframe.definitions import Definitions
from reframe.models import (
    AverageBitrate,
    ChapterRange,
    ColorInfo,
    CropRect,
    CropSettings,
    EncoderState,
    EncoderStatus,
    ExternalSubtitle,
    FilterConfig,
    FilterSettings,
    FitWithin,
    Fix,
    FrameRange,
    HdrFormat,
    HdrInfo,
    NamingOptions,
    Rational,
    RemoveOp,
    Severity,
    SubtitleOutputTrack,
    TimeRange,
    ToolOrigin,
    ToolStatus,
)
from reframe.validation import JOB_RULES, TEMPLATE_RULES

from . import cases_inplace, cases_metadata, cases_options
from . import scenario as sc
from .scenario import Case, Mod, both

DEFS: Definitions = sc.DEFS
ERR, WARN, INFO = Severity.ERROR, Severity.WARNING, Severity.INFO
#: A name Windows does not allow: an error for a Windows path, a warning elsewhere.
NOT_PORTABLE = ERR if sys.platform == "win32" else WARN


def build(mod: Mod) -> Any:
    scenario = sc.base()
    mod(scenario)
    return scenario


def video(**changes: Any) -> Mod:
    def mod(s: Any) -> None:
        for key, value in changes.items():
            setattr(s.job.video, key, value)

    return mod


def caps(states: dict[str, Any], **kw: Any) -> Mod:
    def mod(s: Any) -> None:
        s.caps = sc.make_caps(states, **kw)

    return mod


def container(value: str) -> Mod:
    def mod(s: Any) -> None:
        s.job.output.container = value

    return mod


def one_audio(s: Any) -> None:
    s.job.audio = s.job.audio[:1]


def webm(s: Any) -> None:
    s.job.output.container = "webm"
    s.job.output.path = Path("/out/Movie (2019).webm")
    s.job.audio = s.job.audio[:1]
    s.job.audio[0].encoder = "libopus"
    s.job.subtitles = []


def audio(index: int, **changes: Any) -> Mod:
    def mod(s: Any) -> None:
        for key, value in changes.items():
            setattr(s.job.audio[index], key, value)

    return mod


def subs(*tracks: SubtitleOutputTrack) -> Mod:
    def mod(s: Any) -> None:
        s.job.subtitles = list(tracks)

    return mod


def sub(index: int, **changes: Any) -> Mod:
    def mod(s: Any) -> None:
        for key, value in changes.items():
            setattr(s.job.subtitles[index], key, value)

    return mod


def crop(mode: str, rect: CropRect | None = None, detection_error: str | None = None) -> Mod:
    def mod(s: Any) -> None:
        s.job.dimensions.crop = CropSettings(
            mode=mode,  # type: ignore[arg-type]
            rect=rect,
            detection_error=detection_error,
        )

    return mod


def dims(**changes: Any) -> Mod:
    def mod(s: Any) -> None:
        for key, value in changes.items():
            setattr(s.job.dimensions, key, value)

    return mod


def filters(**configs: FilterConfig) -> Mod:
    def mod(s: Any) -> None:
        s.job.filters = FilterSettings(dict(configs))

    return mod


def job_range(value: Any) -> Mod:
    def mod(s: Any) -> None:
        s.job.range = value

    return mod


def output_path(value: Path | None) -> Mod:
    def mod(s: Any) -> None:
        s.job.output.path = value

    return mod


def naming(**changes: Any) -> Mod:
    def mod(s: Any) -> None:
        for key, value in changes.items():
            setattr(s.job.output.naming, key, value)

    return mod


def settings_naming(**changes: Any) -> Mod:
    def mod(s: Any) -> None:
        s.settings.output.naming = NamingOptions(**changes)

    return mod


def collision(policy: str) -> Mod:
    def mod(s: Any) -> None:
        s.settings.output.collision = policy

    return mod


def output_exists(s: Any) -> None:
    s.fs.add_file(sc.OUTPUT)


def defs(change: Callable[[Definitions], None]) -> Mod:
    def mod(s: Any) -> None:
        copy = DEFS.model_copy(deep=True)
        change(copy)
        s.definitions = copy

    return mod


def ffmpeg_status(status: ToolStatus) -> Mod:
    """ffmpeg from a Settings path with ``status``; "Use bundled" removes the path, and the
    rediscovery then finds the bundled ffmpeg."""

    def mod(s: Any) -> None:
        use_bundled = Fix(
            label="Use bundled FFmpeg",
            patch=[RemoveOp(path="/tools/ffmpeg")],
            target="settings",
        )
        s.settings.tools.ffmpeg = Path("/opt/old/ffmpeg")
        s.tools = sc.make_tools(
            ffmpeg=sc.tool(
                "ffmpeg",
                status,
                origin=ToolOrigin.SETTINGS,
                reason="the path in Settings → Tools",
                fixes=[use_bundled],
            )
        )
        bad = s.tools
        s.rediscover = lambda settings: sc.make_tools() if settings.tools.ffmpeg is None else bad

    return mod


def hdr_source(s: Any) -> None:
    s.source.video[0].color = ColorInfo(primaries="bt2020", transfer="smpte2084", matrix="bt2020nc")


def hdr10_source(s: Any) -> None:
    """HDR10 as the probe reports it: the format list, not only the transfer."""
    hdr_source(s)
    s.source.video[0].hdr = HdrInfo(formats=[HdrFormat.HDR10])


def hlg_source(s: Any) -> None:
    s.source.video[0].color = ColorInfo(
        primaries="bt2020", transfer="arib-std-b67", matrix="bt2020nc"
    )
    s.source.video[0].hdr = HdrInfo(formats=[HdrFormat.HLG])


def webm_video(s: Any) -> None:
    s.job.video.encoder = "libsvtav1"
    s.job.output.path = Path("/out/Movie (2019).webm")
    s.job.subtitles = []
    s.job.audio = s.job.audio[1:]
    s.job.audio[0].encoder = "libopus"


TALL = FitWithin(width=1920, height=1160)


def rechecking(s: Any) -> None:
    """A cached snapshot that detection checks again (from_cache and detecting)."""
    s.caps = s.caps.model_copy(update={"from_cache": True, "detecting": True})


def tall_source(s: Any) -> None:
    s.source.video[0].height = 1160


def aligned_with_late_copy(late: float) -> Mod:
    def mod(s: Any) -> None:
        s.job.output.align_av_start = True
        s.source.video[0].start_time = 0.0
        s.source.audio[0].start_time = 0.0
        s.source.audio[1].start_time = late  # the passthru AAC track

    return mod


def narrow_source(s: Any) -> None:
    s.source.video[0].width = 318
    s.source.video[0].height = 720


def x265_level(level: str, **video_changes: Any) -> Mod:
    def mod(s: Any) -> None:
        s.job.video.level = level
        for key, value in video_changes.items():
            setattr(s.job.video, key, value)

    return mod


def nothing(s: Any) -> None:
    del s


def no_frame_rate(s: Any) -> None:
    s.source.video[0].frame_rate = None
    s.source.video[0].avg_frame_rate = None


def x265_without_quality(d: Definitions) -> None:
    d.video_encoders["libx265"].rate_control.quality = None


def x265_without_bitrate(d: Definitions) -> None:
    d.video_encoders["libx265"].rate_control.bitrate = None


def mkv_without_text_copy(d: Definitions) -> None:
    mkv = d.containers["mkv"]
    mkv.text_subtitle_target = None
    mkv.subtitles.copy_codecs = ["hdmv_pgs_subtitle"]


def deblock_needs_tune(d: Definitions) -> None:
    preset = d.filters["deblock"].implementations[0].preset("medium")
    assert preset is not None
    preset.chain = None


UNTESTED_NVENC = EncoderStatus(
    id="hevc_nvenc",
    state=EncoderState.UNKNOWN,
    in_build=True,
    hardware=True,
    reason="Not tested: hardware test encodes are off (Settings → Encoders)",
)
NVENC_NO_10BIT = EncoderStatus(
    id="hevc_nvenc",
    state=EncoderState.AVAILABLE,
    in_build=True,
    hardware=True,
    supports_10bit=False,
    reason_10bit="10-bit is not supported by this GPU",
)
NVENC_FEW_PRESETS = EncoderStatus(
    id="hevc_nvenc",
    state=EncoderState.AVAILABLE,
    in_build=True,
    presets=["p1", "p2", "p3", "p4"],
)
NVENC_OPTIONS = ["preset", "tune", "rc", "cq", "multipass", "spatial-aq"]


def nvenc_options(options: list[str]) -> Mod:
    return caps(
        {
            "hevc_nvenc": EncoderStatus(
                id="hevc_nvenc",
                state=EncoderState.AVAILABLE,
                in_build=True,
                private_options=options,
            )
        }
    )


SRT, PGS = 0, 1  # subtitle output tracks of the clean job
EXTERNAL = Path("/media/movies/Movie.2019.en.srt")

CASES: list[Case] = [
    Case(
        "ffmpeg missing",
        "tool.missing",
        "",
        ERR,
        ffmpeg_status(ToolStatus.MISSING),
        nothing,
    ),
    Case(
        "ffmpeg too old",
        "tool.too_old",
        "",
        ERR,
        ffmpeg_status(ToolStatus.TOO_OLD),
        nothing,
    ),
    Case(
        "ffmpeg broken",
        "tool.broken",
        "",
        ERR,
        ffmpeg_status(ToolStatus.BROKEN),
        nothing,
    ),
    Case(
        "unknown video encoder",
        "encoder.unknown",
        "video.encoder",
        ERR,
        video(encoder="libx999"),
        video(encoder="libx264"),
    ),
    Case(
        "video encoder checking",
        "encoder.checking",
        "video.encoder",
        INFO,
        caps({"libx265": EncoderState.CHECKING}),
        nothing,
    ),
    Case(
        "video encoder untested",
        "encoder.untested",
        "video.encoder",
        WARN,
        both(video(encoder="hevc_nvenc"), caps({"hevc_nvenc": UNTESTED_NVENC})),
        video(encoder="hevc_nvenc"),
    ),
    Case(
        "video encoder unavailable",
        "encoder.unavailable",
        "video.encoder",
        ERR,
        both(
            video(encoder="hevc_nvenc", preset="p5", tune="uhq", advanced={"b_ref_mode": "each"}),
            caps({"hevc_nvenc": EncoderState.UNAVAILABLE}),
        ),
        video(encoder="hevc_nvenc", preset="p5"),
    ),
    Case(
        "video encoder unavailable, bitrate",
        "encoder.unavailable",
        "video.encoder",
        ERR,
        both(
            video(encoder="h264_nvenc", rate_control=AverageBitrate(kbps=8000, two_pass=True)),
            caps(
                {
                    "h264_nvenc": EncoderState.UNAVAILABLE,
                    "h264_qsv": EncoderState.UNAVAILABLE,
                    "h264_amf": EncoderState.UNAVAILABLE,
                    "h264_vaapi": EncoderState.ERROR,
                }
            ),
        ),
        video(encoder="h264_nvenc"),
    ),
    Case(
        "audio encoder unavailable",
        "encoder.unavailable",
        "audio[0].encoder",
        ERR,
        both(
            audio(0, encoder="libfdk_aac", bitrate=560),
            caps({"libfdk_aac": EncoderState.UNAVAILABLE}),
        ),
        audio(0, encoder="libfdk_aac", bitrate=560),
    ),
    Case(
        "passthru fallback unavailable",
        "encoder.unavailable",
        "audio[1].encoder",
        ERR,
        both(
            container("mp4"),
            lambda s: setattr(s.source.audio[1], "codec", "vorbis"),
            audio(1, encoder="libfdk_aac"),
            caps({"libfdk_aac": EncoderState.UNAVAILABLE}),
        ),
        both(audio(1, encoder="libfdk_aac"), caps({"libfdk_aac": EncoderState.UNAVAILABLE})),
    ),
    Case(
        "10-bit on an 8-bit encoder",
        "encoder.no_10bit",
        "video.bit_depth",
        ERR,
        video(encoder="h264_qsv", bit_depth=10, profile="main"),
        video(encoder="libx265", bit_depth=10),
    ),
    Case(
        "10-bit test failed",
        "encoder.no_10bit",
        "video.bit_depth",
        ERR,
        both(
            video(encoder="hevc_nvenc", bit_depth=10, profile="main10"),
            caps({"hevc_nvenc": NVENC_NO_10BIT}),
        ),
        both(video(encoder="hevc_nvenc", bit_depth=8), caps({"hevc_nvenc": NVENC_NO_10BIT})),
    ),
    Case(
        "cached 10-bit failure checked again",
        "encoder.checking",
        "video.bit_depth",
        INFO,
        both(
            video(encoder="hevc_nvenc", bit_depth=10, profile="main10"),
            caps({"hevc_nvenc": NVENC_NO_10BIT}),
            rechecking,
        ),
        both(
            video(encoder="hevc_nvenc", bit_depth=10, profile="main10"),
            caps({"hevc_nvenc": NVENC_NO_10BIT}),
        ),
    ),
    Case(
        "x265 lookahead not above the B-frames",
        "encoder.lookahead_too_short",
        "video.advanced.rc-lookahead",
        ERR,
        video(encoder="libx265", advanced={"rc-lookahead": 4, "bframes": 4}),
        video(encoder="libx265", advanced={"rc-lookahead": 5, "bframes": 4}),
    ),
    Case(
        "x265 preset lookahead with more B-frames",
        "encoder.lookahead_too_short",
        "video.advanced.rc-lookahead",
        ERR,
        video(encoder="libx265", preset="ultrafast", advanced={"bframes": 5}),
        video(encoder="libx265", preset="ultrafast", advanced={"bframes": 4}),
    ),
    Case(
        "x265 no lookahead with B-frames",
        "encoder.lookahead_too_short",
        "video.advanced.rc-lookahead",
        ERR,
        video(encoder="libx265", tune="zerolatency", advanced={"bframes": 3}),
        video(encoder="libx265", tune="zerolatency"),
    ),
    Case(
        "x265 animation tune adds B-frames",
        "encoder.lookahead_too_short",
        "video.advanced.rc-lookahead",
        ERR,
        video(encoder="libx265", preset="slower", tune="animation", advanced={"rc-lookahead": 6}),
        video(encoder="libx265", preset="slower", tune="animation", advanced={"rc-lookahead": 11}),
    ),
    Case(
        "x264 subme 10 without trellis 2",
        "encoder.subme_needs_trellis",
        "video.advanced.subme",
        WARN,
        video(encoder="libx264", advanced={"subme": 10, "trellis": "1"}),
        video(encoder="libx264", advanced={"subme": 10, "trellis": "2"}),
    ),
    Case(
        "x264 veryslow with trellis 0",
        "encoder.subme_needs_trellis",
        "video.advanced.subme",
        WARN,
        video(encoder="libx264", preset="veryslow", advanced={"trellis": "0"}),
        video(encoder="libx264", preset="veryslow"),
    ),
    Case(
        "unknown speed preset",
        "encoder.preset_unsupported",
        "video.preset",
        ERR,
        video(preset="p5"),
        video(preset="slow"),
    ),
    Case(
        "preset not in this build",
        "encoder.preset_unsupported",
        "video.preset",
        ERR,
        both(video(encoder="hevc_nvenc", preset="p7"), caps({"hevc_nvenc": NVENC_FEW_PRESETS})),
        both(video(encoder="hevc_nvenc", preset="p4"), caps({"hevc_nvenc": NVENC_FEW_PRESETS})),
    ),
    Case(
        "unknown tune",
        "encoder.tune_unsupported",
        "video.tune",
        ERR,
        video(tune="film"),
        video(tune="grain"),
    ),
    Case(
        "encoder without tunes",
        "encoder.tune_unsupported",
        "video.tune",
        ERR,
        video(encoder="h264_qsv", tune="hq"),
        video(encoder="h264_qsv"),
    ),
    Case(
        "profile for another bit depth",
        "encoder.profile_unsupported",
        "video.profile",
        ERR,
        video(profile="main10"),
        video(profile="main10", bit_depth=10),
    ),
    Case(
        "unknown level",
        "encoder.level_unsupported",
        "video.level",
        ERR,
        video(level="9.9"),
        video(level="4.1"),
    ),
    Case(
        "unknown advanced option",
        "encoder.option_unknown",
        "video.advanced.nonsense",
        ERR,
        video(advanced={"nonsense": 1}),
        video(advanced={"bframes": 4}),
    ),
    Case(
        "option not in this build",
        "encoder.option_unsupported",
        "video.advanced.b_ref_mode",
        ERR,
        both(
            video(encoder="hevc_nvenc", advanced={"b_ref_mode": "each"}),
            nvenc_options(NVENC_OPTIONS),
        ),
        both(
            video(encoder="hevc_nvenc", advanced={"b_ref_mode": "each"}),
            nvenc_options([*NVENC_OPTIONS, "b_ref_mode"]),
        ),
    ),
    Case(
        "option out of range",
        "encoder.option_invalid",
        "video.advanced.bframes",
        ERR,
        video(advanced={"bframes": 40}),
        video(advanced={"bframes": 8}),
    ),
    Case(
        "option not a choice",
        "encoder.option_invalid",
        "video.advanced.aq-mode",
        ERR,
        video(advanced={"aq-mode": "9"}),
        video(advanced={"aq-mode": "3"}),
    ),
    Case(
        "no constant quality",
        "encoder.rate_control_unsupported",
        "video.rate_control",
        ERR,
        defs(x265_without_quality),
        both(defs(x265_without_quality), video(rate_control=AverageBitrate())),
    ),
    Case(
        "no average bitrate",
        "encoder.rate_control_unsupported",
        "video.rate_control",
        ERR,
        both(defs(x265_without_bitrate), video(rate_control=AverageBitrate())),
        defs(x265_without_bitrate),
    ),
    Case(
        "quality out of range",
        "encoder.quality_out_of_range",
        "video.rate_control.value",
        ERR,
        lambda s: setattr(s.job.video.rate_control, "value", 60.0),
        lambda s: setattr(s.job.video.rate_control, "value", 51.0),
    ),
    Case(
        "bitrate out of range",
        "encoder.bitrate_out_of_range",
        "video.rate_control.kbps",
        ERR,
        video(rate_control=AverageBitrate(kbps=50)),
        video(rate_control=AverageBitrate(kbps=100)),
    ),
    Case(
        "2-pass unsupported",
        "encoder.two_pass_unsupported",
        "video.rate_control.two_pass",
        ERR,
        video(
            encoder="h264_qsv", rate_control=AverageBitrate(two_pass=True, turbo_first_pass=True)
        ),
        video(rate_control=AverageBitrate(two_pass=True)),
    ),
    Case(
        "NVENC H.265 level 4.1 above its bitrate",
        "encoder.level_bitrate_too_high",
        "video.rate_control.kbps",
        ERR,
        video(encoder="hevc_nvenc", level="4.1", rate_control=AverageBitrate(kbps=11001)),
        video(encoder="hevc_nvenc", level="4.1", rate_control=AverageBitrate(kbps=11000)),
    ),
    Case(
        "NVENC H.265 High tier level 4.1 above its bitrate",
        "encoder.level_bitrate_too_high",
        "video.rate_control.kbps",
        ERR,
        video(
            encoder="hevc_nvenc",
            level="4.1",
            advanced={"tier": "high"},
            rate_control=AverageBitrate(kbps=27501),
        ),
        video(
            encoder="hevc_nvenc",
            level="4.1",
            advanced={"tier": "high"},
            rate_control=AverageBitrate(kbps=27500),
        ),
    ),
    Case(
        "NVENC H.264 level 4.1 above its bitrate (High, the default profile)",
        "encoder.level_bitrate_too_high",
        "video.rate_control.kbps",
        ERR,
        video(encoder="h264_nvenc", level="4.1", rate_control=AverageBitrate(kbps=46876)),
        video(encoder="h264_nvenc", level="4.1", rate_control=AverageBitrate(kbps=46875)),
    ),
    Case(
        "NVENC H.264 Main level 4.1 above its bitrate",
        "encoder.level_bitrate_too_high",
        "video.rate_control.kbps",
        ERR,
        video(
            encoder="h264_nvenc",
            level="4.1",
            profile="main",
            rate_control=AverageBitrate(kbps=37501),
        ),
        video(
            encoder="h264_nvenc",
            level="4.1",
            profile="main",
            rate_control=AverageBitrate(kbps=37500),
        ),
    ),
    Case(
        "x265 level too low for 1080p",
        "encoder.level_too_low",
        "video.level",
        ERR,
        x265_level("3.1"),
        x265_level("4.0"),
    ),
    Case(
        "x265 level too low for the frame rate",
        "encoder.level_too_low",
        "video.level",
        ERR,
        x265_level("4.0", framerate=Rational(num=60, den=1), framerate_mode="constant"),
        x265_level("4.1", framerate=Rational(num=60, den=1), framerate_mode="constant"),
    ),
    Case(
        "Align A/V start with a copied track that starts late",
        "container.align_copied_track",
        "audio[1].action",
        INFO,
        aligned_with_late_copy(0.5),
        aligned_with_late_copy(0.03),
    ),
    Case(
        "AMF pre-analysis on a picture below 200 lines",
        "encoder.preanalysis_picture_too_small",
        "video.advanced.preanalysis",
        ERR,
        both(
            video(encoder="hevc_amf", advanced={"preanalysis": True}),
            dims(size=FitWithin(width=320, height=180)),
        ),
        both(
            video(encoder="hevc_amf", advanced={"preanalysis": True}),
            dims(size=FitWithin(width=356, height=200)),
        ),
    ),
    Case(
        "AMF pre-analysis on a picture below 320 columns",
        "encoder.preanalysis_picture_too_small",
        "video.advanced.preanalysis",
        ERR,
        both(video(encoder="av1_amf", advanced={"preanalysis": True}), narrow_source),
        both(video(encoder="av1_amf", advanced={"preanalysis": False}), narrow_source),
    ),
    Case(
        "AMF pre-analysis started by a custom rate control on a small picture",
        "encoder.preanalysis_picture_too_small",
        "video.custom_params",
        ERR,
        both(
            video(encoder="h264_amf", custom_params="rc=qvbr"),
            dims(size=FitWithin(width=320, height=180)),
        ),
        both(
            video(encoder="h264_amf", custom_params="rc=vbr_peak:preanalysis=0"),
            dims(size=FitWithin(width=320, height=180)),
        ),
    ),
    Case(
        "NVENC H.264 level too low for 1080p",
        "encoder.level_too_low",
        "video.level",
        ERR,
        x265_level("3.2", encoder="h264_nvenc"),
        x265_level("4.0", encoder="h264_nvenc"),
    ),
    Case(
        "NVENC H.264 level too low for the frame rate",
        "encoder.level_too_low",
        "video.level",
        ERR,
        x265_level(
            "4.1",
            encoder="h264_nvenc",
            framerate=Rational(num=60, den=1),
            framerate_mode="constant",
        ),
        x265_level(
            "4.2",
            encoder="h264_nvenc",
            framerate=Rational(num=60, den=1),
            framerate_mode="constant",
        ),
    ),
    Case(
        "NVENC H.265 level too low for 1080p",
        "encoder.level_too_low",
        "video.level",
        ERR,
        x265_level("3.1", encoder="hevc_nvenc"),
        x265_level("4.0", encoder="hevc_nvenc"),
    ),
    Case(
        "x265 level too low after the ultrafast padding",
        "encoder.level_too_low",
        "video.level",
        ERR,
        both(x265_level("4.0", preset="ultrafast"), tall_source, dims(size=TALL)),
        both(x265_level("4.0", preset="medium"), tall_source, dims(size=TALL)),
    ),
    Case(
        "fast decode unsupported",
        "encoder.fast_decode_unsupported",
        "video.fast_decode",
        WARN,
        video(encoder="hevc_nvenc", fast_decode=True),
        video(fast_decode=True),
    ),
    Case(
        "fast decode and a tune on x265",
        "encoder.fast_decode_tune_conflict",
        "video.fast_decode",
        ERR,
        video(encoder="libx265", tune="grain", fast_decode=True),
        video(encoder="libx264", tune="film", fast_decode=True),
    ),
    Case(
        "source without video",
        "source.no_video",
        "source",
        ERR,
        lambda s: setattr(s.source, "video", []),
        nothing,
    ),
    Case(
        "video codec not in container",
        "container.codec_unsupported",
        "video.encoder",
        ERR,
        webm,
        both(webm, video(encoder="libsvtav1")),
    ),
    Case(
        "passthrough codec not in container",
        "container.codec_unsupported",
        "video.passthrough",
        ERR,
        both(webm, video(passthrough=True)),
        video(passthrough=True),
    ),
    Case(
        "audio codec not in container",
        "container.codec_unsupported",
        "audio[0].encoder",
        ERR,
        both(container("webm"), one_audio),
        both(container("webm"), one_audio, audio(0, encoder="libopus", bitrate=None)),
    ),
    Case(
        "passthru fallback codec not in container",
        "container.codec_unsupported",
        "audio[0].encoder",
        ERR,
        both(container("webm"), lambda s: setattr(s.job, "audio", s.job.audio[1:])),
        both(
            container("webm"),
            lambda s: setattr(s.job, "audio", s.job.audio[1:]),
            audio(0, encoder="libopus"),
        ),
    ),
    Case(
        "converted subtitle not in container",
        "container.codec_unsupported",
        "subtitles[0].convert_to",
        ERR,
        both(
            container("mp4"),
            subs(SubtitleOutputTrack(source=3, action="convert", convert_to="ass")),
        ),
        both(
            container("mp4"),
            subs(SubtitleOutputTrack(source=3, action="convert", convert_to="mov_text")),
        ),
    ),
    Case(
        "copied text subtitle not in container",
        "container.codec_unsupported",
        "subtitles[0].action",
        ERR,
        both(defs(mkv_without_text_copy), subs(SubtitleOutputTrack(source=3))),
        subs(SubtitleOutputTrack(source=3)),
    ),
    Case(
        "flag the container cannot store",
        "container.flag_unsupported",
        "audio[0].metadata.original",
        WARN,
        both(container("mp4"), lambda s: setattr(s.job.audio[0].metadata, "original", True)),
        lambda s: setattr(s.job.audio[0].metadata, "original", True),
    ),
    Case(
        "crop removes the whole width",
        "dimensions.crop_invalid",
        "dimensions.crop.rect",
        ERR,
        crop("manual", CropRect(left=1000, right=1000)),
        crop("manual", CropRect(left=140, right=140)),
    ),
    Case(
        "crop leaves less than a step",
        "dimensions.crop_invalid",
        "dimensions.crop.rect",
        ERR,
        both(
            lambda s: setattr(s.source.video[0], "height", 1081),
            crop("manual", CropRect(top=540, bottom=540)),
        ),
        both(
            lambda s: setattr(s.source.video[0], "height", 1081),
            crop("manual", CropRect(top=540, bottom=538)),
        ),
    ),
    Case(
        "crop snapped to the chroma grid",
        "dimensions.crop_snapped",
        "dimensions.crop.rect",
        INFO,
        crop("manual", CropRect(top=141, bottom=141, left=3)),
        crop("manual", CropRect(top=140, bottom=140, left=2)),
    ),
    Case(
        "crop detection not run",
        "dimensions.crop_not_detected",
        "dimensions.crop",
        INFO,
        crop("auto"),
        crop("auto", CropRect(top=140, bottom=140)),
    ),
    Case(
        "conservative crop detection not run",
        "dimensions.crop_not_detected",
        "dimensions.crop",
        INFO,
        crop("conservative"),
        crop("conservative", CropRect(top=140, bottom=140)),
    ),
    Case(
        "crop detection failed",
        "dimensions.crop_detection_failed",
        "dimensions.crop",
        WARN,
        crop("auto", detection_error="Crop detection failed on every frame."),
        crop("auto", CropRect(top=140), detection_error="Crop detection failed on every frame."),
    ),
    Case(
        "manual crop without values",
        "dimensions.crop_missing",
        "dimensions.crop.rect",
        WARN,
        crop("manual"),
        crop("manual", CropRect()),
    ),
    Case(
        "upscaled",
        "dimensions.upscaled",
        "dimensions.size",
        WARN,
        dims(allow_upscaling=True, size=FitWithin(width=3840, height=2160)),
        dims(size=FitWithin(width=3840, height=2160)),
    ),
    Case(
        "outside the fit box",
        "dimensions.outside_box",
        "dimensions.size",
        WARN,
        dims(size=FitWithin(width=10, height=10), modulus=16),
        dims(size=FitWithin(width=10, height=10)),
    ),
    Case(
        "custom PAR missing",
        "dimensions.custom_par_missing",
        "dimensions.custom_par",
        ERR,
        dims(pixel_aspect="custom"),
        dims(pixel_aspect="custom", custom_par=Rational(num=4, den=3)),
    ),
    Case(
        "unknown filter",
        "filter.unknown",
        "filters.sparkle",
        ERR,
        filters(sparkle=FilterConfig()),
        filters(deblock=FilterConfig(preset="medium")),
    ),
    Case(
        "unknown implementation",
        "filter.implementation_unknown",
        "filters.denoise.implementation",
        ERR,
        filters(denoise=FilterConfig(preset="light", implementation="bm3d")),
        filters(denoise=FilterConfig(preset="light", implementation="hqdn3d")),
    ),
    Case(
        "implementation cannot run",
        "filter.implementation_unavailable",
        "filters.tonemap.implementation",
        ERR,
        both(
            hdr10_source,
            filters(tonemap=FilterConfig(implementation="libplacebo")),
            lambda s: setattr(
                s.caps, "filter_failures", {"libplacebo": "No working Vulkan driver"}
            ),
        ),
        both(hdr10_source, filters(tonemap=FilterConfig(implementation="libplacebo"))),
    ),
    Case(
        "implementation not tested",
        "filter.implementation_untested",
        "filters.tonemap.implementation",
        WARN,
        both(
            filters(tonemap=FilterConfig(implementation="libplacebo")),
            lambda s: setattr(s.caps, "untested_filters", ["libplacebo"]),
        ),
        both(
            filters(tonemap=FilterConfig()),
            lambda s: setattr(s.caps, "untested_filters", ["libplacebo"]),
        ),
    ),
    Case(
        "no implementation can run",
        "filter.unavailable",
        "filters.denoise",
        ERR,
        both(
            filters(denoise=FilterConfig(preset="light")), caps({}, filters=["zscale", "tonemap"])
        ),
        both(
            filters(denoise=FilterConfig(preset="light")),
            caps({}, filters=["zscale", "tonemap", "hqdn3d"]),
        ),
    ),
    Case(
        "unknown filter preset",
        "filter.preset_unknown",
        "filters.denoise.preset",
        ERR,
        filters(denoise=FilterConfig(preset="default", implementation="nlmeans")),
        filters(denoise=FilterConfig(preset="light")),
    ),
    Case(
        "unknown filter tune",
        "filter.tune_unknown",
        "filters.denoise.tune",
        ERR,
        filters(denoise=FilterConfig(preset="light", tune="anime")),
        filters(denoise=FilterConfig(preset="light", tune="film")),
    ),
    Case(
        "filter preset needs a tune",
        "filter.tune_required",
        "filters.deblock.tune",
        ERR,
        both(defs(deblock_needs_tune), filters(deblock=FilterConfig(preset="medium"))),
        both(
            defs(deblock_needs_tune), filters(deblock=FilterConfig(preset="medium", tune="small"))
        ),
    ),
    Case(
        "custom filter without parameters",
        "filter.custom_missing",
        "filters.custom.custom",
        ERR,
        filters(custom=FilterConfig()),
        filters(custom=FilterConfig(custom="eq=gamma=1.1")),
    ),
    Case(
        "HDR to SDR without tone mapping",
        "filter.hdr_without_tonemap",
        "filters.colorspace",
        WARN,
        both(hdr10_source, filters(colorspace=FilterConfig(preset="bt709"))),
        both(
            hdr10_source, filters(colorspace=FilterConfig(preset="bt709"), tonemap=FilterConfig())
        ),
    ),
    Case(
        "HDR to BT.2020 SDR without tone mapping",
        "filter.hdr_without_tonemap",
        "filters.colorspace",
        WARN,
        both(hdr10_source, filters(colorspace=FilterConfig(preset="bt2020"))),
        both(
            hdr10_source, filters(colorspace=FilterConfig(preset="bt2020"), tonemap=FilterConfig())
        ),
    ),
    Case(
        "HDR source encoded to 8-bit",
        "filter.hdr_8bit",
        "video.bit_depth",
        WARN,
        both(hdr10_source, video(bit_depth=8)),
        both(hdr10_source, video(bit_depth=10)),
    ),
    Case(
        "HDR10 source encoded to 8-bit, tone mapped",
        "filter.hdr_8bit",
        "video.bit_depth",
        WARN,
        both(hdr10_source, video(encoder="libx264", bit_depth=8)),
        both(hdr10_source, video(encoder="libx264", bit_depth=8), filters(tonemap=FilterConfig())),
    ),
    Case(
        "HLG source encoded to 8-bit by an encoder without 10-bit",
        "filter.hdr_8bit",
        "video.bit_depth",
        WARN,
        both(hlg_source, video(encoder="h264_amf", bit_depth=8)),
        video(encoder="h264_amf", bit_depth=8),
    ),
    Case(
        "HDR source encoded to 8-bit, video passed through",
        "filter.hdr_8bit",
        "video.bit_depth",
        WARN,
        both(hdr10_source, video(bit_depth=8)),
        both(hdr10_source, video(bit_depth=8, passthrough=True)),
    ),
    Case(
        "audio source missing",
        "audio.source_missing",
        "audio[0].source_stream",
        ERR,
        audio(0, source_stream=9),
        nothing,
    ),
    Case(
        "audio without a source",
        "audio.source_missing",
        "audio[0].source_stream",
        ERR,
        audio(0, source_stream=None),
        audio(0, source_stream=2),
    ),
    Case(
        "gain on a copied passthru track",
        "audio.passthru_settings_ignored",
        "audio[1].action",
        WARN,
        audio(1, gain=3.0, loudness="ebu_r128", drc=1.0),
        audio(1, gain=3.0, loudness="ebu_r128", drc=1.0, action="encode"),
    ),
    Case(
        "loudness on a copied passthru track without an encoder",
        "audio.passthru_settings_ignored",
        "audio[1].action",
        WARN,
        audio(1, loudness="streaming", encoder=None),
        both(audio(1, loudness="streaming", encoder=None), container("webm"), webm_video),
    ),
    Case(
        "auto passthru",
        "audio.passthru_fallback",
        "audio[1].action",
        INFO,
        both(container("mp4"), lambda s: setattr(s.source.audio[1], "codec", "vorbis")),
        container("mp4"),
    ),
    Case(
        "mixdown unsupported",
        "audio.mixdown_unsupported",
        "audio[0].mixdown",
        INFO,
        both(
            lambda s: setattr(s.source.audio[0], "channels", 8),
            audio(0, encoder="ac3", mixdown="7.1", bitrate=640),
        ),
        both(
            lambda s: setattr(s.source.audio[0], "channels", 8),
            audio(0, encoder="ac3", mixdown="5.1", bitrate=640),
        ),
    ),
    Case(
        "mixdown would upmix",
        "audio.mixdown_upmix",
        "audio[1].mixdown",
        INFO,
        audio(1, action="encode", mixdown="5.1"),
        audio(1, action="encode", mixdown="stereo"),
    ),
    Case(
        "bitrate above the range",
        "audio.bitrate_out_of_range",
        "audio[0].bitrate",
        INFO,
        audio(0, encoder="ac3", mixdown="5.1", bitrate=700),
        audio(0, encoder="ac3", mixdown="5.1", bitrate=640),
    ),
    Case(
        "bitrate not a fixed step",
        "audio.bitrate_out_of_range",
        "audio[0].bitrate",
        INFO,
        audio(0, encoder="ac3", bitrate=250),
        audio(0, encoder="ac3", bitrate=224),
    ),
    Case(
        "VBR quality without a VBR mode",
        "audio.quality_unsupported",
        "audio[0].quality",
        INFO,
        audio(0, encoder="aac", bitrate=None, quality=4.0),
        audio(0, encoder="libmp3lame", bitrate=None, quality=4.0),
    ),
    Case(
        "sample rate unsupported",
        "audio.samplerate_unsupported",
        "audio[0].samplerate",
        INFO,
        audio(0, encoder="ac3", bitrate=224, samplerate=96000),
        audio(0, encoder="ac3", bitrate=224, samplerate=48000),
    ),
    Case(
        "subtitle source missing",
        "subtitle.source_missing",
        "subtitles[0].source",
        ERR,
        sub(SRT, source=9),
        nothing,
    ),
    Case(
        "external subtitle of an unknown type",
        "subtitle.external_unknown",
        "subtitles[2].source.path",
        ERR,
        both(
            lambda s: s.job.subtitles.append(
                SubtitleOutputTrack(source=ExternalSubtitle(path=EXTERNAL.with_suffix(".idx")))
            ),
            lambda s: s.fs.add_file(EXTERNAL.with_suffix(".idx")),
        ),
        both(
            lambda s: s.job.subtitles.append(
                SubtitleOutputTrack(source=ExternalSubtitle(path=EXTERNAL.with_suffix(".SUP")))
            ),
            lambda s: s.fs.add_file(EXTERNAL.with_suffix(".SUP")),
        ),
    ),
    Case(
        "external subtitle missing",
        "subtitle.external_missing",
        "subtitles[2].source.path",
        ERR,
        lambda s: s.job.subtitles.append(
            SubtitleOutputTrack(source=ExternalSubtitle(path=EXTERNAL))
        ),
        both(
            lambda s: s.job.subtitles.append(
                SubtitleOutputTrack(source=ExternalSubtitle(path=EXTERNAL))
            ),
            lambda s: s.fs.add_file(EXTERNAL),
        ),
    ),
    Case(
        "two burned-in tracks",
        "subtitle.burn_multiple",
        "subtitles[1].action",
        ERR,
        both(sub(SRT, action="burn"), sub(PGS, action="burn")),
        sub(SRT, action="burn"),
    ),
    Case(
        "burn-in with passthrough",
        "subtitle.burn_passthrough",
        "subtitles[0].action",
        ERR,
        both(video(passthrough=True), sub(SRT, action="burn")),
        video(passthrough=True),
    ),
    Case(
        "PGS into MP4",
        "subtitle.bitmap_unsupported",
        "subtitles[1].action",
        ERR,
        container("mp4"),
        nothing,
    ),
    Case(
        "PGS into MP4 with a burned track",
        "subtitle.bitmap_unsupported",
        "subtitles[1].action",
        ERR,
        both(container("mp4"), sub(SRT, action="burn")),
        both(container("mp4"), sub(PGS, action="burn")),
    ),
    Case(
        "bitmap converted to text",
        "subtitle.convert_bitmap",
        "subtitles[1].action",
        ERR,
        sub(PGS, action="convert", convert_to="srt"),
        sub(SRT, action="convert", convert_to="ass"),
    ),
    Case(
        "conversion without a format",
        "subtitle.convert_target_missing",
        "subtitles[0].convert_to",
        ERR,
        sub(SRT, action="convert"),
        sub(SRT, action="convert", convert_to="ass"),
    ),
    Case(
        "forced only on text",
        "subtitle.forced_only_unsupported",
        "subtitles[0].forced_only",
        ERR,
        sub(SRT, action="burn", forced_only=True),
        sub(PGS, action="burn", forced_only=True),
    ),
    Case(
        "forced only on a copy",
        "subtitle.forced_only_unsupported",
        "subtitles[1].forced_only",
        ERR,
        sub(PGS, forced_only=True),
        sub(PGS, action="burn", forced_only=True),
    ),
    Case(
        "unknown language",
        "metadata.language_invalid",
        "audio[0].metadata.language",
        WARN,
        lambda s: setattr(s.job.audio[0].metadata, "language", "xyz"),
        lambda s: setattr(s.job.audio[0].metadata, "language", "hu"),
    ),
    Case(
        "frame range without a frame rate",
        "range.no_frame_rate",
        "range",
        ERR,
        both(job_range(FrameRange(start=1, end=5)), no_frame_rate),
        both(
            job_range(FrameRange(start=1, end=5)),
            no_frame_rate,
            lambda s: setattr(s.source.video[0], "frame_count", 14385),
            lambda s: setattr(s.source.video[0], "duration", 600.0),
        ),
    ),
    Case(
        "range starts after the end",
        "range.outside",
        "range.start",
        ERR,
        job_range(TimeRange(start=700)),
        job_range(TimeRange(start=100)),
    ),
    Case(
        "empty time range",
        "range.outside",
        "range",
        ERR,
        job_range(TimeRange(start=100, end=50)),
        job_range(TimeRange(start=100, end=200)),
    ),
    Case(
        "range ends after the end",
        "range.end_beyond",
        "range.end",
        WARN,
        job_range(TimeRange(start=10, end=700)),
        job_range(TimeRange(start=10, end=600)),
    ),
    Case(
        "chapters on a source without chapters",
        "range.outside",
        "range",
        ERR,
        both(job_range(ChapterRange(start=1, end=1)), lambda s: setattr(s.source, "chapters", [])),
        job_range(ChapterRange(start=1, end=2)),
    ),
    Case(
        "empty chapter range",
        "range.outside",
        "range",
        ERR,
        job_range(ChapterRange(start=2, end=1)),
        job_range(ChapterRange(start=2, end=2)),
    ),
    Case(
        "chapter range starts after the end",
        "range.outside",
        "range.start",
        ERR,
        job_range(ChapterRange(start=3, end=3)),
        job_range(ChapterRange(start=2, end=2)),
    ),
    Case(
        "chapter range ends after the end",
        "range.end_beyond",
        "range.end",
        WARN,
        job_range(ChapterRange(start=1, end=5)),
        job_range(ChapterRange(start=1, end=2)),
    ),
    Case(
        "frame range starts after the end",
        "range.outside",
        "range.start",
        ERR,
        job_range(FrameRange(start=20000)),
        job_range(FrameRange(start=14000)),
    ),
    Case(
        "frame range ends after the end",
        "range.end_beyond",
        "range.end",
        WARN,
        job_range(FrameRange(start=0, end=20000)),
        job_range(FrameRange(start=0, end=14000)),
    ),
    Case(
        "empty frame range",
        "range.outside",
        "range",
        ERR,
        job_range(FrameRange(start=10, end=10)),
        job_range(FrameRange(start=10, end=11)),
    ),
    Case("no output path", "output.no_path", "output.path", ERR, output_path(None), nothing),
    Case(
        "output is the source",
        "output.same_as_source",
        "output.path",
        ERR,
        output_path(sc.SOURCE),
        nothing,
    ),
    Case(
        "output is a folder",
        "output.is_folder",
        "output.path",
        ERR,
        lambda s: s.fs.add_dir(sc.OUTPUT),
        nothing,
    ),
    Case(
        "collision, ask",
        "output.exists",
        "output.path",
        ERR,
        both(output_exists, collision("ask")),
        collision("ask"),
    ),
    Case(
        "output name too long",
        "output.name_too_long",
        "output.path",
        ERR,
        output_path(Path("/out") / ("x" * 250 + ".mkv")),
        output_path(Path("/out") / ("x" * 246 + ".mkv")),
    ),
    Case(
        "output folder name too long",
        "output.name_too_long",
        "output.path",
        ERR,
        output_path(Path("/out") / ("x" * 256) / "Movie.mkv"),
        output_path(Path("/out") / ("x" * 255) / "Movie.mkv"),
    ),
    Case(
        "reserved Windows name",
        "output.name_not_portable",
        "output.path",
        NOT_PORTABLE,
        output_path(Path("/out/CON.mkv")),
        output_path(Path("/out/CONTACT.mkv")),
    ),
    Case(
        "character Windows does not allow",
        "output.name_not_portable",
        "output.path",
        NOT_PORTABLE,
        output_path(Path("/out/Movie: The Sequel.mkv")),
        output_path(Path("/out/Movie - The Sequel.mkv")),
    ),
    Case("collision, auto-rename", "output.renamed", "output.path", INFO, output_exists, nothing),
    Case(
        "collision, overwrite",
        "output.overwrite",
        "output.path",
        WARN,
        both(output_exists, collision("overwrite")),
        collision("overwrite"),
    ),
    Case(
        "wrong extension",
        "output.extension_mismatch",
        "output.path",
        WARN,
        output_path(Path("/out/Movie.mp4")),
        output_path(Path("/out/Movie.MKV")),
    ),
    Case(
        "no folder exists",
        "output.folder_missing",
        "output.path",
        ERR,
        output_path(Path("Videos/Movie.mkv")),
        both(output_path(Path("Videos/Movie.mkv")), lambda s: s.fs.add_dir(Path("."))),
    ),
    Case(
        "folder not writable",
        "output.not_writable",
        "output.path",
        ERR,
        lambda s: s.fs.readonly.add(str(Path("/out"))),
        nothing,
    ),
    Case(
        "folder is a file",
        "output.not_writable",
        "output.path",
        ERR,
        both(
            output_path(Path("/out/notes.txt/Movie.mkv")),
            lambda s: s.fs.add_file(Path("/out/notes.txt")),
        ),
        output_path(Path("/out/notes/Movie.mkv")),
    ),
    Case(
        "not enough disk space",
        "output.disk_space",
        "output.path",
        WARN,
        both(
            video(rate_control=AverageBitrate(kbps=6000)),
            lambda s: setattr(s.fs, "free", 100_000_000),
        ),
        lambda s: setattr(s.fs, "free", 100_000_000),
    ),
    Case(
        "not enough disk space, remux",
        "output.disk_space",
        "output.path",
        WARN,
        both(video(passthrough=True), lambda s: setattr(s.fs, "free", 100_000_000)),
        video(passthrough=True),
    ),
    Case(
        "unknown template variable",
        "naming.unknown_variable",
        "output.naming.template",
        ERR,
        naming(template="{titel} ({year})"),
        naming(template="{main_title} ({year})"),
    ),
    Case(
        "template syntax",
        "naming.template_syntax",
        "output.naming.template",
        ERR,
        naming(template="{main_title"),
        naming(template="{main_title}"),
    ),
    Case(
        "empty template",
        "naming.empty_template",
        "output.naming.template",
        WARN,
        naming(template=" "),
        naming(template="{name}"),
    ),
    Case(
        "bad format spec",
        "naming.bad_format_spec",
        "output.naming.template",
        ERR,
        naming(template="{main_title} {year:%Y}"),
        naming(template="{main_title} {year:04}"),
    ),
    Case(
        "backslash in template",
        "naming.backslash",
        "output.naming.template",
        WARN,
        naming(template="Movies\\{main_title}"),
        naming(template="Movies/{main_title}"),
    ),
    Case(
        "settings template with errors",
        "naming.unknown_variable",
        "output.naming.template",
        ERR,
        settings_naming(movie_template="{titel}"),
        settings_naming(movie_template="{title}"),
    ),
    Case(
        "bad override",
        "naming.bad_override",
        "output.naming.field_overrides.season",
        WARN,
        naming(field_overrides={"season": "two"}),
        naming(field_overrides={"season": "2"}),
    ),
    Case(
        "unknown override",
        "naming.unknown_override",
        "output.naming.field_overrides.colour",
        WARN,
        naming(field_overrides={"colour": "red"}),
        naming(field_overrides={"year": "2019"}),
    ),
    Case(
        "empty manual name",
        "naming.manual_name_empty",
        "output.naming.manual_name",
        WARN,
        naming(mode="manual", manual_name=""),
        naming(mode="manual", manual_name="Film"),
    ),
    Case(
        "fixed folder not chosen",
        "naming.no_output_folder",
        "output.path",
        WARN,
        settings_naming(output_folder_mode="fixed"),
        settings_naming(output_folder_mode="fixed", output_folder=Path("/out")),
    ),
]


#: Cases in other files next to this one: each has ``cases(h) -> list[Case]``, where ``h``
#: gives this module's helpers (``h.Case``, ``h.ERR``, ``h.video``, …).
_HELPERS = SimpleNamespace(**globals())
for _cases in (cases_inplace, cases_options, cases_metadata):
    CASES.extend(_cases.cases(_HELPERS))


@pytest.fixture(autouse=True)
def _fresh_definitions() -> None:
    """Custom-definition cases copy the definitions; the shared ones must stay unchanged."""
    assert DEFS.containers["mkv"].text_subtitle_target is not None
    assert DEFS.video_encoders["libx265"].rate_control.quality is not None


def test_clean_job_has_no_issues() -> None:
    assert sc.base().validate() == []


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_positive(case: Case) -> None:
    issues = sc.check(build(case.positive))
    matching = [i for i in issues if i.code == case.code and i.path == case.path]
    assert matching, [(i.code, i.path) for i in issues]
    assert {i.severity for i in matching} == {case.severity}


#: A negative of `nothing` is the clean job itself, so `test_clean_job_has_no_issues` is the
#: negative test of those codes and running `check` on it again would add nothing.
NEGATIVE_CASES = [c for c in CASES if c.negative is not nothing]


@pytest.mark.parametrize("case", NEGATIVE_CASES, ids=[c.id for c in NEGATIVE_CASES])
def test_negative(case: Case) -> None:
    issues = sc.check(build(case.negative))
    assert not sc.found(issues, case.code, case.path), issues


@pytest.mark.parametrize(
    ("params", "on"),
    [
        *((f"preanalysis={off}", False) for off in ("disabled", "DISABLE", "N", "00", "-1")),
        ("preanalysis=auto", False),
        *((f"preanalysis={on}", True) for on in ("enabled", "Yes", "01", "+1")),
        ("preanalysis", True),
        ("rc=04", True),
        ("rc=hqcbr", True),
        ("rc=3", False),
        ("rc=QVBR", False),  # FFmpeg refuses it: no pre-analysis
    ],
)
def test_amf_preanalysis_custom_params_are_read_as_ffmpeg_reads_them(params: str, on: bool) -> None:
    small = dims(size=FitWithin(width=320, height=180))
    issues = build(both(video(encoder="h264_amf", custom_params=params), small)).validate()
    assert sc.found(issues, "encoder.preanalysis_picture_too_small", "video.custom_params") is on


def test_a_track_name_variable_typo_has_a_fix() -> None:
    def issue_of(name: str) -> Any:
        found = build(cases_metadata.track_name(name)).validate()
        return next(i for i in found if i.code == "metadata.name_variable_unknown")

    typo = issue_of("{lang_nmae:upper} {chanels}")
    assert typo.message == (
        "{lang_nmae} and {chanels} are not track name variables, so the track name is written "
        "as typed, braces and all. Did you mean {lang_name} and {channels}?"
    )
    (repair,) = typo.fixes
    assert repair.label == "Use {lang_name} and {channels}"
    assert [op.model_dump() for op in repair.patch] == [
        {"op": "replace", "path": "/audio/0/metadata/name", "value": "{lang_name:upper} {channels}"}
    ]
    other = issue_of("{lang_name} {episode}")
    assert other.fixes == []
    assert other.message.startswith("{episode} is not a track name variable")
    assert other.message.endswith(
        "The variables of a track name are {bitrate}, {channels}, {codec}, {lang}, {lang_name}, "
        "{lang_native}, {source_codec}, {title}."
    )


def test_every_code_has_a_case() -> None:
    declared = {code for rule in JOB_RULES for code in rule.codes}
    covered = {case.code for case in CASES}
    assert declared - covered == set()


def test_every_case_code_is_declared() -> None:
    declared = {code for rule in JOB_RULES for code in rule.codes}
    assert {case.code for case in CASES} - declared == set()
    template_declared = {code for rule in TEMPLATE_RULES for code in rule.codes}
    assert template_declared <= declared


def test_switch_container_changes_the_extension() -> None:
    s = sc.base()
    s.job.output.container = "mp4"
    s.job.output.path = Path("/out/Movie (2019).mp4")
    s.job.subtitles = [SubtitleOutputTrack(source=4, action="copy")]  # PGS
    issues = sc.check(s)
    [issue] = [i for i in issues if i.code == "subtitle.bitmap_unsupported"]
    [switch] = [f for f in issue.fixes if f.label == f"Switch to {sc.DEFS.containers['mkv'].label}"]
    switched = s.apply(switch)
    assert switched.job.output.path == Path("/out/Movie (2019).mkv")
    assert not sc.found(switched.validate(), "output.extension_mismatch")


def test_switch_container_keeps_every_track_valid() -> None:
    """WebVTT fits MKV and WebM, but WebM cannot hold x265, so the fixes offer only MKV."""
    s = sc.base()
    s.job.output.container = "mp4"
    s.job.output.path = Path("/out/Movie (2019).mp4")
    s.job.subtitles = [SubtitleOutputTrack(source=3, action="convert", convert_to="webvtt")]
    [issue] = [i for i in sc.check(s) if i.path == "subtitles[0].convert_to"]
    switches = [f.label for f in issue.fixes if f.label.startswith("Switch to")]
    assert switches == [f"Switch to {sc.DEFS.containers['mkv'].label}"]


def test_encode_the_video_picks_an_encoder_the_container_holds() -> None:
    s = sc.base()
    s.job.video.passthrough = True
    s.job.output.container = "webm"
    s.job.output.path = Path("/out/Movie (2019).webm")
    s.job.audio = s.job.audio[:1]
    s.job.audio[0].encoder = "libopus"
    s.job.subtitles = []
    [issue] = [i for i in sc.check(s) if i.code == "container.codec_unsupported"]
    encode = next(f for f in issue.fixes if f.label.startswith("Encode the video"))
    after = s.apply(encode).validate()
    assert sc.error_codes(after) == set()


def test_closest_match_respects_detected_10bit() -> None:
    states: dict[str, EncoderState | EncoderStatus] = {
        "hevc_nvenc": EncoderState.UNAVAILABLE,
    }
    for encoder_id in sc.DEFS.video_encoders:
        if encoder_id != "hevc_nvenc":
            states[encoder_id] = EncoderStatus(
                id=encoder_id,
                state=EncoderState.AVAILABLE,
                in_build=True,
                supports_10bit=False,
                reason_10bit="10-bit is not supported by this GPU",
            )
    s = sc.base()
    s.caps = sc.make_caps(states)
    s.job.video.encoder = "hevc_nvenc"
    s.job.video.bit_depth = 10
    [issue] = [i for i in sc.check(s) if i.code == "encoder.unavailable"]
    after = s.apply(issue.fixes[0]).validate()
    assert not sc.found(after, "encoder.no_10bit")


def test_burn_it_in_is_not_offered_next_to_another_burn_in() -> None:
    s = sc.base()
    pgs = sc.make_source().subtitles[1].index
    s.source = sc.make_source()
    s.job.subtitles = [
        SubtitleOutputTrack(source=3, action="burn"),
        SubtitleOutputTrack(source=pgs, action="convert", convert_to="srt"),
    ]
    [issue] = [i for i in sc.check(s) if i.code == "subtitle.convert_bitmap"]
    assert "Burn it in" not in [f.label for f in issue.fixes]


@pytest.mark.parametrize(
    ("found", "charset", "fixes"),
    [
        ("UTF8", "UTF-16LE", ["Read it as UTF-8 (as detected)", "Remove this subtitle track"]),
        ("UTF8", "CP1250", ["Read it as UTF-8 (as detected)", "Remove this subtitle track"]),
        ("UNKNOWN", "UTF-16LE", ["Remove this subtitle track"]),
    ],
)
def test_reading_as_utf8_is_offered_only_for_a_utf8_file(
    found: str, charset: str, fixes: list[str]
) -> None:
    s = sc.base()
    cases_metadata.external(getattr(cases_metadata, found), charset)(s)
    [issue] = [i for i in sc.check(s) if i.path == cases_metadata.AT]
    assert [f.label for f in issue.fixes] == fixes
