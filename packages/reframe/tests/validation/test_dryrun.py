"""The dry run without FFmpeg: the custom-parameter split, the reduced job and command, and the
reading of FFmpeg's log (recorded texts of FFmpeg n9.0.2: x264 core 165, x265 4.3, SVT-AV1
v4.2.0, libvpx 1.17; ``test_dryrun_ffmpeg.py`` runs them for real)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from reframe.jsonpatch import apply_patch
from reframe.models import (
    AverageBitrate,
    CapabilitySnapshot,
    ChapterSettings,
    JobSettings,
    MediaSource,
    Severity,
    SourceRef,
    ToolInfo,
    ToolSet,
    ToolStatus,
    VideoSettings,
)
from reframe.validation.dryrun import (
    DRY_RUN_CODES,
    dry_run,
    dry_run_argv,
    dry_run_job,
    failure_detail,
    parse_dry_run,
    split_custom_params,
)

pytestmark = pytest.mark.anyio


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


def _job(**video: object) -> JobSettings:
    return JobSettings(
        source=SourceRef(path=Path("/media/in.mkv")),
        video=VideoSettings.model_validate({"encoder": "libx265", **video}),
    )


def _codes(issues: list) -> list[tuple[str, str, Severity]]:  # type: ignore[type-arg]
    return [(i.code, i.path, i.severity) for i in issues]


# --------------------------------------------------------------------------- custom params


def test_split_custom_params_keeps_the_typed_text() -> None:
    params = split_custom_params(" ref=4 :bogus:path=C\\:/x::")
    assert [(p.name, p.value) for p in params] == [("ref", "4"), ("bogus", "1"), ("path", "C:/x")]
    assert [p.raw for p in params] == ["ref=4 ", "bogus", "path=C\\:/x"]
    assert split_custom_params("") == []


# --------------------------------------------------------------------------- the job


def test_the_dry_run_job_is_video_only() -> None:
    job = _job(rate_control=AverageBitrate(kbps=3000, two_pass=True))
    job.chapters = ChapterSettings(names=["A"], generate_every=5)
    job.output.web_optimized = True
    probe = dry_run_job(job)
    assert probe.audio == []
    assert probe.subtitles == []
    assert not probe.chapters.enabled
    assert probe.chapters.names is None
    assert not probe.output.web_optimized
    assert isinstance(probe.video.rate_control, AverageBitrate)
    assert not probe.video.rate_control.two_pass
    assert probe.output.path == Path("dry-run.mkv")
    # The job itself is unchanged.
    assert isinstance(job.video.rate_control, AverageBitrate)
    assert job.video.rate_control.two_pass
    assert job.output.path is None


# --------------------------------------------------------------------------- the log


@pytest.mark.parametrize(
    ("stderr", "name"),
    [
        ("[libx264 @ 0x55aa] Error parsing option 'bogus = 1'.", "bogus"),
        ("[libx265 @ 0x55aa] Unknown option: bogus.", "bogus"),
        ("[libx265 @ 0x55aa] Invalid value for bogus: foo.", "bogus"),
        ("[libsvtav1 @ 0x55aa] Error parsing option bogus: 1.", "bogus"),
        ("Unrecognized option 'bogus:v:0'.\nError splitting the argument list", "bogus"),
        ("[libvpx-vp9 @ 0x55aa] Error setting option bogus to value abc.", "bogus"),
    ],
)
def test_a_refused_custom_parameter(stderr: str, name: str) -> None:
    job = _job(custom_params="ref=3:bogus=1:me=1")
    issues = parse_dry_run(job, stderr, 0)
    assert _codes(issues) == [
        ("encoder.custom_param_rejected", "video.custom_params", Severity.ERROR)
    ]
    assert f"'{name}" in issues[0].message
    patched = apply_patch(job.model_dump(mode="json"), issues[0].fixes[0].patch)
    assert patched["video"]["custom_params"] == "ref=3:me=1"


def test_a_refused_advanced_option_by_its_cli_name() -> None:
    job = _job(encoder="hevc_nvenc", advanced={"b_ref_mode": "each"})
    stderr = "[hevc_nvenc @ 0x1] Error setting option b_ref_mode to value each."
    issues = parse_dry_run(job, stderr, 234)
    assert _codes(issues) == [
        ("encoder.option_rejected", "video.advanced.b_ref_mode", Severity.ERROR)
    ]
    patched = apply_patch(job.model_dump(mode="json"), issues[0].fixes[0].patch)
    assert patched["video"]["advanced"] == {}


def test_an_unknown_name_points_at_the_custom_parameters() -> None:
    issues = parse_dry_run(_job(custom_params="a=1"), "Unknown option: zzz.", 0)
    assert _codes(issues) == [("encoder.dry_run_failed", "video.custom_params", Severity.ERROR)]


def test_an_encoder_warning_that_names_a_parameter() -> None:
    stderr = (
        "x265 [warning]: limit-tu disabled, requires tu-inter-depth > 1\n"
        "x265 [warning]: Source height < 720p; disabling lookahead-slices\n"
    )
    issues = parse_dry_run(_job(custom_params="limit-tu=4"), stderr, 0)
    assert _codes(issues) == [("encoder.dry_run_warning", "video.custom_params", Severity.WARNING)]
    assert "limit-tu disabled" in issues[0].message
    # A warning about something the job did not set is not an issue.
    assert parse_dry_run(_job(custom_params="ref=3"), stderr, 0) == []


def test_a_failed_start_with_the_encoders_own_message() -> None:
    stderr = (
        "x265 [error]: min CU size must be less than or equal to max CU size\n"
        "[libx265 @ 0x5] Cannot open libx265 encoder.\n"
        "[vost#0:0/libx265 @ 0x6] Error while opening encoder - maybe incorrect parameters\n"
        "Conversion failed!\n"
    )
    job = _job(custom_params="ctu=16:min-cu-size=32")
    issues = parse_dry_run(job, stderr, 183)
    # "min CU size" names the custom parameter min-cu-size: its fix removes it.
    assert _codes(issues) == [
        ("encoder.custom_param_rejected", "video.custom_params", Severity.ERROR)
    ]
    assert issues[0].message.endswith("min CU size must be less than or equal to max CU size")
    patched = apply_patch(job.model_dump(mode="json"), issues[0].fixes[0].patch)
    assert patched["video"]["custom_params"] == "ctu=16"
    # Nothing to name: the error points at the custom parameters, without a fix.
    other = parse_dry_run(_job(custom_params="ref=3"), stderr, 183)
    assert _codes(other) == [("encoder.dry_run_failed", "video.custom_params", Severity.ERROR)]
    assert other[0].fixes == []


def test_a_failed_start_that_names_an_option() -> None:
    stderr = "Svt[error]: Hierarchical Levels supported: [0-5]\n"
    job = _job(encoder="libsvtav1", advanced={"hierarchical-levels": "5"})
    issues = parse_dry_run(job, stderr, 234)
    assert _codes(issues) == [
        ("encoder.option_rejected", "video.advanced.hierarchical-levels", Severity.ERROR)
    ]


def test_exit_code_zero_without_output_is_a_failure() -> None:
    """av1_amf with a bad ``-align`` (RX 7600): "Resolution incorrect for alignment mode",
    "Could not open encoder before EOF", and FFmpeg still exits with 0."""
    stderr = (
        "[av1_amf @ 0x1] Resolution incorrect for alignment mode\n"
        "[vost#0:0/av1_amf @ 0x2] [enc:av1_amf @ 0x3] Could not open encoder before EOF\n"
        "[out#0/null @ 0x4] Nothing was written into output file\n"
    )
    issues = parse_dry_run(_job(encoder="av1_amf"), stderr, 0)
    assert _codes(issues) == [("encoder.dry_run_failed", "video.encoder", Severity.ERROR)]
    assert "Resolution incorrect for alignment mode" in issues[0].message


def test_libvpx_failure_detail_has_the_additional_information() -> None:
    stderr = (
        "[libvpx-vp9 @ 0x1] v1.17.0\n"
        "[libvpx-vp9 @ 0x1] Failed to initialize encoder: Invalid parameter\n"
        "[libvpx-vp9 @ 0x1]   Additional information: g_lag_in_frames out of range\n"
    )
    assert failure_detail(stderr, "libvpx-vp9") == (
        "Failed to initialize encoder: Invalid parameter (g_lag_in_frames out of range)"
    )
    assert failure_detail("", "libx264") is None
    assert failure_detail("something odd\n", "libx264") == "something odd"


def test_a_clean_run_has_no_issues() -> None:
    assert parse_dry_run(_job(custom_params="ref=3"), "frame=1 fps=0.0\n", 0) == []
    issues = parse_dry_run(_job(), "", 1)
    assert _codes(issues) == [("encoder.dry_run_failed", "video.encoder", Severity.ERROR)]
    assert issues[0].message.endswith("exit code 1")
    assert {code for code, _, _ in _codes(issues)} <= set(DRY_RUN_CODES)


# --------------------------------------------------------------------------- without FFmpeg


def _tools(status: ToolStatus, path: Path | None = None) -> ToolSet:
    def info(name: str) -> ToolInfo:
        return ToolInfo.model_validate({"name": name, "status": status, "path": path})

    return ToolSet(
        ffmpeg=info("ffmpeg"),
        ffprobe=info("ffprobe"),
        mkvpropedit=info("mkvpropedit"),
        mediainfo=info("mediainfo"),
    )


def _source() -> MediaSource:
    source: MediaSource = sc.make_source()
    return source


async def test_without_ffmpeg_the_dry_run_is_skipped() -> None:
    issues = await dry_run(_job(), _source(), CapabilitySnapshot(), _tools(ToolStatus.MISSING))
    assert _codes(issues) == [("encoder.dry_run_skipped", "video.encoder", Severity.WARNING)]


async def test_passthrough_has_nothing_to_test() -> None:
    job = _job(passthrough=True)
    found = _tools(ToolStatus.FOUND, Path("/usr/bin/ffmpeg"))
    assert await dry_run(job, _source(), CapabilitySnapshot(), found) == []


async def test_a_job_that_cannot_be_planned() -> None:
    found = _tools(ToolStatus.FOUND, Path("/usr/bin/ffmpeg"))
    issues = await dry_run(_job(encoder="nope"), _source(), CapabilitySnapshot(), found)
    assert _codes(issues) == [("encoder.dry_run_failed", "video.encoder", Severity.ERROR)]


def test_the_command_ends_with_one_frame_to_null() -> None:
    found = _tools(ToolStatus.FOUND, Path("/usr/bin/ffmpeg"))
    job = _job(custom_params="ref=3")
    job.output.path = Path("/out/x.mkv")
    argv = dry_run_argv(job, _source(), CapabilitySnapshot(), found)
    assert argv[-5:] == ["-frames:v", "1", "-f", "null", "-"]
    assert "/out/x.part.mkv" not in argv
    assert argv[argv.index("-x265-params:v:0") + 1] == "ref=3"
    assert "-map_chapters" in argv
    assert argv[argv.index("-map_chapters") + 1] == "-1"
