"""``-encoders``, ``-filters`` and ``-h encoder=`` parsing, against real captured output of the
pinned build (``testing/reframe_testing/fake_data/``)."""

from __future__ import annotations

import pytest

from reframe.capabilities import parse_encoder_help, parse_encoders, parse_filters
from reframe.definitions import load_definitions
from reframe_testing import fake_tools as ft


def data_text(name: str) -> str:
    return (ft.DATA_DIR / name).read_text(encoding="utf-8")


def test_encoder_list_of_the_pinned_build() -> None:
    encoders = parse_encoders(data_text("encoders.stdout.txt"))
    assert len(encoders) > 200
    # the legend is not an encoder
    assert "=" not in encoders
    assert "------" not in encoders


def test_every_definition_encoder_but_libfdk_aac_is_in_the_pinned_build() -> None:
    encoders = parse_encoders(data_text("encoders.stdout.txt"))
    defs = load_definitions()
    known = set(defs.video_encoders) | set(defs.audio_encoders)
    assert known - encoders == {"libfdk_aac"}  # GPL builds have no FDK AAC


def test_encoder_list_of_garbage_is_empty() -> None:
    assert parse_encoders("") == frozenset()
    assert (
        parse_encoders("ffmpeg version n9.0.2\n V....D libx264 not after a separator\n")
        == frozenset()
    )


def test_filter_list_of_the_pinned_build() -> None:
    filters = parse_filters(data_text("filters.stdout.txt"))
    assert len(filters) > 500
    assert {"libplacebo", "zscale", "tonemap", "scale", "hwupload", "bwdif"} <= set(filters)
    assert filters == sorted(filters)
    assert "=" not in filters
    assert "|" not in filters


def test_filter_list_with_three_flag_columns() -> None:
    text = (
        "Filters:\n  T.. = Timeline support\n  .S. = Slice threading\n  ..C = Command support\n"
        "  A = Audio input/output\n  | = Source or sink filter\n  ------\n"
        " ... abench            A->A       Benchmark part of a filtergraph.\n"
        " TSC zscale            V->V       Apply resizing, colorspace and bit depth conversion.\n"
        " ... buffer            |->V       Buffer video frames.\n"
    )
    assert parse_filters(text) == ["abench", "buffer", "zscale"]


def test_filter_list_of_garbage_is_empty() -> None:
    assert parse_filters("") == []


HELP_FILES = sorted(
    p.stem.removesuffix(".stdout") for p in (ft.DATA_DIR / "help_encoder").iterdir()
)


@pytest.mark.parametrize("name", HELP_FILES)
def test_every_captured_help_text_parses(name: str) -> None:
    parsed = parse_encoder_help(data_text(f"help_encoder/{name}.stdout.txt"))
    assert parsed is not None
    assert "Exiting" not in " ".join(parsed.private_options)


def test_help_of_libx265() -> None:
    parsed = parse_encoder_help(data_text("help_encoder/libx265.stdout.txt"))
    assert parsed is not None
    assert parsed.private_options == [
        "crf",
        "qp",
        "forced-idr",
        "preset",
        "tune",
        "profile",
        "x265-stats",
        "udu_sei",
        "a53cc",
        "x265-params",
        "dolbyvision",
    ]
    assert parsed.presets == []
    assert "yuv420p10le" in parsed.pix_fmts


def test_help_of_hevc_nvenc_lists_the_named_presets() -> None:
    parsed = parse_encoder_help(data_text("help_encoder/hevc_nvenc.stdout.txt"))
    assert parsed is not None
    assert parsed.presets == ["slow", "medium", "fast", "p1", "p2", "p3", "p4", "p5", "p6", "p7"]
    assert {"preset", "tune", "rc", "cq", "spatial-aq", "b_ref_mode"} <= set(parsed.private_options)
    assert "p010le" in parsed.pix_fmts


def test_help_of_libsvtav1_lists_the_preset_range() -> None:
    parsed = parse_encoder_help(data_text("help_encoder/libsvtav1.stdout.txt"))
    assert parsed is not None
    assert parsed.presets == [str(n) for n in range(-2, 14)]
    assert parsed.pix_fmts == ["yuv420p", "yuv420p10le"]


def test_help_of_amf_and_qsv_presets() -> None:
    amf = parse_encoder_help(data_text("help_encoder/hevc_amf.stdout.txt"))
    qsv = parse_encoder_help(data_text("help_encoder/hevc_qsv.stdout.txt"))
    assert amf is not None
    assert qsv is not None
    assert amf.presets == ["quality", "balanced", "speed", "high_quality"]
    assert qsv.presets == ["veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"]


def test_help_of_vaapi_has_hardware_frames_only() -> None:
    parsed = parse_encoder_help(data_text("help_encoder/hevc_vaapi.stdout.txt"))
    assert parsed is not None
    assert parsed.pix_fmts == ["vaapi"]
    assert parsed.presets == []
    assert {"rc_mode", "qp", "profile", "tier", "level", "sei"} <= set(parsed.private_options)


def test_help_of_an_audio_encoder() -> None:
    parsed = parse_encoder_help(data_text("help_encoder/aac.stdout.txt"))
    assert parsed is not None
    assert parsed.private_options == [
        "aac_coder",
        "aac_ms",
        "aac_is",
        "aac_pns",
        "aac_tns",
        "aac_pce",
    ]
    assert parsed.pix_fmts == []


def test_help_of_an_unknown_encoder_is_none() -> None:
    assert parse_encoder_help(data_text("help_encoder_unknown.stdout.txt")) is None
    assert parse_encoder_help("") is None
    assert parse_encoder_help("something else\n") is None


def test_large_integer_preset_ranges_are_not_listed() -> None:
    text = (
        "Encoder x [x]:\n    Supported pixel formats: yuv420p\nx AVOptions:\n"
        "  -preset            <int>        E..V....... speed (from 0 to 1000) (default 5)\n"
    )
    parsed = parse_encoder_help(text)
    assert parsed is not None
    assert parsed.presets == []
    assert parsed.private_options == ["preset"]
