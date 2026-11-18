"""``validate_template``: what a preset alone can be checked for."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from reframe.definitions import convert_quality
from reframe.jsonpatch import apply_patch
from reframe.models import (
    AudioCodecRule,
    AudioOutputSettings,
    ConstantQuality,
    EncoderState,
    EncoderStatus,
    ExtraAudioOutput,
    FilterConfig,
    FilterSettings,
    NamingOptions,
    OutputTrackRule,
    Preset,
    Severity,
    TrackSelector,
    VideoSettings,
)
from reframe.models.issues import ValidationIssue
from reframe.validation import TEMPLATE_RULES, TemplateContext, validate_template
from reframe.validation.common import error, fix, replace
from reframe.validation.registry import Rule

from . import scenario as sc
from .scenario import Case, Mod, both

ERR, WARN, INFO = Severity.ERROR, Severity.WARNING, Severity.INFO


def preset(**video: Any) -> Preset:
    return Preset(
        id="h265-nvenc-1080p",
        name="H.265 NVENC 1080p",
        category="Hardware",
        video=VideoSettings(**({"encoder": "libx265"} | video)),
    )


def base() -> Any:
    return sc.TemplateScenario(template=preset())


def build(mod: Mod) -> Any:
    scenario = base()
    mod(scenario)
    return scenario


def video(**changes: Any) -> Mod:
    def mod(s: Any) -> None:
        for key, value in changes.items():
            setattr(s.template.video, key, value)

    return mod


def caps(states: dict[str, Any], **kw: Any) -> Mod:
    def mod(s: Any) -> None:
        s.caps = sc.make_caps(states, **kw)

    return mod


def container(value: str) -> Mod:
    def mod(s: Any) -> None:
        s.template.output.container = value

    return mod


def webm_video(s: Any) -> None:
    s.template.output.container = "webm"
    s.template.video.encoder = "libsvtav1"
    s.template.audio_defaults.passthru.fallback_encoder = "libopus"


def rule(**changes: Any) -> Mod:
    def mod(s: Any) -> None:
        s.template.audio_defaults.codec_rules = [AudioCodecRule(**changes)]

    return mod


def rules(*items: AudioCodecRule) -> Mod:
    def mod(s: Any) -> None:
        s.template.audio_defaults.codec_rules = list(items)

    return mod


HU_ANY = AudioCodecRule(languages=["hu"], codec="aac", max_bitrate=160)
HU_51 = AudioCodecRule(
    languages=["hu"], source_channels="5.1_or_more", codec="ac3", mixdown="5.1", max_bitrate=448
)
CATCH_ALL = AudioCodecRule(codec="aac", mixdown="up_to_5.1", max_bitrate=256)


def nothing(s: Any) -> None:
    del s


NO_HEVC_HARDWARE: dict[str, EncoderState | EncoderStatus] = {
    "hevc_nvenc": EncoderStatus(
        id="hevc_nvenc",
        state=EncoderState.UNAVAILABLE,
        hardware=True,
        in_build=True,
        reason="NVIDIA driver not found",
    ),
    "hevc_qsv": EncoderState.UNAVAILABLE,
    "hevc_amf": EncoderState.UNAVAILABLE,
    "hevc_vaapi": EncoderState.UNAVAILABLE,
}

CASES: list[Case] = [
    Case(
        "video encoder unavailable",
        "encoder.unavailable",
        "video.encoder",
        ERR,
        both(video(encoder="hevc_nvenc"), caps(NO_HEVC_HARDWARE)),
        video(encoder="hevc_nvenc"),
    ),
    Case(
        "unknown video encoder",
        "encoder.unknown",
        "video.encoder",
        ERR,
        video(encoder="libx999"),
        nothing,
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
        "10-bit",
        "encoder.no_10bit",
        "video.bit_depth",
        ERR,
        video(encoder="h264_qsv", bit_depth=10),
        video(bit_depth=10),
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
        "quality out of range",
        "encoder.quality_out_of_range",
        "video.rate_control.value",
        ERR,
        video(rate_control=ConstantQuality(value=70)),
        video(rate_control=ConstantQuality()),
    ),
    Case(
        "video codec not in container",
        "container.codec_unsupported",
        "video.encoder",
        ERR,
        both(webm_video, video(encoder="libx265")),
        webm_video,
    ),
    Case(
        "codec rule encoder unavailable",
        "encoder.unavailable",
        "audio_defaults.codec_rules[0].codec",
        ERR,
        both(
            rule(codec="libfdk_aac", max_bitrate=256),
            caps({"libfdk_aac": EncoderState.UNAVAILABLE}),
        ),
        rule(codec="libfdk_aac", max_bitrate=256),
    ),
    Case(
        "codec rule codec not in container",
        "container.codec_unsupported",
        "audio_defaults.codec_rules[0].codec",
        ERR,
        webm_video,
        both(webm_video, rule(codec="libopus")),
    ),
    Case(
        "passthru rule",
        "container.codec_unsupported",
        "audio_defaults.codec_rules[0].codec",
        ERR,
        both(webm_video, rule(codec="ac3")),
        both(webm_video, rule(codec="passthru")),
    ),
    Case(
        "extra output unavailable",
        "encoder.unavailable",
        "audio_defaults.codec_rules[0].extras.extra_outputs[0].codec",
        ERR,
        both(
            lambda s: s.template.audio_defaults.codec_rules[0].extras.extra_outputs.append(
                ExtraAudioOutput(codec="libfdk_aac")
            ),
            caps({"libfdk_aac": EncoderState.ERROR}),
        ),
        lambda s: s.template.audio_defaults.codec_rules[0].extras.extra_outputs.append(
            ExtraAudioOutput(codec="ac3")
        ),
    ),
    Case(
        "fallback encoder not in container",
        "container.codec_unsupported",
        "audio_defaults.passthru.fallback_encoder",
        ERR,
        both(
            webm_video,
            rule(codec="libopus"),
            lambda s: setattr(s.template.audio_defaults.passthru, "fallback_encoder", "aac"),
        ),
        both(webm_video, rule(codec="libopus")),
    ),
    Case(
        "explicit audio rule",
        "encoder.unknown",
        "audio_rules[0].settings.encoder",
        ERR,
        lambda s: s.template.audio_rules.append(
            OutputTrackRule(
                selector=TrackSelector(kind="audio"), settings=AudioOutputSettings(encoder="aac_at")
            )
        ),
        lambda s: s.template.audio_rules.append(
            OutputTrackRule(
                selector=TrackSelector(kind="audio"), settings=AudioOutputSettings(encoder="aac")
            )
        ),
    ),
    Case(
        "unknown naming variable",
        "naming.unknown_variable",
        "naming.movie_template",
        ERR,
        lambda s: setattr(s.template, "naming", NamingOptions(movie_template="{titel}")),
        lambda s: setattr(s.template, "naming", NamingOptions(movie_template="{title}")),
    ),
    Case(
        "unknown variable in a tag",
        "naming.unknown_variable",
        "tags.title",
        ERR,
        lambda s: setattr(s.template.tags, "title", "{nme}"),
        lambda s: setattr(s.template.tags, "title", "{name}"),
    ),
    Case(
        "fixed output folder not chosen",
        "naming.no_output_folder",
        "naming.output_folder",
        WARN,
        lambda s: setattr(s.template, "naming", NamingOptions(output_folder_mode="fixed")),
        lambda s: setattr(
            s.template,
            "naming",
            NamingOptions(output_folder_mode="fixed", output_folder=Path("/out")),
        ),
    ),
    Case(
        "unknown filter preset",
        "filter.preset_unknown",
        "filters.denoise.preset",
        ERR,
        lambda s: setattr(
            s.template, "filters", FilterSettings({"denoise": FilterConfig(preset="default")})
        ),
        lambda s: setattr(
            s.template, "filters", FilterSettings({"denoise": FilterConfig(preset="light")})
        ),
    ),
    Case(
        "custom PAR missing",
        "dimensions.custom_par_missing",
        "dimensions.custom_par",
        ERR,
        lambda s: setattr(s.template.dimensions, "pixel_aspect", "custom"),
        nothing,
    ),
    # The defaults lint (reframe.batch.lint_defaults, wired in by validate_template).
    Case(
        "codec rule shadowed",
        "defaults.rule_shadowed",
        "audio_defaults.codec_rules[1]",
        WARN,
        rules(HU_ANY, HU_51, CATCH_ALL),
        rules(HU_51, HU_ANY, CATCH_ALL),
    ),
    Case(
        "codec rule unreachable",
        "defaults.rule_unreachable",
        "audio_defaults.codec_rules[0]",
        WARN,
        rules(HU_51.model_copy(update={"languages": []}), CATCH_ALL),
        rules(HU_51, CATCH_ALL),
    ),
    Case(
        "codec rule max bitrate snapped",
        "defaults.bitrate_snapped",
        "audio_defaults.codec_rules[0].max_bitrate",
        INFO,
        rule(codec="ac3", mixdown="5.1", max_bitrate=700),
        rule(codec="ac3", mixdown="5.1", max_bitrate=640),
    ),
    # The advanced-option rules need only the video settings.
    Case(
        "x265 amp without rectangular partitions",
        "encoder.option_inactive",
        "video.advanced.amp",
        WARN,
        video(preset="medium", advanced={"amp": True}),
        video(preset="medium", advanced={"amp": True, "rect": True}),
    ),
    Case(
        "x265 TU size above the CTU",
        "encoder.option_ignored",
        "video.advanced.max-tu-size",
        WARN,
        video(advanced={"ctu": "16", "max-tu-size": "32"}),
        video(advanced={"ctu": "16", "max-tu-size": "16"}),
    ),
    Case(
        "SVT-AV1 minimum QP above the maximum",
        "encoder.option_conflict",
        "video.advanced.min-qp",
        ERR,
        video(encoder="libsvtav1", advanced={"min-qp": 40, "max-qp": 20}),
        video(encoder="libsvtav1", advanced={"min-qp": 20, "max-qp": 40}),
    ),
    Case(
        "custom parameter names a file",
        "encoder.custom_param_file",
        "video.custom_params",
        ERR,
        video(custom_params="aq-mode=3:analysis-save=/home/u/x"),
        video(custom_params="aq-mode=3"),
    ),
    Case(
        "custom parameter overrides an option",
        "encoder.custom_param_overrides",
        "video.advanced.psy-rd",
        WARN,
        video(custom_params="psy-rd=0.75", advanced={"psy-rd": 1.5}),
        video(advanced={"psy-rd": 1.5}),
    ),
]


def test_a_codec_the_container_cannot_hold_is_reported_once() -> None:
    """The container rule reports it; the defaults lint does not."""
    issues = sc.check_template(build(webm_video))
    on_path = [i for i in issues if i.path == "audio_defaults.codec_rules[0].codec"]
    assert [i.code for i in on_path] == ["container.codec_unsupported"]
    assert not [i for i in issues if i.code == "defaults.codec_not_in_container"]


def test_clean_template_has_no_issues() -> None:
    assert base().validate() == []


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_positive(case: Case) -> None:
    issues = sc.check_template(build(case.positive))
    matching = [i for i in issues if i.code == case.code and i.path == case.path]
    assert matching, [(i.code, i.path) for i in issues]
    assert {i.severity for i in matching} == {case.severity}
    assert all(f.target == "template" for i in issues for f in i.fixes)


#: A negative of `nothing` is the clean template itself, so `test_clean_template_has_no_issues`
#: is the negative test of those codes and running `check_template` on it again would add nothing.
NEGATIVE_CASES = [c for c in CASES if c.negative is not nothing]


@pytest.mark.parametrize("case", NEGATIVE_CASES, ids=[c.id for c in NEGATIVE_CASES])
def test_negative(case: Case) -> None:
    issues = sc.check_template(build(case.negative))
    assert not sc.found(issues, case.code, case.path), issues


@pytest.mark.parametrize("registered", TEMPLATE_RULES, ids=[r.name for r in TEMPLATE_RULES])
def test_every_template_rule_has_a_positive_case(registered: Any, monkeypatch: Any) -> None:
    monkeypatch.setattr("reframe.validation.TEMPLATE_RULES", [registered])
    for case in CASES:
        scenario = build(case.positive)
        found = validate_template(
            scenario.template, scenario.caps, definitions=scenario.definitions
        )
        if any(i.code in registered.codes for i in found):
            return
    pytest.fail(f"no positive case for the template rule {registered.name}")


def test_an_unavailable_nvenc_preset_names_the_closest_encoder() -> None:
    template = preset(encoder="hevc_nvenc", rate_control=ConstantQuality(value=27), preset="p5")
    caps = sc.make_caps(NO_HEVC_HARDWARE)
    issues = validate_template(template, caps)

    assert [(i.severity, i.code, i.path) for i in issues] == [
        (ERR, "encoder.unavailable", "video.encoder")
    ]
    issue = issues[0]
    assert issue.message == (
        'Preset "H.265 NVENC 1080p" uses hevc_nvenc, which is not available: '
        "NVIDIA driver not found."
    )
    (fix,) = issue.fixes
    rf = convert_quality(27, "hevc_nvenc", "libx265")
    assert fix.label == f"Use libx265 (closest match; quality CQ 27 → RF {rf:g}, approximate)"
    assert fix.target == "template"
    patched = Preset.model_validate(apply_patch(template.model_dump(mode="json"), fix.patch))
    assert patched.video.encoder == "libx265"
    assert patched.video.rate_control == ConstantQuality(value=rf)
    assert patched.video.preset is None  # p5 is an NVENC preset
    assert validate_template(patched, caps) == []


def test_subject_names_the_template() -> None:
    template = preset(encoder="libx999")
    (issue,) = validate_template(template, sc.make_caps(), subject="Batch group 2")
    assert issue.message == "Batch group 2 uses the unknown encoder 'libx999'."


def test_template_fixes_target_the_template_but_settings_fixes_stay(monkeypatch: Any) -> None:
    def both_targets(ctx: TemplateContext) -> list[ValidationIssue]:
        return [
            error(
                "output.example",
                "output",
                "Example.",
                fix("Fix the preset", replace("output.path", None)),
                fix(
                    "Fix the settings", replace("output.collision", "overwrite"), target="settings"
                ),
            )
        ]

    rule = Rule("output", "both_targets", both_targets, ("output.example",))
    monkeypatch.setattr("reframe.validation.TEMPLATE_RULES", [rule])
    (issue,) = validate_template(preset(), sc.make_caps())
    assert [f.target for f in issue.fixes] == ["template", "settings"]
