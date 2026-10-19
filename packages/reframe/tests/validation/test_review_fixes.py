"""Validation regression tests for output paths, fixes and some edge cases."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path, PurePath, PureWindowsPath
from types import ModuleType
from typing import Any

import pytest

from reframe.command import build_plan
from reframe.models import (
    AverageBitrate,
    ChapterSettings,
    CropRect,
    CropSettings,
    EncoderState,
    EncoderStatus,
    FieldOrder,
    FilterConfig,
    FilterSettings,
    ReplaceOp,
    Severity,
    SourceRef,
    SubtitleOutputTrack,
)
from reframe.validation import LocalFileSystem
from reframe.validation.output import output_path_issues, source_clash, written_paths


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
MKV = sc.DEFS.containers["mkv"]
W = PureWindowsPath


def codes(issues: list[Any]) -> list[str]:
    return [i.code for i in issues]


def errors(issues: list[Any]) -> list[str]:
    return [i.code for i in issues if i.severity is Severity.ERROR]


def path_issues(path: PurePath, source: PurePath, fs: Any) -> list[Any]:
    return output_path_issues(path, source, fs, container=MKV, collision="auto_rename")


def test_the_partial_file_is_the_source() -> None:
    """The builder would write ``Foo.part.mkv`` (the source), and the queue would remove it."""
    source = Path("/media/Foo.part.mkv")
    fs = sc.FakeFs(files=[source], dirs=[Path("/media")])
    [issue] = path_issues(Path("/media/Foo.mkv"), source, fs)
    assert (issue.code, issue.severity) == ("output.same_as_source", Severity.ERROR)
    assert "Foo.part.mkv" in issue.message
    [fix] = issue.fixes
    [op] = fix.patch
    assert isinstance(op, ReplaceOp)
    assert isinstance(op.value, str)
    assert source_clash(Path(op.value), source, fs) is None
    assert path_issues(Path(op.value), source, fs) == []


@pytest.mark.parametrize(
    "source_name", ["Foo.part.chapters.txt", "Foo.part.passlog", "Foo.part.passlog-0.log"]
)
def test_plan_and_statistics_files_are_the_source(source_name: str) -> None:
    source = Path("/media") / source_name
    fs = sc.FakeFs(files=[source], dirs=[Path("/media")])
    assert codes(path_issues(Path("/media/Foo.mkv"), source, fs)) == ["output.same_as_source"]


def test_written_paths_are_the_builders() -> None:
    s = sc.base()
    s.job.video.encoder = "libx265"
    s.job.video.rate_control = AverageBitrate(kbps=2000, two_pass=True)
    s.job.chapters = ChapterSettings(generate_every=60.0)
    plan = build_plan(s.job, s.source, s.caps, s.tools)
    planned = {plan.output_final, plan.output_tmp, *(f.path for f in plan.files), *plan.temp_files}
    assert planned <= set(written_paths(Path(str(s.job.output.path))))


def test_windows_spelling_of_the_partial_file() -> None:
    source = W("C:\\Videos\\FOO.PART.MKV")
    fs = sc.FakeFs(files=[source], dirs=[W("C:\\Videos")], case_insensitive=True)
    assert codes(path_issues(W("c:\\videos\\foo.mkv"), source, fs)) == ["output.same_as_source"]


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
@pytest.mark.parametrize("source_name", ["Foo.mkv", "Foo.part.mkv"])
def test_output_folder_linked_to_the_source_folder(tmp_path: Path, source_name: str) -> None:
    """The output folder is a symlink to the source's folder (a string compare misses it);
    the real file system finds the same file."""
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    os.symlink(real, link)
    source = real / source_name
    source.write_bytes(b"x")
    issues = path_issues(link / "Foo.mkv", source, LocalFileSystem())
    assert errors(issues) == ["output.same_as_source"]


def test_switch_container_changes_the_extension() -> None:
    s = sc.base()
    s.job.output.container = "mp4"
    s.job.output.path = Path("/out/Movie (2019).mp4")
    s.job.subtitles = [SubtitleOutputTrack(source=4, action="copy")]  # PGS
    issues = sc.check(s)
    [issue] = [i for i in issues if i.code == "subtitle.bitmap_unsupported"]
    [switch] = [f for f in issue.fixes if f.label == f"Switch to {MKV.label}"]
    switched = s.apply(switch)
    assert switched.job.output.path == Path("/out/Movie (2019).mkv")
    assert "output.extension_mismatch" not in codes(switched.validate())


def test_switch_container_keeps_every_track_valid() -> None:
    """WebM holds neither x265 nor the subtitles, so the fixes offer only MKV."""
    s = sc.base()
    s.job.output.container = "avi"
    [issue] = [i for i in sc.check(s) if i.code == "container.unknown"]
    assert [f.label for f in issue.fixes] == [f"Switch to {MKV.label}"]


def test_encode_the_video_picks_an_encoder_the_container_holds() -> None:
    s = sc.base()
    s.job.video.passthrough = True
    s.job.output.container = "webm"
    s.job.output.path = Path("/out/Movie (2019).webm")
    s.job.audio = s.job.audio[:1]
    s.job.audio[0].encoder = "libopus"
    s.job.subtitles = []
    [issue] = [i for i in sc.check(s) if i.code == "container.codec_unsupported"]
    encode = next(f for f in issue.fixes if f.label.startswith("Encode the video"))
    after = s.apply(encode).validate()
    assert errors(after) == []


def test_closest_match_respects_detected_10bit() -> None:
    states: dict[str, EncoderState | EncoderStatus] = {
        "hevc_nvenc": EncoderState.UNAVAILABLE,
    }
    for encoder_id in sc.DEFS.video_encoders:
        if encoder_id != "hevc_nvenc":
            states[encoder_id] = EncoderStatus(
                id=encoder_id,
                state=EncoderState.AVAILABLE,
                in_build=True,
                supports_10bit=False,
                reason_10bit="10-bit is not supported by this GPU",
            )
    s = sc.base()
    s.caps = sc.make_caps(states)
    s.job.video.encoder = "hevc_nvenc"
    s.job.video.bit_depth = 10
    [issue] = [i for i in sc.check(s) if i.code == "encoder.unavailable"]
    after = s.apply(issue.fixes[0]).validate()
    assert "encoder.no_10bit" not in codes(after)


def test_burn_it_in_is_not_offered_next_to_another_burn_in() -> None:
    s = sc.base()
    pgs = sc.make_source().subtitles[1].index
    s.source = sc.make_source()
    s.job.subtitles = [
        SubtitleOutputTrack(source=3, action="burn"),
        SubtitleOutputTrack(source=pgs, action="convert", convert_to="srt"),
    ]
    [issue] = [i for i in sc.check(s) if i.code == "subtitle.convert_bitmap"]
    assert "Burn it in" not in [f.label for f in issue.fixes]


def test_reserved_name_is_an_error_for_a_windows_path() -> None:
    fs = sc.FakeFs(files=[W("C:\\Videos\\Movie.mkv")], dirs=[W("C:\\Out")], case_insensitive=True)
    issues = path_issues(W("C:\\Out\\con.mkv"), W("C:\\Videos\\Movie.mkv"), fs)
    [issue] = [i for i in issues if i.code == "output.name_not_portable"]
    assert issue.severity is Severity.ERROR
    assert issue.fixes[0].label == "Save as con_.mkv"


def test_too_long_name_counts_the_partial_suffix() -> None:
    s = sc.base()
    s.job.output.path = Path("/out") / ("é" * 124 + ".mkv")  # 252 bytes; .part.mkv: 257
    [issue] = [i for i in sc.check(s) if i.code == "output.name_too_long"]
    assert "partial file name" in issue.message
    s.job.output.path = Path("/out") / ("é" * 123 + ".mkv")  # .part.mkv: 255 bytes
    assert "output.name_too_long" not in codes(sc.check(s))


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
    assert code in codes(issues)
    assert "validation.rule_failed" not in codes(issues)


def test_deinterlaced_crop_is_on_the_frame_grid() -> None:
    """An interlaced 4:2:0 source: a 2-line crop is off the field grid (4 lines) but on the
    frame grid, which the builder uses when it deinterlaces."""
    s = sc.base()
    s.source.video[0].field_order = FieldOrder.TOP_FIRST
    s.job.dimensions.crop = CropSettings(mode="manual", rect=CropRect(top=2, bottom=2))
    assert "dimensions.crop_snapped" in codes(s.validate())
    s.job.filters = FilterSettings({"deinterlace": FilterConfig()})
    assert "dimensions.crop_snapped" not in codes(sc.check(s))
    plan = build_plan(s.job, s.source, s.caps, s.tools)
    argv = [str(a) for step in plan.steps for a in step.argv]
    assert any("crop=1920:1076:0:2" in a for a in argv), argv


def test_source_ref_is_used_for_the_clash() -> None:
    s = sc.base()
    s.job.source = SourceRef(path=Path("/out/Movie (2019).part.mkv"))
    s.fs.add_file(Path("/out/Movie (2019).part.mkv"))
    assert "output.same_as_source" in errors(s.validate())
