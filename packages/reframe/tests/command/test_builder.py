"""``build_plan``: what it refuses, the argument order, steps, ranges and the display."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from reframe.command import PlanError, build_plan, partial_path
from reframe.command.builder import GLOBAL_ARGS, STEP_WEIGHTS
from reframe.models import (
    AudioOutputTrack,
    AverageBitrate,
    ChapterRange,
    EncodePlan,
    EncoderStatus,
    ExternalSubtitle,
    FrameRange,
    JobSettings,
    MediaSource,
    PlanStep,
    SubtitleOutputTrack,
    TimeRange,
    TrackMetadata,
    resolve_argv,
)

from .conftest import caps, draft, recorded, tools


def plan_of(job: JobSettings, source: MediaSource, **kwargs: Any) -> EncodePlan:
    return build_plan(job, source, kwargs.pop("caps", None) or caps(),
                      kwargs.pop("tools", None) or tools(), **kwargs)  # fmt: skip


def argv(step: PlanStep) -> list[str]:
    return [a for a in step.argv if isinstance(a, str)]


def output_options(plan: EncodePlan) -> list[str]:
    """The arguments between the last map and the codecs of the main step."""
    [main] = [s for s in plan.steps if s.kind in ("encode", "pass2")]
    args = argv(main)
    last_map = max(i for i, a in enumerate(args) if a == "-map") + 2
    return args[last_map : args.index("-c:v:0")]


def test_nothing_reaches_the_muxer_before_zero() -> None:
    """M2 review, finding M4: ``-ss 0`` as an output option when the video is encoded and a
    range starts after 0 or an external subtitle has a negative offset; the copied external
    track of a remux drops its own early events instead."""
    src = recorded("multitrack.mkv")
    ext = SubtitleOutputTrack(source=ExternalSubtitle(path=Path("/m/a.srt"), offset_ms=-700))
    job = draft(src, subtitles=False)
    assert "-ss" not in output_options(plan_of(job, src))
    job.range = TimeRange(start=1.2, end=3.7)
    assert output_options(plan_of(job, src))[:4] == ["-ss", "0", "-t", "2.5"]
    job.range = TimeRange()
    job.subtitles = [ext]
    assert output_options(plan_of(job, src))[:2] == ["-ss", "0"]
    job.subtitles = [ext.model_copy(update={"source": ExternalSubtitle(path=Path("/m/a.srt"))})]
    assert "-ss" not in output_options(plan_of(job, src))
    burn = ext.model_copy(update={"action": "burn"})  # filtered: the shift is in the filter
    job.subtitles = [burn]
    assert "-ss" not in output_options(plan_of(job, src))
    remux = draft(src, audio="passthru", subtitles=False)
    remux.video.passthrough = True
    remux.subtitles = [ext]
    plan = plan_of(remux, src)
    assert "-ss" not in output_options(plan)
    main = argv(plan.steps[0])
    assert main[main.index("-c:s:0") : main.index("-c:s:0") + 4] == [
        "-c:s:0", "copy", "-copypriorss:s:0", "0",
    ]  # fmt: skip
    remux.range = TimeRange(start=1.0)  # the copied video starts at the keyframe before 1 s
    ranged = argv(plan_of(remux, src).steps[0])
    assert "-copypriorss:s:0" not in ranged
    assert ranged.count("-ss") == 2  # the source and the subtitle file: input options only


def test_partial_path() -> None:
    assert partial_path(Path("/o/Movie.mkv")) == Path("/o/Movie.part.mkv")
    assert partial_path(Path("/o/Movie.mkv"), ".chapters.txt") == Path("/o/Movie.part.chapters.txt")
    assert partial_path(Path("/o/Show S01.E01.m4v")) == Path("/o/Show S01.E01.part.m4v")
    assert partial_path(Path("/o/noext")) == Path("/o/noext.part")


# --------------------------------------------------------------------------- refusals


def test_refusals() -> None:
    src = recorded("multitrack.mkv")

    def refuses(match: str, **change: Any) -> None:
        job = draft(src, video={"encoder": "libx264"})
        for key, value in change.items():
            target, _, attr = key.partition("__")
            setattr(getattr(job, target) if attr else job, attr or target, value)
        with pytest.raises(PlanError, match=match):
            plan_of(job, change.pop("_source", src))

    refuses("output path is not set", output__path=None)
    refuses("unknown container", output__container="avi")
    refuses("unknown video encoder", video__encoder="libx266")
    refuses("H.264 cannot be written into WebM", output__container="webm")
    refuses("no 10-bit mode", video__encoder="h264_amf", video__bit_depth=10)
    refuses("no audio stream 9", audio=[AudioOutputTrack(source_stream=9)])
    refuses("no audio stream None", audio=[AudioOutputTrack()])
    refuses("range is empty", range=TimeRange(start=2.0, end=1.0))
    job = draft(src)
    with pytest.raises(PlanError, match="no video stream"):
        plan_of(job, src.model_copy(update={"video": []}))
    job = draft(src, container="webm", audio="passthru")
    job.video.passthrough = True
    with pytest.raises(PlanError, match="h264 video cannot be copied into WebM"):
        plan_of(job, src)
    no_rate = src.model_copy(deep=True)
    no_rate.video[0].frame_rate = None
    no_rate.video[0].avg_frame_rate = None
    job = draft(src)
    job.range = FrameRange(start=1, end=5)
    with pytest.raises(PlanError, match="frame rate"):
        plan_of(job, no_rate)


# --------------------------------------------------------------------------- order and steps


def test_argument_order() -> None:
    src = recorded("chapters.mkv")
    job = draft(src, video={"encoder": "hevc_vaapi"}, container="mp4",
                output_settings={"web_optimized": True})  # fmt: skip
    job.range = TimeRange(start=1.0, end=3.0)
    job.chapters.names = ["One", "Two", "Three", "Four"]
    job.subtitles = [SubtitleOutputTrack(source=ExternalSubtitle(path=Path("/m/x.srt")))]
    plan = plan_of(job, src)
    a = argv(plan.steps[0])
    assert a[: len(GLOBAL_ARGS)] == list(GLOBAL_ARGS)
    order = [
        a.index("-init_hw_device"),
        a.index("-ss"),
        a.index(str(src.ref.path)),
        a.index("/m/x.srt"),
        a.index("ffmetadata"),
        a.index("-map"),
        a.index("-t"),
        a.index("-filter:v:0"),
        a.index("-c:v:0"),
        a.index("-c:s:0"),
        a.index("-map_metadata:s"),
        a.index("-map_chapters"),
        a.index("-map_metadata"),
        a.index("-movflags"),
        a.index("-f", a.index("-movflags")),
    ]
    assert order == sorted(order)
    assert a[-1] == str(plan.output_tmp)


def test_two_pass_with_loudnorm_steps_and_weights() -> None:
    src = recorded("multitrack.mkv")
    job = draft(src, video={"encoder": "libx265",
                            "rate_control": AverageBitrate(kbps=1000, two_pass=True)})  # fmt: skip
    job.audio[0].loudness = "ebu_r128"
    job.audio[1].metadata = TrackMetadata(language="pt-BR")
    plan = plan_of(job, src)
    assert [s.kind for s in plan.steps] == ["analyse", "pass1", "pass2", "mkvpropedit", "finalize"]
    assert [s.progress_weight for s in plan.steps] == [
        STEP_WEIGHTS[k] for k in ("analyse", "pass1", "pass2", "mkvpropedit", "finalize")
    ]
    analyse, pass1, pass2, edit, final = plan.steps
    assert analyse.measures[0].id == "a0"
    assert analyse.description == "Measure the loudness of audio track 1 (Japanese 5.1)"
    assert argv(pass1)[-3:] == ["-f", "null", "-"]
    assert "-map_chapters" not in argv(pass1)
    values = {f"a0.{k}": "-20.0" for k in ("input_i", "input_tp", "input_lra", "input_thresh")}
    values["a0.target_offset"] = "0.5"
    resolved = resolve_argv(pass2.argv, values)
    assert any("measured_I=-20.0" in arg for arg in resolved)
    assert edit.tool == "mkvpropedit"
    assert argv(edit) == [str(plan.output_tmp), "--edit", "track:a2", "--set", "language=pt-BR"]
    assert final.tool is None
    assert final.description == "Rename multitrack.part.mkv to multitrack.mkv"
    assert "<a0.input_i>" in plan.display
    assert plan.display.count(" && ") == 4
    assert plan.temp_files[0] == Path("/out/multitrack.part.passlog")


def test_no_mkvpropedit_step_without_the_tool_or_for_webm() -> None:
    src = recorded("multitrack.mkv")
    job = draft(src)
    job.audio[0].metadata = TrackMetadata(language="pt-BR")
    assert "mkvpropedit" not in [
        s.kind for s in plan_of(job, src, tools=tools(mkvpropedit=False)).steps
    ]
    webm = draft(src, container="webm", audio_encoder="libopus", video={"encoder": "libsvtav1"})
    webm.audio[0].metadata = TrackMetadata(language="pt-BR")
    assert "mkvpropedit" not in [s.kind for s in plan_of(webm, src).steps]


def test_strict_is_written_once() -> None:
    src = recorded("truehd-atmos")
    job = draft(src, container="mp4", audio="passthru")
    job.audio.append(job.audio[0].model_copy())
    a = argv(plan_of(job, src).steps[0])
    assert a.count("-strict") == 1


def test_vaapi_device_default_and_from_the_status() -> None:
    src = recorded("multitrack.mkv")
    job = draft(src, video={"encoder": "h264_vaapi"})
    no_device = caps()
    no_device.encoders["h264_vaapi"] = EncoderStatus(id="h264_vaapi")
    assert "vaapi=va:/dev/dri/renderD128" in argv(plan_of(job, src, caps=no_device).steps[0])
    other = caps(devices={"h264_vaapi": "/dev/dri/renderD130"})
    assert "vaapi=va:/dev/dri/renderD130" in argv(plan_of(job, src, caps=other).steps[0])


def test_attachments_only_with_a_copied_ass_track_in_matroska() -> None:
    src = recorded("ass-fonts")
    job = draft(src, video={"encoder": "libx264"})
    assert "0:t?" in argv(plan_of(job, src).steps[0])
    job.subtitles = []
    assert "0:t?" not in argv(plan_of(job, src).steps[0])
    mp4 = draft(src, container="mp4", video={"encoder": "libx264"})
    assert "0:t?" not in argv(plan_of(mp4, src).steps[0])


# --------------------------------------------------------------------------- ranges


def test_ranges() -> None:
    src = recorded("multitrack.mkv")
    job = draft(src)
    job.range = TimeRange(start=1.0, end=99.0)
    plan = plan_of(job, src)
    assert plan.expected_duration == pytest.approx(3.021)
    assert "-t" not in argv(plan.steps[0])
    job.range = TimeRange(start=0.0, end=2.5)
    plan = plan_of(job, src)
    assert "-ss" not in argv(plan.steps[0])
    assert plan.expected_duration == 2.5
    job.range = FrameRange(start=25)
    assert plan_of(job, src).expected_duration == pytest.approx(3.021)
    # A chapter range that ends after the last chapter ends with it (decision 0026).
    chapters = recorded("chapters.mkv")  # 4 chapters; the last is 4.0 to 5.0 s, the file 5.021
    clamped = draft(chapters)
    clamped.range = ChapterRange(start=4, end=5)
    plan = plan_of(clamped, chapters)
    assert plan.expected_duration == 1.0
    assert " -ss 4 -i " in plan.display
    assert " -t 1 " in plan.display
    clamped.range = ChapterRange(start=2, end=99)
    assert plan_of(clamped, chapters).expected_duration == 4.0
    unknown = src.model_copy(deep=True)
    unknown.container.duration = None
    unknown.video[0].duration = None
    job.range = TimeRange(start=1.0)
    assert plan_of(job, unknown).expected_duration == 0.0
