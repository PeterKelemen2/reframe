"""convert_quality, supported_options / supported_presets, and the loader's merge rules."""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from reframe.definitions import (
    convert_quality,
    load_definitions,
    supported_options,
    supported_presets,
)
from reframe.definitions.loader import resolve_video_encoders
from reframe.models.capabilities import EncoderStatus

_WITH_QUALITY = sorted(
    e.id for e in load_definitions().video_encoders.values() if e.rate_control.quality is not None
)

# --------------------------------------------------------------------------- convert_quality


def test_same_scale_encoders_keep_the_value() -> None:
    assert convert_quality(22, "libx264", "libx265") == 22
    assert convert_quality(22.25, "libx264", "libx264") == 22.3  # a half step goes up
    assert convert_quality(22.24, "libx264", "libx264") == 22.2
    assert convert_quality(99, "libx264", "libx264") == 51


def test_a_half_step_rounds_up_on_every_scale() -> None:
    """M2 review: x264 23 is 26.5 on the QSV, AMF and VAAPI scales. Banker's rounding gave
    QSV (min 1) 27 but AMF and VAAPI (min 0) 26."""
    assert {
        e: convert_quality(23, "libx264", e)
        for e in ("hevc_qsv", "hevc_amf", "h264_amf", "hevc_vaapi", "h264_vaapi")
    } == dict.fromkeys(("hevc_qsv", "hevc_amf", "h264_amf", "hevc_vaapi", "h264_vaapi"), 27)


@pytest.mark.parametrize(
    "encoder", ["libsvtav1", "av1_amf", "h264_vaapi", "hevc_vaapi", "av1_vaapi"]
)
def test_quality_zero_is_not_offered_where_the_encoder_ignores_it(encoder: str) -> None:
    """M2 review: SVT-AV1 `-crf 0`, VAAPI `-global_quality 0` and AMF AV1 QP 0 give the
    encoder's default quality (test_tools.py `test_quality_range_ends_are_honoured`), so the
    best end of the range is 1 and a converted 0 lands there."""
    mode = load_definitions().video_encoders[encoder].rate_control.quality
    assert mode is not None
    assert mode.min == 1
    assert convert_quality(0, "libx264", encoder) == 1


def test_h264_and_hevc_vaapi_stop_at_51() -> None:
    """`-global_quality 52` gives the same file as 51 (H.264 / H.265 QP is 0-51)."""
    for encoder in ("h264_vaapi", "hevc_vaapi"):
        mode = load_definitions().video_encoders[encoder].rate_control.quality
        assert mode is not None
        assert mode.max == 51


@pytest.mark.parametrize("encoder", _WITH_QUALITY)
def test_defaults_sit_on_the_conversion_scale(encoder: str) -> None:
    """Every default is what x264 RF 22 (HandBrake's 1080p presets) converts to. The M2 review
    found h264_vaapi at 20 (x264 17.6) and av1_qsv at 24 (x264 24, the 2160p value)."""
    mode = load_definitions().video_encoders[encoder].rate_control.quality
    assert mode is not None
    assert mode.default == convert_quality(22, "libx264", encoder)


def test_handbrake_preset_equivalents() -> None:
    """HandBrake's 1080p / 2160p presets: x264 22 / 24 ↔ NVENC 27 / 30 ↔ QSV, VCN 25 / 28."""
    assert convert_quality(22, "libx265", "hevc_nvenc") == 27
    assert convert_quality(24, "libx265", "hevc_nvenc") == 30
    assert convert_quality(22, "libx265", "hevc_qsv") == 25
    assert convert_quality(28, "hevc_amf", "libx265") == 24
    assert convert_quality(35, "libsvtav1", "libx264") == 24
    assert convert_quality(120, "av1_amf", "libsvtav1") == 35


def test_conversion_clamps_and_rounds_to_the_target() -> None:
    assert convert_quality(0, "libx264", "hevc_nvenc") == 1  # NVENC CQ starts at 1
    assert convert_quality(51, "libx264", "av1_amf") == 255
    value = convert_quality(23.7, "libx264", "hevc_qsv")
    assert value == round(value)


def test_conversion_errors() -> None:
    with pytest.raises(KeyError):
        convert_quality(22, "nope", "libx265")
    defs = load_definitions()
    no_quality = defs.model_copy(deep=True)
    no_quality.video_encoders["libx265"].rate_control.quality = None
    with pytest.raises(ValueError, match="no constant-quality"):
        convert_quality(22, "libx264", "libx265", definitions=no_quality)


@given(
    st.sampled_from(_WITH_QUALITY),
    st.sampled_from(_WITH_QUALITY),
    st.floats(0, 1),
    st.floats(0, 1),
)
def test_conversion_is_monotonic_and_in_range(src: str, dst: str, a: float, b: float) -> None:
    mode = load_definitions().video_encoders[src].rate_control.quality
    target = load_definitions().video_encoders[dst].rate_control.quality
    assert mode is not None
    assert target is not None
    lo, hi = sorted((mode.min + a * (mode.max - mode.min), mode.min + b * (mode.max - mode.min)))
    x, y = convert_quality(lo, src, dst), convert_quality(hi, src, dst)
    assert target.min <= x <= y <= target.max


# --------------------------------------------------------------------------- supported_options


def test_none_status_hides_nothing() -> None:
    enc = load_definitions().video_encoders["hevc_nvenc"]
    assert supported_options(enc, None) == enc.options
    assert supported_options(enc, EncoderStatus(id="hevc_nvenc")) == enc.options


def test_private_options_missing_from_the_build_are_hidden() -> None:
    enc = load_definitions().video_encoders["hevc_nvenc"]
    status = EncoderStatus(id="hevc_nvenc", private_options=["preset", "spatial-aq"])
    keys = [o.key for o in supported_options(enc, status)]
    assert "spatial-aq" in keys
    assert "temporal-aq" not in keys  # private, not listed
    assert "bf" in keys
    assert "refs" in keys


def test_x26x_params_need_the_params_argument() -> None:
    enc = load_definitions().video_encoders["libx265"]
    with_params = EncoderStatus(id="libx265", private_options=["preset", "x265-params"])
    without = EncoderStatus(id="libx265", private_options=["preset", "crf"])
    assert supported_options(enc, with_params) == enc.options
    assert supported_options(enc, without) == []


def test_supported_presets() -> None:
    nvenc = load_definitions().video_encoders["hevc_nvenc"]
    assert len(supported_presets(nvenc, None)) == 7
    status = EncoderStatus(id="hevc_nvenc", presets=["p1", "p4", "slow"])
    assert [c.value for c in supported_presets(nvenc, status)] == ["p1", "p4"]
    vp9 = load_definitions().video_encoders["libvpx-vp9"]
    by_written = EncoderStatus(id="libvpx-vp9", presets=["2"])
    assert [c.value for c in supported_presets(vp9, by_written)] == ["medium"]
    defs = load_definitions().model_copy(deep=True)
    defs.video_encoders["libx264"].presets = None
    assert supported_presets(defs.video_encoders["libx264"], None) == []


# --------------------------------------------------------------------------- loader


def _raw() -> dict[str, Any]:
    return {
        "base": {"b": {"help": "base help", "rate_control": {"quality": {"min": 0, "max": 51}}}},
        "encoder": {
            "e1": {"extends": "b", "label": "E1", "rate_control": {"quality": {"max": 63}}},
            "e2": {"extends": ["b"], "option_sets": ["s"], "options": [{"key": "own"}]},
        },
    }


def test_extends_merges_tables_and_option_sets_prepend() -> None:
    resolved = resolve_video_encoders(_raw(), {"s": [{"key": "shared"}]})
    assert resolved["e1"]["id"] == "e1"
    assert resolved["e1"]["help"] == "base help"
    assert resolved["e1"]["rate_control"]["quality"] == {"min": 0, "max": 63}
    assert resolved["e2"]["rate_control"]["quality"] == {"min": 0, "max": 51}
    assert [o["key"] for o in resolved["e2"]["options"]] == ["shared", "own"]
    assert "extends" not in resolved["e1"]
    assert "option_sets" not in resolved["e2"]


def test_merged_tables_are_not_shared() -> None:
    sets = {"s": [{"key": "shared"}]}
    raw = _raw()
    raw["encoder"]["e1"]["option_sets"] = ["s"]
    resolved = resolve_video_encoders(raw, sets)
    resolved["e1"]["options"][0]["key"] = "changed"
    resolved["e1"]["rate_control"]["quality"]["min"] = 5
    assert resolved["e2"]["options"][0]["key"] == "shared"
    assert resolved["e2"]["rate_control"]["quality"]["min"] == 0
    assert raw["base"]["b"]["rate_control"]["quality"]["min"] == 0


def test_unknown_base_or_option_set_is_an_error() -> None:
    raw = _raw()
    raw["encoder"]["e1"]["extends"] = "nope"
    with pytest.raises(ValueError, match="unknown base 'nope'"):
        resolve_video_encoders(raw, {"s": []})
    with pytest.raises(ValueError, match="unknown option set 's'"):
        resolve_video_encoders(_raw(), {})
