"""Helpers on the definition models and the shape of the packaged data that C-7 / C-8 rely on."""

from __future__ import annotations

import pytest

from reframe.definitions import (
    AudioBitrateDef,
    BitrateLimits,
    ChoiceSetting,
    Condition,
    DerivedValue,
    load_definitions,
)
from reframe.definitions.models import FILTER_IDS, FILTER_STAGES, interpolate
from reframe.models.job import FilterSettings, OptionValue


def test_derived_values_follow_handbrake_offsets() -> None:
    p = DerivedValue(offset=2, ramp_below=8, max=51, integer=True)
    assert p.compute(25) == 27
    assert p.compute(4) == 5  # offset scaled: 2 * 4 / 8 = 1
    assert p.compute(50) == 51
    i = DerivedValue(offset=-2, min=0, integer=True)
    assert i.compute(1) == 0
    assert DerivedValue().compute(22.5) == 22.5


def test_condition_matching() -> None:
    ctx: dict[str, OptionValue | None] = {
        "rate_control": "quality",
        "option:aq-mode": "0",
        "bit_depth": 10,
    }
    assert Condition(field="rate_control", value="quality").matches(ctx)
    assert not Condition(field="rate_control", op="ne", value="quality").matches(ctx)
    assert Condition(field="option:aq-mode", op="in", value=["0", "1"]).matches(ctx)
    assert Condition(field="option:aq-mode", op="not_in", value=["1"]).matches(ctx)
    assert Condition(field="bit_depth", op="in", value=10).matches(ctx)
    assert not Condition(field="preset", value="slow").matches(ctx)


def test_choice_setting_helpers() -> None:
    profiles = load_definitions().video_encoders["libx265"].profiles
    assert isinstance(profiles, ChoiceSetting)
    assert profiles.values(10) == ["main10"]
    assert profiles.values() == ["main", "main10"]
    assert profiles.default_for(10) == "main10"
    assert profiles.default_for(8) == "main"
    assert profiles.get("nope") is None
    level = load_definitions().video_encoders["libsvtav1"].levels
    assert level is not None
    choice = level.get("4.1")
    assert choice is not None
    assert choice.written == "41"
    x264_level = load_definitions().video_encoders["libx264"].levels
    assert x264_level is not None
    choice = x264_level.get("4.1")
    assert choice is not None
    assert choice.written == "4.1"


def test_snap_down_and_up() -> None:
    ac3 = load_definitions().audio_encoders["ac3"].bitrate
    assert ac3 is not None
    assert ac3.snap(150, "stereo") == 128
    assert ac3.snap(150, "stereo", "up") == 160
    assert ac3.snap(700, "5.1") == 640
    assert ac3.snap(100, "5.1") == 224  # below the 5.1 minimum
    assert ac3.snap(10, "stereo", "up") == 96
    assert ac3.snap(5000, "stereo", "up") == 640
    assert ac3.snap(192, "7.1") is None
    assert ac3.values("5.1") == [224, 256, 320, 384, 448, 512, 576, 640]
    opus = load_definitions().audio_encoders["libopus"].bitrate
    assert opus is not None
    assert opus.snap(150, "stereo") == 150
    assert opus.snap(9999, "stereo") == 512
    assert opus.values("stereo") is None
    assert opus.values("7.1") is None
    free = AudioBitrateDef(by_mixdown={"stereo": BitrateLimits(min=64, max=320, default=128)})
    assert free.snap(1, "stereo", "up") == 64
    assert free.values("mono") is None


def test_interpolate() -> None:
    points = [(0.0, 0.0), (10.0, 20.0), (20.0, 25.0)]
    assert interpolate(points, 5) == 10
    assert interpolate(points, 15) == 22.5
    assert interpolate(points, 30) == 30  # extrapolates the last segment
    assert interpolate(points, -10) == -20
    assert interpolate([(0.0, 1.0), (0.0, 2.0)], 0) == 1.0
    with pytest.raises(ValueError, match="two points"):
        interpolate([(0.0, 0.0)], 1)


def test_filter_ids_match_the_job_model() -> None:
    """FilterSettings documents the ids; the definitions define exactly those."""
    doc = FilterSettings.__doc__ or ""
    for filter_id in FILTER_IDS:
        assert f"``{filter_id}``" in doc, filter_id
    defs = load_definitions()
    assert set(defs.filters) == set(FILTER_IDS)
    assert set(defs.filter_order) == set(FILTER_IDS) | set(FILTER_STAGES)


def test_filter_order_is_the_plan_order() -> None:
    """03 §Filters: detelecine → deinterlace → denoise → deblock → crop → scale → tone map /
    colorspace → sharpen → chroma smooth → grayscale → format/upload."""
    order = load_definitions().filter_order
    plan = [
        "detelecine",
        "deinterlace",
        "denoise",
        "deblock",
        "crop",
        "scale",
        "tonemap",
        "colorspace",
        "sharpen",
        "chroma_smooth",
        "grayscale",
        "format",
    ]
    assert [step for step in order if step in plan] == plan
    assert order.index("interlace_detection") == order.index("deinterlace") - 1
    assert order.index("crop") < order.index("custom") < order.index("scale")
    defs = load_definitions()
    assert [f.id for f in defs.ordered_filters()] == [s for s in order if s in defs.filters]
    assert defs.filters["denoise"].position == order.index("denoise")


def test_filter_implementation_choice() -> None:
    tonemap = load_definitions().filters["tonemap"]
    preset = tonemap.preset("default")
    assert preset is not None
    assert tonemap.preset("nope") is None
    impl = tonemap.implementation_for(preset)
    assert impl is not None
    assert impl.id == "libplacebo"
    impl = tonemap.implementation_for(
        preset, {"libplacebo": False, "zscale": True, "tonemap": True}
    )
    assert impl is not None
    assert impl.id == "zscale"
    assert impl.requires_tagged_input
    assert tonemap.implementation_for(preset, {"zscale": True}) is None
    assert preset.chain("zscale", "mobius") is not None
    assert "mobius" in (preset.chain("zscale", "mobius") or "")
    assert preset.chain("libplacebo") == preset.chain("libplacebo", None)
    denoise = load_definitions().filters["denoise"]
    fast = denoise.preset("hqdn3d-light")
    assert fast is not None
    impl = denoise.implementation_for(fast)
    assert impl is not None
    assert impl.id == "hqdn3d"
    light = denoise.preset("light")
    assert light is not None
    tuned_only = light.model_copy(update={"chains": {}})
    impl = denoise.implementation_for(tuned_only)
    assert impl is not None
    assert impl.id == "nlmeans"
    deinterlace = load_definitions().filters["deinterlace"]
    assert all(i.combed_only == "deint=interlaced" for i in deinterlace.implementations)


def test_containers_answer_the_c8_questions() -> None:
    c = load_definitions().containers
    assert c["mkv"].video.can_copy("vc1")
    assert c["mp4"].audio.can_copy("truehd")
    assert c["mp4"].audio.copy_args["truehd"] == ["-strict", "-2"]
    assert not c["mp4"].subtitles.can_copy("hdmv_pgs_subtitle")
    assert not c["mp4"].subtitles.can_copy("subrip")
    assert c["mp4"].text_subtitle_target == "mov_text"
    assert not c["webm"].audio.can_copy("aac")
    assert c["mp4"].format_flags["web_optimized"] == ["-movflags", "+faststart"]
    assert c["mp4"].codec_tags["hevc"] == "hvc1"
    assert not c["mp4"].attachments
    assert c["mkv"].attachments
    assert not c["webm"].attachments
    assert set(c["webm"].flags) == {"default", "forced"}
    assert "original" not in c["mp4"].flags
    assert c["mkv"].language_format == "iso639_2b"
    assert c["mp4"].language_format == "iso639_2t"
    assert c["mp4"].model_dump()["video"]["copy"]  # serialised under the alias
    flags = load_definitions().track_flags
    assert flags["commentary"].disposition == "comment"
    assert flags["hearing_impaired"].mkvpropedit == "flag-hearing-impaired"


def test_video_encoder_option_lookup() -> None:
    x265 = load_definitions().video_encoders["libx265"]
    option = x265.option("sao")
    assert option is not None
    assert option.type == "bool"
    assert x265.option("nope") is None


def test_passthru_and_mixdowns() -> None:
    defs = load_definitions()
    assert defs.passthru_codecs["dtshd"].profiles is not None
    assert "DTS-HD MA" in defs.passthru_codecs["dtshd"].profiles
    assert "DTS-HD MA" in defs.passthru_codecs["dts"].exclude_profiles
    assert defs.mixdowns["dpl2"].matrix_encoding == "dplii"
    assert defs.mixdowns["5.1"].channels == 6
    for enc in defs.audio_encoders.values():
        assert enc.passthru is not None
