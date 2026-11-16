"""The validation engine: rule order, failing rules, defaults, encoder switches and estimates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from reframe.dimensions import compute_geometry, source_geometry
from reframe.jsonpatch import apply_patch
from reframe.models import (
    AverageBitrate,
    BitrateSource,
    ChapterRange,
    ConstantQuality,
    CropRect,
    CropSettings,
    DimensionSettings,
    FieldOrder,
    FilterConfig,
    FilterSettings,
    FitWithin,
    FrameRange,
    JobSettings,
    NamingOptions,
    Rational,
    SameAsSource,
    TimeRange,
    ValidationIssue,
    VideoSettings,
    VideoStream,
)
from reframe.validation import (
    JOB_RULES,
    JobContext,
    estimate_output_bytes,
    switch_video_encoder,
    validate,
)
from reframe.validation.range import frame_count, range_duration
from reframe.validation.registry import AREAS, Rule, job_rule, ordered

from . import scenario as sc

DEFS = sc.DEFS


def context(scenario: Any) -> JobContext:
    return JobContext(
        job=scenario.job,
        source=scenario.source,
        caps=scenario.caps,
        tools=scenario.tools,
        fs=scenario.fs,
        settings=scenario.settings,
        definitions=scenario.definitions,
        naming=scenario.settings.output.naming,
    )


def test_rules_run_area_by_area() -> None:
    areas = [rule.area for rule in ordered(JOB_RULES)]
    assert areas == sorted(areas, key=AREAS.index)
    assert {rule.area for rule in JOB_RULES} == set(AREAS)


def test_issues_are_listed_in_area_order() -> None:
    s = sc.base()
    s.job.output.path = Path("/out/Movie.mp4")  # output (warning)
    s.job.video.encoder = "libx999"  # encoder (error)
    s.job.audio[0].source_stream = 9  # audio (error)
    issues = s.validate()
    assert [i.code for i in issues] == [
        "encoder.unknown",
        "audio.source_missing",
        "output.extension_mismatch",
    ]


def test_a_failing_rule_is_an_issue_not_an_exception() -> None:
    def broken(ctx: JobContext) -> list[ValidationIssue]:
        raise RuntimeError("boom")

    rule = Rule("output", "broken", broken, ())
    s = sc.base()
    issues = validate(s.job, s.source, s.caps, s.tools, s.fs, rules=[rule, *JOB_RULES])
    assert [(i.code, i.severity.value) for i in issues] == [("validation.rule_failed", "error")]
    assert "broken: RuntimeError: boom" in issues[0].message


def test_job_rule_decorator_registers(monkeypatch: Any) -> None:
    registered: list[Rule[JobContext]] = []
    monkeypatch.setattr("reframe.validation.registry.JOB_RULES", registered)

    @job_rule("range", "x.y")
    def example(ctx: JobContext) -> list[ValidationIssue]:
        return []

    assert [(r.area, r.name, r.codes) for r in registered] == [("range", "example", ("x.y",))]


def test_defaults_without_settings_and_definitions() -> None:
    s = sc.base()
    assert validate(s.job, s.source, s.caps, s.tools, s.fs) == []


def test_naming_options_override_settings() -> None:
    s = sc.base()
    s.naming = NamingOptions(movie_template="{titel}")
    assert sc.found(s.validate(), "naming.unknown_variable")


def test_source_without_video() -> None:
    s = sc.base()
    s.source.video = []
    s.source.container.duration = None
    s.job.dimensions = DimensionSettings(crop=CropSettings(mode="auto"))
    s.job.range = FrameRange(start=5)
    assert [i.code for i in sc.check(s)] == ["source.no_video"]  # and no rule fails
    assert context(s).output_size is None


def test_video_passthrough_skips_picture_rules() -> None:
    s = sc.base()
    s.job.video.passthrough = True
    s.job.video.encoder = "libx999"
    s.job.dimensions.crop = CropSettings(mode="auto")
    assert sc.check(s) == []
    assert context(s).output_size == (1920, 1080)


def switch(video: VideoSettings, new: str) -> VideoSettings:
    ops, _ = switch_video_encoder(video, new, DEFS)
    job = JobSettings(source=sc.make_source().ref, video=video)
    data = apply_patch(job.model_dump(mode="json"), ops)
    return JobSettings.model_validate(data).video


def test_switch_converts_quality_and_resets_what_the_new_encoder_lacks() -> None:
    video = VideoSettings(
        encoder="hevc_nvenc",
        rate_control=ConstantQuality(value=27),
        preset="p5",
        tune="uhq",
        profile="main10",
        bit_depth=10,
        advanced={"b_ref_mode": "each", "bf": 3},
    )
    _, note = switch_video_encoder(video, "libx265", DEFS)
    assert note is not None
    assert note.startswith("quality CQ 27 → RF ")
    new = switch(video, "libx265")
    assert (new.encoder, new.preset, new.tune, new.profile, new.bit_depth) == (
        "libx265",
        None,
        None,
        "main10",
        10,
    )
    assert new.advanced == {}


def test_switch_bitrate_mode() -> None:
    video = VideoSettings(
        encoder="h264_nvenc",
        rate_control=AverageBitrate(kbps=250_000, two_pass=True, turbo_first_pass=True),
        bit_depth=10,
        fast_decode=True,
    )
    new = switch(video, "h264_qsv")
    assert new.rate_control == AverageBitrate(kbps=200_000)
    assert new.bit_depth == 8
    assert new.fast_decode is False


def test_switch_to_an_encoder_without_the_mode() -> None:
    defs = DEFS.model_copy(deep=True)
    defs.video_encoders["libx265"].rate_control.quality = None
    defs.video_encoders["libx264"].rate_control.bitrate = None
    quality = VideoSettings(encoder="libx264", rate_control=ConstantQuality(value=20))
    ops, note = switch_video_encoder(quality, "libx265", defs)
    assert note is None
    assert ops[1].value == AverageBitrate().model_dump(mode="json")  # type: ignore[union-attr]
    bitrate = VideoSettings(encoder="libx265", rate_control=AverageBitrate())
    ops, _ = switch_video_encoder(bitrate, "libx264", defs)
    assert ops[1].value == {"mode": "quality", "value": 22.0}  # type: ignore[union-attr]


def test_switch_from_an_unknown_encoder_rounds_to_the_new_scale() -> None:
    video = VideoSettings(encoder="libx999", rate_control=ConstantQuality(value=70.04))
    assert switch(video, "libx265").rate_control == ConstantQuality(value=51.0)


def test_estimate_bitrate_mode() -> None:
    s = sc.base()
    s.job.video.rate_control = AverageBitrate(kbps=6000)
    # 6000 kb/s video + AAC 160 kb/s + the AAC passthru at 128 kb/s, 600 s, +2 %
    expected = int((6_000_000 + 160_000 + 128_000) * 600 / 8 * 1.02)
    assert estimate_output_bytes(context(s)) == expected
    s.job.audio[0].bitrate = None  # the encoder's default for stereo (160)
    assert estimate_output_bytes(context(s)) == expected
    s.job.audio[0].encoder = "flac"  # lossless: the source bitrate
    assert estimate_output_bytes(context(s)) == int(
        (6_000_000 + 640_000 + 128_000) * 600 / 8 * 1.02
    )


def test_estimate_passthrough_and_quality() -> None:
    s = sc.base()
    assert estimate_output_bytes(context(s)) is None  # constant quality: unknown
    s.job.video.passthrough = True
    s.job.range = TimeRange(start=0, end=60)
    assert estimate_output_bytes(context(s)) == int((8_000_000 + 160_000 + 128_000) * 60 / 8 * 1.02)
    s.source.video[0].bitrate.value = None
    s.source.video[0].bitrate.source = BitrateSource.UNKNOWN
    assert estimate_output_bytes(context(s)) == 6 * sc.GB // 10  # a tenth of the file
    s.source.container.size = None
    assert estimate_output_bytes(context(s)) is None


def test_range_duration_and_frames() -> None:
    s = sc.base()
    assert range_duration(context(s)) == 600.0
    s.job.range = ChapterRange(start=2, end=2)
    assert range_duration(context(s)) == 300.0
    s.job.range = ChapterRange(start=3, end=3)
    assert range_duration(context(s)) is None
    s.job.range = FrameRange(start=0, end=2400)
    assert range_duration(context(s)) == 2400 / (24000 / 1001)
    s.job.range = TimeRange(start=10)
    s.source.container.duration = None
    assert range_duration(context(s)) is None
    s.job.range = TimeRange(start=10, end=20)
    assert range_duration(context(s)) == 10.0
    s.source.video[0].frame_count = 1000
    assert frame_count(context(s)) == 1000
    s.job.range = FrameRange(start=0)
    assert range_duration(context(s)) == 1000 / (24000 / 1001)
    s.source.video[0].frame_rate = None
    s.source.video[0].avg_frame_rate = None
    assert range_duration(context(s)) is None
    s.source.video[0].frame_count = None
    assert frame_count(context(s)) is None


@settings(max_examples=300, deadline=None)
@given(
    width=st.integers(16, 4096),
    height=st.integers(16, 2304),
    sar=st.sampled_from([(1, 1), (32, 27), (8, 9), (4, 3)]),
    interlaced=st.booleans(),
    modulus=st.sampled_from([2, 4, 8, 16]),
    box=st.tuples(st.integers(16, 3840), st.integers(16, 2160)),
    crop=st.tuples(*(st.integers(0, 301) for _ in range(4))),
    size_mode=st.sampled_from(["fit", "source"]),
)
def test_no_odd_sizes(
    width: int,
    height: int,
    sar: tuple[int, int],
    interlaced: bool,
    modulus: int,
    box: tuple[int, int],
    crop: tuple[int, int, int, int],
    size_mode: str,
) -> None:
    """Output sizes are even, and the cropped size is on the chroma grid too."""
    stream = VideoStream(
        index=0,
        width=width,
        height=height,
        pix_fmt="yuv420p",
        sar=Rational(num=sar[0], den=sar[1]),
        field_order=FieldOrder.TOP_FIRST if interlaced else FieldOrder.PROGRESSIVE,
    )
    top, bottom, left, right = crop
    dims = DimensionSettings(
        crop=CropSettings(
            mode="manual", rect=CropRect(top=top, bottom=bottom, left=left, right=right)
        ),
        size=FitWithin(width=box[0], height=box[1]) if size_mode == "fit" else SameAsSource(),
        modulus=modulus,  # type: ignore[arg-type]
    )
    geometry = compute_geometry(source_geometry(stream), dims)
    assert geometry.scaled_width % 2 == 0
    assert geometry.scaled_height % 2 == 0
    applied = geometry.crop != CropRect()
    if applied:
        assert geometry.cropped_width % 2 == 0
        assert geometry.cropped_height % (4 if interlaced else 2) == 0


@pytest.mark.parametrize("where", ["advanced", "filter"])
def test_a_newline_in_a_key_is_an_issue_not_a_crash(where: str) -> None:
    s = sc.base()
    if where == "advanced":
        s.job.video.advanced = {"psy\nrd": 1.0}
        code = "encoder.option_unknown"
    else:
        s.job.filters = FilterSettings.model_construct({"de\nnoise": FilterConfig()})
        code = "filter.unknown"
    issues = sc.check(s)
    assert sc.found(issues, code)
    assert not sc.found(issues, "validation.rule_failed")
