"""The option search, the HDR options, option resolution and the option linter checks. Pure: no
FFmpeg."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from reframe.command.video import hdr_params
from reframe.definitions import (
    OPTION_CATEGORIES,
    Condition,
    Definitions,
    describe_condition,
    effective_option,
    hdr_options,
    load_definitions,
    option_context,
    option_default,
    search_options,
    unmet_conditions,
)
from reframe.definitions.hdr import content_light_text, svt_mastering_display, x265_master_display
from reframe.definitions.loader import load_raw
from reframe.definitions.search import cli_name
from reframe.models import (
    AverageBitrate,
    ContentLightLevel,
    HdrFormat,
    HdrInfo,
    MasteringDisplay,
    VideoSettings,
    VideoStream,
)
from reframe_testing.definitions_lint import lint_definitions

DEFS = load_definitions()
X264, X265 = DEFS.video_encoders["libx264"], DEFS.video_encoders["libx265"]
SVT = DEFS.video_encoders["libsvtav1"]


def _keys(encoder_id: str, query: str) -> list[str]:
    return [o.key for o in search_options(DEFS.video_encoders[encoder_id].options, query)]


def test_psy_finds_psy_rd_and_psy_rdoq_first() -> None:
    assert _keys("libx265", "psy")[:2] == ["psy-rd", "psy-rdoq"]
    assert _keys("libx264", "psy")[:3] == ["psy", "psy-rd", "psy-trellis"]


def test_search_is_case_insensitive_and_ranks_exact_names_first() -> None:
    assert _keys("libx265", "SAO")[0] == "sao"
    assert _keys("libx265", "Psy-RDOQ")[0] == "psy-rdoq"
    # The label: "Strong intra smoothing".
    assert _keys("libx265", "smoothing") == ["strong-intra-smoothing"]


def test_search_covers_cli_names_choices_help_and_categories() -> None:
    # The CLI name differs from the key: x264 psy-trellis writes psy-rd.
    assert "psy-trellis" in _keys("libx264", "psy-rd")
    # FFmpeg arguments without their dash; a leading dash in the query is ignored.
    assert _keys("hevc_nvenc", "-bf") == ["bf"]
    assert cli_name(DEFS.video_encoders["hevc_nvenc"].option("bf")) == "bf"  # type: ignore[arg-type]
    # A choice ("umh" of x264 me) and help text ("blocking").
    assert _keys("libx264", "umh") == ["me"]
    assert "aq-mode" in _keys("libx264", "blocking")
    # A category: every loop filter.
    loop = _keys("libx265", "loop")
    assert {"sao", "deblock-tc", "strong-intra-smoothing"} <= set(loop)


def test_every_word_of_the_query_must_match() -> None:
    assert _keys("libx265", "psy rdoq") == ["psy-rdoq"]
    assert _keys("libx265", "psy zebra") == []


def test_an_empty_query_lists_every_option_in_order() -> None:
    assert search_options(X265.options, "") == X265.options
    assert search_options(X265.options, "  -  ") == X265.options


HDR = VideoStream.model_validate(
    {
        "index": 0,
        "width": 3840,
        "height": 2160,
        "hdr": HdrInfo(
            formats=[HdrFormat.HDR10],
            mastering_display=MasteringDisplay(
                red_x=0.68, red_y=0.32, green_x=0.265, green_y=0.69, blue_x=0.15, blue_y=0.06,
                white_x=0.3127, white_y=0.329, min_luminance=0.0001, max_luminance=1000,
            ),
            content_light=ContentLightLevel(max_cll=1000, max_fall=400),
        ),
    }
)  # fmt: skip


def test_hdr_options_per_encoder() -> None:
    """The values of the ``hdr10`` fixture (``_X265_HDR10`` in reframe_testing.media)."""
    assert hdr_options(X265, HDR) == {
        "master-display": "G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(10000000,1)",
        "max-cll": "1000,400",
    }
    assert hdr_options(SVT, HDR) == {
        "mastering-display": "G(0.265,0.69)B(0.15,0.06)R(0.68,0.32)WP(0.3127,0.329)L(1000,0.0001)",
        "content-light": "1000,400",
    }
    for encoder_id in ("libx264", "libvpx-vp9", "hevc_nvenc", "hevc_qsv", "hevc_amf"):
        assert hdr_options(DEFS.video_encoders[encoder_id], HDR) == {}


def test_hdr_options_match_what_the_builder_writes() -> None:
    """The builder writes the same strings when the output stays HDR (one formatter)."""
    for encoder in (X265, SVT):
        written = hdr_params(encoder, HDR)
        for key, value in hdr_options(encoder, HDR).items():
            option = encoder.option(key)
            assert option is not None
            assert written[option.mapping.name] == value  # type: ignore[union-attr]


def test_missing_or_empty_hdr_metadata() -> None:
    sdr = HDR.model_copy(update={"hdr": None})
    assert hdr_options(X265, sdr) == {}
    hdr = HDR.hdr
    assert hdr is not None
    assert hdr.mastering_display is not None
    no_peak = hdr.model_copy(
        update={
            "mastering_display": hdr.mastering_display.model_copy(update={"max_luminance": 0}),
            "content_light": ContentLightLevel(max_cll=0, max_fall=0),
        }
    )
    assert hdr_options(X265, HDR.model_copy(update={"hdr": no_peak})) == {}
    only_cll = hdr.model_copy(update={"mastering_display": None})
    assert hdr_options(SVT, HDR.model_copy(update={"hdr": only_cll})) == {
        "content-light": "1000,400"
    }


def test_hdr_formatters() -> None:
    md = MasteringDisplay(
        red_x=0.708, red_y=0.292, green_x=0.17, green_y=0.797, blue_x=0.131, blue_y=0.046,
        white_x=0.3127, white_y=0.329, min_luminance=0.005, max_luminance=4000,
    )  # fmt: skip
    assert x265_master_display(md) == (
        "G(8500,39850)B(6550,2300)R(35400,14600)WP(15635,16450)L(40000000,50)"
    )
    assert svt_mastering_display(md) == (
        "G(0.17,0.797)B(0.131,0.046)R(0.708,0.292)WP(0.3127,0.329)L(4000,0.005)"
    )
    assert content_light_text(ContentLightLevel(max_cll=4000, max_fall=1000)) == "4000,1000"


def test_option_defaults_and_context() -> None:
    bframes = X265.option("bframes")
    assert bframes is not None
    assert option_default(bframes, "slower") == 8
    assert option_default(bframes, None) is None
    pools = X265.option("pools")
    assert pools is not None
    assert option_default(pools, "medium") is None
    assert option_default(X265.option("wpp"), "medium") is True  # type: ignore[arg-type]
    video = VideoSettings(encoder="libx265", preset="slow", advanced={"rd": 5})
    context = option_context(X265, video)
    assert context["preset"] == "slow"
    assert context["option:rd"] == 5
    assert context["option:rect"] is True
    assert context["rate_control"] == "quality"
    assert option_context(X265, VideoSettings(encoder="libx265"))["preset"] == "medium"
    two = VideoSettings(encoder="libx265", rate_control=AverageBitrate(two_pass=True))
    assert option_context(X265, two)["two_pass"] is True
    assert effective_option(X265, video, "rd") == 5
    assert effective_option(X265, video, "rect") is True
    assert effective_option(X265, video, "no-such-option") is None


def test_unmet_conditions_and_their_text() -> None:
    amp = X265.option("amp")
    assert amp is not None
    medium = option_context(X265, VideoSettings(encoder="libx265", advanced={"amp": True}))
    unmet = unmet_conditions(amp, medium)
    assert [describe_condition(c, X265) for c in unmet] == ["Rectangular partitions (rect) on"]
    rd_refine = X265.option("rd-refine")
    assert rd_refine is not None
    texts = [describe_condition(c, X265) for c in rd_refine.requires]
    assert texts == ["RD level (rd) 5 or 6", "Adaptive quantisation (aq-mode) not Off"]
    hrd = X265.option("hrd")
    assert hrd is not None
    assert describe_condition(hrd.requires[0], X265) == "VBV maximum rate (vbv-maxrate) not 0"
    conditions: list[tuple[Condition, str]] = [
        (Condition(field="rate_control", value="bitrate"), "the rate control average bitrate"),
        (Condition(field="two_pass", value=True), "2-pass on"),
        (Condition(field="bit_depth", value=10), "the bit depth 10"),
        (Condition(field="tune", op="in", value=["grain", "film"]), "the tune grain or film"),
        (Condition(field="option:gone", value=1.0), "gone 1"),
    ]
    for condition, text in conditions:
        assert describe_condition(condition, X265) == text


def _lint_mutated(mutate: Callable[[dict[str, Any]], None]) -> list[str]:
    raw = load_raw()
    mutate(raw)
    return lint_definitions(Definitions.model_validate(raw))


def _option(raw: dict[str, Any], encoder: str, key: str) -> dict[str, Any]:
    options: list[dict[str, Any]] = raw["video_encoders"][encoder]["options"]
    return next(o for o in options if o["key"] == key)


def test_every_option_is_in_a_category_of_the_panel() -> None:
    for encoder in DEFS.video_encoders.values():
        for option in encoder.options:
            assert option.category in OPTION_CATEGORIES, (encoder.id, option.key)
    problems = _lint_mutated(lambda raw: _option(raw, "libx265", "rect").update(category="Misc"))
    assert any("libx265.options.rect" in p and "unknown category" in p for p in problems)


@pytest.mark.parametrize(
    ("encoder", "key", "mapping", "needle"),
    [
        ("libx265", "amp", {"kind": "x26x_param", "name": "rect"}, "like option 'rect'"),
        ("hevc_nvenc", "gpu", {"kind": "ffmpeg_arg", "arg": "-bf"}, "like option 'bf'"),
        ("libx265", "rect", {"kind": "x26x_param", "name": "level-idc"}, "levels already"),
        ("hevc_nvenc", "gpu", {"kind": "private_opt", "name": "cq"}, "rate control already"),
        ("libsvtav1", "lp", {"kind": "x26x_param", "name": "fast-decode"}, "fast decode"),
        ("libvpx-vp9", "threads", {"kind": "private_opt", "name": "row-mt"}, "extra_args"),
    ],
)
def test_an_option_that_writes_what_something_else_writes(
    encoder: str, key: str, mapping: dict[str, str], needle: str
) -> None:
    problems = _lint_mutated(lambda raw: _option(raw, encoder, key).update(mapping=mapping))
    assert any(f"{encoder}.options.{key}" in p and needle in p for p in problems), problems


def test_nvenc_multipass_may_share_the_argument_of_2_pass() -> None:
    """The option is for constant quality, NVENC's 2-pass for average bitrate."""
    assert lint_definitions(DEFS) == []

    def bitrate_too(raw: dict[str, Any]) -> None:
        _option(raw, "hevc_nvenc", "multipass")["requires"] = []

    problems = _lint_mutated(bitrate_too)
    assert any("hevc_nvenc.options.multipass" in p and "2-pass" in p for p in problems)
