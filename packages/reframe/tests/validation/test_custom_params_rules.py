"""Validation of custom encoder parameters: files they name, the allow-list of the encoders
without a params argument, and parameters that set an advanced option. Runs no FFmpeg."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from reframe.jsonpatch import apply_patch
from reframe.models import (
    ConstantQuality,
    EncoderState,
    EncoderStatus,
    JobSettings,
    OptionValue,
    Severity,
)
from reframe.presets import builtin_presets
from reframe.validation import validate_template
from reframe.validation import video as video_rules


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


def _issues(encoder: str, custom: str, **caps: EncoderStatus) -> list[tuple[str, str]]:
    s = sc.base()
    s.job.video.encoder = encoder
    if encoder == "libvpx-vp9":
        s.job.video.rate_control = ConstantQuality(value=30)
        s.job.video.preset = None
        s.job.video.tune = None
        s.job.video.profile = None
        s.job.video.level = None
    s.job.video.custom_params = custom
    if caps:
        s.caps = sc.make_caps(dict(caps))
    return [
        (i.code, i.message)
        for i in s.validate()
        if i.code.startswith("encoder.custom_param") and i.path == "video.custom_params"
    ]


@pytest.mark.parametrize(
    ("encoder", "custom"),
    [
        ("libx265", "analysis-save=/home/u/victim.txt"),
        ("libx265", "csv=/home/u/log.csv"),
        ("libx265", "--csv=/home/u/log.csv"),
        ("libx265", "analysis_save=/home/u/a.dat"),  # x265 reads '_' as '-'
        ("libx265", "nocsv=/home/u/x"),  # x265 reads it as csv=true: a file named "true"
        ("libx265", "'csv'=/home/u/x"),  # FFmpeg removes the quotes
        ("libx265", "c\\sv=/home/u/x"),  # and the escape
        ("libx265", "aq-mode=3:pass=1"),  # x265_2pass.log in the working folder
        ("libx265", "scaling-list=/home/u/list.txt"),
        ("libx265", "dhdr10-info=/home/u/meta.json"),
        ("libx264", "dump-yuv=/home/u/frames.yuv"),
        ("libx264", "stats=/home/u/x.log"),
        ("libx264", "nostats=/home/u/x.log"),  # x264 writes a file named "true" with pass=1
        ("libx264", "cqmfile=/home/u/cqm.txt"),
        # x264 reads every cqm value as a file name unless it contains
        # "flat" or "jvt" (case-sensitive), and a "no" prefix gives it "true" / "false".
        ("libx264", "cqm=/home/u/cqm.txt"),
        ("libx264", "cqm=FLAT"),
        ("libx264", "nocqm=flat"),
        # x265 compares the whole scaling-list value; FFmpeg keeps an escaped space.
        ("libx265", "scaling-list=default\\ :aq-mode=3"),
        ("libx265", "no-scaling-list=default"),
        ("libsvtav1", "fgs-table=/home/u/grain.tbl"),
        ("libvpx-vp9", "vstats_file=/home/u/v.log"),
        ("libvpx-vp9", "passlogfile=/home/u/p"),
        ("libvpx-vp9", "progress=/home/u/p.txt"),
        ("libvpx-vp9", "/filter=/home/u/graph.txt"),  # FFmpeg reads the value from the file
        ("h264_vaapi", "stats_enc_post=/home/u/s.txt"),
    ],
)
def test_a_parameter_that_names_a_file_is_an_error(encoder: str, custom: str) -> None:
    found = _issues(encoder, custom)
    assert [code for code, _ in found] == ["encoder.custom_param_file"], found
    assert "file" in found[0][1]


@pytest.mark.parametrize(
    ("encoder", "custom"),
    [
        ("libx265", "aq-mode=3:psy-rd=2.0:scaling-list=default"),
        ("libx265", "no-sao=1:nr-intra=100"),
        ("libx264", "nr=100:no-dct-decimate=1"),
        ("libx264", "cqm=flat"),  # x264's presets
        ("libx264", "cqm=jvt:nr=100"),
        ("libx264", "cqm='jvt '"),  # FFmpeg gives x264 "jvt ": the JVT matrix
        ("libsvtav1", "film-grain=8:enable-qm=1"),
        ("libvpx-vp9", "lag-in-frames=16:arnr-maxframes=7:g=120"),
        ("hevc_nvenc", "rc-lookahead=20:spatial-aq=1:init_qpB=20"),
        ("h264_vaapi", "quality=4"),
    ],
)
def test_ordinary_parameters_pass(encoder: str, custom: str) -> None:
    assert _issues(encoder, custom) == []


def test_an_encoder_without_a_params_argument_takes_only_its_options() -> None:
    """FFmpeg reads ``-<name>:v:0`` as any of its own options first: only the encoder's private
    options (this build's list when detection read it, else the recorded list) and the generic
    encoder options pass."""
    assert [c for c, _ in _issues("libvpx-vp9", "bogus=1")] == ["encoder.custom_param_unknown"]
    assert [c for c, _ in _issues("libvpx-vp9", "c=libx265")] == ["encoder.custom_param_unknown"]
    assert [c for c, _ in _issues("hevc_qsv", "qsv_params=a=1")] == ["encoder.custom_param_unknown"]
    # The build's own list (encoder detection) decides when it was read.
    status = EncoderStatus(
        id="libvpx-vp9", state=EncoderState.AVAILABLE, private_options=["new-option"]
    )
    assert _issues("libvpx-vp9", "new-option=1", **{"libvpx-vp9": status}) == []
    assert [c for c, _ in _issues("libvpx-vp9", "lag-in-frames=16", **{"libvpx-vp9": status})] == [
        "encoder.custom_param_unknown"
    ]


def test_each_refused_entry_has_a_fix_that_removes_only_it() -> None:
    s = sc.base()
    s.job.video.encoder = "libx265"
    s.job.video.custom_params = "aq-mode=3 :analysis-save=/home/u/x:psy-rd=2.0"
    issues = [i for i in sc.check(s) if i.code == "encoder.custom_param_file"]
    assert len(issues) == 1
    assert issues[0].severity is Severity.ERROR
    (fix,) = issues[0].fixes
    assert fix.label == "Remove analysis-save=/home/u/x from the custom parameters"
    fixed = JobSettings.model_validate(apply_patch(s.job.model_dump(mode="json"), fix.patch))
    assert fixed.video.custom_params == "aq-mode=3 :psy-rd=2.0"


def test_a_key_only_ffmpegs_split_finds_is_removed_with_all_parameters() -> None:
    """``a='1:csv=/x'`` is one pair for FFmpeg (not refused); ``'x':csv=/y`` has the key
    ``csv`` both ways; a quoted key that our split cannot attribute drops the whole text."""
    assert _issues("libx265", "aq-mode='1:csv=/x'") != []  # our split sees csv: refused anyway
    s = sc.base()
    s.job.video.encoder = "libx265"
    s.job.video.custom_params = "aq-mode=3:'c'sv=/home/u/x"
    issues = [i for i in s.validate() if i.code == "encoder.custom_param_file"]
    assert [f.label for i in issues for f in i.fixes] == [
        "Remove 'c'sv=/home/u/x from the custom parameters"
    ]


@pytest.mark.parametrize(
    ("encoder", "param"),
    [
        ("libx265", r"csv=C:\Users\u\log.csv"),
        ("libx265", r"csv='C:\Users\u\log.csv'"),
        ("libx264", "dump-yuv=D:/u/frames.yuv"),
        ("libvpx-vp9", r"vstats_file=C:\Users\u\v.log"),
    ],
)
def test_the_fix_removes_a_windows_path_with_its_parameter(encoder: str, param: str) -> None:
    """``C:\\x`` is split at the drive colon, by FFmpeg too: one issue, and its fix leaves no
    ``\\x`` behind."""
    s = sc.base()
    s.job.video.encoder = encoder
    s.job.video.preset = s.job.video.tune = s.job.video.profile = s.job.video.level = None
    if encoder == "libvpx-vp9":
        s.job.video.rate_control = ConstantQuality(value=30)
    s.job.video.custom_params = f"lag-in-frames=16:{param}:speed=2"
    [issue] = [i for i in s.validate() if i.path == "video.custom_params"]
    assert issue.code == "encoder.custom_param_file"
    [fix] = issue.fixes
    assert fix.label == f"Remove {param} from the custom parameters"
    assert s.apply(fix).job.video.custom_params == "lag-in-frames=16:speed=2"


def test_presets_get_the_check_too() -> None:
    template = next(p for p in builtin_presets() if p.video.encoder == "libx265")
    template = template.model_copy(deep=True)
    template.video.custom_params = "analysis-save=/home/u/victim.txt"
    issues = validate_template(template, sc.make_caps())
    found = [i for i in issues if i.code == "encoder.custom_param_file"]
    assert [(i.severity, i.path) for i in found] == [(Severity.ERROR, "video.custom_params")]
    assert all(f.target == "template" for i in found for f in i.fixes)


def test_no_built_in_preset_is_refused() -> None:
    for preset in builtin_presets():
        assert video_rules.video_custom_param_issues(preset.video, sc.make_caps(), sc.DEFS) == [], (
            preset.id
        )


OVERRIDES = "encoder.custom_param_overrides"


def _overrides(
    encoder: str, custom: str, advanced: dict[str, OptionValue] | None = None
) -> list[tuple[Severity, str, str]]:
    s = sc.base()
    s.job.video.encoder = encoder
    s.job.video.preset = None
    s.job.video.custom_params = custom
    s.job.video.advanced = advanced or {}
    return [(i.severity, i.path, i.message) for i in s.validate() if i.code == OVERRIDES]


def test_a_parameter_over_a_set_option_is_a_warning_with_both_values() -> None:
    s = sc.base()
    s.job.video.custom_params = "aq-mode=2:psy-rd=0.75"
    s.job.video.advanced = {"psy-rd": 1.5}
    [issue] = [i for i in s.validate() if i.path == "video.advanced.psy-rd"]
    assert (issue.code, issue.severity) == (OVERRIDES, Severity.WARNING)
    assert issue.message == (
        "The custom parameter psy-rd=0.75 sets Psy-RD strength (psy-rd): x265 uses it, not the "
        "1.5 set here."
    )
    (fix,) = issue.fixes
    assert fix.label == "Remove psy-rd=0.75 from the custom parameters"
    assert s.apply(fix).job.video.custom_params == "aq-mode=2"


def test_a_parameter_over_a_default_is_info() -> None:
    [(severity, path, message)] = _overrides("libx265", "aq-mode=1")
    assert (severity, path) == (Severity.INFO, "video.advanced.aq-mode")
    assert message == (
        "The custom parameter aq-mode=1 sets Adaptive quantisation (aq-mode): x265 uses it in "
        "place of the default."
    )


@pytest.mark.parametrize(
    ("encoder", "custom", "advanced", "expected"),
    [
        # x265 reads '_' as '-' and no-<key> as <key>=0
        ("libx265", "psy_rd=0.5:no-rect=1", {}, ["psy-rd", "rect"]),
        # one value fills both parts
        ("libx264", "deblock=-2,-2", {"deblock-alpha": 1}, ["deblock-alpha", "deblock-beta"]),
        ("libsvtav1", "keyint=10s", {}, ["keyint"]),
        # written -<name>:v:0 after the options: a private option and a generic one
        ("hevc_nvenc", "rc-lookahead=20:bf=2", {"rc-lookahead": 10}, ["rc-lookahead", "bf"]),
        ("libvpx-vp9", "g=120:lag-in-frames=16", {}, ["g", "lag-in-frames"]),
        ("libx265", "fades=1:ssim-rd=1", {}, []),
        ("hevc_nvenc", "init_qpB=20", {}, []),
    ],
)
def test_the_options_a_parameter_sets(
    encoder: str, custom: str, advanced: dict[str, OptionValue], expected: list[str]
) -> None:
    found = _overrides(encoder, custom, advanced)
    assert [path.removeprefix("video.advanced.") for _, path, _ in found] == expected
    for severity, path, _ in found:
        set_here = path.removeprefix("video.advanced.") in advanced
        assert severity is (Severity.WARNING if set_here else Severity.INFO)


def test_the_last_entry_is_the_one_named() -> None:
    [(_, _, message)] = _overrides("libx265", "psy-rd=1:psy-rd=0.75", {"psy-rd": 1.5})
    assert "psy-rd=0.75" in message


def test_a_copied_video_has_no_override() -> None:
    s = sc.base()
    s.job.video.passthrough = True
    s.job.video.custom_params = "psy-rd=0.75"
    assert not sc.found(s.validate(), OVERRIDES)


def test_presets_get_the_override_too() -> None:
    template = next(p for p in builtin_presets() if p.video.encoder == "libx265")
    template = template.model_copy(deep=True)
    template.video.custom_params = "psy-rd=0.75"
    template.video.advanced["psy-rd"] = 1.5
    issues = [i for i in validate_template(template, sc.make_caps()) if i.code == OVERRIDES]
    assert [(i.severity, i.path) for i in issues] == [(Severity.WARNING, "video.advanced.psy-rd")]
    assert [f.target for i in issues for f in i.fixes] == ["template"]
