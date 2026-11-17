"""Rule cases of the advanced encoder options (``reframe.validation.video``).

Each rule is behaviour recorded with the encoders (testdata/README.md, "Advanced encoder options").
"""

from __future__ import annotations

from typing import Any

from reframe.models import AverageBitrate, ConstantQuality


def cases(h: Any) -> list[Any]:
    case, video, warn, err = h.Case, h.video, h.WARN, h.ERR
    vp9 = {"encoder": "libvpx-vp9", "rate_control": ConstantQuality(value=30)}
    return [
        # encoder.option_inactive: the builder leaves the option out
        case(
            "x265 amp without rectangular partitions",
            "encoder.option_inactive",
            "video.advanced.amp",
            warn,
            video(encoder="libx265", advanced={"amp": True, "rect": False}),
            video(encoder="libx265", advanced={"amp": True, "rect": True}),
        ),
        case(
            "x265 amp at the medium preset (rect off by default)",
            "encoder.option_inactive",
            "video.advanced.amp",
            warn,
            video(encoder="libx265", preset="medium", advanced={"amp": True}),
            video(encoder="libx265", preset="slow", advanced={"amp": True}),
        ),
        case(
            "x264 HRD without VBV",
            "encoder.option_inactive",
            "video.advanced.nal-hrd",
            warn,
            video(encoder="libx264", advanced={"nal-hrd": "vbr", "vbv-maxrate": 20000}),
            video(
                encoder="libx264",
                advanced={"nal-hrd": "vbr", "vbv-maxrate": 20000, "vbv-bufsize": 25000},
            ),
        ),
        case(
            "x265 rd-refine below RD 5",
            "encoder.option_inactive",
            "video.advanced.rd-refine",
            warn,
            video(encoder="libx265", advanced={"rd-refine": True, "rd": 4}),
            video(encoder="libx265", advanced={"rd-refine": True, "rd": 5}),
        ),
        case(
            "SVT-AV1 variance boost strength without variance boost",
            "encoder.option_inactive",
            "video.advanced.variance-boost-strength",
            warn,
            video(encoder="libsvtav1", advanced={"variance-boost-strength": 3}),
            video(
                encoder="libsvtav1",
                advanced={"variance-boost-strength": 3, "enable-variance-boost": True},
            ),
        ),
        case(
            "VP9 undershoot with constant quality",
            "encoder.option_inactive",
            "video.advanced.undershoot-pct",
            warn,
            video(**vp9, advanced={"undershoot-pct": 50}),
            video(
                encoder="libvpx-vp9", rate_control=AverageBitrate(), advanced={"undershoot-pct": 50}
            ),
        ),
        case(
            "x265 dynamic RD without VBV",
            "encoder.option_inactive",
            "video.advanced.dynamic-rd",
            warn,
            video(encoder="libx265", advanced={"dynamic-rd": 2.0}),
            video(
                encoder="libx265",
                advanced={"dynamic-rd": 2.0, "vbv-maxrate": 8000, "vbv-bufsize": 8000},
            ),
        ),
        case(
            "x265 VBV buffer without a maximum rate at a constant quality",
            "encoder.option_inactive",
            "video.advanced.vbv-bufsize",
            warn,
            video(encoder="libx265", advanced={"vbv-bufsize": 5000}),
            video(encoder="libx265", rate_control=AverageBitrate(), advanced={"vbv-bufsize": 5000}),
        ),
        # encoder.option_ignored: the encoder changes the value without an error
        case(
            "x264 Blu-ray compatibility lowers the B-frames",
            "encoder.option_ignored",
            "video.advanced.bframes",
            warn,
            video(encoder="libx264", advanced={"bluray-compat": True, "bframes": 5}),
            video(encoder="libx264", advanced={"bluray-compat": True, "bframes": 3}),
        ),
        case(
            "x264 Blu-ray compatibility lowers weighted P-frames",
            "encoder.option_ignored",
            "video.advanced.weightp",
            warn,
            video(encoder="libx264", advanced={"bluray-compat": True, "weightp": "2"}),
            video(encoder="libx264", advanced={"bluray-compat": False, "weightp": "2"}),
        ),
        case(
            "x264 Blu-ray compatibility makes the B-pyramid strict",
            "encoder.option_ignored",
            "video.advanced.b-pyramid",
            warn,
            video(encoder="libx264", advanced={"bluray-compat": True, "b-pyramid": "normal"}),
            video(encoder="libx264", advanced={"bluray-compat": True, "b-pyramid": "strict"}),
        ),
        case(
            "x265 TU size above the CTU",
            "encoder.option_ignored",
            "video.advanced.max-tu-size",
            warn,
            video(encoder="libx265", advanced={"ctu": "16", "max-tu-size": "32"}),
            video(encoder="libx265", advanced={"ctu": "16", "max-tu-size": "16"}),
        ),
        case(
            "x265 quantisation group above the CTU",
            "encoder.option_ignored",
            "video.advanced.qg-size",
            warn,
            video(encoder="libx265", advanced={"ctu": "32", "qg-size": "64"}),
            video(encoder="libx265", advanced={"ctu": "64", "qg-size": "64"}),
        ),
        case(
            "x265 parallel mode analysis turns limit-refs 2 off",
            "encoder.option_ignored",
            "video.advanced.limit-refs",
            warn,
            video(encoder="libx265", advanced={"pmode": True, "limit-refs": "2"}),
            video(encoder="libx265", advanced={"pmode": True, "limit-refs": "1"}),
        ),
        case(
            "SVT-AV1 forward keyframes force hierarchical levels 4",
            "encoder.option_ignored",
            "video.advanced.hierarchical-levels",
            warn,
            video(encoder="libsvtav1", advanced={"irefresh-type": "1", "hierarchical-levels": "3"}),
            video(encoder="libsvtav1", advanced={"irefresh-type": "2", "hierarchical-levels": "3"}),
        ),
        # encoder.option_conflict: the encoder refuses to start
        case(
            "x265 minimum CU above the CTU",
            "encoder.option_conflict",
            "video.advanced.min-cu-size",
            err,
            video(encoder="libx265", advanced={"ctu": "16", "min-cu-size": "32"}),
            video(encoder="libx265", advanced={"ctu": "32", "min-cu-size": "32"}),
        ),
        case(
            "SVT-AV1 minimum QP above the maximum",
            "encoder.option_conflict",
            "video.advanced.min-qp",
            err,
            video(encoder="libsvtav1", advanced={"min-qp": 40, "max-qp": 20}),
            video(encoder="libsvtav1", advanced={"min-qp": 20, "max-qp": 40}),
        ),
        case(
            "SVT-AV1 minimum QM level above the maximum",
            "encoder.option_conflict",
            "video.advanced.qm-min",
            err,
            video(encoder="libsvtav1", advanced={"enable-qm": True, "qm-min": 12, "qm-max": 4}),
            video(encoder="libsvtav1", advanced={"enable-qm": True, "qm-min": 4, "qm-max": 12}),
        ),
        case(
            "VP9 qmin above qmax",
            "encoder.option_conflict",
            "video.advanced.qmin",
            err,
            video(
                encoder="libvpx-vp9",
                rate_control=AverageBitrate(),
                advanced={"qmin": 40, "qmax": 20},
            ),
            video(
                encoder="libvpx-vp9",
                rate_control=AverageBitrate(),
                advanced={"qmin": 20, "qmax": 40},
            ),
        ),
        case(
            "VP9 CQ above qmax",
            "encoder.option_conflict",
            "video.advanced.qmax",
            err,
            video(**vp9, advanced={"qmax": 29}),
            video(**vp9, advanced={"qmax": 30}),
        ),
        case(
            "VP9 CQ below qmin",
            "encoder.option_conflict",
            "video.advanced.qmin",
            err,
            video(**vp9, advanced={"qmin": 31}),
            video(**vp9, advanced={"qmin": 30}),
        ),
        # other option and custom parameter errors
        case(
            "x265 custom parameter that writes a file",
            "encoder.custom_param_file",
            "video.custom_params",
            err,
            video(encoder="libx265", custom_params="aq-mode=3:analysis-save=/tmp/x.dat"),
            video(encoder="libx265", custom_params="aq-mode=3:analysis-reuse-level=5"),
        ),
        case(
            "FFmpeg's own file option as a VP9 custom parameter",
            "encoder.custom_param_file",
            "video.custom_params",
            err,
            video(**vp9, custom_params="vstats_file=/tmp/v.log"),
            video(**vp9, custom_params="lag-in-frames=16"),
        ),
        case(
            "VP9 custom parameter that is no option of the encoder",
            "encoder.custom_param_unknown",
            "video.custom_params",
            err,
            video(**vp9, custom_params="bogus=1"),
            video(**vp9, custom_params="arnr-maxframes=7:g=120"),
        ),
        # encoder.custom_param_overrides: the custom parameters come last, so they win
        case(
            "x265 custom parameter over a set option",
            "encoder.custom_param_overrides",
            "video.advanced.psy-rd",
            warn,
            video(encoder="libx265", advanced={"psy-rd": 1.5}, custom_params="psy-rd=0.75"),
            video(encoder="libx265", advanced={"psy-rd": 1.5}, custom_params="fades=1"),
        ),
        case(
            "NVENC custom parameter over an option's default",
            "encoder.custom_param_overrides",
            "video.advanced.rc-lookahead",
            h.INFO,
            video(encoder="hevc_nvenc", preset="p4", custom_params="rc-lookahead=20"),
            video(encoder="hevc_nvenc", preset="p4", custom_params="init_qpB=20"),
        ),
    ]
