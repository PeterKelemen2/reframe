"""C-8 "Done when": every rule has a positive and a negative test, and every fix patch, when
applied, removes its issue.

:data:`CASES` is the rule table: for each issue code (and path), a change of the clean
scenario that must produce it (positive) and a close change that must not (negative). The
positive scenario goes through :func:`scenario.check`, which applies every fix of every issue
and validates again (the issue, same code and path, must be gone). ``test_every_code_has_a_case``
proves that the table covers every code the registered rules declare.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
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


def _load(name: str) -> ModuleType:
    # pytest runs with --import-mode=importlib: a helper next to the tests is loaded by path.
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
DEFS: Definitions = sc.DEFS
ERR, WARN, INFO = Severity.ERROR, Severity.WARNING, Severity.INFO

type Mod = Callable[[Any], None]


@dataclass(frozen=True)
class Case:
    id: str
    code: str
    path: str
    severity: Severity
    positive: Mod
    negative: Mod


def build(mod: Mod) -> Any:
    scenario = sc.base()
    mod(scenario)
    return scenario


# --------------------------------------------------------------------------- modifiers


def video(**changes: Any) -> Mod:
    def mod(s: Any) -> None:
        for key, value in changes.items():
            setattr(s.job.video, key, value)

    return mod


def caps(states: dict[str, Any], **kw: Any) -> Mod:
    def mod(s: Any) -> None:
        s.caps = sc.make_caps(states, **kw)

    return mod


def both(*mods: Mod) -> Mod:
    def mod(s: Any) -> None:
        for m in mods:
            m(s)

    return mod


def container(value: str) -> Mod:
    def mod(s: Any) -> None:
        s.job.output.container = value

    return mod


def one_audio(s: Any) -> None:
    s.job.audio = s.job.audio[:1]


def webm(s: Any) -> None:
    """WebM with tracks it can hold: Opus audio, no subtitles."""
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


def crop(mode: str, rect: CropRect | None = None) -> Mod:
    def mod(s: Any) -> None:
        s.job.dimensions.crop = CropSettings(mode=mode, rect=rect)  # type: ignore[arg-type]

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


def ffmpeg_status(status: ToolStatus | None) -> Mod:
    """ffmpeg from a Settings path with ``status``; "Use bundled" removes the path, and the
    rediscovery then finds the bundled ffmpeg (C-1)."""

    def mod(s: Any) -> None:
        if status is None:
            return
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


def mkvpropedit(status: ToolStatus) -> Mod:
    def mod(s: Any) -> None:
        s.tools = sc.make_tools(mkvpropedit=sc.tool("mkvpropedit", status))

    return mod


def hdr_source(s: Any) -> None:
    s.source.video[0].color = ColorInfo(primaries="bt2020", transfer="smpte2084", matrix="bt2020nc")


def hdr10_source(s: Any) -> None:
    """HDR10 as the probe reports it (C-3): the format list, not only the transfer."""
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
    """A cached snapshot that detection checks again (C-4: from_cache and detecting)."""
    s.caps = s.caps.model_copy(update={"from_cache": True, "detecting": True})


def tall_source(s: Any) -> None:
    """1920x1160: within level 4 at 8-pixel padding, not at ultrafast's 16 (1168 lines)."""
    s.source.video[0].height = 1160


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


# --------------------------------------------------------------------------- custom definitions


def mkv_original_via_mkvpropedit(d: Definitions) -> None:
    mkv = d.containers["mkv"]
    mkv.flags = [f for f in mkv.flags if f != "original"]
    mkv.mkvpropedit_flags = ["original"]


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

# --------------------------------------------------------------------------- the table

CASES: list[Case] = [
    # ---- tools
    Case(
        "ffmpeg missing",
        "tool.missing",
        "",
        ERR,
        ffmpeg_status(ToolStatus.MISSING),
        ffmpeg_status(None),
    ),
    Case(
        "ffmpeg too old",
        "tool.too_old",
        "",
        ERR,
        ffmpeg_status(ToolStatus.TOO_OLD),
        ffmpeg_status(None),
    ),
    Case(
        "ffmpeg broken",
        "tool.broken",
        "",
        ERR,
        ffmpeg_status(ToolStatus.BROKEN),
        ffmpeg_status(None),
    ),
    Case(
        "mkvpropedit for edit in place",
        "tool.mkvpropedit_missing",
        "output.edit_in_place",
        ERR,
        both(
            lambda s: setattr(s.job.output, "edit_in_place", True), mkvpropedit(ToolStatus.MISSING)
        ),
        lambda s: setattr(s.job.output, "edit_in_place", True),
    ),
    Case(
        "mkvpropedit for a flag",
        "tool.mkvpropedit_missing",
        "audio[0].metadata.original",
        WARN,
        both(
            defs(mkv_original_via_mkvpropedit),
            mkvpropedit(ToolStatus.MISSING),
            lambda s: setattr(s.job.audio[0].metadata, "original", True),
        ),
        both(
            defs(mkv_original_via_mkvpropedit),
            lambda s: setattr(s.job.audio[0].metadata, "original", True),
        ),
    ),
    # ---- encoder: availability (C-4) with the conversion
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
    # ---- encoder: settings
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
    # ---- source
    Case(
        "source without video",
        "source.no_video",
        "source",
        ERR,
        lambda s: setattr(s.source, "video", []),
        nothing,
    ),
    # ---- container
    Case(
        "unknown container",
        "container.unknown",
        "output.container",
        ERR,
        container("avi"),
        container("mp4"),
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
    # ---- dimensions
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
    # ---- filters
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
            hdr_source,
            filters(tonemap=FilterConfig(implementation="libplacebo")),
            lambda s: setattr(
                s.caps, "filter_failures", {"libplacebo": "No working Vulkan driver"}
            ),
        ),
        both(hdr_source, filters(tonemap=FilterConfig(implementation="libplacebo"))),
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
        both(hdr_source, filters(colorspace=FilterConfig(preset="bt709"))),
        both(hdr_source, filters(colorspace=FilterConfig(preset="bt709"), tonemap=FilterConfig())),
    ),
    Case(
        "HDR to BT.2020 SDR without tone mapping",
        "filter.hdr_without_tonemap",
        "filters.colorspace",
        WARN,
        both(hdr_source, filters(colorspace=FilterConfig(preset="bt2020"))),
        both(hdr_source, filters(colorspace=FilterConfig(preset="bt2020"), tonemap=FilterConfig())),
    ),
    Case(
        "HDR source encoded to 8-bit",
        "filter.hdr_8bit",
        "video.bit_depth",
        WARN,
        both(hdr_source, video(bit_depth=8)),
        both(hdr_source, video(bit_depth=10)),
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
    # ---- audio
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
        "source layout unsupported",
        "audio.mixdown_unsupported",
        "audio[0].mixdown",
        INFO,
        both(
            lambda s: setattr(s.source.audio[0], "channels", 8),
            audio(0, encoder="ac3", mixdown=None, bitrate=None),
        ),
        audio(0, encoder="ac3", mixdown=None, bitrate=None),
    ),
    Case(
        "MP3 cannot keep 5.1",
        "audio.mixdown_unsupported",
        "audio[0].mixdown",
        INFO,
        audio(0, encoder="libmp3lame", mixdown=None, bitrate=None),
        audio(0, encoder="libmp3lame", mixdown="dpl2", bitrate=None),
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
        "Dolby Pro Logic II of a stereo source",
        "audio.mixdown_upmix",
        "audio[1].mixdown",
        INFO,
        audio(1, action="encode", mixdown="dpl2"),
        audio(0, mixdown="dpl2"),
    ),
    Case(
        "upmix to a layout MP3 cannot make",
        "audio.mixdown_upmix",
        "audio[0].mixdown",
        INFO,
        both(
            lambda s: setattr(s.source.audio[0], "channels", 3),
            audio(0, encoder="libmp3lame", mixdown="5.1", bitrate=None),
        ),
        both(
            lambda s: setattr(s.source.audio[0], "channels", 3),
            audio(0, encoder="libmp3lame", mixdown="stereo", bitrate=None),
        ),
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
        "bitrate below the range of the kept layout",
        "audio.bitrate_out_of_range",
        "audio[0].bitrate",
        INFO,
        audio(0, encoder="aac", mixdown=None, bitrate=160),
        audio(0, encoder="aac", mixdown=None, bitrate=384),
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
    # ---- subtitles
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
    # ---- metadata
    Case(
        "BCP 47 tag without mkvpropedit",
        "metadata.language_tag_lost",
        "audio[0].metadata.language",
        WARN,
        both(
            lambda s: setattr(s.job.audio[0].metadata, "language", "pt-BR"),
            mkvpropedit(ToolStatus.MISSING),
        ),
        lambda s: setattr(s.job.audio[0].metadata, "language", "pt-BR"),
    ),
    Case(
        "BCP 47 tag of the source without mkvpropedit",
        "metadata.language_tag_lost",
        "subtitles[0].metadata.language",
        WARN,
        both(
            lambda s: setattr(s.source.subtitles[0], "language_ietf", "zh-Hant"),
            mkvpropedit(ToolStatus.MISSING),
        ),
        both(
            lambda s: setattr(s.source.subtitles[0], "language_ietf", "zh-Hant"),
            mkvpropedit(ToolStatus.MISSING),
            container("mp4"),
            output_path(Path("/out/Movie (2019).mp4")),
            subs(SubtitleOutputTrack(source=3, action="convert", convert_to="mov_text")),
        ),
    ),
    Case(
        "unknown language",
        "metadata.language_invalid",
        "audio[0].metadata.language",
        WARN,
        lambda s: setattr(s.job.audio[0].metadata, "language", "xyz"),
        lambda s: setattr(s.job.audio[0].metadata, "language", "hu"),
    ),
    # ---- range
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
    # ---- output
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
        WARN,
        output_path(Path("/out/CON.mkv")),
        output_path(Path("/out/CONTACT.mkv")),
    ),
    Case(
        "character Windows does not allow",
        "output.name_not_portable",
        "output.path",
        WARN,
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
        lambda s: s.fs.readonly.add("/out"),
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
    # ---- naming
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


@pytest.fixture(autouse=True)
def _fresh_definitions() -> None:
    """Custom-definition cases copy the definitions; the shared ones must stay unchanged."""
    assert DEFS.containers["mkv"].mkvpropedit_flags == []


def test_clean_job_has_no_issues() -> None:
    assert sc.base().validate() == []


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_positive(case: Case) -> None:
    issues = sc.check(build(case.positive))
    matching = [i for i in issues if i.code == case.code and i.path == case.path]
    assert matching, [(i.code, i.path) for i in issues]
    assert {i.severity for i in matching} == {case.severity}


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_negative(case: Case) -> None:
    issues = sc.check(build(case.negative))
    assert not sc.found(issues, case.code, case.path), issues


def test_every_code_has_a_case() -> None:
    declared = {code for rule in JOB_RULES for code in rule.codes}
    covered = {case.code for case in CASES}
    assert declared - covered == set()


def test_every_case_code_is_declared() -> None:
    declared = {code for rule in JOB_RULES for code in rule.codes}
    assert {case.code for case in CASES} - declared == set()
    template_declared = {code for rule in TEMPLATE_RULES for code in rule.codes}
    assert template_declared <= declared
