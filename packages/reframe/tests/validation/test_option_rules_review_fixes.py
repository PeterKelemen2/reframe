"""Option rules for the x265 level padding, the VBV pair and the HDR text formats."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from reframe.models import AverageBitrate, ConstantQuality, FitWithin, Severity


def _load(name: str) -> ModuleType:
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


def _found(**video: Any) -> list[tuple[str, str, Severity]]:
    s = sc.base()
    for key, value in video.items():
        setattr(s.job.video, key, value)
    return [(i.code, i.path, i.severity) for i in sc.check(s)]


def _level_errors(preset: str, advanced: dict[str, Any]) -> set[str]:
    s = sc.base()
    s.source.video[0].height = 1160
    s.job.dimensions.size = FitWithin(width=1920, height=1160)
    s.job.video.encoder = "libx265"
    s.job.video.level = "4.0"
    s.job.video.preset = preset
    s.job.video.advanced = advanced
    return {i.code for i in sc.check(s) if i.severity is Severity.ERROR}


def test_r5_4_level_with_min_cu_size_16_at_medium() -> None:
    assert "encoder.level_too_low" in _level_errors("medium", {"min-cu-size": "16"})
    assert "encoder.level_too_low" not in _level_errors("medium", {})


def test_r5_4_level_with_min_cu_size_8_at_ultrafast() -> None:
    assert "encoder.level_too_low" not in _level_errors("ultrafast", {"min-cu-size": "8"})
    assert "encoder.level_too_low" in _level_errors("ultrafast", {})


@pytest.mark.parametrize("encoder", ["libx264", "libx265"])
def test_r5_7_vbv_maxrate_without_a_buffer_is_inactive(encoder: str) -> None:
    """x264 drops it without a word (SEI ``rc=crf``, no VBV); x265 logs "VBV maxrate
    specified, but no bufsize, ignored"."""
    found = _found(encoder=encoder, advanced={"vbv-maxrate": 5000})
    assert ("encoder.option_inactive", "video.advanced.vbv-maxrate", Severity.WARNING) in found
    for rc in (ConstantQuality(value=22), AverageBitrate(kbps=2000)):
        found = _found(encoder=encoder, rate_control=rc, advanced={"vbv-maxrate": 5000})
        assert ("encoder.option_inactive", "video.advanced.vbv-maxrate", Severity.WARNING) in found
    both = _found(encoder=encoder, advanced={"vbv-maxrate": 5000, "vbv-bufsize": 6000})
    assert not [f for f in both if f[1].startswith("video.advanced.vbv")]


@pytest.mark.parametrize("encoder", ["libx264", "libx265"])
def test_r5_7_a_vbv_buffer_without_a_maximum_rate(encoder: str) -> None:
    """At a constant quality it is dropped ("VBV bufsize set but maxrate unspecified,
    ignored"); with an average bitrate the encoder uses the bitrate as the maximum ("VBV maxrate
    unspecified, assuming CBR"): not reported."""
    found = _found(encoder=encoder, advanced={"vbv-bufsize": 5000})
    assert ("encoder.option_inactive", "video.advanced.vbv-bufsize", Severity.WARNING) in found
    abr = _found(
        encoder=encoder, rate_control=AverageBitrate(kbps=2000), advanced={"vbv-bufsize": 5000}
    )
    assert not [f for f in abr if f[1].startswith("video.advanced.vbv")]


X265_MD = "G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(10000000,1)"
SVT_MD = "G(0.265,0.69)B(0.15,0.06)R(0.68,0.32)WP(0.3127,0.329)L(1000,0.0001)"
X265_SPACED = X265_MD.replace("(13250,", "(13250, ")
X265_R_FIRST = "R(34000,16000)G(13250,34500)B(7500,3000)WP(15635,16450)L(10000000,1)"
SVT_R_FIRST = "R(0.68,0.32)G(0.265,0.69)B(0.15,0.06)WP(0.3127,0.329)L(1000,0.0001)"
SVT_SHORT = "G(.265,.69)B(.15,.06)R(.68,.32)WP(.3127,.329)L(1e3,1e-4)"


@pytest.mark.parametrize(
    ("encoder", "key", "value", "valid"),
    [
        ("libx265", "master-display", X265_MD, True),
        ("libx265", "master-display", X265_SPACED, True),
        ("libx265", "master-display", "garbage", False),
        ("libx265", "master-display", X265_MD.removesuffix("L(10000000,1)"), False),
        ("libx265", "master-display", SVT_MD, False),  # plain numbers: x265 cannot parse them
        ("libx265", "master-display", X265_R_FIRST, False),
        ("libx265", "master-display", X265_MD.replace("13250", "70000"), False),  # wraps
        ("libx265", "master-display", X265_MD + "junk", False),
        ("libx265", "max-cll", "1000,400", True),
        ("libx265", "max-cll", "1000, 400", True),
        ("libx265", "max-cll", "1000", False),  # "Invalid value", MaxFALL 0
        ("libx265", "max-cll", "garbage", False),
        ("libx265", "max-cll", "70000,400", False),  # wraps to 4464
        ("libsvtav1", "mastering-display", SVT_MD, True),
        ("libsvtav1", "mastering-display", SVT_R_FIRST, True),
        ("libsvtav1", "mastering-display", SVT_SHORT, True),
        ("libsvtav1", "mastering-display", "garbage", False),  # no metadata, no message
        ("libsvtav1", "mastering-display", SVT_MD + "junk", False),  # FFmpeg never ends
        ("libsvtav1", "mastering-display", "junk" + SVT_MD, False),
        ("libsvtav1", "mastering-display", SVT_MD.removesuffix("L(1000,0.0001)"), False),
        ("libsvtav1", "mastering-display", SVT_MD.replace("0.265", "2"), False),  # clipped
        ("libsvtav1", "mastering-display", X265_MD, False),  # luminance overflow
        ("libsvtav1", "content-light", "1000,400", True),
        ("libsvtav1", "content-light", "1000", False),  # "Invalid cll provided"
        ("libsvtav1", "content-light", "1000,400,5", False),
        ("libsvtav1", "content-light", "70000,400", False),  # clipped to 65535
    ],
)  # fmt: skip
def test_r5_8_the_hdr_text_options_are_checked(
    encoder: str, key: str, value: str, valid: bool
) -> None:
    found = _found(encoder=encoder, bit_depth=10, advanced={key: value})
    invalid = ("encoder.option_invalid", f"video.advanced.{key}", Severity.ERROR)
    assert (invalid in found) is not valid, found


def test_r5_8_copy_hdr_metadata_writes_valid_text() -> None:
    from reframe.definitions import hdr_options, load_definitions
    from reframe.models import ContentLightLevel, HdrInfo, MasteringDisplay

    source = sc.make_source()
    stream = source.video[0]
    stream.hdr = HdrInfo(
        mastering_display=MasteringDisplay(
            red_x=0.68, red_y=0.32, green_x=0.265, green_y=0.69, blue_x=0.15, blue_y=0.06,
            white_x=0.3127, white_y=0.329, max_luminance=1000.0, min_luminance=0.00005,
        ),
        content_light=ContentLightLevel(max_cll=1000, max_fall=400),
    )  # fmt: skip
    defs = load_definitions()
    for encoder in ("libx265", "libsvtav1"):
        values = hdr_options(defs.video_encoders[encoder], stream)
        assert len(values) == 2
        found = _found(encoder=encoder, bit_depth=10, advanced=values)
        assert not [f for f in found if f[0] == "encoder.option_invalid"], (encoder, values)


X265_SIGNED = "G(+13250,+34500)B(+7500,+3000)R(+34000,+16000)WP(+15635,+16450)L(+10000000,+1)"
SVT_SIGNED = "G(+0.265,+0.69)B(+.15,+.06)R(+0.68,+0.32)WP(+0.3127,+0.329)L(+1e+3,+1e-4)"
ARABIC_13250 = "\u0661\u0663\u0662\u0665\u0660"


@pytest.mark.parametrize(
    ("encoder", "key", "value", "valid"),
    [
        # x265 (sscanf %hu / %u) and SVT-AV1 take a "+" and write the same as without it.
        ("libx265", "master-display", X265_SIGNED, True),
        ("libx265", "master-display", X265_MD.replace("(13250", "( +13250"), True),
        ("libx265", "max-cll", "+1000,+400", True),
        ("libsvtav1", "mastering-display", SVT_SIGNED, True),
        ("libsvtav1", "content-light", "+1000,+400", True),
        # "-0" is written as 0; any other negative number wraps or is changed.
        ("libx265", "master-display", X265_MD.replace("L(10000000,1)", "L(10000000,-0)"), True),
        ("libx265", "max-cll", "1000,-0", True),
        ("libsvtav1", "mastering-display", SVT_MD.replace("L(1000,0.0001)", "L(1000,-0.0)"), True),
        ("libsvtav1", "content-light", "1000,-0", True),
        ("libx265", "master-display", X265_MD.replace("(13250", "(-1"), False),  # 65535
        ("libx265", "master-display", X265_MD.replace("L(10000000,1)", "L(10000000,-1)"), False),
        ("libx265", "max-cll", "1000,-400", False),  # 65136
        ("libsvtav1", "mastering-display", SVT_MD.replace("(0.265", "(-0.265"), False),  # 0.735
        ("libsvtav1", "mastering-display", SVT_MD.replace("0.0001)", "-0.0001)"), False),
        ("libsvtav1", "content-light", "-1,400", False),  # 65535
        # Not parsed: two signs, a space after the sign.
        ("libx265", "master-display", X265_MD.replace("(13250", "(++13250"), False),
        ("libx265", "master-display", X265_MD.replace("(13250", "(+ 13250"), False),
        ("libsvtav1", "mastering-display", SVT_MD.replace("(0.265", "(++0.265"), False),
        ("libsvtav1", "content-light", "+ 1000,400", False),
        # C white space before a number is skipped; other characters are not.
        ("libx265", "master-display", X265_MD.replace("(13250", "(\t\v\f13250"), True),
        ("libsvtav1", "content-light", "1000,\v400", True),
        ("libx265", "master-display", X265_MD.replace("(13250", "(\u00a013250"), False),
        ("libx265", "master-display", X265_MD.replace("13250", ARABIC_13250), False),
        ("libx265", "max-cll", "\u0661000,400", False),
        ("libsvtav1", "mastering-display", SVT_MD.replace("(0.265", "(\u00a00.265"), False),
        # FFmpeg drops only " \n\t\r" around the value: x265 cannot parse a text that starts
        # with a vertical tab, and SVT-AV1 never ends.
        ("libx265", "master-display", "\v" + X265_MD, False),
        ("libsvtav1", "mastering-display", "\f" + SVT_MD, False),
        ("libx265", "master-display", " \t" + X265_MD + "\n", True),
    ],
)  # fmt: skip
def test_rc_2_signs_and_spaces_as_the_encoders_read_them(
    encoder: str, key: str, value: str, valid: bool
) -> None:
    found = _found(encoder=encoder, bit_depth=10, advanced={key: value})
    invalid = ("encoder.option_invalid", f"video.advanced.{key}", Severity.ERROR)
    assert (invalid in found) is not valid, found
