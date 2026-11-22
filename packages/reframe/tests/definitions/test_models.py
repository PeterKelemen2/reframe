"""Helpers on the definition models and the shape of the packaged data."""

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
from reframe.models.job import FilterConfig, FilterSettings, OptionValue


def test_derived_values_follow_handbrake_offsets() -> None:
    p = DerivedValue(offset=2, ramp_below=8, max=51, integer=True)
    assert p.compute(25) == 27
    assert p.compute(4) == 5  # offset scaled: 2 * 4 / 8 = 1
    assert p.compute(50) == 51
    i = DerivedValue(offset=-2, min=0, integer=True)
    assert i.compute(1) == 0
    assert DerivedValue().compute(22.5) == 22.5
    assert DerivedValue(offset=0.5, integer=True).compute(2) == 3  # half up, not to even


def test_av1_nvenc_initial_qps_are_on_the_qindex_scale() -> None:
    mode = load_definitions().video_encoders["av1_nvenc"].rate_control.quality
    assert mode is not None
    derived = mode.derived
    assert derived["qp_p"].compute(mode.max) == 255
    assert derived["qp_p"].compute(mode.default) == 134  # 33 · 255 / 63
    assert derived["qp_i"].compute(mode.default) == 126
    assert derived["qp_b"].compute(mode.default) == 142
    assert all(d.compute(mode.min) >= 0 and d.compute(mode.max) <= 255 for d in derived.values())


def test_a_copy_deny_list_wins_over_the_wildcard() -> None:
    mkv = load_definitions().containers["mkv"]
    for codec in ("pcm_bluray", "pcm_dvd", "s302m", "pcm_s8", "pcm_u16le", "dsd_lsbf_planar"):
        assert not mkv.audio.can_copy(codec), codec
    for codec in ("pcm_s16le", "pcm_s24le", "pcm_s16be", "pcm_u8", "pcm_f32le", "truehd"):
        assert mkv.audio.can_copy(codec), codec
    assert not mkv.video.can_copy("qtrle")
    assert mkv.video.can_copy("prores")


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


def test_filter_implementation_choice() -> None:
    tonemap = load_definitions().filters["tonemap"]
    assert [i.id for i in tonemap.implementations] == ["libplacebo", "zscale"]
    default = FilterConfig()
    impl = tonemap.implementation_for(default)
    assert impl is not None
    assert impl.id == "libplacebo"
    assert impl.needs_vulkan
    no_vulkan = {"libplacebo": False, "zscale": True, "tonemap": True}
    impl = tonemap.implementation_for(default, no_vulkan)
    assert impl is not None
    assert impl.id == "zscale"
    assert impl.requires_tagged_input
    assert tonemap.implementation_for(default, {"zscale": True}) is None
    # An explicit choice is kept, or fails: it never falls back.
    chosen = FilterConfig(implementation="libplacebo")
    assert tonemap.implementation_for(chosen, no_vulkan) is None
    assert tonemap.implementation_for(FilterConfig(implementation="nope")) is None
    # With no choice, an implementation that lacks the preset is skipped.
    static = FilterConfig(preset="static")
    assert tonemap.implementation_for(static, no_vulkan) is None
    impl = tonemap.implementation_for(static)
    assert impl is not None
    assert impl.id == "libplacebo"
    assert tonemap.implementation_for() is not None
    assert tonemap.implementation("zscale") is not None
    assert tonemap.implementation("nope") is None


def test_filter_chain_for_a_config() -> None:
    filters = load_definitions().filters
    denoise = filters["denoise"]
    light = denoise.chain_for(FilterConfig(preset="light"))
    assert light is not None
    assert light.startswith("nlmeans=")
    film = denoise.chain_for(FilterConfig(preset="light", tune="film"))
    assert film is not None
    assert film.startswith("nlmeans=")
    fast = denoise.chain_for(FilterConfig(preset="light", implementation="hqdn3d"))
    assert fast == "hqdn3d=luma_spatial=2:chroma_spatial=1:luma_tmp=2:chroma_tmp=3"
    custom = denoise.chain_for(FilterConfig(preset="custom", implementation="hqdn3d", custom="4"))
    assert custom == "hqdn3d=4"
    assert denoise.chain_for(FilterConfig(preset="nope")) is None
    yadif = filters["deinterlace"].chain_for(
        FilterConfig(preset="skip-spatial", implementation="yadif")
    )
    assert yadif == "yadif=mode=send_frame_nospatial:parity=auto"
    # bwdif has no "skip-spatial": with no choice, the yadif implementation is used.
    auto = filters["deinterlace"].chain_for(FilterConfig(preset="skip-spatial"))
    assert auto == yadif
    # A tune the implementation does not have falls back to the plain chain.
    zscale = filters["tonemap"].chain_for(
        FilterConfig(tune="bt2390"), {"libplacebo": False, "zscale": True, "tonemap": True}
    )
    assert zscale is not None
    assert "tonemap=hable" in zscale
    preset = filters["grayscale"].implementations[0].preset("default")
    assert preset is not None
    assert preset.chain_for("x") == "hue=s=0"
    needs_tune = preset.model_copy(update={"chain": None})
    impl = filters["grayscale"].implementations[0].model_copy(update={"presets": [needs_tune]})
    grayscale = filters["grayscale"].model_copy(update={"implementations": [impl]})
    assert grayscale.chain_for(FilterConfig()) is None
    deinterlace = filters["deinterlace"]
    assert all(i.combed_only == "deint=interlaced" for i in deinterlace.implementations)


def test_containers_answer_the_validation_questions() -> None:
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
    assert flags["hearing_impaired"].disposition == "hearing_impaired"


def test_passthru_and_mixdowns() -> None:
    defs = load_definitions()
    assert defs.passthru_codecs["dtshd"].profiles is not None
    assert "DTS-HD MA" in defs.passthru_codecs["dtshd"].profiles
    assert "DTS-HD MA" in defs.passthru_codecs["dts"].exclude_profiles
    assert defs.mixdowns["dpl2"].matrix_encoding == "dplii"
    assert defs.mixdowns["5.1"].channels == 6
    for enc in defs.audio_encoders.values():
        assert enc.passthru is not None
