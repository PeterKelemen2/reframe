"""Video encoder arguments: rate control, choices, options, 2-pass, HDR, frame rate."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from reframe.command import PlanError
from reframe.command.video import (
    format_number,
    frame_rate_args,
    hdr_params,
    pass_log_files,
    source_rate,
    spec,
    video_encoder_args,
)
from reframe.definitions import (
    EncoderOption,
    FixedDefault,
    PresetDefault,
    RateControlDef,
    VideoEncoderDef,
    X26xParam,
    load_definitions,
)
from reframe.definitions.models import EncoderDefault
from reframe.models import (
    AverageBitrate,
    ColorInfo,
    ConstantQuality,
    ContentLightLevel,
    EncoderStatus,
    HdrFormat,
    HdrInfo,
    MasteringDisplay,
    Rational,
    VideoSettings,
    VideoStream,
)

DEFS = load_definitions()


def video_stream(**kwargs: Any) -> VideoStream:
    return VideoStream.model_validate({"index": 0, "width": 1920, "height": 1080, **kwargs})


def args(encoder: str, *, run: int | None = None, hdr: bool = False, **settings: Any) -> list[str]:
    stream = settings.pop("stream", None) or video_stream()
    status = settings.pop("status", None)
    video = VideoSettings.model_validate({"encoder": encoder, **settings})
    return video_encoder_args(
        DEFS.video_encoders[encoder], video, stream, status=status, run=run,
        passlog=Path("/out/x.part.passlog") if run else None, hdr=hdr,
    )  # fmt: skip


def test_spec_and_numbers() -> None:
    assert spec("-preset", "v:0") == "-preset:v:0"
    assert spec("-b:v", "v:0") == "-b:v:0"
    assert spec("-q:a", "a:3") == "-q:a:3"
    assert [format_number(v) for v in (22.0, 20.5, 0.15, 3)] == ["22", "20.5", "0.15", "3"]
    assert format_number(7.5, integer=True) == "8"


def test_quality_values_and_derived_qps() -> None:
    assert args("libx264", rate_control=ConstantQuality(value=20.5)) == [
        "-c:v:0", "libx264", "-crf:v:0", "20.5",
    ]  # fmt: skip
    assert args("h264_amf", rate_control=ConstantQuality(value=25.4))[2:10] == [
        "-rc:v:0", "cqp", "-qp_i:v:0", "25", "-qp_p:v:0", "27", "-qp_b:v:0", "29",
    ]  # fmt: skip


def test_choices_written_values() -> None:
    out = args("libsvtav1", preset="6", level="5.1", tune="0")
    assert out[out.index("-preset:v:0") + 1] == "6"
    assert out[-1] == "tune=0:level=51"
    vp9 = args("libvpx-vp9", preset="slow", profile="2", bit_depth=10)
    assert vp9[vp9.index("-cpu-used:v:0") + 1] == "1"
    assert vp9[vp9.index("-profile:v:0") + 1] == "2"
    unknown = args("libx264", preset="superslow")
    assert unknown[unknown.index("-preset:v:0") + 1] == "superslow"


def test_a_choice_the_encoder_does_not_have() -> None:
    with pytest.raises(PlanError, match="no level setting"):
        args("h264_qsv", level="4.1")


def test_fast_decode() -> None:
    assert "film,fastdecode" in args("libx264", tune="film", fast_decode=True)
    assert "fastdecode" in args("libx265", fast_decode=True)
    with pytest.raises(PlanError, match="takes one tune"):
        args("libx265", tune="grain", fast_decode=True)
    assert args("libsvtav1", fast_decode=True)[-1] == "fast-decode=1"
    assert "fastdecode" not in " ".join(args("hevc_nvenc", fast_decode=True))


def test_rate_control_modes_missing() -> None:
    no_quality = DEFS.video_encoders["libx264"].model_copy(
        update={"rate_control": RateControlDef()}
    )
    stream = video_stream()
    with pytest.raises(PlanError, match="constant-quality"):
        video_encoder_args(no_quality, VideoSettings(), stream, status=None, run=None,
                           passlog=None, hdr=False)  # fmt: skip
    with pytest.raises(PlanError, match="average-bitrate"):
        video_encoder_args(no_quality, VideoSettings(rate_control=AverageBitrate()), stream,
                           status=None, run=None, passlog=None, hdr=False)  # fmt: skip
    with pytest.raises(PlanError, match="no 2-pass"):
        args("h264_amf", rate_control=AverageBitrate(two_pass=True))
    with pytest.raises(PlanError, match="pass number"):
        args("libx264", rate_control=AverageBitrate(two_pass=True))


def test_two_pass_runs() -> None:
    rc = AverageBitrate(kbps=900, two_pass=True, turbo_first_pass=True)
    first = args("libx264", rate_control=rc, run=1)
    second = args("libx264", rate_control=rc, run=2)
    assert first[-6:] == [
        "-pass:v:0", "1", "-passlogfile:v:0", "/out/x.part.passlog", "-fastfirstpass:v:0", "1",
    ]  # fmt: skip
    assert second[-4:] == ["-pass:v:0", "2", "-passlogfile:v:0", "/out/x.part.passlog"]
    x265 = args("libx265", rate_control=AverageBitrate(two_pass=True), run=1)
    assert x265[-1] == "pass=1:stats=/out/x.part.passlog:slow-firstpass=1"
    nvenc = args("hevc_nvenc", rate_control=AverageBitrate(two_pass=True))
    assert nvenc[-2:] == ["-multipass:v:0", "fullres"]


def test_pass_log_files() -> None:
    prefix = Path("/o/a.part.passlog")
    assert [p.name for p in pass_log_files(prefix, stats_param=True)] == [
        "a.part.passlog", "a.part.passlog.temp", "a.part.passlog.cutree",
        "a.part.passlog.cutree.temp",
    ]  # fmt: skip
    assert [p.name for p in pass_log_files(prefix, stats_param=False)] == [
        "a.part.passlog-0.log", "a.part.passlog-0.log.temp", "a.part.passlog-0.log.mbtree",
        "a.part.passlog-0.log.mbtree.temp",
    ]  # fmt: skip


def test_options_conditions_support_and_composites() -> None:
    out = args(
        "libx265",
        preset="slow",
        advanced={"aq-mode": "0", "aq-strength": 1.5, "psy-rd": 1.5, "deblock-beta": 2},
    )
    assert out[-1] == "aq-mode=0:psy-rd=1.5:deblock=0,2"
    # 10-bit only: hdr10-opt requires bit_depth 10.
    assert "hdr10-opt" not in args("libx265", advanced={"hdr10-opt": True})[-1]
    # A private option the build does not list is skipped (validation reports it).
    status = EncoderStatus(id="hevc_nvenc", private_options=["preset", "tune"])
    nvenc = args("hevc_nvenc", advanced={"b_ref_mode": "middle", "bf": 2}, status=status)
    assert "-b_ref_mode:v:0" not in nvenc
    assert nvenc[-2:] == ["-bf:v:0", "2"]


def test_a_composite_part_without_a_default() -> None:
    base = DEFS.video_encoders["libx265"]
    a = EncoderOption(key="a", label="A", category="x", type="int", help="h",
                      default=FixedDefault(value=1),
                      mapping=X26xParam(name="ab", part=0))  # fmt: skip
    b = EncoderOption(key="b", label="B", category="x", type="int", help="h",
                      default=EncoderDefault(), mapping=X26xParam(name="ab", part=1))  # fmt: skip
    c = EncoderOption(key="c", label="C", category="x", type="int", help="h",
                      default=PresetDefault(values={"medium": 4}),
                      mapping=X26xParam(name="cd", part=0))  # fmt: skip
    d = EncoderOption(key="d", label="D", category="x", type="int", help="h",
                      default=PresetDefault(values={"medium": 5}),
                      mapping=X26xParam(name="cd", part=1))  # fmt: skip
    enc: VideoEncoderDef = base.model_copy(update={"options": [a, b, c, d]})
    stream = video_stream()
    out = video_encoder_args(enc, VideoSettings(advanced={"c": 9}), stream, status=None, run=None,
                             passlog=None, hdr=False)  # fmt: skip
    assert out[-1] == "cd=9,5"
    with pytest.raises(PlanError, match="no default to complete ab="):
        video_encoder_args(enc, VideoSettings(advanced={"a": 3}), stream, status=None, run=None,
                           passlog=None, hdr=False)  # fmt: skip


def test_custom_params_go_last_raw() -> None:
    assert args("libx264", custom_params="nr=100:ref=4")[-1] == "nr=100:ref=4"
    assert "-x264-params:v:0" not in args("libx264", custom_params="  ")
    assert "nr=1" not in " ".join(args("h264_amf", custom_params="nr=1"))


HDR_STREAM = video_stream(
    color=ColorInfo(primaries="bt2020", transfer="smpte2084", matrix="bt2020nc"),
    hdr=HdrInfo(
        formats=[HdrFormat.HDR10],
        mastering_display=MasteringDisplay(
            red_x=0.68, red_y=0.32, green_x=0.265, green_y=0.69, blue_x=0.15, blue_y=0.06,
            white_x=0.3127, white_y=0.329, min_luminance=0.005, max_luminance=4000,
        ),
        content_light=ContentLightLevel(max_cll=1200, max_fall=350),
    ),
)  # fmt: skip


def test_hdr_params_per_encoder() -> None:
    x265 = hdr_params(DEFS.video_encoders["libx265"], HDR_STREAM)
    assert x265 == {
        "colorprim": "bt2020",
        "transfer": "smpte2084",
        "colormatrix": "bt2020nc",
        "master-display": "G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(40000000,50)",
        "max-cll": "1200,350",
    }
    assert hdr_params(DEFS.video_encoders["libx264"], HDR_STREAM) == {
        "colorprim": "bt2020", "transfer": "smpte2084", "colormatrix": "bt2020nc",
    }  # fmt: skip
    svt = hdr_params(DEFS.video_encoders["libsvtav1"], HDR_STREAM)
    assert svt["matrix-coefficients"] == "bt2020-ncl"
    assert (
        svt["mastering-display"]
        == "G(0.265,0.69)B(0.15,0.06)R(0.68,0.32)WP(0.3127,0.329)L(4000,0.005)"
    )
    assert hdr_params(DEFS.video_encoders["hevc_vaapi"], HDR_STREAM) == {}
    hlg = video_stream(
        color=ColorInfo(primaries="bt2020", transfer="arib-std-b67", matrix="unknown")
    )
    assert hdr_params(DEFS.video_encoders["libsvtav1"], hlg) == {
        "color-primaries": "bt2020", "transfer-characteristics": "hlg",
    }  # fmt: skip


def test_hdr_params_yield_to_advanced_options() -> None:
    out = args("libx265", bit_depth=10, hdr=True, stream=HDR_STREAM,
               advanced={"max-cll": "500,100"})  # fmt: skip
    assert "max-cll=500,100" in out[-1]
    assert "max-cll=1200,350" not in out[-1]


def test_frame_rate_modes() -> None:
    vfr = video_stream(frame_rate=Rational(num=120, den=1), avg_frame_rate=Rational(num=38, den=1))
    rate = Rational(num=30000, den=1001)
    assert frame_rate_args(VideoSettings(), vfr) == []
    assert frame_rate_args(VideoSettings(framerate_mode="constant"), vfr) == [
        "-r:v:0", "38", "-fps_mode:v:0", "cfr",
    ]  # fmt: skip
    assert frame_rate_args(VideoSettings(framerate_mode="constant", framerate=rate), vfr) == [
        "-r:v:0", "30000/1001", "-fps_mode:v:0", "cfr",
    ]  # fmt: skip
    assert frame_rate_args(VideoSettings(framerate_mode="peak", framerate=rate), vfr) == [
        "-fpsmax:v:0", "30000/1001",
    ]  # fmt: skip
    assert frame_rate_args(VideoSettings(framerate_mode="variable", framerate=rate), vfr) == [
        "-fpsmax:v:0", "30000/1001",
    ]  # fmt: skip
    unknown = video_stream()
    assert frame_rate_args(VideoSettings(framerate_mode="constant"), unknown) == [
        "-fps_mode:v:0", "cfr",
    ]  # fmt: skip


def test_source_rate_fallbacks() -> None:
    assert source_rate(video_stream(frame_count=96, duration=4.0)) == Fraction(24)
    assert source_rate(video_stream(frame_rate=Rational(num=25, den=1))) == Rational(num=25, den=1)
    assert source_rate(video_stream()) is None
    counted = video_stream(frame_count=1001, duration=41.75)
    assert frame_rate_args(VideoSettings(framerate_mode="constant"), counted)[1] == "24000/1001"
